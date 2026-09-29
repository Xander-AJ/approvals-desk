from __future__ import annotations

from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from testcontainers.postgres import PostgresContainer

from app.db.models import Base
from app.db.rls import rls_statements


@pytest.fixture(scope="session")
def pg() -> Iterator[PostgresContainer]:
    with PostgresContainer("postgres:16", driver="asyncpg") as c:
        yield c


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engines(pg: PostgresContainer) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    owner_url = pg.get_connection_url()
    owner = create_async_engine(owner_url)
    async with owner.begin() as c:
        await c.execute(text("CREATE ROLE app_user LOGIN PASSWORD 'app_user' NOSUPERUSER NOBYPASSRLS"))
        await c.run_sync(Base.metadata.create_all)
        for s in rls_statements():
            await c.execute(text(s))
    app_url = owner_url.replace(f"{pg.username}:{pg.password}", "app_user:app_user")
    app = create_async_engine(app_url)
    yield owner, app
    await owner.dispose()
    await app.dispose()
