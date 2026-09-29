"""LangGraph agent. execute_action is its own node and is the ONLY node with a side effect.

Resume semantics: on resume the graph re-enters the interrupted node (await_review) from its start;
nodes before it are NOT re-run (checkpointed per node). execute_action's sandbox call carries an
idempotency key so a re-run after a crash cannot duplicate the money movement.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from app.agent.llm import LLM
from app.agent.policy import Decision, Policy, evaluate
from app.domain.idempotency import idempotency_key


class SandboxClient(Protocol):
    async def get_context(self, account_id: str) -> dict[str, Any]: ...
    async def mutate(self, action_type: str, account_id: str, amount: Decimal, key: str) -> dict[str, Any]: ...


class Persistence(Protocol):
    """Domain-side writes (proposal row, state transitions, audit, outbox) — owned by the API layer."""
    async def save_proposal(self, thread_id: str, proposal: dict[str, Any], decision: str, reason: str) -> dict[str, Any]: ...
    async def escalate(self, thread_id: str, reason: str) -> None: ...
    async def load_proposal(self, thread_id: str) -> dict[str, Any]: ...
    async def mark(self, thread_id: str, state: str, result: dict[str, Any] | None = None) -> None: ...


class State(TypedDict, total=False):
    thread_id: str
    account_id: str
    message: str
    intent: str
    context: dict[str, Any]
    proposal: dict[str, Any] | None
    proposal_id: str
    version: int
    decision: str
    review: dict[str, Any]
    outcome: str
    reply: str


@dataclass
class Deps:
    llm: LLM
    sandbox: SandboxClient
    store: Persistence
    policy: Policy


def _add_node(g: Any, name: str, fn: Any) -> None:
    # langgraph>=1 types node inputs with protocols that mypy doesn't match against a TypedDict State.
    g.add_node(name, fn)


def build_graph(deps: Deps, checkpointer: Any) -> Any:
    async def classify(s: State) -> State:
        return {"intent": await deps.llm.classify(s["message"])}

    async def retrieve_context(s: State) -> State:
        return {"context": await deps.sandbox.get_context(s["account_id"])}

    async def draft(s: State) -> State:
        p = await deps.llm.draft(s["message"], s["context"])
        return {"proposal": p.model_dump(mode="json") if p else None}

    async def policy_check(s: State) -> State:
        p = s["proposal"]
        if p is None:
            if s.get("intent", "other") != "other":  # a money request we could not turn into a proposal
                await deps.store.escalate(s["thread_id"], "money request without a draftable proposal")
                return {"decision": "escalated", "outcome": "passed to a human agent for review"}
            return {"decision": "none", "outcome": "no action proposed"}
        d, reason = evaluate(deps.policy, p["action_type"], Decimal(p["amount"]), p["risk_score"])
        row = await deps.store.save_proposal(s["thread_id"], p, d.value, reason)
        return {"decision": d.value, "proposal_id": row["id"], "version": row["version"]}

    async def await_review(s: State) -> State:
        # Everything before interrupt() is replayed on resume, so it must be side-effect free.
        review = interrupt({"proposal_id": s["proposal_id"]})
        return {"review": review}

    async def execute_action(s: State) -> State:
        row = await deps.store.load_proposal(s["thread_id"])  # picks up human edits + version
        key = idempotency_key(s["thread_id"], row["id"], row["version"])
        try:
            result = await deps.sandbox.mutate(row["action_type"], s["account_id"], Decimal(row["amount"]), key)
        except Exception as e:  # noqa: BLE001
            await deps.store.mark(s["thread_id"], "failed", {"error": str(e)})
            return {"outcome": f"failed: {e}"}
        await deps.store.mark(s["thread_id"], "executed", result)
        return {"outcome": f"{row['action_type']} of {row['amount']} executed"}

    async def compose_reply(s: State) -> State:
        return {"reply": await deps.llm.reply(s["message"], s.get("outcome", "no action taken"))}

    def after_policy(s: State) -> str:
        return {"auto_approve": "execute_action", "review": "await_review"}.get(s["decision"], "compose_reply")

    def after_review(s: State) -> str:
        return "execute_action" if s["review"]["decision"] in ("approved", "edited") else "compose_reply"

    g = StateGraph(State)
    _add_node(g, "classify", classify)
    _add_node(g, "retrieve_context", retrieve_context)
    _add_node(g, "draft", draft)
    _add_node(g, "policy_check", policy_check)
    _add_node(g, "await_review", await_review)
    _add_node(g, "execute_action", execute_action)
    _add_node(g, "compose_reply", compose_reply)
    g.set_entry_point("classify")
    g.add_edge("classify", "retrieve_context")
    g.add_edge("retrieve_context", "draft")
    g.add_edge("draft", "policy_check")
    g.add_conditional_edges("policy_check", after_policy)
    g.add_conditional_edges("await_review", after_review)
    g.add_edge("execute_action", "compose_reply")
    g.add_edge("compose_reply", END)
    return g.compile(checkpointer=checkpointer)


__all__ = ["Deps", "Decision", "build_graph"]
