"""Mint a local/test OIDC bearer token.

This refuses to run unless ``AUTH_DEV_MODE=true``. It is a developer
convenience, never a production authentication path.

Example:

    AUTH_DEV_MODE=true AUTH_DEV_SECRET=... AUTH_ISSUER=https://dev.local \
    AUTH_AUDIENCE=jymz-dev python scripts/mint_dev_token.py --sub dev-user
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Mint a dev-only bearer token.")
    parser.add_argument("--sub", default="dev-user")
    parser.add_argument("--email", default=None)
    parser.add_argument("--minutes", type=int, default=60)
    args = parser.parse_args()

    settings = get_settings()
    if not settings.auth_dev_mode:
        print("AUTH_DEV_MODE=false; refusing to mint a token.", file=sys.stderr)
        return 2

    secret = settings.auth_dev_secret_value
    if not secret or not settings.auth_issuer or not settings.auth_audience:
        print("AUTH_DEV_SECRET, AUTH_ISSUER, and AUTH_AUDIENCE are required.", file=sys.stderr)
        return 2

    now = datetime.now(UTC)
    payload = {
        "sub": args.sub,
        "iss": settings.auth_issuer,
        "aud": settings.auth_audience,
        "iat": now,
        "exp": now + timedelta(minutes=max(1, args.minutes)),
    }
    if args.email:
        payload["email"] = args.email
        payload["email_verified"] = True

    print(jwt.encode(payload, secret, algorithm="HS256"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
