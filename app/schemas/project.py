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


class PageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    url: str
    title: str | None
    meta_description: str | None
    status_code: int | None
    word_count: int | None
    created_at: datetime


class CrawlRequest(BaseModel):
    seed_url: AnyHttpUrl = Field(..., examples=["https://example.com"])
    max_pages: int | None = Field(default=None, ge=1, le=500)
    max_depth: int | None = Field(default=None, ge=0, le=10)


class CrawlResponse(BaseModel):
    mode: str  # "inline" | "queued"
    audit: AuditOut | None = None
    task_id: str | None = None


class KeywordCreate(BaseModel):
    keywords: list[str] = Field(..., examples=[["seo audit", "technical seo"]])


class KeywordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    keyword: str
    volume: int | None
    difficulty: float | None
    intent: str | None
    cluster_id: uuid.UUID | None


class ClusterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    topic: str
    topic_id: uuid.UUID | None


class RecommendationStatusUpdate(BaseModel):
    status: str = Field(..., examples=["in_progress", "done", "dismissed"])


class GraphResponse(BaseModel):
    nodes: list[dict]
    edges: list[dict]


class ReportResponse(BaseModel):
    project: dict
    seo_score: int | None
    grade: str | None
    score_trend: list[int]
    pages: int
    keywords: int
    clusters: int
    recommendations_by_status: dict[str, int]
    issues_by_type: dict[str, int]
    kpis: dict
    generated_at: str
