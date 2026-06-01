"""Project / audit / recommendation endpoints (persistent, multi-tenant).

Until real auth (Clerk) lands, the tenant is resolved from an optional
``X-Organization-Id`` header, defaulting to a bootstrapped "Default
Organization". Swapping in Clerk later means changing only `get_current_org_id`.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.exceptions import NotFoundError
from app.db import repositories as repo
from app.db.base import get_session
from app.schemas.audit import AuditRequest  # noqa: F401  (kept for symmetry)
from app.schemas.project import (
    AuditOut,
    CrawlRequest,
    CrawlResponse,
    PageOut,
    ProjectAuditRequest,
    ProjectCreate,
    ProjectOut,
    RecommendationOut,
)
from app.services.audit import AuditResult, run_audit_async
from app.services.audit_engine import run_project_crawl_audit
from app.services.persistence import persist_audit

logger = logging.getLogger(__name__)

router = APIRouter(tags=["projects"])


async def get_current_org_id(
    session: AsyncSession = Depends(get_session),
    x_organization_id: str | None = Header(default=None),
) -> uuid.UUID:
    """Resolve the active organization (header override, else default org)."""
    if x_organization_id:
        try:
            org_id = uuid.UUID(x_organization_id)
        except ValueError as exc:
            raise NotFoundError("Invalid X-Organization-Id.") from exc
        org = await repo.get_organization(session, org_id)
        if org is None:
            raise NotFoundError(f"Organization {org_id} not found.")
        return org.id
    org = await repo.get_or_create_default_org(session)
    return org.id


async def _require_project(
    session: AsyncSession, project_id: uuid.UUID, org_id: uuid.UUID
):
    project = await repo.get_project(
        session, project_id=project_id, organization_id=org_id
    )
    if project is None:
        raise NotFoundError(f"Project {project_id} not found.")
    return project


@router.post("/projects", response_model=ProjectOut, summary="Create a project")
async def create_project(
    payload: ProjectCreate,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
) -> ProjectOut:
    project = await repo.create_project(
        session, organization_id=org_id, name=payload.name, domain=payload.domain
    )
    return ProjectOut.model_validate(project)


@router.get("/projects", response_model=list[ProjectOut], summary="List projects")
async def list_projects(
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
) -> list[ProjectOut]:
    projects = await repo.list_projects(session, organization_id=org_id)
    return [ProjectOut.model_validate(p) for p in projects]


@router.get(
    "/projects/{project_id}/audits",
    response_model=list[AuditOut],
    summary="List a project's audits (newest first)",
)
async def list_project_audits(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
) -> list[AuditOut]:
    await _require_project(session, project_id, org_id)
    audits = await repo.list_audits(
        session, project_id=project_id, organization_id=org_id
    )
    return [AuditOut.model_validate(a) for a in audits]


@router.get(
    "/projects/{project_id}/recommendations",
    response_model=list[RecommendationOut],
    summary="List a project's recommendations (highest priority first)",
)
async def list_project_recommendations(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
) -> list[RecommendationOut]:
    await _require_project(session, project_id, org_id)
    recs = await repo.list_recommendations(
        session, project_id=project_id, organization_id=org_id
    )
    return [RecommendationOut.model_validate(r) for r in recs]


@router.post(
    "/projects/{project_id}/audit",
    response_model=AuditResult,
    summary="Run an audit for a project and persist it",
)
async def run_project_audit(
    project_id: uuid.UUID,
    payload: ProjectAuditRequest,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
    settings: Settings = Depends(get_settings),
) -> AuditResult:
    await _require_project(session, project_id, org_id)
    render_js: bool | str = "auto" if payload.render_js else False
    result = await run_audit_async(
        str(payload.url),
        settings,
        render_js=render_js,
        use_cache=payload.use_cache,
    )
    await persist_audit(
        session, organization_id=org_id, project_id=project_id, result=result
    )
    return result


@router.get(
    "/projects/{project_id}/pages",
    response_model=list[PageOut],
    summary="List crawled pages for a project",
)
async def list_project_pages(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
) -> list[PageOut]:
    await _require_project(session, project_id, org_id)
    pages = await repo.list_pages(
        session, project_id=project_id, organization_id=org_id
    )
    return [PageOut.model_validate(p) for p in pages]


@router.post(
    "/projects/{project_id}/crawl",
    response_model=CrawlResponse,
    summary="Crawl a whole site, audit it, and persist pages + findings",
)
async def crawl_project(
    project_id: uuid.UUID,
    payload: CrawlRequest,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
    settings: Settings = Depends(get_settings),
) -> CrawlResponse:
    await _require_project(session, project_id, org_id)

    if settings.crawl_dispatch == "celery":
        # Enqueue for the worker; returns immediately.
        from app.worker import crawl_audit_task

        task = crawl_audit_task.delay(
            str(org_id), str(project_id), str(payload.seed_url)
        )
        return CrawlResponse(mode="queued", task_id=task.id)

    # Inline: crawl + audit within the request (good for dev / small sites).
    audit = await run_project_crawl_audit(
        session,
        organization_id=org_id,
        project_id=project_id,
        seed_url=str(payload.seed_url),
        settings=settings,
        max_pages=payload.max_pages,
        max_depth=payload.max_depth,
    )
    return CrawlResponse(mode="inline", audit=AuditOut.model_validate(audit))
