"""Billing (spec §27) — plan limits + Stripe, gated by configuration.

When `SEO_STRIPE_SECRET_KEY` is unset, billing is disabled: plans stay "free",
no limits are enforced, and the checkout/webhook endpoints report that billing
isn't configured. Set the key to activate Stripe Checkout + subscription sync.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.exceptions import BadRequestError, NotFoundError, PaymentRequiredError
from app.db import repositories as repo

# Plans and their project caps (None = unlimited).
_PLAN_PROJECT_LIMIT = {"free": None, "pro": None}


async def enforce_project_limit(
    session: AsyncSession,
    *,
    organization_id: uuid.UUID,
    settings: Settings | None = None,
) -> None:
    """Raise PaymentRequiredError if a free-plan org is at its project cap."""
    settings = settings or get_settings()
    if not settings.stripe_enabled:
        return  # billing disabled -> no limits
    org = await repo.get_organization(session, organization_id)
    if org is None:
        return
    limit = (
        settings.free_plan_max_projects
        if org.plan == "free"
        else _PLAN_PROJECT_LIMIT.get(org.plan)
    )
    if limit is None:
        return
    projects = await repo.list_projects(session, organization_id=organization_id)
    if len(projects) >= limit:
        raise PaymentRequiredError(
            f"The '{org.plan}' plan allows {limit} projects. Upgrade to add more."
        )


def create_checkout_session(
    *, organization_id: uuid.UUID, settings: Settings | None = None
) -> str:
    """Create a Stripe Checkout session and return its URL."""
    settings = settings or get_settings()
    if not settings.stripe_enabled:
        raise BadRequestError("Billing is not configured (no Stripe key).")
    if not settings.stripe_price_pro:
        raise BadRequestError("No Stripe price configured (SEO_STRIPE_PRICE_PRO).")

    import stripe

    stripe.api_key = settings.stripe_secret_key
    session = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": settings.stripe_price_pro, "quantity": 1}],
        success_url="http://localhost:3000/?billing=success",
        cancel_url="http://localhost:3000/?billing=cancel",
        client_reference_id=str(organization_id),
    )
    return session.url


async def handle_webhook(
    session: AsyncSession,
    *,
    payload: bytes,
    signature: str,
    settings: Settings | None = None,
) -> str:
    """Verify a Stripe webhook and sync the org's plan."""
    settings = settings or get_settings()
    if not settings.stripe_enabled:
        raise BadRequestError("Billing is not configured.")

    import stripe

    try:
        event = stripe.Webhook.construct_event(
            payload, signature, settings.stripe_webhook_secret
        )
    except Exception as exc:  # signature/parse failure
        raise BadRequestError("Invalid Stripe webhook signature.", detail=str(exc))

    if event["type"] == "checkout.session.completed":
        obj = event["data"]["object"]
        org_id = obj.get("client_reference_id")
        if org_id:
            org = await repo.get_organization(session, uuid.UUID(org_id))
            if org is None:
                raise NotFoundError("Organization not found for checkout.")
            org.plan = "pro"
            org.stripe_customer_id = obj.get("customer")
            await session.flush()
    return event["type"]
