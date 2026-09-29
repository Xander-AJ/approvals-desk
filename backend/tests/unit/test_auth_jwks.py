"""RS256 / JWKS verification (the production path): tokens come from the web app's issuer, keys from its JWKS."""
import base64
import json
import time
import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.api.main import create_app
from app.auth import JwksCache
from app.config import Settings

JWKS_URL = "https://console.example.com/.well-known/jwks.json"
ISS, AUD = "https://console.example.com", "approvals-api"
TENANT = uuid.uuid4()


def _key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(private: rsa.RSAPrivateKey, kid: str) -> dict[str, Any]:
    d = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    return {**d, "kid": kid, "use": "sig", "alg": "RS256"}


def _token(private: Any, kid: str | None = "k1", *, alg: str = "RS256", **over: Any) -> str:
    claims = {"sub": "github:42", "tenant_id": str(TENANT), "role": "agent", "iss": ISS, "aud": AUD,
              "exp": int(time.time()) + 600, **over}
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, private, algorithm=alg, headers={"kid": kid} if kid else {})


class Idp:
    """A fake identity provider's JWKS endpoint that counts fetches and can fail."""

    def __init__(self, *keys: tuple[str, rsa.RSAPrivateKey]) -> None:
        self.keys = list(keys)
        self.fetches = 0
        self.down = False

    def handler(self, req: httpx.Request) -> httpx.Response:
        self.fetches += 1
        if self.down:
            return httpx.Response(503)
        return httpx.Response(200, json={"keys": [_jwk(k, kid) for kid, k in self.keys]})


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def _app(idp: Idp, clock: Clock | None = None, **settings: Any) -> Any:
    http = httpx.AsyncClient(transport=httpx.MockTransport(idp.handler))
    app = create_app(Settings(jwt_jwks_url=JWKS_URL, jwt_issuer=ISS, jwt_audience=AUD, jwt_secret=None, **settings),
                     SimpleNamespace(engine=None), http=http)  # type: ignore[arg-type]
    if clock:
        app.state.jwks = JwksCache(JWKS_URL, http, clock=clock)
    return app


async def _status(app: Any, token: str) -> int:
    """401/403/503 = rejected by auth. 422 = authenticated (the deliberately invalid body is then rejected)."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/tickets", json={"customer_ref": "../x", "message": "m"},
                         headers={"Authorization": f"Bearer {token}"})
        return r.status_code


async def test_valid_rs256_token_is_accepted() -> None:
    k = _key()
    assert await _status(_app(Idp(("k1", k))), _token(k)) == 422


@pytest.mark.parametrize("bad", [
    {"aud": "some-other-service"}, {"aud": None}, {"iss": "https://evil.example.com"}, {"exp": int(time.time()) - 5},
    {"exp": None}, {"sub": None}, {"role": "superuser"}, {"tenant_id": "not-a-uuid"}, {"tenant_id": None},
])
async def test_claims_are_enforced(bad: dict[str, Any]) -> None:
    k = _key()
    status = await _status(_app(Idp(("k1", k))), _token(k, **bad))
    assert status in (401, 403), bad


async def test_a_token_signed_by_a_different_key_under_a_known_kid_is_rejected() -> None:
    real, attacker = _key(), _key()
    assert await _status(_app(Idp(("k1", real))), _token(attacker, "k1")) == 401


async def test_algorithm_confusion_is_rejected() -> None:
    """Classic attack: sign HS256 using the (public) RSA key as the HMAC secret, or use alg=none."""
    k = _key()
    public_pem = k.public_key().public_bytes(serialization.Encoding.PEM,
                                             serialization.PublicFormat.SubjectPublicKeyInfo)
    app = _app(Idp(("k1", k)))
    now = int(time.time()) + 600
    claims = {"sub": "x", "tenant_id": str(TENANT), "role": "admin", "iss": ISS, "aud": AUD, "exp": now}
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    import hashlib
    import hmac
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": "k1"}).encode())
    body = b64(json.dumps(claims).encode())
    sig = b64(hmac.new(public_pem, f"{head}.{body}".encode(), hashlib.sha256).digest())
    assert await _status(app, f"{head}.{body}.{sig}") == 401
    none_head = b64(json.dumps({"alg": "none", "typ": "JWT", "kid": "k1"}).encode())
    assert await _status(app, f"{none_head}.{body}.") == 401


@pytest.mark.parametrize("kid", [None, "nope"])
async def test_missing_or_unknown_kid_is_rejected(kid: str | None) -> None:
    k = _key()
    assert await _status(_app(Idp(("k1", k))), _token(k, kid)) == 401


async def test_dev_hs256_tokens_are_not_accepted_in_jwks_mode() -> None:
    k = _key()
    dev = jwt.encode({"sub": "u", "tenant_id": str(TENANT), "role": "admin", "iss": ISS, "aud": AUD,
                      "exp": int(time.time()) + 60}, "x" * 40, algorithm="HS256", headers={"kid": "k1"})
    assert await _status(_app(Idp(("k1", k))), dev) == 401


async def test_keys_are_cached_across_requests() -> None:
    k, idp = _key(), Idp(("k1", _key()))
    idp.keys = [("k1", k)]
    app = _app(idp)
    for _ in range(25):
        assert await _status(app, _token(k)) == 422
    assert idp.fetches == 1


async def test_random_key_ids_cannot_make_us_hammer_the_idp() -> None:
    k, idp, clock = _key(), Idp(), Clock()
    idp.keys = [("k1", k)]
    app = _app(idp, clock)
    assert await _status(app, _token(k)) == 422
    baseline = idp.fetches
    for i in range(50):  # attacker-controlled kids
        await _status(app, _token(k, f"random-{i}"))
    assert idp.fetches == baseline  # within min_refresh: zero extra fetches
    clock.t += 31
    for i in range(50):
        await _status(app, _token(k, f"more-{i}"))
    assert idp.fetches == baseline + 1  # one refresh per window, however many bad kids


async def test_key_rotation_is_picked_up_after_the_refresh_window() -> None:
    old, new, idp, clock = _key(), _key(), Idp(), Clock()
    idp.keys = [("old", old)]
    app = _app(idp, clock)
    assert await _status(app, _token(old, "old")) == 422
    idp.keys = [("old", old), ("new", new)]
    assert await _status(app, _token(new, "new")) == 401  # too soon to refetch
    clock.t += 31
    assert await _status(app, _token(new, "new")) == 422
    assert await _status(app, _token(old, "old")) == 422  # both valid during the overlap


async def test_idp_outage_is_a_503_not_a_401_and_recovers() -> None:
    k, idp, clock = _key(), Idp(), Clock()
    idp.keys, idp.down = [("k1", k)], True
    app = _app(idp, clock)
    assert await _status(app, _token(k)) == 503
    before = idp.fetches
    assert await _status(app, _token(k)) == 503
    assert idp.fetches == before  # backing off, not retrying on every request
    idp.down = False
    clock.t += 31
    assert await _status(app, _token(k)) == 422


async def test_cached_keys_keep_working_through_an_idp_outage() -> None:
    k, idp, clock = _key(), Idp(), Clock()
    idp.keys = [("k1", k)]
    app = _app(idp, clock)
    assert await _status(app, _token(k)) == 422
    idp.down = True
    clock.t += 600  # past the TTL: a refresh is attempted, fails, and the stale key is still used
    assert await _status(app, _token(k)) == 422


def test_jwks_mode_requires_an_audience() -> None:
    with pytest.raises(ValueError, match="AUDIENCE"):
        create_app(Settings(jwt_jwks_url=JWKS_URL, jwt_issuer=ISS, jwt_secret=None),
                   SimpleNamespace(engine=None))  # type: ignore[arg-type]


def test_webhook_url_requires_an_explicit_signing_secret() -> None:
    with pytest.raises(ValueError, match="WEBHOOK_SECRET"):
        create_app(Settings(webhook_url="https://hooks.example.com/x", webhook_secret=None),
                   SimpleNamespace(engine=None))  # type: ignore[arg-type]
    create_app(Settings(webhook_url="https://hooks.example.com/x", webhook_secret="s3cret"),
               SimpleNamespace(engine=None))  # type: ignore[arg-type]
