from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any


class Decision(StrEnum):
    AUTO_APPROVE = "auto_approve"
    REVIEW = "review"
    BLOCK = "block"


@dataclass(frozen=True)
class Policy:
    auto_approve_max: Decimal
    hard_limit: Decimal
    max_auto_risk: int
    allowed_actions: frozenset[str]


# Our own prompt delimiters can never appear in a genuine customer message; seeing them means someone is
# trying to break out of the <customer> block.
_TAMPER = re.compile(r"</?\s*(customer|ledger)\b", re.I)


def is_tampered(message: str) -> bool:
    return bool(_TAMPER.search(message))


def verify_claim(action_type: str, amount: Decimal, transactions: list[dict[str, Any]]) -> bool:
    """Deterministic check against the ledger, independent of anything the model or customer said:
    a refund is 'verified' only when at least two charges of exactly that amount exist (a real duplicate).
    Reversals and fee waivers cannot be verified from the ledger, so they are never auto-approvable."""
    if action_type != "refund":
        return False
    same = [t for t in transactions if t.get("kind") == "charge" and Decimal(str(t["amount"])) == amount]
    return len(same) >= 2


def evaluate(policy: Policy, action_type: str, amount: Decimal, risk_score: int, *, verified: bool = False,
             tampered: bool = False) -> tuple[Decision, str]:
    """Pure policy check. BLOCK proposals are never executable, even with human approval.

    Auto-approval requires `verified` (ledger-confirmed by code) and an untampered message; the model's
    risk_score alone can lower scrutiny only for claims that are already verified."""
    if action_type not in policy.allowed_actions:
        return Decision.BLOCK, f"action {action_type} not allowed for tenant"
    if amount > policy.hard_limit:
        return Decision.BLOCK, f"amount exceeds hard limit {policy.hard_limit}"
    if tampered:
        return Decision.REVIEW, "message contains prompt-delimiter tampering"
    if not verified:
        return Decision.REVIEW, "claim not verified against the ledger"
    if amount <= policy.auto_approve_max and risk_score <= policy.max_auto_risk:
        return Decision.AUTO_APPROVE, "verified duplicate within auto-approve threshold and risk tier"
    return Decision.REVIEW, "requires human review"
