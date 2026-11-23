"""Print P2.3 operational status as JSON.

Example:

    DATABASE_URL=... python scripts/ops_status.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.db.session import dispose_database, init_database  # noqa: E402
from app.services.dataset import get_dataset  # noqa: E402
from app.services.ops import ops_status  # noqa: E402


def main() -> int:
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
        status = ops_status(
            session,
            settings=settings,
            dataset=get_dataset(settings.dataset_path),
        )
    finally:
        session.close()
        dispose_database(engine)

    print(json.dumps(status.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0 if status.status == "ok" and status.database == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
