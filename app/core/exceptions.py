"""Domain-specific exceptions for the service layer.

Keeping these separate from HTTP concerns lets the service layer raise
meaningful errors without knowing anything about FastAPI. The API layer
(see `app/main.py`) maps them to HTTP responses via the shared `AppError`
base — every subclass carries the HTTP status and a stable machine-readable
code it should surface.
"""

from __future__ import annotations


class AppError(Exception):
    """Base class for all classified, expected service-layer failures."""

    # Default HTTP status the API layer should surface for this error.
    status_code: int = 500
    # Stable machine-readable code returned in the JSON body.
    error_code: str = "internal_error"

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class NotFoundError(AppError):
    """A requested resource does not exist (or isn't visible to this tenant)."""

    status_code = 404
    error_code = "not_found"


class BadRequestError(AppError):
    """The request was understood but is invalid (e.g. bad enum value)."""

    status_code = 422
    error_code = "bad_request"


class ForbiddenError(AppError):
    """The caller's role lacks permission for this action (RBAC)."""

    status_code = 403
    error_code = "forbidden"


# --------------------------------------------------------------------------- #
# Scraper errors
# --------------------------------------------------------------------------- #
class ScraperError(AppError):
    """Base class for all scraper failures."""

    status_code = 502
    error_code = "scraper_error"


class InvalidURLError(ScraperError):
    """The supplied URL is malformed or uses an unsupported scheme."""

    status_code = 400
    error_code = "invalid_url"


class FetchError(ScraperError):
    """The target could not be fetched (DNS, connection, timeout, TLS...)."""

    status_code = 502
    error_code = "fetch_failed"


class RateLimitedError(FetchError):
    """The target returned 429/503 repeatedly and exhausted our retries."""

    status_code = 429
    error_code = "rate_limited"


class CrawlerBlockedError(FetchError):
    """The target blocked the crawler (403, CAPTCHA, or bot-challenge page)."""

    status_code = 403
    error_code = "crawler_blocked"


class HTTPStatusError(FetchError):
    """The target returned a non-success HTTP status we won't retry."""

    status_code = 502
    error_code = "upstream_http_error"

    def __init__(
        self, message: str, *, upstream_status: int, detail: str | None = None
    ) -> None:
        super().__init__(message, detail=detail)
        self.upstream_status = upstream_status


class ContentTooLargeError(ScraperError):
    """The response body exceeded the configured size limit."""

    status_code = 413
    error_code = "content_too_large"


class EmptyContentError(ScraperError):
    """Fetched successfully but no meaningful content could be extracted."""

    status_code = 422
    error_code = "empty_content"


# --------------------------------------------------------------------------- #
# LLM / Ollama errors
# --------------------------------------------------------------------------- #
class LLMError(AppError):
    """Base class for all LLM integration failures."""

    status_code = 502
    error_code = "llm_error"


class LLMTimeoutError(LLMError):
    """The model did not respond within the configured timeout."""

    status_code = 504
    error_code = "llm_timeout"


class LLMConnectionError(LLMError):
    """Could not reach the Ollama server (is it running?)."""

    status_code = 503
    error_code = "llm_unavailable"


class LLMResponseError(LLMError):
    """Ollama responded, but the payload could not be parsed/validated."""

    status_code = 502
    error_code = "llm_bad_response"


# --------------------------------------------------------------------------- #
# Agent errors
# --------------------------------------------------------------------------- #
class AgentError(AppError):
    """Base class for orchestration failures."""

    status_code = 500
    error_code = "agent_error"


class MaxStepsExceededError(AgentError):
    """The ReAct loop ran out of steps before producing a final report."""

    status_code = 504
    error_code = "agent_max_steps_exceeded"
