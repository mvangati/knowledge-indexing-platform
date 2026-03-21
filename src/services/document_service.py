"""Document ingestion and retrieval service."""

from __future__ import annotations

import json
from typing import Optional

try:
    from ulid import ULID  # python-ulid >= 2.x
    def _new_document_id() -> str:
        return f"doc_{ULID()}"
except ImportError:
    import uuid
    def _new_document_id() -> str:  # type: ignore[misc]
        return f"doc_{uuid.uuid4().hex.upper()}"

from src.db.database import get_db
from src.models.document import (
    DocumentDetail,
    DocumentIngestRequest,
    DocumentIngestResponse,
)
from src.services.metrics_service import metrics_service
from src.utils.logger import get_logger

logger = get_logger(__name__)


class DocumentService:
    async def ingest(
        self, tenant_id: str, request: DocumentIngestRequest
    ) -> DocumentIngestResponse:
        """Store a document and return its assigned ID."""
        document_id = _new_document_id()
        tags_json = json.dumps(request.tags)

        async with get_db() as db:
            # Ensure tenant row exists
            await db.execute(
                "INSERT OR IGNORE INTO tenants (tenant_id) VALUES (?)",
                (tenant_id,),
            )
            await db.execute(
                """
                INSERT INTO documents (document_id, tenant_id, title, content, tags)
                VALUES (?, ?, ?, ?, ?)
                """,
                (document_id, tenant_id, request.title, request.content, tags_json),
            )
            await db.commit()

            async with db.execute(
                "SELECT created_at FROM documents WHERE document_id = ?",
                (document_id,),
            ) as cursor:
                row = await cursor.fetchone()

        metrics_service.record_document_created(tenant_id)
        logger.info(
            '"action":"document.create","tenant_id":"%s","document_id":"%s"',
            tenant_id,
            document_id,
        )

        return DocumentIngestResponse(
            document_id=document_id,
            tenant_id=tenant_id,
            title=request.title,
            created_at=row["created_at"],
        )

    async def get_document(
        self, tenant_id: str, document_id: str
    ) -> Optional[DocumentDetail]:
        """Retrieve a single document — returns None if not found or wrong tenant."""
        async with get_db() as db:
            async with db.execute(
                """
                SELECT document_id, tenant_id, title, content, tags, created_at, updated_at
                FROM documents
                WHERE document_id = ? AND tenant_id = ?
                """,
                (document_id, tenant_id),
            ) as cursor:
                row = await cursor.fetchone()

        if row is None:
            return None
        return DocumentDetail.from_row(dict(row))

    async def delete_document(self, tenant_id: str, document_id: str) -> bool:
        """Delete a document. Returns True if deleted, False if not found."""
        async with get_db() as db:
            async with db.execute(
                "SELECT 1 FROM documents WHERE document_id = ? AND tenant_id = ?",
                (document_id, tenant_id),
            ) as cursor:
                exists = await cursor.fetchone()

            if not exists:
                return False

            await db.execute(
                "DELETE FROM documents WHERE document_id = ? AND tenant_id = ?",
                (document_id, tenant_id),
            )
            await db.commit()

        metrics_service.record_document_deleted(tenant_id)
        logger.info(
            '"action":"document.delete","tenant_id":"%s","document_id":"%s"',
            tenant_id,
            document_id,
        )
        return True

    async def sync_document_count(self, tenant_id: str) -> None:
        """Sync the in-memory document count from the database."""
        async with get_db() as db:
            async with db.execute(
                "SELECT COUNT(*) as cnt FROM documents WHERE tenant_id = ?",
                (tenant_id,),
            ) as cursor:
                row = await cursor.fetchone()
        count = row["cnt"] if row else 0
        metrics_service.set_document_count(tenant_id, count)
