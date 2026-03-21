# Knowledge Indexing Platform

A scalable, multi-tenant knowledge indexing platform supporting document ingestion, semantic search, audit logging, and compliance-ready observability.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Quick Start](#quick-start)
- [Setup Instructions](#setup-instructions)
- [Running Tests](#running-tests)
- [API Usage Examples](#api-usage-examples)
- [Infrastructure Deployment](#infrastructure-deployment)
- [Time Spent](#time-spent)
- [Assumptions](#assumptions)
- [Future Improvements](#future-improvements)

---

## Architecture Overview

See [`docs/system-design.md`](docs/system-design.md) for the full design document.

**Key components:**
- **FastAPI** — async REST API with built-in OpenAPI/Swagger
- **SQLite + FTS5** — embedded full-text search with tenant-scoped row-level isolation
- **API Key Middleware** — per-tenant authentication and rate-limiting hooks
- **Prometheus-style Metrics** — in-process counters exposed via `/api/v1/metrics`
- **Structured JSON Logging** — request tracing with correlation IDs

---

## Quick Start

```bash
# Clone and enter the project
git clone https://github.com/your-org/knowledge-indexing-platform.git
cd knowledge-indexing-platform

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy and edit environment variables
cp .env.example .env

# Run the server
uvicorn src.main:app --reload --port 8000
```

Open **http://localhost:8000/docs** for the interactive Swagger UI.

---

## Setup Instructions

### Prerequisites

| Tool | Version |
|------|---------|
| Python | ≥ 3.11 |
| pip | ≥ 23 |
| Docker (optional) | ≥ 24 |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./data/knowledge.db` | SQLite file path |
| `API_KEY_HEADER` | `X-API-Key` | Header name for tenant auth |
| `LOG_LEVEL` | `INFO` | Python logging level |
| `MAX_DOCUMENT_SIZE_KB` | `5120` | Max document content size |
| `SEARCH_DEFAULT_LIMIT` | `10` | Default page size for search |
| `SEARCH_MAX_LIMIT` | `100` | Maximum page size for search |
| `TENANT_KEYS` | `tenant1:key-abc,tenant2:key-xyz` | Comma-sep tenant:key pairs |

### Running with Docker

```bash
# Build and start
docker-compose -f infra/docker/docker-compose.yml up --build

# Tail logs
docker-compose -f infra/docker/docker-compose.yml logs -f app
```

---

## Running Tests

### Install dev dependencies

```bash
pip install -r requirements-dev.txt
```

### Run all tests with coverage

```bash
pytest tests/ -v --cov=src --cov-report=term-missing --cov-report=html
```

Coverage report is written to `htmlcov/index.html`.

### Run a specific test file

```bash
pytest tests/test_documents.py -v
pytest tests/test_search.py -v
pytest tests/test_health.py -v
pytest tests/test_middleware.py -v
```

### Run performance benchmarks

```bash
python tests/benchmarks/bench_search.py
```

This seeds 10 000 documents and measures p50/p95/p99 latencies for search queries.

### Check coverage threshold

```bash
pytest tests/ --cov=src --cov-fail-under=70
```

---

## API Usage Examples

### Provision tenant API keys (in `.env`)

```
TENANT_KEYS=acme:key-acme-secret,globex:key-globex-secret
```

### 1. Ingest a document

```bash
curl -s -X POST http://localhost:8000/api/v1/tenants/acme/documents \
  -H "Content-Type: application/json" \
  -H "X-API-Key: key-acme-secret" \
  -d '{
    "title": "Q4 Financial Report",
    "content": "Revenue increased 24% year-over-year driven by enterprise sales...",
    "tags": ["finance", "quarterly", "enterprise"]
  }' | jq
```

**Response `201 Created`:**
```json
{
  "document_id": "doc_01HZ8K...",
  "tenant_id": "acme",
  "title": "Q4 Financial Report",
  "created_at": "2026-03-18T10:00:00Z"
}
```

### 2. Search documents

```bash
curl -s "http://localhost:8000/api/v1/tenants/acme/documents/search?q=enterprise+sales&limit=5&offset=0" \
  -H "X-API-Key: key-acme-secret" | jq
```

**Response `200 OK`:**
```json
{
  "total": 1,
  "limit": 5,
  "offset": 0,
  "results": [
    {
      "document_id": "doc_01HZ8K...",
      "title": "Q4 Financial Report",
      "snippet": "...driven by enterprise sales...",
      "score": 0.87,
      "tags": ["finance", "quarterly", "enterprise"],
      "created_at": "2026-03-18T10:00:00Z"
    }
  ],
  "query_time_ms": 4.2
}
```

### 3. Health check

```bash
curl -s http://localhost:8000/api/v1/health | jq
```

### 4. Metrics

```bash
curl -s http://localhost:8000/api/v1/metrics | jq
```

### 5. Get a document by ID

```bash
curl -s http://localhost:8000/api/v1/tenants/acme/documents/doc_01HZ8K... \
  -H "X-API-Key: key-acme-secret" | jq
```

### 6. Cross-tenant isolation test (should return 403)

```bash
curl -s "http://localhost:8000/api/v1/tenants/globex/documents/search?q=financial" \
  -H "X-API-Key: key-acme-secret" | jq
```

---

## Infrastructure Deployment

See [`infra/terraform/README.md`](infra/terraform/README.md) for AWS deployment instructions.

**Overview:**
- ECS Fargate cluster with auto-scaling
- Aurora PostgreSQL Serverless v2 (production replacement for SQLite)
- API Gateway + WAF
- CloudWatch dashboards and alarms
- Blue/green deployments via CodeDeploy

---

## Time Spent

| Section | Time |
|---------|------|
| Part 1 — System Design | ~2 hrs |
| Part 2 — Core Implementation | ~4 hrs |
| Part 3 — Infrastructure as Code | ~2 hrs |
| Documentation + polish | ~1 hr |
| **Total** | **~9 hrs** |

---

## Assumptions

1. **Simplified auth** — API keys are stored in environment variables. Production would use AWS Secrets Manager or Vault.
2. **SQLite for dev/test** — production Terraform provisions Aurora PostgreSQL with pgvector for true semantic search.
3. **In-process metrics** — production would push to Prometheus/CloudWatch; the in-memory counters reset on restart.
4. **Single-region** — Terraform provisions us-east-1; multi-region would require Route 53 latency routing + read replicas.
5. **Text search only** — FTS5 BM25 ranking is used; production would add vector embeddings (OpenAI/Bedrock) for semantic similarity.
6. **No message queue** — ingestion is synchronous; production would use SQS + Lambda workers for async processing of large documents.

---

## Future Improvements

- [ ] Replace FTS5 with vector embeddings (pgvector + OpenAI Embeddings or AWS Bedrock Titan)
- [ ] Add SQS-based async ingestion pipeline for large document batches
- [ ] Implement per-tenant rate limiting with Redis sliding window
- [ ] Add OAuth2/OIDC (Auth0 or Cognito) replacing API key auth
- [ ] Multi-region active-active with CRDTs for eventual consistency
- [ ] Webhook support for ingestion completion events
- [ ] Document chunking + overlap for large PDFs
- [ ] OpenTelemetry traces exported to Jaeger/X-Ray
