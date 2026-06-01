"""Headless-browser rendering for JavaScript-heavy pages.

Many modern sites (React/Vue/Next SPAs) ship an almost-empty HTML shell and
paint everything client-side, so the `httpx`-based scraper sees no content.
This module loads such a page in a headless Chromium (via Playwright), lets the
JavaScript run, and returns the fully-rendered HTML for the normal extractor.

Playwright is run in a **dedicated subprocess** (`app.services.render_cli`).
That isolation is deliberate: launching a headless browser from within a web
server's worker thread (Streamlit's ScriptRunner, FastAPI's threadpool, nested
``asyncio.run`` + ``to_thread``) is riddled with event-loop pitfalls that differ
across Windows and Linux. A fresh process has a clean main thread and the
default loop, so it works the same everywhere.

Playwright is an optional dependency: if it isn't importable, `is_available()`
returns False and the scraper simply skips the fallback.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Project root (parent of the `app` package) so the subprocess can resolve
# `python -m app.services.render_cli` regardless of the caller's CWD.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[2])


@dataclass
class RenderedPage:
    final_url: str
    status_code: int
    html: str


def is_available() -> bool:
    """True if the Playwright package is importable (browser checked at run time)."""
    try:
        import playwright  # noqa: F401

        return True
    except Exception:
        return False


def render(
    url: str,
    *,
    user_agent: str,
    timeout: float = 30.0,
    locale: str = "en-US",  # kept for API compatibility; CLI defaults to en-US
) -> RenderedPage:
    """Load `url` in headless Chromium (in a subprocess) and return the HTML.

    Raises `FetchError` on navigation/timeout/launch failures.
    """
    from app.core.exceptions import FetchError

    timeout_ms = int(timeout * 1000)
    cmd = [
        sys.executable,
        "-m",
        "app.services.render_cli",
        url,
        str(timeout_ms),
        user_agent,
    ]

    try:
        proc = subprocess.run(
            cmd,
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout + 30,  # grace for browser launch/teardown
        )
    except subprocess.TimeoutExpired as exc:
        raise FetchError(
            f"Headless render of {url} timed out after {timeout:.0f}s.",
            detail=str(exc),
        ) from exc

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-500:]
        # A missing browser binary shows up here as a Playwright launch error.
        raise FetchError(f"Headless render of {url} failed.", detail=detail)

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise FetchError(
            f"Headless render of {url} produced no parseable output.",
            detail=(proc.stdout or "")[:300],
        ) from exc

    return RenderedPage(
        final_url=data["final_url"],
        status_code=data["status"],
        html=data["html"],
    )
