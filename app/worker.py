"""Celery app + tasks (spec §12: Redis + Celery queues).

The Celery worker is the production dispatcher for long-running crawl/audit
jobs. The actual work lives in async services; tasks just bridge Celery's sync
world to them via ``asyncio.run`` and open their own DB session (the worker is
a separate process from the API).

Run the worker (in Docker this is the `worker` service):
    celery -A app.worker.celery worker --loglevel=info -Q crawl
"""

from __future__ import annotations

import asyncio
import uuid

from celery import Celery

from app.config import get_settings

settings = get_settings()

celery = Celery(
    "seoos",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery.conf.task_default_queue = "crawl"
celery.conf.task_routes = {"app.worker.crawl_audit_task": {"queue": "crawl"}}


async def _run_crawl_audit(
    organization_id: str, project_id: str, seed_url: str
) -> dict:
    # Imported here to keep import time light for non-worker processes.
    from app.db.base import get_sessionmaker
    from app.services.audit_engine import run_project_crawl_audit

    factory = get_sessionmaker()
    async with factory() as session:
        audit = await run_project_crawl_audit(
            session,
            organization_id=uuid.UUID(organization_id),
            project_id=uuid.UUID(project_id),
            seed_url=seed_url,
        )
        await session.commit()
        return {"audit_id": str(audit.id), "score": audit.overall_score}


@celery.task(name="app.worker.crawl_audit_task")
def crawl_audit_task(organization_id: str, project_id: str, seed_url: str) -> dict:
    """Crawl + audit a site and persist the results (runs in a worker)."""
    return asyncio.run(_run_crawl_audit(organization_id, project_id, seed_url))
