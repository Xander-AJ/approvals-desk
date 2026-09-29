"""arq worker: SLA expiry, outbox delivery, and crash recovery on startup."""
from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
from arq import cron
from arq.connections import RedisSettings
from opentelemetry import propagate, trace
from sqlalchemy import select

from app.config import Settings
from app.db.models import OutboxDelivery, OutboxEvent, Proposal, Tenant, TenantIntegration
from app.db.session import make_engine, tenant_session
from app.domain.state_machine import InvalidTransition, ProposalState
from app.integrations import slack
from app.services.runs import Runtime, recover_runs
from app.services.store import apply_transition
from app.telemetry import setup_tracing


async def all_tenants(rt: Runtime) -> list[uuid.UUID]:
    async with rt.engine.connect() as c:  # tenants table is not tenant-scoped
        return [r[0] for r in await c.execute(select(Tenant.id))]


async def expire_stale(rt: Runtime) -> int:
    """Expire pending proposals past their SLA, then let the run finish (reply to customer)."""
    n = 0
    for tid in await all_tenants(rt):
        async with tenant_session(rt.engine, tid) as s:
            rows = (await s.execute(select(Proposal).where(
                Proposal.state == "pending_review", Proposal.expires_at < datetime.now(UTC))
                .with_for_update(skip_locked=True))).scalars().all()
            threads = []
            for p in rows:
                try:
                    apply_transition(s, p, ProposalState.EXPIRED, "worker:sla")
                    threads.append(p.thread_id)
                except InvalidTransition:
                    continue
        for th in threads:
            await rt.resume(tid, th, "expired")
            n += 1
    return n


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


async def dispatch_outbox(rt: Runtime, settings: Settings, http: httpx.AsyncClient | None = None) -> int:
    """At-least-once delivery. Receivers dedupe on the X-Event-Id header."""
    sent = 0
    owns_client = http is None
    client = http or httpx.AsyncClient()
    try:
        sent = await _dispatch(rt, settings, client)
    finally:
        if owns_client:
            await client.aclose()
    return sent


async def _dispatch(rt: Runtime, settings: Settings, client: httpx.AsyncClient) -> int:
    sent = 0
    for tid in await all_tenants(rt):
        async with tenant_session(rt.engine, tid) as s:
            integ = await s.get(TenantIntegration, tid)
            rows = (await s.execute(select(OutboxEvent).where(OutboxEvent.delivered_at.is_(None))
                                    .order_by(OutboxEvent.created_at).limit(50)
                                    .with_for_update(skip_locked=True))).scalars().all()
            for ev in rows:
                needed: list[str] = []
                if settings.webhook_url:
                    needed.append("webhook")
                if ev.topic == "proposal.pending_review" and integ and integ.slack_webhook_url:
                    needed.append("slack")
                done = set((await s.execute(select(OutboxDelivery.sink)
                                            .where(OutboxDelivery.event_id == ev.id))).scalars())
                ok = True
                for sink in (x for x in needed if x not in done):
                    try:
                        if sink == "webhook":
                            await _send_webhook(client, settings, tid, ev)
                        else:
                            assert integ and integ.slack_webhook_url
                            await slack.post(client, integ.slack_webhook_url,
                                             slack.proposal_message(tid, ev.payload["proposal"], settings.console_url))
                    except (httpx.HTTPError, ValueError):
                        ev.attempts += 1
                        ok = False
                        continue
                    s.add(OutboxDelivery(tenant_id=tid, event_id=ev.id, sink=sink))
                    await s.flush()  # record each success immediately: a later sink failing must not resend this one
                if ok:
                    ev.delivered_at = datetime.now(UTC)
                    sent += 1
    return sent


async def _send_webhook(client: httpx.AsyncClient, settings: Settings, tid: uuid.UUID, ev: OutboxEvent) -> None:
    assert settings.webhook_url and settings.webhook_secret  # Settings.validate_for_runtime enforces the pair
    body = json.dumps({"topic": ev.topic, "tenant_id": str(tid), **ev.payload}).encode()
    r = await client.post(settings.webhook_url, content=body, timeout=5,
                          headers={"X-Event-Id": str(ev.id), "X-Signature": sign(settings.webhook_secret, body),
                                   "Content-Type": "application/json"})
    r.raise_for_status()


def build_runtime(settings: Settings, checkpointer: Any) -> Runtime:
    from app.agent.llm import make_llm
    from app.services.sandbox_client import HttpSandbox
    engine = make_engine(settings.database_url)
    return Runtime(engine, make_llm(settings), HttpSandbox(httpx.AsyncClient(
        base_url=settings.sandbox_url,
        headers={"X-Sandbox-Key": settings.sandbox_api_key} if settings.sandbox_api_key else {})), checkpointer)


async def startup(ctx: dict[str, Any]) -> None:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    setup_tracing("approvals-worker")
    settings = Settings()
    cm = AsyncPostgresSaver.from_conn_string(settings.checkpoint_dsn)
    saver = await cm.__aenter__()
    await saver.setup()
    ctx["cm"], ctx["settings"] = cm, settings
    ctx["rt"] = build_runtime(settings, saver)
    with trace.get_tracer("worker").start_as_current_span("worker.recover_runs"):
        await recover_runs(ctx["rt"], await all_tenants(ctx["rt"]))  # resume runs orphaned by a crash


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["cm"].__aexit__(None, None, None)


async def expire_job(ctx: dict[str, Any]) -> int:
    with trace.get_tracer("worker").start_as_current_span("job.expire_stale"):
        return await expire_stale(ctx["rt"])


async def resume_job(ctx: dict[str, Any], tenant_id: str, thread_id: str, decision: str,
                     carrier: dict[str, str] | None = None) -> bool:
    parent = propagate.extract(carrier or {})
    with trace.get_tracer("worker").start_as_current_span("job.resume_run", context=parent):
        return await ctx["rt"].resume(uuid.UUID(tenant_id), thread_id, decision) is not None


async def outbox_job(ctx: dict[str, Any]) -> int:
    return await dispatch_outbox(ctx["rt"], ctx["settings"])


class WorkerSettings:
    functions = [resume_job]
    on_startup = startup
    on_shutdown = shutdown
    cron_jobs = [cron(expire_job, second={0, 30}), cron(outbox_job, second={5, 15, 25, 35, 45, 55})]
    redis_settings = RedisSettings.from_dsn(Settings().redis_url)
