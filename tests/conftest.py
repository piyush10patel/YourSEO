"""Shared pytest fixtures and test doubles.

Everything here is offline — no network, no Ollama, no headless browser — so
the suite runs fast and deterministically in CI.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.services.scraper import ExtractedContent, FetchedPage


@pytest.fixture
def settings() -> Settings:
    """Settings tuned for fast, deterministic tests (tiny backoff, no retries)."""
    return Settings(
        max_retries=2,
        backoff_initial=0.001,
        backoff_max=0.002,
        ollama_max_retries=1,
        agent_temperature=0.0,
        agent_max_steps=6,
    )


class FakeScraper:
    """Stands in for ScraperService.scrape — returns canned page content."""

    def __init__(
        self, markdown: str | None = None, title: str = "Vegan Bakery"
    ) -> None:
        self.calls: list[str] = []
        self._markdown = markdown or (
            "# Vegan Bakery\n\nWe sell vegan cake and vegan cookies. Our vegan "
            "cake is the best vegan cake in town. Order vegan treats today."
        )
        self._title = title

    async def scrape(
        self, url: str, *, include_links: bool = True, render_js: Any = "auto"
    ):
        self.calls.append(url)
        page = FetchedPage(final_url=url + "/", status_code=200, html="<html/>")
        content = ExtractedContent(
            title=self._title,
            description="Old meta.",
            canonical_url=None,
            markdown=self._markdown,
        )
        return page, content


@pytest.fixture
def fake_scraper() -> FakeScraper:
    return FakeScraper()
