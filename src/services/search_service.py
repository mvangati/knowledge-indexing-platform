"""
Search service using SQLite FTS5 with BM25 ranking.

Tenant isolation is enforced by binding tenant_id in every query.
The FTS5 MATCH clause is further constrained by a JOIN back to the
documents table so that only the querying tenant's rows can appear.

In production this maps to an OpenSearch query with a must_filter on
tenant_id, or a dedicated per-tenant index.
"""

from __future__ import annotations

import json
import math
import re
import time
from typing import List, Tuple

from src.db.database import get_db
from src.models.document import SearchResponse, SearchResult
from src.utils.logger import get_logger

logger = get_logger(__name__)

_SNIPPET_LENGTH = 200  # characters
_SNIPPET_WINDOW = 50   # characters around the first match


def _make_snippet(content: str, query: str) -> str:
    """Return a short excerpt of content around the first query term match."""
    terms = [t.lower() for t in re.split(r"\s+", query.strip()) if t]
    lower_content = content.lower()

    start = 0
    for term in terms:
        idx = lower_content.find(term)
        if idx != -1:
            start = max(0, idx - _SNIPPET_WINDOW)
            break

    end = min(len(content), start + _SNIPPET_LENGTH)
    snippet = content[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(content):
        snippet = snippet + "…"
    return snippet


def _normalize_score(raw_bm25: float) -> float:
    """
    FTS5 BM25 returns negative values (lower = better match).
    Convert to a 0–1 scale where 1 is the best possible match.
    """
    # sigmoid-style normalization
    return round(1 / (1 + math.exp(raw_bm25)), 4)


def _sanitize_query(query: str) -> str:
    """
    Escape FTS5 special characters to prevent syntax errors from
    user-supplied queries, then construct a prefix-search expression.
    """
    # Remove characters that have special meaning in FTS5 queries
    sanitized = re.sub(r'["\'\^\*\(\)\:\,\.]', " ", query).strip()
    if not sanitized:
        return '""'
    # Join terms with AND for more precise results; add * for prefix match
    terms = sanitized.split()
    return " AND ".join(f'"{t}"*' for t in terms if t)


class SearchService:
    async def search(
        self,
        tenant_id: str,
        query: str,
        limit: int = 10,
        offset: int = 0,
    ) -> SearchResponse:
        t0 = time.monotonic()

        fts_query = _sanitize_query(query)

        async with get_db() as db:
            # Count matching documents for this tenant
            async with db.execute(
                """
                SELECT COUNT(*) as cnt
                FROM documents_fts f
                JOIN documents d ON d.rowid = f.rowid
                WHERE documents_fts MATCH ?
                  AND d.tenant_id = ?
                """,
                (fts_query, tenant_id),
            ) as cursor:
                count_row = await cursor.fetchone()
            total = count_row["cnt"] if count_row else 0

            # Ranked retrieval — bm25() returns negative scores
            async with db.execute(
                """
                SELECT
                    d.document_id,
                    d.title,
                    d.content,
                    d.tags,
                    d.created_at,
                    bm25(documents_fts) AS bm25_score
                FROM documents_fts f
                JOIN documents d ON d.rowid = f.rowid
                WHERE documents_fts MATCH ?
                  AND d.tenant_id = ?
                ORDER BY bm25_score ASC   -- ascending because BM25 is negative
                LIMIT ? OFFSET ?
                """,
                (fts_query, tenant_id, limit, offset),
            ) as cursor:
                rows = await cursor.fetchall()

        elapsed_ms = (time.monotonic() - t0) * 1000

        results: List[SearchResult] = []
        for row in rows:
            results.append(
                SearchResult(
                    document_id=row["document_id"],
                    title=row["title"],
                    snippet=_make_snippet(row["content"], query),
                    score=_normalize_score(row["bm25_score"]),
                    tags=(
                        json.loads(row["tags"])
                        if isinstance(row["tags"], str)
                        else row["tags"]
                    ),
                    created_at=row["created_at"],
                )
            )

        logger.info(
            '"action":"search","tenant_id":"%s","query":"%s","total":%d,"time_ms":%.2f',
            tenant_id,
            query[:100],
            total,
            elapsed_ms,
        )

        return SearchResponse(
            total=total,
            limit=limit,
            offset=offset,
            results=results,
            query_time_ms=round(elapsed_ms, 2),
        )
