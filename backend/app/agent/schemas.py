from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

ActionType = Literal["refund", "reversal", "fee_waiver"]


class Evidence(BaseModel):
    source: str
    detail: str


class ActionProposal(BaseModel):
    action_type: ActionType
    amount: Decimal = Field(gt=0)
    currency: str = "KES"
    reason: str
    evidence: list[Evidence]
    risk_score: int = Field(ge=0, le=100)
    reference_txn: str | None = None
