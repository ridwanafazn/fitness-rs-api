"""Canonical fitness-domain vocabulary.

Everything that used to be duplicated across the rule engine, filter and GA
now lives here.  Keeping one source of truth prevents the classic bug where
the filter understands ``chest`` but the fitness function expects ``Chest``.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, FrozenSet, Set


class Gender(str, Enum):
    MALE = "male"
    FEMALE = "female"


class BodyPart(str, Enum):
    NECK = "neck"
    SHOULDERS = "shoulders"
    CHEST = "chest"
    BACK = "back"
    ABS = "abs"
    BICEPS = "biceps"
    TRICEPS = "triceps"
    FOREARMS = "forearms"
    GLUTES = "glutes"
    QUADRICEPS = "quadriceps"
    HAMSTRINGS = "hamstrings"
    CALVES = "calves"
    CARDIO = "cardio"


class Equipment(str, Enum):
    BARBELL = "barbell"
    BODY_WEIGHT = "body weight"
    CABLE = "cable"
    CHEST_PRESS_MACHINE = "chest press machine"
    DUMBBELL = "dumbbell"
    ELLIPTICAL_MACHINE = "elliptical machine"
    EXERCISE_BIKE = "exercise bike"
    EZ_BARBELL = "ez barbell"
    KETTLEBELL = "kettlebell"
    LEVERAGE_MACHINE = "leverage machine"
    ROPE = "rope"
    SLED_MACHINE = "sled machine"
    SMITH_MACHINE = "smith machine"
    TRAP_BAR = "trap bar"
    TREADMILL = "treadmill"
    WEIGHTED = "weighted"
    WHEEL_ROLLER = "wheel roller"


class Focus(str, Enum):
    FULLBODY = "fullbody"
    UPPER = "upper"
    LOWER = "lower"
    PUSH = "push"
    PULL = "pull"
    LEGS = "legs"
    CARDIO = "cardio"
    MALE_FOCUS = "male focus"
    FEMALE_FOCUS = "female focus"
    NECK = "neck"
    SHOULDERS = "shoulders"
    CHEST = "chest"
    BACK = "back"
    ABS = "abs"
    BICEPS = "biceps"
    TRICEPS = "triceps"
    FOREARMS = "forearms"
    GLUTES = "glutes"
    QUADRICEPS = "quadriceps"
    HAMSTRINGS = "hamstrings"
    CALVES = "calves"


ALL_BODY_PARTS: FrozenSet[BodyPart] = frozenset(BodyPart)
ALL_EQUIPMENT: FrozenSet[Equipment] = frozenset(Equipment)
ALL_FOCUS: FrozenSet[Focus] = frozenset(Focus)

BODY_PART_VALUES = tuple(item.value for item in BodyPart)
EQUIPMENT_VALUES = tuple(item.value for item in Equipment)
FOCUS_VALUES = tuple(item.value for item in Focus)

# Focus -> body parts that satisfy it.  Cardio is deliberately excluded from
# fullbody because the original thesis treats it as a separate session.
FOCUS_TO_BODY_PARTS: Dict[Focus, FrozenSet[BodyPart]] = {
    Focus.FULLBODY: ALL_BODY_PARTS - {BodyPart.CARDIO},
    Focus.UPPER: frozenset(
        {
            BodyPart.NECK,
            BodyPart.SHOULDERS,
            BodyPart.CHEST,
            BodyPart.BACK,
            BodyPart.ABS,
            BodyPart.BICEPS,
            BodyPart.TRICEPS,
            BodyPart.FOREARMS,
        }
    ),
    Focus.LOWER: frozenset(
        {
            BodyPart.GLUTES,
            BodyPart.QUADRICEPS,
            BodyPart.HAMSTRINGS,
            BodyPart.CALVES,
        }
    ),
    Focus.PUSH: frozenset(
        {BodyPart.SHOULDERS, BodyPart.CHEST, BodyPart.TRICEPS}
    ),
    Focus.PULL: frozenset(
        {BodyPart.BACK, BodyPart.BICEPS, BodyPart.FOREARMS, BodyPart.NECK}
    ),
    Focus.LEGS: frozenset(
        {
            BodyPart.GLUTES,
            BodyPart.QUADRICEPS,
            BodyPart.HAMSTRINGS,
            BodyPart.CALVES,
        }
    ),
    Focus.CARDIO: frozenset({BodyPart.CARDIO}),
    Focus.MALE_FOCUS: frozenset(
        {
            BodyPart.CHEST,
            BodyPart.SHOULDERS,
            BodyPart.BICEPS,
            BodyPart.TRICEPS,
            BodyPart.BACK,
            BodyPart.ABS,
        }
    ),
    Focus.FEMALE_FOCUS: frozenset(
        {
            BodyPart.GLUTES,
            BodyPart.QUADRICEPS,
            BodyPart.HAMSTRINGS,
            BodyPart.ABS,
        }
    ),
}
# Specific body-part focuses map to themselves.
for _part in BodyPart:
    if _part is BodyPart.CARDIO:
        continue
    FOCUS_TO_BODY_PARTS[Focus(_part.value)] = frozenset({_part})

GENDER_DEFAULT_FOCUS: Dict[Gender, tuple[BodyPart, ...]] = {
    Gender.MALE: (
        BodyPart.CHEST,
        BodyPart.SHOULDERS,
        BodyPart.BICEPS,
        BodyPart.TRICEPS,
        BodyPart.BACK,
        BodyPart.ABS,
    ),
    Gender.FEMALE: (
        BodyPart.GLUTES,
        BodyPart.QUADRICEPS,
        BodyPart.HAMSTRINGS,
        BodyPart.ABS,
    ),
}

GENDER_PRIORITY: Dict[Gender, Dict[BodyPart, int]] = {
    Gender.MALE: {
        BodyPart.CHEST: 1,
        BodyPart.SHOULDERS: 2,
        BodyPart.BICEPS: 3,
        BodyPart.TRICEPS: 4,
        BodyPart.BACK: 5,
        BodyPart.ABS: 6,
    },
    Gender.FEMALE: {
        BodyPart.GLUTES: 0,
        BodyPart.QUADRICEPS: 1,
        BodyPart.HAMSTRINGS: 2,
        BodyPart.ABS: 3,
    },
}

# Muscle -> body part.  Used by injury mapping and by the GA's muscle-variation
# term.  Keep this in sync with the glosarium branch.
MUSCLE_TO_BODY_PART: Dict[str, BodyPart] = {
    "sternocleidomastoid": BodyPart.NECK,
    "splenius capitis": BodyPart.NECK,
    "splenius cervicis": BodyPart.NECK,
    "deltoid": BodyPart.SHOULDERS,
    "deltoids": BodyPart.SHOULDERS,
    "front deltoids": BodyPart.SHOULDERS,
    "side deltoids": BodyPart.SHOULDERS,
    "rear deltoids": BodyPart.SHOULDERS,
    "pectoralis major": BodyPart.CHEST,
    "pectoralis minor": BodyPart.CHEST,
    "upper chest": BodyPart.CHEST,
    "middle chest": BodyPart.CHEST,
    "lower chest": BodyPart.CHEST,
    "trapezius": BodyPart.BACK,
    "upper traps": BodyPart.BACK,
    "lower traps": BodyPart.BACK,
    "rotator cuff": BodyPart.BACK,
    "teres major": BodyPart.BACK,
    "latissimus dorsi": BodyPart.BACK,
    "lats": BodyPart.BACK,
    "erector spinae": BodyPart.BACK,
    "rectus abdominis": BodyPart.ABS,
    "obliques": BodyPart.ABS,
    "serratus": BodyPart.ABS,
    "biceps brachii": BodyPart.BICEPS,
    "brachialis": BodyPart.BICEPS,
    "long head": BodyPart.TRICEPS,
    "lateral head": BodyPart.TRICEPS,
    "medial head": BodyPart.TRICEPS,
    "brachioradialis": BodyPart.FOREARMS,
    "flexors": BodyPart.FOREARMS,
    "extensors": BodyPart.FOREARMS,
    "gluteus maximus": BodyPart.GLUTES,
    "gluteus medius": BodyPart.GLUTES,
    "gluteus minimus": BodyPart.GLUTES,
    "rectus femoris": BodyPart.QUADRICEPS,
    "vastus lateralis": BodyPart.QUADRICEPS,
    "vastus medialis": BodyPart.QUADRICEPS,
    "vastus intermedius": BodyPart.QUADRICEPS,
    "biceps femoris": BodyPart.HAMSTRINGS,
    "semitendinosus": BodyPart.HAMSTRINGS,
    "semimembranosus": BodyPart.HAMSTRINGS,
    "gastrocnemius": BodyPart.CALVES,
    "soleus": BodyPart.CALVES,
    "cardio": BodyPart.CARDIO,
}

# Common joint/region complaints -> body parts to avoid.  This is deliberately
# conservative: when in doubt we exclude more, because a missing exercise is a
# much smaller problem than recommending an exercise that hurts the user.
INJURY_ALIASES: Dict[str, FrozenSet[BodyPart]] = {
    "knee": frozenset(
        {
            BodyPart.QUADRICEPS,
            BodyPart.HAMSTRINGS,
            BodyPart.GLUTES,
            BodyPart.CALVES,
        }
    ),
    "knees": frozenset(
        {
            BodyPart.QUADRICEPS,
            BodyPart.HAMSTRINGS,
            BodyPart.GLUTES,
            BodyPart.CALVES,
        }
    ),
    "acl": frozenset(
        {
            BodyPart.QUADRICEPS,
            BodyPart.HAMSTRINGS,
            BodyPart.GLUTES,
            BodyPart.CALVES,
        }
    ),
    "meniscus": frozenset(
        {
            BodyPart.QUADRICEPS,
            BodyPart.HAMSTRINGS,
            BodyPart.GLUTES,
            BodyPart.CALVES,
        }
    ),
    "patella": frozenset(
        {
            BodyPart.QUADRICEPS,
            BodyPart.HAMSTRINGS,
            BodyPart.GLUTES,
            BodyPart.CALVES,
        }
    ),
    "lower back": frozenset(
        {BodyPart.BACK, BodyPart.GLUTES, BodyPart.HAMSTRINGS}
    ),
    "lowerback": frozenset(
        {BodyPart.BACK, BodyPart.GLUTES, BodyPart.HAMSTRINGS}
    ),
    "low back": frozenset(
        {BodyPart.BACK, BodyPart.GLUTES, BodyPart.HAMSTRINGS}
    ),
    "lumbago": frozenset({BodyPart.BACK}),
    "upper back": frozenset({BodyPart.BACK}),
    "sciatica": frozenset(
        {BodyPart.BACK, BodyPart.GLUTES, BodyPart.HAMSTRINGS}
    ),
    "shoulder": frozenset(
        {BodyPart.SHOULDERS, BodyPart.CHEST, BodyPart.TRICEPS}
    ),
    "shoulders": frozenset(
        {BodyPart.SHOULDERS, BodyPart.CHEST, BodyPart.TRICEPS}
    ),
    "rotator cuff": frozenset({BodyPart.SHOULDERS, BodyPart.BACK}),
    "elbow": frozenset(
        {BodyPart.BICEPS, BodyPart.TRICEPS, BodyPart.FOREARMS}
    ),
    "elbows": frozenset(
        {BodyPart.BICEPS, BodyPart.TRICEPS, BodyPart.FOREARMS}
    ),
    "tennis elbow": frozenset(
        {BodyPart.BICEPS, BodyPart.TRICEPS, BodyPart.FOREARMS}
    ),
    "wrist": frozenset({BodyPart.FOREARMS}),
    "wrists": frozenset({BodyPart.FOREARMS}),
    "ankle": frozenset({BodyPart.CALVES}),
    "ankles": frozenset({BodyPart.CALVES}),
    "hip": frozenset(
        {BodyPart.GLUTES, BodyPart.QUADRICEPS, BodyPart.HAMSTRINGS}
    ),
    "hips": frozenset(
        {BodyPart.GLUTES, BodyPart.QUADRICEPS, BodyPart.HAMSTRINGS}
    ),
    "hernia": frozenset({BodyPart.ABS}),
    "bicep": frozenset({BodyPart.BICEPS}),
    "biceps": frozenset({BodyPart.BICEPS}),
    "tricep": frozenset({BodyPart.TRICEPS}),
    "triceps": frozenset({BodyPart.TRICEPS}),
    "forearm": frozenset({BodyPart.FOREARMS}),
    "forearms": frozenset({BodyPart.FOREARMS}),
    "glute": frozenset({BodyPart.GLUTES}),
    "glutes": frozenset({BodyPart.GLUTES}),
    "quad": frozenset({BodyPart.QUADRICEPS}),
    "quads": frozenset({BodyPart.QUADRICEPS}),
    "quadriceps": frozenset({BodyPart.QUADRICEPS}),
    "hamstring": frozenset({BodyPart.HAMSTRINGS}),
    "hamstrings": frozenset({BodyPart.HAMSTRINGS}),
    "calf": frozenset({BodyPart.CALVES}),
    "calves": frozenset({BodyPart.CALVES}),
    "neck": frozenset({BodyPart.NECK}),
    "chest": frozenset({BodyPart.CHEST}),
    "back": frozenset({BodyPart.BACK}),
    "abs": frozenset({BodyPart.ABS}),
    "abdominals": frozenset({BodyPart.ABS}),
}

CARDIO_RUN_EXERCISES: FrozenSet[str] = frozenset({"run", "run on treadmill"})
CARDIO_INDOOR_EXERCISES: FrozenSet[str] = frozenset(
    {
        "stationary bike run",
        "elliptical machine walk",
        "bicycle recline walk",
        "cycle cross trainer",
        "walking on incline treadmill",
        "walking on treadmill",
        "walking",
    }
)

# Split names emitted by the rule table.
SPLIT_FULLBODY = "fullbody"
SPLIT_UPPERLOWER = "upperlower"
SPLIT_PPL = "ppl"
SPLIT_PPL_FOCUS = "ppl+focus"
SPLIT_UPPERLOWER_FOCUS = "upperlower+focus"


def normalise_token(value: str) -> str:
    """Lowercase, strip, and collapse separators for user-facing vocabulary."""

    return " ".join(
        str(value).lower().replace("_", " ").replace("-", " ").split()
    )


def coerce_body_part(value: str | BodyPart) -> BodyPart:
    if isinstance(value, BodyPart):
        return value
    return BodyPart(normalise_token(value))


def coerce_equipment(value: str | Equipment) -> Equipment:
    if isinstance(value, Equipment):
        return value
    return Equipment(normalise_token(value))


def coerce_focus(value: str | Focus) -> Focus:
    if isinstance(value, Focus):
        return value
    return Focus(normalise_token(value))


def is_valid_injury_term(term: str) -> bool:
    normalised = normalise_token(term)
    return (
        normalised in INJURY_ALIASES
        or normalised in MUSCLE_TO_BODY_PART
        or normalised in {part.value for part in BodyPart}
    )


def supported_injury_terms() -> Set[str]:
    return (
        set(INJURY_ALIASES)
        | set(MUSCLE_TO_BODY_PART)
        | {part.value for part in BodyPart}
    )
