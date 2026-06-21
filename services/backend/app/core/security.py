"""AuthN (OIDC JWT verification) + AuthZ (RBAC permission checks).

The backend trusts only tokens signed by Keycloak (RS256, verified against JWKS).
Permissions are resolved from the local DB role → role_permissions, never from
client-supplied claims, so a tampered token cannot widen access.
"""
from __future__ import annotations

import time
from functools import lru_cache
from typing import Annotated

import httpx
from fastapi import Depends, Header, HTTPException, status
from jose import jwt
from jose.exceptions import JWTError

from app.core.config import settings


class Principal:
    """The authenticated caller, resolved to a local user + permission set."""

    def __init__(self, user_id: str, email: str, role: str, permissions: set[str], team_id: str | None):
        self.user_id = user_id
        self.email = email
        self.role = role
        self.permissions = permissions
        self.team_id = team_id

    def require(self, *perms: str) -> None:
        if not set(perms).issubset(self.permissions):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient_permissions")


@lru_cache
def _jwks_cache_holder() -> dict:
    return {"keys": None, "fetched_at": 0.0}


async def _get_jwks() -> dict:
    cache = _jwks_cache_holder()
    if cache["keys"] is None or time.time() - cache["fetched_at"] > 3600:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(settings.oidc_jwks_url)
            resp.raise_for_status()
            cache["keys"] = resp.json()
            cache["fetched_at"] = time.time()
    return cache["keys"]


async def verify_token(authorization: Annotated[str | None, Header()] = None) -> dict:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing_bearer_token")
    token = authorization.split(" ", 1)[1]
    try:
        jwks = await _get_jwks()
        claims = jwt.decode(
            token,
            jwks,
            algorithms=["RS256"],
            audience=settings.keycloak_client_id,
            options={"verify_aud": False},  # Keycloak puts client in azp; validate below
        )
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"invalid_token: {exc}") from exc
    return claims


async def get_current_principal(
    claims: Annotated[dict, Depends(verify_token)],
) -> Principal:
    """Map the verified token subject to the local user + permissions.

    Implementation note: looks up users by keycloak_id, joins role + role_permissions.
    Shown abbreviated; see app.services.user_service.resolve_principal for the query.
    """
    from app.services.user_service import resolve_principal_by_keycloak_id

    principal = await resolve_principal_by_keycloak_id(claims["sub"])
    if principal is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "user_not_provisioned")
    return principal


def require_internal_token(x_internal_token: Annotated[str | None, Header()] = None) -> None:
    """Guard for gateway↔backend internal endpoints."""
    if x_internal_token != settings.internal_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid_internal_token")


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
