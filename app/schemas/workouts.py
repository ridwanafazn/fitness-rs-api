"""Request/response schemas for P0.3 workout execution and sync."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.schemas.exercise import ExerciseOut
from app.schemas.recommendation import ErrorDetail


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _validate_timezone(value: Any) -> Any:
    if value is None:
        return None
    if not isinstance(value, str):
        return value
    timezone = value.strip()
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Timezone harus nama IANA yang valid, misalnya Asia/Jakarta.") from exc
    return timezone


class WorkoutStartRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    plan_id: uuid.UUID
    day: Optional[int] = Field(default=None, ge=1, le=7)
    plan_version: Optional[int] = Field(default=None, ge=1)
    timezone: Optional[str] = Field(default=None, max_length=64)
    client_session_id: Optional[uuid.UUID] = None

    @field_validator("timezone", mode="before")
    @classmethod
    def _timezone(cls, value: Any) -> Any:
        return _validate_timezone(value)


class SetOut(BaseModel):
    id: uuid.UUID
    workout_exercise_id: uuid.UUID
    set_number: int
    reps: Optional[int] = None
    weight_kg: Optional[float] = None
    rpe: Optional[float] = None
    completed: bool = True
    notes: Optional[str] = None
    client_set_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    @field_serializer("created_at", "updated_at", "deleted_at")
    def _serialize_timestamps(self, value: Optional[datetime]) -> Optional[datetime]:
        return None if value is None else _as_utc(value)


class WorkoutExerciseOut(ExerciseOut):
    id: uuid.UUID
    source_plan_exercise_id: Optional[uuid.UUID] = None
    position: int
    notes: Optional[str] = None
    substituted_from_exercise_id: Optional[str] = None
    sets: List[SetOut] = Field(default_factory=list)


class WorkoutResponse(BaseModel):
    id: uuid.UUID
    plan_id: Optional[uuid.UUID] = None
    plan_version_id: Optional[uuid.UUID] = None
    plan_day_id: Optional[uuid.UUID] = None
    day_number: Optional[int] = None
    title: str
    focus: str
    status: str
    timezone: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    notes: Optional[str] = None
    client_session_id: Optional[uuid.UUID] = None
    total_sets: int = 0
    total_reps: int = 0
    total_volume_kg: float = 0
    exercise_count: int = 0
    duration_seconds: Optional[int] = None
    exercises: List[WorkoutExerciseOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @field_serializer("started_at", "completed_at", "created_at", "updated_at")
    def _serialize_timestamps(self, value: Optional[datetime]) -> Optional[datetime]:
        return None if value is None else _as_utc(value)


class WorkoutSummary(BaseModel):
    id: uuid.UUID
    plan_id: Optional[uuid.UUID] = None
    day_number: Optional[int] = None
    title: str
    focus: str
    status: str
    timezone: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    total_sets: int = 0
    total_reps: int = 0
    total_volume_kg: float = 0
    exercise_count: int = 0
    duration_seconds: Optional[int] = None

    @field_serializer("started_at", "completed_at")
    def _serialize_timestamps(self, value: Optional[datetime]) -> Optional[datetime]:
        return None if value is None else _as_utc(value)


class WorkoutListResponse(BaseModel):
    items: List[WorkoutSummary] = Field(default_factory=list)
    next_cursor: Optional[str] = None


class WorkoutUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    notes: Optional[str] = Field(default=None, max_length=4000)


class SetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client_set_id: Optional[uuid.UUID] = None
    workout_exercise_id: uuid.UUID
    set_number: int = Field(..., ge=1, le=100)
    reps: Optional[int] = Field(default=None, ge=0, le=1000)
    weight_kg: Optional[float] = Field(default=None, ge=0, le=2000)
    rpe: Optional[float] = Field(default=None, ge=1, le=10)
    completed: bool = True
    notes: Optional[str] = Field(default=None, max_length=2000)


class SetUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reps: Optional[int] = Field(default=None, ge=0, le=1000)
    weight_kg: Optional[float] = Field(default=None, ge=0, le=2000)
    rpe: Optional[float] = Field(default=None, ge=1, le=10)
    completed: Optional[bool] = None
    notes: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _require_at_least_one_value(self) -> SetUpdateRequest:
        if not any(value is not None for value in self.model_dump().values()):
            raise ValueError("Minimal satu field set harus diisi.")
        return self


class WorkoutCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    notes: Optional[str] = Field(default=None, max_length=4000)


class WorkoutSubstituteRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    replacement_exercise_id: str = Field(..., min_length=1, max_length=64)


class SyncMutation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client_mutation_id: str = Field(..., min_length=1, max_length=64)
    type: Literal[
        "set.create",
        "set.update",
        "set.delete",
        "workout.complete",
        "exercise.substitute",
    ]
    occurred_at: Optional[datetime] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class SyncBatchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mutations: List[SyncMutation] = Field(..., min_length=1, max_length=100)


class SetCreateSyncPayload(SetCreateRequest):
    workout_id: uuid.UUID


class SetUpdateSyncPayload(SetUpdateRequest):
    set_id: uuid.UUID


class SetDeleteSyncPayload(BaseModel):
    set_id: uuid.UUID


class WorkoutCompleteSyncPayload(BaseModel):
    workout_id: uuid.UUID
    notes: Optional[str] = Field(default=None, max_length=4000)


class ExerciseSubstituteSyncPayload(BaseModel):
    workout_id: uuid.UUID
    workout_exercise_id: uuid.UUID
    replacement_exercise_id: str = Field(..., min_length=1, max_length=64)


class SyncMutationResult(BaseModel):
    client_mutation_id: str
    status: Literal["applied", "duplicate", "error"]
    result: Optional[Dict[str, Any]] = None
    error: Optional[ErrorDetail] = None


class SyncBatchResponse(BaseModel):
    results: List[SyncMutationResult] = Field(default_factory=list)
