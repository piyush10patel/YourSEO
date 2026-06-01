"""Web scraping service.

Pipeline:
    1. fetch()      -- GET the URL with browser-like headers + exponential
                       backoff on rate limiting / transient failures.
    2. extract()    -- locate the main body content with BeautifulSoup and
                       strip scripts, styles, nav, ads, and other chrome.
    3. to_markdown()-- convert the cleaned HTML fragment to tidy Markdown.

The public entry point is `ScraperService.scrape(url)`.

Everything raises subclasses of `app.core.exceptions.ScraperError`; the API
layer is responsible for turning those into HTTP responses.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup, Comment, Tag
from markdownify import markdownify as md
from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import Settings, get_settings
from app.services import renderer
from app.core.exceptions import (
    ContentTooLargeError,
    CrawlerBlockedError,
    EmptyContentError,
    FetchError,
    HTTPStatusError,
    InvalidURLError,
    RateLimitedError,
)

logger = logging.getLogger(__name__)

# Status codes that mean "back off and try again" rather than "give up".
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Markers that indicate a bot-challenge / CAPTCHA interstitial rather than the
# real page (kept specific to avoid false positives on pages that merely
# mention "captcha").
_BLOCK_MARKERS = (
    "just a moment...",
    "challenge-platform",
    "/cdn-cgi/challenge-platform",
    "captcha-delivery",
    "px-captcha",
    "attention required! | cloudflare",
)

# Tags whose entire subtree is noise for content extraction.
_STRIP_TAGS = (
    "script",
    "style",
    "noscript",
    "template",
    "iframe",
    "svg",
    "form",
    "nav",
    "header",
    "footer",
    "aside",
)

# Containers most likely to hold the primary article body, best first.
_MAIN_SELECTORS = (
    "article",
    "main",
    '[role="main"]',
    "#content",
    "#main",
    ".post-content",
    ".article-content",
    ".entry-content",
    ".content",
)

# Class/id substrings that signal boilerplate even outside the stripped tags.
_NOISE_PATTERN = re.compile(
    r"(?:^|[-_ ])(?:nav|menu|sidebar|footer|header|comment|share|social|"
    r"promo|banner|advert|ads?|cookie|popup|modal|breadcrumb|pagination|"
    r"related|newsletter|subscribe)(?:$|[-_ ])",
    re.IGNORECASE,
)


class _RetryableFetch(Exception):
    """Internal signal: this fetch attempt failed but is worth retrying."""

    def __init__(self, reason: str, *, status: int | None = None) -> None:
        super().__init__(reason)
        self.status = status


@dataclass
class FetchedPage:
    final_url: str
    status_code: int
    html: str


@dataclass
class ExtractedContent:
    title: str | None
    description: str | None
    canonical_url: str | None
    markdown: str


class ScraperService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        # Optional transport injection makes the async HTTP path fully testable
        # (e.g. httpx.MockTransport) without real network access.
        self._transport = transport

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def scrape(
        self,
        url: str,
        *,
        include_links: bool = True,
        render_js: bool | str = "auto",
    ) -> tuple[FetchedPage, ExtractedContent]:
        """Scrape ``url`` to (page, content).

        ``render_js`` controls the headless-browser path:
          * "auto" (default): use the fast async HTTP fetch; if extraction
            yields no content (JS-rendered page), transparently re-fetch with
            headless Chromium.
          * True: always render with Chromium.
          * False: never render; raise EmptyContentError on empty pages.
        """
        self._validate_url(url)

        if render_js is True:
            page = await self.fetch_rendered(url)
            content = self.extract(
                page.html, base_url=page.final_url, include_links=include_links
            )
            return page, content

        page = await self.fetch(url)
        try:
            content = self.extract(
                page.html, base_url=page.final_url, include_links=include_links
            )
        except EmptyContentError:
            # Empty almost always means client-side rendering — fall back to a
            # headless browser when allowed and available.
            if render_js == "auto" and renderer.is_available():
                logger.info("Empty content for %s; retrying with headless render.", url)
                page = await self.fetch_rendered(url)
                content = self.extract(
                    page.html, base_url=page.final_url, include_links=include_links
                )
            else:
                raise
        return page, content

    async def fetch_rendered(self, url: str) -> FetchedPage:
        """Fetch ``url`` via headless Chromium (executes JavaScript).

        Playwright's browser subprocess needs a ProactorEventLoop on Windows,
        which the synchronous ``renderer.render`` sets up on its own loop. We
        run it in a worker thread so it neither blocks our event loop nor
        collides with it.
        """
        rendered = await asyncio.to_thread(
            renderer.render,
            url,
            user_agent=self.settings.user_agent,
            timeout=self.settings.request_timeout * 2,  # JS pages need more time
        )
        return FetchedPage(
            final_url=rendered.final_url,
            status_code=rendered.status_code,
            html=rendered.html,
        )

    # ------------------------------------------------------------------ #
    # Step 1: fetch (async, non-blocking)
    # ------------------------------------------------------------------ #
    async def fetch(self, url: str) -> FetchedPage:
        """Fetch ``url``, retrying transient/rate-limit failures with backoff."""
        s = self.settings

        async with httpx.AsyncClient(
            headers=self._browser_headers(),
            timeout=httpx.Timeout(s.request_timeout),
            follow_redirects=True,
            transport=self._transport,
        ) as client:
            try:
                # tenacity drives exponential backoff. We retry only on the
                # internal _RetryableFetch signal so a 404 fails fast.
                async for attempt in AsyncRetrying(
                    reraise=True,
                    stop=stop_after_attempt(s.max_retries),
                    wait=wait_exponential(
                        multiplier=s.backoff_initial,
                        exp_base=s.backoff_multiplier,
                        max=s.backoff_max,
                    ),
                    retry=retry_if_exception_type(_RetryableFetch),
                    before_sleep=_log_backoff,
                ):
                    with attempt:
                        return await self._fetch_once(client, url)
            except _RetryableFetch as exc:
                # Retries exhausted on a retryable condition.
                if exc.status in (429, 503):
                    raise RateLimitedError(
                        "Target kept rate limiting us after all retries.",
                        detail=str(exc),
                    ) from exc
                raise FetchError(
                    "Target remained unavailable after all retries.",
                    detail=str(exc),
                ) from exc

        # Unreachable (AsyncRetrying with reraise=True always returns or raises).
        raise FetchError("Fetch produced no response.")

    async def _fetch_once(self, client: httpx.AsyncClient, url: str) -> FetchedPage:
        try:
            async with client.stream("GET", url) as resp:
                status = resp.status_code

                if status in _RETRYABLE_STATUS:
                    retry_after = resp.headers.get("Retry-After")
                    raise _RetryableFetch(
                        f"upstream returned {status}"
                        + (f" (Retry-After: {retry_after})" if retry_after else ""),
                        status=status,
                    )

                if status in (401, 403):
                    raise CrawlerBlockedError(
                        "Target website blocked the crawler.",
                        detail=f"HTTP {status}",
                    )

                if status >= 400:
                    raise HTTPStatusError(
                        f"Target returned HTTP {status}.",
                        upstream_status=status,
                    )

                html = await self._read_capped(resp)
                final_url = str(resp.url)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            # Connection/timeout/TLS issues are transient enough to retry.
            raise _RetryableFetch(f"request failed: {exc}") from exc

        # A 200 that's really a bot-challenge page is also "blocked".
        if _looks_blocked(html):
            raise CrawlerBlockedError(
                "Target website blocked the crawler.",
                detail="bot-challenge / CAPTCHA page detected",
            )

        return FetchedPage(final_url=final_url, status_code=status, html=html)

    async def _read_capped(self, resp: httpx.Response) -> str:
        """Stream the body, aborting if it exceeds the configured byte cap."""
        limit = self.settings.max_content_bytes
        chunks: list[bytes] = []
        total = 0
        async for chunk in resp.aiter_bytes(chunk_size=16_384):
            total += len(chunk)
            if total > limit:
                raise ContentTooLargeError(
                    f"Response exceeded the {limit} byte limit.",
                )
            chunks.append(chunk)

        raw = b"".join(chunks)
        encoding = resp.encoding or "utf-8"
        return raw.decode(encoding, errors="replace")

    # ------------------------------------------------------------------ #
    # Step 2: extract main content
    # ------------------------------------------------------------------ #
    def extract(
        self, html: str, *, base_url: str, include_links: bool = True
    ) -> ExtractedContent:
        soup = BeautifulSoup(html, "lxml")

        title = self._extract_title(soup)
        description = self._extract_meta(soup, "description")
        canonical = self._extract_canonical(soup)

        # Remove obviously non-content subtrees up front.
        for tag in soup(list(_STRIP_TAGS)):
            tag.decompose()
        # Drop HTML comments.
        for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
            comment.extract()

        # Strip elements whose class/id scream "boilerplate".
        self._drop_noise(soup)

        main = self._find_main(soup)
        if main is None:
            raise EmptyContentError("Could not locate any main content in the page.")

        markdown = self.to_markdown(main, include_links=include_links)
        markdown = self._tidy_markdown(markdown)

        # Fallback: if our chosen container yielded nothing, try the whole body
        # before giving up — better a noisy result than no result.
        if not markdown.strip() and main is not (soup.body or soup):
            markdown = self._tidy_markdown(
                self.to_markdown(soup.body or soup, include_links=include_links)
            )

        if not markdown.strip():
            raise EmptyContentError(
                "Main content was empty after cleaning. The page likely renders "
                "its content with JavaScript (client-side), which this scraper "
                "cannot execute — try a server-rendered page/URL."
            )

        return ExtractedContent(
            title=title,
            description=description,
            canonical_url=canonical,
            markdown=markdown,
        )

    def _find_main(self, soup: BeautifulSoup) -> Tag | None:
        for selector in _MAIN_SELECTORS:
            node = soup.select_one(selector)
            if node and self._text_length(node) >= 200:
                return node

        # Fallback heuristic: the <div>/<section> with the most text.
        candidates = soup.find_all(["div", "section"])
        best = max(candidates, key=self._text_length, default=None)
        if best and self._text_length(best) >= 200:
            return best

        # Last resort: the body itself (or the whole doc).
        return soup.body or soup

    def _drop_noise(self, soup: BeautifulSoup) -> None:
        for tag in soup.find_all(True):
            # Decomposing a container also decomposes its descendants, whose
            # `.attrs` then become None while they're still in this list —
            # skip those to avoid crashing on the leftover references.
            if tag.attrs is None:
                continue
            classes = tag.get("class") or []
            if isinstance(classes, str):  # some parsers return a string
                classes = classes.split()
            identifier = " ".join([*classes, tag.get("id") or ""]).strip()
            if not identifier or not _NOISE_PATTERN.search(identifier):
                continue
            # Don't nuke a large content block just because its class happens
            # to match a noise token — real boilerplate (nav/footer/ads) is short.
            if self._text_length(tag) <= 200:
                tag.decompose()

    @staticmethod
    def _text_length(tag: Tag) -> int:
        return len(tag.get_text(" ", strip=True))

    # ------------------------------------------------------------------ #
    # Step 3: HTML -> Markdown
    # ------------------------------------------------------------------ #
    def to_markdown(self, node: Tag, *, include_links: bool = True) -> str:
        strip = [] if include_links else ["a"]
        return md(
            str(node),
            heading_style="ATX",
            bullets="-",
            strip=strip,
            escape_asterisks=False,
            escape_underscores=False,
        )

    @staticmethod
    def _tidy_markdown(text: str) -> str:
        # Collapse 3+ blank lines into one blank line.
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Trim trailing whitespace on each line.
        text = "\n".join(line.rstrip() for line in text.splitlines())
        return text.strip()

    # ------------------------------------------------------------------ #
    # Metadata helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> str | None:
        if soup.title and soup.title.string:
            return soup.title.string.strip()
        h1 = soup.find("h1")
        return h1.get_text(strip=True) if h1 else None

    @staticmethod
    def _extract_meta(soup: BeautifulSoup, name: str) -> str | None:
        tag = soup.find("meta", attrs={"name": name}) or soup.find(
            "meta", attrs={"property": f"og:{name}"}
        )
        if tag and tag.get("content"):
            return tag["content"].strip()
        return None

    @staticmethod
    def _extract_canonical(soup: BeautifulSoup) -> str | None:
        tag = soup.find("link", attrs={"rel": "canonical"})
        return tag.get("href") if tag else None

    # ------------------------------------------------------------------ #
    # Validation & headers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise InvalidURLError(f"Unsupported or malformed URL: {url!r}")

    def _browser_headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.settings.user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0",
        }


def _looks_blocked(html: str) -> bool:
    """True if the HTML looks like a bot-challenge / CAPTCHA interstitial."""
    head = html[:5000].lower()
    return any(marker in head for marker in _BLOCK_MARKERS)


def _log_backoff(state: RetryCallState) -> None:
    """tenacity callback: log each backoff sleep."""
    exc = state.outcome.exception() if state.outcome else None
    wait = getattr(state.next_action, "sleep", 0.0)
    logger.warning(
        "Fetch attempt %d failed; backing off %.1fs (%s)",
        state.attempt_number,
        wait,
        exc,
    )
