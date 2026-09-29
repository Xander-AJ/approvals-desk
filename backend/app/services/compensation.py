"""Compensation: undo an executed money movement (executed -> compensated).

Same exactly-once discipline as execution. The sandbox call carries a deterministic idempotency key and happens
OUTSIDE any DB transaction; the state change is recorded afterwards. A crash between the two is safe to retry:
the sandbox replays the original result, and the row is still `executed` so the retry completes the transition.
"""
from __future__ import annotations

import hashlib
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.db.models import Proposal, Ticket
from app.db.session import tenant_session
from app.domain.idempotency import idempotency_key
from app.domain.state_machine import InvalidTransition, ProposalState
from app.services.runs import Runtime
from app.services.store import apply_transition


def compensation_key(thread_id: str, proposal_id: str, version: int) -> str:
    return hashlib.sha256((idempotency_key(thread_id, proposal_id, version) + ":compensate").encode()).hexdigest()


class NotFound(Exception):
    pass


async def compensate(rt: Runtime, tenant_id: uuid.UUID, proposal_id: uuid.UUID, actor: str, reason: str) -> dict[str, Any]:
    async with tenant_session(rt.engine, tenant_id) as s:
        p = await s.get(Proposal, proposal_id)
        if p is None:
            raise NotFound
        if ProposalState(p.state) != ProposalState.EXECUTED:
            raise InvalidTransition(ProposalState(p.state), ProposalState.COMPENSATED)
        ticket = (await s.execute(select(Ticket).where(Ticket.id == p.ticket_id))).scalar_one()
        ref = (p.result or {}).get("txn_id")
        if not ref:
            raise InvalidTransition(ProposalState.EXECUTED, ProposalState.COMPENSATED)  # nothing to undo
        args = (ticket.customer_ref, Decimal(p.amount), str(ref),
                compensation_key(p.thread_id, str(p.id), p.version))

    result: dict[str, Any] = await rt.sandbox.compensate(*args)  # may raise: state untouched, safe to retry

    async with tenant_session(rt.engine, tenant_id) as s:
        p = (await s.execute(select(Proposal).where(Proposal.id == proposal_id).with_for_update())).scalar_one()
        apply_transition(s, p, ProposalState.COMPENSATED, actor,
                         {**(p.result or {}), "compensation": result, "compensation_reason": reason}, note=reason)
    return result
