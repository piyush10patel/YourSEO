"""Role-based access control (spec §26).

Four ordered roles: viewer < editor < admin < owner. `require_role(min_role)`
is a FastAPI dependency that rejects callers below the threshold.

Until real auth (Clerk) is wired, the caller's role comes from an optional
``X-User-Role`` header (default ``owner`` for local dev). Swapping in Clerk
later means changing only `current_role` to read the verified membership —
every endpoint's ``Depends(require_role(...))`` stays the same.
"""

from __future__ import annotations

from enum import IntEnum

from fastapi import Header

from app.core.exceptions import BadRequestError, ForbiddenError


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


def current_role(x_user_role: str = Header(default="owner")) -> Role:
    """Resolve the caller's role (header today; Clerk membership later)."""
    return parse_role(x_user_role)


def require_role(minimum: Role):
    """Dependency factory: require at least ``minimum`` role."""

    def _dependency(x_user_role: str = Header(default="owner")) -> Role:
        resolved = parse_role(x_user_role)
        if resolved < minimum:
            raise ForbiddenError(
                f"This action requires the '{minimum.name.lower()}' role or higher; "
                f"you have '{resolved.name.lower()}'."
            )
        return resolved

    return _dependency
