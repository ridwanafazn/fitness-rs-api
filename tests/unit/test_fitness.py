from __future__ import annotations

import pytest

from app.domain.constants import BodyPart, Focus
from app.domain.fitness import (
    body_part_variation_penalty,
    count_injured_exercises,
    score_solution,
)
from tests.helpers import make_exercise


@pytest.mark.unit
def test_composite_focus_rewards_relevant_body_part():
    chest = make_exercise("1", body_part=BodyPart.CHEST)
    calves = make_exercise("2", body_part=BodyPart.CALVES)

    chest_score = score_solution(
        [chest],
        focus=Focus.UPPER,
        injured_parts=set(),
        preferred_parts=set(),
        available_parts={BodyPart.CHEST, BodyPart.CALVES},
    )
    calves_score = score_solution(
        [calves],
        focus=Focus.UPPER,
        injured_parts=set(),
        preferred_parts=set(),
        available_parts={BodyPart.CHEST, BodyPart.CALVES},
    )

    assert chest_score > calves_score


@pytest.mark.unit
def test_injury_is_a_large_penalty():
    chest = make_exercise("1", body_part=BodyPart.CHEST)
    safe_score = score_solution(
        [chest],
        focus=Focus.CHEST,
        injured_parts=set(),
        preferred_parts=set(),
        available_parts={BodyPart.CHEST},
    )
    injured_score = score_solution(
        [chest],
        focus=Focus.CHEST,
        injured_parts={BodyPart.CHEST},
        preferred_parts=set(),
        available_parts={BodyPart.CHEST},
    )
    assert injured_score < safe_score
    assert safe_score - injured_score >= 1000


@pytest.mark.unit
def test_preference_adds_a_bonus():
    chest = make_exercise("1", body_part=BodyPart.CHEST)
    without = score_solution(
        [chest],
        focus=Focus.CHEST,
        injured_parts=set(),
        preferred_parts=set(),
        available_parts={BodyPart.CHEST},
    )
    with_pref = score_solution(
        [chest],
        focus=Focus.CHEST,
        injured_parts=set(),
        preferred_parts={BodyPart.CHEST},
        available_parts={BodyPart.CHEST},
    )
    assert with_pref > without


@pytest.mark.unit
def test_duplicate_body_part_is_penalised():
    chest_a = make_exercise("1", body_part=BodyPart.CHEST)
    chest_b = make_exercise("2", body_part=BodyPart.CHEST)
    back = make_exercise("3", body_part=BodyPart.BACK)

    duplicate = score_solution(
        [chest_a, chest_b],
        focus=Focus.UPPER,
        injured_parts=set(),
        preferred_parts=set(),
        available_parts={BodyPart.CHEST, BodyPart.BACK},
    )
    varied = score_solution(
        [chest_a, back],
        focus=Focus.UPPER,
        injured_parts=set(),
        preferred_parts=set(),
        available_parts={BodyPart.CHEST, BodyPart.BACK},
    )
    assert varied > duplicate


@pytest.mark.unit
def test_specific_body_part_day_is_exempt_from_body_part_spread_penalty():
    penalty = body_part_variation_penalty(
        [BodyPart.CHEST, BodyPart.CHEST, BodyPart.CHEST, BodyPart.CHEST],
        Focus.CHEST,
        {BodyPart.CHEST},
    )
    assert penalty == 0


@pytest.mark.unit
def test_count_injured_exercises():
    exercises = [
        make_exercise("1", body_part=BodyPart.CHEST),
        make_exercise("2", body_part=BodyPart.BACK),
    ]
    assert count_injured_exercises(exercises, {BodyPart.CHEST}) == 1
