import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
import pytest_asyncio
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import select, update

from app.agent.fake_llm import FakeLLM
from app.api.main import create_app
from app.auth import mint_token
from app.config import Settings
from app.db.models import OutboxEvent, Proposal, Tenant, TenantPolicy, Ticket
from app.db.session import tenant_session
from app.services.runs import Runtime
from app.worker import dispatch_outbox, expire_stale, sign

pytestmark = pytest.mark.asyncio(loop_scope="session")


class StubSandbox:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.fail_context = False
        self.fail_mutate = False

    async def get_context(self, account_id: str) -> dict[str, Any]:
        if self.fail_context:
            raise httpx.ConnectError("sandbox unreachable")
        return {"transactions": [{"id": f"t{i}", "amount": "1200", "kind": "charge"} for i in range(2)]}

    async def mutate(self, action_type: str, account_id: str, amount: Decimal, key: str) -> dict[str, Any]:
        await asyncio.sleep(0.05)  # widen the race window for the concurrency test
        if self.fail_mutate:
            raise httpx.ConnectError("sandbox unreachable")
        self.calls.append(key)
        return {"txn_id": f"r{len(self.calls)}"}


@pytest_asyncio.fixture(loop_scope="session")
async def world(engines):  # type: ignore[no-untyped-def]
    owner, app_engine = engines
    tenant = uuid.uuid4()
    async with owner.begin() as c:
        await c.execute(Tenant.__table__.insert().values(id=tenant, name="w"))
    async with tenant_session(app_engine, tenant) as s:
        s.add(TenantPolicy(tenant_id=tenant, auto_approve_max=Decimal("500"), hard_limit=Decimal("50000"),
                           max_auto_risk=30, allowed_actions=["refund"], sla_minutes=60))
    sb = StubSandbox()
    settings = Settings(webhook_url="http://hook/x", webhook_secret="s3cret")
    rt = Runtime(app_engine, FakeLLM(), sb, MemorySaver())
    api = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(settings, rt)), base_url="http://api")

    def h(role: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {mint_token(settings, role, tenant, role)}"}

    async def new_proposal() -> str:
        r = await api.post("/tickets", json={"customer_ref": "c", "message": "nimekatwa mara mbili KES 1,200"},
                           headers=h("agent"))
        assert r.status_code == 200, r.text
        return str(r.json()["proposal_id"])

    return {"rt": rt, "api": api, "tenant": tenant, "h": h, "sb": sb, "settings": settings,
            "engine": app_engine, "new": new_proposal}


async def test_sla_expiry_expires_pending_and_never_executes(world) -> None:  # type: ignore[no-untyped-def]
    pid = uuid.UUID(await world["new"]())
    async with tenant_session(world["engine"], world["tenant"]) as s:
        await s.execute(update(Proposal).where(Proposal.id == pid)
                        .values(expires_at=datetime.now(UTC) - timedelta(minutes=1)))
    calls_before = len(world["sb"].calls)
    assert await expire_stale(world["rt"]) >= 1
    d = (await world["api"].get(f"/proposals/{pid}", headers=world["h"]("reviewer"))).json()
    assert d["state"] == "expired"
    assert len(world["sb"].calls) == calls_before
    # a late approval on an expired proposal is a 409, and still executes nothing
    r = await world["api"].post(f"/proposals/{pid}/approve", headers=world["h"]("reviewer"))
    assert r.status_code == 409 and len(world["sb"].calls) == calls_before
    async with tenant_session(world["engine"], world["tenant"]) as s:
        assert (await s.execute(select(OutboxEvent).where(OutboxEvent.topic == "proposal.expired"))).first()
        t = (await s.execute(select(Ticket).where(Ticket.id == d["ticket_id"]))).scalar_one()
        assert t.reply  # the customer is told, run finished


async def test_concurrent_approvals_execute_once(world) -> None:  # type: ignore[no-untyped-def]
    pid = await world["new"]()
    before = len(world["sb"].calls)
    rs = await asyncio.gather(*[world["api"].post(f"/proposals/{pid}/approve", headers=world["h"]("reviewer"))
                                for _ in range(4)])
    codes = sorted(r.status_code for r in rs)
    assert codes == [200, 409, 409, 409], codes
    assert len(world["sb"].calls) == before + 1


async def test_outbox_delivery_signed_retried_and_deduplicable(world) -> None:  # type: ignore[no-untyped-def]
    rt, settings = world["rt"], world["settings"]
    async with tenant_session(world["engine"], world["tenant"]) as s:
        await s.execute(update(OutboxEvent).values(delivered_at=datetime.now(UTC)))  # drain earlier events
        ev = OutboxEvent(tenant_id=world["tenant"], topic="proposal.executed", payload={"proposal_id": "p"})
        s.add(ev)
        await s.flush()
        ev_id = str(ev.id)
    seen: list[httpx.Request] = []
    fail = {"on": True}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(500 if fail["on"] else 200)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    await dispatch_outbox(rt, settings, http)  # receiver down: nothing may be marked delivered
    async with tenant_session(world["engine"], world["tenant"]) as s:
        row = await s.get(OutboxEvent, uuid.UUID(ev_id))
        assert row.delivered_at is None and row.attempts == 1  # type: ignore[union-attr]
    fail["on"] = False
    await dispatch_outbox(rt, settings, http)
    await dispatch_outbox(rt, settings, http)  # already delivered: must not be sent a third time
    mine = [r for r in seen if r.headers["X-Event-Id"] == ev_id]
    assert len(mine) == 2  # one failed attempt + one success; same id on retry -> receiver can dedupe
    async with tenant_session(world["engine"], world["tenant"]) as s:
        assert (await s.get(OutboxEvent, uuid.UUID(ev_id))).delivered_at is not None  # type: ignore[union-attr]
    req = mine[-1]
    assert req.headers["X-Signature"] == sign("s3cret", req.content)
    assert json.loads(req.content)["topic"] == "proposal.executed"


async def test_metrics_reflect_edit_reject_and_latency(world) -> None:  # type: ignore[no-untyped-def]
    api, h = world["api"], world["h"]
    edited, rejected = await world["new"](), await world["new"]()
    assert (await api.post(f"/proposals/{edited}/edit", json={"amount": "1000"}, headers=h("reviewer"))).status_code == 200
    assert (await api.post(f"/proposals/{rejected}/reject", headers=h("reviewer"))).status_code == 200
    m = (await api.get("/metrics", headers=h("reviewer"))).json()
    assert m["total"] >= 2 and 0 < m["override_rate"] <= 1
    assert m["avg_approval_latency_s"] is not None and m["avg_approval_latency_s"] >= 0


async def test_agent_failure_escalates_to_a_human_instead_of_a_500(world) -> None:  # type: ignore[no-untyped-def]
    world["sb"].fail_context = True
    try:
        r = await world["api"].post("/tickets", json={"customer_ref": "c", "message": "nimekatwa mara mbili KES 1,200"},
                                    headers=world["h"]("agent"))
    finally:
        world["sb"].fail_context = False
    assert r.status_code == 200, r.text
    assert r.json()["decision"] == "escalated" and r.json()["proposal_id"] is None
    esc = (await world["api"].get("/tickets?needs_human=true", headers=world["h"]("reviewer"))).json()
    assert any(t["id"] == r.json()["ticket_id"] for t in esc)


async def test_execution_failure_marks_failed_emits_event_and_is_terminal(world) -> None:  # type: ignore[no-untyped-def]
    pid = await world["new"]()
    calls = len(world["sb"].calls)
    world["sb"].fail_mutate = True
    try:
        r = await world["api"].post(f"/proposals/{pid}/approve", headers=world["h"]("reviewer"))
    finally:
        world["sb"].fail_mutate = False
    assert r.status_code == 200, r.text
    d = (await world["api"].get(f"/proposals/{pid}", headers=world["h"]("reviewer"))).json()
    assert d["state"] == "failed" and "error" in d["result"]
    assert [a["event"] for a in d["audit"]][-2:] == ["approved", "failed"]
    assert len(world["sb"].calls) == calls  # nothing moved
    async with tenant_session(world["engine"], world["tenant"]) as s:
        ev = (await s.execute(select(OutboxEvent).where(OutboxEvent.topic == "proposal.failed"))).scalars().all()
        assert any(e.payload["proposal_id"] == pid for e in ev)
    # failed is terminal: a second approve cannot re-run the money movement
    assert (await world["api"].post(f"/proposals/{pid}/approve", headers=world["h"]("reviewer"))).status_code == 409
