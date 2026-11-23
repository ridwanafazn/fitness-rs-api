"""P2.3 operational status aggregation."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Dict, Optional

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.redis import is_redis_uri, redis_is_ready
from app.db.models import NotificationOutbox
from app.schemas.ops import OpsStatusOut, OutboxStatusOut
from app.services.dataset import Dataset


def utcnow() -> datetime:
    return datetime.now(UTC)


def migration_head(session: Session) -> Optional[str]:
    try:
        value = session.scalar(text("SELECT version_num FROM alembic_version"))
        return str(value) if value is not None else None
    except Exception:
        session.rollback()
        return None


def outbox_status(session: Session) -> OutboxStatusOut:
    now = utcnow()
    try:
        rows = session.execute(
            select(NotificationOutbox.status, func.count(NotificationOutbox.id))
            .group_by(NotificationOutbox.status)
        ).all()
        counts: Dict[str, int] = {
            "pending": 0,
            "failed": 0,
            "sent": 0,
            "cancelled": 0,
        }
        for status_value, total in rows:
            counts[str(status_value)] = int(total or 0)

        due_filter = (
            NotificationOutbox.status.in_(("pending", "failed")),
            NotificationOutbox.attempts < NotificationOutbox.max_attempts,
            NotificationOutbox.scheduled_at <= now,
            or_(
                NotificationOutbox.locked_until.is_(None),
                NotificationOutbox.locked_until < now,
            ),
        )
        due_pending = int(
            session.scalar(
                select(func.count(NotificationOutbox.id)).where(*due_filter)
            )
            or 0
        )
        oldest_due = session.scalar(
            select(func.min(NotificationOutbox.scheduled_at)).where(*due_filter)
        )
        last_sent = session.scalar(select(func.max(NotificationOutbox.sent_at)))
        return OutboxStatusOut(
            pending=counts.get("pending", 0),
            failed=counts.get("failed", 0),
            sent=counts.get("sent", 0),
            cancelled=counts.get("cancelled", 0),
            due_pending=due_pending,
            oldest_due_at=oldest_due,
            last_sent_at=last_sent,
        )
    except Exception:
        session.rollback()
        return OutboxStatusOut()


def ops_status(
    session: Session,
    *,
    settings: Settings,
    dataset: Dataset,
) -> OpsStatusOut:
    database = "ok"
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        session.rollback()
        database = "unavailable"

    redis_status, redis_detail = (
        redis_is_ready(settings.rate_limit_storage_uri)
        if settings.rate_limit_enabled
        else ("not_configured", None)
    )
    outbox = outbox_status(session) if database == "ok" else OutboxStatusOut()
    head = migration_head(session) if database == "ok" else None
    degraded = database != "ok" or redis_status == "unavailable"

    return OpsStatusOut(
        status="degraded" if degraded else "ok",
        environment=settings.environment,
        app_version=settings.app_version,
        generated_at=utcnow(),
        dataset_version=dataset.version,
        dataset_size=len(dataset.exercises),
        database=database,
        migration_head=head,
        redis=redis_status,
        redis_detail=redis_detail,
        rate_limit="redis" if is_redis_uri(settings.rate_limit_storage_uri) else "memory",
        rate_limit_fail_open=settings.rate_limit_fail_open,
        outbox=outbox,
    )
