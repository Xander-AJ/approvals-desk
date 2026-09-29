"""Seed two demo tenants + sandbox accounts. Usage: python -m app.seed"""
from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import text

from app.config import Settings
from app.db.models import TenantPolicy
from app.db.session import make_engine, tenant_session

TENANTS = {
    uuid.UUID("11111111-1111-1111-1111-111111111111"): ("Mzigo Wallet", Decimal("500")),
    uuid.UUID("22222222-2222-2222-2222-222222222222"): ("Duka Marketplace", Decimal("0")),
}


async def _post_with_retry(sb: httpx.AsyncClient, path: str, body: dict[str, Any], attempts: int = 20) -> None:
    """The sandbox may still be booting on a PaaS: retry connection errors only. A 4xx/5xx (bad key, bad request) is
    a real failure and must not be reported as 'seeded'."""
    for n in range(1, attempts + 1):
        try:
            (await sb.post(path, json=body)).raise_for_status()
            return
        except httpx.TransportError:
            if n == attempts:
                raise
            await asyncio.sleep(3)


async def main() -> None:
    s = Settings()
    engine = make_engine(s.database_url)
    async with engine.begin() as c:
        for tid, (name, _) in TENANTS.items():
            await c.execute(text("INSERT INTO tenants (id, name) VALUES (:i, :n) ON CONFLICT DO NOTHING"),
                            {"i": tid, "n": name})
    for tid, (_, auto) in TENANTS.items():
        async with tenant_session(engine, tid) as sess:
            if not await sess.get(TenantPolicy, tid):
                sess.add(TenantPolicy(tenant_id=tid, auto_approve_max=auto, hard_limit=Decimal("50000"),
                                      max_auto_risk=30, allowed_actions=["refund", "reversal", "fee_waiver"],
                                      sla_minutes=60))
    async with httpx.AsyncClient(
            base_url=s.sandbox_url,
            headers={"X-Sandbox-Key": s.sandbox_api_key} if s.sandbox_api_key else {}) as sb:
        for acct in ("wanjiku", "otieno"):
            body = {"account_id": acct, "balance": "0", "txns": [
                {"id": f"{acct}-c1", "amount": "1200", "merchant": "Java House"},
                {"id": f"{acct}-c2", "amount": "1200", "merchant": "Java House"},
                {"id": f"{acct}-c3", "amount": "350", "merchant": "Naivas"}]}
            await _post_with_retry(sb, "/dev/seed", body)
    print("seeded tenants:", ", ".join(f"{n}={t}" for t, (n, _) in TENANTS.items()))


if __name__ == "__main__":
    asyncio.run(main())
