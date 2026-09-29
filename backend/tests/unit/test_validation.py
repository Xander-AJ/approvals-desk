import uuid
from types import SimpleNamespace

import httpx
import pytest

from app.api.main import create_app
from app.auth import mint_token
from app.config import Settings
from app.services.sandbox_client import HttpSandbox

S = Settings()
TENANT = uuid.uuid4()


def _client(role: str = "admin") -> httpx.AsyncClient:
    app = create_app(S, SimpleNamespace(engine=None))  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t",
                             headers={"Authorization": f"Bearer {mint_token(S, role, TENANT, role)}"})


GOOD_POLICY = {"auto_approve_max": "500", "hard_limit": "50000", "max_auto_risk": 30,
               "allowed_actions": ["refund"], "sla_minutes": 60}


@pytest.mark.parametrize("ref", ["../ledger", "a/b", ".hidden", "..", "", "x" * 65, "a b", "a?b=1", "a#b"])
async def test_customer_ref_that_could_alter_the_sandbox_path_is_rejected(ref: str) -> None:
    async with _client("agent") as c:
        r = await c.post("/tickets", json={"customer_ref": ref, "message": "hi"})
        assert r.status_code == 422, ref


@pytest.mark.parametrize("limit", ["0", "-1", "501", "abc"])
async def test_list_limit_is_bounded(limit: str) -> None:
    async with _client("reviewer") as c:
        assert (await c.get(f"/proposals?limit={limit}")).status_code == 422


@pytest.mark.parametrize("amount", ["0", "-5", "1000000000000", "12.345", "abc"])
async def test_edit_amount_is_bounded_to_what_the_column_can_hold(amount: str) -> None:
    async with _client("reviewer") as c:
        r = await c.post(f"/proposals/{uuid.uuid4()}/edit", json={"amount": amount})
        assert r.status_code == 422, amount


@pytest.mark.parametrize("patch", [
    {"allowed_actions": ["refund", "wire_transfer"]},
    {"auto_approve_max": "60000"},  # above hard_limit
    {"auto_approve_max": "-1"},
    {"hard_limit": "0"},
    {"hard_limit": "1e30"},
    {"max_auto_risk": 101},
    {"sla_minutes": 0},
    {"sla_minutes": 10**9},
])
async def test_policy_rejects_invalid_values(patch: dict[str, object]) -> None:
    async with _client("admin") as c:
        assert (await c.put("/policy", json={**GOOD_POLICY, **patch})).status_code == 422, patch


async def test_sandbox_client_percent_encodes_account_ids() -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.raw_path.decode())
        return httpx.Response(200, json=[])

    sb = HttpSandbox(httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://sb"))
    await sb.get_context("../ledger?x=1")
    assert seen == ["/accounts/..%2Fledger%3Fx%3D1/transactions"]
