"""Immutable domain models shared by rules, filters, GA and API schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from app.domain.constants import BodyPart, Equipment, Focus, Gender


@dataclass(frozen=True)
class Exercise:
    exercise_id: str
    exercise_name: str
    body_part: BodyPart
    equipment: Tuple[Equipment, ...]
    primary_muscle: Tuple[str, ...]
    secondary_muscle: Tuple[str, ...]
    exercise_type: str
    movement_type: str
    image_url: Optional[str] = None

    @property
    def name_lower(self) -> str:
        return self.exercise_name.strip().lower()


@dataclass(frozen=True)
class UserProfile:
    gender: Gender
    height_cm: float
    weight_kg: float
    injuries: Tuple[str, ...] = ()
    available_days: int = 3
    preferred_body_part: Tuple[BodyPart, ...] = ()
    preferred_equipment: Tuple[Equipment, ...] = ()
    seed: Optional[int] = None

    @property
    def bmi(self) -> float:
        height_m = self.height_cm / 100.0
        return round(self.weight_kg / (height_m**2), 2)

    @property
    def bmi_category(self) -> str:
        bmi = self.bmi
        if bmi < 18.5:
            return "Underweight"
        if bmi < 25:
            return "Normal"
        if bmi < 30:
            return "Overweight"
        if bmi < 35:
            return "Obese I"
        if bmi < 40:
            return "Obese II"
        return "Obese III"


@dataclass(frozen=True)
class RuleResult:
    split_method: str
    schedule: Dict[str, Focus]
    focus_order: Tuple[BodyPart, ...] = ()
    warnings: Tuple[str, ...] = ()


@dataclass(frozen=True)
class DayPlan:
    day: int
    focus: Focus
    exercises: Tuple[Exercise, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class RecommendationPlan:
    bmi: float
    bmi_category: str
    split_type: str
    schedule: Dict[str, Focus]
    days: Tuple[DayPlan, ...]
    seed: int
    dataset_version: str
    algorithm_version: str
    warnings: Tuple[str, ...] = ()
