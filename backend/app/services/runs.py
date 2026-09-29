from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from langgraph.types import Command
from sqlalchemy import select

from app.agent.graph import Deps, build_graph
from app.agent.policy import Policy
from app.db.models import TenantPolicy, Ticket
from app.db.session import tenant_session
from app.services.store import Store


class Runtime:
    """Wires graph dependencies per tenant. The checkpointer is shared and durable in production."""

    def __init__(self, engine: Any, llm: Any, sandbox: Any, checkpointer: Any) -> None:
        self.engine, self.llm, self.sandbox, self.checkpointer = engine, llm, sandbox, checkpointer

    async def policy(self, tenant_id: uuid.UUID) -> Policy:
        async with tenant_session(self.engine, tenant_id) as s:
            p = await s.get(TenantPolicy, tenant_id)
        if p is None:
            return Policy(Decimal(0), Decimal(50000), 0, frozenset({"refund", "reversal", "fee_waiver"}))
        return Policy(p.auto_approve_max, p.hard_limit, p.max_auto_risk, frozenset(p.allowed_actions))

    async def graph(self, tenant_id: uuid.UUID) -> Any:
        deps = Deps(self.llm, self.sandbox, Store(self.engine, tenant_id), await self.policy(tenant_id))
        return build_graph(deps, self.checkpointer)

    async def _save_reply(self, tenant_id: uuid.UUID, thread_id: str, out: dict[str, Any] | None) -> None:
        if not out or not out.get("reply"):
            return
        async with tenant_session(self.engine, tenant_id) as s:
            t = (await s.execute(select(Ticket).where(Ticket.thread_id == thread_id))).scalar_one_or_none()
            if t:
                t.reply = out["reply"]

    async def start(self, tenant_id: uuid.UUID, thread_id: str, account_id: str, message: str) -> dict[str, Any]:
        g = await self.graph(tenant_id)
        out: dict[str, Any] = await g.ainvoke(
            {"thread_id": thread_id, "account_id": account_id, "message": message},
            {"configurable": {"thread_id": thread_id}})
        await self._save_reply(tenant_id, thread_id, out)
        return out

    async def resume(self, tenant_id: uuid.UUID, thread_id: str, decision: str) -> dict[str, Any] | None:
        """Resume a paused run. Also used by crash recovery: if the run stopped mid-flight after the
        human decision was already committed, continue from the last checkpoint instead."""
        g = await self.graph(tenant_id)
        cfg = {"configurable": {"thread_id": thread_id}}
        st = await g.aget_state(cfg)
        if any(t.interrupts for t in st.tasks):
            out: dict[str, Any] = await g.ainvoke(Command(resume={"decision": decision}), cfg)
            await self._save_reply(tenant_id, thread_id, out)
            return out
        if st.next:
            out = await g.ainvoke(None, cfg)
            await self._save_reply(tenant_id, thread_id, out)
            return out
        return None  # already finished; nothing to do


async def recover_runs(rt: Runtime, tenant_ids: list[uuid.UUID]) -> int:
    """Worker startup: resume every run whose proposal is approved/edited but not yet executed."""
    from app.db.models import Proposal
    n = 0
    for tid in tenant_ids:
        async with tenant_session(rt.engine, tid) as s:
            rows = (await s.execute(select(Proposal.thread_id, Proposal.state)
                                    .where(Proposal.state.in_(["approved", "edited"])))).all()
        for thread_id, state in rows:
            if await rt.resume(tid, thread_id, state):
                n += 1
    return n
