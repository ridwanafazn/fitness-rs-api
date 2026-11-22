"""Request/response schemas for P1.1 progress, history, and insights."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_serializer

from app.schemas.workouts import WorkoutSummary


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class DailyMetricOut(BaseModel):
    date: date
    workouts_completed: int = 0
    total_sets: int = 0
    total_reps: int = 0
    total_volume_kg: float = 0
    duration_seconds: int = 0
    sets_by_body_part: Dict[str, int] = Field(default_factory=dict)
    volume_by_body_part: Dict[str, float] = Field(default_factory=dict)


class ProgressTotals(BaseModel):
    workouts_completed: int = 0
    total_sets: int = 0
    total_reps: int = 0
    total_volume_kg: float = 0
    duration_seconds: int = 0


class ProgressResponse(BaseModel):
    timezone: str
    from_date: date
    to_date: date
    totals: ProgressTotals
    days: List[DailyMetricOut] = Field(default_factory=list)
    sets_by_body_part: Dict[str, int] = Field(default_factory=dict)
    volume_by_body_part: Dict[str, float] = Field(default_factory=dict)
    streak_days: int = 0


class PersonalRecordOut(BaseModel):
    exercise_id: str
    exercise_name: str
    record_type: str
    value: float
    reps: Optional[int] = None
    weight_kg: Optional[float] = None
    achieved_at: datetime

    @field_serializer("achieved_at")
    def _serialize_achieved_at(self, value: datetime) -> datetime:
        return _as_utc(value)


class WeeklyReviewOut(BaseModel):
    week_start: date
    timezone: str
    workouts_completed: int = 0
    total_sets: int = 0
    total_reps: int = 0
    total_volume_kg: float = 0
    duration_seconds: int = 0
    sets_by_body_part: Dict[str, int] = Field(default_factory=dict)
    volume_by_body_part: Dict[str, float] = Field(default_factory=dict)
    summary: Optional[str] = None


class InsightsResponse(BaseModel):
    timezone: str
    streak_days: int = 0
    workouts_last_28_days: int = 0
    current_week: Optional[WeeklyReviewOut] = None
    body_part_balance: Dict[str, float] = Field(default_factory=dict)
    personal_records: List[PersonalRecordOut] = Field(default_factory=list)
    summary: str = ""


class ProgressHistoryResponse(BaseModel):
    items: List[WorkoutSummary] = Field(default_factory=list)
    next_cursor: Optional[str] = None
