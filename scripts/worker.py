"""Long-running notification worker.

Examples:

    DATABASE_URL=... python scripts/worker.py
    DATABASE_URL=... python scripts/worker.py --once --no-reminders
    DATABASE_URL=... python scripts/worker.py --interval 60 --limit 100
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time
from pathlib import Path
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.db.session import dispose_database, init_database  # noqa: E402
from app.services.notifications import (  # noqa: E402
    enqueue_due_reminders,
    process_outbox,
)


def run_cycle(
    session_factory,
    *,
    mode: str,
    webhook_url: Optional[str],
    limit: int,
    include_reminders: bool,
    worker_id: str,
    lease_seconds: int,
) -> Dict[str, int]:
    session = session_factory()
    try:
        enqueued = enqueue_due_reminders(session) if include_reminders else 0
        result = process_outbox(
            session,
            mode=mode,
            webhook_url=webhook_url,
            limit=limit,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
        )
        result["enqueued"] = enqueued
        return result
    finally:
        session.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the notification worker.")
    parser.add_argument("--interval", type=int, default=30, help="Seconds between cycles.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--no-reminders", action="store_true")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit.")
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--lease-seconds", type=int, default=None)
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

    worker_id = (args.worker_id or f"worker-{os.getpid()}")[:64]
    lease_seconds = (
        args.lease_seconds
        if args.lease_seconds is not None
        else settings.notification_outbox_lease_seconds
    )
    interval = max(5, args.interval)
    stopping = False

    def _stop(signum, frame) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, _stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _stop)

    print(
        f"worker_started id={worker_id} interval={interval}s "
        f"mode={settings.notification_delivery_mode}",
        flush=True,
    )
    try:
        while not stopping:
            try:
                result = run_cycle(
                    session_factory,
                    mode=settings.notification_delivery_mode,
                    webhook_url=settings.notification_webhook_url,
                    limit=min(max(args.limit, 1), 200),
                    include_reminders=not args.no_reminders,
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                )
                print(
                    "worker_cycle "
                    f"enqueued={result['enqueued']} processed={result['processed']} "
                    f"sent={result['sent']} retry={result['retry']} "
                    f"failed={result['failed']}",
                    flush=True,
                )
            except Exception as exc:
                print(
                    f"worker_cycle_failed {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
            if args.once:
                break
            deadline = time.monotonic() + interval
            while not stopping and time.monotonic() < deadline:
                time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
    finally:
        dispose_database(engine)
        print("worker_stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
