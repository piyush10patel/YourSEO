"""Request/response models for project, audit, and recommendation endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    name: str = Field(..., examples=["My Website"])
    domain: str | None = Field(default=None, examples=["example.com"])


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    domain: str | None
    created_at: datetime


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    page_id: uuid.UUID | None
    overall_score: int
    grade: str
    confidence: str
    created_at: datetime


class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    audit_id: uuid.UUID | None
    type: str
    title: str
    detail: str | None
    impact: float
    confidence: float
    effort: float
    priority: float
    status: str
    created_at: datetime


class ProjectAuditRequest(BaseModel):
    url: AnyHttpUrl
    render_js: bool = True
    use_cache: bool = True
