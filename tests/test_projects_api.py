"""Project API tests via httpx ASGITransport (single event loop, SQLite).

We use httpx.AsyncClient + ASGITransport (not the sync TestClient) so the
request handlers share the test's event loop with the in-memory async DB.
The DB session dependency is overridden to the test's SQLite sessionmaker.
"""

from __future__ import annotations

import httpx
import pytest_asyncio

from app.db.base import get_session
from app.main import app


@pytest_asyncio.fixture
async def client(db_sessionmaker):
    async def override_get_session():
        async with db_sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_session] = override_get_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_create_and_list_projects(client) -> None:
    resp = await client.post(
        "/api/v1/projects", json={"name": "My Site", "domain": "example.com"}
    )
    assert resp.status_code == 200, resp.text
    project = resp.json()
    assert project["name"] == "My Site"
    assert project["organization_id"]  # default org auto-created

    listed = await client.get("/api/v1/projects")
    assert listed.status_code == 200
    assert len(listed.json()) == 1


async def test_audits_and_recommendations_start_empty(client) -> None:
    pid = (await client.post("/api/v1/projects", json={"name": "S"})).json()["id"]
    assert (await client.get(f"/api/v1/projects/{pid}/audits")).json() == []
    assert (await client.get(f"/api/v1/projects/{pid}/recommendations")).json() == []


async def test_unknown_project_returns_404(client) -> None:
    import uuid

    resp = await client.get(f"/api/v1/projects/{uuid.uuid4()}/recommendations")
    assert resp.status_code == 404
    assert resp.json()["error_code"] == "not_found"


async def test_invalid_org_header_rejected(client) -> None:
    resp = await client.get(
        "/api/v1/projects", headers={"X-Organization-Id": "not-a-uuid"}
    )
    assert resp.status_code == 404


async def test_keywords_cluster_and_graph_flow(client) -> None:
    pid = (await client.post("/api/v1/projects", json={"name": "KW"})).json()["id"]

    # Add keywords (dedupes).
    added = await client.post(
        f"/api/v1/projects/{pid}/keywords",
        json={"keywords": ["seo audit tool", "seo audit guide", "link building"]},
    )
    assert added.status_code == 200
    assert len(added.json()) == 3

    # Cluster them.
    clusters = await client.post(f"/api/v1/projects/{pid}/cluster")
    assert clusters.status_code == 200
    assert len(clusters.json()) >= 1

    # Build + read the knowledge graph.
    built = await client.post(f"/api/v1/projects/{pid}/graph/build")
    assert built.status_code == 200 and built.json()["edges"] >= 1

    graph = await client.get(f"/api/v1/projects/{pid}/graph")
    assert graph.status_code == 200
    body = graph.json()
    assert body["nodes"] and body["edges"]


async def test_patch_unknown_recommendation_404(client) -> None:
    import uuid

    resp = await client.patch(
        f"/api/v1/recommendations/{uuid.uuid4()}", json={"status": "done"}
    )
    assert resp.status_code == 404
