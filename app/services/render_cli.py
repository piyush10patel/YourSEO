"""Standalone headless-render worker, run as a subprocess by `renderer.render`.

Running Playwright in its *own* process sidesteps every asyncio
event-loop/thread pitfall that arises when a headless browser is launched from
within a web server's worker thread (Streamlit's ScriptRunner, FastAPI's
threadpool, nested ``asyncio.run`` + ``to_thread``, Windows vs Linux loop
policies, ...). A fresh process has a clean main thread and the default loop,
so Playwright's **sync** API "just works".

Usage (invoked internally):
    python -m app.services.render_cli <url> <timeout_ms> <user_agent>

On success: prints a JSON object {final_url, status, html} to stdout.
On failure: exits non-zero with a message on stderr.
"""

from __future__ import annotations

import json
import sys


def _render(url: str, timeout_ms: int, user_agent: str) -> dict:
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            user_agent=user_agent,
            locale="en-US",
            viewport={"width": 1366, "height": 900},
        )
        page = context.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
            except PWTimeout:
                pass  # never fully idle (polling/ads) — DOM content is enough
            status = response.status if response else 200
            final_url = page.url
            html = page.content()
        finally:
            context.close()
            browser.close()
    return {"final_url": final_url, "status": status, "html": html}


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write("usage: render_cli <url> [timeout_ms] [user_agent]\n")
        return 2
    url = sys.argv[1]
    timeout_ms = int(sys.argv[2]) if len(sys.argv) > 2 else 30000
    user_agent = sys.argv[3] if len(sys.argv) > 3 else "Mozilla/5.0"
    try:
        result = _render(url, timeout_ms, user_agent)
    except Exception as exc:  # surface to the parent via stderr + exit code
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return 1
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
