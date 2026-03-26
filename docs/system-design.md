# System Design: Multi-Tenant Knowledge Indexing Platform

**Version:** 1.0  
**Author:** Platform Engineering  
**Date:** March 2026

---

## 1. Architecture Overview

The platform is a cloud-native, multi-tenant knowledge indexing service that ingests documents, indexes them for fast retrieval, and exposes a RESTful API with strict per-tenant data isolation.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              Client Layer                                        │
│          Enterprise Apps │ Admin UI │ Third-party Integrations                  │
└────────────────────────────────────┬────────────────────────────────────────────┘
                                     │ HTTPS
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          API Gateway + WAF                                       │
│   • TLS termination    • Rate limiting (per-tenant)    • DDoS protection        │
└────────────────────────────────────┬────────────────────────────────────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    ▼                ▼                 ▼
           ┌──────────────┐ ┌──────────────┐  ┌──────────────┐
           │  Ingestion   │ │   Search     │  │  Admin /     │
           │  Service     │ │   Service    │  │  Metrics     │
           │  (ECS)       │ │   (ECS)      │  │  Service     │
           └──────┬───────┘ └──────┬───────┘  └──────┬───────┘
                  │                │ (1) check cache  │
                  │                ▼                  │
                  │       ┌──────────────────┐        │
                  │       │   ElastiCache    │        │
                  │       │   Redis          │        │
                  │       │   (search cache) │        │
                  │       └────────┬─────────┘        │
                  │                │ (2) cache miss   │
                  │                ▼                  │
                  │       ┌──────────────┐            │
                  │       │  OpenSearch  │◄───────────┘
                  │       │  (vector +   │
                  │       │  FTS index)  │
                  │       └──────────────┘
                  │
                  ▼
          ┌───────────────────────────────┐
          │         SQS Queue             │
          │  (async ingestion only)       │
          └───────────────┬───────────────┘
                          ▼
          ┌───────────────────────────────┐
          │     Document Processor        │
          │  • Chunking   • Embedding     │
          │  • Metadata extraction        │
          └───────────────┬───────────────┘
                          │
         ┌────────────────┼────────────────┐
         ▼                ▼                ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
│  Aurora PG   │ │  OpenSearch  │ │       S3         │
│  (metadata   │ │  (vector +   │ │  (raw doc cold   │
│   + audit)   │ │  FTS index)  │ │   storage)       │
└──────────────┘ └──────────────┘ └──────────────────┘
```

> **Note:** SQS is used exclusively by the Ingestion Service for async document
> processing (chunking, embedding generation). The Search Service connects
> directly to ElastiCache Redis (cache check first) and OpenSearch (on cache
> miss). This keeps search latency low — a queue would add hundreds of
> milliseconds and unnecessary complexity to a synchronous read path.

### Data Flow — Document Ingestion

```
Client → API Gateway → Ingestion Service
  → Auth middleware (validate tenant API key / JWT)
  → Schema validation
  → Store metadata in Aurora (tenant-scoped row)
  → Publish message to SQS
  → Return 201 with document_id

SQS → Document Processor Lambda
  → Chunk document (512 token windows, 64-token overlap)
  → Generate embeddings (Bedrock Titan or OpenAI)
  → Upsert vectors into OpenSearch (tenant-prefixed index)
  → Store raw document in S3 (bucket prefix = tenant_id)
  → Write audit event to Aurora audit_log table
```

### Data Flow — Search

```
Client → API Gateway → Search Service
  → Auth middleware
  → Build tenant-scoped query (must_filter by tenant_id)
  → Check Redis cache (key = sha256(tenant_id + query + params))
  → Cache miss: query OpenSearch kNN + BM25 hybrid
  → Rerank results with cross-encoder (optional)
  → Write to cache (TTL = 60s)
  → Return ranked results
```

---

## 2. Multi-Tenancy Strategy

### 2.1 Data Isolation Model

We use a **shared database, separate schema (logical isolation)** approach, with row-level security (RLS) as the enforcement mechanism. This balances operational simplicity with strong isolation guarantees.

| Approach | Pros | Cons | Our Choice |
|----------|------|------|-----------|
| Separate DB per tenant | Strongest isolation | High ops overhead, N×cost | ✗ |
| Separate schema per tenant | Good isolation | Schema drift risk | Partial |
| Shared schema + RLS | Operationally simple | Misconfiguration risk | ✓ |

**Row-Level Security in PostgreSQL:**
```sql
-- Every document row carries tenant_id
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON documents
  USING (tenant_id = current_setting('app.tenant_id'));
```

The application sets `SET LOCAL app.tenant_id = 'acme'` at the start of each database transaction, and Postgres enforces the policy at the engine level — a compromised application query cannot leak cross-tenant rows even with a SQL injection.

### 2.2 Vector Search Isolation (OpenSearch)

Each tenant gets a **dedicated index** (`idx_{tenant_id}_documents`) rather than a shared index with a filter field. This prevents cross-tenant data leakage in approximate-nearest-neighbor queries where filtering after the ANN phase can miss documents.

```
idx_acme_documents        ← tenant "acme" vectors only
idx_globex_documents      ← tenant "globex" vectors only
```

Index-level access control is enforced via OpenSearch fine-grained access control mapped to an IAM role per tenant.

### 2.3 Network / API Isolation

- **API Gateway resource policies** restrict callers by IP allowlist (per-tenant VPC peering or PrivateLink).
- **Authentication**: Every request carries a bearer JWT (issued by Cognito) or a tenant API key. The middleware extracts `tenant_id` from the token claims and asserts it matches the URL path parameter. A mismatch returns `403 Forbidden`.
- **Service-to-service**: Internal services communicate over a private VPC with security groups restricting port access to only required pairs.

---

## 3. Scalability Considerations

### 3.1 Ingestion at 100K Documents/Day

100K docs/day ≈ **70 docs/second** at peak (assuming 2× diurnal spike factor → ~140 docs/s).

**Strategy:**
1. **API tier**: Stateless ECS Fargate tasks behind an ALB. Auto-scaling on CPU and ALB request count. Each task handles ~500 req/s; 1–3 tasks cover the load with headroom.
2. **Queue decoupling**: Ingestion API immediately enqueues to SQS and returns `202 Accepted`. This decouples API latency from embedding generation time (which can take 200–500ms per document).
3. **Processor scaling**: Lambda consumers scale from 0 to 1000 concurrent executions based on SQS queue depth. Reserved concurrency per tenant prevents one tenant from starving others.
4. **S3 for raw storage**: Unlimited scale, no provisioning required. Lifecycle rules archive docs >90 days to Glacier.

### 3.2 Read Scaling at 10K Concurrent Queries

10K concurrent queries ≈ **10K connections**. Naive DB connection-per-request would exhaust Aurora.

**Strategy:**
1. **Connection pooling**: PgBouncer in transaction mode sits between ECS tasks and Aurora, maintaining 100 pooled connections and serving 10K app-level connections.
2. **Redis cache**: 95%+ of searches repeat within a 60-second window (long-tail distribution). Cache hit ratio eliminates most DB/OpenSearch load.
3. **Read replicas**: Aurora Global Database adds up to 15 read replicas. Search queries are routed to a replica cluster endpoint; only writes go to the primary.
4. **OpenSearch**: Configured with 3 data nodes and 1 dedicated master node. Shard count sized so each shard holds ≤ 50GB. For 10K concurrent queries, we horizontally scale the coordinating node pool.

### 3.3 Caching Strategy

| Cache Layer | Technology | TTL | Key |
|-------------|-----------|-----|-----|
| Search results | Redis | 60 s | `sha256(tenant_id:query:limit:offset)` |
| Tenant config | Redis | 300 s | `tenant:{id}:config` |
| Health status | In-process | 5 s | singleton |

Cache invalidation: document writes publish a `cache_invalidate:{tenant_id}` event to a Redis pub/sub channel; all Search Service instances subscribe and evict tenant-scoped keys.

---

## 4. Security & Compliance

### 4.1 Authentication & Authorization

**API Authentication:**
- External clients authenticate with **short-lived JWTs** (15-min expiry) issued by Amazon Cognito after an OAuth2 authorization code flow.
- Service accounts use **API keys** stored in AWS Secrets Manager and rotated every 90 days.
- Every request goes through a centralized `AuthMiddleware` that validates the token signature, checks expiry, and extracts `{tenant_id, roles, scopes}` from claims.

**Authorization (RBAC):**

| Role | Permissions |
|------|-------------|
| `tenant:admin` | All CRUD + manage API keys |
| `tenant:writer` | Ingest documents |
| `tenant:reader` | Search + read documents |
| `platform:admin` | Cross-tenant read, metrics |

Permissions are checked at the route handler level with a `@require_scope("documents:write")` decorator pattern.

### 4.2 Data Encryption

| Layer | Mechanism |
|-------|----------|
| In transit | TLS 1.3 (API Gateway enforces TLS min version) |
| At rest — Aurora | AES-256 via AWS KMS CMK (per-tenant key optional) |
| At rest — S3 | SSE-S3 default; SSE-KMS with per-tenant CMK for regulated tenants |
| At rest — OpenSearch | KMS-managed node-level encryption |
| At rest — Redis | ElastiCache encryption at rest enabled |

**Key Management:** Each regulated tenant optionally brings their own KMS key (BYOK). Key ARNs are stored per-tenant in the `tenants` config table. S3 and Aurora encrypt/decrypt using the tenant's CMK, so even AWS cannot read the data without the customer's key.

### 4.3 Audit Logging Design

Every mutating API call and all search queries write an audit event:

```sql
CREATE TABLE audit_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id   TEXT NOT NULL,
    user_id     TEXT,
    action      TEXT NOT NULL,  -- 'document.create', 'document.search', etc.
    resource_id TEXT,
    ip_address  INET,
    user_agent  TEXT,
    request_id  TEXT NOT NULL,
    status_code INT,
    duration_ms INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_tenant_created ON audit_log (tenant_id, created_at DESC);
```

Audit logs are:
- **Immutable** — no `UPDATE`/`DELETE` is granted to the application role.
- **Retained** — S3 export via DMS for 7-year retention (SOC 2, HIPAA).
- **Monitored** — CloudWatch Logs Insights queries alert on anomalous patterns (burst ingestion, off-hours access, >100 failed auth attempts/min).

---

## 5. Technology Stack Justification

| Component | Choice | Rationale |
|-----------|--------|-----------|
| API Framework | FastAPI (Python) | Async, built-in OpenAPI, Pydantic validation, battle-tested at scale |
| Primary Database | Aurora PostgreSQL Serverless v2 | ACID, RLS, pgvector, auto-pause for dev, scales to 128 ACUs |
| Vector + FTS | OpenSearch 2.x | kNN + BM25 hybrid search in one engine, AWS managed |
| Message Queue | Amazon SQS | Serverless, at-least-once delivery, per-tenant DLQ |
| Cache | ElastiCache Redis 7 | Sub-ms reads, pub/sub for cache invalidation, cluster mode |
| Object Storage | S3 | Infinite scale, lifecycle tiers, S3-compatible |
| Container Orchestration | ECS Fargate | No node management, per-task IAM roles, Graviton2 savings |
| IaC | Terraform | Multi-cloud portability, strong ecosystem, state locking via S3+DynamoDB |
| Auth | Amazon Cognito | Managed OIDC, machine-to-machine client credentials, Cognito hosted UI |
| Observability | CloudWatch + OpenTelemetry | Native AWS integration; OTEL allows future migration to Datadog/Grafana |

### Tradeoffs

**FastAPI vs Go/Rust:** FastAPI has slower raw throughput but 3–5× faster development velocity and a mature ML/NLP ecosystem (LangChain, spaCy). At our target scale (<1000 req/s per task), Python async IO is sufficient.

**Aurora vs DynamoDB:** Aurora requires connection management and capacity planning but provides SQL flexibility and RLS that would be complex to replicate in DynamoDB. DynamoDB would be reconsidered if write throughput exceeds 50K/s.

**OpenSearch vs Pinecone/Weaviate:** OpenSearch is self-hostable and AWS-managed, avoiding vendor lock-in on the vector database. Pinecone offers simpler operations but limits query flexibility and adds egress costs.

**SQS vs Kafka:** Kafka offers log compaction and consumer group replay, which is useful for audit trails. SQS is operationally simpler for our queue depth (<10M messages). We would re-evaluate Kafka if we needed event sourcing or stream processing.

---

## 6. High Availability & Fault Tolerance

- **Multi-AZ**: All stateful components (Aurora, Redis, OpenSearch) deployed across 3 AZs.
- **Circuit breakers**: Search Service uses a `tenacity`-based retry policy with exponential backoff + jitter. After 3 failures the circuit opens for 30s.
- **Bulkheads**: Each tenant's SQS consumer lambda has reserved concurrency, preventing a noisy tenant from exhausting the Lambda pool.
- **Health checks**: ECS tasks are replaced automatically when the `/api/v1/health` check returns non-200 for 2 consecutive intervals (30s each).
- **Blue/green deployments**: CodeDeploy shifts traffic 10% → 50% → 100% with automatic rollback if error rate or p99 latency alarms trigger during the bake window.
- **RTO/RPO**: Aurora automated backups every 5 minutes give RPO < 5 min. Aurora Global Database secondary region gives RTO < 1 min for failover.