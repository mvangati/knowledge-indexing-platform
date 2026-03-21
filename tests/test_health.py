"""Tests for /api/v1/health and /api/v1/metrics endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_health_returns_200(client: AsyncClient):
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200


async def test_health_body_structure(client: AsyncClient):
    data = (await client.get("/api/v1/health")).json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"
    assert "uptime_seconds" in data
    assert data["version"] == "1.0.0"


async def test_health_uptime_is_positive(client: AsyncClient):
    data = (await client.get("/api/v1/health")).json()
    assert data["uptime_seconds"] >= 0


async def test_metrics_returns_200(client: AsyncClient):
    resp = await client.get("/api/v1/metrics")
    assert resp.status_code == 200


async def test_metrics_body_structure(client: AsyncClient):
    data = (await client.get("/api/v1/metrics")).json()
    assert "uptime_seconds" in data
    assert "tenants" in data
    assert isinstance(data["tenants"], dict)


async def test_metrics_no_auth_required(client: AsyncClient):
    """Health and metrics must be publicly accessible for load balancers."""
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    resp2 = await client.get("/api/v1/metrics")
    assert resp2.status_code == 200
