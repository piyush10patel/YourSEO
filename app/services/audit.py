"""Audit service: the single entry point the UI calls.

Produces one tidy `AuditResult` that bundles everything the dashboard needs:
hard on-page metrics + a computed SEO score, plus the LLM-generated
qualitative report (keyword gaps, technical fixes, rewritten meta).

Two modes:
  * live  -- scrape -> keyword-analyze -> score, then ask the LLM for the
             qualitative report (`FinalReport`).
  * demo  -- deterministic sample data; no network or model required, so the
             UI is fully demoable offline.

The autonomous ReAct `AgentOrchestrator` is the multi-step alternative for the
API; here we use the cheaper, deterministic scrape->analyze->one-LLM-call path
because the UI already has the page content in hand and wants a fast, single
structured answer.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, AsyncIterator

from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.schemas.agent import FinalReport, KeywordGap, TechnicalFix
from app.services.cache import build_cache
from app.services.keyword_analyzer import analyze_keywords
from app.services.ollama import OllamaClient
from app.services.scraper import ScraperService

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Result model
# --------------------------------------------------------------------------- #
class ScoreBreakdown(BaseModel):
    title: int = Field(..., ge=0, le=100)
    meta_description: int = Field(..., ge=0, le=100)
    content_depth: int = Field(..., ge=0, le=100)
    keyword_focus: int = Field(..., ge=0, le=100)


class AuditResult(BaseModel):
    url: str
    fetched_url: str
    title: str | None
    current_meta_description: str | None
    word_count: int

    overall_score: int = Field(..., ge=0, le=100)
    grade: str
    breakdown: ScoreBreakdown

    top_keywords: list[dict[str, Any]]
    keyword_gaps: list[KeywordGap]
    technical_fixes: list[TechnicalFix]
    rewritten_meta_description: str

    generated_by: str  # "live" | "demo"
    from_cache: bool = False  # True when served from the 24h cache
    confidence: str = "high"  # "high" | "low" — how trustworthy the audit is
    warnings: list[str] = Field(default_factory=list)  # data-quality caveats


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def _range_score(
    value: float, lo: float, hi: float, floor: float, ceil: float
) -> float:
    """100 inside [lo, hi]; ramps linearly to 0 at `floor`/`ceil`."""
    if lo <= value <= hi:
        return 100.0
    if value < lo:
        if value <= floor:
            return 0.0
        return (value - floor) / (lo - floor) * 100.0
    if value >= ceil:
        return 0.0
    return (ceil - value) / (ceil - hi) * 100.0


def _clamp(v: float) -> int:
    return max(0, min(100, int(round(v))))


def _grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"


def compute_score(
    *,
    title: str | None,
    meta: str | None,
    word_count: int,
    analysis: dict[str, Any],
) -> tuple[int, ScoreBreakdown]:
    """Derive a 0-100 SEO score from concrete on-page signals."""
    title_s = _range_score(len(title), 30, 60, 0, 90) if title else 0.0
    meta_s = _range_score(len(meta), 120, 160, 0, 220) if meta else 0.0
    depth_s = min(100.0, word_count / 600 * 100)

    top = analysis.get("top_keywords") or []
    top_density = top[0]["density_pct"] if top else 0.0
    # Healthy primary-keyword density is ~1-3%; reward that, penalise stuffing.
    focus_s = _range_score(top_density, 1.0, 3.0, 0.0, 8.0)

    breakdown = ScoreBreakdown(
        title=_clamp(title_s),
        meta_description=_clamp(meta_s),
        content_depth=_clamp(depth_s),
        keyword_focus=_clamp(focus_s),
    )
    overall = _clamp(0.20 * title_s + 0.25 * meta_s + 0.25 * depth_s + 0.30 * focus_s)
    return overall, breakdown


# --------------------------------------------------------------------------- #
# Content-quality assessment (guards against auditing the wrong page)
# --------------------------------------------------------------------------- #
# Below this, results are flagged low-confidence.
_MIN_WORDS_OK = 150
# Below this (or on a login wall), the LLM is skipped entirely — there is
# nothing real to ground a report on, so we refuse to fabricate one.
_MIN_WORDS_FOR_LLM = 80

_LOGIN_RE = re.compile(
    r"\b(log ?in|sign ?in|sign ?up|create (an )?account|forgot password|"
    r"log into your account)\b",
    re.IGNORECASE,
)


def assess_content(
    title: str | None, markdown: str, word_count: int
) -> tuple[str, list[str], bool]:
    """Return (confidence, warnings, usable).

    ``usable`` is False when the page is a login wall or too thin to audit —
    the caller then skips the LLM rather than generating ungrounded advice.
    """
    warnings: list[str] = []
    confidence = "high"

    login_in_title = bool(title and _LOGIN_RE.search(title))
    login_in_body = bool(_LOGIN_RE.search(markdown[:800]))
    login_wall = login_in_title or (login_in_body and word_count < 250)

    if login_wall:
        warnings.append(
            "This looks like a login / sign-up page, not the page's real "
            "content. The score and recommendations reflect the logged-out "
            "page — log-in-walled sites (LinkedIn, Facebook, ...) can't be "
            "audited by an unauthenticated crawler."
        )
        confidence = "low"

    if word_count < _MIN_WORDS_OK:
        warnings.append(
            f"Thin content: only {word_count} words were extracted, so the "
            "score and recommendations may be unreliable."
        )
        confidence = "low"

    usable = (not login_wall) and word_count >= _MIN_WORDS_FOR_LLM
    return confidence, warnings, usable


def _filter_ungrounded_gaps(gaps: list[KeywordGap], markdown: str) -> list[KeywordGap]:
    """Drop 'gaps' the model invented for terms already prominent on the page.

    A genuine keyword gap is a term that's absent or under-used; if the model
    suggests one that already appears several times, it's hallucinated noise.
    """
    text = markdown.lower()
    kept: list[KeywordGap] = []
    for gap in gaps:
        kw = gap.keyword.lower().strip()
        if kw and text.count(kw) < 3:
            kept.append(gap)
    return kept


# --------------------------------------------------------------------------- #
# Live audit
# --------------------------------------------------------------------------- #
async def _generate_report(
    llm: OllamaClient,
    *,
    fetched_url: str,
    title: str | None,
    meta: str | None,
    word_count: int,
    analysis: dict[str, Any],
    content: str,
) -> FinalReport:
    prompt = (
        "Analyze this web page for SEO and produce an improvement report.\n\n"
        f"URL: {fetched_url}\n"
        f"Title: {title!r}\n"
        f"Current meta description: {meta!r}\n"
        f"Word count: {word_count}\n\n"
        "Keyword analysis (top terms with density):\n"
        f"{json.dumps(analysis, indent=2)[:3000]}\n\n"
        "Page content excerpt:\n"
        f"{content[:3000]}\n\n"
        "Produce: keyword_gaps (valuable terms the page under-targets, with a "
        "rationale grounded in the analysis), technical_fixes (concrete on-page "
        "issues with severity), and a rewritten_meta_description of 150-160 "
        "characters that is compelling and keyword-rich.\n\n"
        "Only suggest keyword gaps that are NOT already frequent in the content "
        "above. If the content is too sparse to analyze, return empty lists."
    )
    system = (
        "You are a senior SEO strategist. Ground EVERY statement strictly in the "
        "provided page content and keyword analysis. Do NOT invent statistics, "
        "traffic numbers, competitor names, or any claim the content does not "
        "support. A keyword_gap must be a topically-relevant term that is ABSENT "
        "or under-used on the page — never one already prominent. If the page "
        "lacks real content, return empty keyword_gaps and technical_fixes "
        "rather than guessing."
    )
    return await llm.generate_json(
        prompt,
        schema=FinalReport,
        system=system,
        temperature=0.1,  # low temp -> more deterministic, less embellishment
    )


async def run_audit_async(
    url: str,
    settings: Settings | None = None,
    *,
    demo: bool = False,
    render_js: bool | str = "auto",
    use_cache: bool = True,
) -> AuditResult:
    settings = settings or get_settings()
    if demo:
        return demo_result(url)

    # Return a recent (<= TTL) cached audit instantly, skipping scrape + LLM.
    cache = build_cache(settings) if use_cache else None
    if cache is not None:
        cached = await cache.get(url)
        if cached is not None:
            logger.info("Cache hit for %s — returning stored audit.", url)
            cached["from_cache"] = True
            return AuditResult(**cached)

    scraper = ScraperService(settings=settings)
    page, content = await scraper.scrape(url, render_js=render_js)
    word_count = len(content.markdown.split())
    analysis = analyze_keywords(content.markdown)

    overall, breakdown = compute_score(
        title=content.title,
        meta=content.description,
        word_count=word_count,
        analysis=analysis,
    )

    confidence, warnings, usable = assess_content(
        content.title, content.markdown, word_count
    )

    if not usable:
        # Refuse to fabricate a report on a login wall / near-empty page.
        logger.info("Skipping LLM for %s (low-quality content).", url)
        report = FinalReport(
            keyword_gaps=[],
            technical_fixes=[],
            rewritten_meta_description=(
                content.description
                or content.title
                or "No meaningful content was available to generate a description."
            ),
        )
        warnings.append(
            "AI recommendations were skipped to avoid ungrounded advice on this page."
        )
    else:
        async with OllamaClient(settings=settings) as llm:
            report = await _generate_report(
                llm,
                fetched_url=page.final_url,
                title=content.title,
                meta=content.description,
                word_count=word_count,
                analysis=analysis,
                content=content.markdown,
            )
        # Drop any keyword gaps the model invented for already-prominent terms.
        report.keyword_gaps = _filter_ungrounded_gaps(
            report.keyword_gaps, content.markdown
        )

    result = AuditResult(
        url=url,
        fetched_url=page.final_url,
        title=content.title,
        current_meta_description=content.description,
        word_count=word_count,
        overall_score=overall,
        grade=_grade(overall),
        breakdown=breakdown,
        top_keywords=(analysis.get("top_keywords") or [])[:8],
        keyword_gaps=report.keyword_gaps,
        technical_fixes=report.technical_fixes,
        rewritten_meta_description=report.rewritten_meta_description,
        generated_by="live",
        confidence=confidence,
        warnings=warnings,
    )

    if cache is not None:
        await cache.set(url, result.model_dump())

    return result


# --------------------------------------------------------------------------- #
# Streaming executive summary (token-by-token, free text)
# --------------------------------------------------------------------------- #
def _summary_prompt(result: AuditResult) -> str:
    gaps = "; ".join(g.keyword for g in result.keyword_gaps) or "none"
    fixes = "; ".join(f.issue for f in result.technical_fixes) or "none"
    return (
        f"SEO audit results for {result.fetched_url}:\n"
        f"- Overall score: {result.overall_score}/100 (grade {result.grade})\n"
        f"- Word count: {result.word_count}\n"
        f"- Keyword gaps: {gaps}\n"
        f"- Technical issues: {fixes}\n"
        f"- Suggested meta description: {result.rewritten_meta_description}\n\n"
        "Write a concise executive summary (3-5 sentences) for a non-technical "
        "business owner: what the score means, the 1-2 highest-impact actions, "
        "and the expected benefit. Be encouraging and specific."
    )


async def stream_summary_async(
    result: AuditResult,
    settings: Settings | None = None,
) -> AsyncIterator[str]:
    """Stream a plain-text executive summary of an audit, token by token."""
    settings = settings or get_settings()
    system = (
        "You are a senior SEO strategist writing a brief, friendly executive "
        "summary. Plain prose only — no markdown headings or JSON."
    )
    async with OllamaClient(settings=settings) as llm:
        async for chunk in llm.stream_chat(
            _summary_prompt(result), system=system, temperature=0.4
        ):
            yield chunk


def run_audit(
    url: str,
    settings: Settings | None = None,
    *,
    demo: bool = False,
    render_js: bool | str = "auto",
    use_cache: bool = True,
) -> AuditResult:
    """Synchronous wrapper for Streamlit (which runs in a sync context)."""
    return asyncio.run(
        run_audit_async(
            url, settings, demo=demo, render_js=render_js, use_cache=use_cache
        )
    )


# --------------------------------------------------------------------------- #
# Demo data
# --------------------------------------------------------------------------- #
def demo_result(url: str) -> AuditResult:
    """Deterministic sample audit so the UI works with no backend."""
    analysis_top = [
        {"term": "vegan cake", "count": 14, "density_pct": 2.1},
        {"term": "bakery", "count": 11, "density_pct": 1.6},
        {"term": "gluten free", "count": 6, "density_pct": 0.9},
        {"term": "delivery", "count": 5, "density_pct": 0.7},
        {"term": "cupcakes", "count": 4, "density_pct": 0.6},
        {"term": "organic", "count": 3, "density_pct": 0.4},
    ]
    return AuditResult(
        url=url,
        fetched_url=url,
        title="Sweet Roots — Artisan Vegan Bakery",
        current_meta_description="We bake vegan cakes.",
        word_count=512,
        overall_score=72,
        grade="C",
        breakdown=ScoreBreakdown(
            title=88, meta_description=40, content_depth=85, keyword_focus=95
        ),
        top_keywords=analysis_top,
        keyword_gaps=[
            KeywordGap(
                keyword="gluten free vegan cake",
                rationale="High-intent long-tail term mentioned only once; competitors rank for it.",
            ),
            KeywordGap(
                keyword="vegan birthday cake delivery",
                rationale="Strong commercial intent and not present on the page at all.",
            ),
            KeywordGap(
                keyword="eggless dessert recipes",
                rationale="Top-of-funnel term that could drive blog traffic; currently uncovered.",
            ),
        ],
        technical_fixes=[
            TechnicalFix(
                issue="Meta description is only 20 characters.",
                recommendation="Expand to 150-160 chars with primary keywords and a clear CTA.",
                severity="high",
            ),
            TechnicalFix(
                issue="No structured data (schema.org) for the bakery/products.",
                recommendation="Add LocalBusiness and Product JSON-LD to enable rich results.",
                severity="medium",
            ),
            TechnicalFix(
                issue="Several images are missing descriptive alt text.",
                recommendation="Add keyword-relevant alt text to all product images.",
                severity="low",
            ),
        ],
        rewritten_meta_description=(
            "Order artisan vegan cakes, gluten-free treats & eggless desserts from "
            "Sweet Roots Bakery. Fresh daily, delivered to your door. Taste the difference!"
        ),
        generated_by="demo",
    )
