"""Tenant-scoped data access.

Every project-scoped read goes through `get_project(..., organization_id)` so a
caller can never reach another org's data — the enforcement of spec §24's
mandatory ``WHERE organization_id = ?``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Audit,
    Organization,
    Page,
    Project,
    Recommendation,
)

_DEFAULT_ORG_NAME = "Default Organization"


# --------------------------------------------------------------------------- #
# Organizations
# --------------------------------------------------------------------------- #
async def create_organization(
    session: AsyncSession, *, name: str, plan: str = "free"
) -> Organization:
    org = Organization(name=name, plan=plan)
    session.add(org)
    await session.flush()
    return org


async def get_organization(
    session: AsyncSession, org_id: uuid.UUID
) -> Organization | None:
    return await session.get(Organization, org_id)


async def get_or_create_default_org(session: AsyncSession) -> Organization:
    """Bootstrap org used until real auth (Clerk) is wired in."""
    result = await session.execute(
        select(Organization).where(Organization.name == _DEFAULT_ORG_NAME).limit(1)
    )
    org = result.scalar_one_or_none()
    if org is None:
        org = await create_organization(session, name=_DEFAULT_ORG_NAME)
    return org


# --------------------------------------------------------------------------- #
# Projects (tenant-scoped)
# --------------------------------------------------------------------------- #
async def create_project(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    name: str,
    domain: str | None = None,
) -> Project:
    project = Project(organization_id=organization_id, name=name, domain=domain)
    session.add(project)
    await session.flush()
    return project


async def list_projects(
    session: AsyncSession, *, organization_id: uuid.UUID
) -> list[Project]:
    result = await session.execute(
        select(Project)
        .where(Project.organization_id == organization_id)
        .order_by(Project.created_at.desc())
    )
    return list(result.scalars().all())


async def get_project(
    session: AsyncSession, *, project_id: uuid.UUID, organization_id: uuid.UUID
) -> Project | None:
    result = await session.execute(
        select(Project).where(
            Project.id == project_id,
            Project.organization_id == organization_id,  # tenant scope
        )
    )
    return result.scalar_one_or_none()


# --------------------------------------------------------------------------- #
# Pages / Audits / Recommendations
# --------------------------------------------------------------------------- #
async def upsert_page(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    url: str,
    title: str | None,
    meta_description: str | None,
    status_code: int | None,
    word_count: int | None,
) -> Page:
    result = await session.execute(
        select(Page).where(Page.project_id == project_id, Page.url == url)
    )
    page = result.scalar_one_or_none()
    if page is None:
        page = Page(project_id=project_id, url=url)
        session.add(page)
    page.title = title
    page.meta_description = meta_description
    page.status_code = status_code
    page.word_count = word_count
    await session.flush()
    return page


async def create_audit(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    page_id: uuid.UUID | None,
    overall_score: int,
    grade: str,
    confidence: str,
) -> Audit:
    audit = Audit(
        project_id=project_id,
        page_id=page_id,
        overall_score=overall_score,
        grade=grade,
        confidence=confidence,
    )
    session.add(audit)
    await session.flush()
    return audit


async def add_recommendation(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    audit_id: uuid.UUID | None,
    type: str,
    title: str,
    detail: str | None = None,
    impact: float = 0.5,
    confidence: float = 0.5,
    effort: float = 0.5,
    priority: float = 0.0,
) -> Recommendation:
    rec = Recommendation(
        project_id=project_id,
        audit_id=audit_id,
        type=type,
        title=title,
        detail=detail,
        impact=impact,
        confidence=confidence,
        effort=effort,
        priority=priority,
    )
    session.add(rec)
    await session.flush()
    return rec


async def list_pages(
    session: AsyncSession, *, project_id: uuid.UUID, organization_id: uuid.UUID
) -> list[Page]:
    if not await get_project(
        session, project_id=project_id, organization_id=organization_id
    ):
        return []
    result = await session.execute(
        select(Page).where(Page.project_id == project_id).order_by(Page.url)
    )
    return list(result.scalars().all())


async def list_audits(
    session: AsyncSession, *, project_id: uuid.UUID, organization_id: uuid.UUID
) -> list[Audit]:
    if not await get_project(
        session, project_id=project_id, organization_id=organization_id
    ):
        return []
    result = await session.execute(
        select(Audit)
        .where(Audit.project_id == project_id)
        .order_by(Audit.created_at.desc())
    )
    return list(result.scalars().all())


async def list_recommendations(
    session: AsyncSession, *, project_id: uuid.UUID, organization_id: uuid.UUID
) -> list[Recommendation]:
    if not await get_project(
        session, project_id=project_id, organization_id=organization_id
    ):
        return []
    result = await session.execute(
        select(Recommendation)
        .where(Recommendation.project_id == project_id)
        .order_by(Recommendation.priority.desc(), Recommendation.created_at.desc())
    )
    return list(result.scalars().all())
