"""P1.3 provider integrations (Strava first)."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.crypto import encrypt_secret, sign_state, verify_state
from app.core.errors import (
    IntegrationExchangeError,
    IntegrationNotConfiguredError,
    IntegrationStateError,
    IntegrationUnsupportedError,
)
from app.db.models import IntegrationToken
from app.schemas.notifications import (
    IntegrationAuthorizeResponse,
    IntegrationOut,
)
from app.services.audit import record_audit
from app.services.identity import commit_or_conflict

STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_SCOPES = "read,activity:read_all"


def _state_secret(settings: Settings) -> Optional[str]:
    return settings.integration_state_secret or settings.token_encryption_key


def _require_strava_config(settings: Settings) -> str:
    secret = _state_secret(settings)
    if (
        not settings.strava_client_id
        or not settings.strava_client_secret
        or not settings.strava_redirect_uri
        or not secret
        or not settings.token_encryption_key
    ):
        raise IntegrationNotConfiguredError(
            "Strava belum dikonfigurasi pada server."
        )
    return secret


def authorize_url(
    *,
    user_id: uuid.UUID,
    provider: str,
    settings: Settings,
) -> IntegrationAuthorizeResponse:
    if provider == "google_fit" or provider == "apple_health":
        raise IntegrationUnsupportedError(
            "Provider ini belum tersedia; gunakan Strava.",
            details={"provider": provider},
        )
    if provider != "strava":
        raise IntegrationUnsupportedError(
            "Provider integrasi tidak didukung.",
            details={"provider": provider},
        )

    secret = _require_strava_config(settings)
    state = sign_state(
        user_id=user_id,
        provider=provider,
        secret=secret,
    )
    query = urllib.parse.urlencode(
        {
            "client_id": settings.strava_client_id,
            "redirect_uri": settings.strava_redirect_uri,
            "response_type": "code",
            "approval_prompt": "force",
            "scope": STRAVA_SCOPES,
            "state": state,
        }
    )
    return IntegrationAuthorizeResponse(
        provider=provider,
        authorize_url=f"{STRAVA_AUTHORIZE_URL}?{query}",
        state=state,
    )


def state_user_id(state: str, provider: str, settings: Settings) -> uuid.UUID:
    secret = _require_strava_config(settings)
    try:
        user_id, state_provider = verify_state(
            state,
            secret=secret,
            expected_provider=provider,
        )
    except ValueError as exc:
        raise IntegrationStateError() from exc
    if state_provider != provider:
        raise IntegrationStateError()
    return user_id


def _exchange_strava_code(code: str, settings: Settings) -> Dict[str, Any]:
    payload = urllib.parse.urlencode(
        {
            "client_id": settings.strava_client_id,
            "client_secret": settings.strava_client_secret,
            "code": code,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        STRAVA_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise IntegrationExchangeError() from exc


def serialize_integration(token: IntegrationToken) -> IntegrationOut:
    return IntegrationOut(
        provider=token.provider,
        status=token.status,
        scopes=list(token.scopes or []),
        expires_at=token.expires_at,
        connected_at=token.created_at,
    )


def list_integrations(
    session: Session,
    *,
    user_id: uuid.UUID,
) -> List[IntegrationOut]:
    tokens = list(
        session.scalars(
            select(IntegrationToken)
            .where(
                IntegrationToken.owner_user_id == user_id,
                IntegrationToken.status == "active",
            )
            .order_by(IntegrationToken.created_at.desc())
        ).all()
    )
    return [serialize_integration(token) for token in tokens]


def _encrypt_token(value: Optional[str], key: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return encrypt_secret(value, key)
    except ValueError as exc:
        raise IntegrationNotConfiguredError(
            "TOKEN_ENCRYPTION_KEY tidak valid."
        ) from exc


def handle_callback(
    session: Session,
    *,
    user_id: uuid.UUID,
    provider: str,
    code: str,
    state: str,
    settings: Settings,
    actor_role: str,
) -> IntegrationOut:
    if provider == "google_fit" or provider == "apple_health":
        raise IntegrationUnsupportedError(
            "Provider ini belum tersedia; gunakan Strava.",
            details={"provider": provider},
        )
    if provider != "strava":
        raise IntegrationUnsupportedError(
            "Provider integrasi tidak didukung.",
            details={"provider": provider},
        )

    secret = _require_strava_config(settings)
    try:
        state_user_id, state_provider = verify_state(
            state,
            secret=secret,
            expected_provider=provider,
        )
    except ValueError as exc:
        raise IntegrationStateError() from exc
    if state_user_id != user_id:
        raise IntegrationStateError()

    result = _exchange_strava_code(code, settings)
    access_token = result.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise IntegrationExchangeError("Access token Strava tidak diterima.")

    refresh_token = result.get("refresh_token")
    expires_at_epoch = result.get("expires_at")
    expires_at = (
        datetime.fromtimestamp(int(expires_at_epoch), tz=UTC)
        if expires_at_epoch
        else None
    )
    athlete = result.get("athlete") or {}
    external_user_id = str(athlete.get("id")) if athlete.get("id") else None
    scope_value = result.get("scope")
    scopes = (
        [item.strip() for item in scope_value.split(",") if item.strip()]
        if isinstance(scope_value, str)
        else STRAVA_SCOPES.split(",")
    )

    integration = session.scalar(
        select(IntegrationToken).where(
            IntegrationToken.owner_user_id == user_id,
            IntegrationToken.provider == provider,
        )
    )
    if integration is None:
        integration = IntegrationToken(
            owner_user_id=user_id,
            provider=provider,
        )
        session.add(integration)
    integration.external_user_id = external_user_id
    integration.access_token_ciphertext = _encrypt_token(
        access_token, settings.token_encryption_key
    )
    integration.refresh_token_ciphertext = _encrypt_token(
        str(refresh_token) if refresh_token else None,
        settings.token_encryption_key,
    )
    integration.scopes = scopes
    integration.expires_at = expires_at
    integration.status = "active"
    integration.updated_at = datetime.now(UTC)
    session.flush()

    record_audit(
        session,
        actor_user_id=user_id,
        actor_role=actor_role,
        action="integration.connected",
        resource_type="integration_token",
        resource_id=str(integration.id),
        metadata={"provider": provider, "scopes": scopes},
    )
    commit_or_conflict(session)
    return serialize_integration(integration)


def disconnect_integration(
    session: Session,
    *,
    user_id: uuid.UUID,
    provider: str,
    actor_role: str,
) -> None:
    integration = session.scalar(
        select(IntegrationToken).where(
            IntegrationToken.owner_user_id == user_id,
            IntegrationToken.provider == provider,
        )
    )
    if integration is None:
        raise IntegrationUnsupportedError(
            "Integrasi tidak ditemukan.",
            details={"provider": provider},
        )
    integration.status = "revoked"
    integration.access_token_ciphertext = None
    integration.refresh_token_ciphertext = None
    integration.updated_at = datetime.now(UTC)
    record_audit(
        session,
        actor_user_id=user_id,
        actor_role=actor_role,
        action="integration.disconnected",
        resource_type="integration_token",
        resource_id=str(integration.id),
        metadata={"provider": provider},
    )
    commit_or_conflict(session)
