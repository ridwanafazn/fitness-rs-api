"""P0.3 workout execution and sync endpoints."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_dataset
from app.auth.dependencies import Principal, get_current_principal, get_db_session
from app.schemas.recommendation import ErrorResponse
from app.schemas.workouts import (
    SetCreateRequest,
    SetOut,
    SetUpdateRequest,
    SyncBatchRequest,
    SyncBatchResponse,
    WorkoutCompleteRequest,
    WorkoutListResponse,
    WorkoutResponse,
    WorkoutStartRequest,
    WorkoutSubstituteRequest,
    WorkoutUpdateRequest,
)
from app.services.audit import actor_role_label
from app.services.dataset import Dataset
from app.services.workouts import (
    add_set,
    apply_sync_batch,
    complete_workout,
    delete_set,
    get_owned_workout,
    list_workouts,
    serialize_set,
    serialize_summary,
    serialize_workout,
    start_workout,
    substitute_exercise,
    update_set,
    update_workout,
)

router = APIRouter()
sets_router = APIRouter()
sync_router = APIRouter()

_WORKOUT_RESPONSES: Dict[int | str, Dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Token tidak valid atau tidak dikirim"},
    403: {"model": ErrorResponse, "description": "Akses ditolak"},
    404: {"model": ErrorResponse, "description": "Workout/set/plan tidak ditemukan"},
    409: {"model": ErrorResponse, "description": "Workout selesai atau konflik set"},
    422: {"model": ErrorResponse, "description": "Data workout tidak valid"},
    503: {"model": ErrorResponse, "description": "Auth/database belum dikonfigurasi"},
}


@router.post(
    "/start",
    response_model=WorkoutResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Mulai workout dari satu hari plan",
    responses=_WORKOUT_RESPONSES,
)
def start_workout_endpoint(
    payload: WorkoutStartRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> WorkoutResponse:
    workout = start_workout(
        session,
        owner_user_id=principal.user.id,
        payload=payload,
        actor_role=actor_role_label(principal.roles),
    )
    return serialize_workout(workout)


@router.get(
    "",
    response_model=WorkoutListResponse,
    summary="Riwayat workout",
    responses=_WORKOUT_RESPONSES,
)
def list_workouts_endpoint(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: Optional[str] = Query(default=None, max_length=64),
    status_filter: Optional[str] = Query(default=None, alias="status"),
) -> WorkoutListResponse:
    workouts, next_cursor = list_workouts(
        session,
        owner_user_id=principal.user.id,
        limit=limit,
        cursor=cursor,
        status_filter=status_filter,
    )
    return WorkoutListResponse(
        items=[serialize_summary(workout) for workout in workouts],
        next_cursor=next_cursor,
    )


@router.get(
    "/{workout_id}",
    response_model=WorkoutResponse,
    summary="Detail workout",
    responses=_WORKOUT_RESPONSES,
)
def get_workout_endpoint(
    workout_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> WorkoutResponse:
    workout = get_owned_workout(
        session,
        workout_id=workout_id,
        owner_user_id=principal.user.id,
    )
    return serialize_workout(workout)


@router.patch(
    "/{workout_id}",
    response_model=WorkoutResponse,
    summary="Perbarui catatan workout",
    responses=_WORKOUT_RESPONSES,
)
def update_workout_endpoint(
    workout_id: uuid.UUID,
    payload: WorkoutUpdateRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> WorkoutResponse:
    workout = get_owned_workout(
        session,
        workout_id=workout_id,
        owner_user_id=principal.user.id,
    )
    updated = update_workout(
        session,
        workout=workout,
        payload=payload,
        actor_role=actor_role_label(principal.roles),
    )
    return serialize_workout(updated)


@router.post(
    "/{workout_id}/complete",
    response_model=WorkoutResponse,
    summary="Selesaikan workout",
    responses=_WORKOUT_RESPONSES,
)
def complete_workout_endpoint(
    workout_id: uuid.UUID,
    payload: WorkoutCompleteRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> WorkoutResponse:
    workout = get_owned_workout(
        session,
        workout_id=workout_id,
        owner_user_id=principal.user.id,
    )
    completed = complete_workout(
        session,
        workout=workout,
        payload=payload,
        actor_role=actor_role_label(principal.roles),
    )
    return serialize_workout(completed)


@router.post(
    "/{workout_id}/sets",
    response_model=SetOut,
    status_code=status.HTTP_201_CREATED,
    summary="Tambah set",
    responses=_WORKOUT_RESPONSES,
)
def add_set_endpoint(
    workout_id: uuid.UUID,
    payload: SetCreateRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> SetOut:
    set_log = add_set(
        session,
        owner_user_id=principal.user.id,
        workout_id=workout_id,
        payload=payload,
        actor_role=actor_role_label(principal.roles),
    )
    return serialize_set(set_log)


@router.post(
    "/{workout_id}/exercises/{workout_exercise_id}/substitute",
    response_model=WorkoutResponse,
    summary="Ganti exercise dalam workout",
    responses=_WORKOUT_RESPONSES,
)
def substitute_exercise_endpoint(
    workout_id: uuid.UUID,
    workout_exercise_id: uuid.UUID,
    payload: WorkoutSubstituteRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
    dataset: Dataset = Depends(get_dataset),
) -> WorkoutResponse:
    workout = get_owned_workout(
        session,
        workout_id=workout_id,
        owner_user_id=principal.user.id,
    )
    substitute_exercise(
        session,
        workout=workout,
        workout_exercise_id=workout_exercise_id,
        payload=payload,
        dataset=dataset,
        actor_role=actor_role_label(principal.roles),
    )
    return serialize_workout(
        get_owned_workout(
            session,
            workout_id=workout_id,
            owner_user_id=principal.user.id,
        )
    )


@sets_router.patch(
    "/{set_id}",
    response_model=SetOut,
    summary="Perbarui set",
    responses=_WORKOUT_RESPONSES,
)
def update_set_endpoint(
    set_id: uuid.UUID,
    payload: SetUpdateRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> SetOut:
    set_log = update_set(
        session,
        owner_user_id=principal.user.id,
        set_id=set_id,
        payload=payload,
        actor_role=actor_role_label(principal.roles),
    )
    return serialize_set(set_log)


@sets_router.delete(
    "/{set_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete set",
    responses=_WORKOUT_RESPONSES,
)
def delete_set_endpoint(
    set_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> Response:
    delete_set(
        session,
        owner_user_id=principal.user.id,
        set_id=set_id,
        actor_role=actor_role_label(principal.roles),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@sync_router.post(
    "/batch",
    response_model=SyncBatchResponse,
    summary="Terapkan batch mutation offline",
    responses=_WORKOUT_RESPONSES,
)
def sync_batch_endpoint(
    payload: SyncBatchRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
    dataset: Dataset = Depends(get_dataset),
) -> SyncBatchResponse:
    return apply_sync_batch(
        session,
        owner_user_id=principal.user.id,
        mutations=payload.mutations,
        dataset=dataset,
        actor_role=actor_role_label(principal.roles),
    )
