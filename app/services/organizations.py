"""P2.1 free organizations, memberships, and invitations (no billing)."""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Collection, List, Tuple

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.crypto import hash_secret
from app.core.errors import (
    OrganizationAccessDeniedError,
    OrganizationConflictError,
    OrganizationInvitationConflictError,
    OrganizationInvitationNotFoundError,
    OrganizationNotFoundError,
    OrganizationValidationError,
)
from app.db.models import (
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    Plan,
    TrainerClient,
    User,
)
from app.domain.organization import (
    ADMIN_ROLES,
    INVITABLE_ROLES,
    OrganizationInvitationStatus,
    OrganizationRole,
    OrganizationStatus,
)
from app.schemas.organizations import (
    OrganizationCreate,
    OrganizationInvitationCreate,
    OrganizationInvitationOut,
    OrganizationMemberOut,
    OrganizationOut,
    OrganizationSummary,
    OrganizationUpdate,
)
from app.services.audit import record_audit
from app.services.identity import commit_or_conflict

INVITATION_TTL_DAYS = 14


def utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:64] or "org"


def _unique_slug(session: Session, base: str) -> str:
    candidate = base
    index = 2
    while session.scalar(select(Organization.id).where(Organization.slug == candidate)):
        candidate = f"{base[:58]}-{index}"
        index += 1
    return candidate


def _membership(
    session: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
) -> OrganizationMembership:
    membership = session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == org_id,
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.status == "active",
        )
    )
    if membership is None:
        raise OrganizationNotFoundError()
    return membership


def _require_role(
    session: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    roles: Collection[OrganizationRole],
) -> OrganizationMembership:
    membership = _membership(session, org_id=org_id, user_id=user_id)
    if membership.role not in {role.value for role in roles}:
        raise OrganizationAccessDeniedError()
    return membership


def organization_out(org: Organization, role: str) -> OrganizationOut:
    return OrganizationOut(
        id=org.id,
        name=org.name,
        slug=org.slug,
        type=org.type,
        description=org.description,
        website=org.website,
        timezone=org.timezone,
        branding=dict(org.branding or {}),
        status=org.status,
        role=role,
        created_at=org.created_at,
        updated_at=org.updated_at,
    )


def create_organization(
    session: Session,
    *,
    user_id: uuid.UUID,
    payload: OrganizationCreate,
    actor_role: str,
) -> Organization:
    base_slug = payload.slug or _slugify(payload.name)
    org = Organization(
        name=payload.name,
        slug=_unique_slug(session, base_slug),
        type=payload.type.value,
        description=payload.description,
        website=payload.website,
        timezone=payload.timezone,
        branding=dict(payload.branding),
        status=OrganizationStatus.ACTIVE.value,
        created_by=user_id,
    )
    session.add(org)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise OrganizationConflictError(
            "Slug organisasi sudah digunakan."
        ) from exc
    session.add(
        OrganizationMembership(
            organization_id=org.id,
            user_id=user_id,
            role=OrganizationRole.OWNER.value,
            status="active",
        )
    )
    session.flush()
    record_audit(
        session,
        actor_user_id=user_id,
        actor_role=actor_role,
        action="organization.created",
        resource_type="organization",
        resource_id=str(org.id),
        metadata={"type": org.type},
    )
    commit_or_conflict(session)
    return org


def list_organizations(
    session: Session,
    *,
    user_id: uuid.UUID,
) -> List[OrganizationOut]:
    rows = session.execute(
        select(Organization, OrganizationMembership.role)
        .join(
            OrganizationMembership,
            OrganizationMembership.organization_id == Organization.id,
        )
        .where(
            OrganizationMembership.user_id == user_id,
            OrganizationMembership.status == "active",
            Organization.status != OrganizationStatus.ARCHIVED.value,
        )
        .order_by(Organization.name)
    ).all()
    return [organization_out(org, role) for org, role in rows]


def get_organization(
    session: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
) -> Tuple[Organization, OrganizationMembership]:
    org = session.get(Organization, org_id)
    if org is None:
        raise OrganizationNotFoundError()
    membership = _membership(session, org_id=org_id, user_id=user_id)
    return org, membership


def update_organization(
    session: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: OrganizationUpdate,
    actor_role: str,
) -> Organization:
    org, membership = get_organization(session, org_id=org_id, user_id=user_id)
    if membership.role not in {role.value for role in ADMIN_ROLES}:
        raise OrganizationAccessDeniedError()
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        if field == "status" and value is not None:
            value = value.value if hasattr(value, "value") else value
        setattr(org, field, value)
    org.updated_at = utcnow()
    session.flush()
    record_audit(
        session,
        actor_user_id=user_id,
        actor_role=actor_role,
        action="organization.updated",
        resource_type="organization",
        resource_id=str(org.id),
        metadata={"fields": sorted(data)},
    )
    commit_or_conflict(session)
    return org


def list_members(
    session: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
) -> List[OrganizationMemberOut]:
    _membership(session, org_id=org_id, user_id=user_id)
    rows = session.execute(
        select(OrganizationMembership, User)
        .join(User, User.id == OrganizationMembership.user_id)
        .where(
            OrganizationMembership.organization_id == org_id,
            OrganizationMembership.status == "active",
        )
        .order_by(OrganizationMembership.role, User.display_name)
    ).all()
    return [
        OrganizationMemberOut(
            user_id=membership.user_id,
            display_name=user.display_name,
            role=membership.role,
            status=membership.status,
            joined_at=membership.created_at,
        )
        for membership, user in rows
    ]


def _invitation_out(invitation: OrganizationInvitation) -> OrganizationInvitationOut:
    return OrganizationInvitationOut(
        id=invitation.id,
        email=invitation.email,
        role=invitation.role,
        status=invitation.status,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
    )


def create_invitation(
    session: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: OrganizationInvitationCreate,
    actor_role: str,
) -> Tuple[OrganizationInvitation, str]:
    org, _ = get_organization(session, org_id=org_id, user_id=user_id)
    _require_role(
        session,
        org_id=org_id,
        user_id=user_id,
        roles=ADMIN_ROLES,
    )
    if org.status == OrganizationStatus.ARCHIVED.value:
        raise OrganizationConflictError("Organisasi sedang diarsipkan.")
    if payload.role not in INVITABLE_ROLES:
        raise OrganizationValidationError("Role undangan tidak valid.")

    existing = session.scalar(
        select(OrganizationMembership)
        .join(User, User.id == OrganizationMembership.user_id)
        .where(
            OrganizationMembership.organization_id == org_id,
            OrganizationMembership.status == "active",
            func.lower(User.email) == payload.email,
        )
    )
    if existing is not None:
        raise OrganizationInvitationConflictError("User sudah menjadi member.")

    now = utcnow()
    pending = session.scalar(
        select(OrganizationInvitation).where(
            OrganizationInvitation.organization_id == org_id,
            OrganizationInvitation.email == payload.email,
            OrganizationInvitation.status == OrganizationInvitationStatus.PENDING.value,
            OrganizationInvitation.expires_at > now,
        )
    )
    if pending is not None:
        raise OrganizationInvitationConflictError(
            "Sudah ada undangan pending untuk email tersebut."
        )

    token = secrets.token_urlsafe(32)
    invitation = OrganizationInvitation(
        organization_id=org_id,
        email=payload.email,
        role=payload.role.value,
        token_hash=hash_secret(token),
        status=OrganizationInvitationStatus.PENDING.value,
        invited_by=user_id,
        expires_at=now + timedelta(days=INVITATION_TTL_DAYS),
    )
    session.add(invitation)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise OrganizationInvitationConflictError(
            "Undangan tidak bisa dibuat. Coba lagi."
        ) from exc
    record_audit(
        session,
        actor_user_id=user_id,
        actor_role=actor_role,
        action="organization.invitation_created",
        resource_type="organization_invitation",
        resource_id=str(invitation.id),
        metadata={"organization_id": str(org_id), "role": invitation.role},
    )
    commit_or_conflict(session)
    return invitation, token


def list_invitations(
    session: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
) -> List[OrganizationInvitationOut]:
    _require_role(
        session,
        org_id=org_id,
        user_id=user_id,
        roles=ADMIN_ROLES,
    )
    invitations = list(
        session.scalars(
            select(OrganizationInvitation)
            .where(OrganizationInvitation.organization_id == org_id)
            .order_by(OrganizationInvitation.created_at.desc())
        ).all()
    )
    now = utcnow()
    changed = False
    for invitation in invitations:
        if (
            invitation.status == OrganizationInvitationStatus.PENDING.value
            and _as_utc(invitation.expires_at) <= now
        ):
            invitation.status = OrganizationInvitationStatus.EXPIRED.value
            invitation.updated_at = now
            changed = True
    if changed:
        commit_or_conflict(session)
    return [_invitation_out(invitation) for invitation in invitations]


def _pending_invitation(session: Session, token: str) -> OrganizationInvitation:
    invitation = session.scalar(
        select(OrganizationInvitation).where(
            OrganizationInvitation.token_hash == hash_secret(token)
        )
    )
    if (
        invitation is None
        or invitation.status != OrganizationInvitationStatus.PENDING.value
    ):
        raise OrganizationInvitationNotFoundError()
    if _as_utc(invitation.expires_at) <= utcnow():
        invitation.status = OrganizationInvitationStatus.EXPIRED.value
        commit_or_conflict(session)
        raise OrganizationInvitationNotFoundError()
    return invitation


def accept_invitation(
    session: Session,
    *,
    user: User,
    token: str,
    actor_role: str,
) -> OrganizationMembership:
    invitation = _pending_invitation(session, token)
    if not user.email or user.email.lower() != invitation.email:
        raise OrganizationAccessDeniedError("Email akun tidak cocok dengan undangan.")
    org = session.get(Organization, invitation.organization_id)
    if org is None or org.status == OrganizationStatus.ARCHIVED.value:
        raise OrganizationConflictError("Organisasi tidak aktif.")

    existing = session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == invitation.organization_id,
            OrganizationMembership.user_id == user.id,
        )
    )
    if existing is not None and existing.status == "active":
        raise OrganizationInvitationConflictError("User sudah menjadi member.")
    if existing is None:
        membership = OrganizationMembership(
            organization_id=invitation.organization_id,
            user_id=user.id,
            role=invitation.role,
            status="active",
        )
        session.add(membership)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise OrganizationInvitationConflictError(
                "Keanggotaan berubah secara bersamaan. Coba lagi."
            ) from exc
    else:
        membership = existing
        membership.role = invitation.role
        membership.status = "active"
        membership.revoked_at = None
        membership.updated_at = utcnow()
        session.flush()

    invitation.status = OrganizationInvitationStatus.ACCEPTED.value
    invitation.accepted_at = utcnow()
    invitation.updated_at = utcnow()
    record_audit(
        session,
        actor_user_id=user.id,
        actor_role=actor_role,
        action="organization.invitation_accepted",
        resource_type="organization_membership",
        resource_id=str(membership.id),
        metadata={
            "organization_id": str(invitation.organization_id),
            "role": membership.role,
        },
    )
    commit_or_conflict(session)
    return membership


def decline_invitation(
    session: Session,
    *,
    user: User,
    token: str,
    actor_role: str,
) -> None:
    invitation = _pending_invitation(session, token)
    if not user.email or user.email.lower() != invitation.email:
        raise OrganizationAccessDeniedError("Email akun tidak cocok dengan undangan.")
    invitation.status = OrganizationInvitationStatus.DECLINED.value
    invitation.declined_at = utcnow()
    invitation.updated_at = utcnow()
    record_audit(
        session,
        actor_user_id=user.id,
        actor_role=actor_role,
        action="organization.invitation_declined",
        resource_type="organization_invitation",
        resource_id=str(invitation.id),
        metadata={"organization_id": str(invitation.organization_id)},
    )
    commit_or_conflict(session)


def _active_owner_count(session: Session, org_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.count(OrganizationMembership.id)).where(
                OrganizationMembership.organization_id == org_id,
                OrganizationMembership.role == OrganizationRole.OWNER.value,
                OrganizationMembership.status == "active",
            )
        )
        or 0
    )


def update_member_role(
    session: Session,
    *,
    org_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    new_role: OrganizationRole,
    actor_role: str,
) -> OrganizationMembership:
    actor_membership = _membership(
        session,
        org_id=org_id,
        user_id=actor_user_id,
    )
    target = session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == org_id,
            OrganizationMembership.user_id == target_user_id,
            OrganizationMembership.status == "active",
        )
    )
    if target is None:
        raise OrganizationNotFoundError("Member tidak ditemukan.")

    actor_is_owner = actor_membership.role == OrganizationRole.OWNER.value
    if new_role is OrganizationRole.OWNER and not actor_is_owner:
        raise OrganizationAccessDeniedError("Hanya owner yang bisa transfer ownership.")
    if target.role == OrganizationRole.OWNER.value and not actor_is_owner:
        raise OrganizationAccessDeniedError("Hanya owner yang bisa mengubah owner.")
    if actor_membership.role not in {role.value for role in ADMIN_ROLES}:
        raise OrganizationAccessDeniedError()
    if (
        target.role == OrganizationRole.OWNER.value
        and new_role is not OrganizationRole.OWNER
        and _active_owner_count(session, org_id) <= 1
    ):
        raise OrganizationConflictError("Organisasi harus memiliki minimal satu owner.")

    old_role = target.role
    if new_role is OrganizationRole.OWNER and target.role != OrganizationRole.OWNER.value:
        actor_membership.role = OrganizationRole.ADMIN.value
        actor_membership.updated_at = utcnow()
        target.role = OrganizationRole.OWNER.value
    else:
        target.role = new_role.value
    target.updated_at = utcnow()
    session.flush()
    record_audit(
        session,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action="organization.member_role_changed",
        resource_type="organization_membership",
        resource_id=str(target.id),
        metadata={"from": old_role, "to": target.role},
    )
    commit_or_conflict(session)
    return target


def remove_member(
    session: Session,
    *,
    org_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    target_user_id: uuid.UUID,
    actor_role: str,
) -> None:
    actor_membership = _membership(
        session,
        org_id=org_id,
        user_id=actor_user_id,
    )
    if actor_membership.role not in {role.value for role in ADMIN_ROLES}:
        raise OrganizationAccessDeniedError()
    target = session.scalar(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == org_id,
            OrganizationMembership.user_id == target_user_id,
            OrganizationMembership.status == "active",
        )
    )
    if target is None:
        raise OrganizationNotFoundError("Member tidak ditemukan.")
    if target.role == OrganizationRole.OWNER.value:
        if actor_membership.role != OrganizationRole.OWNER.value:
            raise OrganizationAccessDeniedError()
        if _active_owner_count(session, org_id) <= 1:
            raise OrganizationConflictError("Organisasi harus memiliki minimal satu owner.")
    target.status = "revoked"
    target.revoked_at = utcnow()
    target.updated_at = utcnow()
    record_audit(
        session,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action="organization.member_removed",
        resource_type="organization_membership",
        resource_id=str(target.id),
        metadata={"organization_id": str(org_id), "role": target.role},
    )
    commit_or_conflict(session)


def leave_organization(
    session: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    actor_role: str,
) -> None:
    membership = _membership(session, org_id=org_id, user_id=user_id)
    if (
        membership.role == OrganizationRole.OWNER.value
        and _active_owner_count(session, org_id) <= 1
    ):
        raise OrganizationConflictError(
            "Owner terakhir tidak bisa keluar; transfer ownership terlebih dahulu."
        )
    membership.status = "revoked"
    membership.revoked_at = utcnow()
    membership.updated_at = utcnow()
    record_audit(
        session,
        actor_user_id=user_id,
        actor_role=actor_role,
        action="organization.left",
        resource_type="organization_membership",
        resource_id=str(membership.id),
        metadata={"organization_id": str(org_id), "role": membership.role},
    )
    commit_or_conflict(session)


def organization_summary(
    session: Session,
    *,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
) -> OrganizationSummary:
    _require_role(
        session,
        org_id=org_id,
        user_id=user_id,
        roles=ADMIN_ROLES,
    )
    memberships = list(
        session.scalars(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == org_id,
                OrganizationMembership.status == "active",
            )
        ).all()
    )
    trainers = [
        membership.user_id
        for membership in memberships
        if membership.role == OrganizationRole.TRAINER.value
    ]
    clients = 0
    if trainers:
        clients = int(
            session.scalar(
                select(func.count(func.distinct(TrainerClient.client_user_id))).where(
                    TrainerClient.trainer_user_id.in_(trainers),
                    TrainerClient.status == "active",
                )
            )
            or 0
        )
    member_ids = [membership.user_id for membership in memberships]
    active_plans = 0
    if member_ids:
        active_plans = int(
            session.scalar(
                select(func.count(Plan.id)).where(
                    Plan.owner_user_id.in_(member_ids),
                    Plan.status == "active",
                    Plan.deleted_at.is_(None),
                )
            )
            or 0
        )
    return OrganizationSummary(
        members_total=len(memberships),
        trainers=len(trainers),
        clients=clients,
        active_plans=active_plans,
    )
