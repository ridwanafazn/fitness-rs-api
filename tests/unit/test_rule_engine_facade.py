from __future__ import annotations

import pytest

from app.core.errors import InvalidInputError
from app.rules.rule_engine import FitnessRuleEngine, UserInput


@pytest.mark.unit
def test_facade_runs_the_rule_table():
    engine = FitnessRuleEngine()
    engine.reset()
    engine.declare(
        UserInput(
            gender="male",
            bmi=22.0,
            available_days=2,
            preferred_body_part=["chest"],
        )
    )
    engine.run()
    split, schedule = engine.get_result()
    assert split == "upperlower"
    assert schedule == {"day_1": "upper", "day_2": "lower"}


@pytest.mark.unit
def test_facade_requires_input():
    engine = FitnessRuleEngine()
    with pytest.raises(InvalidInputError):
        engine.run()


@pytest.mark.unit
def test_facade_rejects_invalid_gender():
    engine = FitnessRuleEngine()
    engine.declare(UserInput(gender="robot", bmi=22.0, available_days=1))
    with pytest.raises(InvalidInputError):
        engine.run()


@pytest.mark.unit
def test_facade_requires_run_before_get_result():
    engine = FitnessRuleEngine()
    with pytest.raises(InvalidInputError):
        engine.get_result()
