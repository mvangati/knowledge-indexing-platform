"""Application configuration loaded from environment variables / .env file."""

from __future__ import annotations

from functools import lru_cache
from typing import Dict

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/knowledge.db"

    # Auth
    api_key_header: str = "X-API-Key"
    # Format: "tenantId:apiKey,tenantId2:apiKey2"
    tenant_keys: str = "tenant1:key-tenant1-secret,tenant2:key-tenant2-secret"

    # Logging
    log_level: str = "INFO"

    # Search
    search_default_limit: int = 10
    search_max_limit: int = 100

    # Document limits
    max_document_size_kb: int = 5120  # 5 MB

    @property
    def tenant_key_map(self) -> Dict[str, str]:
        """Return {tenant_id: api_key} mapping parsed from TENANT_KEYS."""
        result: Dict[str, str] = {}
        for pair in self.tenant_keys.split(","):
            pair = pair.strip()
            if ":" in pair:
                tenant_id, api_key = pair.split(":", 1)
                result[tenant_id.strip()] = api_key.strip()
        return result

    @property
    def api_key_to_tenant(self) -> Dict[str, str]:
        """Return {api_key: tenant_id} reverse mapping."""
        return {v: k for k, v in self.tenant_key_map.items()}

    @property
    def max_document_size_bytes(self) -> int:
        return self.max_document_size_kb * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
