"""P2.2 research event, experiment, version, quality, and export schemas."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from app.domain.research import (
    EVENT_NAMES,
    QUALITY_RUBRIC_KEYS,
    ExperimentStatus,
    QualityReviewStatus,
    QualitySubjectType,
    validate_event_properties,
)

_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_VARIANT_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class EventCreate(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    name: str = Field(..., min_length=2, max_length=64)
    properties: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: Optional[datetime] = None
    idempotency_key: Optional[str] = Field(default=None, max_length=128)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        if value not in EVENT_NAMES:
            raise ValueError("Nama event tidak diizinkan.")
        return value

    @field_validator("properties")
    @classmethod
    def _properties(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        return validate_event_properties(value)

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at(cls, value: Optional[datetime]) -> Optional[datetime]:
        if value is None:
            return None
        normalised = _as_utc(value)
        now = datetime.now(UTC)
        if normalised > now + timedelta(minutes=5):
            raise ValueError("occurred_at tidak boleh di masa depan.")
        if normalised < now - timedelta(days=30):
            raise ValueError("occurred_at maksimal 30 hari ke belakang.")
        return normalised

    @field_validator("idempotency_key")
    @classmethod
    def _idempotency_key(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class EventOut(BaseModel):
    id: uuid.UUID
    name: str
    properties: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime
    received_at: datetime

    @field_serializer("occurred_at", "received_at")
    def _serialize_timestamps(self, value: datetime) -> datetime:
        return _as_utc(value)


class ExperimentVariant(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    key: str = Field(..., min_length=1, max_length=32)
    weight: int = Field(default=1, ge=1, le=100)

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not _VARIANT_KEY_RE.fullmatch(value):
            raise ValueError(
                "Variant key harus huruf kecil, angka, underscore, atau strip."
            )
        return value


def _validate_variants(variants: List[ExperimentVariant]) -> List[ExperimentVariant]:
    if len(variants) < 2:
        raise ValueError("Eksperimen membutuhkan minimal 2 variant.")
    if len(variants) > 4:
        raise ValueError("Eksperimen maksimal 4 variant.")
    keys = [variant.key for variant in variants]
    if len(set(keys)) != len(keys):
        raise ValueError("Variant key harus unik.")
    return variants


class ExperimentCreate(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    key: str = Field(..., min_length=3, max_length=64)
    name: str = Field(..., min_length=2, max_length=160)
    description: Optional[str] = Field(default=None, max_length=2000)
    status: ExperimentStatus = ExperimentStatus.DRAFT
    variants: List[ExperimentVariant]
    traffic_percent: int = Field(default=100, ge=0, le=100)

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        if not _KEY_RE.fullmatch(value):
            raise ValueError(
                "Key eksperimen harus huruf kecil, angka, underscore, atau strip."
            )
        return value

    @field_validator("variants")
    @classmethod
    def _variants(cls, value: List[ExperimentVariant]) -> List[ExperimentVariant]:
        return _validate_variants(value)


class ExperimentUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    description: Optional[str] = Field(default=None, max_length=2000)
    status: Optional[ExperimentStatus] = None
    variants: Optional[List[ExperimentVariant]] = None
    traffic_percent: Optional[int] = Field(default=None, ge=0, le=100)

    @field_validator("variants")
    @classmethod
    def _variants(
        cls, value: Optional[List[ExperimentVariant]]
    ) -> Optional[List[ExperimentVariant]]:
        if value is None:
            return None
        return _validate_variants(value)

    @model_validator(mode="after")
    def _require_change(self) -> ExperimentUpdate:
        if (
            self.description is None
            and self.status is None
            and self.variants is None
            and self.traffic_percent is None
        ):
            raise ValueError("Minimal satu field eksperimen harus diisi.")
        return self


class ExperimentOut(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    description: Optional[str] = None
    status: str
    variants: List[Dict[str, Any]] = Field(default_factory=list)
    traffic_percent: int
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("started_at", "ended_at", "created_at", "updated_at")
    def _serialize_timestamps(self, value: Optional[datetime]) -> Optional[datetime]:
        return None if value is None else _as_utc(value)


class ExperimentListResponse(BaseModel):
    items: List[ExperimentOut] = Field(default_factory=list)


class AssignmentOut(BaseModel):
    experiment_key: str
    experiment_name: str
    variant: str
    assigned_at: datetime
    exposed_at: Optional[datetime] = None

    @field_serializer("assigned_at", "exposed_at")
    def _serialize_timestamps(self, value: Optional[datetime]) -> Optional[datetime]:
        return None if value is None else _as_utc(value)


class AssignmentsResponse(BaseModel):
    items: List[AssignmentOut] = Field(default_factory=list)


class VariantReportOut(BaseModel):
    variant: str
    assignments: int = 0
    exposures: int = 0
    events: Dict[str, int] = Field(default_factory=dict)


class ExperimentReportOut(BaseModel):
    id: uuid.UUID
    key: str
    name: str
    status: str
    traffic_percent: int
    variants: List[str] = Field(default_factory=list)
    variant_weights: Dict[str, int] = Field(default_factory=dict)
    assignments_total: int = 0
    exposures_total: int = 0
    by_variant: List[VariantReportOut] = Field(default_factory=list)
    generated_at: datetime

    @field_serializer("generated_at")
    def _serialize_generated_at(self, value: datetime) -> datetime:
        return _as_utc(value)


class VersionOut(BaseModel):
    id: uuid.UUID
    kind: str
    version: str
    checksum: str
    row_count: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> datetime:
        return _as_utc(value)


class VersionListResponse(BaseModel):
    items: List[VersionOut] = Field(default_factory=list)


class QualityReviewCreate(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    subject_type: QualitySubjectType
    subject_id: str = Field(..., min_length=1, max_length=64)
    status: QualityReviewStatus = QualityReviewStatus.PENDING
    rubric: Dict[str, int] = Field(default_factory=dict)
    notes: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("rubric")
    @classmethod
    def _rubric(cls, value: Dict[str, int]) -> Dict[str, int]:
        return _validate_rubric(value, required=True)


def _validate_rubric(value: Dict[str, int], *, required: bool) -> Dict[str, int]:
    if required and not value:
        raise ValueError("Rubric minimal satu kategori.")
    cleaned: Dict[str, int] = {}
    for key, score in value.items():
        if key not in QUALITY_RUBRIC_KEYS:
            raise ValueError(f"Kategori rubric tidak dikenal: {key}.")
        if isinstance(score, bool) or not isinstance(score, int):
            raise ValueError("Skor rubric harus bilangan bulat.")
        if score < 1 or score > 5:
            raise ValueError("Skor rubric harus 1 sampai 5.")
        cleaned[key] = score
    return cleaned


class QualityReviewUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    status: Optional[QualityReviewStatus] = None
    rubric: Optional[Dict[str, int]] = None
    notes: Optional[str] = Field(default=None, max_length=4000)

    @field_validator("rubric")
    @classmethod
    def _rubric(cls, value: Optional[Dict[str, int]]) -> Optional[Dict[str, int]]:
        if value is None:
            return None
        return _validate_rubric(value, required=True)

    @model_validator(mode="after")
    def _require_change(self) -> QualityReviewUpdate:
        if self.status is None and self.rubric is None and self.notes is None:
            raise ValueError("Minimal satu field review harus diisi.")
        return self


class QualityReviewOut(BaseModel):
    id: uuid.UUID
    reviewer_user_id: Optional[uuid.UUID] = None
    subject_type: str
    subject_id: str
    status: str
    rubric: Dict[str, int] = Field(default_factory=dict)
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @field_serializer("created_at", "updated_at")
    def _serialize_timestamps(self, value: datetime) -> datetime:
        return _as_utc(value)


class QualityReviewListResponse(BaseModel):
    items: List[QualityReviewOut] = Field(default_factory=list)


class ResearchReportOut(BaseModel):
    start: datetime
    end: datetime
    generated_at: datetime
    versions: List[VersionOut] = Field(default_factory=list)
    events_total: int = 0
    unique_event_users: int = 0
    events_by_name: Dict[str, int] = Field(default_factory=dict)
    plans_total: int = 0
    plans_by_dataset_version: Dict[str, int] = Field(default_factory=dict)
    plans_by_algorithm_version: Dict[str, int] = Field(default_factory=dict)
    workouts_total: int = 0
    workouts_completed: int = 0
    workout_completion_rate: Optional[float] = None
    feedback_total: int = 0
    average_rating: Optional[float] = None
    safety_reports_total: int = 0
    reports_by_severity: Dict[str, int] = Field(default_factory=dict)
    reports_by_status: Dict[str, int] = Field(default_factory=dict)
    experiments: List[ExperimentReportOut] = Field(default_factory=list)

    @field_serializer("start", "end", "generated_at")
    def _serialize_timestamps(self, value: datetime) -> datetime:
        return _as_utc(value)


class ExportEventOut(BaseModel):
    user_ref: str
    name: str
    properties: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime

    @field_serializer("occurred_at")
    def _serialize_occurred_at(self, value: datetime) -> datetime:
        return _as_utc(value)


class ExportPlanOut(BaseModel):
    user_ref: str
    plan_ref: str
    created_at: datetime
    day_count: int
    split_type: str
    bmi_category: Optional[str] = None
    dataset_version: str
    algorithm_version: str

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> datetime:
        return _as_utc(value)


class ExportWorkoutOut(BaseModel):
    user_ref: str
    workout_ref: str
    plan_ref: Optional[str] = None
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    total_sets: int

    @field_serializer("started_at", "completed_at")
    def _serialize_timestamps(self, value: Optional[datetime]) -> Optional[datetime]:
        return None if value is None else _as_utc(value)


class ExportFeedbackOut(BaseModel):
    user_ref: str
    plan_ref: Optional[str] = None
    workout_ref: Optional[str] = None
    rating: Optional[int] = None
    difficulty: Optional[str] = None
    pain: bool = False
    created_at: datetime

    @field_serializer("created_at")
    def _serialize_created_at(self, value: datetime) -> datetime:
        return _as_utc(value)


class ExportSafetyReportOut(BaseModel):
    user_ref: str
    exercise_id: str
    severity: str
    status: str
    created_at: datetime
    resolved_at: Optional[datetime] = None

    @field_serializer("created_at", "resolved_at")
    def _serialize_timestamps(self, value: Optional[datetime]) -> Optional[datetime]:
        return None if value is None else _as_utc(value)


class ResearchExportOut(BaseModel):
    generated_at: datetime
    start: datetime
    end: datetime
    consent_kind: str = "research_analytics"
    user_count: int = 0
    events: List[ExportEventOut] = Field(default_factory=list)
    plans: List[ExportPlanOut] = Field(default_factory=list)
    workouts: List[ExportWorkoutOut] = Field(default_factory=list)
    feedback: List[ExportFeedbackOut] = Field(default_factory=list)
    safety_reports: List[ExportSafetyReportOut] = Field(default_factory=list)
    versions: List[VersionOut] = Field(default_factory=list)
    truncated: Dict[str, bool] = Field(default_factory=dict)

    @field_serializer("generated_at", "start", "end")
    def _serialize_timestamps(self, value: datetime) -> datetime:
        return _as_utc(value)
