"""Trainer workspace vocabulary for P1.2."""

from __future__ import annotations

from enum import StrEnum
from typing import FrozenSet, Tuple


class TrainingScope(StrEnum):
    PLANS = "plans"
    WORKOUTS = "workouts"
    FEEDBACK = "feedback"
    PROGRESS = "progress"


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    REVOKED = "revoked"
    EXPIRED = "expired"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    CHANGES_REQUESTED = "changes_requested"


SCOPE_VALUES: Tuple[str, ...] = tuple(item.value for item in TrainingScope)
DEFAULT_SCOPES: FrozenSet[TrainingScope] = frozenset(TrainingScope)
INVITATION_STATUS_VALUES: Tuple[str, ...] = tuple(
    item.value for item in InvitationStatus
)
REVIEW_STATUS_VALUES: Tuple[str, ...] = tuple(item.value for item in ReviewStatus)
