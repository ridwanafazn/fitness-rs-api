from __future__ import annotations

import pytest

from app.core.errors import InvalidInputError, UnsupportedDaysError
from app.domain.constants import BodyPart, Focus, Gender
from app.domain.rules import build_rule_result


@pytest.mark.unit
@pytest.mark.parametrize("gender", [Gender.MALE, Gender.FEMALE])
@pytest.mark.parametrize("bmi", [22.0, 27.0])
@pytest.mark.parametrize("days", [1, 2, 3, 4, 5])
def test_rule_matrix_has_correct_number_of_days(gender, bmi, days):
    result = build_rule_result(
        gender=gender,
        bmi=bmi,
        available_days=days,
    )

    assert len(result.schedule) == days
    assert set(result.schedule) == {f"day_{index}" for index in range(1, days + 1)}
    assert all(isinstance(focus, Focus) for focus in result.schedule.values())


@pytest.mark.unit
@pytest.mark.parametrize("gender", [Gender.MALE, Gender.FEMALE])
def test_three_day_normal_bmi_uses_ppl(gender):
    result = build_rule_result(gender=gender, bmi=22.0, available_days=3)
    assert result.split_method == "ppl"
    assert [focus.value for focus in result.schedule.values()] == [
        "push",
        "pull",
        "legs",
    ]


@pytest.mark.unit
@pytest.mark.parametrize("gender", [Gender.MALE, Gender.FEMALE])
def test_three_day_overweight_injects_cardio(gender):
    result = build_rule_result(gender=gender, bmi=27.0, available_days=3)
    assert result.split_method == "upperlower"
    assert [focus.value for focus in result.schedule.values()] == [
        "upper",
        "lower",
        "cardio",
    ]


@pytest.mark.unit
def test_five_day_normal_bmi_uses_two_focus_days():
    result = build_rule_result(gender=Gender.MALE, bmi=22.0, available_days=5)
    assert result.split_method == "ppl+focus"
    assert len(result.schedule) == 5
    assert list(result.schedule.values())[:3] == [
        Focus.PUSH,
        Focus.PULL,
        Focus.LEGS,
    ]


@pytest.mark.unit
def test_preference_outside_gender_default_is_respected():
    # A male user who wants glutes should still get a glute-focused day.
    result = build_rule_result(
        gender=Gender.MALE,
        bmi=22.0,
        available_days=5,
        preferred_body_part=(BodyPart.GLUTES,),
    )
    focus_values = [focus.value for focus in result.schedule.values()]
    assert "glutes" in focus_values


@pytest.mark.unit
def test_preference_for_female_chest_is_respected():
    result = build_rule_result(
        gender=Gender.FEMALE,
        bmi=22.0,
        available_days=5,
        preferred_body_part=(BodyPart.CHEST,),
    )
    focus_values = [focus.value for focus in result.schedule.values()]
    assert "chest" in focus_values


@pytest.mark.unit
def test_injured_preference_is_not_used_for_focus_days():
    result = build_rule_result(
        gender=Gender.MALE,
        bmi=22.0,
        available_days=5,
        preferred_body_part=(BodyPart.CHEST,),
        injured_body_parts={BodyPart.CHEST},
    )
    focus_values = [focus.value for focus in result.schedule.values()]
    assert "chest" not in focus_values[3:]


@pytest.mark.unit
def test_leg_day_is_replaced_when_all_leg_parts_are_injured():
    result = build_rule_result(
        gender=Gender.MALE,
        bmi=22.0,
        available_days=3,
        injured_body_parts={
            BodyPart.QUADRICEPS,
            BodyPart.HAMSTRINGS,
            BodyPart.GLUTES,
            BodyPart.CALVES,
        },
    )
    assert result.schedule["day_3"] is Focus.CARDIO
    assert result.warnings


@pytest.mark.unit
def test_no_safe_focus_raises():
    with pytest.raises(InvalidInputError):
        build_rule_result(
            gender=Gender.MALE,
            bmi=22.0,
            available_days=1,
            injured_body_parts=set(BodyPart),
        )


@pytest.mark.unit
@pytest.mark.parametrize("days", [0, 6, 7, -1])
def test_unsupported_days_raise(days):
    with pytest.raises(UnsupportedDaysError):
        build_rule_result(gender=Gender.MALE, bmi=22.0, available_days=days)
