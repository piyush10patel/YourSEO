"""Persist an `AuditResult` into the relational domain model.

Turns a one-shot audit into durable rows: upserts the Page, records an Audit,
and materialises the qualitative findings as prioritised Recommendation rows
(seeding the spec §13 engine with priority = impact x confidence / effort).
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repositories as repo
from app.db.models import Audit
from app.services.audit import AuditResult

# Map qualitative confidence -> a numeric factor for the priority formula.
_CONFIDENCE = {"high": 0.85, "low": 0.4}
# Per-severity impact/effort priors for technical fixes.
_SEVERITY = {
    "high": (0.9, 0.4),
    "medium": (0.6, 0.5),
    "low": (0.3, 0.6),
}


def _priority(impact: float, confidence: float, effort: float) -> float:
    return round(impact * confidence / max(effort, 0.01), 3)


async def persist_audit(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    result: AuditResult,
) -> Audit:
    """Persist ``result`` under ``project_id`` (verified against the org)."""
    from app.core.exceptions import NotFoundError

    project = await repo.get_project(
        session, project_id=project_id, organization_id=organization_id
    )
    if project is None:
        raise NotFoundError(f"Project {project_id} not found.")

    page = await repo.upsert_page(
        session,
        project_id=project_id,
        url=result.fetched_url,
        title=result.title,
        meta_description=result.current_meta_description,
        status_code=None,
        word_count=result.word_count,
    )

    audit = await repo.create_audit(
        session,
        project_id=project_id,
        page_id=page.id,
        overall_score=result.overall_score,
        grade=result.grade,
        confidence=result.confidence,
    )

    conf = _CONFIDENCE.get(result.confidence, 0.6)

    for gap in result.keyword_gaps:
        impact, effort = 0.7, 0.5
        await repo.add_recommendation(
            session,
            project_id=project_id,
            audit_id=audit.id,
            type="keyword_gap",
            title=gap.keyword,
            detail=gap.rationale,
            impact=impact,
            confidence=conf,
            effort=effort,
            priority=_priority(impact, conf, effort),
        )

    for fix in result.technical_fixes:
        impact, effort = _SEVERITY.get(fix.severity.lower(), (0.5, 0.5))
        await repo.add_recommendation(
            session,
            project_id=project_id,
            audit_id=audit.id,
            type="technical_fix",
            title=fix.issue,
            detail=fix.recommendation,
            impact=impact,
            confidence=conf,
            effort=effort,
            priority=_priority(impact, conf, effort),
        )

    if result.rewritten_meta_description:
        await repo.add_recommendation(
            session,
            project_id=project_id,
            audit_id=audit.id,
            type="meta_description",
            title="Rewritten meta description",
            detail=result.rewritten_meta_description,
            impact=0.6,
            confidence=conf,
            effort=0.2,
            priority=_priority(0.6, conf, 0.2),
        )

    return audit
