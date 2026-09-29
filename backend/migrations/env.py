import asyncio
import os

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.models import Base

target_metadata = Base.metadata
URL = os.environ["MIGRATION_DATABASE_URL"]  # owner role, not the RLS-bound app role


def _run(conn):  # type: ignore[no-untyped-def]
    context.configure(connection=conn, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def main() -> None:
    engine = create_async_engine(URL)
    async with engine.connect() as c:
        await c.run_sync(_run)
    await engine.dispose()


asyncio.run(main())
