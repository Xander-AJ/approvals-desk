import time
import uuid
from types import SimpleNamespace

import httpx
import jwt
import pytest

from app.api.main import create_app
from app.auth import mint_token
from app.config import Settings

S = Settings()
TENANT = uuid.uuid4()


async def _status(token: str) -> int:
    app = create_app(S, SimpleNamespace(engine=None))  # type: ignore[arg-type]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        return (await c.get("/policy", headers={"Authorization": f"Bearer {token}"})).status_code


def _raw(**over: object) -> str:
    claims = {"sub": "u", "tenant_id": str(TENANT), "role": "agent", "iss": S.jwt_issuer, "exp": int(time.time()) + 60}
    claims.update(over)
    return jwt.encode({k: v for k, v in claims.items() if v is not None}, S.jwt_secret, algorithm="HS256")


async def test_expired_token_rejected() -> None:
    assert await _status(_raw(exp=int(time.time()) - 10)) == 401


async def test_token_without_exp_rejected() -> None:
    assert await _status(_raw(exp=None)) == 401


async def test_wrong_issuer_and_bad_signature_rejected() -> None:
    assert await _status(_raw(iss="evil")) == 401
    assert await _status(jwt.encode({"sub": "u"}, "x" * 40, algorithm="HS256")) == 401


async def test_unknown_role_rejected() -> None:
    assert await _status(_raw(role="superuser")) == 403


def test_minted_token_has_expiry() -> None:
    claims = jwt.decode(mint_token(S, "u", TENANT, "agent"), S.jwt_secret, algorithms=["HS256"], issuer=S.jwt_issuer)
    assert claims["exp"] > time.time()


def test_dev_auth_with_jwks_is_refused() -> None:
    with pytest.raises(ValueError):
        create_app(Settings(dev_auth=True, jwt_jwks_url="https://idp/.well-known/jwks.json"),
                   SimpleNamespace(engine=None))  # type: ignore[arg-type]
