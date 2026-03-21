"""Document ingestion, retrieval, and search endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import Response

from src.config import get_settings
from src.models.document import (
    DocumentDetail,
    DocumentIngestRequest,
    DocumentIngestResponse,
    SearchResponse,
)
from src.services.document_service import DocumentService
from src.services.search_service import SearchService

router = APIRouter(prefix="/api/v1/tenants/{tenantId}", tags=["Documents"])

_document_service = DocumentService()
_search_service = SearchService()


@router.post(
    "/documents",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentIngestResponse,
    summary="Ingest a document",
    description="Store a new document for the authenticated tenant. Returns the assigned document_id.",
)
async def ingest_document(
    tenantId: str,
    body: DocumentIngestRequest,
    request: Request,
) -> DocumentIngestResponse:
    settings = get_settings()
    content_bytes = len(body.content.encode("utf-8"))
    if content_bytes > settings.max_document_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Document content exceeds maximum allowed size of "
                f"{settings.max_document_size_kb} KB"
            ),
        )
    return await _document_service.ingest(tenantId, body)


@router.get(
    "/documents/search",
    response_model=SearchResponse,
    summary="Search documents",
    description=(
        "Full-text search across the authenticated tenant's documents using BM25 ranking. "
        "Results are paginated and include relevance scores."
    ),
)
async def search_documents(
    tenantId: str,
    request: Request,
    q: str = Query(..., min_length=1, max_length=512, description="Search query"),
    limit: int = Query(None, ge=1, description="Max results per page"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
) -> SearchResponse:
    settings = get_settings()
    if limit is None:
        limit = settings.search_default_limit
    limit = min(limit, settings.search_max_limit)
    return await _search_service.search(
        tenant_id=tenantId,
        query=q,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/documents/{documentId}",
    response_model=DocumentDetail,
    summary="Get a document by ID",
)
async def get_document(
    tenantId: str,
    documentId: str,
    request: Request,
) -> DocumentDetail:
    doc = await _document_service.get_document(tenantId, documentId)
    if doc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{documentId}' not found",
        )
    return doc


@router.delete(
    "/documents/{documentId}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
    summary="Delete a document",
)
async def delete_document(
    tenantId: str,
    documentId: str,
    request: Request,
) -> None:
    deleted = await _document_service.delete_document(tenantId, documentId)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{documentId}' not found",
        )
