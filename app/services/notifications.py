"""P1.3 notification preferences, devices, outbox, and calendar."""

from __future__ import annotations

import json
import logging
import os
import secrets
import urllib.request
import uuid
from datetime import UTC, datetime, time, timedelta
from typing import Dict, List, Mapping, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.crypto import (
    encrypt_secret,
    hash_secret,
    sign_unsubscribe,
    verify_unsubscribe,
)
from app.core.errors import (
    CalendarNotFoundError,
    DeviceNotFoundError,
    NotificationValidationError,
)
from app.db.models import (
    Device,
    NotificationOutbox,
    NotificationPreference,
    Plan,
)
from app.schemas.notifications import (
    CalendarTokenResponse,
    DeviceCreate,
    DeviceOut,
    NotificationPreferencesOut,
    NotificationPreferencesUpdate,
    OutboxOut,
)
from app.services.audit import record_audit
from app.services.identity import commit_or_conflict
from app.services.plans import calendar_ics_for_plan

logger = logging.getLogger(__name__)

CHANNELS = ("email", "push", "whatsapp")
EMPTY_CALENDAR = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//JYMZ//Training Plan//EN\r\n"
    "CALSCALE:GREGORIAN\r\n"
    "METHOD:PUBLISH\r\n"
    "END:VCALENDAR\r\n"
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def ensure_preferences(session: Session, user_id: uuid.UUID) -> NotificationPreference:
    prefs = session.scalar(
        select(NotificationPreference).where(
            NotificationPreference.owner_user_id == user_id
        )
    )
    if prefs is None:
        prefs = NotificationPreference(owner_user_id=user_id)
        session.add(prefs)
        session.flush()
    return prefs


def preferences_out(prefs: NotificationPreference) -> NotificationPreferencesOut:
    return NotificationPreferencesOut(
        email_enabled=prefs.email_enabled,
        push_enabled=prefs.push_enabled,
        whatsapp_enabled=prefs.whatsapp_enabled,
        reminder_enabled=prefs.reminder_enabled,
        reminder_time=prefs.reminder_time,
        timezone=prefs.timezone,
        quiet_hours_start=prefs.quiet_hours_start,
        quiet_hours_end=prefs.quiet_hours_end,
        weekly_review_enabled=prefs.weekly_review_enabled,
        calendar_connected=prefs.calendar_token_hash is not None,
    )


def get_preferences(session: Session, user_id: uuid.UUID) -> NotificationPreference:
    prefs = ensure_preferences(session, user_id)
    commit_or_conflict(session)
    return prefs


def update_preferences(
    session: Session,
    *,
    user_id: uuid.UUID,
    payload: NotificationPreferencesUpdate,
    actor_role: str,
) -> NotificationPreference:
    prefs = ensure_preferences(session, user_id)
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(prefs, field, value)

    channels = [
        prefs.email_enabled,
        prefs.push_enabled,
        prefs.whatsapp_enabled,
    ]
    if prefs.reminder_enabled and not any(channels):
        raise NotificationValidationError(
            "Aktifkan minimal satu channel sebelum mengaktifkan reminder."
        )
    prefs.updated_at = utcnow()
    session.flush()

    record_audit(
        session,
        actor_user_id=user_id,
        actor_role=actor_role,
        action="notification.preferences_updated",
        resource_type="notification_preferences",
        resource_id=str(prefs.id),
        metadata={"fields": sorted(data)},
    )
    commit_or_conflict(session)
    return prefs


def _channels(prefs: NotificationPreference) -> List[str]:
    result = []
    if prefs.email_enabled:
        result.append("email")
    if prefs.push_enabled:
        result.append("push")
    if prefs.whatsapp_enabled:
        result.append("whatsapp")
    return result


def _in_quiet_hours(local_time: time, start: Optional[str], end: Optional[str]) -> bool:
    if not start or not end:
        return False
    start_time = time.fromisoformat(start)
    end_time = time.fromisoformat(end)
    if start_time <= end_time:
        return start_time <= local_time < end_time
    return local_time >= start_time or local_time < end_time


def register_device(
    session: Session,
    *,
    user_id: uuid.UUID,
    payload: DeviceCreate,
    encryption_key: Optional[str],
    actor_role: str,
) -> Device:
    token_hash = hash_secret(payload.token)
    device = session.scalar(
        select(Device).where(
            Device.owner_user_id == user_id,
            Device.token_hash == token_hash,
        )
    )
    try:
        ciphertext = encrypt_secret(payload.token, encryption_key)
    except ValueError as exc:
        raise NotificationValidationError(
            "TOKEN_ENCRYPTION_KEY tidak valid."
        ) from exc

    if device is None:
        device = Device(
            owner_user_id=user_id,
            platform=payload.platform,
            device_name=payload.device_name,
            token_hash=token_hash,
            token_ciphertext=ciphertext,
        )
        session.add(device)
    else:
        device.platform = payload.platform
        device.device_name = payload.device_name
        device.token_ciphertext = ciphertext
    device.last_seen_at = utcnow()
    session.flush()

    record_audit(
        session,
        actor_user_id=user_id,
        actor_role=actor_role,
        action="notification.device_registered",
        resource_type="device",
        resource_id=str(device.id),
        metadata={"platform": payload.platform},
    )
    commit_or_conflict(session)
    return device


def device_out(device: Device) -> DeviceOut:
    return DeviceOut(
        id=device.id,
        platform=device.platform,
        device_name=device.device_name,
        has_token=device.token_ciphertext is not None,
        last_seen_at=device.last_seen_at,
        created_at=device.created_at,
    )


def list_devices(session: Session, user_id: uuid.UUID) -> List[Device]:
    return list(
        session.scalars(
            select(Device)
            .where(Device.owner_user_id == user_id)
            .order_by(Device.created_at.desc())
        ).all()
    )


def delete_device(
    session: Session,
    *,
    user_id: uuid.UUID,
    device_id: uuid.UUID,
    actor_role: str,
) -> None:
    device = session.scalar(
        select(Device).where(
            Device.id == device_id,
            Device.owner_user_id == user_id,
        )
    )
    if device is None:
        raise DeviceNotFoundError()
    session.delete(device)
    record_audit(
        session,
        actor_user_id=user_id,
        actor_role=actor_role,
        action="notification.device_deleted",
        resource_type="device",
        resource_id=str(device.id),
        metadata={},
    )
    commit_or_conflict(session)


def enqueue_notification(
    session: Session,
    *,
    owner_user_id: uuid.UUID,
    channel: str,
    template: str,
    payload: Mapping[str, object],
    scheduled_at: Optional[datetime] = None,
    idempotency_key: Optional[str] = None,
    max_attempts: int = 3,
) -> NotificationOutbox:
    key = idempotency_key or f"{template}:{uuid.uuid4()}"
    existing = session.scalar(
        select(NotificationOutbox).where(
            NotificationOutbox.idempotency_key == key
        )
    )
    if existing is not None:
        return existing
    item = NotificationOutbox(
        owner_user_id=owner_user_id,
        channel=channel,
        template=template,
        payload=dict(payload),
        scheduled_at=scheduled_at or utcnow(),
        status="pending",
        max_attempts=max_attempts,
        idempotency_key=key[:128],
    )
    session.add(item)
    session.flush()
    return item


def outbox_out(item: NotificationOutbox) -> OutboxOut:
    return OutboxOut(
        id=item.id,
        channel=item.channel,
        template=item.template,
        status=item.status,
        scheduled_at=item.scheduled_at,
        attempts=item.attempts,
        max_attempts=item.max_attempts,
    )


def enqueue_test_notification(
    session: Session,
    *,
    user_id: uuid.UUID,
    channel: str,
    template: str,
    actor_role: str,
) -> NotificationOutbox:
    prefs = ensure_preferences(session, user_id)
    if channel not in _channels(prefs):
        raise NotificationValidationError(
            f"Channel {channel} belum diaktifkan.",
            details={"channel": channel},
        )
    item = enqueue_notification(
        session,
        owner_user_id=user_id,
        channel=channel,
        template=template,
        payload={"type": "test"},
        idempotency_key=f"test:{user_id}:{uuid.uuid4()}",
    )
    record_audit(
        session,
        actor_user_id=user_id,
        actor_role=actor_role,
        action="notification.test_enqueued",
        resource_type="notification_outbox",
        resource_id=str(item.id),
        metadata={"channel": channel},
    )
    commit_or_conflict(session)
    return item


def _latest_plan(session: Session, user_id: uuid.UUID) -> Optional[Plan]:
    return session.scalar(
        select(Plan)
        .where(Plan.owner_user_id == user_id, Plan.deleted_at.is_(None))
        .order_by(Plan.created_at.desc())
        .limit(1)
    )


def enqueue_due_reminders(session: Session) -> int:
    now = utcnow()
    enqueued = 0
    preferences = list(
        session.scalars(
            select(NotificationPreference).where(
                (NotificationPreference.reminder_enabled.is_(True))
                | (NotificationPreference.weekly_review_enabled.is_(True))
            )
        ).all()
    )

    for prefs in preferences:
        try:
            tz = ZoneInfo(prefs.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            continue
        local_now = now.astimezone(tz)
        local_time = local_now.time().replace(second=0, microsecond=0)
        if _in_quiet_hours(
            local_time,
            prefs.quiet_hours_start,
            prefs.quiet_hours_end,
        ):
            continue
        reminder_at = time.fromisoformat(prefs.reminder_time)
        if prefs.reminder_enabled and local_time >= reminder_at:
            plan = _latest_plan(session, prefs.owner_user_id)
            payload = {
                "type": "workout_reminder",
                "local_date": str(local_now.date()),
                "plan_id": str(plan.id) if plan else None,
            }
            for channel in _channels(prefs):
                enqueue_notification(
                    session,
                    owner_user_id=prefs.owner_user_id,
                    channel=channel,
                    template="workout_reminder",
                    payload=payload,
                    idempotency_key=(
                        f"reminder:{prefs.owner_user_id}:{local_now.date()}:{channel}"
                    ),
                )
                enqueued += 1

        if prefs.weekly_review_enabled and local_now.weekday() == 0:
            week_start = local_now.date() - timedelta(days=local_now.weekday())
            payload = {
                "type": "weekly_review",
                "week_start": str(week_start),
            }
            for channel in _channels(prefs):
                enqueue_notification(
                    session,
                    owner_user_id=prefs.owner_user_id,
                    channel=channel,
                    template="weekly_review",
                    payload=payload,
                    idempotency_key=(
                        f"weekly_review:{prefs.owner_user_id}:{week_start}:{channel}"
                    ),
                )
                enqueued += 1

    commit_or_conflict(session)
    return enqueued


def _deliver(item: NotificationOutbox, *, mode: str, webhook_url: Optional[str]) -> None:
    if mode == "log":
        logger.info(
            "notification_delivery",
            extra={
                "outbox_id": str(item.id),
                "owner_user_id": str(item.owner_user_id),
                "channel": item.channel,
                "template": item.template,
            },
        )
        return
    if mode == "webhook":
        if not webhook_url:
            raise RuntimeError("NOTIFICATION_WEBHOOK_URL belum diatur")
        payload = {
            "id": str(item.id),
            "channel": item.channel,
            "template": item.template,
            "payload": item.payload,
            "idempotency_key": item.idempotency_key,
        }
        request = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=5):
            return
    raise RuntimeError("mode pengiriman notifikasi tidak aktif")


def default_worker_id() -> str:
    return f"{os.getpid()}-{uuid.uuid4().hex[:8]}"


def process_outbox(
    session: Session,
    *,
    mode: str,
    webhook_url: Optional[str],
    limit: int = 50,
    worker_id: Optional[str] = None,
    lease_seconds: int = 300,
) -> Dict[str, int]:
    if mode == "disabled":
        return {"processed": 0, "sent": 0, "retry": 0, "failed": 0}

    now = utcnow()
    lease_seconds = min(max(int(lease_seconds), 30), 3600)
    worker = (worker_id or default_worker_id())[:64]
    claim_stmt = (
        select(NotificationOutbox)
        .where(
            NotificationOutbox.status.in_(("pending", "failed")),
            NotificationOutbox.attempts < NotificationOutbox.max_attempts,
            NotificationOutbox.scheduled_at <= now,
            or_(
                NotificationOutbox.locked_until.is_(None),
                NotificationOutbox.locked_until < now,
            ),
        )
        .order_by(NotificationOutbox.scheduled_at)
        .limit(min(max(limit, 1), 200))
    )
    if session.get_bind().dialect.name == "postgresql":
        claim_stmt = claim_stmt.with_for_update(skip_locked=True)

    items = list(session.scalars(claim_stmt).all())
    if not items:
        return {"processed": 0, "sent": 0, "retry": 0, "failed": 0}

    lock_until = now + timedelta(seconds=lease_seconds)
    for item in items:
        item.locked_until = lock_until
        item.locked_by = worker
    # Make the lease visible before delivery so another worker can skip these
    # rows. A crash after this point is recovered when the lease expires.
    session.commit()

    sent = 0
    retry = 0
    failed = 0

    for item in items:
        try:
            _deliver(item, mode=mode, webhook_url=webhook_url)
            item.status = "sent"
            item.sent_at = utcnow()
            item.last_error = None
            sent += 1
        except Exception as exc:
            item.attempts += 1
            item.last_error = f"{type(exc).__name__}: delivery failed"
            if item.attempts >= item.max_attempts:
                item.status = "failed"
                failed += 1
            else:
                item.status = "pending"
                item.scheduled_at = utcnow() + timedelta(
                    minutes=min(60, 2**item.attempts)
                )
                retry += 1
        finally:
            item.locked_until = None
            item.locked_by = None
        item.updated_at = utcnow()

    commit_or_conflict(session)
    return {
        "processed": len(items),
        "sent": sent,
        "retry": retry,
        "failed": failed,
    }


def build_calendar(session: Session, user_id: uuid.UUID) -> bytes:
    plan = _latest_plan(session, user_id)
    if plan is None:
        return EMPTY_CALENDAR.encode("utf-8")
    return calendar_ics_for_plan(session, plan)


def create_calendar_token(
    session: Session,
    *,
    user_id: uuid.UUID,
    actor_role: str,
) -> Tuple[str, NotificationPreference]:
    prefs = ensure_preferences(session, user_id)
    token = secrets.token_urlsafe(32)
    prefs.calendar_token_hash = hash_secret(token)
    prefs.calendar_token_created_at = utcnow()
    prefs.updated_at = utcnow()
    record_audit(
        session,
        actor_user_id=user_id,
        actor_role=actor_role,
        action="notification.calendar_token_created",
        resource_type="notification_preferences",
        resource_id=str(prefs.id),
        metadata={},
    )
    commit_or_conflict(session)
    return token, prefs


def resolve_calendar_token(session: Session, token: str) -> bytes:
    prefs = session.scalar(
        select(NotificationPreference).where(
            NotificationPreference.calendar_token_hash == hash_secret(token)
        )
    )
    if prefs is None:
        raise CalendarNotFoundError()
    return build_calendar(session, prefs.owner_user_id)


def unsubscribe_token(user_id: uuid.UUID, secret: str) -> str:
    return sign_unsubscribe(user_id, secret)


def unsubscribe_by_token(session: Session, token: str, secret: str) -> None:
    try:
        user_id = verify_unsubscribe(token, secret)
    except ValueError as exc:
        raise NotificationValidationError("Unsubscribe token tidak valid.") from exc
    prefs = ensure_preferences(session, user_id)
    prefs.email_enabled = False
    prefs.updated_at = utcnow()
    record_audit(
        session,
        actor_user_id=None,
        actor_role=None,
        action="notification.unsubscribed",
        resource_type="notification_preferences",
        resource_id=str(prefs.id),
        metadata={"channel": "email"},
    )
    commit_or_conflict(session)


def calendar_response(token: str, calendar_url: str) -> CalendarTokenResponse:
    return CalendarTokenResponse(token=token, calendar_url=calendar_url)
