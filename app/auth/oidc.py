"""OIDC access-token validation.

The backend is provider-agnostic: it validates a bearer token against the
configured issuer/audience and either a JWKS endpoint (production) or a
symmetric secret (local/test mode only).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional

import jwt
from jwt import PyJWKClient
from jwt.exceptions import (
    InvalidTokenError,
    PyJWKClientConnectionError,
    PyJWKClientError,
)

from app.core.config import Settings
from app.core.errors import AuthNotConfiguredError, AuthUnavailableError, UnauthorizedError

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_BEARER_CHALLENGE = {"WWW-Authenticate": "Bearer"}


@dataclass(frozen=True)
class TokenClaims:
    subject: str
    issuer: str
    email: Optional[str]
    email_verified: bool
    display_name: Optional[str]
    raw: Dict[str, Any]


def _email_is_verified(payload: Dict[str, Any]) -> bool:
    claim = payload.get("email_verified", payload.get("emailVerified"))
    if claim is True:
        return True
    return isinstance(claim, str) and claim.strip().lower() == "true"


def _normalise_email(payload: Dict[str, Any]) -> Optional[str]:
    if not _email_is_verified(payload):
        return None
    email = payload.get("email")
    if not isinstance(email, str):
        return None
    cleaned = email.strip().lower()
    if len(cleaned) > 320 or not _EMAIL_RE.fullmatch(cleaned):
        return None
    return cleaned


def _normalise_display_name(payload: Dict[str, Any]) -> Optional[str]:
    value = payload.get("name") or payload.get("preferred_username")
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())
    if not cleaned:
        return None
    return cleaned[:100]


class TokenVerifier:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.dev_mode = settings.auth_dev_mode
        self.algorithms = ["HS256"] if self.dev_mode else settings.auth_algorithm_list
        self._jwks_client: Optional[PyJWKClient] = None

        if self.dev_mode:
            if not settings.auth_dev_secret_value:
                raise AuthNotConfiguredError("AUTH_DEV_SECRET belum diatur.")
            return

        if not settings.auth_jwks_url or not settings.auth_issuer or not settings.auth_audience:
            raise AuthNotConfiguredError("Konfigurasi OIDC belum lengkap.")

        self._jwks_client = PyJWKClient(
            settings.auth_jwks_url,
            cache_keys=True,
            lifespan=settings.auth_jwks_cache_seconds,
            timeout=5,
        )

    def _decode_key(self, token: str) -> Any:
        if self.dev_mode:
            return self.settings.auth_dev_secret_value
        assert self._jwks_client is not None
        return self._jwks_client.get_signing_key_from_jwt(token).key

    def verify(self, token: str) -> TokenClaims:
        if not token or not token.strip():
            raise UnauthorizedError("Token akses tidak dikirim.", headers=_BEARER_CHALLENGE)

        try:
            key = self._decode_key(token)
            payload = jwt.decode(
                token,
                key,
                algorithms=self.algorithms,
                audience=self.settings.auth_audience,
                issuer=self.settings.auth_issuer,
                leeway=self.settings.auth_leeway_seconds,
                options={"require": ["exp", "sub", "iss", "aud"]},
            )
        except PyJWKClientConnectionError as exc:
            logger.warning("jwks_connection_failed", extra={"reason": type(exc).__name__})
            raise AuthUnavailableError() from exc
        except PyJWKClientError as exc:
            logger.warning("jwks_lookup_failed", extra={"reason": type(exc).__name__})
            raise UnauthorizedError(
                "Token akses tidak valid.",
                headers=_BEARER_CHALLENGE,
            ) from exc
        except InvalidTokenError as exc:
            logger.warning("token_validation_failed", extra={"reason": type(exc).__name__})
            raise UnauthorizedError(
                "Token akses tidak valid atau sudah kedaluwarsa.",
                headers=_BEARER_CHALLENGE,
            ) from exc

        subject = payload.get("sub")
        issuer = payload.get("iss")
        if not isinstance(subject, str) or not subject.strip():
            raise UnauthorizedError("Token tidak memiliki subject.", headers=_BEARER_CHALLENGE)
        if not isinstance(issuer, str) or not issuer.strip():
            raise UnauthorizedError("Token tidak memiliki issuer.", headers=_BEARER_CHALLENGE)
        subject = subject.strip()
        issuer = issuer.strip()
        if len(subject) > 255 or len(issuer) > 255:
            raise UnauthorizedError("Klaim identitas token tidak valid.", headers=_BEARER_CHALLENGE)

        return TokenClaims(
            subject=subject,
            issuer=issuer,
            email=_normalise_email(payload),
            email_verified=_email_is_verified(payload),
            display_name=_normalise_display_name(payload),
            raw=payload,
        )
