"""Reporting engine (spec §20).

Aggregates a project's *owned* data into an executive report: SEO score + trend,
page/keyword/cluster counts, issue breakdown, and recommendation status.

The spec's business KPIs (traffic, rankings, conversions, revenue) require
external analytics (Google Analytics / Search Console) which aren't connected
yet — they're returned as nulls with a clear note rather than fabricated.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db import repositories as repo


async def build_report(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
) -> dict[str, Any]:
    project = await repo.get_project(
        session, project_id=project_id, organization_id=organization_id
    )
    if project is None:
        raise NotFoundError(f"Project {project_id} not found.")

    audits = await repo.list_audits(
        session, project_id=project_id, organization_id=organization_id
    )
    recs = await repo.list_recommendations(
        session, project_id=project_id, organization_id=organization_id
    )
    pages = await repo.list_pages(
        session, project_id=project_id, organization_id=organization_id
    )
    keywords = await repo.list_keywords(
        session, project_id=project_id, organization_id=organization_id
    )
    clusters = await repo.list_clusters(
        session, project_id=project_id, organization_id=organization_id
    )

    latest = audits[0] if audits else None
    # Oldest -> newest, last 10 audits.
    trend = [a.overall_score for a in reversed(audits)][-10:]

    return {
        "project": {"name": project.name, "domain": project.domain},
        "seo_score": latest.overall_score if latest else None,
        "grade": latest.grade if latest else None,
        "score_trend": trend,
        "pages": len(pages),
        "keywords": len(keywords),
        "clusters": len(clusters),
        "recommendations_by_status": dict(Counter(r.status for r in recs)),
        "issues_by_type": dict(Counter(r.type for r in recs)),
        "kpis": {
            "traffic": None,
            "rankings": None,
            "conversions": None,
            "revenue": None,
            "note": "Connect Google Analytics / Search Console to populate "
            "traffic, rankings, conversions, and revenue.",
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
