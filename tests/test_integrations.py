"""Phase 6 tests: providers, GSC parsing, enrichment, Authority agent."""

from __future__ import annotations

from app.agents.base import AgentContext
from app.agents.workers import AuthorityAgent
from app.config import Settings
from app.db import repositories as repo
from app.integrations.gsc import parse_gsc_csv
from app.integrations.stubs import (
    StubBacklinkProvider,
    StubKeywordProvider,
    StubSerpProvider,
)
from app.services.enrichment import enrich_keywords


def test_parse_gsc_csv_standard_export() -> None:
    text = (
        "Query,Clicks,Impressions,CTR,Position\n"
        "seo audit,10,1000,1%,5.4\n"
        "free seo tool,0,50,0%,12\n"
    )
    rows = parse_gsc_csv(text)
    assert len(rows) == 2
    assert rows[0] == {
        "query": "seo audit",
        "clicks": 10,
        "impressions": 1000,
        "position": 5.4,
    }


def test_parse_gsc_csv_tolerant_headers_and_empty() -> None:
    # "Top queries" variant, only a query column.
    rows = parse_gsc_csv("Top queries\nbacklink checker\n")
    assert rows[0]["query"] == "backlink checker"
    # No recognizable query column -> empty.
    assert parse_gsc_csv("Foo,Bar\n1,2\n") == []


def test_stub_keyword_provider_is_deterministic_and_shaped() -> None:
    p = StubKeywordProvider()
    a = p.metrics(["seo audit"])
    b = p.metrics(["seo audit"])
    assert a == b  # deterministic
    m = a["seo audit"]
    assert isinstance(m["volume"], int) and 0.0 <= m["difficulty"] <= 1.0
    assert m["intent"] in {
        "informational",
        "commercial",
        "transactional",
        "navigational",
    }
    assert m["is_stub"] is True


def test_stub_serp_and_backlinks() -> None:
    pos = StubSerpProvider().positions("example.com", ["a", "b"])
    assert all(1 <= v <= 100 for v in pos.values())
    summary = StubBacklinkProvider().summary("example.com")
    assert summary["is_stub"] is True and summary["referring_domains"] >= 0


async def test_enrich_keywords_fills_metrics(db_session) -> None:
    org = await repo.create_organization(db_session, name="Acme")
    project = await repo.create_project(
        db_session, organization_id=org.id, name="S", domain="site.test"
    )
    await repo.add_keywords(
        db_session, project_id=project.id, keywords=["seo audit", "link building"]
    )
    enriched = await enrich_keywords(
        db_session, organization_id=org.id, project_id=project.id
    )
    assert enriched and all(k.volume is not None for k in enriched)
    assert all(k.intent is not None for k in enriched)


async def test_authority_agent_uses_backlink_provider(db_session) -> None:
    org = await repo.create_organization(db_session, name="Acme")
    project = await repo.create_project(
        db_session, organization_id=org.id, name="S", domain="site.test"
    )
    ctx = AgentContext(
        session=db_session,
        organization_id=org.id,
        project_id=project.id,
        settings=Settings(),
    )
    result = await AuthorityAgent().run(ctx)
    # With the stub provider it now produces data (low confidence, flagged stub).
    assert result.confidence == 0.3
    assert any("referring_domains" in e for e in result.evidence)
