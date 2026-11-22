from __future__ import annotations

import pytest

from app.core.errors import InsufficientPoolError
from app.domain.constants import BodyPart, Focus
from app.domain.models import Exercise
from app.services.genetic_optimizer import GAConfig, run_ga_schedule
from tests.helpers import make_exercise

FAST_GA = GAConfig(
    num_generations=5,
    sol_per_pop=10,
    num_parents_mating=4,
    keep_parents=2,
    random_seed=42,
)


def _chest_pool() -> list[Exercise]:
    muscles = [
        "upper chest",
        "middle chest",
        "lower chest",
        "pectoralis major",
        "front deltoids",
        "triceps brachii",
        "serratus",
        "rectus abdominis",
    ]
    return [
        make_exercise(
            str(index),
            body_part=BodyPart.CHEST,
            primary=(muscle,),
            secondary=("triceps",),
        )
        for index, muscle in enumerate(muscles, start=1)
    ]


@pytest.mark.unit
def test_ga_returns_expected_number_of_unique_exercises():
    daywise = run_ga_schedule(
        {"day_1": Focus.CHEST},
        {"day_1": _chest_pool()},
        injured_body_parts=set(),
        preferred_body_parts=set(),
        config=FAST_GA,
    )
    day = daywise["day_1"]
    assert len(day.exercises) == 4
    assert len({exercise.exercise_id for exercise in day.exercises}) == 4
    assert all(exercise.body_part is BodyPart.CHEST for exercise in day.exercises)


@pytest.mark.unit
def test_same_seed_is_reproducible():
    kwargs = {
        "schedule": {"day_1": Focus.CHEST},
        "daily_exercise_pool": {"day_1": _chest_pool()},
        "injured_body_parts": set(),
        "preferred_body_parts": set(),
        "config": FAST_GA,
    }
    first = run_ga_schedule(**kwargs)["day_1"]
    second = run_ga_schedule(**kwargs)["day_1"]
    assert [e.exercise_id for e in first.exercises] == [
        e.exercise_id for e in second.exercises
    ]


@pytest.mark.unit
def test_pool_smaller_than_num_genes_raises():
    pool = _chest_pool()[:3]
    with pytest.raises(InsufficientPoolError):
        run_ga_schedule(
            {"day_1": Focus.CHEST},
            {"day_1": pool},
            injured_body_parts=set(),
            preferred_body_parts=set(),
            config=FAST_GA,
        )


@pytest.mark.unit
def test_cardio_post_processing_keeps_one_run():
    pool = [
        make_exercise("1", name="run", body_part=BodyPart.CARDIO),
        make_exercise("2", name="walking on treadmill", body_part=BodyPart.CARDIO),
        make_exercise("3", name="stationary bike run", body_part=BodyPart.CARDIO),
        make_exercise("4", name="elliptical machine walk", body_part=BodyPart.CARDIO),
        make_exercise("5", name="walking", body_part=BodyPart.CARDIO),
    ]
    daywise = run_ga_schedule(
        {"day_1": Focus.CARDIO},
        {"day_1": pool},
        injured_body_parts=set(),
        preferred_body_parts=set(),
        config=FAST_GA,
    )
    selected = daywise["day_1"].exercises
    assert 1 <= len(selected) <= 2
    assert all(exercise.body_part is BodyPart.CARDIO for exercise in selected)
    if any(exercise.name_lower == "run" for exercise in selected):
        assert len(selected) == 1


@pytest.mark.unit
def test_ga_can_handle_upper_focus_pool():
    pool = [
        make_exercise("1", body_part=BodyPart.CHEST),
        make_exercise("2", body_part=BodyPart.BACK),
        make_exercise("3", body_part=BodyPart.SHOULDERS),
        make_exercise("4", body_part=BodyPart.BICEPS),
        make_exercise("5", body_part=BodyPart.TRICEPS),
        make_exercise("6", body_part=BodyPart.FOREARMS),
        make_exercise("7", body_part=BodyPart.NECK),
        make_exercise("8", body_part=BodyPart.ABS),
    ]
    daywise = run_ga_schedule(
        {"day_1": Focus.UPPER},
        {"day_1": pool},
        injured_body_parts=set(),
        preferred_body_parts={BodyPart.CHEST},
        config=FAST_GA,
    )
    assert len(daywise["day_1"].exercises) == 5
