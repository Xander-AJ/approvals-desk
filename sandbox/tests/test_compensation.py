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
        await c.post("/dev/seed", json={"account_id": "a2", "balance": "0"})
        yield c


async def _refund(c, key="r1", amount="1200"):
    return (await c.post("/refunds", json={"account_id": "a1", "amount": amount}, headers={"Idempotency-Key": key})).json()


def _comp(c, ref, key="c1", amount="1200", account="a1"):
    return c.post("/compensations", json={"account_id": account, "reference_txn": ref, "amount": amount},
                  headers={"Idempotency-Key": key})


async def test_compensation_debits_the_account_and_links_the_original(client):
    ref = (await _refund(client))["txn_id"]
    assert (await client.get("/accounts/a1")).json()["balance"] == "1200.00"
    r = await _comp(client, ref)
    assert r.status_code == 200 and r.json()["reference_txn"] == ref
    assert (await client.get("/accounts/a1")).json()["balance"] == "0.00"
    kinds = [(x["kind"], x["reference"]) for x in (await client.get("/ledger")).json()]
    assert kinds == [("refund", None), ("compensation", ref)]


async def test_replay_with_same_key_returns_original_and_debits_once(client):
    ref = (await _refund(client))["txn_id"]
    a, b = (await _comp(client, ref)).json(), (await _comp(client, ref)).json()
    assert a["txn_id"] == b["txn_id"] and b["replayed"] is True
    assert (await client.get("/accounts/a1")).json()["balance"] == "0.00"


async def test_a_different_key_cannot_compensate_the_same_transaction_twice(client):
    ref = (await _refund(client))["txn_id"]
    assert (await _comp(client, ref, key="c1")).status_code == 200
    assert (await _comp(client, ref, key="c2")).status_code == 409
    assert (await client.get("/accounts/a1")).json()["balance"] == "0.00"


async def test_concurrent_compensations_debit_once(client):
    ref = (await _refund(client))["txn_id"]
    rs = await asyncio.gather(*[_comp(client, ref, key=f"k{i}") for i in range(4)])
    assert sorted(r.status_code for r in rs).count(200) == 1
    assert (await client.get("/accounts/a1")).json()["balance"] == "0.00"


@pytest.mark.parametrize("case,expected", [("amount", 409), ("account", 404), ("unknown", 404), ("charge", 422), ("nokey", 400)])
async def test_invalid_compensations_are_refused_and_change_nothing(client, case, expected):
    ref = (await _refund(client))["txn_id"]
    kw = {"amount": dict(ref=ref, amount="5"), "account": dict(ref=ref, account="a2"), "unknown": dict(ref="nope"),
          "charge": dict(ref="x1")}.get(case, dict(ref=ref))
    if case == "nokey":
        r = await client.post("/compensations", json={"account_id": "a1", "reference_txn": ref, "amount": "1200"})
    else:
        r = await _comp(client, **kw)
    assert r.status_code == expected
    assert (await client.get("/accounts/a1")).json()["balance"] == "1200.00"
