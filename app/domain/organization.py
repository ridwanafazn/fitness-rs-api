"""Organization and membership vocabulary for P2.1 (free collaboration mode)."""

from __future__ import annotations

from enum import StrEnum
from typing import FrozenSet, Tuple


class OrganizationType(StrEnum):
    GYM = "gym"
    STUDIO = "studio"
    COACH = "coach"
    RESEARCH = "research"
    OTHER = "other"


class OrganizationStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class OrganizationRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    TRAINER = "trainer"
    MEMBER = "member"


class OrganizationInvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    REVOKED = "revoked"
    EXPIRED = "expired"


ROLE_VALUES: Tuple[str, ...] = tuple(item.value for item in OrganizationRole)
INVITABLE_ROLES: FrozenSet[OrganizationRole] = frozenset(
    {OrganizationRole.ADMIN, OrganizationRole.TRAINER, OrganizationRole.MEMBER}
)
ADMIN_ROLES: FrozenSet[OrganizationRole] = frozenset(
    {OrganizationRole.OWNER, OrganizationRole.ADMIN}
)
TYPE_VALUES: Tuple[str, ...] = tuple(item.value for item in OrganizationType)
STATUS_VALUES: Tuple[str, ...] = tuple(item.value for item in OrganizationStatus)
INVITATION_STATUS_VALUES: Tuple[str, ...] = tuple(
    item.value for item in OrganizationInvitationStatus
)
