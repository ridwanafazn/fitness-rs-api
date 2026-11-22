"""Canonical profile and consent vocabulary for P0.1."""

from __future__ import annotations

from enum import StrEnum
from typing import Dict, FrozenSet, Tuple


class Goal(StrEnum):
    MUSCLE_GAIN = "muscle_gain"
    FAT_LOSS = "fat_loss"
    GENERAL_HEALTH = "general_health"


class Experience(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class UnitSystem(StrEnum):
    METRIC = "metric"
    IMPERIAL = "imperial"


class ConsentKind(StrEnum):
    HEALTH_DATA_PROCESSING = "health_data_processing"
    RESEARCH_ANALYTICS = "research_analytics"
    TRAINER_SHARING = "trainer_sharing"
    MARKETING = "marketing"


SESSION_MINUTES: Tuple[int, ...] = (30, 45, 60, 90)
PROFILE_REQUIRED_FIELDS: Tuple[str, ...] = (
    "gender",
    "height_cm",
    "weight_kg",
    "goal",
    "experience",
    "session_minutes",
    "timezone",
    "locale",
    "unit_system",
)
CONSENT_KINDS: FrozenSet[ConsentKind] = frozenset(ConsentKind)

# Friendly spellings that the frontend or a human may send.  Values are the
# canonical strings from ``app.domain.constants.Equipment``.
EQUIPMENT_ALIASES: Dict[str, str] = {
    "bodyweight": "body weight",
    "body-weight": "body weight",
    "dumbbells": "dumbbell",
    "barbells": "barbell",
    "cables": "cable",
    "kettlebells": "kettlebell",
    "machines": "leverage machine",
    "machine": "leverage machine",
}

SUPPORTED_LOCALES: Dict[str, str] = {
    "id-id": "id-ID",
    "en-us": "en-US",
}
