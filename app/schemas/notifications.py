"""Request/response schemas for P1.3 notifications and integrations."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import List, Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

_HHMM_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _validate_hhmm(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    if not _HHMM_RE.fullmatch(cleaned):
        raise ValueError("Waktu harus format HH:MM (00:00-23:59).")
    return cleaned


def _validate_timezone(value: str) -> str:
    cleaned = value.strip()
    try:
        ZoneInfo(cleaned)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Timezone harus nama IANA yang valid.") from exc
    return cleaned


class NotificationPreferencesUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    email_enabled: Optional[bool] = None
    push_enabled: Optional[bool] = None
    whatsapp_enabled: Optional[bool] = None
    reminder_enabled: Optional[bool] = None
    reminder_time: Optional[str] = Field(default=None, max_length=5)
    timezone: Optional[str] = Field(default=None, max_length=64)
    quiet_hours_start: Optional[str] = Field(default=None, max_length=5)
    quiet_hours_end: Optional[str] = Field(default=None, max_length=5)
    weekly_review_enabled: Optional[bool] = None

    @field_validator("reminder_time", "quiet_hours_start", "quiet_hours_end", mode="before")
    @classmethod
    def _times(cls, value: Optional[str]) -> Optional[str]:
        return _validate_hhmm(value)

    @field_validator("timezone", mode="before")
    @classmethod
    def _timezone(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else _validate_timezone(value)

    @model_validator(mode="after")
    def _validate(self) -> NotificationPreferencesUpdate:
        if not any(value is not None for value in self.model_dump().values()):
            raise ValueError("Minimal satu preferensi harus diisi.")
        if (self.quiet_hours_start is None) != (self.quiet_hours_end is None):
            raise ValueError("quiet_hours_start dan quiet_hours_end harus diisi bersama.")
        return self


class NotificationPreferencesOut(BaseModel):
    email_enabled: bool = False
    push_enabled: bool = False
    whatsapp_enabled: bool = False
    reminder_enabled: bool = False
    reminder_time: str = "18:00"
    timezone: str = "UTC"
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    weekly_review_enabled: bool = False
    calendar_connected: bool = False


class DeviceCreate(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    token: str = Field(..., min_length=1, max_length=4096)
    platform: Literal["ios", "android", "web"]
    device_name: Optional[str] = Field(default=None, max_length=120)


class DeviceOut(BaseModel):
    id: uuid.UUID
    platform: str
    device_name: Optional[str] = None
    has_token: bool = False
    last_seen_at: datetime
    created_at: datetime

    @field_serializer("last_seen_at", "created_at")
    def _serialize_timestamps(self, value: datetime) -> datetime:
        return _as_utc(value)


class DeviceListResponse(BaseModel):
    items: List[DeviceOut] = Field(default_factory=list)


class TestNotificationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    channel: Literal["email", "push", "whatsapp"]
    template: str = Field(default="test", min_length=1, max_length=64)


class OutboxOut(BaseModel):
    id: uuid.UUID
    channel: str
    template: str
    status: str
    scheduled_at: datetime
    attempts: int
    max_attempts: int

    @field_serializer("scheduled_at")
    def _serialize_scheduled_at(self, value: datetime) -> datetime:
        return _as_utc(value)


class CalendarTokenResponse(BaseModel):
    token: str
    calendar_url: str


class UnsubscribeTokenResponse(BaseModel):
    token: str
    unsubscribe_url: str


class IntegrationOut(BaseModel):
    provider: str
    status: str
    scopes: List[str] = Field(default_factory=list)
    expires_at: Optional[datetime] = None
    connected_at: datetime

    @field_serializer("expires_at", "connected_at")
    def _serialize_timestamps(self, value: Optional[datetime]) -> Optional[datetime]:
        return None if value is None else _as_utc(value)


class IntegrationListResponse(BaseModel):
    items: List[IntegrationOut] = Field(default_factory=list)


class IntegrationAuthorizeResponse(BaseModel):
    provider: str
    authorize_url: str
    state: str


class IntegrationCallbackRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str = Field(..., min_length=1, max_length=2048)
    state: str = Field(..., min_length=1, max_length=2048)
