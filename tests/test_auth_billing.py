"""Clerk JWT verification + billing (plan limits / Stripe-disabled) tests."""

from __future__ import annotations

import time
import uuid

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.config import Settings
from app.core.auth import ClerkVerifier, Role, _map_clerk_role
from app.core.exceptions import BadRequestError, PaymentRequiredError, UnauthorizedError
from app.db import repositories as repo
from app.services import billing


def _rsa_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key, key.public_key()


def test_clerk_verifier_accepts_valid_token() -> None:
    priv, pub = _rsa_keypair()
    token = jwt.encode(
        {
            "sub": "user_1",
            "org_id": "org_42",
            "org_role": "admin",
            "exp": int(time.time()) + 300,
        },
        priv,
        algorithm="RS256",
    )
    claims = ClerkVerifier("https://x/jwks").verify(token, signing_key=pub)
    assert claims["sub"] == "user_1" and claims["org_id"] == "org_42"


def test_clerk_verifier_rejects_expired_token() -> None:
    priv, pub = _rsa_keypair()
    token = jwt.encode(
        {"sub": "u", "exp": int(time.time()) - 10}, priv, algorithm="RS256"
    )
    with pytest.raises(UnauthorizedError):
        ClerkVerifier("https://x/jwks").verify(token, signing_key=pub)


def test_map_clerk_role() -> None:
    assert _map_clerk_role("org:admin") is Role.ADMIN
    assert _map_clerk_role("basic_member") is Role.EDITOR
    assert _map_clerk_role(None) is Role.VIEWER


async def test_enforce_project_limit_noop_when_billing_disabled(db_session) -> None:
    org = await repo.create_organization(db_session, name="Free")
    for i in range(5):
        await repo.create_project(db_session, organization_id=org.id, name=f"p{i}")
    # Stripe disabled (default) -> no enforcement even past the cap.
    await billing.enforce_project_limit(
        db_session, organization_id=org.id, settings=Settings()
    )


async def test_enforce_project_limit_blocks_free_plan_when_billing_on(
    db_session,
) -> None:
    org = await repo.create_organization(db_session, name="Free")  # plan defaults free
    await repo.create_project(db_session, organization_id=org.id, name="p1")
    settings = Settings(stripe_secret_key="sk_test_x", free_plan_max_projects=1)
    with pytest.raises(PaymentRequiredError):
        await billing.enforce_project_limit(
            db_session, organization_id=org.id, settings=settings
        )


def test_checkout_requires_billing_configured() -> None:
    with pytest.raises(BadRequestError):
        billing.create_checkout_session(
            organization_id=uuid.uuid4(), settings=Settings()
        )
