"""Audit-engine tests: checks over a synthetic crawl + persisted crawl->audit."""

from __future__ import annotations

from app.core.events import AUDIT_COMPLETED, Event, bus
from app.db import repositories as repo
from app.services.audit_engine import (
    run_project_crawl_audit,
    run_site_audit,
    score_from_issues,
)
from app.services.crawler import CrawledPage, CrawlResult


def _sample_result() -> CrawlResult:
    home = CrawledPage(
        url="https://site.test/",
        status_code=200,
        title="Home",
        meta_description="A welcoming home page with plenty of content here.",
        word_count=300,
        h1_count=1,
        internal_links=[
            "https://site.test/about",
            "https://site.test/blog",
            "https://site.test/missing",
        ],
    )
    about = CrawledPage(
        url="https://site.test/about",
        status_code=200,
        title="About",
        meta_description=None,
        word_count=300,
        h1_count=1,
        internal_links=["https://site.test/"],
    )
    blog = CrawledPage(
        url="https://site.test/blog",
        status_code=200,
        title="Home",  # dup title
        meta_description="x",
        word_count=5,
        h1_count=1,  # thin
        internal_links=["https://site.test/missing"],
    )
    missing = CrawledPage(url="https://site.test/missing", status_code=404)
    orphan = CrawledPage(
        url="https://site.test/orphan",
        status_code=200,
        title="Orphan",
        meta_description="orphan page",
        word_count=300,
        h1_count=1,
    )
    edges = {
        home.url: set(home.internal_links),
        about.url: set(about.internal_links),
        blog.url: set(blog.internal_links),
        missing.url: set(),
        orphan.url: set(),
    }
    return CrawlResult(
        seed_url="https://site.test/",
        pages=[home, about, blog, missing, orphan],
        edges=edges,
    )


def test_run_site_audit_detects_all_categories() -> None:
    issues = run_site_audit(_sample_result(), thin_words=150)
    types = {i.type for i in issues}
    assert "broken_link" in types  # -> /missing (404)
    assert "http_error" in types  # /missing itself
    assert "missing_meta" in types  # /about
    assert "thin_content" in types  # /blog
    assert "duplicate_title" in types  # Home shared by / and /blog
    assert "orphan_page" in types  # /orphan has no inbound links


def test_score_decreases_with_issues() -> None:
    issues = run_site_audit(_sample_result(), thin_words=150)
    assert 0 <= score_from_issues(issues, 4) < 100
    assert score_from_issues([], 4) == 100


async def test_run_project_crawl_audit_persists_and_emits(db_session) -> None:
    org = await repo.create_organization(db_session, name="Acme")
    project = await repo.create_project(
        db_session, organization_id=org.id, name="Site", domain="site.test"
    )

    fired: list[Event] = []
    bus.subscribe(AUDIT_COMPLETED, lambda e: fired.append(e) or _noop())

    class FakeCrawler:
        async def crawl(self, seed_url, **kwargs):
            return _sample_result()

    audit = await run_project_crawl_audit(
        db_session,
        organization_id=org.id,
        project_id=project.id,
        seed_url="https://site.test/",
        crawler=FakeCrawler(),
    )

    pages = await repo.list_pages(
        db_session, project_id=project.id, organization_id=org.id
    )
    recs = await repo.list_recommendations(
        db_session, project_id=project.id, organization_id=org.id
    )
    assert len(pages) == 5
    assert recs and recs[0].priority >= recs[-1].priority
    assert audit.overall_score < 100
    assert any(e.name == AUDIT_COMPLETED for e in fired)


async def _noop() -> None:
    return None
