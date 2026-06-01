"""Billing endpoints (Stripe). Disabled gracefully when no key is configured."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.auth import Role, get_current_org_id, require_role
from app.db import repositories as repo
from app.db.base import get_session
from app.services import billing

router = APIRouter(tags=["billing"])


@router.get("/billing/plan", summary="Current plan + billing status")
async def billing_plan(
    session: AsyncSession = Depends(get_session),
    org_id: uuid.UUID = Depends(get_current_org_id),
    settings: Settings = Depends(get_settings),
) -> dict:
    org = await repo.get_organization(session, org_id)
    return {
        "plan": org.plan if org else "free",
        "billing_enabled": settings.stripe_enabled,
        "free_plan_max_projects": settings.free_plan_max_projects,
    }


@router.post("/billing/checkout", summary="Create a Stripe Checkout session")
async def billing_checkout(
    org_id: uuid.UUID = Depends(get_current_org_id),
    settings: Settings = Depends(get_settings),
    _role: Role = Depends(require_role(Role.ADMIN)),
) -> dict:
    url = billing.create_checkout_session(organization_id=org_id, settings=settings)
    return {"checkout_url": url}


@router.post("/billing/webhook", summary="Stripe webhook (subscription sync)")
async def billing_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
    stripe_signature: str = Header(default=""),
) -> dict:
    payload = await request.body()
    event_type = await billing.handle_webhook(
        session, payload=payload, signature=stripe_signature, settings=settings
    )
    return {"received": True, "type": event_type}
