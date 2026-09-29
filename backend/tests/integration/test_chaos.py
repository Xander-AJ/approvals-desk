"""Chaos: SIGKILL-equivalent crash after the sandbox accepted the refund but before the run recorded it.
After recovery there must be exactly ONE refund in the ledger and the proposal must be executed."""
import os
import socket
import subprocess
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import select

from app.agent.fake_llm import FakeLLM
from app.api.main import create_app
from app.auth import mint_token
from app.config import Settings
from app.db.models import Proposal, Tenant, TenantPolicy
from app.db.session import tenant_session
from app.domain.state_machine import ProposalState
from app.services.runs import Runtime
from app.services.sandbox_client import HttpSandbox
from app.services.store import apply_transition

pytestmark = pytest.mark.asyncio(loop_scope="session")
ROOT = Path(__file__).resolve().parents[3]
SB_KEY = "chaos-test-sandbox-key-0123456789abcdef"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


async def test_kill_between_approval_and_execution_yields_exactly_one_refund(engines, pg, tmp_path) -> None:  # type: ignore[no-untyped-def]
    owner, app_engine = engines
    port = _free_port()
    sb_url = f"http://127.0.0.1:{port}"
    env = {**os.environ, "SANDBOX_DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path}/sb.db",
           "PYTHONPATH": f"{ROOT / 'sandbox'}:{ROOT / 'backend'}", "SANDBOX_API_KEY": SB_KEY}
    sandbox = subprocess.Popen([sys.executable, "-m", "uvicorn", "pesa.main:app", "--port", str(port)],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        async with httpx.AsyncClient(base_url=sb_url, headers={"X-Sandbox-Key": SB_KEY}) as sb:
            for _ in range(50):
                try:
                    if (await sb.get("/ledger")).status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.2)
            await sb.post("/dev/seed", json={"account_id": "cust1", "balance": "0", "txns": [
                {"id": "c1", "amount": "1200"}, {"id": "c2", "amount": "1200"}]})

            host, mapped = pg.get_container_host_ip(), pg.get_exposed_port(5432)
            ckpt_dsn = f"postgresql://{pg.username}:{pg.password}@{host}:{mapped}/{pg.dbname}"
            app_url = f"postgresql+asyncpg://app_user:app_user@{host}:{mapped}/{pg.dbname}"
            settings = Settings(database_url=app_url, checkpoint_dsn=ckpt_dsn, sandbox_url=sb_url, sandbox_api_key=SB_KEY)

            tenant = uuid.uuid4()
            async with owner.begin() as c:
                await c.execute(Tenant.__table__.insert().values(id=tenant, name="chaos"))
            async with tenant_session(app_engine, tenant) as s:
                s.add(TenantPolicy(tenant_id=tenant, auto_approve_max=Decimal("500"), hard_limit=Decimal("50000"),
                                   max_auto_risk=30, allowed_actions=["refund"], sla_minutes=60))

            # 1. customer message -> proposal pending review (durable checkpoint in Postgres)
            async with AsyncPostgresSaver.from_conn_string(ckpt_dsn) as saver:
                await saver.setup()
                rt = Runtime(app_engine, FakeLLM(), HttpSandbox(httpx.AsyncClient(base_url=sb_url, headers={"X-Sandbox-Key": SB_KEY})), saver)
                api = create_app(settings, rt)
                client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://api")
                tok = {"Authorization": f"Bearer {mint_token(settings, 'a', tenant, 'agent')}"}
                r = await client.post("/tickets", json={"customer_ref": "cust1", "message": "nimekatwa mara mbili KES 1,200"}, headers=tok)
                pid = uuid.UUID(r.json()["proposal_id"])
                assert r.json()["decision"] == "review"

            # 2. human approval is committed, but the process dies before the run continues
            async with tenant_session(app_engine, tenant) as s:
                p = (await s.execute(select(Proposal).where(Proposal.id == pid))).scalar_one()
                apply_transition(s, p, ProposalState.APPROVED, "reviewer@x")

            # 3. worker crashes right after the sandbox accepted the refund
            crash = subprocess.run([sys.executable, "-m", "app.worker_cli"], cwd=ROOT / "backend",
                                   env={**env, "AD_DATABASE_URL": app_url, "AD_CHECKPOINT_DSN": ckpt_dsn,
                                        "AD_SANDBOX_URL": sb_url, "AD_SANDBOX_API_KEY": SB_KEY, "CRASH_AFTER_MUTATE": "1"},
                                   capture_output=True, timeout=120)
            assert crash.returncode == 137, crash.stderr.decode()[-2000:]
            assert len((await sb.get("/ledger")).json()) == 1  # money moved once...
            async with tenant_session(app_engine, tenant) as s:
                assert (await s.get(Proposal, pid)).state == "approved"  # type: ignore[union-attr]  # ...but not recorded

            # 4. restarted worker recovers from the checkpointer
            ok = subprocess.run([sys.executable, "-m", "app.worker_cli"], cwd=ROOT / "backend",
                                env={**env, "AD_DATABASE_URL": app_url, "AD_CHECKPOINT_DSN": ckpt_dsn,
                                     "AD_SANDBOX_URL": sb_url, "AD_SANDBOX_API_KEY": SB_KEY},
                                capture_output=True, timeout=120)
            assert ok.returncode == 0, ok.stderr.decode()[-2000:]
            ledger = (await sb.get("/ledger")).json()
            assert len(ledger) == 1, ledger  # exactly one refund
            async with tenant_session(app_engine, tenant) as s:
                assert (await s.get(Proposal, pid)).state == "executed"  # type: ignore[union-attr]
    finally:
        sandbox.kill()
