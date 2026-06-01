"""API tests via FastAPI's TestClient with dependencies/services mocked."""

from __future__ import annotations

import app.api.routes as routes
from fastapi.testclient import TestClient

from app.api.routes import get_scraper
from app.main import app
from app.services.audit import AuditResult, ScoreBreakdown
from app.schemas.agent import KeywordGap, TechnicalFix
from tests.conftest import FakeScraper


client = TestClient(app)


def _fake_audit_result(url: str) -> AuditResult:
    return AuditResult(
        url=url,
        fetched_url=url,
        title="T",
        current_meta_description="m",
        word_count=200,
        overall_score=75,
        grade="C",
        breakdown=ScoreBreakdown(
            title=80, meta_description=70, content_depth=80, keyword_focus=70
        ),
        top_keywords=[],
        keyword_gaps=[KeywordGap(keyword="kw", rationale="why")],
        technical_fixes=[TechnicalFix(issue="i", recommendation="r", severity="low")],
        rewritten_meta_description="A better meta description for the page.",
        generated_by="live",
    )


def test_health_returns_typed_payload() -> None:
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "service" in body and "version" in body


def test_scrape_happy_path() -> None:
    app.dependency_overrides[get_scraper] = lambda: FakeScraper()
    try:
        resp = client.post(
            "/api/v1/scrape", json={"url": "https://example.com", "include_links": True}
        )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["status_code"] == 200
    assert body["metadata"]["title"] == "Vegan Bakery"
    assert body["metadata"]["word_count"] > 0
    assert body["markdown"].startswith("# Vegan Bakery")


def test_scrape_rejects_invalid_url() -> None:
    # Pydantic AnyHttpUrl rejects a non-http scheme -> 422 validation error.
    resp = client.post("/api/v1/scrape", json={"url": "not-a-url"})
    assert resp.status_code == 422
    assert resp.json()["error_code"] == "validation_error"


def test_unknown_route_returns_structured_error() -> None:
    resp = client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "http_error"


def test_audit_endpoint(monkeypatch) -> None:
    async def fake_run_audit_async(url, settings=None, **kwargs):
        return _fake_audit_result(url)

    monkeypatch.setattr(routes, "run_audit_async", fake_run_audit_async)
    resp = client.post(
        "/api/v1/audit", json={"url": "https://example.com", "render_js": False}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall_score"] == 75
    assert body["keyword_gaps"][0]["keyword"] == "kw"
    assert body["from_cache"] is False


def test_audit_stream_emits_sse_events(monkeypatch) -> None:
    async def fake_run_audit_async(url, settings=None, **kwargs):
        return _fake_audit_result(url)

    async def fake_stream_summary_async(result, settings=None):
        for token in ["Great ", "summary."]:
            yield token

    monkeypatch.setattr(routes, "run_audit_async", fake_run_audit_async)
    monkeypatch.setattr(routes, "stream_summary_async", fake_stream_summary_async)

    resp = client.post(
        "/api/v1/audit/stream", json={"url": "https://example.com", "render_js": False}
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    text = resp.text
    assert "event: result" in text
    assert "event: token" in text
    assert "Great " in text and "summary." in text
    assert "event: done" in text
