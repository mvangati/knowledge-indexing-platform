"""Tests for the authentication and tenant-isolation middleware."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import ACME_HEADERS, GLOBEX_HEADERS, INVALID_HEADERS

pytestmark = pytest.mark.asyncio


async def test_missing_api_key_returns_401(client: AsyncClient):
    resp = await client.post(
        "/api/v1/tenants/acme/documents",
        json={"title": "T", "content": "C"},
    )
    assert resp.status_code == 401
    assert "Missing API key" in resp.json()["error"]


async def test_invalid_api_key_returns_401(client: AsyncClient):
    resp = await client.post(
        "/api/v1/tenants/acme/documents",
        json={"title": "T", "content": "C"},
        headers=INVALID_HEADERS,
    )
    assert resp.status_code == 401
    assert "Invalid API key" in resp.json()["error"]


async def test_wrong_tenant_key_returns_403(client: AsyncClient):
    """globex key must not access acme tenant endpoints."""
    resp = await client.post(
        "/api/v1/tenants/acme/documents",
        json={"title": "T", "content": "C"},
        headers=GLOBEX_HEADERS,  # key is valid but for a different tenant
    )
    assert resp.status_code == 403
    assert "Forbidden" in resp.json()["error"]


async def test_correct_key_is_accepted(client: AsyncClient):
    resp = await client.post(
        "/api/v1/tenants/acme/documents",
        json={"title": "T", "content": "C"},
        headers=ACME_HEADERS,
    )
    assert resp.status_code == 201


async def test_request_id_header_present(client: AsyncClient):
    """Every authenticated response should carry X-Request-ID."""
    resp = await client.post(
        "/api/v1/tenants/acme/documents",
        json={"title": "T", "content": "C"},
        headers=ACME_HEADERS,
    )
    assert "x-request-id" in resp.headers


async def test_health_requires_no_auth(client: AsyncClient):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200


async def test_search_endpoint_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/tenants/acme/documents/search?q=test")
    assert resp.status_code == 401
