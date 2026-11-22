"""P0.4 feedback, safety reports, and platform-admin endpoints."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_dataset, get_settings
from app.auth.dependencies import (
    Principal,
    get_current_principal,
    get_db_session,
    require_platform_admin,
)
from app.core.config import Settings
from app.schemas.feedback import (
    AuditListResponse,
    FeedbackCreate,
    FeedbackListResponse,
    FeedbackOut,
    QualitySummary,
    UnsafeReportCreate,
    UnsafeReportListResponse,
    UnsafeReportOut,
    UnsafeReportUpdate,
)
from app.schemas.recommendation import ErrorResponse
from app.services.audit import actor_role_label
from app.services.dataset import Dataset
from app.services.feedback import (
    list_audit,
    list_feedback,
    list_safety_reports,
    quality_summary,
    serialize_audit,
    serialize_feedback,
    serialize_report,
    submit_feedback,
    submit_safety_report,
    update_safety_report,
)

router = APIRouter()
safety_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_platform_admin)])

_COMMON_RESPONSES: Dict[int | str, Dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Token tidak valid atau tidak dikirim"},
    403: {"model": ErrorResponse, "description": "Akses ditolak"},
    429: {"model": ErrorResponse, "description": "Terlalu banyak kiriman"},
    503: {"model": ErrorResponse, "description": "Auth/database belum dikonfigurasi"},
}

_ADMIN_RESPONSES: Dict[int | str, Dict[str, Any]] = {
    **_COMMON_RESPONSES,
    404: {"model": ErrorResponse, "description": "Report/feedback tidak ditemukan"},
    409: {"model": ErrorResponse, "description": "Transisi status tidak valid"},
    422: {"model": ErrorResponse, "description": "Filter atau payload tidak valid"},
}


@router.post(
    "",
    response_model=FeedbackOut,
    status_code=status.HTTP_201_CREATED,
    summary="Kirim feedback plan/workout",
    responses={
        **_COMMON_RESPONSES,
        422: {"model": ErrorResponse, "description": "Feedback tidak valid"},
    },
)
def create_feedback_endpoint(
    payload: FeedbackCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> FeedbackOut:
    feedback = submit_feedback(
        session,
        owner_user_id=principal.user.id,
        payload=payload,
        actor_role=actor_role_label(principal.roles),
        limit_per_hour=settings.feedback_rate_limit_per_hour,
    )
    return serialize_feedback(feedback)


@safety_router.post(
    "",
    response_model=UnsafeReportOut,
    status_code=status.HTTP_201_CREATED,
    summary="Laporkan exercise yang tidak aman",
    responses={
        **_COMMON_RESPONSES,
        422: {"model": ErrorResponse, "description": "Report tidak valid"},
    },
)
def create_safety_report_endpoint(
    payload: UnsafeReportCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
    dataset: Dataset = Depends(get_dataset),
    settings: Settings = Depends(get_settings),
) -> UnsafeReportOut:
    report = submit_safety_report(
        session,
        reporter_user_id=principal.user.id,
        payload=payload,
        dataset=dataset,
        actor_role=actor_role_label(principal.roles),
        limit_per_hour=settings.safety_report_rate_limit_per_hour,
        webhook_url=settings.alert_webhook_url,
    )
    return serialize_report(report)


@admin_router.get(
    "/safety-reports",
    response_model=UnsafeReportListResponse,
    summary="Antrean safety report",
    responses=_ADMIN_RESPONSES,
)
def admin_list_safety_reports(
    session: Session = Depends(get_db_session),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = Query(default=None, max_length=64),
    status_filter: Optional[str] = Query(default=None, alias="status"),
    severity_filter: Optional[str] = Query(default=None, alias="severity"),
) -> UnsafeReportListResponse:
    reports, next_cursor = list_safety_reports(
        session,
        status_filter=status_filter,
        severity_filter=severity_filter,
        limit=limit,
        cursor=cursor,
    )
    return UnsafeReportListResponse(
        items=[serialize_report(report) for report in reports],
        next_cursor=next_cursor,
    )


@admin_router.patch(
    "/safety-reports/{report_id}",
    response_model=UnsafeReportOut,
    summary="Triage, eskalasi, atau selesaikan safety report",
    responses=_ADMIN_RESPONSES,
)
def admin_update_safety_report(
    report_id: uuid.UUID,
    payload: UnsafeReportUpdate,
    principal: Principal = Depends(require_platform_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> UnsafeReportOut:
    report = update_safety_report(
        session,
        report_id=report_id,
        payload=payload,
        admin_user_id=principal.user.id,
        actor_role=actor_role_label(principal.roles),
        webhook_url=settings.alert_webhook_url,
    )
    return serialize_report(report)


@admin_router.get(
    "/feedback",
    response_model=FeedbackListResponse,
    summary="Daftar feedback",
    responses=_ADMIN_RESPONSES,
)
def admin_list_feedback(
    session: Session = Depends(get_db_session),
    plan_id: Optional[uuid.UUID] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = Query(default=None, max_length=64),
) -> FeedbackListResponse:
    feedback, next_cursor = list_feedback(
        session,
        plan_id=plan_id,
        limit=limit,
        cursor=cursor,
    )
    return FeedbackListResponse(
        items=[serialize_feedback(item) for item in feedback],
        next_cursor=next_cursor,
    )


@admin_router.get(
    "/audit",
    response_model=AuditListResponse,
    summary="Audit trail",
    responses=_ADMIN_RESPONSES,
)
def admin_list_audit(
    session: Session = Depends(get_db_session),
    action: Optional[str] = Query(default=None, max_length=100),
    actor_user_id: Optional[uuid.UUID] = Query(default=None),
    resource_type: Optional[str] = Query(default=None, max_length=50),
    limit: int = Query(default=50, ge=1, le=100),
    cursor: Optional[str] = Query(default=None, max_length=64),
) -> AuditListResponse:
    entries, next_cursor = list_audit(
        session,
        action=action,
        actor_user_id=actor_user_id,
        resource_type=resource_type,
        limit=limit,
        cursor=cursor,
    )
    return AuditListResponse(
        items=[serialize_audit(entry) for entry in entries],
        next_cursor=next_cursor,
    )


@admin_router.get(
    "/quality-summary",
    response_model=QualitySummary,
    summary="Metrik feedback dan safety",
    responses=_ADMIN_RESPONSES,
)
def admin_quality_summary(
    session: Session = Depends(get_db_session),
) -> QualitySummary:
    return quality_summary(session)
