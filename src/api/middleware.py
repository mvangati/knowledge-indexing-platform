"""
Authentication and observability middleware.

Auth flow:
  1. Extract API key from request header (default: X-API-Key).
  2. Look up the tenant_id associated with that key.
  3. If the route contains a {tenantId} path parameter, assert it matches
     the authenticated tenant_id. This prevents a valid key from one tenant
     accessing another tenant's data.
  4. Store tenant_id in request.state for downstream use.

Metrics flow:
  After the response is sent, record duration and status code per tenant.
"""

from __future__ import annotations

import time
import uuid
import re

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from src.config import get_settings
from src.services.metrics_service import metrics_service
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Routes that do not require authentication
_PUBLIC_PATHS = {"/api/v1/health", "/api/v1/metrics", "/openapi.json", "/docs", "/redoc"}


class AuthMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        request.state.tenant_id = None
        t0 = time.monotonic()

        # Skip auth for public paths
        if request.url.path in _PUBLIC_PATHS or request.url.path.startswith(
            ("/docs", "/redoc", "/openapi")
        ):
            response = await call_next(request)
            return response

        settings = get_settings()
        api_key = request.headers.get(settings.api_key_header)

        if not api_key:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "Missing API key",
                    "detail": f"Provide a valid key in the '{settings.api_key_header}' header",
                    "request_id": request_id,
                },
            )

        api_key_to_tenant = settings.api_key_to_tenant
        tenant_id = api_key_to_tenant.get(api_key)

        if not tenant_id:
            return JSONResponse(
                status_code=401,
                content={
                    "error": "Invalid API key",
                    "request_id": request_id,
                },
            )

        # Check that the key matches the tenant in the URL path, if present
        match = re.search(r"/tenants/([^/]+)", request.url.path)
        path_tenant = match.group(1) if match else None
        
        if path_tenant and path_tenant != tenant_id:
            logger.info(
                '"action":"auth.tenant_mismatch","authenticated_tenant":"%s","requested_tenant":"%s"',
                tenant_id,
                path_tenant,
            )
            return JSONResponse(
                status_code=403,
                content={
                    "error": "Forbidden",
                    "detail": "API key does not grant access to this tenant",
                    "request_id": request_id,
                },
            )

        request.state.tenant_id = tenant_id

        response = await call_next(request)

        duration_ms = (time.monotonic() - t0) * 1000
        metrics_service.record_request(tenant_id, duration_ms, response.status_code)

        response.headers["X-Request-ID"] = request_id
        return response
