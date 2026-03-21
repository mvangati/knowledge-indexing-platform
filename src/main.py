"""
Knowledge Indexing Platform — FastAPI application entrypoint.

Startup order:
  1. Load settings (from .env or environment variables)
  2. Initialise SQLite database (create tables + FTS index if not present)
  3. Register middleware (auth + metrics)
  4. Mount routers
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.documents import router as documents_router
from src.api.health import router as health_router
from src.api.middleware import AuthMetricsMiddleware
from src.config import get_settings
from src.db.database import init_db
from src.utils.logger import get_logger

settings = get_settings()
logger = get_logger("main", settings.log_level)

app = FastAPI(
    title="Knowledge Indexing Platform",
    description=(
        "Multi-tenant document ingestion and semantic search service.\n\n"
        "Authenticate with an `X-API-Key` header. Each API key is scoped to a single tenant."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS (lock down in production) ────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth + Metrics middleware ─────────────────────────────────────────────────
app.add_middleware(AuthMetricsMiddleware)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(health_router)
app.include_router(documents_router)


# ── Lifespan ──────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup() -> None:
    logger.info('"event":"startup","log_level":"%s"', settings.log_level)
    await init_db()
    logger.info('"event":"ready"')


@app.on_event("shutdown")
async def shutdown() -> None:
    logger.info('"event":"shutdown"')
