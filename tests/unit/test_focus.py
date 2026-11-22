from __future__ import annotations

import pytest

from app.domain.constants import BodyPart, Focus
from app.domain.focus import is_exercise_focus, num_exercises_for_focus


@pytest.mark.unit
@pytest.mark.parametrize(
    ("body_part", "focus", "expected"),
    [
        (BodyPart.CHEST, Focus.UPPER, True),
        (BodyPart.CHEST, Focus.PUSH, True),
        (BodyPart.CHEST, Focus.PULL, False),
        (BodyPart.CALVES, Focus.LOWER, True),
        (BodyPart.CALVES, Focus.UPPER, False),
        (BodyPart.BACK, Focus.PULL, True),
        (BodyPart.ABS, Focus.LEGS, False),
        (BodyPart.CARDIO, Focus.FULLBODY, False),
        (BodyPart.CARDIO, Focus.CARDIO, True),
        (BodyPart.CHEST, Focus.CHEST, True),
        (BodyPart.BACK, Focus.CHEST, False),
    ],
)
def test_focus_mapping(body_part, focus, expected):
    assert is_exercise_focus(body_part, focus) is expected


@pytest.mark.unit
@pytest.mark.parametrize(
    ("focus", "expected"),
    [
        (Focus.CARDIO, 3),
        (Focus.CHEST, 4),
        (Focus.BACK, 4),
        (Focus.UPPER, 5),
        (Focus.LOWER, 5),
        (Focus.FULLBODY, 5),
        (Focus.PUSH, 5),
    ],
)
def test_num_exercises_for_focus(focus, expected):
    assert num_exercises_for_focus(focus) == expected
