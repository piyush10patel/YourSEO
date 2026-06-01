"""Request/response models for the scrape API."""

from __future__ import annotations

from pydantic import AnyHttpUrl, BaseModel, Field


class ScrapeRequest(BaseModel):
    url: AnyHttpUrl = Field(
        ...,
        description="Absolute http(s) URL of the page to scrape.",
        examples=["https://example.com/blog/post"],
    )
    include_links: bool = Field(
        default=True,
        description="Keep hyperlinks in the Markdown output. Disable for plain prose.",
    )


class ScrapeMetadata(BaseModel):
    title: str | None = Field(default=None, description="Page <title> or best heading.")
    description: str | None = Field(
        default=None, description="Meta description, if present."
    )
    canonical_url: str | None = Field(
        default=None, description="rel=canonical, if present."
    )
    word_count: int = Field(..., description="Word count of the extracted Markdown.")


class ScrapeResponse(BaseModel):
    url: str = Field(..., description="The final URL fetched (after redirects).")
    status_code: int = Field(..., description="HTTP status of the fetched page.")
    metadata: ScrapeMetadata
    markdown: str = Field(..., description="Clean Markdown of the main page content.")


class ErrorResponse(BaseModel):
    """Uniform error envelope returned for every failed request."""

    error_code: str = Field(..., examples=["fetch_failed"])
    message: str
    detail: str | None = None


class HealthResponse(BaseModel):
    """Liveness/readiness probe payload."""

    status: str = Field(..., examples=["ok"])
    service: str = Field(..., examples=["AI SEO Agent"])
    version: str = Field(..., examples=["0.1.0"])
