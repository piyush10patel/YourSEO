"""RBAC role logic tests (spec §26)."""

from __future__ import annotations

import pytest

from app.core.exceptions import BadRequestError, ForbiddenError
from app.core.rbac import Role, parse_role, require_role


def test_role_ordering() -> None:
    assert Role.VIEWER < Role.EDITOR < Role.ADMIN < Role.OWNER


def test_parse_role_valid_and_invalid() -> None:
    assert parse_role("Editor") is Role.EDITOR
    with pytest.raises(BadRequestError):
        parse_role("superuser")


def test_require_role_allows_equal_or_higher() -> None:
    dep = require_role(Role.EDITOR)
    assert dep("editor") is Role.EDITOR
    assert dep("admin") is Role.ADMIN
    assert dep("owner") is Role.OWNER


def test_require_role_denies_lower() -> None:
    dep = require_role(Role.EDITOR)
    with pytest.raises(ForbiddenError):
        dep("viewer")
