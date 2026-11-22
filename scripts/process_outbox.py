"""Process due workout reminders and the notification outbox.

Examples:

    DATABASE_URL=... python scripts/process_outbox.py --limit 100
    DATABASE_URL=... python scripts/process_outbox.py --no-reminders
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.db.session import dispose_database, init_database  # noqa: E402
from app.services.notifications import (  # noqa: E402
    enqueue_due_reminders,
    process_outbox,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Process notifications.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--no-reminders", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 2
    if not settings.notifications_enabled:
        print("NOTIFICATIONS_ENABLED is false.", file=sys.stderr)
        return 2

    engine, session_factory = init_database(settings)
    if engine is None or session_factory is None:
        print("Database is not configured.", file=sys.stderr)
        return 2

    session = session_factory()
    try:
        enqueued = 0
        if not args.no_reminders:
            enqueued = enqueue_due_reminders(session)
        result = process_outbox(
            session,
            mode=settings.notification_delivery_mode,
            webhook_url=settings.notification_webhook_url,
            limit=min(max(args.limit, 1), 200),
        )
    finally:
        session.close()
        dispose_database(engine)

    print(
        "enqueued={enqueued} processed={processed} sent={sent} retry={retry} failed={failed}".format(
            enqueued=enqueued,
            **result,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
