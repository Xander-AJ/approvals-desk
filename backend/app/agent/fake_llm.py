from __future__ import annotations

import re
from decimal import Decimal

from app.agent.schemas import ActionProposal, Evidence

_DOUBLE = re.compile(r"double|twice|mara mbili|imekata mara|zimekatwa", re.I)
_FEE = re.compile(r"fee|charge.*wrong|makato", re.I)
_REV = re.compile(r"reverse|wrong number|nimetuma vibaya|sent.*wrong", re.I)
_AMT = re.compile(r"(?:kes|ksh)?\s*([\d,]{3,})", re.I)


class FakeLLM:
    """Rule-based stand-in with the same interface as the real model (Sheng-aware)."""

    async def classify(self, message: str) -> str:
        if _DOUBLE.search(message):
            return "refund"
        if _REV.search(message):
            return "reversal"
        if _FEE.search(message):
            return "fee_waiver"
        return "other"

    async def draft(self, message: str, context: dict) -> ActionProposal | None:  # type: ignore[type-arg]
        kind = await self.classify(message)
        if kind == "other":
            return None
        m = _AMT.search(message)
        txns = context.get("transactions", [])
        amount = Decimal(m.group(1).replace(",", "")) if m else Decimal(txns[-1]["amount"] if txns else 0)
        if amount <= 0:
            return None
        matches = [t for t in txns if Decimal(t["amount"]) == amount and t["kind"] == "charge"]
        evidence = [Evidence(source="ledger", detail=f"charge {t['id']} of {t['amount']}") for t in matches]
        risk = 10 if len(matches) >= 2 else 45
        return ActionProposal(
            action_type=kind, amount=amount, reason=message[:200], evidence=evidence or
            [Evidence(source="customer", detail="claim unverified")], risk_score=risk,
            reference_txn=matches[-1]["id"] if matches else None,
        )

    async def reply(self, message: str, outcome: str) -> str:
        return f"Update on your request: {outcome}"
