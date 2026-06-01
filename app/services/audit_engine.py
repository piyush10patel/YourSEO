"""Site audit engine (spec §7) + crawl→audit→persist orchestration.

Consumes a `CrawlResult` and produces typed `AuditIssue`s across the spec's
categories — technical, content, structure. (Performance / Core Web Vitals is
deferred: it needs Lighthouse / real browser metrics, a later phase.)

`run_project_crawl_audit` is the high-level entry point used by the API and the
Celery task: it crawls, persists pages, runs the checks, persists an Audit plus
prioritised Recommendation rows, and emits domain events.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.events import (
    AUDIT_COMPLETED,
    CRAWL_COMPLETED,
    RECOMMENDATION_GENERATED,
    Event,
    bus,
)
from app.db import repositories as repo
from app.db.models import Audit
from app.services.audit import _grade
from app.services.crawler import CrawlResult, Crawler, _normalize
from app.services.persistence import _priority

logger = logging.getLogger(__name__)

# Per-severity impact/effort priors (shared shape with persistence).
_SEVERITY = {"high": (0.9, 0.4), "medium": (0.6, 0.5), "low": (0.3, 0.6)}


@dataclass
class AuditIssue:
    type: str
    severity: str  # low | medium | high
    title: str
    detail: str
    page_url: str | None = None


def run_site_audit(result: CrawlResult, *, thin_words: int = 150) -> list[AuditIssue]:
    issues: list[AuditIssue] = []
    statuses = {p.url: p.status_code for p in result.pages}
    inbound: dict[str, int] = defaultdict(int)

    # Structure: inbound links + broken internal links.
    for src, targets in result.edges.items():
        for target in targets:
            inbound[target] += 1
            if statuses.get(target, 0) >= 400:
                issues.append(
                    AuditIssue(
                        "broken_link",
                        "high",
                        f"Broken internal link to {target}",
                        f"{src} links to {target}, which returns HTTP "
                        f"{statuses[target]}.",
                        page_url=src,
                    )
                )

    titles: dict[str, list[str]] = defaultdict(list)
    metas: dict[str, list[str]] = defaultdict(list)

    for page in result.pages:
        if page.status_code == 0:
            issues.append(
                AuditIssue(
                    "fetch_error",
                    "high",
                    "Page failed to load",
                    page.error or "Network error",
                    page_url=page.url,
                )
            )
            continue
        if page.status_code >= 400:
            issues.append(
                AuditIssue(
                    "http_error",
                    "high",
                    f"Page returns HTTP {page.status_code}",
                    "Fix or remove this URL.",
                    page_url=page.url,
                )
            )
            continue

        if not page.title:
            issues.append(
                AuditIssue(
                    "missing_title",
                    "high",
                    "Missing <title>",
                    "Add a unique, descriptive title tag.",
                    page_url=page.url,
                )
            )
        else:
            titles[page.title].append(page.url)

        if not page.meta_description:
            issues.append(
                AuditIssue(
                    "missing_meta",
                    "medium",
                    "Missing meta description",
                    "Add a 150-160 char meta description.",
                    page_url=page.url,
                )
            )
        else:
            metas[page.meta_description].append(page.url)

        if page.word_count < thin_words:
            issues.append(
                AuditIssue(
                    "thin_content",
                    "medium",
                    f"Thin content ({page.word_count} words)",
                    "Expand with substantive, useful content.",
                    page_url=page.url,
                )
            )
        if page.h1_count == 0:
            issues.append(
                AuditIssue(
                    "missing_h1",
                    "low",
                    "No H1 heading",
                    "Add a single descriptive H1.",
                    page_url=page.url,
                )
            )
        elif page.h1_count > 1:
            issues.append(
                AuditIssue(
                    "multiple_h1",
                    "low",
                    f"{page.h1_count} H1 headings",
                    "Use exactly one H1 per page.",
                    page_url=page.url,
                )
            )
        if page.canonical and _normalize(page.canonical) != page.url:
            issues.append(
                AuditIssue(
                    "canonical_mismatch",
                    "low",
                    "Canonical points elsewhere",
                    f"rel=canonical -> {page.canonical}",
                    page_url=page.url,
                )
            )
        if page.images_missing_alt:
            issues.append(
                AuditIssue(
                    "image_alt",
                    "low",
                    f"{page.images_missing_alt} images missing alt",
                    "Add descriptive alt text to images.",
                    page_url=page.url,
                )
            )

    for title, urls in titles.items():
        if len(urls) > 1:
            issues.append(
                AuditIssue(
                    "duplicate_title",
                    "medium",
                    "Duplicate <title> across pages",
                    f"{len(urls)} pages share the title {title!r}.",
                )
            )
    for meta, urls in metas.items():
        if len(urls) > 1:
            issues.append(
                AuditIssue(
                    "duplicate_meta",
                    "low",
                    "Duplicate meta description across pages",
                    f"{len(urls)} pages share the same meta.",
                )
            )

    for page in result.ok_pages:
        if page.url != result.seed_url and inbound.get(page.url, 0) == 0:
            issues.append(
                AuditIssue(
                    "orphan_page",
                    "medium",
                    "Orphan page",
                    "No internal links point to this page.",
                    page_url=page.url,
                )
            )

    return issues


def score_from_issues(issues: list[AuditIssue], page_count: int) -> int:
    """A simple 0-100 health score: penalise issues, weighted by severity."""
    weights = {"high": 5, "medium": 2, "low": 1}
    penalty = sum(weights.get(i.severity, 1) for i in issues)
    base = max(10, page_count) * 4  # more pages -> more tolerance
    return max(0, min(100, round(100 - 100 * penalty / base)))


async def run_project_crawl_audit(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    project_id: uuid.UUID,
    seed_url: str,
    settings: Settings | None = None,
    max_pages: int | None = None,
    max_depth: int | None = None,
    crawler: Crawler | None = None,
) -> Audit:
    """Crawl a site, persist pages, audit it, and store an Audit + recs."""
    from app.core.exceptions import NotFoundError

    settings = settings or get_settings()
    project = await repo.get_project(
        session, project_id=project_id, organization_id=organization_id
    )
    if project is None:
        raise NotFoundError(f"Project {project_id} not found.")

    crawler = crawler or Crawler(settings=settings)
    result = await crawler.crawl(
        seed_url,
        max_pages=max_pages or settings.crawl_max_pages,
        max_depth=max_depth or settings.crawl_max_depth,
        concurrency=settings.crawl_concurrency,
    )

    for page in result.pages:
        await repo.upsert_page(
            session,
            project_id=project_id,
            url=page.url,
            title=page.title,
            meta_description=page.meta_description,
            status_code=page.status_code,
            word_count=page.word_count,
        )
    await bus.emit(
        Event(
            CRAWL_COMPLETED, {"project_id": str(project_id), "pages": len(result.pages)}
        )
    )

    issues = run_site_audit(result, thin_words=settings.thin_content_words)
    score = score_from_issues(issues, len(result.ok_pages))
    audit = await repo.create_audit(
        session,
        project_id=project_id,
        page_id=None,
        overall_score=score,
        grade=_grade(score),
        confidence="high",
    )

    for issue in issues:
        impact, effort = _SEVERITY.get(issue.severity, (0.5, 0.5))
        await repo.add_recommendation(
            session,
            project_id=project_id,
            audit_id=audit.id,
            type=issue.type,
            title=issue.title,
            detail=issue.detail,
            impact=impact,
            confidence=0.9,
            effort=effort,
            priority=_priority(impact, 0.9, effort),
        )
    await bus.emit(
        Event(
            RECOMMENDATION_GENERATED,
            {"project_id": str(project_id), "count": len(issues)},
        )
    )
    await bus.emit(
        Event(
            AUDIT_COMPLETED,
            {"project_id": str(project_id), "issues": len(issues), "score": score},
        )
    )
    return audit
