"""Recommendation engine (spec §13) — status workflow + priority.

The priority formula (priority = impact x confidence / effort) is applied when
recommendations are created (see persistence / audit_engine). This module owns
the lifecycle: validating and transitioning status, and recomputing priority.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.db import repositories as repo
from app.db.models import Recommendation

VALID_STATUSES = {"open", "in_progress", "done", "dismissed"}


def priority(impact: float, confidence: float, effort: float) -> float:
    return round(impact * confidence / max(effort, 0.01), 3)


async def set_status(
    session: AsyncSession,
    *,
    rec_id: uuid.UUID,
    organization_id: uuid.UUID,
    status: str,
) -> Recommendation:
    if status not in VALID_STATUSES:
        raise BadRequestError(
            f"Invalid status {status!r}. Valid: {sorted(VALID_STATUSES)}."
        )
    rec = await repo.get_recommendation(
        session, rec_id=rec_id, organization_id=organization_id
    )
    if rec is None:
        raise NotFoundError(f"Recommendation {rec_id} not found.")
    rec.status = status
    await session.flush()
    return rec
