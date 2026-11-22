"""P1.2 trainer workspace endpoints."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import (
    Principal,
    get_current_principal,
    get_db_session,
    require_trainer,
)
from app.schemas.progress import ProgressResponse
from app.schemas.recommendation import ErrorResponse
from app.schemas.trainer import (
    ClientTrainerListResponse,
    InvitationAcceptRequest,
    PlanReviewIn,
    PlanReviewListResponse,
    PlanReviewOut,
    TrainerClientListResponse,
    TrainerClientOut,
    TrainerCommentCreate,
    TrainerCommentListResponse,
    TrainerCommentOut,
    TrainerFeedbackResponse,
    TrainerInvitationCreate,
    TrainerInvitationCreated,
    TrainerInvitationListResponse,
    TrainerPlansResponse,
    TrainerProfileIn,
    TrainerProfileOut,
    TrainerWorkoutsResponse,
)
from app.services.audit import actor_role_label
from app.services.trainer import (
    accept_invitation,
    create_comment,
    create_invitation,
    decline_invitation,
    get_client_progress,
    get_trainer_profile,
    list_client_comments,
    list_client_feedback,
    list_client_plans,
    list_client_reviews,
    list_client_trainers,
    list_client_workouts,
    list_clients,
    list_invitations,
    review_plan,
    revoke_client_access,
    serialize_client_link,
    upsert_trainer_profile,
)

trainer_router = APIRouter()
client_trainer_router = APIRouter()

_TRAINER_RESPONSES: Dict[int | str, Dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Token tidak valid atau tidak dikirim"},
    403: {"model": ErrorResponse, "description": "Akses trainer/client ditolak"},
    404: {"model": ErrorResponse, "description": "Trainer/client/plan tidak ditemukan"},
    409: {"model": ErrorResponse, "description": "Undangan/akses konflik"},
    422: {"model": ErrorResponse, "description": "Data trainer tidak valid"},
    503: {"model": ErrorResponse, "description": "Auth/database belum dikonfigurasi"},
}


@trainer_router.get(
    "/profile",
    response_model=TrainerProfileOut,
    summary="Profil trainer",
    responses=_TRAINER_RESPONSES,
)
def get_trainer_profile_endpoint(
    principal: Principal = Depends(require_trainer),
    session: Session = Depends(get_db_session),
) -> TrainerProfileOut:
    profile = get_trainer_profile(session, principal.user.id)
    return TrainerProfileOut.model_validate(profile, from_attributes=True)


@trainer_router.put(
    "/profile",
    response_model=TrainerProfileOut,
    summary="Buat/perbarui profil trainer",
    responses=_TRAINER_RESPONSES,
)
def upsert_trainer_profile_endpoint(
    payload: TrainerProfileIn,
    principal: Principal = Depends(require_trainer),
    session: Session = Depends(get_db_session),
) -> TrainerProfileOut:
    profile = upsert_trainer_profile(
        session,
        user_id=principal.user.id,
        payload=payload,
        actor_role=actor_role_label(principal.roles),
    )
    return TrainerProfileOut.model_validate(profile, from_attributes=True)


@trainer_router.post(
    "/invitations",
    response_model=TrainerInvitationCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Undang client",
    responses=_TRAINER_RESPONSES,
)
def create_invitation_endpoint(
    payload: TrainerInvitationCreate,
    request: Request,
    principal: Principal = Depends(require_trainer),
    session: Session = Depends(get_db_session),
) -> TrainerInvitationCreated:
    invitation, token = create_invitation(
        session,
        trainer_user_id=principal.user.id,
        trainer_email=principal.claims.email,
        payload=payload,
        actor_role=actor_role_label(principal.roles),
    )
    invite_url = str(request.url_for("accept_trainer_invitation", token=token))
    return TrainerInvitationCreated(
        id=invitation.id,
        client_email=invitation.client_email,
        requested_scopes=list(invitation.requested_scopes or []),
        status=invitation.status,
        expires_at=invitation.expires_at,
        token=token,
        invite_url=invite_url,
    )


@trainer_router.get(
    "/invitations",
    response_model=TrainerInvitationListResponse,
    summary="Daftar undangan trainer",
    responses=_TRAINER_RESPONSES,
)
def list_invitations_endpoint(
    principal: Principal = Depends(require_trainer),
    session: Session = Depends(get_db_session),
) -> TrainerInvitationListResponse:
    return TrainerInvitationListResponse(
        items=list_invitations(session, trainer_user_id=principal.user.id)
    )


@trainer_router.post(
    "/invitations/{token}/accept",
    response_model=TrainerClientOut,
    summary="Terima undangan trainer",
    responses=_TRAINER_RESPONSES,
)
def accept_trainer_invitation(
    token: str,
    payload: InvitationAcceptRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> TrainerClientOut:
    link = accept_invitation(
        session,
        user=principal.user,
        token=token,
        payload=payload,
        actor_role=actor_role_label(principal.roles),
    )
    return serialize_client_link(session, link)


@trainer_router.post(
    "/invitations/{token}/decline",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Tolak undangan trainer",
    responses=_TRAINER_RESPONSES,
)
def decline_trainer_invitation(
    token: str,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> Response:
    decline_invitation(
        session,
        user=principal.user,
        token=token,
        actor_role=actor_role_label(principal.roles),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@trainer_router.get(
    "/clients",
    response_model=TrainerClientListResponse,
    summary="Daftar client trainer",
    responses=_TRAINER_RESPONSES,
)
def list_clients_endpoint(
    principal: Principal = Depends(require_trainer),
    session: Session = Depends(get_db_session),
) -> TrainerClientListResponse:
    return TrainerClientListResponse(
        items=list_clients(session, trainer_user_id=principal.user.id)
    )


@trainer_router.get(
    "/clients/{client_id}/plans",
    response_model=TrainerPlansResponse,
    summary="Plan client (butuh consent plans)",
    responses=_TRAINER_RESPONSES,
)
def list_client_plans_endpoint(
    client_id: uuid.UUID,
    principal: Principal = Depends(require_trainer),
    session: Session = Depends(get_db_session),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: Optional[str] = Query(default=None, max_length=64),
) -> TrainerPlansResponse:
    return list_client_plans(
        session,
        trainer_user_id=principal.user.id,
        client_user_id=client_id,
        limit=limit,
        cursor=cursor,
        actor_role=actor_role_label(principal.roles),
    )


@trainer_router.get(
    "/clients/{client_id}/workouts",
    response_model=TrainerWorkoutsResponse,
    summary="Riwayat workout client (butuh consent workouts)",
    responses=_TRAINER_RESPONSES,
)
def list_client_workouts_endpoint(
    client_id: uuid.UUID,
    principal: Principal = Depends(require_trainer),
    session: Session = Depends(get_db_session),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: Optional[str] = Query(default=None, max_length=64),
) -> TrainerWorkoutsResponse:
    return list_client_workouts(
        session,
        trainer_user_id=principal.user.id,
        client_user_id=client_id,
        limit=limit,
        cursor=cursor,
        actor_role=actor_role_label(principal.roles),
    )


@trainer_router.get(
    "/clients/{client_id}/feedback",
    response_model=TrainerFeedbackResponse,
    summary="Feedback client (butuh consent feedback)",
    responses=_TRAINER_RESPONSES,
)
def list_client_feedback_endpoint(
    client_id: uuid.UUID,
    principal: Principal = Depends(require_trainer),
    session: Session = Depends(get_db_session),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: Optional[str] = Query(default=None, max_length=64),
) -> TrainerFeedbackResponse:
    return list_client_feedback(
        session,
        trainer_user_id=principal.user.id,
        client_user_id=client_id,
        limit=limit,
        cursor=cursor,
        actor_role=actor_role_label(principal.roles),
    )


@trainer_router.get(
    "/clients/{client_id}/progress",
    response_model=ProgressResponse,
    summary="Progress client (butuh consent progress)",
    responses=_TRAINER_RESPONSES,
)
def get_client_progress_endpoint(
    client_id: uuid.UUID,
    principal: Principal = Depends(require_trainer),
    session: Session = Depends(get_db_session),
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    timezone: Optional[str] = Query(default=None, max_length=64),
) -> ProgressResponse:
    return get_client_progress(
        session,
        trainer_user_id=principal.user.id,
        client_user_id=client_id,
        from_date=from_date,
        to_date=to_date,
        timezone_name=timezone,
        actor_role=actor_role_label(principal.roles),
    )


@trainer_router.post(
    "/clients/{client_id}/comments",
    response_model=TrainerCommentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Komentar untuk client",
    responses=_TRAINER_RESPONSES,
)
def create_comment_endpoint(
    client_id: uuid.UUID,
    payload: TrainerCommentCreate,
    principal: Principal = Depends(require_trainer),
    session: Session = Depends(get_db_session),
) -> TrainerCommentOut:
    comment = create_comment(
        session,
        trainer_user_id=principal.user.id,
        client_user_id=client_id,
        payload=payload,
        actor_role=actor_role_label(principal.roles),
    )
    return TrainerCommentOut.model_validate(comment, from_attributes=True)


@trainer_router.patch(
    "/plans/{plan_id}/review",
    response_model=PlanReviewOut,
    summary="Review plan client",
    responses=_TRAINER_RESPONSES,
)
def review_plan_endpoint(
    plan_id: uuid.UUID,
    payload: PlanReviewIn,
    principal: Principal = Depends(require_trainer),
    session: Session = Depends(get_db_session),
) -> PlanReviewOut:
    review = review_plan(
        session,
        trainer_user_id=principal.user.id,
        plan_id=plan_id,
        payload=payload,
        actor_role=actor_role_label(principal.roles),
    )
    return PlanReviewOut.model_validate(review, from_attributes=True)


@client_trainer_router.get(
    "/trainers",
    response_model=ClientTrainerListResponse,
    summary="Trainer yang punya akses",
    responses=_TRAINER_RESPONSES,
)
def list_my_trainers_endpoint(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> ClientTrainerListResponse:
    return ClientTrainerListResponse(
        items=list_client_trainers(session, client_user_id=principal.user.id)
    )


@client_trainer_router.delete(
    "/trainers/{trainer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cabut akses trainer",
    responses=_TRAINER_RESPONSES,
)
def revoke_trainer_access_endpoint(
    trainer_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> Response:
    revoke_client_access(
        session,
        client_user_id=principal.user.id,
        trainer_user_id=trainer_id,
        actor_role=actor_role_label(principal.roles),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@client_trainer_router.get(
    "/trainer/comments",
    response_model=TrainerCommentListResponse,
    summary="Komentar dari trainer",
    responses=_TRAINER_RESPONSES,
)
def list_my_trainer_comments_endpoint(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> TrainerCommentListResponse:
    return TrainerCommentListResponse(
        items=list_client_comments(session, client_user_id=principal.user.id)
    )


@client_trainer_router.get(
    "/trainer/reviews",
    response_model=PlanReviewListResponse,
    summary="Review plan dari trainer",
    responses=_TRAINER_RESPONSES,
)
def list_my_plan_reviews_endpoint(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> PlanReviewListResponse:
    return PlanReviewListResponse(
        items=list_client_reviews(session, client_user_id=principal.user.id)
    )
