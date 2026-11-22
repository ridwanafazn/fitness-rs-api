"""FastAPI application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.api import api_router
from app.core.config import Settings, get_settings
from app.core.errors import (
    AppError,
    error_payload,
    validation_details,
)
from app.core.logging import configure_logging
from app.core.middleware import (
    AccessLogMiddleware,
    MaxBodySizeMiddleware,
    RateLimitMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
)
from app.services.dataset import clear_dataset_cache, get_dataset

logger = logging.getLogger("fitness_api")


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "-")
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(
                code=exc.code,
                message=exc.message,
                request_id=request_id,
                details=exc.details,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "-")
        details = validation_details(exc.errors())
        payload = error_payload(
            code="validation_error",
            message="Payload request tidak valid.",
            request_id=request_id,
            details=details,
        )
        # Old clients read ``detail``; keep the key populated for them.
        payload["detail"] = details
        return JSONResponse(status_code=422, content=payload)

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "-")
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(
                code="http_error",
                message=str(exc.detail),
                request_id=request_id,
            ),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "-")
        logger.exception(
            "unhandled_exception",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
            },
        )
        return JSONResponse(
            status_code=500,
            content=error_payload(
                code="internal_error",
                message="Terjadi kesalahan internal. Silakan coba lagi.",
                request_id=request_id,
            ),
        )


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    """Create a configured FastAPI application.

    ``settings`` is injectable so tests can use a temporary dataset without
    mutating process-global environment variables.
    """

    app_settings = settings or get_settings()
    configure_logging(app_settings.log_level, json_format=not app_settings.is_test)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        clear_dataset_cache()
        dataset = get_dataset(app_settings.dataset_path)
        app.state.dataset = dataset
        logger.info(
            "startup",
            extra={
                "environment": app_settings.environment,
                "dataset_version": dataset.version,
                "dataset_size": len(dataset.exercises),
                "version": app_settings.app_version,
            },
        )
        yield
        logger.info("shutdown")

    docs_enabled = app_settings.docs_enabled
    app = FastAPI(
        title=app_settings.app_name,
        description=(
            "Hybrid fitness recommender: deterministic rule table + genetic "
            "algorithm, with hard injury constraints."
        ),
        version=app_settings.app_version,
        contact={"name": "Ridwan Ahmad Fauzan", "url": "https://github.com/ridwanafazn"},
        lifespan=lifespan,
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )

    app.state.settings = app_settings

    # Starlette treats the last-added middleware as the outermost layer.
    # Desired order (outermost -> innermost):
    # CORS -> security headers -> RequestID -> AccessLog -> rate limit ->
    # body size -> trusted host -> gzip -> app.
    app.add_middleware(GZipMiddleware, minimum_size=500)

    if app_settings.allowed_host_list != ["*"]:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=app_settings.allowed_host_list,
        )

    app.add_middleware(MaxBodySizeMiddleware, max_bytes=app_settings.max_request_bytes)

    app.add_middleware(
        RateLimitMiddleware,
        enabled=app_settings.rate_limit_enabled,
        limit=app_settings.rate_limit,
        storage_uri=app_settings.rate_limit_storage_uri,
        trust_proxy_headers=app_settings.trust_proxy_headers,
    )

    app.add_middleware(AccessLogMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(
        SecurityHeadersMiddleware,
        hsts=app_settings.is_production,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
        expose_headers=[
            "X-Process-Time",
            "X-Request-ID",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
        ],
        max_age=600,
    )

    _register_exception_handlers(app)
    app.include_router(api_router, prefix=app_settings.api_prefix)

    @app.get("/", tags=["infra"], include_in_schema=False)
    def root() -> dict:
        return {
            "name": app_settings.app_name,
            "version": app_settings.app_version,
            "docs": "/docs" if docs_enabled else None,
            "health": "/health",
            "ready": "/ready",
        }

    @app.get("/health", tags=["infra"])
    def healthcheck() -> dict:
        return {
            "status": "ok",
            "version": app_settings.app_version,
            "environment": app_settings.environment,
        }

    @app.get("/ready", tags=["infra"])
    def readiness(request: Request) -> JSONResponse:
        dataset = getattr(request.app.state, "dataset", None)
        if dataset is None:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "reason": "dataset_not_loaded"},
            )
        return JSONResponse(
            status_code=200,
            content={
                "status": "ready",
                "dataset_version": dataset.version,
                "dataset_size": len(dataset.exercises),
            },
        )

    if app_settings.metrics_enabled:
        Instrumentator().instrument(app).expose(
            app,
            endpoint="/metrics",
            include_in_schema=False,
        )

    return app


app = create_app()
