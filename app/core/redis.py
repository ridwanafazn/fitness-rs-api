"""Optional Redis health checks for rate limiting and operations."""

from __future__ import annotations

import logging
from typing import Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def is_redis_uri(uri: Optional[str]) -> bool:
    if not uri:
        return False
    parsed = urlparse(uri)
    return parsed.scheme in {"redis", "rediss"}


def redis_is_ready(uri: Optional[str]) -> Tuple[str, Optional[str]]:
    """Return ``(status, detail)`` without raising.

    Status is ``not_configured`` for memory/non-Redis backends, ``ok`` when a
    PING succeeds, and ``unavailable`` when the client or server fails.
    """

    if not is_redis_uri(uri):
        return "not_configured", None
    assert uri is not None
    try:
        import redis
    except ImportError:
        return "unavailable", "redis_client_missing"
    try:
        client = redis.Redis.from_url(
            uri,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        client.ping()
        return "ok", None
    except Exception as exc:  # pragma: no cover - depends on external Redis
        logger.warning("redis_readiness_check_failed", exc_info=True)
        return "unavailable", type(exc).__name__
