from __future__ import annotations

import json
import logging
import uuid
from decimal import Decimal
from typing import Annotated, Any, Literal
from urllib.parse import parse_qs

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from opentelemetry import propagate
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.policy import Decision, evaluate
from app.auth import JwksCache, Principal, require
from app.config import Settings
from app.db.models import AuditEvent, Proposal, SlackIdentity, TenantIntegration, TenantPolicy, Ticket
from app.db.session import tenant_session
from app.domain.state_machine import InvalidTransition, ProposalState
from app.integrations import slack
from app.services import compensation
from app.services.runs import Runtime
from app.services.store import Store, apply_transition, snap

log = logging.getLogger(__name__)
Agent = Annotated[Principal, Depends(require("agent", "admin"))]
Reviewer = Annotated[Principal, Depends(require("reviewer", "admin"))]
Admin = Annotated[Principal, Depends(require("admin"))]
Any_ = Annotated[Principal, Depends(require("agent", "reviewer", "admin"))]


Money = Annotated[Decimal, Field(max_digits=12, decimal_places=2)]


class TicketIn(BaseModel):
    # Becomes a sandbox account id inside a URL path: no slashes, no leading dot ("..").
    customer_ref: str = Field(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")
    message: str = Field(min_length=1, max_length=2000)


class EditIn(BaseModel):
    amount: Money = Field(gt=0)
    reason: str | None = None


class BulkIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    decision: str = Field(pattern="^(approve|reject)$")


class DevTokenIn(BaseModel):
    tenant_id: uuid.UUID
    role: str
    user: str


class CompensateIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class SlackConfigIn(BaseModel):
    webhook_url: str = Field(max_length=500)
    channel_label: str | None = Field(None, max_length=100)


class SlackIdentityIn(BaseModel):
    slack_user_id: str = Field(pattern=r"^[UW][A-Z0-9]{2,31}$")
    role: Literal["reviewer", "admin"]
    label: str = Field("", max_length=200)


class PolicyIn(BaseModel):
    auto_approve_max: Money = Field(ge=0)
    hard_limit: Money = Field(gt=0)
    max_auto_risk: int = Field(ge=0, le=100)
    allowed_actions: list[Literal["refund", "reversal", "fee_waiver"]]
    sla_minutes: int = Field(gt=0, le=60 * 24 * 30)

    @model_validator(mode="after")
    def _auto_below_hard_limit(self) -> PolicyIn:
        if self.auto_approve_max > self.hard_limit:
            raise ValueError("auto_approve_max must not exceed hard_limit")
        return self


def create_app(settings: Settings, rt: Runtime, queue: Any = None, http: httpx.AsyncClient | None = None) -> FastAPI:
    settings.validate_for_runtime()
    app = FastAPI(title="approvals-desk")
    app.state.settings = settings
    app.state.rt = rt
    engine: AsyncEngine = rt.engine
    http_client = http or httpx.AsyncClient()  # shared: Slack posts and JWKS fetches
    if settings.jwt_jwks_url:
        app.state.jwks = JwksCache(settings.jwt_jwks_url, http_client)

    @app.exception_handler(InvalidTransition)
    async def _409(_: Request, e: InvalidTransition) -> JSONResponse:
        return JSONResponse({"detail": str(e)}, status_code=409)

    if settings.dev_auth:
        from app.auth import mint_token

        @app.post("/dev/token")
        async def dev_token(body: DevTokenIn) -> dict[str, str]:
            return {"token": mint_token(settings, body.user, body.tenant_id, body.role)}

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/tickets")
    async def create_ticket(body: TicketIn, p: Agent) -> dict[str, Any]:
        thread_id = f"th-{uuid.uuid4().hex}"
        async with tenant_session(engine, p.tenant_id) as s:
            t = Ticket(tenant_id=p.tenant_id, customer_ref=body.customer_ref, message=body.message, thread_id=thread_id)
            s.add(t)
            await s.flush()
            tid = str(t.id)
        try:
            out = await rt.start(p.tenant_id, thread_id, body.customer_ref, body.message)
        except Exception:  # noqa: BLE001 - any agent/sandbox/LLM failure must reach a human, not a 500
            log.exception("agent run failed for ticket %s", tid)
            await Store(engine, p.tenant_id).escalate(thread_id, "agent run failed")
            return {"ticket_id": tid, "thread_id": thread_id, "proposal_id": None, "decision": "escalated",
                    "reply": None}
        if out.get("reply"):
            async with tenant_session(engine, p.tenant_id) as s:
                (await s.get(Ticket, uuid.UUID(tid))).reply = out["reply"]  # type: ignore[union-attr]
        return {"ticket_id": tid, "thread_id": thread_id, "proposal_id": out.get("proposal_id"),
                "decision": out.get("decision"), "reply": out.get("reply")}

    @app.get("/tickets")
    async def list_tickets(p: Any_, needs_human: bool | None = None) -> list[dict[str, Any]]:
        q = select(Ticket).order_by(Ticket.created_at.desc()).limit(200)
        if needs_human is not None:
            q = q.where(Ticket.needs_human == needs_human)
        async with tenant_session(engine, p.tenant_id) as s:
            return [{"id": str(t.id), "customer_ref": t.customer_ref, "message": t.message, "reply": t.reply,
                     "needs_human": t.needs_human, "created_at": t.created_at.isoformat()}
                    for t in (await s.execute(q)).scalars()]

    @app.get("/proposals")
    async def list_proposals(p: Any_, state: str | None = None, action_type: str | None = None,
                             limit: Annotated[int, Query(ge=1, le=500)] = 100) -> list[dict[str, Any]]:
        q = select(Proposal).order_by(Proposal.created_at.desc()).limit(limit)
        if state:
            q = q.where(Proposal.state == state)
        if action_type:
            q = q.where(Proposal.action_type == action_type)
        async with tenant_session(engine, p.tenant_id) as s:
            return [{**snap(x), "auto_approved": x.auto_approved, "trace_id": x.trace_id,
                     "expires_at": x.expires_at.isoformat() if x.expires_at else None}
                    for x in (await s.execute(q)).scalars()]

    @app.get("/proposals/{pid}")
    async def get_proposal(pid: uuid.UUID, p: Any_) -> dict[str, Any]:
        async with tenant_session(engine, p.tenant_id) as s:
            x = await s.get(Proposal, pid)
            if not x:
                raise HTTPException(404)
            audit = (await s.execute(select(AuditEvent).where(AuditEvent.proposal_id == pid)
                                     .order_by(AuditEvent.created_at))).scalars()
            return {**snap(x), "evidence": x.evidence, "result": x.result, "original": x.original,
                    "trace_id": x.trace_id, "trace_url": f"{settings.jaeger_url}/trace/{x.trace_id}" if x.trace_id else None,
                    "audit": [{"event": a.event, "actor": a.actor, "before": a.before, "after": a.after,
                               "trace_id": a.trace_id, "at": a.created_at.isoformat()} for a in audit]}

    async def _decide(pid: uuid.UUID, p: Principal, target: ProposalState, edit: EditIn | None = None) -> str:
        async with tenant_session(engine, p.tenant_id) as s:
            x = (await s.execute(select(Proposal).where(Proposal.id == pid).with_for_update())).scalar_one_or_none()
            if not x:
                raise HTTPException(404)
            if edit:
                pol = await rt.policy(p.tenant_id)
                d, why = evaluate(pol, x.action_type, edit.amount, x.risk_score)
                if d == Decision.BLOCK:
                    raise HTTPException(422, why)
                if ProposalState(x.state) != ProposalState.PENDING_REVIEW:
                    raise InvalidTransition(ProposalState(x.state), ProposalState.EDITED)
                x.original = snap(x)
                x.amount, x.version = edit.amount, x.version + 1
                x.reason = edit.reason or x.reason
            apply_transition(s, x, target, p.user)
            return x.thread_id

    async def _resume(p: Principal, thread_id: str, decision: str) -> None:
        if queue is not None:  # durable: the job survives a dead worker and runs when it returns
            carrier: dict[str, str] = {}
            propagate.inject(carrier)  # link approval -> execution in one trace
            await queue.enqueue_job("resume_job", str(p.tenant_id), thread_id, decision, carrier,
                                    _job_id=f"resume-{thread_id}-{decision}")
        else:
            await rt.resume(p.tenant_id, thread_id, decision)

    @app.post("/proposals/{pid}/approve")
    async def approve(pid: uuid.UUID, p: Reviewer) -> dict[str, str]:
        th = await _decide(pid, p, ProposalState.APPROVED)
        await _resume(p, th, "approved")
        return {"status": "ok"}

    @app.post("/proposals/{pid}/reject")
    async def reject(pid: uuid.UUID, p: Reviewer) -> dict[str, str]:
        th = await _decide(pid, p, ProposalState.REJECTED)
        await _resume(p, th, "rejected")
        return {"status": "ok"}

    @app.post("/proposals/{pid}/edit")
    async def edit(pid: uuid.UUID, body: EditIn, p: Reviewer) -> dict[str, str]:
        th = await _decide(pid, p, ProposalState.EDITED, body)
        await _resume(p, th, "edited")
        return {"status": "ok"}

    @app.post("/proposals/{pid}/compensate")
    async def compensate(pid: uuid.UUID, body: CompensateIn, p: Admin) -> dict[str, Any]:
        """Undo an executed refund/reversal/fee waiver. Admin only; needs a reason; audited; at most once."""
        try:
            result = await compensation.compensate(rt, p.tenant_id, pid, p.user, body.reason)
        except compensation.NotFound:
            raise HTTPException(404) from None
        except (httpx.HTTPError, ValueError) as e:
            log.exception("compensation failed for proposal %s", pid)
            raise HTTPException(502, f"payments provider error ({type(e).__name__}); nothing was recorded, retry is safe") from e
        return {"status": "ok", "compensation": result}

    @app.post("/proposals/bulk")
    async def bulk(body: BulkIn, p: Reviewer) -> dict[str, Any]:
        results: dict[str, str] = {}
        for pid in body.ids:
            try:
                if body.decision == "approve":
                    await approve(pid, p)
                else:
                    await reject(pid, p)
                results[str(pid)] = "ok"
            except (InvalidTransition, HTTPException) as e:
                results[str(pid)] = f"error: {getattr(e, 'detail', e)}"
        return {"results": results}

    @app.get("/policy")
    async def get_policy(p: Any_) -> dict[str, Any]:
        pol = await rt.policy(p.tenant_id)
        async with tenant_session(engine, p.tenant_id) as s:
            row = await s.get(TenantPolicy, p.tenant_id)
        return {"auto_approve_max": str(pol.auto_approve_max), "hard_limit": str(pol.hard_limit),
                "max_auto_risk": pol.max_auto_risk, "allowed_actions": sorted(pol.allowed_actions),
                "sla_minutes": row.sla_minutes if row else 60}

    @app.put("/policy")
    async def put_policy(body: PolicyIn, p: Admin) -> dict[str, str]:
        async with tenant_session(engine, p.tenant_id) as s:
            row = await s.get(TenantPolicy, p.tenant_id) or TenantPolicy(tenant_id=p.tenant_id)
            for k, v in body.model_dump().items():
                setattr(row, k, v)
            s.add(row)
            s.add(AuditEvent(tenant_id=p.tenant_id, actor=p.user, event="policy_updated", after=body.model_dump(mode="json")))
        return {"status": "ok"}

    @app.get("/metrics")
    async def metrics(p: Any_) -> dict[str, Any]:
        async with tenant_session(engine, p.tenant_id) as s:
            total = (await s.execute(select(func.count()).select_from(Proposal))).scalar_one()
            auto = (await s.execute(select(func.count()).where(Proposal.auto_approved))).scalar_one()
            human = (await s.execute(select(func.count()).where(
                Proposal.decided_at.is_not(None), ~Proposal.auto_approved))).scalar_one()
            overridden = (await s.execute(select(func.count()).where(
                Proposal.original.is_not(None) | (Proposal.state == "rejected") & ~Proposal.auto_approved
                & (Proposal.expires_at.is_not(None))))).scalar_one()
            lat: Any = (await s.execute(select(func.avg(func.extract("epoch", Proposal.decided_at - Proposal.created_at)))
                                   .where(Proposal.decided_at.is_not(None), ~Proposal.auto_approved))).scalar_one()
        return {"total": total, "auto_approve_rate": auto / total if total else 0.0,
                "override_rate": overridden / human if human else 0.0,
                "avg_approval_latency_s": float(lat) if lat is not None else None}

    # ------------------------------------------------------------------ Slack integration
    @app.get("/integrations")
    async def get_integrations(p: Admin) -> dict[str, Any]:
        async with tenant_session(engine, p.tenant_id) as s:
            integ = await s.get(TenantIntegration, p.tenant_id)
            idents = (await s.execute(select(SlackIdentity).order_by(SlackIdentity.label))).scalars().all()
        url = integ.slack_webhook_url if integ else None
        return {"slack": {"configured": bool(url), "webhook_hint": f"…{url[-4:]}" if url else None,
                          "channel_label": integ.slack_channel_label if integ else None,
                          "interactions_enabled": bool(settings.slack_signing_secret)},
                "identities": [{"id": str(i.id), "slack_user_id": i.slack_user_id, "role": i.role, "label": i.label}
                               for i in idents]}

    @app.put("/integrations/slack")
    async def put_slack(body: SlackConfigIn, p: Admin) -> dict[str, str]:
        if not slack.is_slack_url(body.webhook_url):
            raise HTTPException(422, "webhook_url must be an https://hooks.slack.com/... URL")
        async with tenant_session(engine, p.tenant_id) as s:
            row = await s.get(TenantIntegration, p.tenant_id) or TenantIntegration(tenant_id=p.tenant_id)
            row.slack_webhook_url, row.slack_channel_label = body.webhook_url, body.channel_label
            s.add(row)
            s.add(AuditEvent(tenant_id=p.tenant_id, actor=p.user, event="integration_updated",
                             after={"slack": "configured", "channel_label": body.channel_label}))
        return {"status": "ok"}

    @app.delete("/integrations/slack")
    async def delete_slack(p: Admin) -> dict[str, str]:
        async with tenant_session(engine, p.tenant_id) as s:
            row = await s.get(TenantIntegration, p.tenant_id)
            if row:
                row.slack_webhook_url = None
            s.add(AuditEvent(tenant_id=p.tenant_id, actor=p.user, event="integration_removed", after={"slack": "removed"}))
        return {"status": "ok"}

    @app.post("/integrations/slack/test")
    async def test_slack(p: Admin) -> dict[str, str]:
        async with tenant_session(engine, p.tenant_id) as s:
            row = await s.get(TenantIntegration, p.tenant_id)
        if not row or not row.slack_webhook_url:
            raise HTTPException(409, "Slack is not configured")
        try:
            await slack.post(http_client, row.slack_webhook_url, {"text": "approvals-desk: test message. Slack is connected."})
        except (httpx.HTTPError, ValueError) as e:
            raise HTTPException(502, f"Slack rejected the test message: {type(e).__name__}") from e
        return {"status": "ok"}

    @app.post("/integrations/slack/identities")
    async def add_identity(body: SlackIdentityIn, p: Admin) -> dict[str, str]:
        async with tenant_session(engine, p.tenant_id) as s:
            dup = (await s.execute(select(SlackIdentity).where(SlackIdentity.slack_user_id == body.slack_user_id))).first()
            if dup:
                raise HTTPException(409, "that Slack user is already mapped")
            ident = SlackIdentity(tenant_id=p.tenant_id, **body.model_dump())
            s.add(ident)
            await s.flush()
            s.add(AuditEvent(tenant_id=p.tenant_id, actor=p.user, event="slack_identity_added",
                             after={"slack_user_id": body.slack_user_id, "role": body.role}))
            return {"id": str(ident.id)}

    @app.delete("/integrations/slack/identities/{iid}")
    async def remove_identity(iid: uuid.UUID, p: Admin) -> dict[str, str]:
        async with tenant_session(engine, p.tenant_id) as s:
            ident = await s.get(SlackIdentity, iid)
            if not ident:
                raise HTTPException(404)
            s.add(AuditEvent(tenant_id=p.tenant_id, actor=p.user, event="slack_identity_removed",
                             after={"slack_user_id": ident.slack_user_id}))
            await s.delete(ident)
        return {"status": "ok"}

    async def _slack_reply(url: str | None, body: dict[str, Any]) -> None:
        if not url or not slack.is_slack_url(url):  # response_url comes from the request: never trust its host
            return
        try:
            await slack.post(http_client, url, body)
        except (httpx.HTTPError, ValueError):
            log.warning("could not update Slack message")

    @app.post("/integrations/slack/interactions")
    async def slack_interactions(request: Request, background: BackgroundTasks) -> dict[str, str]:
        secret = settings.slack_signing_secret
        if not secret:
            raise HTTPException(503, "Slack interactions are not configured")
        raw = await request.body()
        if not slack.verify_signature(secret, request.headers.get("x-slack-request-timestamp"),
                                      request.headers.get("x-slack-signature"), raw):
            raise HTTPException(401, "invalid Slack signature")
        try:
            payload = json.loads(parse_qs(raw.decode())["payload"][0])
        except (KeyError, ValueError, IndexError) as e:
            raise HTTPException(400, "malformed interaction payload") from e
        actions = payload.get("actions") or []
        if payload.get("type") != "block_actions" or not actions or actions[0].get("action_id") not in (
                slack.APPROVE_ACTION, slack.REJECT_ACTION):
            return {}  # e.g. the "Open / edit" link button: nothing to do
        try:
            bv = slack.ButtonValue.decode(actions[0]["value"])
        except (KeyError, ValueError) as e:
            raise HTTPException(400, "malformed button value") from e
        uid: str = payload["user"]["id"]
        response_url = payload.get("response_url")

        def reply(text: str) -> None:
            background.add_task(_slack_reply, response_url,
                                {"response_type": "ephemeral", "replace_original": False, "text": text})

        async with tenant_session(engine, bv.tenant_id) as s:
            ident = (await s.execute(select(SlackIdentity).where(SlackIdentity.slack_user_id == uid))).scalar_one_or_none()
            if ident is None:
                s.add(AuditEvent(tenant_id=bv.tenant_id, proposal_id=bv.proposal_id, actor=f"slack:{uid}",
                                 event="slack_unauthorized", after={"attempted": bv.action}))
        if ident is None:
            reply("You are not authorized to decide proposals. Ask an admin to map your Slack user.")
            return {}
        who = Principal(f"slack:{uid} ({ident.label or ident.role})", bv.tenant_id, ident.role)
        target = ProposalState.APPROVED if bv.action == "approve" else ProposalState.REJECTED
        try:
            thread_id = await _decide(bv.proposal_id, who, target)
        except InvalidTransition as e:
            reply(f"Already decided ({e.current.value}); nothing changed.")
            return {}
        except HTTPException:
            reply("Proposal not found.")
            return {}
        await _resume(who, thread_id, "approved" if bv.action == "approve" else "rejected")
        async with tenant_session(engine, bv.tenant_id) as s:
            x = await s.get(Proposal, bv.proposal_id)
            title = f"{x.action_type.replace('_', ' ').title()} · {x.currency} {x.amount:,.2f}" if x else "Proposal"
        background.add_task(_slack_reply, response_url, slack.decided_message(
            title, "Approved" if bv.action == "approve" else "Rejected", ident.label or f"<@{uid}>"))
        return {}

    return app
