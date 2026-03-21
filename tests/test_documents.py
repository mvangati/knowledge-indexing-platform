"""Tests for document ingestion and retrieval endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import ACME_HEADERS, GLOBEX_HEADERS, ingest

pytestmark = pytest.mark.asyncio


# ── Ingestion ─────────────────────────────────────────────────────────────────

async def test_ingest_returns_201(client: AsyncClient):
    resp = await ingest(client, "acme", ACME_HEADERS)
    assert resp.status_code == 201


async def test_ingest_response_schema(client: AsyncClient):
    data = (await ingest(client, "acme", ACME_HEADERS, title="My Doc")).json()
    assert "document_id" in data
    assert data["document_id"].startswith("doc_")
    assert data["tenant_id"] == "acme"
    assert data["title"] == "My Doc"
    assert "created_at" in data


async def test_ingest_assigns_unique_ids(client: AsyncClient):
    id1 = (await ingest(client, "acme", ACME_HEADERS)).json()["document_id"]
    id2 = (await ingest(client, "acme", ACME_HEADERS)).json()["document_id"]
    assert id1 != id2


async def test_ingest_empty_title_returns_422(client: AsyncClient):
    resp = await client.post(
        "/api/v1/tenants/acme/documents",
        json={"title": "", "content": "Some content"},
        headers=ACME_HEADERS,
    )
    assert resp.status_code == 422


async def test_ingest_missing_content_returns_422(client: AsyncClient):
    resp = await client.post(
        "/api/v1/tenants/acme/documents",
        json={"title": "Only title"},
        headers=ACME_HEADERS,
    )
    assert resp.status_code == 422


async def test_ingest_with_tags(client: AsyncClient):
    resp = await ingest(
        client, "acme", ACME_HEADERS,
        title="Tagged Doc",
        content="Content here",
        tags=["finance", "Q4", "ANNUAL"],
    )
    assert resp.status_code == 201


async def test_ingest_content_size_limit(client: AsyncClient):
    """Content larger than MAX_DOCUMENT_SIZE_KB should be rejected."""
    import os
    os.environ["MAX_DOCUMENT_SIZE_KB"] = "1"  # 1 KB limit for this test
    from src.config import get_settings
    get_settings.cache_clear()

    big_content = "x" * (2 * 1024)  # 2 KB
    resp = await client.post(
        "/api/v1/tenants/acme/documents",
        json={"title": "Big", "content": big_content},
        headers=ACME_HEADERS,
    )
    assert resp.status_code == 413

    # Restore
    os.environ["MAX_DOCUMENT_SIZE_KB"] = "5120"
    get_settings.cache_clear()


# ── Retrieval ─────────────────────────────────────────────────────────────────

async def test_get_document_by_id(client: AsyncClient):
    doc_id = (await ingest(client, "acme", ACME_HEADERS, title="Retrieve Me")).json()[
        "document_id"
    ]
    resp = await client.get(
        f"/api/v1/tenants/acme/documents/{doc_id}", headers=ACME_HEADERS
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["document_id"] == doc_id
    assert data["title"] == "Retrieve Me"
    assert "content" in data
    assert "tags" in data


async def test_get_nonexistent_document_returns_404(client: AsyncClient):
    resp = await client.get(
        "/api/v1/tenants/acme/documents/doc_DOESNOTEXIST",
        headers=ACME_HEADERS,
    )
    assert resp.status_code == 404


async def test_cross_tenant_get_returns_404(client: AsyncClient):
    """A document ingested by acme must not be visible to globex."""
    doc_id = (await ingest(client, "acme", ACME_HEADERS)).json()["document_id"]
    resp = await client.get(
        f"/api/v1/tenants/globex/documents/{doc_id}",
        headers=GLOBEX_HEADERS,
    )
    assert resp.status_code == 404


# ── Deletion ──────────────────────────────────────────────────────────────────

async def test_delete_document_returns_204(client: AsyncClient):
    doc_id = (await ingest(client, "acme", ACME_HEADERS)).json()["document_id"]
    resp = await client.delete(
        f"/api/v1/tenants/acme/documents/{doc_id}",
        headers=ACME_HEADERS,
    )
    assert resp.status_code == 204


async def test_deleted_document_not_retrievable(client: AsyncClient):
    doc_id = (await ingest(client, "acme", ACME_HEADERS)).json()["document_id"]
    await client.delete(
        f"/api/v1/tenants/acme/documents/{doc_id}", headers=ACME_HEADERS
    )
    resp = await client.get(
        f"/api/v1/tenants/acme/documents/{doc_id}", headers=ACME_HEADERS
    )
    assert resp.status_code == 404


async def test_delete_nonexistent_document_returns_404(client: AsyncClient):
    resp = await client.delete(
        "/api/v1/tenants/acme/documents/doc_GONE",
        headers=ACME_HEADERS,
    )
    assert resp.status_code == 404


async def test_cross_tenant_delete_returns_404(client: AsyncClient):
    """globex must not be able to delete acme documents."""
    doc_id = (await ingest(client, "acme", ACME_HEADERS)).json()["document_id"]
    resp = await client.delete(
        f"/api/v1/tenants/globex/documents/{doc_id}",
        headers=GLOBEX_HEADERS,
    )
    assert resp.status_code == 404
    # Verify acme doc still exists
    get_resp = await client.get(
        f"/api/v1/tenants/acme/documents/{doc_id}", headers=ACME_HEADERS
    )
    assert get_resp.status_code == 200
