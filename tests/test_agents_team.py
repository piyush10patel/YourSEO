"""Multi-agent system tests (spec §9-§10): contract, workers, evaluator, planner."""

from __future__ import annotations

import pytest

from app.agents.base import AgentContext, AgentResult
from app.agents.evaluator import EvaluatorAgent
from app.agents.planner import PlannerAgent
from app.agents.registry import get_agent, list_agents, worker_classes
from app.config import Settings
from app.core.exceptions import NotFoundError
from app.db import repositories as repo


async def _seeded_ctx(db_session) -> AgentContext:
    """A project with keywords, clusters, an audit and recommendations."""
    org = await repo.create_organization(db_session, name="Acme")
    project = await repo.create_project(
        db_session, organization_id=org.id, name="Site", domain="site.test"
    )
    await repo.add_keywords(
        db_session,
        project_id=project.id,
        keywords=["seo audit tool", "seo audit guide", "link building tips"],
    )
    from app.services import clustering

    await clustering.cluster_keywords(
        db_session, project_id=project.id, organization_id=org.id
    )
    await repo.upsert_page(
        db_session,
        project_id=project.id,
        url="https://site.test/",
        title="Home",
        meta_description=None,
        status_code=200,
        word_count=120,
    )
    audit = await repo.create_audit(
        db_session,
        project_id=project.id,
        page_id=None,
        overall_score=55,
        grade="F",
        confidence="high",
    )
    for typ, title in [
        ("missing_meta", "Missing meta description"),
        ("orphan_page", "Orphan page"),
        ("thin_content", "Thin content (120 words)"),
    ]:
        await repo.add_recommendation(
            db_session,
            project_id=project.id,
            audit_id=audit.id,
            type=typ,
            title=title,
            impact=0.6,
            confidence=0.8,
            effort=0.5,
            priority=0.96,
        )
    return AgentContext(
        session=db_session,
        organization_id=org.id,
        project_id=project.id,
        settings=Settings(),
    )


async def test_every_worker_returns_valid_contract(db_session) -> None:
    ctx = await _seeded_ctx(db_session)
    for name, cls in worker_classes().items():
        result = await cls().run(ctx)
        assert isinstance(result, AgentResult)
        assert result.agent == name
        assert 0.0 <= result.confidence <= 1.0
        assert 0.0 <= result.impact <= 1.0
        assert result.rationale


async def test_audit_agent_reads_persisted_findings(db_session) -> None:
    ctx = await _seeded_ctx(db_session)
    result = await get_agent("audit").run(ctx)
    assert result.confidence >= 0.8  # an audit exists
    assert result.recommendations


async def test_authority_agent_is_honest_stub(db_session) -> None:
    ctx = await _seeded_ctx(db_session)
    result = await get_agent("authority").run(ctx)
    assert result.confidence == 0.0  # no backlink provider configured


async def test_evaluator_ranks_by_confidence_times_impact() -> None:
    a = AgentResult(agent="a", confidence=0.9, impact=0.9, rationale="x")
    b = AgentResult(agent="b", confidence=0.2, impact=0.2, rationale="y")
    ev = EvaluatorAgent().evaluate([b, a])
    assert ev.evidence[0].startswith("a:")  # highest score first
    assert 0.0 <= ev.impact <= 1.0


async def test_planner_orchestrates_team_into_roadmap(db_session) -> None:
    ctx = await _seeded_ctx(db_session)
    result = await PlannerAgent().run(ctx)
    assert result.agent == "planner"
    assert result.recommendations  # roadmap items
    # roadmap items are tagged with their source agent
    assert any(item.startswith("[") for item in result.recommendations)


def test_registry_lists_all_agents_and_rejects_unknown() -> None:
    names = {a["name"] for a in list_agents()}
    assert {
        "audit",
        "keyword",
        "internal_linking",
        "optimization",
        "content",
        "authority",
        "planner",
        "evaluator",
    } <= names
    with pytest.raises(NotFoundError):
        get_agent("does_not_exist")
