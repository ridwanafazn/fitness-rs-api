from __future__ import annotations

import pytest

from app.core.errors import InsufficientPoolError
from app.domain.constants import BodyPart, Equipment, Focus
from app.services.dataset import load_dataset
from app.services.exercise_filter import build_daily_pool, filter_exercises


@pytest.mark.integration
def test_injured_focus_returns_empty_not_full_dataset(dataset_path):
    dataset = load_dataset(dataset_path)
    pool = filter_exercises(
        dataset,
        focus=Focus.CHEST,
        injured_parts={BodyPart.CHEST},
        preferred_equipment=set(),
        required=4,
    )
    assert pool == []


@pytest.mark.integration
def test_injured_focus_raises_in_build_daily_pool(dataset_path):
    dataset = load_dataset(dataset_path)
    with pytest.raises(InsufficientPoolError):
        build_daily_pool(
            schedule={"day_1": Focus.CHEST},
            dataset=dataset,
            injuries=["chest"],
        )


@pytest.mark.integration
def test_equipment_preference_is_respected_when_pool_is_large(dataset_path):
    dataset = load_dataset(dataset_path)
    pool = filter_exercises(
        dataset,
        focus=Focus.CHEST,
        injured_parts=set(),
        preferred_equipment={Equipment.DUMBBELL},
        required=4,
    )
    assert pool
    for exercise in pool:
        assert (
            Equipment.BODY_WEIGHT in exercise.equipment
            or Equipment.DUMBBELL in exercise.equipment
        )


@pytest.mark.integration
def test_fullbody_excludes_cardio(dataset_path):
    dataset = load_dataset(dataset_path)
    pool = filter_exercises(
        dataset,
        focus=Focus.FULLBODY,
        injured_parts=set(),
        preferred_equipment=set(),
        required=5,
    )
    assert pool
    assert all(exercise.body_part is not BodyPart.CARDIO for exercise in pool)


@pytest.mark.integration
def test_knee_injury_does_not_return_leg_exercises(dataset_path):
    dataset = load_dataset(dataset_path)
    pool = filter_exercises(
        dataset,
        focus=Focus.UPPER,
        injured_parts={
            BodyPart.QUADRICEPS,
            BodyPart.HAMSTRINGS,
            BodyPart.GLUTES,
            BodyPart.CALVES,
        },
        preferred_equipment=set(),
        required=5,
    )
    assert pool
    assert all(
        exercise.body_part
        not in {BodyPart.QUADRICEPS, BodyPart.HAMSTRINGS, BodyPart.GLUTES, BodyPart.CALVES}
        for exercise in pool
    )


@pytest.mark.integration
def test_leg_focus_with_knee_injury_fails_safely(dataset_path):
    dataset = load_dataset(dataset_path)
    with pytest.raises(InsufficientPoolError):
        build_daily_pool(
            schedule={"day_1": Focus.LOWER},
            dataset=dataset,
            injuries=["knee"],
        )
