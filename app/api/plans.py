"""P0.2 plan lifecycle endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_recommender
from app.auth.dependencies import Principal, get_current_principal, get_db_session
from app.core.errors import PlanValidationError
from app.db.models import Plan
from app.schemas.plans import (
    PlanCreateRequest,
    PlanImportRequest,
    PlanListResponse,
    PlanResponse,
    PlanShareRequest,
    PlanShareResponse,
    PlanUpdateRequest,
    PlanVersionListResponse,
    PublicPlanResponse,
)
from app.schemas.recommendation import ErrorResponse
from app.services.audit import actor_role_label
from app.services.plans import (
    build_share_response,
    create_plan,
    create_share,
    delete_plan,
    export_ics,
    export_pdf,
    get_owned_plan,
    list_plans,
    list_versions,
    resolve_share,
    revoke_shares,
    serialize_plan,
    serialize_public_plan,
    serialize_summary,
    update_plan,
)
from app.services.recommender import Recommender

router = APIRouter()
public_router = APIRouter()

_PLAN_RESPONSES: Dict[int | str, Dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Token tidak valid atau tidak dikirim"},
    403: {"model": ErrorResponse, "description": "Akses ditolak"},
    404: {"model": ErrorResponse, "description": "Plan tidak ditemukan"},
    409: {"model": ErrorResponse, "description": "Konflik revisi atau data"},
    422: {"model": ErrorResponse, "description": "Plan tidak valid"},
    428: {"model": ErrorResponse, "description": "expected_revision wajib dikirim"},
    503: {"model": ErrorResponse, "description": "Auth/database belum dikonfigurasi"},
}


def _parse_if_match(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    token = value.strip()
    if token.startswith("W/"):
        token = token[2:]
    token = token.strip().strip('"')
    try:
        revision = int(token)
    except ValueError as exc:
        raise PlanValidationError("If-Match harus berisi revision integer.") from exc
    if revision < 1:
        raise PlanValidationError("If-Match harus berisi revision >= 1.")
    return revision


def _expected_revision(payload: PlanUpdateRequest, if_match: Optional[str]) -> Optional[int]:
    header_revision = _parse_if_match(if_match)
    if payload.expected_revision is not None:
        if header_revision is not None and header_revision != payload.expected_revision:
            raise PlanValidationError(
                "expected_revision dan If-Match tidak sama.",
                details={
                    "expected_revision": payload.expected_revision,
                    "if_match": header_revision,
                },
            )
        return payload.expected_revision
    return header_revision


def _owned(
    session: Session,
    plan_id: uuid.UUID,
    principal: Principal,
) -> Plan:
    return get_owned_plan(
        session,
        plan_id=plan_id,
        owner_user_id=principal.user.id,
    )


@router.post(
    "",
    response_model=PlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Buat plan dari input atau simpan hasil rekomendasi",
    responses=_PLAN_RESPONSES,
)
def create_plan_endpoint(
    payload: PlanCreateRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
    recommender: Recommender = Depends(get_recommender),
) -> PlanResponse:
    plan = create_plan(
        session,
        owner_user_id=principal.user.id,
        request=payload.recommendation,
        result=payload.result,
        title=payload.title,
        idempotency_key=idempotency_key,
        recommender=recommender,
        actor_role=actor_role_label(principal.roles),
        source="generated" if payload.result is None else "saved_result",
    )
    return serialize_plan(session, plan)


@router.post(
    "/import",
    response_model=PlanResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Impor plan guest setelah signup",
    responses=_PLAN_RESPONSES,
)
def import_plan_endpoint(
    payload: PlanImportRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
    recommender: Recommender = Depends(get_recommender),
) -> PlanResponse:
    plan = create_plan(
        session,
        owner_user_id=principal.user.id,
        request=payload.recommendation,
        result=payload.result,
        title=payload.title,
        idempotency_key=idempotency_key,
        recommender=recommender,
        actor_role=actor_role_label(principal.roles),
        source="imported",
    )
    return serialize_plan(session, plan)


@router.get(
    "",
    response_model=PlanListResponse,
    summary="Daftar plan milik user",
    responses=_PLAN_RESPONSES,
)
def list_plans_endpoint(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: Optional[str] = Query(default=None, max_length=64),
) -> PlanListResponse:
    plans, next_cursor = list_plans(
        session,
        owner_user_id=principal.user.id,
        limit=limit,
        cursor=cursor,
    )
    return PlanListResponse(
        items=[serialize_summary(plan) for plan in plans],
        next_cursor=next_cursor,
    )


@router.get(
    "/{plan_id}",
    response_model=PlanResponse,
    summary="Detail plan",
    responses=_PLAN_RESPONSES,
)
def get_plan_endpoint(
    plan_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> PlanResponse:
    plan = _owned(session, plan_id, principal)
    return serialize_plan(session, plan)


@router.patch(
    "/{plan_id}",
    response_model=PlanResponse,
    summary="Lock, swap, atau regenerate satu hari",
    responses=_PLAN_RESPONSES,
)
def update_plan_endpoint(
    plan_id: uuid.UUID,
    payload: PlanUpdateRequest,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
    recommender: Recommender = Depends(get_recommender),
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
) -> PlanResponse:
    plan = _owned(session, plan_id, principal)
    updated = update_plan(
        session,
        plan=plan,
        payload=payload,
        expected_revision=_expected_revision(payload, if_match),
        recommender=recommender,
        actor_role=actor_role_label(principal.roles),
    )
    return serialize_plan(session, updated)


@router.delete(
    "/{plan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete plan",
    responses=_PLAN_RESPONSES,
)
def delete_plan_endpoint(
    plan_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> Response:
    plan = _owned(session, plan_id, principal)
    delete_plan(
        session,
        plan=plan,
        actor_role=actor_role_label(principal.roles),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{plan_id}/versions",
    response_model=PlanVersionListResponse,
    summary="Riwayat versi plan",
    responses=_PLAN_RESPONSES,
)
def list_versions_endpoint(
    plan_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> PlanVersionListResponse:
    plan = _owned(session, plan_id, principal)
    return PlanVersionListResponse(items=list_versions(session, plan))


@router.post(
    "/{plan_id}/share",
    response_model=PlanShareResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Buat share link read-only",
    responses=_PLAN_RESPONSES,
)
def create_share_endpoint(
    plan_id: uuid.UUID,
    payload: PlanShareRequest,
    request: Request,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> PlanShareResponse:
    plan = _owned(session, plan_id, principal)
    token, share = create_share(
        session,
        plan=plan,
        expires_in_days=payload.expires_in_days,
        actor_role=actor_role_label(principal.roles),
    )
    share_url = str(request.url_for("get_shared_plan", token=token))
    return build_share_response(token, share, share_url)


@router.delete(
    "/{plan_id}/share",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cabut semua share link plan",
    responses=_PLAN_RESPONSES,
)
def revoke_share_endpoint(
    plan_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> Response:
    plan = _owned(session, plan_id, principal)
    revoke_shares(
        session,
        plan=plan,
        actor_role=actor_role_label(principal.roles),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{plan_id}/export.pdf",
    response_class=Response,
    summary="Ekspor plan sebagai PDF",
    responses=_PLAN_RESPONSES,
)
def export_pdf_endpoint(
    plan_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> Response:
    plan = _owned(session, plan_id, principal)
    content = export_pdf(
        session,
        plan=plan,
        actor_role=actor_role_label(principal.roles),
    )
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="jymz-plan-{plan.id}.pdf"'
        },
    )


@router.get(
    "/{plan_id}/export.ics",
    response_class=Response,
    summary="Ekspor plan sebagai kalender ICS",
    responses=_PLAN_RESPONSES,
)
def export_ics_endpoint(
    plan_id: uuid.UUID,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> Response:
    plan = _owned(session, plan_id, principal)
    content = export_ics(
        session,
        plan=plan,
        actor_role=actor_role_label(principal.roles),
    )
    return Response(
        content=content,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="jymz-plan-{plan.id}.ics"'
        },
    )


@public_router.get(
    "/{token}",
    response_model=PublicPlanResponse,
    name="get_shared_plan",
    summary="Buka plan dari share link (tanpa login)",
    responses={
        404: {"model": ErrorResponse, "description": "Share link tidak valid"},
    },
)
def get_shared_plan(
    token: str,
    session: Session = Depends(get_db_session),
) -> PublicPlanResponse:
    plan, share = resolve_share(session, token)
    return serialize_public_plan(session, plan, share)
