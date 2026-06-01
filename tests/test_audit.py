"""Audit service tests: scoring, content guards, and demo result (no network)."""

from __future__ import annotations

from app.schemas.agent import KeywordGap
from app.services.audit import (
    AuditResult,
    assess_content,
    compute_score,
    demo_result,
    _filter_ungrounded_gaps,
)


def test_score_high_for_well_optimized_page() -> None:
    analysis = {
        "top_keywords": [{"term": "vegan cake", "count": 10, "density_pct": 2.0}]
    }
    score, breakdown = compute_score(
        title="A Great Vegan Bakery in Brooklyn Serving Fresh Cakes",
        meta="x" * 155,
        word_count=900,
        analysis=analysis,
    )
    assert score >= 85
    assert breakdown.title == 100
    assert breakdown.meta_description == 100


def test_score_low_for_thin_page() -> None:
    score, breakdown = compute_score(
        title=None,
        meta=None,
        word_count=40,
        analysis={"top_keywords": []},
    )
    assert score <= 20
    assert breakdown.meta_description == 0


def test_demo_result_is_valid() -> None:
    result = demo_result("https://example.com")
    assert isinstance(result, AuditResult)
    assert result.generated_by == "demo"
    assert 0 <= result.overall_score <= 100
    assert result.keyword_gaps and result.technical_fixes
    assert result.rewritten_meta_description
    assert result.confidence == "high"


def test_assess_content_flags_login_wall() -> None:
    # Mimics LinkedIn's logged-out landing page.
    confidence, warnings, usable = assess_content(
        "LinkedIn: Log In or Sign Up",
        "Welcome to your professional community " * 80,
        640,
    )
    assert confidence == "low"
    assert usable is False  # LLM must be skipped — it's a login wall
    assert any("login" in w.lower() for w in warnings)


def test_assess_content_flags_thin_content() -> None:
    confidence, warnings, usable = assess_content(
        "Some Page", "only a few words here", 4
    )
    assert confidence == "low"
    assert usable is False  # below the LLM floor
    assert any("thin" in w.lower() for w in warnings)


def test_assess_content_passes_good_page() -> None:
    confidence, warnings, usable = assess_content(
        "Artisan Vegan Bakery", "fresh vegan cake " * 200, 400
    )
    assert confidence == "high"
    assert usable is True
    assert warnings == []


def test_filter_ungrounded_gaps_drops_already_prominent_terms() -> None:
    markdown = "vegan cake vegan cake vegan cake everywhere on this page"
    gaps = [
        KeywordGap(keyword="vegan cake", rationale="hallucinated — already prominent"),
        KeywordGap(keyword="gluten free delivery", rationale="genuinely absent"),
    ]
    kept = _filter_ungrounded_gaps(gaps, markdown)
    assert [g.keyword for g in kept] == ["gluten free delivery"]
