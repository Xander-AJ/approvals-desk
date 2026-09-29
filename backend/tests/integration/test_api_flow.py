import sys
import uuid
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from langgraph.checkpoint.memory import MemorySaver

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "sandbox"))
from pesa.app import Base as SandboxBase  # noqa: E402
from pesa.app import create_app as create_sandbox

from app.agent.fake_llm import FakeLLM  # noqa: E402
from app.api.main import create_app  # noqa: E402
from app.auth import mint_token  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db.models import TenantPolicy  # noqa: E402
from app.db.session import tenant_session  # noqa: E402
from app.services.runs import Runtime  # noqa: E402
from app.services.sandbox_client import HttpSandbox  # noqa: E402

pytestmark = pytest.mark.asyncio(loop_scope="session")
SETTINGS = Settings()


@pytest_asyncio.fixture(loop_scope="session")
async def env(engines, tmp_path):  # type: ignore[no-untyped-def]
    _, app_engine = engines
    sb_app = create_sandbox(f"sqlite+aiosqlite:///{tmp_path}/sb.db")
    async with sb_app.state.engine.begin() as c:
        await c.run_sync(SandboxBase.metadata.create_all)
    sb_http = httpx.AsyncClient(transport=httpx.ASGITransport(app=sb_app), base_url="http://sb")
    txns = [{"id": "c1", "amount": "1200"}, {"id": "c2", "amount": "1200"}, {"id": "c3", "amount": "200"}]
    await sb_http.post("/dev/seed", json={"account_id": "cust1", "balance": "0", "txns": txns})
    rt = Runtime(app_engine, FakeLLM(), HttpSandbox(sb_http), MemorySaver())
    api = create_app(SETTINGS, rt)
    tenant, other = uuid.uuid4(), uuid.uuid4()
    for t in (tenant, other):
        async with tenant_session(app_engine, t) as s:
            s.add(TenantPolicy(tenant_id=t, auto_approve_max=Decimal("500"), hard_limit=Decimal("50000"),
                               max_auto_risk=30, allowed_actions=["refund", "reversal", "fee_waiver"], sla_minutes=60))
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=api), base_url="http://api")

    def h(t: uuid.UUID, role: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {mint_token(SETTINGS, f'{role}@x', t, role)}"}

    async def ledger() -> list[dict]:  # type: ignore[type-arg]
        return (await sb_http.get("/ledger")).json()  # type: ignore[no-any-return]

    return client, tenant, other, h, ledger


async def _ticket(env, msg: str):  # type: ignore[no-untyped-def]
    client, tenant, _, h, _ = env
    r = await client.post("/tickets", json={"customer_ref": "cust1", "message": msg}, headers=h(tenant, "agent"))
    assert r.status_code == 200, r.text
    return r.json()


async def test_review_approve_executes_exactly_once_and_double_approve_409(env) -> None:  # type: ignore[no-untyped-def]
    client, tenant, _, h, ledger = env
    before = len(await ledger())
    t = await _ticket(env, "nimekatwa mara mbili KES 1,200")
    assert t["decision"] == "review"
    pid = t["proposal_id"]
    assert len(await ledger()) == before  # nothing before approval
    r = await client.post(f"/proposals/{pid}/approve", headers=h(tenant, "reviewer"))
    assert r.status_code == 200, r.text
    assert len(await ledger()) == before + 1
    d = (await client.get(f"/proposals/{pid}", headers=h(tenant, "reviewer"))).json()
    assert d["state"] == "executed"
    assert [a["event"] for a in d["audit"]] == ["proposed", "pending_review", "approved", "executed"]
    r2 = await client.post(f"/proposals/{pid}/approve", headers=h(tenant, "reviewer"))
    assert r2.status_code == 409
    assert len(await ledger()) == before + 1


async def test_small_low_risk_auto_approves(env) -> None:  # type: ignore[no-untyped-def]
    _, _, _, _, ledger = env
    before = len(await ledger())
    t = await _ticket(env, "charged twice KES 200")  # single 200 charge -> risk 45 -> review
    assert t["decision"] == "review"
    assert len(await ledger()) == before


async def test_edit_changes_amount_and_bumps_version(env) -> None:  # type: ignore[no-untyped-def]
    client, tenant, _, h, ledger = env
    t = await _ticket(env, "nimekatwa mara mbili KES 1,200")
    pid = t["proposal_id"]
    r = await client.post(f"/proposals/{pid}/edit", json={"amount": "900"}, headers=h(tenant, "reviewer"))
    assert r.status_code == 200, r.text
    d = (await client.get(f"/proposals/{pid}", headers=h(tenant, "reviewer"))).json()
    assert d["version"] == 2 and d["amount"] == "900.00" and d["original"]["amount"] == "1200.00"
    assert (await ledger())[-1]["amount"] == "900.00"


async def test_reject_never_executes_and_edit_over_hard_limit_422(env) -> None:  # type: ignore[no-untyped-def]
    client, tenant, _, h, ledger = env
    t = await _ticket(env, "nimekatwa mara mbili KES 1,200")
    before = len(await ledger())
    assert (await client.post(f"/proposals/{t['proposal_id']}/edit", json={"amount": "999999"},
                              headers=h(tenant, "reviewer"))).status_code == 422
    assert (await client.post(f"/proposals/{t['proposal_id']}/reject", headers=h(tenant, "reviewer"))).status_code == 200
    assert len(await ledger()) == before


async def test_rbac_and_tenant_isolation(env) -> None:  # type: ignore[no-untyped-def]
    client, tenant, other, h, _ = env
    t = await _ticket(env, "nimekatwa mara mbili KES 1,200")
    pid = t["proposal_id"]
    assert (await client.post(f"/proposals/{pid}/approve", headers=h(tenant, "agent"))).status_code == 403
    assert (await client.get(f"/proposals/{pid}", headers=h(other, "reviewer"))).status_code == 404
    assert (await client.post(f"/proposals/{pid}/approve", headers=h(other, "reviewer"))).status_code == 404
    assert (await client.get("/proposals")).status_code == 401


async def test_declined_money_request_is_escalated_and_visible_to_reviewers(env) -> None:  # type: ignore[no-untyped-def]
    client, tenant, other, h, ledger = env
    before = len(await ledger())
    r = await client.post("/tickets", json={"customer_ref": "nobody", "message": "nimekatwa mara mbili"},
                          headers=h(tenant, "agent"))
    assert r.status_code == 200, r.text
    assert r.json()["decision"] == "escalated" and r.json()["proposal_id"] is None
    assert len(await ledger()) == before
    esc = (await client.get("/tickets?needs_human=true", headers=h(tenant, "reviewer"))).json()
    assert any(t["message"] == "nimekatwa mara mbili" for t in esc)
    assert (await client.get("/tickets?needs_human=true", headers=h(other, "reviewer"))).json() == []
