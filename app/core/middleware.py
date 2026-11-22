"""HTTP middleware: request IDs, body-size guard, access logging."""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from limits import parse as parse_limit
from limits.storage import storage_from_string
from limits.strategies import MovingWindowRateLimiter
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.errors import error_payload

logger = logging.getLogger("fitness_api.access")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a request ID to every request and response."""

    _VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        candidate = request.headers.get("X-Request-ID", "")
        request_id = candidate if self._VALID_ID.fullmatch(candidate) else uuid.uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class MaxBodySizeMiddleware(BaseHTTPMiddleware):
    """Reject obviously oversized JSON requests before parsing them."""

    def __init__(self, app, max_bytes: int) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
            except ValueError:
                size = 0
            if size > self.max_bytes:
                request_id = getattr(request.state, "request_id", "-")
                return JSONResponse(
                    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                    content=error_payload(
                        code="request_too_large",
                        message=f"Body request melebihi batas {self.max_bytes} byte.",
                        request_id=request_id,
                    ),
                )
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed moving-window limiter backed by the ``limits`` library.

    ``memory://`` is suitable for one process.  For multiple workers or
    instances, point ``storage_uri`` at Redis.
    """

    def __init__(
        self,
        app,
        *,
        enabled: bool,
        limit: str,
        storage_uri: str,
        trust_proxy_headers: bool = False,
    ) -> None:
        super().__init__(app)
        self.enabled = enabled
        self.trust_proxy_headers = trust_proxy_headers
        self.limit_item = parse_limit(limit) if enabled else None
        self.storage = storage_from_string(storage_uri) if enabled else None
        self.strategy = MovingWindowRateLimiter(self.storage) if self.storage is not None else None

    def _key(self, request: Request) -> str:
        if self.trust_proxy_headers:
            forwarded = request.headers.get("x-forwarded-for")
            if forwarded:
                return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if not self.enabled or self.limit_item is None or self.strategy is None:
            return await call_next(request)

        # Platform health checks and metrics scrapes must not consume a
        # client's API quota.
        if request.url.path in {"/health", "/ready", "/metrics"}:
            return await call_next(request)

        key = self._key(request)
        allowed = self.strategy.hit(self.limit_item, key)
        stats = self.strategy.get_window_stats(self.limit_item, key)

        if allowed:
            response = await call_next(request)
        else:
            request_id = getattr(request.state, "request_id", "-")
            response = JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content=error_payload(
                    code="rate_limit_exceeded",
                    message="Terlalu banyak request. Coba lagi beberapa saat.",
                    request_id=request_id,
                ),
            )
            response.headers["Retry-After"] = str(max(1, int(stats.reset_time - time.time())))

        response.headers["X-RateLimit-Limit"] = str(self.limit_item.amount)
        response.headers["X-RateLimit-Remaining"] = str(max(0, stats.remaining))
        response.headers["X-RateLimit-Reset"] = str(int(stats.reset_time))
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Small baseline of security headers for browser-facing deployments."""

    def __init__(self, app, *, hsts: bool = False) -> None:
        super().__init__(app)
        self.hsts = hsts

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "geolocation=(), microphone=(), camera=()"
        )
        if self.hsts:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Log one structured line per request with latency and request ID."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "request_failed",
                extra={
                    "request_id": getattr(request.state, "request_id", "-"),
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(elapsed_ms, 2),
                },
            )
            raise
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Process-Time"] = f"{elapsed_ms / 1000:.4f} sec"
        logger.info(
            "request_completed",
            extra={
                "request_id": getattr(request.state, "request_id", "-"),
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(elapsed_ms, 2),
            },
        )
        return response
