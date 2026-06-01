"""Keyword enrichment (spec §14): fill volume / difficulty / intent.

Uses whichever `KeywordProvider` is configured (stub by default). Updates the
persisted Keyword rows in place.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db import repositories as repo
from app.db.models import Keyword
from app.integrations.base import KeywordProvider
from app.integrations.providers import get_keyword_provider


async def enrich_keywords(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    provider: KeywordProvider | None = None,
) -> list[Keyword]:
    if not await repo.get_project(
        session, project_id=project_id, organization_id=organization_id
    ):
        raise NotFoundError(f"Project {project_id} not found.")

    provider = provider or get_keyword_provider()
    keywords = await repo.list_keywords(
        session, project_id=project_id, organization_id=organization_id
    )
    if not keywords:
        return []

    metrics = provider.metrics([k.keyword for k in keywords])
    for kw in keywords:
        m = metrics.get(kw.keyword)
        if m:
            kw.volume = m["volume"]
            kw.difficulty = m["difficulty"]
            kw.intent = m["intent"]
    await session.flush()
    return keywords
