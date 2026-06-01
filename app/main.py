"""FastAPI application entry point.

Wires together configuration, logging, routes, and — importantly — a set of
exception handlers that guarantee every failure leaves the app as a clean,
consistent JSON envelope (never a bare 500 with an HTML stack trace).

Run locally:
    uvicorn app.main:app --reload
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.agents import router as agents_router
from app.api.projects import router as projects_router
from app.api.routes import router
from app.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging
from app.core.metrics import metrics_middleware, metrics_response
from app.schemas.scrape import ErrorResponse

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(debug=settings.debug)
    logger.info("Starting %s (debug=%s)", settings.app_name, settings.debug)
    yield
    logger.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Scrapes a URL and returns clean Markdown for SEO analysis.",
        lifespan=lifespan,
    )

    # Observability: per-request metrics + Prometheus scrape endpoint.
    app.middleware("http")(metrics_middleware)

    async def metrics_endpoint() -> Response:
        return metrics_response()

    app.add_api_route("/metrics", metrics_endpoint, include_in_schema=False)

    app.include_router(router, prefix="/api/v1")
    app.include_router(projects_router, prefix="/api/v1")
    app.include_router(agents_router, prefix="/api/v1")
    _register_exception_handlers(app)
    return app


def _register_exception_handlers(app: FastAPI) -> None:
    """Map every error class to a uniform ErrorResponse JSON body."""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        # Expected, classified failures from the service layer (scraper, LLM, ...).
        level = logging.WARNING if exc.status_code < 500 else logging.ERROR
        logger.log(level, "%s on %s: %s", type(exc).__name__, request.url, exc.message)
        return _error(exc.status_code, exc.error_code, exc.message, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Bad/malformed request body or query params (Pydantic).
        return _error(
            422,
            "validation_error",
            "Request validation failed.",
            detail=str(exc.errors()),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        # 404s for unknown routes, etc.
        return _error(exc.status_code, "http_error", str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # Anything we did not anticipate — log the full traceback, but never
        # leak internals to the caller.
        logger.exception("Unhandled error on %s", request.url)
        return _error(
            500,
            "internal_error",
            "An unexpected error occurred.",
        )


def _error(
    status_code: int,
    error_code: str,
    message: str,
    detail: str | None = None,
) -> JSONResponse:
    body = ErrorResponse(error_code=error_code, message=message, detail=detail)
    return JSONResponse(status_code=status_code, content=body.model_dump())


app = create_app()
