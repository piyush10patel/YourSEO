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
    Cluster,
    GraphEdge,
    Keyword,
    Organization,
    Page,
    Project,
    Recommendation,
    Topic,
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


async def get_or_create_org_by_clerk(
    session: AsyncSession, clerk_org_id: str, *, name: str = "Organization"
) -> Organization:
    """Map a Clerk organization id to our Organization (create on first sight)."""
    result = await session.execute(
        select(Organization).where(Organization.clerk_org_id == clerk_org_id).limit(1)
    )
    org = result.scalar_one_or_none()
    if org is None:
        org = Organization(name=name, clerk_org_id=clerk_org_id)
        session.add(org)
        await session.flush()
    return org


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
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    organization_id: uuid.UUID,
    status: str | None = None,
    type: str | None = None,
) -> list[Recommendation]:
    if not await get_project(
        session, project_id=project_id, organization_id=organization_id
    ):
        return []
    query = select(Recommendation).where(Recommendation.project_id == project_id)
    if status:
        query = query.where(Recommendation.status == status)
    if type:
        query = query.where(Recommendation.type == type)
    query = query.order_by(
        Recommendation.priority.desc(), Recommendation.created_at.desc()
    )
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_recommendation(
    session: AsyncSession, *, rec_id: uuid.UUID, organization_id: uuid.UUID
) -> Recommendation | None:
    """Fetch a recommendation, scoped to the org via its project."""
    result = await session.execute(
        select(Recommendation)
        .join(Project, Project.id == Recommendation.project_id)
        .where(
            Recommendation.id == rec_id,
            Project.organization_id == organization_id,
        )
    )
    return result.scalar_one_or_none()


# --------------------------------------------------------------------------- #
# Keywords / Clusters / Topics (Phase 3)
# --------------------------------------------------------------------------- #
async def add_keywords(
    session: AsyncSession, *, project_id: uuid.UUID, keywords: list[str]
) -> list[Keyword]:
    """Insert keywords for a project, skipping ones that already exist."""
    existing = await session.execute(
        select(Keyword.keyword).where(Keyword.project_id == project_id)
    )
    have = {k.lower() for k in existing.scalars().all()}
    created: list[Keyword] = []
    for raw in keywords:
        kw = raw.strip()
        if not kw or kw.lower() in have:
            continue
        have.add(kw.lower())
        obj = Keyword(project_id=project_id, keyword=kw)
        session.add(obj)
        created.append(obj)
    await session.flush()
    return created


async def list_keywords(
    session: AsyncSession, *, project_id: uuid.UUID, organization_id: uuid.UUID
) -> list[Keyword]:
    if not await get_project(
        session, project_id=project_id, organization_id=organization_id
    ):
        return []
    result = await session.execute(
        select(Keyword)
        .where(Keyword.project_id == project_id)
        .order_by(Keyword.keyword)
    )
    return list(result.scalars().all())


async def list_clusters(
    session: AsyncSession, *, project_id: uuid.UUID, organization_id: uuid.UUID
) -> list[Cluster]:
    if not await get_project(
        session, project_id=project_id, organization_id=organization_id
    ):
        return []
    result = await session.execute(
        select(Cluster).where(Cluster.project_id == project_id).order_by(Cluster.topic)
    )
    return list(result.scalars().all())


async def list_topics(session: AsyncSession, *, project_id: uuid.UUID) -> list[Topic]:
    result = await session.execute(select(Topic).where(Topic.project_id == project_id))
    return list(result.scalars().all())


async def list_graph_edges(
    session: AsyncSession, *, project_id: uuid.UUID, organization_id: uuid.UUID
) -> list[GraphEdge]:
    if not await get_project(
        session, project_id=project_id, organization_id=organization_id
    ):
        return []
    result = await session.execute(
        select(GraphEdge).where(GraphEdge.project_id == project_id)
    )
    return list(result.scalars().all())
