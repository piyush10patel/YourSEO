"""Shared pytest fixtures and test doubles.

Everything here is offline — no network, no Ollama, no headless browser — so
the suite runs fast and deterministically in CI.
"""

from __future__ import annotations

from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db import models  # noqa: F401  (registers tables on Base.metadata)
from app.db.base import Base
from app.services.scraper import ExtractedContent, FetchedPage


@pytest_asyncio.fixture
async def db_sessionmaker():
    """In-memory SQLite async sessionmaker with the schema created.

    StaticPool keeps a single connection so the :memory: DB persists for the
    whole test. Portable column types mean the same models that run on Postgres
    work here unchanged.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    yield maker
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_sessionmaker):
    async with db_sessionmaker() as session:
        yield session


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
