"""Project / audit / recommendation endpoints (persistent, multi-tenant).

Until real auth (Clerk) lands, the tenant is resolved from an optional
``X-Organization-Id`` header, defaulting to a bootstrapped "Default
Organization". Swapping in Clerk later means changing only `get_current_org_id`.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.auth import Role, get_current_org_id, require_role
from app.core.exceptions import NotFoundError
from app.core.metrics import AUDITS, CRAWLS
from app.db import repositories as repo
from app.db.base import get_session
from app.schemas.audit import AuditRequest  # noqa: F401  (kept for symmetry)
from app.schemas.project import (
    AuditOut,
    ClusterOut,
    CrawlRequest,
    CrawlResponse,
    GraphResponse,
    GscImport,
    KeywordCreate,
    KeywordOut,
    PageOut,
    ProjectAuditRequest,
    ProjectCreate,
    ProjectOut,
    RecommendationOut,
    RecommendationStatusUpdate,
    ReportResponse,
)
from app.integrations.gsc import parse_gsc_csv
from app.integrations.providers import get_backlink_provider, get_serp_provider
from app.services import billing, clustering, enrichment, knowledge_graph, reporting
from app.services import recommendations as rec_engine
from app.services.audit import AuditResult, run_audit_async
from app.services.audit_engine import run_project_crawl_audit
from app.services.persistence import persist_audit

logger = logging.getLogger(__name__)

router = APIRouter(tags=["projects"])


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
    _role: Role = Depends(require_role(Role.ADMIN)),
) -> ProjectOut:
    await billing.enforce_project_limit(session, organization_id=org_id)
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
    status: str | None = None,
    type: str | None = None,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
) -> list[RecommendationOut]:
    await _require_project(session, project_id, org_id)
    recs = await repo.list_recommendations(
        session,
        project_id=project_id,
        organization_id=org_id,
        status=status,
        type=type,
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
    _role: Role = Depends(require_role(Role.EDITOR)),
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
    AUDITS.inc()
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


@router.get(
    "/projects/{project_id}/report",
    response_model=ReportResponse,
    summary="Executive report: score trend, issue breakdown, KPIs",
)
async def project_report(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
) -> ReportResponse:
    report = await reporting.build_report(
        session, organization_id=org_id, project_id=project_id
    )
    return ReportResponse(**report)


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
    _role: Role = Depends(require_role(Role.EDITOR)),
) -> CrawlResponse:
    await _require_project(session, project_id, org_id)
    CRAWLS.inc()

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


# --------------------------------------------------------------------------- #
# Keywords, clustering, knowledge graph (Phase 3)
# --------------------------------------------------------------------------- #
@router.post(
    "/projects/{project_id}/keywords",
    response_model=list[KeywordOut],
    summary="Add keywords to a project (manual / CSV-paste; dedupes)",
)
async def add_keywords(
    project_id: uuid.UUID,
    payload: KeywordCreate,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
    _role: Role = Depends(require_role(Role.EDITOR)),
) -> list[KeywordOut]:
    await _require_project(session, project_id, org_id)
    created = await repo.add_keywords(
        session, project_id=project_id, keywords=payload.keywords
    )
    return [KeywordOut.model_validate(k) for k in created]


@router.get(
    "/projects/{project_id}/keywords",
    response_model=list[KeywordOut],
    summary="List a project's keywords",
)
async def list_keywords(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
) -> list[KeywordOut]:
    await _require_project(session, project_id, org_id)
    kws = await repo.list_keywords(
        session, project_id=project_id, organization_id=org_id
    )
    return [KeywordOut.model_validate(k) for k in kws]


@router.post(
    "/projects/{project_id}/keywords/import-gsc",
    response_model=list[KeywordOut],
    summary="Import keywords from a Google Search Console CSV export",
)
async def import_gsc(
    project_id: uuid.UUID,
    payload: GscImport,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
    _role: Role = Depends(require_role(Role.EDITOR)),
) -> list[KeywordOut]:
    await _require_project(session, project_id, org_id)
    rows = parse_gsc_csv(payload.csv)
    created = await repo.add_keywords(
        session, project_id=project_id, keywords=[r["query"] for r in rows]
    )
    return [KeywordOut.model_validate(k) for k in created]


@router.post(
    "/projects/{project_id}/keywords/enrich",
    response_model=list[KeywordOut],
    summary="Enrich keywords with volume / difficulty / intent",
)
async def enrich_project_keywords(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
    _role: Role = Depends(require_role(Role.EDITOR)),
) -> list[KeywordOut]:
    kws = await enrichment.enrich_keywords(
        session, organization_id=org_id, project_id=project_id
    )
    return [KeywordOut.model_validate(k) for k in kws]


@router.get(
    "/projects/{project_id}/serp",
    summary="Current SERP positions for the project's keywords",
)
async def project_serp(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
    settings: Settings = Depends(get_settings),
) -> dict[str, int]:
    project = await _require_project(session, project_id, org_id)
    kws = await repo.list_keywords(
        session, project_id=project_id, organization_id=org_id
    )
    provider = get_serp_provider(settings)
    return provider.positions(project.domain or "", [k.keyword for k in kws])


@router.get(
    "/projects/{project_id}/backlinks",
    summary="Backlink / authority summary for the project's domain",
)
async def project_backlinks(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
    settings: Settings = Depends(get_settings),
) -> dict:
    project = await _require_project(session, project_id, org_id)
    provider = get_backlink_provider(settings)
    return provider.summary(project.domain or "unknown")


@router.post(
    "/projects/{project_id}/cluster",
    response_model=list[ClusterOut],
    summary="Cluster the project's keywords into topics",
)
async def cluster_project_keywords(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
    _role: Role = Depends(require_role(Role.EDITOR)),
) -> list[ClusterOut]:
    clusters = await clustering.cluster_keywords(
        session, project_id=project_id, organization_id=org_id
    )
    return [ClusterOut.model_validate(c) for c in clusters]


@router.get(
    "/projects/{project_id}/clusters",
    response_model=list[ClusterOut],
    summary="List a project's topic clusters",
)
async def list_clusters(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
) -> list[ClusterOut]:
    await _require_project(session, project_id, org_id)
    clusters = await repo.list_clusters(
        session, project_id=project_id, organization_id=org_id
    )
    return [ClusterOut.model_validate(c) for c in clusters]


@router.post(
    "/projects/{project_id}/graph/build",
    summary="(Re)build the project's knowledge graph",
)
async def build_project_graph(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
    _role: Role = Depends(require_role(Role.EDITOR)),
) -> dict[str, int]:
    edges = await knowledge_graph.build_graph(
        session, project_id=project_id, organization_id=org_id
    )
    return {"edges": edges}


@router.get(
    "/projects/{project_id}/graph",
    response_model=GraphResponse,
    summary="Get the project's knowledge graph (nodes + edges)",
)
async def get_project_graph(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
) -> GraphResponse:
    graph = await knowledge_graph.get_graph(
        session, project_id=project_id, organization_id=org_id
    )
    return GraphResponse(**graph)


@router.patch(
    "/recommendations/{rec_id}",
    response_model=RecommendationOut,
    summary="Update a recommendation's status (open/in_progress/done/dismissed)",
)
async def update_recommendation(
    rec_id: uuid.UUID,
    payload: RecommendationStatusUpdate,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
    _role: Role = Depends(require_role(Role.EDITOR)),
) -> RecommendationOut:
    rec = await rec_engine.set_status(
        session, rec_id=rec_id, organization_id=org_id, status=payload.status
    )
    return RecommendationOut.model_validate(rec)
