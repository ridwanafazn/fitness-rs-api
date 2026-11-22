"""Small crypto helpers for device tokens, OAuth state, and unsubscribe links."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from typing import Optional, Tuple

from cryptography.fernet import Fernet


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def encrypt_secret(value: str, key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    return Fernet(key.encode("utf-8")).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: Optional[str], key: Optional[str]) -> Optional[str]:
    if not value or not key:
        return None
    return Fernet(key.encode("utf-8")).decrypt(value.encode("ascii")).decode("utf-8")


def sign_state(
    *,
    user_id: uuid.UUID,
    provider: str,
    secret: str,
    ttl_seconds: int = 600,
) -> str:
    payload = {
        "u": str(user_id),
        "p": provider,
        "t": int(time.time()),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    signature = hmac.new(
        secret.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return base64.urlsafe_b64encode(f"{raw}.{signature}".encode()).decode("ascii")


def verify_state(
    state: str,
    *,
    secret: str,
    expected_provider: Optional[str] = None,
    ttl_seconds: int = 600,
) -> Tuple[uuid.UUID, str]:
    try:
        decoded = base64.urlsafe_b64decode(state.encode("ascii")).decode("utf-8")
        raw, signature = decoded.rsplit(".", 1)
        expected = hmac.new(
            secret.encode("utf-8"),
            raw.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("bad signature")
        payload = json.loads(raw)
        user_id = uuid.UUID(str(payload["u"]))
        provider = str(payload["p"])
        issued_at = int(payload["t"])
    except Exception as exc:
        raise ValueError("invalid state") from exc

    if expected_provider is not None and provider != expected_provider:
        raise ValueError("provider mismatch")
    if int(time.time()) - issued_at > ttl_seconds:
        raise ValueError("expired state")
    return user_id, provider


def sign_unsubscribe(user_id: uuid.UUID, secret: str) -> str:
    raw = str(user_id)
    signature = hmac.new(
        secret.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return base64.urlsafe_b64encode(f"{raw}.{signature}".encode()).decode("ascii")


def verify_unsubscribe(token: str, secret: str) -> uuid.UUID:
    try:
        decoded = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
        raw, signature = decoded.rsplit(".", 1)
        expected = hmac.new(
            secret.encode("utf-8"),
            raw.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("bad signature")
        return uuid.UUID(raw)
    except Exception as exc:
        raise ValueError("invalid unsubscribe token") from exc
