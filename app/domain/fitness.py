"""Fitness scoring for the genetic algorithm.

The scoring function is pure and deterministic.  Safety is a hard constraint
(the caller removes injured body parts from the gene space), but we still add a
large penalty as defence in depth.  Soft preferences use smaller weights.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence, Set

from app.domain.constants import (
    CARDIO_INDOOR_EXERCISES,
    CARDIO_RUN_EXERCISES,
    FOCUS_TO_BODY_PARTS,
    BodyPart,
    Focus,
)
from app.domain.focus import (
    SPECIFIC_BODY_PART_FOCUSES,
    is_exercise_focus,
    num_exercises_for_focus,
)
from app.domain.models import Exercise


@dataclass(frozen=True)
class FitnessWeights:
    focus_match: float = 2.0
    focus_miss: float = -3.0
    preference: float = 1.0
    injury: float = -1000.0
    duplicate_body_part: float = -2.0
    body_part_variation: float = 10.0
    muscle_variation_primary: float = 3.0
    muscle_variation_secondary: float = 1.0
    cardio_run_penalty: float = 10.0
    cardio_indoor_penalty: float = 10.0


DEFAULT_WEIGHTS = FitnessWeights()


def _is_run(exercise: Exercise) -> bool:
    return exercise.name_lower in CARDIO_RUN_EXERCISES


def _is_indoor_cardio(exercise: Exercise) -> bool:
    return exercise.name_lower in CARDIO_INDOOR_EXERCISES


def body_part_variation_penalty(
    seen_parts: Sequence[BodyPart],
    focus: Focus,
    available_parts: Set[BodyPart],
    *,
    weights: FitnessWeights = DEFAULT_WEIGHTS,
) -> float:
    """Return a penalty (positive) or reward (negative) for body-part spread.

    Specific body-part days and cardio days intentionally use one body part, so
    they are exempt from this term.  The original implementation penalised them
    constantly, which added noise without changing the ranking.
    """

    if focus in SPECIFIC_BODY_PART_FOCUSES or focus is Focus.CARDIO:
        return 0.0

    unique_parts = set(seen_parts)
    part_counts = Counter(seen_parts)
    most_common_count = part_counts.most_common(1)[0][1] if part_counts else 0

    expected = FOCUS_TO_BODY_PARTS[focus] & available_parts
    n_available = len(expected)

    penalty = 0.0
    if n_available >= 3:
        if len(unique_parts) < 3:
            penalty += weights.body_part_variation
        if most_common_count >= 4:
            penalty += weights.body_part_variation
        if len(unique_parts) == 3:
            penalty -= 2.0
        elif len(unique_parts) == 4:
            penalty -= 3.0
        elif len(unique_parts) >= 5:
            penalty -= 5.0
    else:
        if len(unique_parts) < 2:
            penalty += weights.body_part_variation

    return penalty


def muscle_variation_penalty(
    exercises: Sequence[Exercise],
    *,
    weights: FitnessWeights = DEFAULT_WEIGHTS,
) -> float:
    primary = [muscle for ex in exercises for muscle in ex.primary_muscle]
    secondary = [muscle for ex in exercises for muscle in ex.secondary_muscle]

    unique_primary = set(primary)
    unique_secondary = set(secondary)

    penalty = 0.0
    if len(unique_primary) < 2:
        penalty += weights.muscle_variation_primary * (2 - len(unique_primary))
    if len(unique_secondary) < 2:
        penalty += weights.muscle_variation_secondary * (2 - len(unique_secondary))
    return penalty


def score_solution(
    exercises: Sequence[Exercise],
    *,
    focus: Focus,
    injured_parts: Set[BodyPart],
    preferred_parts: Set[BodyPart],
    available_parts: Set[BodyPart],
    weights: FitnessWeights = DEFAULT_WEIGHTS,
) -> float:
    """Score one candidate solution for one training day."""

    score = 0.0
    seen_body_parts: list[BodyPart] = []

    run_count = 0
    indoor_count = 0
    cardio_count = 0

    for exercise in exercises:
        body_part = exercise.body_part

        if body_part in injured_parts:
            score += weights.injury

        if is_exercise_focus(body_part, focus):
            score += weights.focus_match
        else:
            score += weights.focus_miss

        if body_part in preferred_parts:
            score += weights.preference

        if body_part is BodyPart.CARDIO:
            cardio_count += 1
            if _is_run(exercise):
                run_count += 1
            if _is_indoor_cardio(exercise):
                indoor_count += 1

        seen_body_parts.append(body_part)

    score -= body_part_variation_penalty(
        seen_body_parts, focus, available_parts, weights=weights
    )
    score -= muscle_variation_penalty(exercises, weights=weights)

    duplicate_count = len(seen_body_parts) - len(set(seen_body_parts))
    if duplicate_count:
        score += weights.duplicate_body_part * duplicate_count

    if run_count > 1:
        score -= weights.cardio_run_penalty
    if indoor_count > 1:
        score -= weights.cardio_indoor_penalty

    # Cardio should not exceed the expected number of slots for the day.
    expected_cardio = num_exercises_for_focus(focus) if focus is Focus.CARDIO else 0
    if cardio_count > expected_cardio:
        score -= (cardio_count - expected_cardio) * 2.0

    return score


def count_injured_exercises(
    exercises: Iterable[Exercise], injured_parts: Set[BodyPart]
) -> int:
    """Used by integration tests and output validation."""

    return sum(1 for exercise in exercises if exercise.body_part in injured_parts)
