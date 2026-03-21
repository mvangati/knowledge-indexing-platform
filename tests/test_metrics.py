"""Tests for metrics tracking."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import ACME_HEADERS, ingest

pytestmark = pytest.mark.asyncio


async def test_metrics_tracks_document_count(client: AsyncClient):
    await ingest(client, "acme", ACME_HEADERS)
    await ingest(client, "acme", ACME_HEADERS)

    metrics = (await client.get("/api/v1/metrics")).json()
    assert metrics["tenants"]["acme"]["document_count"] == 2


async def test_metrics_tracks_request_count(client: AsyncClient):
    # Make 3 requests
    for _ in range(3):
        await ingest(client, "acme", ACME_HEADERS)

    metrics = (await client.get("/api/v1/metrics")).json()
    assert metrics["tenants"]["acme"]["request_count"] >= 3


async def test_metrics_avg_response_time_nonnegative(client: AsyncClient):
    await ingest(client, "acme", ACME_HEADERS)
    metrics = (await client.get("/api/v1/metrics")).json()
    assert metrics["tenants"]["acme"]["avg_response_time_ms"] >= 0


async def test_metrics_uptime_is_positive(client: AsyncClient):
    metrics = (await client.get("/api/v1/metrics")).json()
    assert metrics["uptime_seconds"] >= 0


async def test_metrics_error_rate_between_0_and_1(client: AsyncClient):
    await ingest(client, "acme", ACME_HEADERS)
    metrics = (await client.get("/api/v1/metrics")).json()
    rate = metrics["tenants"]["acme"]["error_rate"]
    assert 0.0 <= rate <= 1.0


async def test_metrics_isolates_tenants(client: AsyncClient):
    """Document counts must be tracked per-tenant independently."""
    await ingest(client, "acme", ACME_HEADERS)

    metrics = (await client.get("/api/v1/metrics")).json()
    acme_count = metrics["tenants"].get("acme", {}).get("document_count", 0)
    globex_count = metrics["tenants"].get("globex", {}).get("document_count", 0)
    assert acme_count >= 1
    assert globex_count == 0
