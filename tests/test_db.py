"""Persistence tests: tenant scoping, repositories, and audit persistence.

Runs on in-memory SQLite — no Postgres required.
"""

from __future__ import annotations

import uuid

from app.db import repositories as repo
from app.services.audit import demo_result
from app.services.persistence import persist_audit


async def test_default_org_is_idempotent(db_session) -> None:
    org1 = await repo.get_or_create_default_org(db_session)
    org2 = await repo.get_or_create_default_org(db_session)
    assert org1.id == org2.id


async def test_projects_are_tenant_scoped(db_session) -> None:
    org_a = await repo.create_organization(db_session, name="A")
    org_b = await repo.create_organization(db_session, name="B")
    proj_a = await repo.create_project(db_session, organization_id=org_a.id, name="PA")

    # Org B cannot see Org A's project.
    assert (
        await repo.get_project(
            db_session, project_id=proj_a.id, organization_id=org_b.id
        )
        is None
    )
    # Org A can.
    assert (
        await repo.get_project(
            db_session, project_id=proj_a.id, organization_id=org_a.id
        )
        is not None
    )
    assert await repo.list_projects(db_session, organization_id=org_b.id) == []


async def test_persist_audit_writes_page_audit_and_recommendations(db_session) -> None:
    org = await repo.create_organization(db_session, name="Acme")
    project = await repo.create_project(
        db_session, organization_id=org.id, name="Site", domain="example.com"
    )
    result = demo_result("https://example.com")

    audit = await persist_audit(
        db_session, organization_id=org.id, project_id=project.id, result=result
    )
    assert audit.overall_score == result.overall_score

    recs = await repo.list_recommendations(
        db_session, project_id=project.id, organization_id=org.id
    )
    # demo has keyword gaps + technical fixes + a meta-description recommendation
    assert len(recs) == (len(result.keyword_gaps) + len(result.technical_fixes) + 1)
    # Sorted by priority desc, and priority computed from impact*conf/effort.
    assert recs[0].priority >= recs[-1].priority
    assert {r.type for r in recs} <= {
        "keyword_gap",
        "technical_fix",
        "meta_description",
    }

    audits = await repo.list_audits(
        db_session, project_id=project.id, organization_id=org.id
    )
    assert len(audits) == 1


async def test_persist_audit_rejects_foreign_project(db_session) -> None:
    org = await repo.create_organization(db_session, name="Acme")
    other = await repo.create_organization(db_session, name="Other")
    project = await repo.create_project(db_session, organization_id=other.id, name="X")
    result = demo_result("https://example.com")

    import pytest

    from app.core.exceptions import NotFoundError

    with pytest.raises(NotFoundError):
        await persist_audit(
            db_session, organization_id=org.id, project_id=project.id, result=result
        )


async def test_get_project_unknown_id(db_session) -> None:
    org = await repo.create_organization(db_session, name="Acme")
    assert (
        await repo.get_project(
            db_session, project_id=uuid.uuid4(), organization_id=org.id
        )
        is None
    )
