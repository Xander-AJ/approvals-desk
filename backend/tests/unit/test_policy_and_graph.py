from decimal import Decimal
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from app.agent.fake_llm import FakeLLM
from app.agent.graph import Deps, build_graph
from app.agent.policy import Decision, Policy, evaluate

POLICY = Policy(Decimal("500"), Decimal("50000"), 30, frozenset({"refund", "reversal", "fee_waiver"}))


def test_policy_decisions() -> None:
    assert evaluate(POLICY, "refund", Decimal("100"), 10)[0] == Decision.AUTO_APPROVE
    assert evaluate(POLICY, "refund", Decimal("1200"), 10)[0] == Decision.REVIEW
    assert evaluate(POLICY, "refund", Decimal("100"), 80)[0] == Decision.REVIEW
    assert evaluate(POLICY, "refund", Decimal("99999"), 1)[0] == Decision.BLOCK
    assert evaluate(POLICY, "chargeback", Decimal("1"), 1)[0] == Decision.BLOCK


class FakeSandbox:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def get_context(self, account_id: str) -> dict[str, Any]:
        t = lambda i: {"id": i, "amount": "1200", "kind": "charge"}  # noqa: E731
        return {"transactions": [t("x1"), t("x2")]}

    async def mutate(self, action_type: str, account_id: str, amount: Decimal, key: str) -> dict[str, Any]:
        self.calls.append(key)
        return {"txn_id": "r1"}


class Store:
    def __init__(self) -> None:
        self.row: dict[str, Any] = {}
        self.states: list[str] = []

    async def save_proposal(self, thread_id, proposal, decision, reason):  # type: ignore[no-untyped-def]
        self.row = {"id": "p1", "version": 1, **proposal}
        return self.row

    async def escalate(self, thread_id, reason):  # type: ignore[no-untyped-def]
        self.states.append("escalated")

    async def load_proposal(self, thread_id):  # type: ignore[no-untyped-def]
        return self.row

    async def mark(self, thread_id, state, result=None):  # type: ignore[no-untyped-def]
        self.states.append(state)


async def test_interrupt_then_approve_executes_once() -> None:
    sb, store = FakeSandbox(), Store()
    g = build_graph(Deps(FakeLLM(), sb, store, POLICY), MemorySaver())
    cfg = {"configurable": {"thread_id": "th1"}}
    inp = {"thread_id": "th1", "account_id": "a", "message": "nimekatwa mara mbili KES 1,200"}
    await g.ainvoke(inp, cfg)
    assert sb.calls == []  # paused at review, nothing executed
    out = await g.ainvoke(Command(resume={"decision": "approved"}), cfg)
    assert len(sb.calls) == 1 and store.states == ["executed"]
    assert "executed" in out["outcome"]


async def test_reject_never_executes() -> None:
    sb, store = FakeSandbox(), Store()
    g = build_graph(Deps(FakeLLM(), sb, store, POLICY), MemorySaver())
    cfg = {"configurable": {"thread_id": "th2"}}
    await g.ainvoke({"thread_id": "th2", "account_id": "a", "message": "charged twice 1200"}, cfg)
    await g.ainvoke(Command(resume={"decision": "rejected"}), cfg)
    assert sb.calls == []


class EmptyLedgerSandbox(FakeSandbox):
    async def get_context(self, account_id: str) -> dict[str, Any]:
        return {"transactions": []}


async def test_money_request_without_draftable_proposal_escalates_to_human() -> None:
    sb, store = EmptyLedgerSandbox(), Store()
    g = build_graph(Deps(FakeLLM(), sb, store, POLICY), MemorySaver())
    out = await g.ainvoke({"thread_id": "th3", "account_id": "a", "message": "nimekatwa mara mbili"},
                          {"configurable": {"thread_id": "th3"}})
    assert store.states == ["escalated"] and sb.calls == []
    assert out["decision"] == "escalated"


async def test_non_financial_message_does_not_escalate() -> None:
    sb, store = FakeSandbox(), Store()
    g = build_graph(Deps(FakeLLM(), sb, store, POLICY), MemorySaver())
    out = await g.ainvoke({"thread_id": "th4", "account_id": "a", "message": "how do I reset my pin"},
                          {"configurable": {"thread_id": "th4"}})
    assert store.states == [] and out["decision"] == "none"
