"""Health check and metrics endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter
from pydantic import BaseModel

from src.db.database import get_db
from src.services.metrics_service import metrics_service

router = APIRouter(prefix="/api/v1", tags=["Observability"])

_start_time = time.time()


class HealthResponse(BaseModel):
    status: str
    database: str
    uptime_seconds: float
    version: str = "1.0.0"


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Returns service health status. Used by load balancers for readiness probes.",
)
async def health_check() -> HealthResponse:
    db_status = "ok"
    try:
        async with get_db() as db:
            await db.execute("SELECT 1")
    except Exception:
        db_status = "degraded"

    return HealthResponse(
        status="ok" if db_status == "ok" else "degraded",
        database=db_status,
        uptime_seconds=round(time.time() - _start_time, 1),
    )


@router.get(
    "/metrics",
    summary="Service metrics",
    description=(
        "Exposes per-tenant request counts, average response times, "
        "document counts, and error rates."
    ),
)
async def get_metrics() -> dict:
    return metrics_service.snapshot()
