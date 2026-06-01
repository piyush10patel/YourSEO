"""Crawler tests over a mocked multi-page site (httpx.MockTransport)."""

from __future__ import annotations

import httpx

from app.config import Settings
from app.services.crawler import Crawler, parse_page

# A tiny fake site: home -> about + blog; blog links a broken page.
_PAGES = {
    "https://site.test/": (
        200,
        "<html><head><title>Home</title>"
        "<meta name='description' content='Welcome to the home page of our site.'>"
        "</head><body><h1>Home</h1>"
        "<a href='/about'>About</a><a href='/blog'>Blog</a>"
        "<a href='https://external.test/x'>ext</a>" + ("word " * 60) + "</body></html>",
    ),
    "https://site.test/about": (
        200,
        "<html><head><title>About</title></head><body><h1>About</h1>"
        "<a href='/'>Home</a><img src='a.png'>" + ("about " * 60) + "</body></html>",
    ),
    "https://site.test/blog": (
        200,
        "<html><head><title>Home</title></head><body><h1>Blog</h1>"
        "<a href='/missing'>dead</a> thin</body></html>",
    ),
    "https://site.test/missing": (404, "not found"),
}


def _handler(request: httpx.Request) -> httpx.Response:
    key = str(request.url).rstrip("/") if request.url.path != "/" else str(request.url)
    # normalize trailing slash for lookup
    for candidate in (str(request.url), str(request.url).rstrip("/"), key):
        if candidate in _PAGES:
            status, html = _PAGES[candidate]
            return httpx.Response(status, html=html)
    return httpx.Response(404, text="nf")


def test_parse_page_extracts_structure() -> None:
    data = parse_page(_PAGES["https://site.test/"][1], "https://site.test/")
    assert data["title"] == "Home"
    assert data["h1_count"] == 1
    assert "https://site.test/about" in data["internal_links"]
    assert "https://external.test/x" in data["external_links"]
    assert data["word_count"] > 50


async def test_crawl_discovers_pages_and_records_status() -> None:
    settings = Settings()
    crawler = Crawler(settings=settings, transport=httpx.MockTransport(_handler))
    result = await crawler.crawl(
        "https://site.test/", max_pages=20, max_depth=3, concurrency=4
    )
    urls = {p.url: p.status_code for p in result.pages}
    assert "https://site.test/about" in urls
    assert "https://site.test/blog" in urls
    # the broken target was discovered and recorded as 404
    assert urls.get("https://site.test/missing") == 404
    # external links are not crawled
    assert "https://external.test/x" not in urls
