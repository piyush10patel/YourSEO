"""Tool definitions for the ReAct agent.

A `Tool` couples a name + LLM-facing description with an async implementation.
Each implementation takes the raw ``args`` dict the LLM produced plus a
`RunContext` (shared scratch state for one ``run``), and returns a plain-text
*observation* that is fed back into the loop.

Tools never raise for *expected* problems (bad args, scrape failure): they
return an error string so the LLM can read it and self-correct — that is the
whole point of ReAct. Genuinely unexpected exceptions propagate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.core.exceptions import ScraperError
from app.services.keyword_analyzer import analyze_keywords
from app.services.scraper import ScraperService


@dataclass
class RunContext:
    """Per-run shared state. Tools read/write artifacts here so large blobs
    (e.g. scraped page text) don't have to round-trip through the LLM."""

    scraper: ScraperService
    artifacts: dict[str, Any] = field(default_factory=dict)


ToolFunc = Callable[[dict[str, Any], RunContext], Awaitable[str]]


@dataclass
class Tool:
    name: str
    description: str
    args_hint: str
    func: ToolFunc

    async def __call__(self, args: dict[str, Any], ctx: RunContext) -> str:
        return await self.func(args, ctx)


# --------------------------------------------------------------------------- #
# scrape_url
# --------------------------------------------------------------------------- #
async def _scrape_url(args: dict[str, Any], ctx: RunContext) -> str:
    url = (args or {}).get("url")
    if not url or not isinstance(url, str):
        return "Error: 'scrape_url' requires a string 'url' argument."

    try:
        page, content = await ctx.scraper.scrape(url)
    except ScraperError as exc:
        return f"Error: could not scrape {url}: {exc.message}"

    # Stash the full content so analyze_keywords can use it without the LLM
    # having to copy the whole page back as an argument.
    ctx.artifacts["page_markdown"] = content.markdown
    ctx.artifacts["page_metadata"] = {
        "final_url": page.final_url,
        "title": content.title,
        "meta_description": content.description,
        "canonical_url": content.canonical_url,
    }

    preview = content.markdown[:800]
    return (
        f"Scraped {page.final_url} (HTTP {page.status_code}).\n"
        f"Title: {content.title!r}\n"
        f"Existing meta description: {content.description!r}\n"
        f"Canonical: {content.canonical_url!r}\n"
        f"Word count: {len(content.markdown.split())}\n"
        f"(Full text saved; call analyze_keywords to profile it.)\n"
        f"Content preview:\n{preview}"
    )


# --------------------------------------------------------------------------- #
# analyze_keywords
# --------------------------------------------------------------------------- #
async def _analyze_keywords(args: dict[str, Any], ctx: RunContext) -> str:
    args = args or {}
    # Prefer explicit text; otherwise fall back to the last scraped page.
    text = args.get("text") or ctx.artifacts.get("page_markdown")
    if not text:
        return (
            "Error: no text to analyze. Provide a 'text' argument or call "
            "scrape_url first to load a page."
        )

    targets = args.get("target_keywords")
    if isinstance(targets, str):
        targets = [targets]

    result = analyze_keywords(text, target_keywords=targets)
    ctx.artifacts["keyword_analysis"] = result
    return "Keyword analysis:\n" + json.dumps(result, indent=2, ensure_ascii=False)


def build_default_tools(scraper: ScraperService | None = None) -> dict[str, Tool]:
    """Return the agent's tool registry (optionally sharing a scraper)."""
    return {
        "scrape_url": Tool(
            name="scrape_url",
            description="Fetch a web page and return its title, meta description, "
            "and clean main-body text. Use this first to load the page you are "
            "optimizing.",
            args_hint='{"url": "https://example.com"}',
            func=_scrape_url,
        ),
        "analyze_keywords": Tool(
            name="analyze_keywords",
            description="Profile keyword usage of text: top keywords/phrases with "
            "density, plus coverage of any target keywords you pass. If you omit "
            "'text', it analyzes the most recently scraped page.",
            args_hint='{"text": "(optional)", "target_keywords": ["seo", "..."]}',
            func=_analyze_keywords,
        ),
    }
