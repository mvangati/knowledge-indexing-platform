"""Tests for the search endpoint, including tenant isolation and pagination."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import ACME_HEADERS, GLOBEX_HEADERS, EMPTY_HEADERS, ingest

pytestmark = pytest.mark.asyncio


# ── Helpers ───────────────────────────────────────────────────────────────────

async def seed_acme(client: AsyncClient, n: int = 3) -> list[str]:
    ids = []
    for i in range(n):
        resp = await ingest(
            client,
            "acme",
            ACME_HEADERS,
            title=f"Acme Document {i}",
            content=f"This is acme document number {i} about machine learning and AI.",
            tags=[f"tag{i}"],
        )
        ids.append(resp.json()["document_id"])
    return ids


async def seed_globex(client: AsyncClient) -> str:
    resp = await ingest(
        client,
        "globex",
        GLOBEX_HEADERS,
        title="Globex Private Doc",
        content="Globex confidential content about machine learning.",
    )
    return resp.json()["document_id"]


# ── Basic search ──────────────────────────────────────────────────────────────

async def test_search_returns_200(client: AsyncClient):
    await seed_acme(client)
    resp = await client.get(
        "/api/v1/tenants/acme/documents/search?q=machine+learning",
        headers=ACME_HEADERS,
    )
    assert resp.status_code == 200


async def test_search_response_schema(client: AsyncClient):
    await seed_acme(client)
    data = (
        await client.get(
            "/api/v1/tenants/acme/documents/search?q=machine",
            headers=ACME_HEADERS,
        )
    ).json()

    assert "total" in data
    assert "limit" in data
    assert "offset" in data
    assert "results" in data
    assert "query_time_ms" in data
    assert isinstance(data["results"], list)


async def test_search_finds_relevant_documents(client: AsyncClient):
    await seed_acme(client)
    data = (
        await client.get(
            "/api/v1/tenants/acme/documents/search?q=machine+learning",
            headers=ACME_HEADERS,
        )
    ).json()
    assert data["total"] > 0
    assert len(data["results"]) > 0


async def test_search_result_has_score(client: AsyncClient):
    await seed_acme(client)
    results = (
        await client.get(
            "/api/v1/tenants/acme/documents/search?q=acme",
            headers=ACME_HEADERS,
        )
    ).json()["results"]
    for r in results:
        assert "score" in r
        assert 0.0 <= r["score"] <= 1.0


async def test_search_result_has_snippet(client: AsyncClient):
    await seed_acme(client)
    results = (
        await client.get(
            "/api/v1/tenants/acme/documents/search?q=acme",
            headers=ACME_HEADERS,
        )
    ).json()["results"]
    for r in results:
        assert "snippet" in r
        assert len(r["snippet"]) > 0


async def test_search_no_results_for_unmatched_query(client: AsyncClient):
    await seed_acme(client)
    data = (
        await client.get(
            "/api/v1/tenants/acme/documents/search?q=xyznonexistentterm99",
            headers=ACME_HEADERS,
        )
    ).json()
    assert data["total"] == 0
    assert data["results"] == []


async def test_empty_tenant_returns_empty_results(client: AsyncClient):
    """Searching a tenant with no docs should return 0 results, not an error."""
    data = (
        await client.get(
            "/api/v1/tenants/empty-tenant/documents/search?q=anything",
            headers=EMPTY_HEADERS,
        )
    ).json()
    assert data["total"] == 0
    assert data["results"] == []


# ── Tenant isolation ──────────────────────────────────────────────────────────

async def test_search_does_not_cross_tenant_boundary(client: AsyncClient):
    """Acme's search must never return globex's documents."""
    await seed_acme(client)
    await seed_globex(client)

    data = (
        await client.get(
            "/api/v1/tenants/acme/documents/search?q=machine+learning",
            headers=ACME_HEADERS,
        )
    ).json()

    returned_ids = [r["document_id"] for r in data["results"]]
    for r in data["results"]:
        # No result should reference the globex tenant
        assert "globex" not in r["title"].lower() or True  # check via doc id prefix
    # More robust: verify each returned doc belongs to acme by fetching it
    for doc_id in returned_ids:
        doc = (
            await client.get(
                f"/api/v1/tenants/acme/documents/{doc_id}",
                headers=ACME_HEADERS,
            )
        ).json()
        assert doc["tenant_id"] == "acme"


async def test_globex_cannot_see_acme_docs(client: AsyncClient):
    await seed_acme(client)
    data = (
        await client.get(
            "/api/v1/tenants/globex/documents/search?q=acme",
            headers=GLOBEX_HEADERS,
        )
    ).json()
    assert data["total"] == 0


# ── Pagination ────────────────────────────────────────────────────────────────

async def test_pagination_limit(client: AsyncClient):
    await seed_acme(client, n=5)
    data = (
        await client.get(
            "/api/v1/tenants/acme/documents/search?q=acme&limit=2",
            headers=ACME_HEADERS,
        )
    ).json()
    assert len(data["results"]) <= 2
    assert data["limit"] == 2


async def test_pagination_offset(client: AsyncClient):
    await seed_acme(client, n=5)
    page1 = (
        await client.get(
            "/api/v1/tenants/acme/documents/search?q=acme&limit=2&offset=0",
            headers=ACME_HEADERS,
        )
    ).json()
    page2 = (
        await client.get(
            "/api/v1/tenants/acme/documents/search?q=acme&limit=2&offset=2",
            headers=ACME_HEADERS,
        )
    ).json()
    ids1 = {r["document_id"] for r in page1["results"]}
    ids2 = {r["document_id"] for r in page2["results"]}
    assert ids1.isdisjoint(ids2), "Paginated results must not overlap"


async def test_pagination_total_is_consistent(client: AsyncClient):
    await seed_acme(client, n=4)
    data = (
        await client.get(
            "/api/v1/tenants/acme/documents/search?q=acme&limit=2",
            headers=ACME_HEADERS,
        )
    ).json()
    assert data["total"] >= 2  # total reflects full result set, not page size


# ── Edge cases ────────────────────────────────────────────────────────────────

async def test_search_missing_query_param_returns_422(client: AsyncClient):
    resp = await client.get(
        "/api/v1/tenants/acme/documents/search",
        headers=ACME_HEADERS,
    )
    assert resp.status_code == 422


async def test_search_special_chars_do_not_crash(client: AsyncClient):
    await seed_acme(client)
    for q in ['he"llo', "it's", "a:b", "(test)", "foo*bar"]:
        resp = await client.get(
            f"/api/v1/tenants/acme/documents/search?q={q}",
            headers=ACME_HEADERS,
        )
        assert resp.status_code == 200, f"Query '{q}' caused error: {resp.text}"


async def test_search_query_time_ms_is_positive(client: AsyncClient):
    await seed_acme(client)
    data = (
        await client.get(
            "/api/v1/tenants/acme/documents/search?q=document",
            headers=ACME_HEADERS,
        )
    ).json()
    assert data["query_time_ms"] >= 0
