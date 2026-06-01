"""RBAC roles (spec §26).

The implementation now lives in `app.core.auth` (so role + tenancy resolve
through one Clerk-or-dev seam). Re-exported here for stable imports.
"""

from __future__ import annotations

from app.core.auth import Role, parse_role, require_role

__all__ = ["Role", "parse_role", "require_role"]
