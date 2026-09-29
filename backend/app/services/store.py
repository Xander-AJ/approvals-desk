"""Tenant-bound persistence for the agent + API. All state changes go through domain.state_machine,
and each writes an audit event and (for terminal outcomes) an outbox row in the SAME transaction."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.db.models import AuditEvent, OutboxEvent, Proposal, TenantPolicy
from app.db.session import tenant_session
from app.domain.state_machine import InvalidTransition, ProposalState, transition
from app.telemetry import current_trace_id


def snap(p: Proposal) -> dict[str, Any]:
    return {"id": str(p.id), "action_type": p.action_type, "amount": str(p.amount), "currency": p.currency,
            "reason": p.reason, "risk_score": p.risk_score, "state": p.state, "version": p.version,
            "thread_id": p.thread_id, "ticket_id": str(p.ticket_id)}


def apply_transition(s: AsyncSession, p: Proposal, target: ProposalState, actor: str,
                     result: dict[str, Any] | None = None, note: str | None = None) -> None:
    before = snap(p)
    p.state = transition(ProposalState(p.state), target).value  # raises InvalidTransition
    if result is not None:
        p.result = result
    if target in (ProposalState.APPROVED, ProposalState.EDITED, ProposalState.REJECTED, ProposalState.EXPIRED):
        p.decided_at = datetime.now(UTC)
    s.add(AuditEvent(tenant_id=p.tenant_id, proposal_id=p.id, actor=actor, event=target.value,
                     before=before, after={**snap(p), **({"note": note} if note else {})},
                     trace_id=current_trace_id()))
    if target in (ProposalState.EXECUTED, ProposalState.FAILED, ProposalState.REJECTED, ProposalState.EXPIRED):
        s.add(OutboxEvent(tenant_id=p.tenant_id, topic=f"proposal.{target.value}",
                          payload={"proposal_id": str(p.id), "state": target.value, "result": result}))


class Store:
    def __init__(self, engine: AsyncEngine, tenant_id: uuid.UUID) -> None:
        self.engine, self.tenant_id = engine, tenant_id

    # ---- Persistence protocol used by the agent graph ----
    async def save_proposal(self, thread_id: str, proposal: dict[str, Any], decision: str, reason: str) -> dict[str, Any]:
        from app.db.models import Ticket
        async with tenant_session(self.engine, self.tenant_id) as s:
            existing = (await s.execute(select(Proposal).where(Proposal.thread_id == thread_id))).scalar_one_or_none()
            if existing:  # idempotent: node may re-run if crash hit before its checkpoint
                return snap(existing)
            ticket = (await s.execute(select(Ticket).where(Ticket.thread_id == thread_id))).scalar_one()
            pol = await s.get(TenantPolicy, self.tenant_id)
            p = Proposal(tenant_id=self.tenant_id, ticket_id=ticket.id, thread_id=thread_id,
                         action_type=proposal["action_type"], amount=Decimal(proposal["amount"]),
                         currency=proposal["currency"], reason=proposal["reason"], evidence=proposal["evidence"],
                         risk_score=proposal["risk_score"], state=ProposalState.PROPOSED.value,
                         trace_id=current_trace_id())
            s.add(p)
            await s.flush()
            s.add(AuditEvent(tenant_id=self.tenant_id, proposal_id=p.id, actor="agent", event="proposed",
                             after=snap(p), trace_id=current_trace_id()))
            if decision == "auto_approve":
                p.auto_approved = True
                apply_transition(s, p, ProposalState.APPROVED, "policy:auto", note=reason)
            elif decision == "block":
                apply_transition(s, p, ProposalState.REJECTED, "policy:block", note=reason)
            else:
                p.expires_at = datetime.now(UTC) + timedelta(minutes=pol.sla_minutes if pol else 60)
                apply_transition(s, p, ProposalState.PENDING_REVIEW, "agent", note=reason)
            return snap(p)

    async def escalate(self, thread_id: str, reason: str) -> None:
        """Agent could not draft a proposal for a money request: hand it to a human instead of silently denying."""
        from app.db.models import Ticket
        async with tenant_session(self.engine, self.tenant_id) as s:
            t = (await s.execute(select(Ticket).where(Ticket.thread_id == thread_id))).scalar_one()
            if t.needs_human:  # idempotent on node replay
                return
            t.needs_human = True
            s.add(AuditEvent(tenant_id=self.tenant_id, actor="agent", event="escalated",
                             after={"ticket_id": str(t.id), "reason": reason}, trace_id=current_trace_id()))
            s.add(OutboxEvent(tenant_id=self.tenant_id, topic="ticket.escalated",
                              payload={"ticket_id": str(t.id), "reason": reason}))

    async def load_proposal(self, thread_id: str) -> dict[str, Any]:
        async with tenant_session(self.engine, self.tenant_id) as s:
            p = (await s.execute(select(Proposal).where(Proposal.thread_id == thread_id))).scalar_one()
            return snap(p)

    async def mark(self, thread_id: str, state: str, result: dict[str, Any] | None = None) -> None:
        async with tenant_session(self.engine, self.tenant_id) as s:
            p = (await s.execute(select(Proposal).where(Proposal.thread_id == thread_id)
                                 .with_for_update())).scalar_one()
            if p.state == state:  # replay after crash between mark() and checkpoint
                return
            apply_transition(s, p, ProposalState(state), "worker", result)


__all__ = ["InvalidTransition", "Store", "apply_transition", "snap"]
