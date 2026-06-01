"""Authentication + tenancy seam (Clerk, with a dev fallback).

When Clerk is configured (`SEO_CLERK_JWKS_URL` set), requests are authenticated
from a ``Authorization: Bearer <session-jwt>`` token: the JWT is verified against
Clerk's JWKS, and org + role come from its claims. When Clerk is NOT configured,
the app runs in self-hosted dev mode and resolves org/role from the
``X-Organization-Id`` / ``X-User-Role`` headers (default owner / default org).

Both paths funnel through `get_auth_context`, so every endpoint's
``Depends(require_role(...))`` / ``Depends(get_current_org_id)`` works the same
either way — turning on Clerk changes nothing at the call sites.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import IntEnum
from functools import lru_cache

import jwt
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.exceptions import (
    BadRequestError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)
from app.db import repositories as repo
from app.db.base import get_session


class Role(IntEnum):
    VIEWER = 1
    EDITOR = 2
    ADMIN = 3
    OWNER = 4


_BY_NAME = {r.name.lower(): r for r in Role}


def parse_role(value: str) -> Role:
    role = _BY_NAME.get(value.strip().lower())
    if role is None:
        raise BadRequestError(f"Unknown role {value!r}. Valid: {sorted(_BY_NAME)}.")
    return role


def _map_clerk_role(org_role: str | None) -> Role:
    """Map a Clerk org role (e.g. 'org:admin', 'admin', 'basic_member') -> Role."""
    if not org_role:
        return Role.VIEWER
    text = org_role.lower()
    if "admin" in text:
        return Role.ADMIN
    if "member" in text:
        return Role.EDITOR
    return Role.VIEWER


@dataclass
class AuthContext:
    org_id: uuid.UUID
    role: Role
    user_id: str | None = None


class ClerkVerifier:
    """Verifies Clerk session JWTs against the instance JWKS (RS256)."""

    def __init__(self, jwks_url: str, issuer: str = "") -> None:
        self.jwks_url = jwks_url
        self.issuer = issuer
        self._client: jwt.PyJWKClient | None = None

    def _signing_key(self, token: str):
        if self._client is None:
            self._client = jwt.PyJWKClient(self.jwks_url)
        return self._client.get_signing_key_from_jwt(token).key

    def verify(self, token: str, *, signing_key=None) -> dict:
        key = signing_key if signing_key is not None else self._signing_key(token)
        kwargs: dict = {"algorithms": ["RS256"], "options": {"verify_aud": False}}
        if self.issuer:
            kwargs["issuer"] = self.issuer
        try:
            return jwt.decode(token, key, **kwargs)
        except jwt.PyJWTError as exc:
            raise UnauthorizedError(
                "Invalid or expired token.", detail=str(exc)
            ) from exc


@lru_cache
def _verifier(jwks_url: str, issuer: str) -> ClerkVerifier:
    return ClerkVerifier(jwks_url, issuer)


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return None


async def get_auth_context(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> AuthContext:
    if settings.clerk_enabled:
        token = _bearer(request)
        if not token:
            raise UnauthorizedError("Authentication required.")
        claims = _verifier(settings.clerk_jwks_url, settings.clerk_issuer).verify(token)
        clerk_org = claims.get("org_id")
        role = _map_clerk_role(claims.get("org_role"))
        if clerk_org:
            org = await repo.get_or_create_org_by_clerk(
                session, clerk_org, name=claims.get("org_slug") or "Organization"
            )
        else:
            org = await repo.get_or_create_default_org(session)
        return AuthContext(org_id=org.id, role=role, user_id=claims.get("sub"))

    # --- Dev fallback: header-based role/org (no Clerk configured) ---
    role = parse_role(request.headers.get("x-user-role", "owner"))
    org_header = request.headers.get("x-organization-id")
    if org_header:
        try:
            oid = uuid.UUID(org_header)
        except ValueError as exc:
            raise NotFoundError("Invalid X-Organization-Id.") from exc
        org = await repo.get_organization(session, oid)
        if org is None:
            raise NotFoundError(f"Organization {oid} not found.")
        return AuthContext(org_id=org.id, role=role)
    org = await repo.get_or_create_default_org(session)
    return AuthContext(org_id=org.id, role=role)


async def get_current_org_id(
    ctx: AuthContext = Depends(get_auth_context),
) -> uuid.UUID:
    return ctx.org_id


def require_role(minimum: Role):
    """Dependency factory: require at least ``minimum`` role."""

    async def _dependency(ctx: AuthContext = Depends(get_auth_context)) -> Role:
        if ctx.role < minimum:
            raise ForbiddenError(
                f"This action requires the '{minimum.name.lower()}' role or higher; "
                f"you have '{ctx.role.name.lower()}'."
            )
        return ctx.role

    return _dependency
