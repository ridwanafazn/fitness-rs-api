"""Authentication and rate-limit helpers."""

from __future__ import annotations

import secrets
from typing import Optional

from fastapi import Request, Security
from fastapi.security import APIKeyHeader

from app.core.errors import UnauthorizedError

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_api_key(
    request: Request,
    api_key: Optional[str] = Security(api_key_header),
) -> None:
    """Optional API-key gate.

    The API is public when ``API_KEY`` is not configured (useful for demos).
    In production, set ``API_KEY`` and send ``X-API-Key`` from the client.
    """

    configured = getattr(request.app.state.settings, "api_key", None)
    if not configured:
        return
    if not api_key or not secrets.compare_digest(api_key, configured):
        raise UnauthorizedError()
