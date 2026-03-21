"""
Performance benchmark: seed N documents then measure search latency.

Usage:
    python tests/benchmarks/bench_search.py [--docs 10000] [--runs 100]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import statistics
import time

os.environ.setdefault("TENANT_KEYS", "bench-tenant:bench-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./data/bench.db")
os.environ.setdefault("LOG_LEVEL", "WARNING")

from src.db.database import init_db
from src.services.document_service import DocumentService
from src.services.search_service import SearchService
from src.models.document import DocumentIngestRequest

LOREM = (
    "machine learning artificial intelligence natural language processing "
    "deep learning neural network transformer model embeddings retrieval "
    "augmented generation vector database knowledge graph enterprise search "
    "document indexing tenant isolation data privacy compliance audit logging "
    "scalable cloud infrastructure microservices kubernetes docker terraform "
)

QUERIES = [
    "machine learning",
    "artificial intelligence",
    "knowledge graph",
    "audit logging",
    "cloud infrastructure",
    "vector database",
    "document indexing",
    "neural network",
]


def random_content(word_count: int = 150) -> str:
    words = LOREM.split()
    return " ".join(random.choices(words, k=word_count))


async def seed(doc_service: DocumentService, tenant_id: str, n: int) -> None:
    print(f"Seeding {n} documents for tenant '{tenant_id}'...")
    batch_size = 500
    for start in range(0, n, batch_size):
        tasks = [
            doc_service.ingest(
                tenant_id,
                DocumentIngestRequest(
                    title=f"Document {start + i}: {random.choice(LOREM.split())} guide",
                    content=random_content(),
                    tags=random.sample(LOREM.split(), k=3),
                ),
            )
            for i in range(min(batch_size, n - start))
        ]
        await asyncio.gather(*tasks)
        print(f"  {min(start + batch_size, n)}/{n} seeded…")
    print(f"Seeding complete.\n")


async def benchmark(search_service: SearchService, tenant_id: str, runs: int) -> None:
    print(f"Running {runs} search queries...")
    latencies: list[float] = []

    for i in range(runs):
        q = random.choice(QUERIES)
        t0 = time.perf_counter()
        result = await search_service.search(tenant_id=tenant_id, query=q, limit=10)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        latencies.append(elapsed_ms)

    latencies.sort()
    print("\n=== Search Benchmark Results ===")
    print(f"  Runs         : {runs}")
    print(f"  Min          : {min(latencies):.2f} ms")
    print(f"  p50 (median) : {statistics.median(latencies):.2f} ms")
    print(f"  p95          : {latencies[int(0.95 * len(latencies))]:.2f} ms")
    print(f"  p99          : {latencies[int(0.99 * len(latencies))]:.2f} ms")
    print(f"  Max          : {max(latencies):.2f} ms")
    print(f"  Mean         : {statistics.mean(latencies):.2f} ms")

    p99 = latencies[int(0.99 * len(latencies))]
    target_ms = 100
    if p99 <= target_ms:
        print(f"\n✅ p99 ({p99:.1f} ms) is within the {target_ms} ms target.")
    else:
        print(f"\n⚠️  p99 ({p99:.1f} ms) EXCEEDS the {target_ms} ms target.")


async def main(num_docs: int, num_runs: int) -> None:
    os.makedirs("./data", exist_ok=True)
    await init_db()

    tenant_id = "bench-tenant"
    doc_service = DocumentService()
    search_service = SearchService()

    await seed(doc_service, tenant_id, num_docs)
    await benchmark(search_service, tenant_id, num_runs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search performance benchmark")
    parser.add_argument("--docs", type=int, default=10_000, help="Number of documents to seed")
    parser.add_argument("--runs", type=int, default=100, help="Number of search queries to run")
    args = parser.parse_args()

    asyncio.run(main(args.docs, args.runs))
