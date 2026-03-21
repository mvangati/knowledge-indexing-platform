"""
Async SQLite database layer using aiosqlite.

In production this module would be swapped for asyncpg (PostgreSQL).
SQLite FTS5 is used here to demonstrate ranked full-text search
with BM25 scoring — the same conceptual API maps to OpenSearch in production.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import aiosqlite

from src.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

_db_path: str = ""
_lock = asyncio.Lock()


def _resolve_db_path() -> str:
    settings = get_settings()
    url = settings.database_url
    # Strip SQLAlchemy-style prefix
    path = url.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
    return path


async def init_db() -> None:
    """Create tables and FTS indexes if they do not exist."""
    global _db_path
    _db_path = _resolve_db_path()
    # Ensure parent directory exists
    parent = os.path.dirname(os.path.abspath(_db_path))
    os.makedirs(parent, exist_ok=True)

    async with aiosqlite.connect(_db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA foreign_keys=ON;")

        # Tenants registry
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tenants (
                tenant_id   TEXT PRIMARY KEY,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # Documents — metadata store with tenant isolation via tenant_id column
        await db.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                document_id TEXT PRIMARY KEY,
                tenant_id   TEXT NOT NULL,
                title       TEXT NOT NULL,
                content     TEXT NOT NULL,
                tags        TEXT NOT NULL DEFAULT '[]',
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_documents_tenant
            ON documents (tenant_id, created_at DESC)
        """)

        # FTS5 virtual table — BM25 ranked full-text search
        # content='' means the FTS table does NOT store text (saves space);
        # it references the documents table via content_rowid.
        await db.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts
            USING fts5(
                title,
                content,
                tags,
                tenant_id UNINDEXED,
                content='documents',
                content_rowid='rowid',
                tokenize='porter ascii'
            )
        """)

        # Keep FTS in sync via triggers
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS documents_fts_insert
            AFTER INSERT ON documents BEGIN
                INSERT INTO documents_fts(rowid, title, content, tags, tenant_id)
                VALUES (new.rowid, new.title, new.content, new.tags, new.tenant_id);
            END
        """)
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS documents_fts_delete
            AFTER DELETE ON documents BEGIN
                INSERT INTO documents_fts(documents_fts, rowid, title, content, tags, tenant_id)
                VALUES ('delete', old.rowid, old.title, old.content, old.tags, old.tenant_id);
            END
        """)
        await db.execute("""
            CREATE TRIGGER IF NOT EXISTS documents_fts_update
            AFTER UPDATE ON documents BEGIN
                INSERT INTO documents_fts(documents_fts, rowid, title, content, tags, tenant_id)
                VALUES ('delete', old.rowid, old.title, old.content, old.tags, old.tenant_id);
                INSERT INTO documents_fts(rowid, title, content, tags, tenant_id)
                VALUES (new.rowid, new.title, new.content, new.tags, new.tenant_id);
            END
        """)

        # Audit log — append-only
        await db.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id          TEXT PRIMARY KEY,
                tenant_id   TEXT NOT NULL,
                action      TEXT NOT NULL,
                resource_id TEXT,
                user_agent  TEXT,
                ip_address  TEXT,
                request_id  TEXT,
                status_code INTEGER,
                duration_ms REAL,
                created_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_audit_tenant_created
            ON audit_log (tenant_id, created_at DESC)
        """)

        await db.commit()

    logger.info('"Database initialized at %s"', _db_path)


@asynccontextmanager
async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Yield a database connection with row_factory set to dict-like rows."""
    if not _db_path:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    async with aiosqlite.connect(_db_path) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys=ON;")
        yield db
