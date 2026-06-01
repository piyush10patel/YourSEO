"""Multi-page crawler (spec §6).

Pipeline per the spec: URL -> Queue -> Fetcher -> Parser -> Extractor ->
Normalizer -> Database. This module implements an async, same-domain BFS crawl
with a bounded frontier and concurrency, capturing the structural signals the
audit engine needs (status, title, meta, canonical, headings, images, links).

Unlike the single-page audit path, the crawler does NOT run a headless browser
per page (too heavy at scale) — it uses plain async HTTP. JS-only sites will
surface as thin pages, which the audit engine flags.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


@dataclass
class CrawledPage:
    url: str
    status_code: int
    title: str | None = None
    meta_description: str | None = None
    canonical: str | None = None
    word_count: int = 0
    h1_count: int = 0
    images_missing_alt: int = 0
    internal_links: list[str] = field(default_factory=list)
    external_links: list[str] = field(default_factory=list)
    error: str | None = None


@dataclass
class CrawlResult:
    seed_url: str
    pages: list[CrawledPage]
    # adjacency: source_url -> set of internal target urls (the link graph)
    edges: dict[str, set[str]] = field(default_factory=dict)

    @property
    def ok_pages(self) -> list[CrawledPage]:
        return [p for p in self.pages if 200 <= p.status_code < 300]


def _normalize(url: str) -> str:
    """Drop fragments and trailing slash for stable identity."""
    url, _ = urldefrag(url)
    if url.endswith("/") and urlparse(url).path not in ("", "/"):
        url = url.rstrip("/")
    return url


def parse_page(html: str, base_url: str) -> dict:
    """Extract structural signals from a page's HTML."""
    soup = BeautifulSoup(html, "lxml")

    title = soup.title.string.strip() if soup.title and soup.title.string else None
    meta_tag = soup.find("meta", attrs={"name": "description"})
    meta = meta_tag.get("content", "").strip() if meta_tag else None
    canon_tag = soup.find("link", attrs={"rel": "canonical"})
    canonical = canon_tag.get("href") if canon_tag else None

    base_host = urlparse(base_url).netloc.lower()
    internal: list[str] = []
    external: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = _normalize(urljoin(base_url, href))
        scheme = urlparse(absolute).scheme
        if scheme not in ("http", "https"):
            continue
        if urlparse(absolute).netloc.lower() == base_host:
            internal.append(absolute)
        else:
            external.append(absolute)

    images_missing_alt = sum(
        1 for img in soup.find_all("img") if not (img.get("alt") or "").strip()
    )
    h1_count = len(soup.find_all("h1"))

    # Word count of visible text (strip script/style first).
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    word_count = len(soup.get_text(" ", strip=True).split())

    return {
        "title": title,
        "meta_description": meta,
        "canonical": canonical,
        "internal_links": list(dict.fromkeys(internal)),
        "external_links": list(dict.fromkeys(external)),
        "images_missing_alt": images_missing_alt,
        "h1_count": h1_count,
        "word_count": word_count,
    }


class Crawler:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.settings.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    async def crawl(
        self,
        seed_url: str,
        *,
        max_pages: int = 50,
        max_depth: int = 3,
        concurrency: int = 5,
    ) -> CrawlResult:
        seed = _normalize(seed_url)
        seed_host = urlparse(seed).netloc.lower()

        visited: set[str] = set()
        pages: list[CrawledPage] = []
        edges: dict[str, set[str]] = {}
        # frontier holds (url, depth); a simple FIFO is enough for BFS.
        frontier: list[tuple[str, int]] = [(seed, 0)]
        sem = asyncio.Semaphore(concurrency)

        async with httpx.AsyncClient(
            headers=self._headers(),
            timeout=httpx.Timeout(self.settings.request_timeout),
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            while frontier and len(visited) < max_pages:
                # Process the current frontier level concurrently.
                batch = frontier[:max_pages]
                frontier = frontier[len(batch) :]
                tasks = []
                for url, depth in batch:
                    if url in visited or len(visited) >= max_pages:
                        continue
                    visited.add(url)
                    tasks.append(self._fetch_one(client, sem, url, depth, seed_host))
                if not tasks:
                    continue
                for page, depth, links in await asyncio.gather(*tasks):
                    pages.append(page)
                    edges[page.url] = set(page.internal_links)
                    if depth < max_depth:
                        for link in links:
                            if link not in visited:
                                frontier.append((link, depth + 1))

        return CrawlResult(seed_url=seed, pages=pages, edges=edges)

    async def _fetch_one(self, client, sem, url, depth, seed_host):
        async with sem:
            try:
                resp = await client.get(url)
            except httpx.HTTPError as exc:
                return CrawledPage(url=url, status_code=0, error=str(exc)), depth, []

            status = resp.status_code
            # Normalize the (possibly redirected) final URL so page identity
            # matches the normalized link targets — otherwise inbound-link and
            # broken-link matching fails and every page looks orphaned.
            final_url = _normalize(str(resp.url))
            page = CrawledPage(url=final_url, status_code=status)
            links: list[str] = []
            ctype = resp.headers.get("content-type", "")
            if status < 400 and "html" in ctype:
                data = parse_page(resp.text, final_url)
                page.title = data["title"]
                page.meta_description = data["meta_description"]
                page.canonical = data["canonical"]
                page.word_count = data["word_count"]
                page.h1_count = data["h1_count"]
                page.images_missing_alt = data["images_missing_alt"]
                page.internal_links = data["internal_links"]
                page.external_links = data["external_links"]
                # Only follow same-host internal links.
                links = [
                    link
                    for link in data["internal_links"]
                    if urlparse(link).netloc.lower() == seed_host
                ]
            return page, depth, links
