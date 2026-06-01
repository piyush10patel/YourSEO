"""Scraper tests: extraction + the async httpx fetch path.

Network is fully mocked with httpx.MockTransport — no real HTTP is performed.
Extraction (`extract`) is pure/sync; fetching (`fetch`/`scrape`) is async.
"""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.core.exceptions import (
    CrawlerBlockedError,
    EmptyContentError,
    HTTPStatusError,
    InvalidURLError,
    RateLimitedError,
)
from app.services.scraper import ScraperService


@pytest.fixture
def scraper(settings: Settings) -> ScraperService:
    return ScraperService(settings=settings)


def _scraper_with(settings: Settings, handler) -> ScraperService:
    return ScraperService(settings=settings, transport=httpx.MockTransport(handler))


# --------------------------------------------------------------------------- #
# Extraction (sync, pure)
# --------------------------------------------------------------------------- #
def test_extracts_clean_markdown_and_strips_noise(scraper: ScraperService) -> None:
    html = """
    <html><head><title>My Post</title>
    <meta name='description' content='A test page'></head>
    <body>
      <nav>menu junk</nav><header>site header</header>
      <article>
        <h1>Hello World</h1>
        <p>This is the <strong>main</strong> content.</p>
        <ul><li>one</li><li>two</li></ul>
        <script>console.log(1)</script>
      </article>
      <footer>copyright junk</footer>
    </body></html>
    """
    content = scraper.extract(html, base_url="https://x.com/post")
    assert content.title == "My Post"
    assert content.description == "A test page"
    assert "# Hello World" in content.markdown
    assert "**main**" in content.markdown
    assert "menu junk" not in content.markdown
    assert "copyright junk" not in content.markdown
    assert "console.log" not in content.markdown


def test_empty_page_raises_empty_content(scraper: ScraperService) -> None:
    with pytest.raises(EmptyContentError):
        scraper.extract("<html><body></body></html>", base_url="https://x.com")


def test_malformed_html_does_not_crash(scraper: ScraperService) -> None:
    malformed = "<html><body><div><p>Hello <b>world</p></div><span>more text here"
    content = scraper.extract(malformed, base_url="https://x.com")
    assert "Hello" in content.markdown and "world" in content.markdown


# --------------------------------------------------------------------------- #
# Async fetch path (mocked httpx transport)
# --------------------------------------------------------------------------- #
async def test_invalid_url_fails_fast(scraper: ScraperService) -> None:
    with pytest.raises(InvalidURLError):
        await scraper.scrape("ftp://not-http", render_js=False)


async def test_404_raises_http_status_error(settings: Settings) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404, text="nope")

    scraper = _scraper_with(settings, handler)
    with pytest.raises(HTTPStatusError) as exc_info:
        await scraper.scrape("https://example.com/missing", render_js=False)
    assert exc_info.value.upstream_status == 404
    assert calls["n"] == 1  # non-retryable, no retries


async def test_403_raises_crawler_blocked(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden")

    scraper = _scraper_with(settings, handler)
    with pytest.raises(CrawlerBlockedError):
        await scraper.scrape("https://example.com", render_js=False)


async def test_captcha_page_raises_crawler_blocked(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, html="<html><head><title>Just a moment...</title></head></html>"
        )

    scraper = _scraper_with(settings, handler)
    with pytest.raises(CrawlerBlockedError):
        await scraper.scrape("https://example.com", render_js=False)


async def test_429_retried_then_rate_limited(settings: Settings) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "1"}, text="slow down")

    scraper = _scraper_with(settings, handler)
    with pytest.raises(RateLimitedError):
        await scraper.fetch("https://example.com")
    assert calls["n"] == settings.max_retries  # 2 in test settings


async def test_happy_fetch_and_extract(settings: Settings) -> None:
    body = (
        "<html><head><title>Good Page</title></head><body>"
        "<article><h1>Heading</h1><p>" + ("word " * 60) + "</p></article>"
        "</body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html=body)

    scraper = _scraper_with(settings, handler)
    page, content = await scraper.scrape("https://example.com", render_js=False)
    assert page.status_code == 200
    assert content.title == "Good Page"
    assert "# Heading" in content.markdown
