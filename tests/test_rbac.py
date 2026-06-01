"""RBAC role logic tests (spec §26)."""

from __future__ import annotations

import uuid

import pytest

from app.core.auth import AuthContext, Role, parse_role, require_role
from app.core.exceptions import BadRequestError, ForbiddenError


def _ctx(role: Role) -> AuthContext:
    return AuthContext(org_id=uuid.uuid4(), role=role)


def test_role_ordering() -> None:
    assert Role.VIEWER < Role.EDITOR < Role.ADMIN < Role.OWNER


def test_parse_role_valid_and_invalid() -> None:
    assert parse_role("Editor") is Role.EDITOR
    with pytest.raises(BadRequestError):
        parse_role("superuser")


async def test_require_role_allows_equal_or_higher() -> None:
    dep = require_role(Role.EDITOR)
    assert await dep(_ctx(Role.EDITOR)) is Role.EDITOR
    assert await dep(_ctx(Role.ADMIN)) is Role.ADMIN
    assert await dep(_ctx(Role.OWNER)) is Role.OWNER


async def test_require_role_denies_lower() -> None:
    dep = require_role(Role.EDITOR)
    with pytest.raises(ForbiddenError):
        await dep(_ctx(Role.VIEWER))
