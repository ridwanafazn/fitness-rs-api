"""P1.2 trainer workspace: invitations, consent grants, reviews, comments."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import (
    TrainerAccessDeniedError,
    TrainerClientNotFoundError,
    TrainerInvitationConflictError,
    TrainerInvitationNotFoundError,
    TrainerProfileNotFoundError,
    TrainerValidationError,
)
from app.db.models import (
    AccessGrant,
    Plan,
    PlanReview,
    PlanVersion,
    TrainerClient,
    TrainerComment,
    TrainerInvitation,
    TrainerProfile,
    User,
    WorkoutSession,
)
from app.domain.trainer import (
    SCOPE_VALUES,
    InvitationStatus,
    TrainingScope,
)
from app.schemas.progress import ProgressResponse
from app.schemas.trainer import (
    ClientTrainerOut,
    InvitationAcceptRequest,
    PlanReviewIn,
    PlanReviewOut,
    TrainerClientOut,
    TrainerCommentCreate,
    TrainerCommentOut,
    TrainerFeedbackResponse,
    TrainerInvitationCreate,
    TrainerInvitationOut,
    TrainerPlansResponse,
    TrainerProfileIn,
    TrainerProfileOut,
    TrainerWorkoutsResponse,
)
from app.services.audit import record_audit
from app.services.feedback import list_feedback, serialize_feedback
from app.services.identity import commit_or_conflict
from app.services.plans import list_plans
from app.services.plans import serialize_summary as serialize_plan_summary
from app.services.progress import get_progress
from app.services.workouts import (
    list_workouts,
)
from app.services.workouts import (
    serialize_summary as serialize_workout_summary,
)

INVITATION_TTL_DAYS = 14


def utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _scopes(values: List[TrainingScope]) -> List[str]:
    result: List[str] = []
    for value in values:
        if value.value not in SCOPE_VALUES:
            raise TrainerValidationError(
                "Scope trainer tidak valid.",
                details={"scope": value.value},
            )
        if value.value not in result:
            result.append(value.value)
    return result


def _profile_out(profile: TrainerProfile) -> TrainerProfileOut:
    return TrainerProfileOut(
        id=profile.id,
        user_id=profile.user_id,
        display_name=profile.display_name,
        bio=profile.bio,
        specialties=list(profile.specialties or []),
        years_experience=profile.years_experience,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def get_trainer_profile(session: Session, user_id: uuid.UUID) -> TrainerProfile:
    profile = session.scalar(
        select(TrainerProfile).where(TrainerProfile.user_id == user_id)
    )
    if profile is None:
        raise TrainerProfileNotFoundError()
    return profile


def upsert_trainer_profile(
    session: Session,
    *,
    user_id: uuid.UUID,
    payload: TrainerProfileIn,
    actor_role: str,
) -> TrainerProfile:
    profile = session.scalar(
        select(TrainerProfile).where(TrainerProfile.user_id == user_id)
    )
    created = profile is None
    if profile is None:
        profile = TrainerProfile(user_id=user_id)
        session.add(profile)

    profile.display_name = payload.display_name
    profile.bio = payload.bio
    profile.specialties = list(payload.specialties)
    profile.years_experience = payload.years_experience
    profile.updated_at = utcnow()
    session.flush()

    record_audit(
        session,
        actor_user_id=user_id,
        actor_role=actor_role,
        action="trainer.profile_created" if created else "trainer.profile_updated",
        resource_type="trainer_profile",
        resource_id=str(profile.id),
        metadata={"specialties_count": len(payload.specialties)},
    )
    commit_or_conflict(session)
    return profile


def _invitation_out(invitation: TrainerInvitation) -> TrainerInvitationOut:
    return TrainerInvitationOut(
        id=invitation.id,
        client_user_id=invitation.client_user_id,
        client_email=invitation.client_email,
        requested_scopes=list(invitation.requested_scopes or []),
        status=invitation.status,
        expires_at=invitation.expires_at,
        created_at=invitation.created_at,
    )


def list_invitations(
    session: Session,
    *,
    trainer_user_id: uuid.UUID,
) -> List[TrainerInvitationOut]:
    invitations = list(
        session.scalars(
            select(TrainerInvitation)
            .where(TrainerInvitation.trainer_user_id == trainer_user_id)
            .order_by(TrainerInvitation.created_at.desc())
        ).all()
    )
    return [_invitation_out(invitation) for invitation in invitations]


def create_invitation(
    session: Session,
    *,
    trainer_user_id: uuid.UUID,
    trainer_email: Optional[str],
    payload: TrainerInvitationCreate,
    actor_role: str,
) -> Tuple[TrainerInvitation, str]:
    client_email = payload.client_email
    if trainer_email and trainer_email.lower() == client_email:
        raise TrainerInvitationConflictError("Tidak bisa mengundang diri sendiri.")

    client = session.scalar(
        select(User).where(func.lower(User.email) == client_email)
    )
    if client is not None:
        if client.id == trainer_user_id:
            raise TrainerInvitationConflictError("Tidak bisa mengundang diri sendiri.")
        active = session.scalar(
            select(TrainerClient).where(
                TrainerClient.trainer_user_id == trainer_user_id,
                TrainerClient.client_user_id == client.id,
                TrainerClient.status == "active",
            )
        )
        if active is not None:
            raise TrainerInvitationConflictError("Client sudah terhubung.")

    now = utcnow()
    pending = session.scalar(
        select(TrainerInvitation).where(
            TrainerInvitation.trainer_user_id == trainer_user_id,
            TrainerInvitation.client_email == client_email,
            TrainerInvitation.status == "pending",
            TrainerInvitation.expires_at > now,
        )
    )
    if pending is not None:
        raise TrainerInvitationConflictError(
            "Sudah ada undangan pending untuk email tersebut."
        )

    token = secrets.token_urlsafe(32)
    invitation = TrainerInvitation(
        trainer_user_id=trainer_user_id,
        client_user_id=client.id if client is not None else None,
        client_email=client_email,
        token_hash=_hash_token(token),
        requested_scopes=_scopes(payload.scopes),
        message=payload.message,
        status=InvitationStatus.PENDING.value,
        expires_at=now + timedelta(days=INVITATION_TTL_DAYS),
    )
    session.add(invitation)
    session.flush()

    record_audit(
        session,
        actor_user_id=trainer_user_id,
        actor_role=actor_role,
        action="trainer.invitation_created",
        resource_type="trainer_invitation",
        resource_id=str(invitation.id),
        metadata={
            "scopes": list(invitation.requested_scopes or []),
            "has_account": client is not None,
        },
    )
    commit_or_conflict(session)
    return invitation, token


def _pending_invitation(session: Session, token: str) -> TrainerInvitation:
    invitation = session.scalar(
        select(TrainerInvitation).where(
            TrainerInvitation.token_hash == _hash_token(token)
        )
    )
    if invitation is None or invitation.status != InvitationStatus.PENDING.value:
        raise TrainerInvitationNotFoundError()
    if _as_utc(invitation.expires_at) <= utcnow():
        invitation.status = InvitationStatus.EXPIRED.value
        commit_or_conflict(session)
        raise TrainerInvitationNotFoundError()
    return invitation


def _assert_invitation_recipient(
    invitation: TrainerInvitation,
    *,
    user: User,
) -> None:
    if invitation.client_user_id is not None:
        if invitation.client_user_id != user.id:
            raise TrainerAccessDeniedError("Undangan bukan untuk akun ini.")
        return
    if not user.email or user.email.lower() != invitation.client_email:
        raise TrainerAccessDeniedError("Email akun tidak cocok dengan undangan.")


def _active_link(
    session: Session,
    *,
    trainer_user_id: uuid.UUID,
    client_user_id: uuid.UUID,
) -> TrainerClient:
    link = session.scalar(
        select(TrainerClient).where(
            TrainerClient.trainer_user_id == trainer_user_id,
            TrainerClient.client_user_id == client_user_id,
            TrainerClient.status == "active",
        )
    )
    if link is None:
        raise TrainerClientNotFoundError()
    return link


def _require_access(
    session: Session,
    *,
    trainer_user_id: uuid.UUID,
    client_user_id: uuid.UUID,
    scope: TrainingScope,
) -> TrainerClient:
    link = _active_link(
        session,
        trainer_user_id=trainer_user_id,
        client_user_id=client_user_id,
    )
    grant = session.scalar(
        select(AccessGrant).where(
            AccessGrant.trainer_client_id == link.id,
            AccessGrant.scope == scope.value,
            AccessGrant.revoked_at.is_(None),
        )
    )
    if grant is None:
        raise TrainerAccessDeniedError(
            "Client belum memberikan consent untuk data tersebut.",
            details={"scope": scope.value},
        )
    return link


def accept_invitation(
    session: Session,
    *,
    user: User,
    token: str,
    payload: InvitationAcceptRequest,
    actor_role: str,
) -> TrainerClient:
    invitation = _pending_invitation(session, token)
    _assert_invitation_recipient(invitation, user=user)
    if invitation.client_user_id is None:
        invitation.client_user_id = user.id

    scopes = (
        _scopes(payload.scopes)
        if payload.scopes is not None
        else [str(scope) for scope in (invitation.requested_scopes or [])]
    )
    if not scopes:
        raise TrainerValidationError("Pilih minimal satu scope consent.")
    invalid = [scope for scope in scopes if scope not in SCOPE_VALUES]
    if invalid:
        raise TrainerValidationError(
            "Scope consent tidak valid.",
            details={"invalid_scopes": invalid},
        )

    now = utcnow()
    link = session.scalar(
        select(TrainerClient).where(
            TrainerClient.trainer_user_id == invitation.trainer_user_id,
            TrainerClient.client_user_id == user.id,
        )
    )
    if link is None:
        link = TrainerClient(
            trainer_user_id=invitation.trainer_user_id,
            client_user_id=user.id,
            status="active",
        )
        session.add(link)
        session.flush()
    else:
        link.status = "active"
        link.revoked_at = None
        link.updated_at = now
        session.flush()

    existing = list(
        session.scalars(
            select(AccessGrant).where(AccessGrant.trainer_client_id == link.id)
        ).all()
    )
    existing_by_scope = {grant.scope: grant for grant in existing}
    for grant in existing:
        if grant.scope not in scopes:
            grant.revoked_at = now
            grant.updated_at = now
    for scope in scopes:
        existing_grant = existing_by_scope.get(scope)
        if existing_grant is None:
            session.add(
                AccessGrant(
                    trainer_client_id=link.id,
                    scope=scope,
                    granted_at=now,
                )
            )
        else:
            existing_grant.revoked_at = None
            existing_grant.granted_at = now
            existing_grant.updated_at = now

    invitation.status = InvitationStatus.ACCEPTED.value
    invitation.accepted_at = now
    invitation.updated_at = now

    record_audit(
        session,
        actor_user_id=user.id,
        actor_role=actor_role,
        action="trainer.invitation_accepted",
        resource_type="trainer_client",
        resource_id=str(link.id),
        metadata={"scopes": scopes, "trainer_user_id": str(invitation.trainer_user_id)},
    )
    commit_or_conflict(session)
    return link


def decline_invitation(
    session: Session,
    *,
    user: User,
    token: str,
    actor_role: str,
) -> None:
    invitation = _pending_invitation(session, token)
    _assert_invitation_recipient(invitation, user=user)
    now = utcnow()
    invitation.status = InvitationStatus.DECLINED.value
    invitation.declined_at = now
    invitation.updated_at = now
    record_audit(
        session,
        actor_user_id=user.id,
        actor_role=actor_role,
        action="trainer.invitation_declined",
        resource_type="trainer_invitation",
        resource_id=str(invitation.id),
        metadata={},
    )
    commit_or_conflict(session)


def revoke_client_access(
    session: Session,
    *,
    client_user_id: uuid.UUID,
    trainer_user_id: uuid.UUID,
    actor_role: str,
) -> None:
    link = _active_link(
        session,
        trainer_user_id=trainer_user_id,
        client_user_id=client_user_id,
    )
    now = utcnow()
    link.status = "revoked"
    link.revoked_at = now
    link.updated_at = now
    grants = list(
        session.scalars(
            select(AccessGrant).where(AccessGrant.trainer_client_id == link.id)
        ).all()
    )
    for grant in grants:
        grant.revoked_at = now
        grant.updated_at = now
    record_audit(
        session,
        actor_user_id=client_user_id,
        actor_role=actor_role,
        action="trainer.access_revoked",
        resource_type="trainer_client",
        resource_id=str(link.id),
        metadata={"trainer_user_id": str(trainer_user_id)},
    )
    commit_or_conflict(session)


def _link_scopes(session: Session, link: TrainerClient) -> List[str]:
    return list(
        session.scalars(
            select(AccessGrant.scope)
            .where(
                AccessGrant.trainer_client_id == link.id,
                AccessGrant.revoked_at.is_(None),
            )
            .order_by(AccessGrant.scope)
        ).all()
    )


def list_clients(
    session: Session,
    *,
    trainer_user_id: uuid.UUID,
) -> List[TrainerClientOut]:
    links = list(
        session.scalars(
            select(TrainerClient)
            .where(
                TrainerClient.trainer_user_id == trainer_user_id,
                TrainerClient.status == "active",
            )
            .order_by(TrainerClient.created_at.desc())
        ).all()
    )
    return [serialize_client_link(session, link) for link in links]


def serialize_client_link(
    session: Session,
    link: TrainerClient,
) -> TrainerClientOut:
    client = session.get(User, link.client_user_id)
    return TrainerClientOut(
        id=link.id,
        trainer_user_id=link.trainer_user_id,
        client_user_id=link.client_user_id,
        client_display_name=client.display_name if client else None,
        scopes=_link_scopes(session, link),
        status=link.status,
        created_at=link.created_at,
    )


def list_client_trainers(
    session: Session,
    *,
    client_user_id: uuid.UUID,
) -> List[ClientTrainerOut]:
    links = list(
        session.scalars(
            select(TrainerClient)
            .where(
                TrainerClient.client_user_id == client_user_id,
                TrainerClient.status == "active",
            )
            .order_by(TrainerClient.created_at.desc())
        ).all()
    )
    result: List[ClientTrainerOut] = []
    for link in links:
        profile = session.scalar(
            select(TrainerProfile).where(TrainerProfile.user_id == link.trainer_user_id)
        )
        result.append(
            ClientTrainerOut(
                trainer_user_id=link.trainer_user_id,
                display_name=profile.display_name if profile else "Trainer",
                scopes=_link_scopes(session, link),
                since=link.created_at,
            )
        )
    return result


def list_client_plans(
    session: Session,
    *,
    trainer_user_id: uuid.UUID,
    client_user_id: uuid.UUID,
    limit: int,
    cursor: Optional[str],
    actor_role: str,
) -> TrainerPlansResponse:
    _require_access(
        session,
        trainer_user_id=trainer_user_id,
        client_user_id=client_user_id,
        scope=TrainingScope.PLANS,
    )
    plans, next_cursor = list_plans(
        session,
        owner_user_id=client_user_id,
        limit=limit,
        cursor=cursor,
    )
    record_audit(
        session,
        actor_user_id=trainer_user_id,
        actor_role=actor_role,
        action="trainer.client_plans_viewed",
        resource_type="user",
        resource_id=str(client_user_id),
        metadata={"count": len(plans)},
    )
    commit_or_conflict(session)
    return TrainerPlansResponse(
        items=[serialize_plan_summary(plan) for plan in plans],
        next_cursor=next_cursor,
    )


def list_client_workouts(
    session: Session,
    *,
    trainer_user_id: uuid.UUID,
    client_user_id: uuid.UUID,
    limit: int,
    cursor: Optional[str],
    actor_role: str,
) -> TrainerWorkoutsResponse:
    _require_access(
        session,
        trainer_user_id=trainer_user_id,
        client_user_id=client_user_id,
        scope=TrainingScope.WORKOUTS,
    )
    workouts, next_cursor = list_workouts(
        session,
        owner_user_id=client_user_id,
        limit=limit,
        cursor=cursor,
        status_filter="completed",
    )
    record_audit(
        session,
        actor_user_id=trainer_user_id,
        actor_role=actor_role,
        action="trainer.client_workouts_viewed",
        resource_type="user",
        resource_id=str(client_user_id),
        metadata={"count": len(workouts)},
    )
    commit_or_conflict(session)
    return TrainerWorkoutsResponse(
        items=[serialize_workout_summary(workout) for workout in workouts],
        next_cursor=next_cursor,
    )


def list_client_feedback(
    session: Session,
    *,
    trainer_user_id: uuid.UUID,
    client_user_id: uuid.UUID,
    limit: int,
    cursor: Optional[str],
    actor_role: str,
) -> TrainerFeedbackResponse:
    _require_access(
        session,
        trainer_user_id=trainer_user_id,
        client_user_id=client_user_id,
        scope=TrainingScope.FEEDBACK,
    )
    feedback, next_cursor = list_feedback(
        session,
        plan_id=None,
        limit=limit,
        cursor=cursor,
        owner_user_id=client_user_id,
    )
    record_audit(
        session,
        actor_user_id=trainer_user_id,
        actor_role=actor_role,
        action="trainer.client_feedback_viewed",
        resource_type="user",
        resource_id=str(client_user_id),
        metadata={"count": len(feedback)},
    )
    commit_or_conflict(session)
    return TrainerFeedbackResponse(
        items=[serialize_feedback(item) for item in feedback],
        next_cursor=next_cursor,
    )


def get_client_progress(
    session: Session,
    *,
    trainer_user_id: uuid.UUID,
    client_user_id: uuid.UUID,
    from_date,
    to_date,
    timezone_name: Optional[str],
    actor_role: str,
) -> ProgressResponse:
    _require_access(
        session,
        trainer_user_id=trainer_user_id,
        client_user_id=client_user_id,
        scope=TrainingScope.PROGRESS,
    )
    progress = get_progress(
        session,
        owner_user_id=client_user_id,
        from_date=from_date,
        to_date=to_date,
        timezone_name=timezone_name,
    )
    record_audit(
        session,
        actor_user_id=trainer_user_id,
        actor_role=actor_role,
        action="trainer.client_progress_viewed",
        resource_type="user",
        resource_id=str(client_user_id),
        metadata={"from": str(progress.from_date), "to": str(progress.to_date)},
    )
    commit_or_conflict(session)
    return progress


def create_comment(
    session: Session,
    *,
    trainer_user_id: uuid.UUID,
    client_user_id: uuid.UUID,
    payload: TrainerCommentCreate,
    actor_role: str,
) -> TrainerComment:
    _require_access(
        session,
        trainer_user_id=trainer_user_id,
        client_user_id=client_user_id,
        scope=TrainingScope.PLANS,
    )
    if payload.plan_id is not None:
        plan = session.scalar(
            select(Plan).where(
                Plan.id == payload.plan_id,
                Plan.owner_user_id == client_user_id,
                Plan.deleted_at.is_(None),
            )
        )
        if plan is None:
            raise TrainerValidationError("Plan client tidak ditemukan.")
    if payload.workout_session_id is not None:
        workout = session.scalar(
            select(WorkoutSession).where(
                WorkoutSession.id == payload.workout_session_id,
                WorkoutSession.owner_user_id == client_user_id,
                WorkoutSession.deleted_at.is_(None),
            )
        )
        if workout is None:
            raise TrainerValidationError("Workout client tidak ditemukan.")

    comment = TrainerComment(
        trainer_user_id=trainer_user_id,
        client_user_id=client_user_id,
        plan_id=payload.plan_id,
        workout_session_id=payload.workout_session_id,
        body=payload.body,
    )
    session.add(comment)
    session.flush()
    record_audit(
        session,
        actor_user_id=trainer_user_id,
        actor_role=actor_role,
        action="trainer.comment_created",
        resource_type="trainer_comment",
        resource_id=str(comment.id),
        metadata={
            "client_user_id": str(client_user_id),
            "plan_id": str(payload.plan_id) if payload.plan_id else None,
            "workout_session_id": (
                str(payload.workout_session_id)
                if payload.workout_session_id
                else None
            ),
        },
    )
    commit_or_conflict(session)
    return comment


def review_plan(
    session: Session,
    *,
    trainer_user_id: uuid.UUID,
    plan_id: uuid.UUID,
    payload: PlanReviewIn,
    actor_role: str,
) -> PlanReview:
    plan = session.scalar(
        select(Plan).where(
            Plan.id == plan_id,
            Plan.deleted_at.is_(None),
        )
    )
    if plan is None:
        raise TrainerValidationError("Plan tidak ditemukan.")
    _require_access(
        session,
        trainer_user_id=trainer_user_id,
        client_user_id=plan.owner_user_id,
        scope=TrainingScope.PLANS,
    )
    version = session.scalar(
        select(PlanVersion).where(
            PlanVersion.plan_id == plan.id,
            PlanVersion.version == plan.current_version,
        )
    )
    review = session.scalar(
        select(PlanReview).where(
            PlanReview.plan_id == plan.id,
            PlanReview.trainer_user_id == trainer_user_id,
        )
    )
    if review is None:
        review = PlanReview(
            plan_id=plan.id,
            plan_version_id=version.id if version else None,
            trainer_user_id=trainer_user_id,
            status=payload.status.value,
            note=payload.note,
        )
        session.add(review)
    else:
        review.plan_version_id = version.id if version else None
        review.status = payload.status.value
        review.note = payload.note
        review.updated_at = utcnow()
    session.flush()
    record_audit(
        session,
        actor_user_id=trainer_user_id,
        actor_role=actor_role,
        action="trainer.plan_reviewed",
        resource_type="plan",
        resource_id=str(plan.id),
        metadata={"status": payload.status.value},
    )
    commit_or_conflict(session)
    return review


def _review_out(review: PlanReview) -> PlanReviewOut:
    return PlanReviewOut(
        id=review.id,
        plan_id=review.plan_id,
        plan_version_id=review.plan_version_id,
        trainer_user_id=review.trainer_user_id,
        status=review.status,
        note=review.note,
        created_at=review.created_at,
        updated_at=review.updated_at,
    )


def list_client_reviews(
    session: Session,
    *,
    client_user_id: uuid.UUID,
) -> List[PlanReviewOut]:
    reviews = list(
        session.scalars(
            select(PlanReview)
            .join(Plan, Plan.id == PlanReview.plan_id)
            .where(Plan.owner_user_id == client_user_id)
            .order_by(PlanReview.updated_at.desc())
        ).all()
    )
    return [_review_out(review) for review in reviews]


def _comment_out(comment: TrainerComment) -> TrainerCommentOut:
    return TrainerCommentOut(
        id=comment.id,
        trainer_user_id=comment.trainer_user_id,
        client_user_id=comment.client_user_id,
        plan_id=comment.plan_id,
        workout_session_id=comment.workout_session_id,
        body=comment.body,
        created_at=comment.created_at,
    )


def list_client_comments(
    session: Session,
    *,
    client_user_id: uuid.UUID,
) -> List[TrainerCommentOut]:
    comments = list(
        session.scalars(
            select(TrainerComment)
            .where(TrainerComment.client_user_id == client_user_id)
            .order_by(TrainerComment.created_at.desc())
        ).all()
    )
    return [_comment_out(comment) for comment in comments]
