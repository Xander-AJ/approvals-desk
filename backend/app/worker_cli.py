"""One-shot recovery runner (used by the chaos test and for manual ops).

CRASH_AFTER_MUTATE=1 is a test-only fault injector: the process dies right after the sandbox
accepted the money movement but before the run's state was recorded — the worst-case window."""
from __future__ import annotations

import asyncio
import os
import sys
from decimal import Decimal
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.config import Settings
from app.services.runs import recover_runs
from app.worker import all_tenants, build_runtime


class CrashingSandbox:
    def __init__(self, inner: Any) -> None:
        self.inner = inner

    async def get_context(self, account_id: str) -> dict[str, Any]:
        return await self.inner.get_context(account_id)  # type: ignore[no-any-return]

    async def mutate(self, action_type: str, account_id: str, amount: Decimal, key: str) -> dict[str, Any]:
        await self.inner.mutate(action_type, account_id, amount, key)
        os._exit(137)


async def main() -> None:
    settings = Settings()
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_dsn) as saver:
        await saver.setup()
        rt = build_runtime(settings, saver)
        if os.environ.get("CRASH_AFTER_MUTATE") == "1":
            rt.sandbox = CrashingSandbox(rt.sandbox)
        n = await recover_runs(rt, await all_tenants(rt))
        print(f"recovered={n}")


if __name__ == "__main__":
    asyncio.run(main())
    sys.exit(0)
