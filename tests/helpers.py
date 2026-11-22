"""Test factories."""

from __future__ import annotations

from typing import Iterable, Optional

from app.domain.constants import BodyPart, Equipment
from app.domain.models import Exercise


def make_exercise(
    exercise_id: str = "1",
    name: Optional[str] = None,
    body_part: BodyPart = BodyPart.CHEST,
    equipment: Iterable[Equipment] = (Equipment.BODY_WEIGHT,),
    primary: Iterable[str] = ("pectoralis major",),
    secondary: Iterable[str] = (),
    exercise_type: str = "weight_reps",
    movement_type: str = "compound",
) -> Exercise:
    return Exercise(
        exercise_id=exercise_id,
        exercise_name=name or f"{body_part.value} exercise {exercise_id}",
        body_part=body_part,
        equipment=tuple(equipment),
        primary_muscle=tuple(primary),
        secondary_muscle=tuple(secondary),
        exercise_type=exercise_type,
        movement_type=movement_type,
    )
