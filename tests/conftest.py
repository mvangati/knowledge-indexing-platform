"""
Shared pytest fixtures.

Each test gets a fresh in-memory SQLite database so tests are fully isolated
and can run in parallel without interference.
"""

from __future__ import annotations

import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# ── Force test environment BEFORE any src imports ────────────────────────────
os.environ.setdefault(
    "TENANT_KEYS", "acme:key-acme,globex:key-globex,empty-tenant:key-empty"
)
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./data/test_knowledge.db")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from src.main import app  # noqa: E402
from src.db import database as db_module  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def reset_db(tmp_path):
    """
    Point the database at a temporary file for each test, re-initialise it,
    and clean up afterwards.
    """
    db_path = str(tmp_path / "test.db")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"

    # Patch module-level path and re-run init
    db_module._db_path = ""
    # Also clear the lru_cache so settings pick up the new env var
    from src.config import get_settings
    get_settings.cache_clear()

    await db_module.init_db()
    # Reset in-process metrics so counts don't bleed between tests
    from src.services.metrics_service import metrics_service
    metrics_service.reset()
    yield
    # tmp_path is cleaned up automatically by pytest


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    """Return an async test client wired to the FastAPI app."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


# ── Convenience headers ───────────────────────────────────────────────────────

ACME_HEADERS = {"X-API-Key": "key-acme"}
GLOBEX_HEADERS = {"X-API-Key": "key-globex"}
EMPTY_HEADERS = {"X-API-Key": "key-empty"}
INVALID_HEADERS = {"X-API-Key": "bad-key-000"}


# ── Helper ────────────────────────────────────────────────────────────────────

async def ingest(client: AsyncClient, tenant: str, headers: dict, **kwargs) -> dict:
    """Convenience wrapper to ingest a document and return the JSON body."""
    payload = {
        "title": kwargs.get("title", "Test Document"),
        "content": kwargs.get("content", "This is test content for the document."),
        "tags": kwargs.get("tags", ["test"]),
    }
    resp = await client.post(
        f"/api/v1/tenants/{tenant}/documents",
        json=payload,
        headers=headers,
    )
    return resp
