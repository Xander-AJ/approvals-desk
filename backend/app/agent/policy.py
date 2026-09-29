from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


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


def evaluate(policy: Policy, action_type: str, amount: Decimal, risk_score: int) -> tuple[Decision, str]:
    """Pure policy check. BLOCK proposals are never executable, even with human approval."""
    if action_type not in policy.allowed_actions:
        return Decision.BLOCK, f"action {action_type} not allowed for tenant"
    if amount > policy.hard_limit:
        return Decision.BLOCK, f"amount exceeds hard limit {policy.hard_limit}"
    if amount <= policy.auto_approve_max and risk_score <= policy.max_auto_risk:
        return Decision.AUTO_APPROVE, "within auto-approve threshold and risk tier"
    return Decision.REVIEW, "requires human review"
