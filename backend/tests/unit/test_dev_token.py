import uuid
from types import SimpleNamespace

import httpx

from app.api.main import create_app
from app.config import Settings


async def test_dev_token_endpoint_accepts_json_body_and_issues_usable_token() -> None:
    settings = Settings(dev_auth=True)
    app = create_app(settings, SimpleNamespace(engine=None))  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/dev/token", json={"tenant_id": str(uuid.uuid4()), "role": "agent", "user": "a"})
        assert r.status_code == 200, r.text
        assert r.json()["token"]


async def test_dev_token_absent_when_disabled() -> None:
    app = create_app(Settings(dev_auth=False), SimpleNamespace(engine=None))  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.post("/dev/token", json={})).status_code == 404
