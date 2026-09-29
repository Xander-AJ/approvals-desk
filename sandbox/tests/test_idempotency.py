import asyncio

import httpx
import pytest

from pesa.app import Base, create_app


@pytest.fixture
async def client(tmp_path):
    app = create_app(f"sqlite+aiosqlite:///{tmp_path}/s.db")
    async with app.state.engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        await c.post("/dev/seed", json={"account_id": "a1", "balance": "0", "txns": [{"id": "x1", "amount": "1200"}]})
        yield c


async def test_replay_returns_original_and_single_ledger_entry(client):
    body = {"account_id": "a1", "amount": "1200"}
    r1 = await client.post("/refunds", json=body, headers={"Idempotency-Key": "k1"})
    r2 = await client.post("/refunds", json=body, headers={"Idempotency-Key": "k1"})
    assert r1.json()["txn_id"] == r2.json()["txn_id"]
    assert r2.json()["replayed"] is True
    assert len((await client.get("/ledger")).json()) == 1
    assert (await client.get("/accounts/a1")).json()["balance"] == "1200.00"


async def test_missing_key_rejected(client):
    r = await client.post("/refunds", json={"account_id": "a1", "amount": "5"})
    assert r.status_code == 400


async def test_distinct_keys_distinct_refunds(client):
    for k in ("k1", "k2"):
        await client.post("/refunds", json={"account_id": "a1", "amount": "5"}, headers={"Idempotency-Key": k})
    assert len((await client.get("/ledger")).json()) == 2
