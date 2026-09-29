from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any

import httpx
import jwt
from fastapi import Depends, Header, HTTPException, Request

from app.config import Settings


@dataclass(frozen=True)
class Principal:
    user: str
    tenant_id: uuid.UUID
    role: str  # agent | reviewer | admin


class JwksUnavailable(Exception):
    """The key set could not be fetched and nothing is cached: an outage, not a bad token."""


class JwksCache:
    """Async JWKS resolver: cached for `ttl`, one forced refresh per `min_refresh` (so random `kid`s cannot make
    us hammer the IdP), and stale keys keep working if a refresh fails."""

    def __init__(self, url: str, http: httpx.AsyncClient, ttl: float = 300.0, min_refresh: float = 30.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.url, self.http, self.ttl, self.min_refresh, self._clock = url, http, ttl, min_refresh, clock
        self._keys: dict[str, Any] = {}
        self._fetched_at = 0.0
        self._next_attempt = 0.0  # no fetch before this (monotonic): bounds load on the IdP whatever callers send
        self._lock = asyncio.Lock()

    async def _refresh(self) -> None:
        r = await self.http.get(self.url, timeout=5)
        r.raise_for_status()
        keys: dict[str, Any] = {}
        for jwk in r.json().get("keys", []):
            if jwk.get("kty") == "RSA" and jwk.get("kid") and jwk.get("use", "sig") == "sig":
                keys[jwk["kid"]] = jwt.PyJWK(jwk).key
        self._keys, self._fetched_at = keys, self._clock()

    async def key(self, kid: str) -> Any | None:
        async with self._lock:
            now = self._clock()
            need = not self._keys or now - self._fetched_at > self.ttl or kid not in self._keys
            if need and now >= self._next_attempt:
                self._next_attempt = now + self.min_refresh
                try:
                    await self._refresh()
                except (httpx.HTTPError, ValueError, jwt.PyJWTError) as e:
                    if not self._keys:
                        raise JwksUnavailable from e
                    # keep serving the keys we have; the next attempt is allowed after min_refresh
            elif not self._keys:
                raise JwksUnavailable  # still backing off after a failed first fetch
            return self._keys.get(kid)


def mint_token(settings: Settings, user: str, tenant_id: uuid.UUID, role: str) -> str:
    """Dev issuer only. Production tokens come from the OIDC provider."""
    assert settings.jwt_secret, "jwt_secret required to mint dev tokens"
    return jwt.encode({"sub": user, "tenant_id": str(tenant_id), "role": role, "iss": settings.jwt_issuer,
                       "exp": int(time.time()) + 3600},
                      settings.jwt_secret, algorithm="HS256")


async def _claims(request: Request, token: str) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    if settings.jwt_jwks_url:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "RS256" or not header.get("kid"):  # pins the algorithm: no HS256/none confusion
            raise jwt.InvalidAlgorithmError("expected RS256 with a kid")
        key = await request.app.state.jwks.key(header["kid"])
        if key is None:
            raise jwt.InvalidKeyError("unknown signing key")
        claims: dict[str, Any] = jwt.decode(
            token, key, algorithms=["RS256"], issuer=settings.jwt_issuer, audience=settings.jwt_audience,
            options={"require": ["exp", "sub", "aud", "iss"]})
        return claims
    assert settings.jwt_secret
    claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], issuer=settings.jwt_issuer,
                        options={"require": ["exp", "sub"]})
    return claims


async def principal(request: Request, authorization: Annotated[str | None, Header()] = None) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    try:
        c = await _claims(request, authorization[7:])
        p = Principal(str(c["sub"]), uuid.UUID(str(c["tenant_id"])), str(c["role"]))
    except JwksUnavailable as e:
        raise HTTPException(503, "identity provider keys are unavailable; try again shortly") from e
    except (jwt.PyJWTError, KeyError, ValueError) as e:
        raise HTTPException(401, "invalid token") from e
    if p.role not in {"agent", "reviewer", "admin"}:
        raise HTTPException(403, "unknown role")
    return p


def require(*roles: str):  # type: ignore[no-untyped-def]
    async def dep(p: Annotated[Principal, Depends(principal)]) -> Principal:
        if p.role not in roles:
            raise HTTPException(403, f"role {p.role} not permitted")
        return p
    return dep
