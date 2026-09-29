from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True)


@asynccontextmanager
async def tenant_session(engine: AsyncEngine, tenant_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """Session whose transaction is bound to a tenant via app.tenant_id (RLS)."""
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
        )
        yield session
