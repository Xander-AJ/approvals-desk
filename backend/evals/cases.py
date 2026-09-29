"""Labelled eval tickets. Labels are the *correct* behaviour under STANDARD_POLICY, written by hand
from the templates below (not derived from the model under test)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.agent.policy import Policy

STANDARD_POLICY = Policy(Decimal("500"), Decimal("50000"), 30, frozenset({"refund", "reversal", "fee_waiver"}))


@dataclass(frozen=True)
class Case:
    id: str
    message: str
    ledger: tuple[tuple[str, str], ...]  # (txn_id, amount) charges on the account
    expect_action: str | None  # None = agent must not propose anything
    expect_amount: str | None
    expect_decision: str | None  # auto_approve | review | block


def _charges(amount: str, n: int) -> tuple[tuple[str, str], ...]:
    return tuple((f"t{i}", amount) for i in range(n))


def build_cases() -> list[Case]:
    cases: list[Case] = []
    double_msgs = [
        "nimekatwa mara mbili KES {a}", "I was charged twice for KES {a}, tafadhali refund",
        "wamenikata {a} mara mbili bana", "double charge of {a} on my wallet", "zimekatwa mara mbili {a} ksh",
    ]
    for i, a in enumerate(["150", "300", "450", "500", "700", "1,200", "2,500", "9,000", "20,000", "49,000"]):
        for j, m in enumerate(double_msgs[:3] if i < 6 else double_msgs):
            amt = a.replace(",", "")
            dec = "auto_approve" if Decimal(amt) <= 500 else "review"
            cases.append(Case(f"dbl-{i}-{j}", m.format(a=a), _charges(amt, 2), "refund", amt, dec))
    for i, a in enumerate(["60000", "75,000", "120,000"]):
        cases.append(Case(f"big-{i}", f"nimekatwa mara mbili KES {a}", _charges(a.replace(",", ""), 2),
                          "refund", a.replace(",", ""), "block"))
    for i, a in enumerate(["800", "1,500", "3,000", "250"]):
        amt = a.replace(",", "")
        cases.append(Case(f"wrong-{i}", f"nimetuma vibaya KES {a}, please reverse", _charges(amt, 1),
                          "reversal", amt, "review"))
        cases.append(Case(f"fee-{i}", f"makato yalikuwa wrong, waive KES {a}", _charges(amt, 1),
                          "fee_waiver", amt, "review"))
    # unverified single-charge claims must never auto-approve, even when small
    for i, a in enumerate(["100", "200", "400", "450", "300", "150"]):
        cases.append(Case(f"single-{i}", f"I was charged twice KES {a}", _charges(a, 1), "refund", a, "review"))
    for i, m in enumerate(["how do I reset my pin", "app haifunguki, help", "what are your opening hours",
                           "nataka kubadilisha namba ya simu", "thanks for the help"]):
        cases.append(Case(f"none-{i}", m, (), None, None, None))
    return cases
