from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from opentelemetry import propagate
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.agent.policy import Decision, evaluate
from app.auth import Principal, require
from app.config import Settings
from app.db.models import AuditEvent, Proposal, TenantPolicy, Ticket
from app.db.session import tenant_session
from app.domain.state_machine import InvalidTransition, ProposalState
from app.services.runs import Runtime
from app.services.store import apply_transition, snap

Agent = Annotated[Principal, Depends(require("agent", "admin"))]
Reviewer = Annotated[Principal, Depends(require("reviewer", "admin"))]
Admin = Annotated[Principal, Depends(require("admin"))]
Any_ = Annotated[Principal, Depends(require("agent", "reviewer", "admin"))]


class TicketIn(BaseModel):
    customer_ref: str
    message: str = Field(min_length=1, max_length=2000)


class EditIn(BaseModel):
    amount: Decimal = Field(gt=0)
    reason: str | None = None


class BulkIn(BaseModel):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    decision: str = Field(pattern="^(approve|reject)$")


class DevTokenIn(BaseModel):
    tenant_id: uuid.UUID
    role: str
    user: str


class PolicyIn(BaseModel):
    auto_approve_max: Decimal = Field(ge=0)
    hard_limit: Decimal = Field(gt=0)
    max_auto_risk: int = Field(ge=0, le=100)
    allowed_actions: list[str]
    sla_minutes: int = Field(gt=0)


def create_app(settings: Settings, rt: Runtime, queue: Any = None) -> FastAPI:
    settings.validate_for_runtime()
    app = FastAPI(title="approvals-desk")
    app.state.settings = settings
    app.state.rt = rt
    engine: AsyncEngine = rt.engine

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
        out = await rt.start(p.tenant_id, thread_id, body.customer_ref, body.message)
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
                             limit: int = 100) -> list[dict[str, Any]]:
        q = select(Proposal).order_by(Proposal.created_at.desc()).limit(min(limit, 500))
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

    return app
