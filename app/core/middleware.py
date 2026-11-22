"""HTTP middleware: request IDs, body-size guard, access logging."""

from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Callable

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.errors import error_payload

logger = logging.getLogger("fitness_api.access")


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a request ID to every request and response."""

    _VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        candidate = request.headers.get("X-Request-ID", "")
        request_id = (
            candidate if self._VALID_ID.fullmatch(candidate) else uuid.uuid4().hex
        )
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
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content=error_payload(
                        code="request_too_large",
                        message=f"Body request melebihi batas {self.max_bytes} byte.",
                        request_id=request_id,
                    ),
                )
        return await call_next(request)


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
