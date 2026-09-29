import httpx
import pytest

import app.seed as seed


async def test_seed_fails_loudly_on_a_rejected_sandbox_call() -> None:
    sb = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(401)), base_url="http://sb")
    with pytest.raises(httpx.HTTPStatusError):
        await seed._post_with_retry(sb, "/dev/seed", {})


async def test_seed_retries_connection_errors_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(_: float) -> None: ...

    monkeypatch.setattr(seed.asyncio, "sleep", no_sleep)
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ConnectError("sandbox not up yet")
        return httpx.Response(200, json={"ok": "1"})

    sb = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://sb")
    await seed._post_with_retry(sb, "/dev/seed", {})
    assert calls["n"] == 3


async def test_seed_gives_up_after_the_attempt_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_sleep(_: float) -> None: ...

    monkeypatch.setattr(seed.asyncio, "sleep", no_sleep)
    sb = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down"))),
                           base_url="http://sb")
    with pytest.raises(httpx.ConnectError):
        await seed._post_with_retry(sb, "/dev/seed", {}, attempts=3)
