import asyncio
import json
import time
import uuid
from decimal import Decimal
from urllib.parse import urlencode

import httpx
import pytest
import pytest_asyncio
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import select

from app.agent.fake_llm import FakeLLM
from app.api.main import create_app
from app.auth import mint_token
from app.config import Settings
from app.db.models import AuditEvent, Proposal, Tenant, TenantPolicy
from app.db.session import tenant_session
from app.integrations import slack
from app.services.runs import Runtime
from app.worker import dispatch_outbox
from tests.integration.test_worker_and_concurrency import StubSandbox

pytestmark = pytest.mark.asyncio(loop_scope="session")
SECRET = "slack-signing-secret-for-tests"
HOOK = "https://hooks.slack.com/services/T000/B000/XXXXXXXX1234"


@pytest_asyncio.fixture(loop_scope="session")
async def world(engines):  # type: ignore[no-untyped-def]
    owner, app_engine = engines
    ta, tb = uuid.uuid4(), uuid.uuid4()
    for t in (ta, tb):
        async with owner.begin() as c:
            await c.execute(Tenant.__table__.insert().values(id=t, name=str(t)))
        async with tenant_session(app_engine, t) as s:
            s.add(TenantPolicy(tenant_id=t, auto_approve_max=Decimal("500"), hard_limit=Decimal("50000"),
                               max_auto_risk=30, allowed_actions=["refund", "reversal", "fee_waiver"], sla_minutes=60))
    sb = StubSandbox()
    settings = Settings(slack_signing_secret=SECRET, console_url="https://console.test")
    slack_posts: list[tuple[str, dict]] = []  # type: ignore[type-arg]
    hits: list[str] = []
    fail = {"on": False}

    def handler(req: httpx.Request) -> httpx.Response:
        hits.append(str(req.url))
        if fail["on"]:
            return httpx.Response(500)
        slack_posts.append((str(req.url), json.loads(req.content)))
        return httpx.Response(200, text="ok")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    rt = Runtime(app_engine, FakeLLM(), sb, MemorySaver())
    api = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(settings, rt, http=http)), base_url="http://api")

    def h(tenant: uuid.UUID, role: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {mint_token(settings, role, tenant, role)}"}

    async def proposal(tenant: uuid.UUID = ta) -> str:
        r = await api.post("/tickets", json={"customer_ref": "c", "message": "nimekatwa mara mbili KES 1,200"},
                           headers=h(tenant, "agent"))
        assert r.status_code == 200, r.text
        return str(r.json()["proposal_id"])

    async def map_user(tenant: uuid.UUID, slack_id: str, role: str = "reviewer") -> None:
        r = await api.post("/integrations/slack/identities", json={"slack_user_id": slack_id, "role": role, "label": slack_id},
                           headers=h(tenant, "admin"))
        assert r.status_code == 200, r.text

    async def click(action: str, tenant: uuid.UUID, pid: str, user: str, *, secret: str = SECRET, ts: int | None = None,
                    response_url: str = "https://hooks.slack.com/actions/T000/1/abc", value: str | None = None,
                    sign_body: bool = True) -> httpx.Response:
        payload = {"type": "block_actions", "user": {"id": user}, "response_url": response_url,
                   "actions": [{"action_id": f"proposal_{action}",
                                "value": value or slack.ButtonValue(action, tenant, uuid.UUID(pid)).encode()}]}
        body = urlencode({"payload": json.dumps(payload)}).encode()
        stamp = str(ts if ts is not None else int(time.time()))
        sig = slack.sign(secret, stamp, body if sign_body else b"other")
        return await api.post("/integrations/slack/interactions", content=body, headers={
            "X-Slack-Request-Timestamp": stamp, "X-Slack-Signature": sig,
            "Content-Type": "application/x-www-form-urlencoded"})

    async def state(pid: str, tenant: uuid.UUID = ta) -> str:
        async with tenant_session(app_engine, tenant) as s:
            return (await s.get(Proposal, uuid.UUID(pid))).state  # type: ignore[union-attr,no-any-return]

    async def audit(pid: str, tenant: uuid.UUID = ta) -> list[tuple[str, str]]:
        async with tenant_session(app_engine, tenant) as s:
            rows = (await s.execute(select(AuditEvent).where(AuditEvent.proposal_id == uuid.UUID(pid))
                                    .order_by(AuditEvent.created_at))).scalars()
            return [(r.event, r.actor) for r in rows]

    return dict(api=api, ta=ta, tb=tb, h=h, sb=sb, rt=rt, settings=settings, posts=slack_posts, hits=hits, fail=fail,
                proposal=proposal, map_user=map_user, click=click, state=state, audit=audit, http=http)


async def test_admin_config_is_admin_only_validated_and_never_echoes_the_url(world) -> None:  # type: ignore[no-untyped-def]
    api, ta, h = world["api"], world["ta"], world["h"]
    body = {"webhook_url": HOOK, "channel_label": "#refunds"}
    assert (await api.put("/integrations/slack", json=body, headers=h(ta, "reviewer"))).status_code == 403
    assert (await api.get("/integrations", headers=h(ta, "agent"))).status_code == 403
    for bad in ("https://evil.example/hooks.slack.com", "http://hooks.slack.com/services/x", "https://169.254.169.254/x"):
        r = await api.put("/integrations/slack", json={"webhook_url": bad}, headers=h(ta, "admin"))
        assert r.status_code == 422, bad
    assert (await api.put("/integrations/slack", json=body, headers=h(ta, "admin"))).status_code == 200
    got = await api.get("/integrations", headers=h(ta, "admin"))
    assert got.json()["slack"] == {"configured": True, "webhook_hint": "…1234", "channel_label": "#refunds",
                                   "interactions_enabled": True}
    assert "XXXXXXXX" not in got.text and "hooks.slack.com" not in got.text
    world["posts"].clear()
    assert (await api.post("/integrations/slack/test", headers=h(ta, "admin"))).status_code == 200
    assert world["posts"][-1][0] == HOOK
    # tenant B sees nothing of tenant A's configuration
    assert (await api.get("/integrations", headers=h(world["tb"], "admin"))).json()["slack"]["configured"] is False


async def test_pending_review_posts_one_interactive_message_and_retries_do_not_duplicate(world) -> None:  # type: ignore[no-untyped-def]
    api, ta, h, rt = world["api"], world["ta"], world["h"], world["rt"]
    await api.put("/integrations/slack", json={"webhook_url": HOOK}, headers=h(ta, "admin"))
    await dispatch_outbox(rt, world["settings"], world["http"])  # drain earlier events
    world["posts"].clear()
    pid = await world["proposal"]()
    world["fail"]["on"] = True
    await dispatch_outbox(rt, world["settings"], world["http"])  # Slack is down: no message, event stays pending
    assert world["posts"] == []
    world["fail"]["on"] = False
    await dispatch_outbox(rt, world["settings"], world["http"])
    await dispatch_outbox(rt, world["settings"], world["http"])  # already delivered: must not post again
    mine = [m for u, m in world["posts"] if u == HOOK and pid in json.dumps(m)]
    assert len(mine) == 1
    actions = next(b for b in mine[0]["blocks"] if b["type"] == "actions")
    assert {e["action_id"] for e in actions["elements"]} == {"proposal_approve", "proposal_reject", "open_console"}
    assert f"https://console.test/proposals/{pid}" in json.dumps(mine[0])


async def test_tenant_without_slack_config_gets_no_message(world) -> None:  # type: ignore[no-untyped-def]
    await world["proposal"](world["tb"])
    world["posts"].clear()
    await dispatch_outbox(world["rt"], world["settings"], world["http"])
    assert all(world["tb"].hex not in json.dumps(m) for _, m in world["posts"])


async def test_mapped_reviewer_approves_from_slack_and_message_is_replaced(world) -> None:  # type: ignore[no-untyped-def]
    ta = world["ta"]
    await world["map_user"](ta, "U0REVIEW1")
    pid = await world["proposal"]()
    calls = len(world["sb"].calls)
    world["posts"].clear()
    r = await world["click"]("approve", ta, pid, "U0REVIEW1")
    assert r.status_code == 200, r.text
    assert await world["state"](pid) == "executed" and len(world["sb"].calls) == calls + 1
    events = await world["audit"](pid)
    assert ("approved", "slack:U0REVIEW1 (U0REVIEW1)") in events
    url, msg = world["posts"][-1]
    assert url.startswith("https://hooks.slack.com/actions/") and msg["replace_original"] is True
    assert "Approved" in msg["text"]


async def test_slack_reject_never_executes(world) -> None:  # type: ignore[no-untyped-def]
    ta = world["ta"]
    await world["map_user"](ta, "U0REVIEW2")
    pid = await world["proposal"]()
    calls = len(world["sb"].calls)
    assert (await world["click"]("reject", ta, pid, "U0REVIEW2")).status_code == 200
    assert await world["state"](pid) == "rejected" and len(world["sb"].calls) == calls


@pytest.mark.parametrize("kind", ["bad_sig", "wrong_secret", "stale", "future"])
async def test_forged_or_replayed_requests_are_rejected_and_change_nothing(world, kind: str) -> None:  # type: ignore[no-untyped-def]
    ta = world["ta"]
    await world["map_user"](ta, "U0REVIEW3") if kind == "bad_sig" else None
    pid = await world["proposal"]()
    calls = len(world["sb"].calls)
    kw: dict = {"bad_sig": {"sign_body": False}, "wrong_secret": {"secret": "nope"},  # type: ignore[type-arg]
                "stale": {"ts": int(time.time()) - 600}, "future": {"ts": int(time.time()) + 600}}[kind]
    r = await world["click"]("approve", ta, pid, "U0REVIEW3", **kw)
    assert r.status_code == 401
    assert await world["state"](pid) == "pending_review" and len(world["sb"].calls) == calls


async def test_unmapped_slack_user_cannot_decide_even_with_a_valid_signature(world) -> None:  # type: ignore[no-untyped-def]
    ta = world["ta"]
    pid = await world["proposal"]()
    calls = len(world["sb"].calls)
    r = await world["click"]("approve", ta, pid, "U0STRANGER")
    assert r.status_code == 200
    assert await world["state"](pid) == "pending_review" and len(world["sb"].calls) == calls
    assert ("slack_unauthorized", "slack:U0STRANGER") in await world["audit"](pid)


async def test_identity_mapped_in_another_tenant_grants_nothing_here(world) -> None:  # type: ignore[no-untyped-def]
    ta, tb = world["ta"], world["tb"]
    await world["map_user"](tb, "U0OTHERTEN")
    pid = await world["proposal"]()
    calls = len(world["sb"].calls)
    await world["click"]("approve", ta, pid, "U0OTHERTEN")
    assert await world["state"](pid) == "pending_review" and len(world["sb"].calls) == calls
    # and a button value rewritten to tenant B cannot reach tenant A's proposal either
    forged = slack.ButtonValue("approve", tb, uuid.UUID(pid)).encode()
    await world["click"]("approve", tb, pid, "U0OTHERTEN", value=forged)
    assert await world["state"](pid) == "pending_review" and len(world["sb"].calls) == calls


async def test_double_click_and_slack_vs_console_race_execute_once(world) -> None:  # type: ignore[no-untyped-def]
    ta = world["ta"]
    await world["map_user"](ta, "U0RACER01")
    pid = await world["proposal"]()
    calls = len(world["sb"].calls)
    results = await asyncio.gather(
        world["click"]("approve", ta, pid, "U0RACER01"), world["click"]("approve", ta, pid, "U0RACER01"),
        world["api"].post(f"/proposals/{pid}/approve", headers=world["h"](ta, "reviewer")))
    assert sorted(r.status_code for r in results).count(409) <= 1
    assert await world["state"](pid) == "executed"
    assert len(world["sb"].calls) == calls + 1


async def test_response_url_on_a_foreign_host_is_never_requested(world) -> None:  # type: ignore[no-untyped-def]
    ta = world["ta"]
    await world["map_user"](ta, "U0SSRF001")
    pid = await world["proposal"]()
    world["hits"].clear()
    await world["click"]("approve", ta, pid, "U0SSRF001", response_url="http://169.254.169.254/latest/meta-data")
    assert await world["state"](pid) == "executed"
    assert not any("169.254" in u for u in world["hits"])


async def test_interactions_endpoint_is_disabled_without_a_signing_secret(world) -> None:  # type: ignore[no-untyped-def]
    rt = world["rt"]
    api = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(Settings(), rt)), base_url="http://api")
    assert (await api.post("/integrations/slack/interactions", content=b"payload=%7B%7D")).status_code == 503


async def test_identity_management_is_admin_only_unique_and_removable(world) -> None:  # type: ignore[no-untyped-def]
    api, ta, h = world["api"], world["ta"], world["h"]
    body = {"slack_user_id": "U0MANAGE01", "role": "reviewer", "label": "Wanjiku"}
    assert (await api.post("/integrations/slack/identities", json=body, headers=h(ta, "reviewer"))).status_code == 403
    assert (await api.post("/integrations/slack/identities", json={**body, "role": "agent"}, headers=h(ta, "admin"))).status_code == 422
    assert (await api.post("/integrations/slack/identities", json={**body, "slack_user_id": "bad id"}, headers=h(ta, "admin"))).status_code == 422
    iid = (await api.post("/integrations/slack/identities", json=body, headers=h(ta, "admin"))).json()["id"]
    assert (await api.post("/integrations/slack/identities", json=body, headers=h(ta, "admin"))).status_code == 409
    assert (await api.delete(f"/integrations/slack/identities/{iid}", headers=h(world["tb"], "admin"))).status_code == 404
    assert (await api.delete(f"/integrations/slack/identities/{iid}", headers=h(ta, "admin"))).status_code == 200
    pid = await world["proposal"]()
    await world["click"]("approve", ta, pid, "U0MANAGE01")  # removed identity: no longer authorized
    assert await world["state"](pid) == "pending_review"
