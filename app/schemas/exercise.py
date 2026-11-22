"""API representation of an exercise."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.domain.constants import BodyPart, Equipment
from app.domain.models import Exercise


class ExerciseOut(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        from_attributes=True,
        use_enum_values=True,
    )

    exercise_id: str
    exercise_name: str
    body_part: BodyPart
    equipment: List[Equipment]
    primary_muscle: List[str]
    secondary_muscle: List[str] = Field(default_factory=list)
    # Preserve the original response key used by the existing frontend.
    image_url: Optional[str] = Field(None, alias="exercise_image")

    @classmethod
    def from_domain(cls, exercise: Exercise) -> ExerciseOut:
        return cls(
            exercise_id=exercise.exercise_id,
            exercise_name=exercise.exercise_name,
            body_part=exercise.body_part,
            equipment=list(exercise.equipment),
            primary_muscle=list(exercise.primary_muscle),
            secondary_muscle=list(exercise.secondary_muscle),
            exercise_image=exercise.image_url,
        )
