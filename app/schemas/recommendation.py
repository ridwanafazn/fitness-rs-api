"""Request/response schemas for the recommendation API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.constants import (
    BodyPart,
    Equipment,
    Focus,
    Gender,
    is_valid_injury_term,
    normalise_injury_token,
    normalise_token,
    supported_injury_terms,
)
from app.domain.models import DayPlan, RecommendationPlan
from app.schemas.exercise import ExerciseOut


def _normalise_enum_list(value: Any, *, field_name: str, enum_type) -> Any:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return value
    result: List[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} hanya boleh berisi string.")
        token = normalise_token(item)
        try:
            enum_type(token)
        except ValueError:
            # Soft preferences are ignored when unknown, matching the old API.
            continue
        if token and token not in result:
            result.append(token)
    return result


def _normalise_string_list(value: Any, *, field_name: str) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} harus berupa list.")
    result: List[str] = []
    seen = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"{field_name} hanya boleh berisi string.")
        token = normalise_injury_token(item)
        if len(token) > 60:
            raise ValueError(f"{field_name} berisi nilai yang terlalu panjang.")
        if token and token not in seen:
            seen.add(token)
            result.append(token)
    return result


class RecommendationRequest(BaseModel):
    # Keep the old API's tolerant behaviour: unknown fields are ignored rather
    # than breaking an existing frontend with a 422.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    gender: Gender
    height_cm: float = Field(..., gt=50, le=300)
    weight_kg: float = Field(..., gt=10, le=400)
    injuries: List[str] = Field(default_factory=list, max_length=10)
    # 6-7 are accepted for backward compatibility and capped to 5 by the
    # rule engine, matching the old API's observable behaviour.
    available_days: int = Field(..., ge=1, le=7)
    preferred_body_part: List[BodyPart] = Field(default_factory=list, max_length=5)
    preferred_equipment: List[Equipment] = Field(default_factory=list, max_length=10)
    seed: Optional[int] = Field(
        default=None,
        ge=0,
        le=2**32 - 1,
        description="Seed opsional untuk hasil yang reproducible.",
    )

    @field_validator("gender", mode="before")
    @classmethod
    def _normalise_gender(cls, value: Any) -> Any:
        if isinstance(value, str):
            return normalise_token(value)
        return value

    @field_validator("injuries", mode="before")
    @classmethod
    def _validate_injuries(cls, value: Any) -> List[str]:
        terms = _normalise_string_list(value, field_name="injuries")
        unknown = [term for term in terms if not is_valid_injury_term(term)]
        if unknown:
            examples = ", ".join(sorted(supported_injury_terms())[:20])
            raise ValueError(
                f"Cedera tidak dikenali: {', '.join(unknown)}. Contoh yang didukung: {examples}."
            )
        return terms

    @field_validator("preferred_body_part", mode="before")
    @classmethod
    def _normalise_body_part(cls, value: Any) -> Any:
        return _normalise_enum_list(value, field_name="preferred_body_part", enum_type=BodyPart)

    @field_validator("preferred_equipment", mode="before")
    @classmethod
    def _normalise_equipment(cls, value: Any) -> Any:
        return _normalise_enum_list(value, field_name="preferred_equipment", enum_type=Equipment)


class RecommendationDay(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    day: int
    day_focus: Focus
    exercises: List[ExerciseOut]


class RecommendationResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    bmi: float
    bmi_category: str
    split_type: str
    schedule: Dict[str, Focus]
    days: List[RecommendationDay]
    seed: int
    dataset_version: str
    algorithm_version: str
    warnings: List[str] = Field(default_factory=list)

    @classmethod
    def from_plan(cls, plan: RecommendationPlan) -> RecommendationResponse:
        return cls(
            bmi=plan.bmi,
            bmi_category=plan.bmi_category,
            split_type=plan.split_type,
            schedule=plan.schedule,
            days=[
                RecommendationDay(
                    day=day.day,
                    day_focus=day.focus,
                    exercises=[ExerciseOut.from_domain(exercise) for exercise in day.exercises],
                )
                for day in plan.days
            ],
            seed=plan.seed,
            dataset_version=plan.dataset_version,
            algorithm_version=plan.algorithm_version,
            warnings=list(plan.warnings),
        )


class ByFocusRequest(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    day_focus: Focus
    injuries: List[str] = Field(default_factory=list, max_length=10)
    preferred_equipment: List[Equipment] = Field(default_factory=list, max_length=10)
    preferred_body_part: List[BodyPart] = Field(default_factory=list, max_length=5)
    bmi: Optional[float] = Field(
        default=None,
        gt=0,
        le=100,
        description="Opsional; endpoint by-focus tidak memakai BMI untuk memilih exercise.",
    )
    seed: Optional[int] = Field(default=None, ge=0, le=2**32 - 1)

    @field_validator("day_focus", mode="before")
    @classmethod
    def _normalise_day_focus(cls, value: Any) -> Any:
        if isinstance(value, str):
            return normalise_token(value)
        return value

    @field_validator("injuries", mode="before")
    @classmethod
    def _validate_injuries(cls, value: Any) -> List[str]:
        terms = _normalise_string_list(value, field_name="injuries")
        unknown = [term for term in terms if not is_valid_injury_term(term)]
        if unknown:
            examples = ", ".join(sorted(supported_injury_terms())[:20])
            raise ValueError(
                f"Cedera tidak dikenali: {', '.join(unknown)}. Contoh yang didukung: {examples}."
            )
        return terms

    @field_validator("preferred_body_part", mode="before")
    @classmethod
    def _normalise_body_part(cls, value: Any) -> Any:
        return _normalise_enum_list(value, field_name="preferred_body_part", enum_type=BodyPart)

    @field_validator("preferred_equipment", mode="before")
    @classmethod
    def _normalise_equipment(cls, value: Any) -> Any:
        return _normalise_enum_list(value, field_name="preferred_equipment", enum_type=Equipment)


class ByFocusResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    day_focus: Focus
    exercises: List[ExerciseOut]
    seed: int
    dataset_version: str
    algorithm_version: str

    @classmethod
    def from_day(
        cls,
        day: DayPlan,
        *,
        seed: int,
        dataset_version: str,
        algorithm_version: str,
    ) -> ByFocusResponse:
        return cls(
            day_focus=day.focus,
            exercises=[ExerciseOut.from_domain(exercise) for exercise in day.exercises],
            seed=seed,
            dataset_version=dataset_version,
            algorithm_version=algorithm_version,
        )


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: Optional[Any] = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str
