"""Knowledge graph (spec §8) — the relations that tie SEO entities together.

Builds typed edges over the persisted domain:
    Page    -targets->     Keyword   (keyword text appears in the page)
    Keyword -belongs_to->  Cluster
    Cluster -supports->    Topic

Stored in the polymorphic `graph_edges` table. (Semantic similarity edges via
pgvector embeddings are a follow-on; the embedding column already exists.)
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db import repositories as repo
from app.db.models import GraphEdge


async def build_graph(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> int:
    project = await repo.get_project(
        session, project_id=project_id, organization_id=organization_id
    )
    if project is None:
        raise NotFoundError(f"Project {project_id} not found.")

    # Idempotent rebuild.
    await session.execute(delete(GraphEdge).where(GraphEdge.project_id == project_id))
    await session.flush()

    keywords = await repo.list_keywords(
        session, project_id=project_id, organization_id=organization_id
    )
    clusters = await repo.list_clusters(
        session, project_id=project_id, organization_id=organization_id
    )
    pages = await repo.list_pages(
        session, project_id=project_id, organization_id=organization_id
    )

    def edge(s_type, s_id, rel, t_type, t_id) -> None:
        session.add(
            GraphEdge(
                project_id=project_id,
                source_type=s_type,
                source_id=s_id,
                relation=rel,
                target_type=t_type,
                target_id=t_id,
            )
        )

    count = 0
    for kw in keywords:
        if kw.cluster_id:
            edge("keyword", kw.id, "belongs_to", "cluster", kw.cluster_id)
            count += 1
    for cluster in clusters:
        if cluster.topic_id:
            edge("cluster", cluster.id, "supports", "topic", cluster.topic_id)
            count += 1
    # Page -targets-> Keyword (best-effort: keyword text in title/meta).
    for page in pages:
        haystack = f"{page.title or ''} {page.meta_description or ''}".lower()
        for kw in keywords:
            if kw.keyword.lower() in haystack:
                edge("page", page.id, "targets", "keyword", kw.id)
                count += 1

    await session.flush()
    return count


async def get_graph(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> dict[str, Any]:
    """Return nodes + edges for visualization."""
    if not await repo.get_project(
        session, project_id=project_id, organization_id=organization_id
    ):
        raise NotFoundError(f"Project {project_id} not found.")

    pages = await repo.list_pages(
        session, project_id=project_id, organization_id=organization_id
    )
    keywords = await repo.list_keywords(
        session, project_id=project_id, organization_id=organization_id
    )
    clusters = await repo.list_clusters(
        session, project_id=project_id, organization_id=organization_id
    )
    topics = await repo.list_topics(session, project_id=project_id)
    edges = await repo.list_graph_edges(
        session, project_id=project_id, organization_id=organization_id
    )

    nodes = (
        [{"id": str(p.id), "type": "page", "label": p.url} for p in pages]
        + [{"id": str(k.id), "type": "keyword", "label": k.keyword} for k in keywords]
        + [{"id": str(c.id), "type": "cluster", "label": c.topic} for c in clusters]
        + [{"id": str(t.id), "type": "topic", "label": t.name} for t in topics]
    )
    edge_dicts = [
        {
            "source": str(e.source_id),
            "source_type": e.source_type,
            "relation": e.relation,
            "target": str(e.target_id),
            "target_type": e.target_type,
        }
        for e in edges
    ]
    return {"nodes": nodes, "edges": edge_dicts}
