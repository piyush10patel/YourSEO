"""Request models for the audit endpoint.

The response model is `app.services.audit.AuditResult` (already a Pydantic
model), reused directly as the endpoint's `response_model`.
"""

from __future__ import annotations

from pydantic import AnyHttpUrl, BaseModel, Field


class AuditRequest(BaseModel):
    url: AnyHttpUrl = Field(
        ...,
        description="Absolute http(s) URL of the page to audit.",
        examples=["https://www.example.com"],
    )
    render_js: bool = Field(
        default=True,
        description="Render JavaScript with a headless browser when the page "
        "appears to be client-side rendered.",
    )
    use_cache: bool = Field(
        default=True,
        description="Return a cached audit (within the 24h TTL) when available.",
    )
