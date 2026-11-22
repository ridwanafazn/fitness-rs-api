"""Focus-to-body-part helpers used by filtering and the GA."""

from __future__ import annotations

from app.domain.constants import (
    FOCUS_TO_BODY_PARTS,
    BodyPart,
    Focus,
    coerce_focus,
)

# A specific body-part focus gets 4 exercises; cardio gets 3; composite
# focuses (upper/lower/push/pull/legs/fullbody) get 5.
SPECIFIC_BODY_PART_FOCUSES = frozenset(
    Focus(part.value) for part in BodyPart if part is not BodyPart.CARDIO
)


def is_exercise_focus(body_part: str | BodyPart, focus: str | Focus) -> bool:
    part = body_part if isinstance(body_part, BodyPart) else BodyPart(body_part)
    target = coerce_focus(focus)
    return part in FOCUS_TO_BODY_PARTS[target]


def num_exercises_for_focus(focus: str | Focus) -> int:
    target = coerce_focus(focus)
    if target is Focus.CARDIO:
        return 3
    if target in SPECIFIC_BODY_PART_FOCUSES:
        return 4
    return 5
