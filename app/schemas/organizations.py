"""Request/response schemas for P2.1 free organizations."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from app.domain.organization import (
    OrganizationRole,
    OrganizationStatus,
    OrganizationType,
)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _email(value: str) -> str:
    cleaned = value.strip().lower()
    if len(cleaned) > 320 or not _EMAIL_RE.fullmatch(cleaned):
        raise ValueError("Email tidak valid.")
    return cleaned


def _slug(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip().lower()
    if not _SLUG_RE.fullmatch(cleaned):
        raise ValueError("Slug hanya boleh huruf kecil, angka, dan tanda hubung.")
    return cleaned


def _timezone(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    try:
        ZoneInfo(cleaned)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Timezone harus nama IANA yang valid.") from exc
    return cleaned


class OrganizationCreate(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str = Field(..., min_length=2, max_length=160)
    slug: Optional[str] = Field(default=None, max_length=64)
    type: OrganizationType = OrganizationType.GYM
    description: Optional[str] = Field(default=None, max_length=2000)
    website: Optional[str] = Field(default=None, max_length=255)
    timezone: str = Field(default="UTC", max_length=64)
    branding: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("slug", mode="before")
    @classmethod
    def _slug(cls, value: Optional[str]) -> Optional[str]:
        return _slug(value)

    @field_validator("timezone", mode="before")
    @classmethod
    def _timezone(cls, value: Optional[str]) -> Optional[str]:
        return _timezone(value)


class OrganizationUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: Optional[str] = Field(default=None, min_length=2, max_length=160)
    description: Optional[str] = Field(default=None, max_length=2000)
    website: Optional[str] = Field(default=None, max_length=255)
    timezone: Optional[str] = Field(default=None, max_length=64)
    branding: Optional[Dict[str, Any]] = None
    status: Optional[OrganizationStatus] = None

    @field_validator("timezone", mode="before")
    @classmethod
    def _timezone(cls, value: Optional[str]) -> Optional[str]:
        return _timezone(value)


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    type: str
    description: Optional[str] = None
    website: Optional[str] = None
    timezone: str
    branding: Dict[str, Any] = Field(default_factory=dict)
    status: str
    role: str
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _serialize_timestamps(self, value: datetime) -> datetime:
        return _as_utc(value)


class OrganizationListResponse(BaseModel):
    items: List[OrganizationOut] = Field(default_factory=list)


class OrganizationMemberOut(BaseModel):
    user_id: uuid.UUID
    display_name: Optional[str] = None
    role: str
    status: str
    joined_at: datetime

    @field_serializer("joined_at")
    def _serialize_joined_at(self, value: datetime) -> datetime:
        return _as_utc(value)


class OrganizationMemberListResponse(BaseModel):
    items: List[OrganizationMemberOut] = Field(default_factory=list)


class OrganizationMemberUpdate(BaseModel):
    role: OrganizationRole


class OrganizationInvitationCreate(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    email: str = Field(..., min_length=3, max_length=320)
    role: OrganizationRole = OrganizationRole.MEMBER

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, value: str) -> str:
        return _email(value)

    @field_validator("role")
    @classmethod
    def _role(cls, value: OrganizationRole) -> OrganizationRole:
        if value is OrganizationRole.OWNER:
            raise ValueError("Owner tidak bisa diundang; gunakan transfer ownership.")
        return value


class OrganizationInvitationCreated(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    status: str
    expires_at: datetime
    token: str
    invite_url: str

    @field_serializer("expires_at")
    def _serialize_expires_at(self, value: datetime) -> datetime:
        return _as_utc(value)


class OrganizationInvitationOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    status: str
    expires_at: datetime
    created_at: datetime

    @field_serializer("expires_at", "created_at")
    def _serialize_timestamps(self, value: datetime) -> datetime:
        return _as_utc(value)


class OrganizationInvitationListResponse(BaseModel):
    items: List[OrganizationInvitationOut] = Field(default_factory=list)


class OrganizationSummary(BaseModel):
    members_total: int = 0
    trainers: int = 0
    clients: int = 0
    active_plans: int = 0
