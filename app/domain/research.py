"""P2.2 research, experimentation, and quality vocabulary."""

from __future__ import annotations

import json
import math
from enum import StrEnum
from typing import Any, Dict, FrozenSet, Mapping, Tuple


class VersionKind(StrEnum):
    DATASET = "dataset"
    ALGORITHM = "algorithm"


class ExperimentStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"


class QualitySubjectType(StrEnum):
    PLAN_VERSION = "plan_version"
    DATASET_VERSION = "dataset_version"
    ALGORITHM_VERSION = "algorithm_version"


class QualityReviewStatus(StrEnum):
    PENDING = "pending"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


EVENT_NAMES: FrozenSet[str] = frozenset(
    {
        "app_opened",
        "recommendation_viewed",
        "plan_generated",
        "plan_saved",
        "plan_shared",
        "workout_started",
        "workout_completed",
        "set_logged",
        "feedback_submitted",
        "safety_report_submitted",
        "trainer_invitation_accepted",
        "calendar_connected",
        "integration_connected",
        "organization_joined",
        "experiment_exposed",
    }
)

PROPERTY_DENY_MARKERS: Tuple[str, ...] = (
    "email",
    "phone",
    "address",
    "name",
    "note",
    "comment",
    "reason",
    "injur",
    "pain",
    "token",
    "secret",
    "password",
    "birth",
    "location",
    "user_id",
    "plan_id",
    "workout_id",
    "session_id",
    "device",
)

QUALITY_RUBRIC_KEYS: Tuple[str, ...] = (
    "safety",
    "variety",
    "equipment_fit",
    "clarity",
    "progression",
)

VERSION_KIND_VALUES: Tuple[str, ...] = tuple(item.value for item in VersionKind)
EXPERIMENT_STATUS_VALUES: Tuple[str, ...] = tuple(item.value for item in ExperimentStatus)
QUALITY_SUBJECT_VALUES: Tuple[str, ...] = tuple(
    item.value for item in QualitySubjectType
)
QUALITY_REVIEW_STATUS_VALUES: Tuple[str, ...] = tuple(
    item.value for item in QualityReviewStatus
)


def is_sensitive_property_key(key: str) -> bool:
    lowered = key.strip().lower()
    return any(marker in lowered for marker in PROPERTY_DENY_MARKERS)


def validate_event_properties(
    value: Mapping[str, Any],
    *,
    max_keys: int = 20,
    max_bytes: int = 2048,
) -> Dict[str, Any]:
    """Return a flat, PII-free property map or raise ValueError."""

    if not isinstance(value, Mapping):
        raise ValueError("Properties harus berupa object.")
    if len(value) > max_keys:
        raise ValueError(f"Properties maksimal {max_keys} key.")

    cleaned: Dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        if not key or len(key) > 40:
            raise ValueError("Key properties tidak valid.")
        if is_sensitive_property_key(key):
            raise ValueError(f"Key properties sensitif ditolak: {key}.")
        if isinstance(raw_value, bool):
            cleaned[key] = raw_value
        elif isinstance(raw_value, int):
            if abs(raw_value) > 1_000_000_000:
                raise ValueError(f"Nilai properties terlalu besar: {key}.")
            cleaned[key] = raw_value
        elif isinstance(raw_value, float):
            if not math.isfinite(raw_value) or abs(raw_value) > 1_000_000_000:
                raise ValueError(f"Nilai properties tidak valid: {key}.")
            cleaned[key] = raw_value
        elif isinstance(raw_value, str):
            text = raw_value.strip()
            if len(text) > 200:
                raise ValueError(f"String properties terlalu panjang: {key}.")
            cleaned[key] = text
        elif raw_value is None:
            cleaned[key] = None
        else:
            raise ValueError(
                "Properties hanya boleh berisi string, angka, boolean, atau null."
            )

    encoded = json.dumps(cleaned, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > max_bytes:
        raise ValueError(f"Properties maksimal {max_bytes} byte.")
    return cleaned
