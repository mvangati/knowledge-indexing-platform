"""
In-process metrics store.

In production this would be replaced by a Prometheus client that exposes
metrics to a scrape endpoint, or by pushing to CloudWatch EMF.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Dict, List


@dataclass
class TenantMetrics:
    request_count: int = 0
    error_count: int = 0
    document_count: int = 0
    total_duration_ms: float = 0.0
    durations: List[float] = field(default_factory=list)

    @property
    def avg_response_time_ms(self) -> float:
        if not self.durations:
            return 0.0
        return self.total_duration_ms / len(self.durations)

    @property
    def error_rate(self) -> float:
        if self.request_count == 0:
            return 0.0
        return self.error_count / self.request_count


class MetricsService:
    def __init__(self) -> None:
        self._lock = Lock()
        self._tenants: Dict[str, TenantMetrics] = defaultdict(TenantMetrics)
        self._start_time = time.time()

    def record_request(
        self,
        tenant_id: str,
        duration_ms: float,
        status_code: int,
    ) -> None:
        with self._lock:
            m = self._tenants[tenant_id]
            m.request_count += 1
            m.total_duration_ms += duration_ms
            m.durations.append(duration_ms)
            # Keep only the last 10K samples to bound memory
            if len(m.durations) > 10_000:
                m.durations = m.durations[-10_000:]
            if status_code >= 500:
                m.error_count += 1

    def record_document_created(self, tenant_id: str) -> None:
        with self._lock:
            self._tenants[tenant_id].document_count += 1

    def record_document_deleted(self, tenant_id: str) -> None:
        with self._lock:
            m = self._tenants[tenant_id]
            if m.document_count > 0:
                m.document_count -= 1

    def set_document_count(self, tenant_id: str, count: int) -> None:
        with self._lock:
            self._tenants[tenant_id].document_count = count

    def snapshot(self) -> Dict:
        with self._lock:
            tenants_snapshot = {
                tid: {
                    "request_count": m.request_count,
                    "error_count": m.error_count,
                    "error_rate": round(m.error_rate, 4),
                    "document_count": m.document_count,
                    "avg_response_time_ms": round(m.avg_response_time_ms, 2),
                }
                for tid, m in self._tenants.items()
            }

        return {
            "uptime_seconds": round(time.time() - self._start_time, 1),
            "tenants": tenants_snapshot,
        }

    def reset(self) -> None:
        with self._lock:
            self._tenants.clear()
            self._start_time = time.time()

# Singleton instance shared across the application
metrics_service = MetricsService()
