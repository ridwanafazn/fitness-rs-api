"""Request/response schemas for P0.4 feedback, safety, and admin triage."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.domain.feedback import Difficulty, SafetySeverity, SafetyStatus


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class FeedbackCreate(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    plan_id: Optional[uuid.UUID] = None
    workout_session_id: Optional[uuid.UUID] = None
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    difficulty: Optional[Difficulty] = None
    pain: Optional[bool] = None
    pain_area: Optional[str] = Field(default=None, max_length=60)
    comment: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _require_feedback_value(self) -> FeedbackCreate:
        if all(
            value is None
            for value in (
                self.rating,
                self.difficulty,
                self.pain,
                self.comment,
            )
        ):
            raise ValueError("Minimal satu field feedback harus diisi.")
        if self.pain_area and self.pain is not True:
            self.pain = True
        return self


class FeedbackOut(BaseModel):
    id: uuid.UUID
    plan_id: Optional[uuid.UUID] = None
    plan_version_id: Optional[uuid.UUID] = None
    workout_session_id: Optional[uuid.UUID] = None
    rating: Optional[int] = None
    difficulty: Optional[str] = None
    pain: bool = False
    pain_area: Optional[str] = None
    comment: Optional[str] = None
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> datetime:
        return _as_utc(value)


class UnsafeReportCreate(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    plan_id: Optional[uuid.UUID] = None
    plan_exercise_id: Optional[uuid.UUID] = None
    workout_session_id: Optional[uuid.UUID] = None
    exercise_id: Optional[str] = Field(default=None, max_length=64)
    reason: str = Field(..., min_length=5, max_length=2000)
    severity: SafetySeverity = SafetySeverity.MEDIUM

    @model_validator(mode="after")
    def _require_context(self) -> UnsafeReportCreate:
        if not any(
            (
                self.plan_exercise_id,
                self.workout_session_id,
                self.exercise_id,
            )
        ):
            raise ValueError(
                "Sertakan plan_exercise_id, workout_session_id, atau exercise_id."
            )
        return self


class UnsafeReportUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Optional[SafetyStatus] = None
    severity: Optional[SafetySeverity] = None
    resolution_note: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _require_change(self) -> UnsafeReportUpdate:
        if self.status is None and self.severity is None and self.resolution_note is None:
            raise ValueError("Minimal satu field report harus diisi.")
        return self


class UnsafeReportOut(BaseModel):
    id: uuid.UUID
    reporter_user_id: Optional[uuid.UUID] = None
    plan_id: Optional[uuid.UUID] = None
    plan_exercise_id: Optional[uuid.UUID] = None
    workout_session_id: Optional[uuid.UUID] = None
    exercise_id: str
    exercise_name: Optional[str] = None
    reason: str
    severity: str
    status: str
    resolution_note: Optional[str] = None
    resolved_by: Optional[uuid.UUID] = None
    triaged_at: Optional[datetime] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("triaged_at", "resolved_at", "created_at", "updated_at")
    def _serialize_timestamps(self, value: Optional[datetime]) -> Optional[datetime]:
        return None if value is None else _as_utc(value)


class FeedbackListResponse(BaseModel):
    items: List[FeedbackOut] = Field(default_factory=list)
    next_cursor: Optional[str] = None


class UnsafeReportListResponse(BaseModel):
    items: List[UnsafeReportOut] = Field(default_factory=list)
    next_cursor: Optional[str] = None


class AuditLogOut(BaseModel):
    id: uuid.UUID
    actor_user_id: Optional[uuid.UUID] = None
    actor_role: Optional[str] = None
    action: str
    resource_type: Optional[str] = None
    resource_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> datetime:
        return _as_utc(value)


class AuditListResponse(BaseModel):
    items: List[AuditLogOut] = Field(default_factory=list)
    next_cursor: Optional[str] = None


class QualitySummary(BaseModel):
    total_plans: int = 0
    total_feedback: int = 0
    average_rating: Optional[float] = None
    reports_total: int = 0
    reports_by_status: Dict[str, int] = Field(default_factory=dict)
    reports_by_severity: Dict[str, int] = Field(default_factory=dict)
    reports_per_1000_plans: Optional[float] = None
    median_resolution_hours: Optional[float] = None
