"""Agent registry: discover and fetch agents by name."""

from __future__ import annotations

from app.agents.base import Agent
from app.agents.workers import (
    AuditAgent,
    AuthorityAgent,
    ContentAgent,
    InternalLinkingAgent,
    KeywordAgent,
    OptimizationAgent,
)
from app.core.exceptions import NotFoundError

# The narrow "worker" specialists the Planner orchestrates.
_WORKER_CLASSES: dict[str, type[Agent]] = {
    cls.name: cls
    for cls in [
        AuditAgent,
        KeywordAgent,
        InternalLinkingAgent,
        OptimizationAgent,
        ContentAgent,
        AuthorityAgent,
    ]
}


def worker_classes() -> dict[str, type[Agent]]:
    return dict(_WORKER_CLASSES)


def _all_instances() -> list[Agent]:
    from app.agents.evaluator import EvaluatorAgent
    from app.agents.planner import PlannerAgent

    return [cls() for cls in _WORKER_CLASSES.values()] + [
        PlannerAgent(),
        EvaluatorAgent(),
    ]


def list_agents() -> list[dict[str, str]]:
    return [{"name": a.name, "description": a.description} for a in _all_instances()]


def get_agent(name: str) -> Agent:
    for agent in _all_instances():
        if agent.name == name:
            return agent
    raise NotFoundError(f"Unknown agent {name!r}.")
