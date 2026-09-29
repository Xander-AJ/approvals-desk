from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, Request

from app.config import Settings


@dataclass(frozen=True)
class Principal:
    user: str
    tenant_id: uuid.UUID
    role: str  # agent | reviewer | admin


def mint_token(settings: Settings, user: str, tenant_id: uuid.UUID, role: str) -> str:
    """Dev issuer only. Production tokens come from the OIDC provider."""
    return jwt.encode({"sub": user, "tenant_id": str(tenant_id), "role": role, "iss": settings.jwt_issuer,
                       "exp": int(time.time()) + 3600},
                      settings.jwt_secret, algorithm="HS256")


def _decode(settings: Settings, token: str) -> dict[str, object]:
    if settings.jwt_jwks_url:
        key = jwt.PyJWKClient(settings.jwt_jwks_url).get_signing_key_from_jwt(token).key
        return jwt.decode(token, key, algorithms=["RS256"], issuer=settings.jwt_issuer,
                          options={"require": ["exp", "sub"]})
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"], issuer=settings.jwt_issuer,
                      options={"require": ["exp", "sub"]})


async def principal(request: Request, authorization: Annotated[str | None, Header()] = None) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing bearer token")
    try:
        c = _decode(request.app.state.settings, authorization[7:])
        p = Principal(str(c["sub"]), uuid.UUID(str(c["tenant_id"])), str(c["role"]))
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
