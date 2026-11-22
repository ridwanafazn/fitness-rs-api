"""Request/response schemas for P0.2 plan lifecycle."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.schemas.exercise import ExerciseOut
from app.schemas.recommendation import RecommendationRequest, RecommendationResponse


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class PlanCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    recommendation: RecommendationRequest
    result: Optional[RecommendationResponse] = None
    title: Optional[str] = Field(default=None, max_length=120)


class PlanImportRequest(PlanCreateRequest):
    result: RecommendationResponse


class PlanUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: Literal["lock", "swap", "regenerate_day"]
    expected_revision: Optional[int] = Field(default=None, ge=1)
    plan_exercise_id: Optional[uuid.UUID] = None
    locked: Optional[bool] = None
    replacement_exercise_id: Optional[str] = Field(default=None, max_length=64)
    day: Optional[int] = Field(default=None, ge=1, le=7)


class PlanShareRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    expires_in_days: int = Field(default=7, ge=1, le=90)


class PlanExerciseOut(ExerciseOut):
    id: uuid.UUID
    locked: bool = False


class PlanDayOut(BaseModel):
    day: int
    day_focus: str
    exercises: List[PlanExerciseOut] = Field(default_factory=list)


class PlanResponse(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    current_version: int
    revision: int
    input: Dict[str, Any]
    bmi: Optional[float] = None
    bmi_category: Optional[str] = None
    split_type: str
    schedule: Dict[str, str]
    days: List[PlanDayOut] = Field(default_factory=list)
    seed: int
    dataset_version: str
    algorithm_version: str
    warnings: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _serialize_timestamps(self, value: datetime) -> datetime:
        return _as_utc(value)


class PlanSummary(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    current_version: int
    revision: int
    split_type: str
    day_count: int
    seed: int
    dataset_version: str
    algorithm_version: str
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _serialize_timestamps(self, value: datetime) -> datetime:
        return _as_utc(value)


class PlanListResponse(BaseModel):
    items: List[PlanSummary] = Field(default_factory=list)
    next_cursor: Optional[str] = None


class PlanVersionOut(BaseModel):
    version: int
    split_type: str
    schedule: Dict[str, str]
    warnings: List[str] = Field(default_factory=list)
    day_count: int
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> datetime:
        return _as_utc(value)


class PlanVersionListResponse(BaseModel):
    items: List[PlanVersionOut] = Field(default_factory=list)


class PublicPlanResponse(BaseModel):
    title: str
    split_type: str
    schedule: Dict[str, str]
    days: List[PlanDayOut] = Field(default_factory=list)
    seed: int
    dataset_version: str
    algorithm_version: str
    warnings: List[str] = Field(default_factory=list)
    expires_at: datetime

    @field_serializer("expires_at")
    def _serialize_expires_at(self, value: datetime) -> datetime:
        return _as_utc(value)


class PlanShareResponse(BaseModel):
    token: str
    expires_at: datetime
    share_url: str

    @field_serializer("expires_at")
    def _serialize_expires_at(self, value: datetime) -> datetime:
        return _as_utc(value)
