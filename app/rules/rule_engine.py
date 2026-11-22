"""Compatibility facade for the original rule-engine API.

The production path calls :func:`app.domain.rules.build_rule_result` directly.
This facade keeps the old ``FitnessRuleEngine``/``UserInput`` interface for
existing scripts and tests without importing the unmaintained ``experta``
package.

The original Experta implementation is preserved in git history; the decision
table is behaviourally equivalent for the one rule the thesis actually uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.core.errors import InvalidInputError
from app.domain.constants import Gender, coerce_body_part
from app.domain.injuries import map_injury_to_body_parts
from app.domain.models import RuleResult
from app.domain.rules import build_rule_result


@dataclass
class UserInput:
    gender: str
    bmi: float
    injuries: List[str] = field(default_factory=list)
    available_days: int = 1
    preferred_body_part: List[str] = field(default_factory=list)


@dataclass
class Recommendation:
    split_method: str
    schedule: Dict[str, str]


class FitnessRuleEngine:
    """Stateful facade around the pure rule table."""

    def __init__(self) -> None:
        self._user_input: Optional[UserInput] = None
        self._result: Optional[RuleResult] = None

    def reset(self) -> None:
        self._user_input = None
        self._result = None

    def declare(self, fact: UserInput) -> None:
        self._user_input = fact

    def run(self) -> None:
        if self._user_input is None:
            raise InvalidInputError("UserInput belum dideklarasikan.")

        try:
            gender = Gender(self._user_input.gender.lower())
        except ValueError as exc:
            raise InvalidInputError("Gender harus male atau female.") from exc

        try:
            preferred = tuple(
                coerce_body_part(item)
                for item in self._user_input.preferred_body_part
            )
        except ValueError as exc:
            raise InvalidInputError("preferred_body_part tidak valid.") from exc

        injured = map_injury_to_body_parts(self._user_input.injuries)

        self._result = build_rule_result(
            gender=gender,
            bmi=self._user_input.bmi,
            available_days=self._user_input.available_days,
            preferred_body_part=preferred,
            injured_body_parts=injured,
        )

    def get_result(self) -> Tuple[str, Dict[str, str]]:
        if self._result is None:
            raise InvalidInputError("Rule engine belum dijalankan.")
        return (
            self._result.split_method,
            {day: focus.value for day, focus in self._result.schedule.items()},
        )
