"""Agent contract + base class (spec §10).

Every agent returns the same `AgentResult` shape, which makes them composable:
the Planner can run any agent and the Evaluator can score any result without
knowing the agent's internals.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings


class AgentResult(BaseModel):
    """The uniform output of every agent (spec §10)."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    agent: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    impact: float = Field(..., ge=0.0, le=1.0)
    rationale: str
    evidence: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


@dataclass
class AgentContext:
    """Everything an agent needs to run against a project."""

    session: AsyncSession
    organization_id: uuid.UUID
    project_id: uuid.UUID
    settings: Settings
    # Optional inter-agent inputs (e.g. the Planner hands sub-results to the
    # Evaluator) and an optional LLM client for generative agents.
    inputs: dict[str, Any] = field(default_factory=dict)
    llm: Any = None


class Agent(ABC):
    """Base class: a named agent that produces an `AgentResult`."""

    name: str = "agent"
    description: str = ""

    @abstractmethod
    async def run(self, ctx: AgentContext) -> AgentResult:  # pragma: no cover
        ...

    def _result(
        self,
        *,
        confidence: float,
        impact: float,
        rationale: str,
        evidence: list[str] | None = None,
        recommendations: list[str] | None = None,
    ) -> AgentResult:
        return AgentResult(
            agent=self.name,
            confidence=round(confidence, 3),
            impact=round(impact, 3),
            rationale=rationale,
            evidence=evidence or [],
            recommendations=recommendations or [],
        )
