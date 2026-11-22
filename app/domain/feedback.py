"""Feedback and safety vocabulary for P0.4."""

from __future__ import annotations

from enum import StrEnum
from typing import Dict, FrozenSet


class Difficulty(StrEnum):
    TOO_EASY = "too_easy"
    JUST_RIGHT = "just_right"
    TOO_HARD = "too_hard"


class SafetySeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SafetyStatus(StrEnum):
    OPEN = "open"
    TRIAGED = "triaged"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


SAFETY_TRANSITIONS: Dict[SafetyStatus, FrozenSet[SafetyStatus]] = {
    SafetyStatus.OPEN: frozenset(
        {SafetyStatus.TRIAGED, SafetyStatus.RESOLVED, SafetyStatus.DISMISSED}
    ),
    SafetyStatus.TRIAGED: frozenset({SafetyStatus.RESOLVED, SafetyStatus.DISMISSED}),
    SafetyStatus.RESOLVED: frozenset(),
    SafetyStatus.DISMISSED: frozenset(),
}

SEVERITY_VALUES = tuple(item.value for item in SafetySeverity)
STATUS_VALUES = tuple(item.value for item in SafetyStatus)
