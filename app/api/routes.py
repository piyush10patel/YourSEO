"""HTTP routes for the AI SEO Agent."""

from __future__ import annotations

import logging

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.config import Settings, get_settings
from app.schemas.audit import AuditRequest
from app.schemas.scrape import (
    ErrorResponse,
    HealthResponse,
    ScrapeMetadata,
    ScrapeRequest,
    ScrapeResponse,
)
from app.services.audit import AuditResult, run_audit_async, stream_summary_async
from app.services.scraper import ScraperService

logger = logging.getLogger(__name__)

router = APIRouter()

# Error responses shared by the scrape/audit endpoints.
_FETCH_ERRORS: dict = {
    400: {"model": ErrorResponse, "description": "Invalid URL"},
    403: {"model": ErrorResponse, "description": "Crawler blocked by target"},
    413: {"model": ErrorResponse, "description": "Response too large"},
    422: {"model": ErrorResponse, "description": "No extractable content"},
    429: {"model": ErrorResponse, "description": "Upstream rate limited"},
    502: {"model": ErrorResponse, "description": "Upstream fetch failed"},
    504: {"model": ErrorResponse, "description": "LLM timed out"},
}


def get_scraper(settings: Settings = Depends(get_settings)) -> ScraperService:
    """Provide a ScraperService per request."""
    return ScraperService(settings=settings)


@router.get(
    "/health",
    tags=["meta"],
    response_model=HealthResponse,
    summary="Liveness probe",
)
async def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(status="ok", service=settings.app_name, version="0.1.0")


@router.post(
    "/scrape",
    tags=["scrape"],
    response_model=ScrapeResponse,
    summary="Scrape a URL and return clean Markdown",
    responses=_FETCH_ERRORS,
)
async def scrape(
    payload: ScrapeRequest,
    scraper: ScraperService = Depends(get_scraper),
) -> ScrapeResponse:
    url = str(payload.url)
    logger.info("Scraping %s", url)

    # Domain errors raised here are translated to HTTP responses by the
    # exception handlers registered in app/main.py.
    page, content = await scraper.scrape(url, include_links=payload.include_links)

    word_count = len(content.markdown.split())
    return ScrapeResponse(
        url=page.final_url,
        status_code=page.status_code,
        metadata=ScrapeMetadata(
            title=content.title,
            description=content.description,
            canonical_url=content.canonical_url,
            word_count=word_count,
        ),
        markdown=content.markdown,
    )


@router.post(
    "/audit",
    tags=["audit"],
    response_model=AuditResult,
    summary="Run a full SEO audit (scrape + analyze + LLM report)",
    responses=_FETCH_ERRORS,
)
async def audit(
    payload: AuditRequest,
    settings: Settings = Depends(get_settings),
) -> AuditResult:
    url = str(payload.url)
    logger.info(
        "Auditing %s (render_js=%s, cache=%s)",
        url,
        payload.render_js,
        payload.use_cache,
    )
    render_js: bool | str = "auto" if payload.render_js else False
    return await run_audit_async(
        url,
        settings,
        render_js=render_js,
        use_cache=payload.use_cache,
    )


@router.post(
    "/audit/stream",
    tags=["audit"],
    summary="Run an audit and stream the executive summary via SSE",
    response_class=StreamingResponse,
    responses=_FETCH_ERRORS,
)
async def audit_stream(
    payload: AuditRequest,
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """Server-Sent Events stream.

    Emits one ``result`` event with the full structured `AuditResult`, then a
    series of ``token`` events carrying executive-summary text as the LLM
    generates it, and finally a ``done`` event.
    """
    url = str(payload.url)
    render_js: bool | str = "auto" if payload.render_js else False
    result = await run_audit_async(
        url, settings, render_js=render_js, use_cache=payload.use_cache
    )

    async def event_stream():
        # SSE frames: `event: <name>\ndata: <json>\n\n`.
        yield f"event: result\ndata: {result.model_dump_json()}\n\n"
        try:
            async for token in stream_summary_async(result, settings):
                yield f"event: token\ndata: {json.dumps(token)}\n\n"
        except Exception as exc:  # surface streaming errors as an SSE event
            logger.warning("Summary stream failed: %s", exc)
            yield f"event: error\ndata: {json.dumps(str(exc))}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
