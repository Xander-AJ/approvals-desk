import httpx
import pytest

from pesa.app import Base, create_app


@pytest.fixture
async def client(tmp_path):
    app = create_app(f"sqlite+aiosqlite:///{tmp_path}/s.db", api_key="k" * 32)
    async with app.state.engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


@pytest.mark.parametrize("path", ["/ledger", "/accounts/a1"])
async def test_reads_require_the_key(client, path):
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers={"X-Sandbox-Key": "wrong"})).status_code == 401


async def test_mutations_and_seed_require_the_key_and_do_nothing_without_it(client):
    body = {"account_id": "a1", "amount": "5"}
    assert (await client.post("/refunds", json=body, headers={"Idempotency-Key": "k"})).status_code == 401
    assert (await client.post("/dev/seed", json={"account_id": "a1"})).status_code == 401
    ok = {"X-Sandbox-Key": "k" * 32}
    assert (await client.post("/dev/seed", json={"account_id": "a1", "balance": "0"}, headers=ok)).status_code == 200
    assert (await client.post("/refunds", json=body, headers={**ok, "Idempotency-Key": "k"})).status_code == 200
    assert len((await client.get("/ledger", headers=ok)).json()) == 1
