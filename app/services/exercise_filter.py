"""Exercise pool filtering with hard injury constraints.

Safety rule: an exercise pool must never contain a body part that is in the
user's injury set.  If the remaining pool is too small we return the small pool
and let the orchestration layer raise a 422; we do not "helpfully" fall back to
the full dataset.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Optional, Set

from app.core.errors import InsufficientPoolError
from app.domain.constants import BodyPart, Equipment, Focus
from app.domain.focus import (
    is_exercise_focus,
    num_exercises_for_focus,
)
from app.domain.injuries import map_injury_to_body_parts
from app.domain.models import Exercise
from app.services.dataset import Dataset


def _matches_equipment(exercise: Exercise, preferred_equipment: Set[Equipment]) -> bool:
    # Body-weight movements are always available.  Otherwise at least one of
    # the exercise's equipment values must be in the user's preferred set.
    if Equipment.BODY_WEIGHT in exercise.equipment:
        return True
    if not preferred_equipment:
        return True
    return bool(set(exercise.equipment) & preferred_equipment)


def filter_exercises(
    dataset: Dataset,
    *,
    focus: Focus,
    injured_parts: Set[BodyPart],
    preferred_equipment: Set[Equipment],
    required: int,
) -> List[Exercise]:
    """Build a safe, focus-relevant pool for one day.

    The fallback ladder relaxes equipment and then focus, but **never**
    relaxes injuries.
    """

    safe = [exercise for exercise in dataset.exercises if exercise.body_part not in injured_parts]

    focus_safe = [exercise for exercise in safe if is_exercise_focus(exercise.body_part, focus)]

    # The thesis treats cardio as a separate session; fullbody excludes it.
    if focus is Focus.FULLBODY:
        focus_safe = [
            exercise for exercise in focus_safe if exercise.body_part is not BodyPart.CARDIO
        ]
    elif focus is Focus.CARDIO:
        focus_safe = [exercise for exercise in focus_safe if exercise.body_part is BodyPart.CARDIO]

    equipment_safe = [
        exercise for exercise in focus_safe if _matches_equipment(exercise, preferred_equipment)
    ]
    if len(equipment_safe) >= required:
        return equipment_safe

    if len(focus_safe) >= required:
        return focus_safe

    # Deliberately return the safe focus pool even if it is too small.  The
    # caller decides whether to fail with 422; it must not silently use the
    # full dataset.
    return focus_safe


def build_daily_pool(
    *,
    schedule: Mapping[str, Focus],
    dataset: Dataset,
    injuries: Iterable[str],
    preferred_equipment: Iterable[Equipment] = (),
    min_required: Optional[int] = None,
) -> Dict[str, List[Exercise]]:
    """Build one pool per scheduled day.

    Args:
        schedule: ordered mapping of ``day_1`` -> focus.
        dataset: validated exercise dataset.
        injuries: raw injury terms (joints, muscles, body parts).
        preferred_equipment: validated equipment preferences.
        min_required: override for the minimum pool size.  By default each day
            needs exactly the number of genes the GA will request.

    Raises:
        UnknownInjuryError: if an injury term is not supported.
        InsufficientPoolError: if a day has fewer than the required exercises.
    """

    injured_parts = map_injury_to_body_parts(injuries)
    preferred = set(preferred_equipment)
    daily_pool: Dict[str, List[Exercise]] = {}

    for day_key, focus in schedule.items():
        required = min_required or num_exercises_for_focus(focus)
        pool = filter_exercises(
            dataset,
            focus=focus,
            injured_parts=injured_parts,
            preferred_equipment=preferred,
            required=required,
        )
        if len(pool) < required:
            raise InsufficientPoolError(
                details={
                    "day": day_key,
                    "focus": focus.value,
                    "required": required,
                    "available": len(pool),
                    "injuries": sorted(part.value for part in injured_parts),
                    "hint": (
                        "Kurangi area cedera atau longgarkan preferensi alat. "
                        "Sistem tidak akan mengembalikan latihan yang cedera."
                    ),
                }
            )
        daily_pool[day_key] = pool

    return daily_pool
