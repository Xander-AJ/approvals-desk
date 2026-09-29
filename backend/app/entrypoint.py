"""Production ASGI entrypoint: `uvicorn app.entrypoint:app`."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.api.main import create_app
from app.config import Settings
from app.telemetry import setup_tracing
from app.worker import build_runtime

settings = Settings()
setup_tracing("approvals-api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_dsn) as saver:
        await saver.setup()
        queue = await create_pool(RedisSettings.from_dsn(settings.redis_url)) if settings.async_resume else None
        inner = create_app(settings, build_runtime(settings, saver), queue)
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(inner)
        app.mount("/", inner)
        yield


app = FastAPI(lifespan=lifespan)
