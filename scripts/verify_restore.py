"""Validate a restored database before switching traffic to it.

Usage:

    TARGET_DATABASE_URL=postgresql://... python scripts/verify_restore.py \
        --expect-head 0010_outbox_lease

Checks the Alembic head, required tables, and row counts on the target. This is
a verification helper, not a backup tool; see docs/p2-3-scale-and-reliability.md
for Neon PITR/branch restore steps.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from sqlalchemy import create_engine, inspect, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.url import normalize_database_url  # noqa: E402

REQUIRED_TABLES = (
    "users",
    "profiles",
    "consents",
    "plans",
    "plan_versions",
    "workout_sessions",
    "set_logs",
    "feedback",
    "unsafe_reports",
    "audit_log",
    "trainer_clients",
    "notification_outbox",
    "organizations",
    "research_events",
    "experiments",
    "research_versions",
    "quality_reviews",
)

COUNT_TABLES = ("users", "plans", "workout_sessions", "audit_log")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a restored database.")
    parser.add_argument(
        "--database-url",
        default=os.getenv("TARGET_DATABASE_URL") or os.getenv("DATABASE_URL"),
    )
    parser.add_argument("--expect-head", default=None)
    args = parser.parse_args()

    if not args.database_url:
        print("TARGET_DATABASE_URL/DATABASE_URL is not set.", file=sys.stderr)
        return 2

    url = normalize_database_url(args.database_url)
    assert url is not None
    connect_args: Dict[str, object] = {}
    if url.startswith("postgresql"):
        connect_args["connect_timeout"] = 5
    engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
    errors: List[str] = []
    counts: Dict[str, Optional[int]] = {}
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        missing = [table for table in REQUIRED_TABLES if table not in tables]
        if missing:
            errors.append("missing_tables:" + ",".join(missing))

        head: Optional[str] = None
        if "alembic_version" in tables:
            with engine.connect() as connection:
                value = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
                head = str(value) if value is not None else None
        else:
            errors.append("missing_table:alembic_version")

        if args.expect_head and head != args.expect_head:
            errors.append(f"head_mismatch:expected={args.expect_head}:actual={head}")

        with engine.connect() as connection:
            for table in COUNT_TABLES:
                if table not in tables:
                    counts[table] = None
                    continue
                counts[table] = int(
                    connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                    or 0
                )
    finally:
        engine.dispose()

    result = {
        "status": "ok" if not errors else "failed",
        "migration_head": head if "head" in locals() else None,
        "expected_head": args.expect_head,
        "counts": counts,
        "errors": errors,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
