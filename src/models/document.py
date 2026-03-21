"""Pydantic models for document ingestion and retrieval."""

from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ── Request Models ────────────────────────────────────────────────────────────

class DocumentIngestRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=512, description="Document title")
    content: str = Field(..., min_length=1, description="Raw document content")
    tags: List[str] = Field(default_factory=list, description="Searchable tags")

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: List[str]) -> List[str]:
        if len(v) > 50:
            raise ValueError("Maximum 50 tags allowed")
        return [tag.strip().lower() for tag in v if tag.strip()]


# ── Response Models ───────────────────────────────────────────────────────────

class DocumentIngestResponse(BaseModel):
    document_id: str
    tenant_id: str
    title: str
    created_at: str

    model_config = {"from_attributes": True}


class DocumentDetail(BaseModel):
    document_id: str
    tenant_id: str
    title: str
    content: str
    tags: List[str]
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}

    @classmethod
    def from_row(cls, row: dict) -> "DocumentDetail":
        return cls(
            document_id=row["document_id"],
            tenant_id=row["tenant_id"],
            title=row["title"],
            content=row["content"],
            tags=json.loads(row["tags"]) if isinstance(row["tags"], str) else row["tags"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class SearchResult(BaseModel):
    document_id: str
    title: str
    snippet: str = Field(..., description="Content excerpt with query terms highlighted")
    score: float = Field(..., description="BM25 relevance score (higher = more relevant)")
    tags: List[str]
    created_at: str


class SearchResponse(BaseModel):
    total: int
    limit: int
    offset: int
    results: List[SearchResult]
    query_time_ms: float


# ── Error Models ──────────────────────────────────────────────────────────────

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    request_id: Optional[str] = None
