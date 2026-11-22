"""Deterministic rule table for split selection.

This is the production implementation of the thesis' forward-chaining rule
engine.  It is intentionally a pure function: no FastAPI, no pandas, no global
state.  The original Experta implementation can be kept as a research artifact,
but the runtime no longer depends on an unmaintained 2019 library.

The rule table mirrors thesis Table 3.9, with one deliberate documentation fix:
BMI 25.0 is treated as overweight (``>= 25``), matching WHO/Kemenkes.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from app.core.errors import InvalidInputError, UnsupportedDaysError
from app.domain.constants import (
    FOCUS_MIN_SAFE_PARTS,
    FOCUS_TO_BODY_PARTS,
    GENDER_DEFAULT_FOCUS,
    GENDER_PRIORITY,
    SPLIT_FULLBODY,
    SPLIT_PPL,
    SPLIT_PPL_FOCUS,
    SPLIT_UPPERLOWER,
    SPLIT_UPPERLOWER_FOCUS,
    BodyPart,
    Focus,
    Gender,
)
from app.domain.models import RuleResult

PREFERENCE_BONUS = 5
INJURY_PENALTY = -100


def _unique(items: Iterable[BodyPart]) -> List[BodyPart]:
    seen = set()
    result: List[BodyPart] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _focus_scores(
    gender: Gender,
    preferred: Tuple[BodyPart, ...],
    injured: Iterable[BodyPart],
) -> List[BodyPart]:
    """Rank focus options, with preferences first and injuries last."""

    injured_set = set(injured)
    preferred_unique = _unique(preferred)
    focus_options = _unique(list(GENDER_DEFAULT_FOCUS[gender]) + list(preferred_unique))

    scores: Dict[BodyPart, int] = dict.fromkeys(focus_options, 0)

    if preferred_unique:
        for part in preferred_unique:
            if part in scores:
                scores[part] += PREFERENCE_BONUS
    else:
        priority = GENDER_PRIORITY[gender]
        for part in focus_options:
            scores[part] -= priority.get(part, 100)

    for part in focus_options:
        if part in injured_set:
            scores[part] += INJURY_PENALTY

    # Stable sort: ties keep the gender/default order.
    ranked = sorted(focus_options, key=lambda part: scores[part], reverse=True)

    # Prefer safe focuses for the extra focus days.  If every option is
    # injured we keep the ranking; the schedule adapter will later replace the
    # day with a safe focus (or reject the request).
    safe = [part for part in ranked if part not in injured_set]
    unsafe = [part for part in ranked if part in injured_set]
    if safe:
        ranked = safe + unsafe
    return ranked


def _focus_is_viable(focus: Focus, injured: set[BodyPart]) -> bool:
    if focus is Focus.CARDIO:
        return BodyPart.CARDIO not in injured
    safe_parts = FOCUS_TO_BODY_PARTS[focus] - injured
    return len(safe_parts) >= FOCUS_MIN_SAFE_PARTS.get(focus, 1)


def _adapt_schedule_for_injuries(
    schedule: Dict[str, Focus],
    focus_order: List[BodyPart],
    injured: Iterable[BodyPart],
) -> Tuple[Dict[str, Focus], Tuple[str, ...]]:
    """Replace a focus that has no safe body parts with a safe alternative.

    Safety is still absolute; this only prevents a 422 when, for example, a
    knee injury makes the lower-body day impossible but upper-body training is
    perfectly safe.
    """

    injured_set = set(injured)
    warnings: List[str] = []

    for day_key, focus in list(schedule.items()):
        if _focus_is_viable(focus, injured_set):
            continue

        replacement: Optional[Focus] = None
        original_parts = FOCUS_TO_BODY_PARTS[focus]

        # Prefer a specific safe part of the original focus (e.g. a quads day
        # instead of a lower day).  Fall back to cardio, then to any safe focus.
        for part in focus_order:
            if part not in original_parts:
                continue
            candidate = Focus(part.value)
            if _focus_is_viable(candidate, injured_set):
                replacement = candidate
                break

        if replacement is None and BodyPart.CARDIO not in injured_set:
            replacement = Focus.CARDIO

        if replacement is None:
            for part in focus_order:
                candidate = Focus(part.value)
                if _focus_is_viable(candidate, injured_set):
                    replacement = candidate
                    break

        if replacement is None:
            raise InvalidInputError(
                "Tidak ada area tubuh yang aman untuk disusun menjadi jadwal.",
                details={
                    "injuries": sorted(part.value for part in injured_set),
                },
            )

        schedule[day_key] = replacement
        warnings.append(
            f"{day_key}: fokus '{focus.value}' diganti menjadi '{replacement.value}' karena cedera."
        )

    return schedule, tuple(warnings)


def build_rule_result(
    *,
    gender: Gender,
    bmi: float,
    available_days: int,
    preferred_body_part: Tuple[BodyPart, ...] = (),
    injured_body_parts: Iterable[BodyPart] = (),
) -> RuleResult:
    """Build the split and day-focus schedule.

    Args:
        gender: ``male`` or ``female``.
        bmi: pre-computed BMI.
        available_days: 1..5.
        preferred_body_part: user focus preferences, already validated.
        injured_body_parts: mapped body parts to avoid.

    Raises:
        UnsupportedDaysError: when ``available_days`` is outside 1..5.
    """

    if available_days < 1 or available_days > 5:
        raise UnsupportedDaysError(
            details={"available_days": available_days, "allowed": [1, 2, 3, 4, 5]}
        )

    injured = set(injured_body_parts)

    focus_order = _focus_scores(
        gender=gender,
        preferred=preferred_body_part,
        injured=injured,
    )

    overweight = bmi >= 25.0
    schedule: Dict[str, Focus] = {}
    split = SPLIT_FULLBODY

    if available_days == 1:
        split = SPLIT_FULLBODY
        schedule["day_1"] = Focus.CARDIO if overweight else Focus.FULLBODY
    elif available_days == 2:
        split = SPLIT_UPPERLOWER
        schedule["day_1"] = Focus.UPPER
        schedule["day_2"] = Focus.CARDIO if overweight else Focus.LOWER
    elif available_days == 3:
        if overweight:
            split = SPLIT_UPPERLOWER
            schedule = {
                "day_1": Focus.UPPER,
                "day_2": Focus.LOWER,
                "day_3": Focus.CARDIO,
            }
        else:
            split = SPLIT_PPL
            schedule = {
                "day_1": Focus.PUSH,
                "day_2": Focus.PULL,
                "day_3": Focus.LEGS,
            }
    elif available_days == 4:
        split = SPLIT_UPPERLOWER
        if overweight:
            schedule = {
                "day_1": Focus.UPPER,
                "day_2": Focus.CARDIO,
                "day_3": Focus.LOWER,
                "day_4": Focus.CARDIO,
            }
        else:
            schedule = {
                "day_1": Focus.UPPER,
                "day_2": Focus.LOWER,
                "day_3": Focus.UPPER,
                "day_4": Focus.LOWER,
            }
    else:  # 5 days
        if overweight:
            split = SPLIT_UPPERLOWER_FOCUS
            schedule = {
                "day_1": Focus.UPPER,
                "day_2": Focus.CARDIO,
                "day_3": Focus(focus_order[0].value),
                "day_4": Focus.CARDIO,
                "day_5": Focus.LOWER,
            }
        else:
            split = SPLIT_PPL_FOCUS
            schedule = {
                "day_1": Focus.PUSH,
                "day_2": Focus.PULL,
                "day_3": Focus.LEGS,
                "day_4": Focus(focus_order[0].value),
                "day_5": Focus(focus_order[1].value),
            }

    schedule, warnings = _adapt_schedule_for_injuries(schedule, focus_order, injured)

    return RuleResult(
        split_method=split,
        schedule=schedule,
        focus_order=tuple(focus_order),
        warnings=warnings,
    )
