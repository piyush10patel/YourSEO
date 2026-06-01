"""Phase 3 service tests: clustering, knowledge graph, recommendation status."""

from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import BadRequestError, NotFoundError
from app.db import repositories as repo
from app.services import clustering, knowledge_graph
from app.services import recommendations as rec_engine


async def _project(db_session):
    org = await repo.create_organization(db_session, name="Acme")
    project = await repo.create_project(
        db_session, organization_id=org.id, name="Site", domain="site.test"
    )
    return org, project


async def test_clustering_groups_keywords_by_head_term(db_session) -> None:
    org, project = await _project(db_session)
    await repo.add_keywords(
        db_session,
        project_id=project.id,
        keywords=[
            "technical seo audit",
            "seo audit tool",
            "keyword research",
            "keyword tool",
        ],
    )
    clusters = await clustering.cluster_keywords(
        db_session, project_id=project.id, organization_id=org.id
    )
    assert len(clusters) == 2
    topics = {c.topic for c in clusters}
    assert topics == {"audit", "keyword"}

    kws = await repo.list_keywords(
        db_session, project_id=project.id, organization_id=org.id
    )
    assert all(k.cluster_id is not None for k in kws)


async def test_clustering_is_idempotent(db_session) -> None:
    org, project = await _project(db_session)
    await repo.add_keywords(
        db_session, project_id=project.id, keywords=["seo audit", "seo report"]
    )
    first = await clustering.cluster_keywords(
        db_session, project_id=project.id, organization_id=org.id
    )
    second = await clustering.cluster_keywords(
        db_session, project_id=project.id, organization_id=org.id
    )
    # Re-running clears & rebuilds — no duplicate clusters accumulate.
    assert len(first) == len(second)


async def test_build_graph_creates_typed_edges(db_session) -> None:
    org, project = await _project(db_session)
    await repo.add_keywords(
        db_session, project_id=project.id, keywords=["seo audit tool"]
    )
    await clustering.cluster_keywords(
        db_session, project_id=project.id, organization_id=org.id
    )
    await repo.upsert_page(
        db_session,
        project_id=project.id,
        url="https://site.test/tools",
        title="Best SEO audit tool guide",
        meta_description=None,
        status_code=200,
        word_count=400,
    )

    edges = await knowledge_graph.build_graph(
        db_session, project_id=project.id, organization_id=org.id
    )
    assert edges >= 3  # keyword->cluster, cluster->topic, page->keyword

    graph = await knowledge_graph.get_graph(
        db_session, project_id=project.id, organization_id=org.id
    )
    relations = {e["relation"] for e in graph["edges"]}
    assert {"belongs_to", "supports", "targets"} <= relations
    assert {n["type"] for n in graph["nodes"]} >= {
        "page",
        "keyword",
        "cluster",
        "topic",
    }


async def test_recommendation_status_workflow(db_session) -> None:
    org, project = await _project(db_session)
    audit = await repo.create_audit(
        db_session,
        project_id=project.id,
        page_id=None,
        overall_score=50,
        grade="F",
        confidence="high",
    )
    rec = await repo.add_recommendation(
        db_session,
        project_id=project.id,
        audit_id=audit.id,
        type="technical_fix",
        title="Fix meta",
    )
    assert rec.status == "open"

    updated = await rec_engine.set_status(
        db_session, rec_id=rec.id, organization_id=org.id, status="done"
    )
    assert updated.status == "done"

    with pytest.raises(BadRequestError):
        await rec_engine.set_status(
            db_session, rec_id=rec.id, organization_id=org.id, status="nonsense"
        )

    with pytest.raises(NotFoundError):
        await rec_engine.set_status(
            db_session, rec_id=uuid.uuid4(), organization_id=org.id, status="done"
        )
