from __future__ import annotations

from decimal import Decimal
from typing import Any
from urllib.parse import quote

import httpx

_PATHS = {"refund": "/refunds", "reversal": "/reversals", "fee_waiver": "/fee-waivers"}


class HttpSandbox:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.c = client

    async def get_context(self, account_id: str) -> dict[str, Any]:
        r = await self.c.get(f"/accounts/{quote(account_id, safe='')}/transactions")
        r.raise_for_status()
        return {"account_id": account_id, "transactions": r.json()}

    async def mutate(self, action_type: str, account_id: str, amount: Decimal, key: str) -> dict[str, Any]:
        r = await self.c.post(_PATHS[action_type], json={"account_id": account_id, "amount": str(amount)},
                              headers={"Idempotency-Key": key})
        r.raise_for_status()
        out: dict[str, Any] = r.json()
        return out
