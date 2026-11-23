"""P2.3 operational status schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_serializer


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class OutboxStatusOut(BaseModel):
    pending: int = 0
    failed: int = 0
    sent: int = 0
    cancelled: int = 0
    due_pending: int = 0
    oldest_due_at: Optional[datetime] = None
    last_sent_at: Optional[datetime] = None

    @field_serializer("oldest_due_at", "last_sent_at")
    def _serialize_timestamps(self, value: Optional[datetime]) -> Optional[datetime]:
        return None if value is None else _as_utc(value)


class OpsStatusOut(BaseModel):
    status: str
    environment: str
    app_version: str
    generated_at: datetime
    dataset_version: str
    dataset_size: int
    database: str
    migration_head: Optional[str] = None
    redis: str = "not_configured"
    redis_detail: Optional[str] = None
    rate_limit: str = "memory"
    rate_limit_fail_open: bool = True
    outbox: OutboxStatusOut = Field(default_factory=OutboxStatusOut)

    @field_serializer("generated_at")
    def _serialize_generated_at(self, value: datetime) -> datetime:
        return _as_utc(value)
