"""Rebuild P1.1 progress aggregates for one user or all users.

Example:

    DATABASE_URL=... python scripts/rebuild_progress.py --days 90
    DATABASE_URL=... python scripts/rebuild_progress.py --days 365 --user-id <uuid>
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.db.models import Profile, User  # noqa: E402
from app.db.session import dispose_database, init_database  # noqa: E402
from app.services.progress import refresh_progress  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild progress aggregates.")
    parser.add_argument("--days", type=int, default=90, help="Lookback window (1-3650).")
    parser.add_argument("--user-id", type=uuid.UUID, default=None)
    args = parser.parse_args()

    days = min(max(args.days, 1), 3650)
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 2

    engine, session_factory = init_database(settings)
    if engine is None or session_factory is None:
        print("Database is not configured.", file=sys.stderr)
        return 2

    session = session_factory()
    try:
        stmt = select(User).where(User.deleted_at.is_(None))
        if args.user_id is not None:
            stmt = stmt.where(User.id == args.user_id)
        users = list(session.scalars(stmt).all())
        if not users:
            print("No users found.")
            return 0

        for user in users:
            profile = session.get(Profile, user.id)
            timezone_name = profile.timezone if profile and profile.timezone else "UTC"
            try:
                tz = ZoneInfo(timezone_name)
            except (ZoneInfoNotFoundError, ValueError):
                timezone_name = "UTC"
                tz = ZoneInfo("UTC")
            today = datetime.now(tz).date()
            start = today - timedelta(days=days - 1)
            try:
                refresh_progress(
                    session,
                    owner_user_id=user.id,
                    from_date=start,
                    to_date=today,
                    timezone_name=timezone_name,
                )
            except Exception as exc:
                session.rollback()
                print(f"failed user={user.id}: {exc}", file=sys.stderr)
                continue
            print(f"rebuilt user={user.id} range={start}..{today} timezone={timezone_name}")
    finally:
        session.close()
        dispose_database(engine)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
