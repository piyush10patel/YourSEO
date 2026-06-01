"""Agent endpoints: list agents, run one, or run the full plan."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentContext, AgentResult
from app.agents.registry import get_agent, list_agents
from app.api.projects import get_current_org_id
from app.config import Settings, get_settings
from app.core.exceptions import NotFoundError
from app.core.metrics import AGENT_RUNS
from app.core.rbac import Role, require_role
from app.db import repositories as repo
from app.db.base import get_session

router = APIRouter(tags=["agents"])


class AgentInfo(BaseModel):
    name: str
    description: str


async def _ctx(
    project_id: uuid.UUID,
    session: AsyncSession,
    org_id: uuid.UUID,
    settings: Settings,
) -> AgentContext:
    if not await repo.get_project(
        session, project_id=project_id, organization_id=org_id
    ):
        raise NotFoundError(f"Project {project_id} not found.")
    return AgentContext(
        session=session,
        organization_id=org_id,
        project_id=project_id,
        settings=settings,
    )


@router.get("/agents", response_model=list[AgentInfo], summary="List available agents")
async def get_agents() -> list[AgentInfo]:
    return [AgentInfo(**a) for a in list_agents()]


@router.post(
    "/projects/{project_id}/agents/{agent_name}/run",
    response_model=AgentResult,
    summary="Run a single agent for a project",
)
async def run_agent(
    project_id: uuid.UUID,
    agent_name: str,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
    settings: Settings = Depends(get_settings),
    _role: Role = Depends(require_role(Role.EDITOR)),
) -> AgentResult:
    ctx = await _ctx(project_id, session, org_id, settings)
    agent = get_agent(agent_name)
    AGENT_RUNS.labels(agent_name).inc()
    return await agent.run(ctx)


@router.post(
    "/projects/{project_id}/plan",
    response_model=AgentResult,
    summary="Run the Planner: orchestrate the agent team into a roadmap",
)
async def run_plan(
    project_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
    settings: Settings = Depends(get_settings),
    _role: Role = Depends(require_role(Role.EDITOR)),
) -> AgentResult:
    ctx = await _ctx(project_id, session, org_id, settings)
    AGENT_RUNS.labels("planner").inc()
    return await get_agent("planner").run(ctx)
