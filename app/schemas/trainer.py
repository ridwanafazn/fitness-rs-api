"""Request/response schemas for P1.2 trainer workspace."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
)

from app.domain.trainer import ReviewStatus, TrainingScope
from app.schemas.feedback import FeedbackOut
from app.schemas.plans import PlanSummary
from app.schemas.workouts import WorkoutSummary

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _normalise_email(value: str) -> str:
    cleaned = value.strip().lower()
    if len(cleaned) > 320 or not _EMAIL_RE.fullmatch(cleaned):
        raise ValueError("Email tidak valid.")
    return cleaned


class TrainerProfileIn(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    display_name: str = Field(..., min_length=1, max_length=120)
    bio: Optional[str] = Field(default=None, max_length=2000)
    specialties: List[str] = Field(default_factory=list, max_length=20)
    years_experience: Optional[int] = Field(default=None, ge=0, le=60)

    @field_validator("specialties")
    @classmethod
    def _clean_specialties(cls, value: List[str]) -> List[str]:
        result: List[str] = []
        for item in value:
            cleaned = " ".join(item.split())
            if cleaned and cleaned not in result:
                result.append(cleaned[:60])
        return result


class TrainerProfileOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    bio: Optional[str] = None
    specialties: List[str] = Field(default_factory=list)
    years_experience: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _serialize_timestamps(self, value: datetime) -> datetime:
        return _as_utc(value)


class TrainerInvitationCreate(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    client_email: str = Field(..., min_length=3, max_length=320)
    scopes: List[TrainingScope] = Field(
        default_factory=lambda: list(TrainingScope),
        min_length=1,
    )
    message: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("client_email", mode="before")
    @classmethod
    def _email(cls, value: str) -> str:
        return _normalise_email(value)

    @field_validator("scopes")
    @classmethod
    def _dedupe_scopes(cls, value: List[TrainingScope]) -> List[TrainingScope]:
        result: List[TrainingScope] = []
        for item in value:
            if item not in result:
                result.append(item)
        return result


class TrainerInvitationCreated(BaseModel):
    id: uuid.UUID
    client_email: str
    requested_scopes: List[str]
    status: str
    expires_at: datetime
    token: str
    invite_url: str

    @field_serializer("expires_at")
    def _serialize_expires_at(self, value: datetime) -> datetime:
        return _as_utc(value)


class TrainerInvitationOut(BaseModel):
    id: uuid.UUID
    client_user_id: Optional[uuid.UUID] = None
    client_email: str
    requested_scopes: List[str]
    status: str
    expires_at: datetime
    created_at: datetime

    @field_serializer("expires_at", "created_at")
    def _serialize_timestamps(self, value: datetime) -> datetime:
        return _as_utc(value)


class TrainerInvitationListResponse(BaseModel):
    items: List[TrainerInvitationOut] = Field(default_factory=list)


class InvitationAcceptRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    scopes: Optional[List[TrainingScope]] = Field(default=None, min_length=1)

    @field_validator("scopes")
    @classmethod
    def _dedupe_scopes(
        cls, value: Optional[List[TrainingScope]]
    ) -> Optional[List[TrainingScope]]:
        if value is None:
            return None
        result: List[TrainingScope] = []
        for item in value:
            if item not in result:
                result.append(item)
        return result


class AccessGrantOut(BaseModel):
    scope: str
    granted_at: datetime

    @field_serializer("granted_at")
    def _serialize_granted_at(self, value: datetime) -> datetime:
        return _as_utc(value)


class TrainerClientOut(BaseModel):
    id: uuid.UUID
    trainer_user_id: uuid.UUID
    client_user_id: uuid.UUID
    client_display_name: Optional[str] = None
    scopes: List[str] = Field(default_factory=list)
    status: str
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> datetime:
        return _as_utc(value)


class TrainerClientListResponse(BaseModel):
    items: List[TrainerClientOut] = Field(default_factory=list)


class TrainerPlansResponse(BaseModel):
    items: List[PlanSummary] = Field(default_factory=list)
    next_cursor: Optional[str] = None


class TrainerWorkoutsResponse(BaseModel):
    items: List[WorkoutSummary] = Field(default_factory=list)
    next_cursor: Optional[str] = None


class TrainerFeedbackResponse(BaseModel):
    items: List[FeedbackOut] = Field(default_factory=list)
    next_cursor: Optional[str] = None


class PlanReviewIn(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    status: ReviewStatus
    note: Optional[str] = Field(default=None, max_length=2000)


class PlanReviewOut(BaseModel):
    id: uuid.UUID
    plan_id: uuid.UUID
    plan_version_id: Optional[uuid.UUID] = None
    trainer_user_id: uuid.UUID
    status: str
    note: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _serialize_timestamps(self, value: datetime) -> datetime:
        return _as_utc(value)


class PlanReviewListResponse(BaseModel):
    items: List[PlanReviewOut] = Field(default_factory=list)


class TrainerCommentCreate(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    body: str = Field(..., min_length=1, max_length=4000)
    plan_id: Optional[uuid.UUID] = None
    workout_session_id: Optional[uuid.UUID] = None


class TrainerCommentOut(BaseModel):
    id: uuid.UUID
    trainer_user_id: uuid.UUID
    client_user_id: uuid.UUID
    plan_id: Optional[uuid.UUID] = None
    workout_session_id: Optional[uuid.UUID] = None
    body: str
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> datetime:
        return _as_utc(value)


class TrainerCommentListResponse(BaseModel):
    items: List[TrainerCommentOut] = Field(default_factory=list)


class ClientTrainerOut(BaseModel):
    trainer_user_id: uuid.UUID
    display_name: str
    scopes: List[str] = Field(default_factory=list)
    since: datetime

    @field_serializer("since")
    def _serialize_since(self, value: datetime) -> datetime:
        return _as_utc(value)


class ClientTrainerListResponse(BaseModel):
    items: List[ClientTrainerOut] = Field(default_factory=list)
