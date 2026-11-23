"""P2.2 research events, experiments, quality reviews, and export endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime
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
from app.domain.research import (
    ExperimentStatus,
    QualityReviewStatus,
    QualitySubjectType,
    VersionKind,
)
from app.schemas.recommendation import ErrorResponse
from app.schemas.research import (
    AssignmentsResponse,
    EventCreate,
    EventOut,
    ExperimentCreate,
    ExperimentListResponse,
    ExperimentOut,
    ExperimentReportOut,
    ExperimentUpdate,
    QualityReviewCreate,
    QualityReviewListResponse,
    QualityReviewOut,
    QualityReviewUpdate,
    ResearchExportOut,
    ResearchReportOut,
    VersionListResponse,
)
from app.services.audit import actor_role_label
from app.services.dataset import Dataset
from app.services.research import (
    assign_experiments,
    create_experiment,
    create_quality_review,
    experiment_report,
    get_experiment,
    get_quality_review,
    list_experiments,
    list_quality_reviews,
    list_versions,
    register_versions,
    research_export,
    research_report,
    serialize_event,
    serialize_experiment,
    serialize_quality_review,
    serialize_version,
    submit_event,
    update_experiment,
    update_quality_review,
)

user_router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_platform_admin)])

_RESPONSES: Dict[int | str, Dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Token tidak valid atau tidak dikirim"},
    403: {"model": ErrorResponse, "description": "Akses research ditolak"},
    404: {"model": ErrorResponse, "description": "Resource research tidak ditemukan"},
    409: {"model": ErrorResponse, "description": "Konflik research"},
    422: {"model": ErrorResponse, "description": "Data research tidak valid"},
    429: {"model": ErrorResponse, "description": "Batas event per jam tercapai"},
    503: {"model": ErrorResponse, "description": "Auth/database/export belum dikonfigurasi"},
}


@user_router.post(
    "/events",
    response_model=EventOut,
    status_code=status.HTTP_201_CREATED,
    summary="Kirim event research",
    responses=_RESPONSES,
)
def create_research_event(
    payload: EventCreate,
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> EventOut:
    event, _ = submit_event(
        session,
        user_id=principal.user.id,
        payload=payload,
        actor_role=actor_role_label(principal.roles),
        limit_per_hour=settings.research_event_rate_limit_per_hour,
    )
    return serialize_event(event)


@user_router.get(
    "/experiments",
    response_model=AssignmentsResponse,
    summary="Assignment eksperimen saya",
    responses=_RESPONSES,
)
def list_my_experiments(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
) -> AssignmentsResponse:
    return AssignmentsResponse(
        items=assign_experiments(session, user_id=principal.user.id)
    )


@admin_router.post(
    "/research/versions/register",
    response_model=VersionListResponse,
    summary="Daftarkan dataset/algorithm version",
    responses=_RESPONSES,
)
def register_research_versions(
    principal: Principal = Depends(require_platform_admin),
    session: Session = Depends(get_db_session),
    dataset: Dataset = Depends(get_dataset),
    settings: Settings = Depends(get_settings),
) -> VersionListResponse:
    records = register_versions(
        session,
        dataset=dataset,
        settings=settings,
        user_id=principal.user.id,
        actor_role=actor_role_label(principal.roles),
    )
    return VersionListResponse(items=[serialize_version(item) for item in records])


@admin_router.get(
    "/research/versions",
    response_model=VersionListResponse,
    summary="Daftar dataset/algorithm version",
    responses=_RESPONSES,
)
def list_research_versions(
    kind: Optional[VersionKind] = Query(default=None),
    session: Session = Depends(get_db_session),
) -> VersionListResponse:
    return VersionListResponse(
        items=list_versions(session, kind=kind.value if kind else None)
    )


@admin_router.get(
    "/research/report",
    response_model=ResearchReportOut,
    summary="Research report agregat",
    responses=_RESPONSES,
)
def get_research_report(
    start: datetime = Query(..., description="Awal window (ISO 8601)"),
    end: datetime = Query(..., description="Akhir window (ISO 8601)"),
    session: Session = Depends(get_db_session),
) -> ResearchReportOut:
    return research_report(session, start=start, end=end)


@admin_router.get(
    "/research/export",
    response_model=ResearchExportOut,
    summary="Export research PII-redacted",
    responses=_RESPONSES,
)
def export_research(
    start: datetime = Query(..., description="Awal window (ISO 8601)"),
    end: datetime = Query(..., description="Akhir window (ISO 8601)"),
    principal: Principal = Depends(require_platform_admin),
    session: Session = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ResearchExportOut:
    return research_export(
        session,
        start=start,
        end=end,
        secret=settings.research_export_secret,
        actor_user_id=principal.user.id,
        actor_role=actor_role_label(principal.roles),
    )


@admin_router.post(
    "/experiments",
    response_model=ExperimentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Buat eksperimen",
    responses=_RESPONSES,
)
def create_experiment_endpoint(
    payload: ExperimentCreate,
    principal: Principal = Depends(require_platform_admin),
    session: Session = Depends(get_db_session),
) -> ExperimentOut:
    experiment = create_experiment(
        session,
        payload=payload,
        user_id=principal.user.id,
        actor_role=actor_role_label(principal.roles),
    )
    return serialize_experiment(experiment)


@admin_router.get(
    "/experiments",
    response_model=ExperimentListResponse,
    summary="Daftar eksperimen",
    responses=_RESPONSES,
)
def list_experiments_endpoint(
    status_filter: Optional[ExperimentStatus] = Query(default=None, alias="status"),
    session: Session = Depends(get_db_session),
) -> ExperimentListResponse:
    return ExperimentListResponse(
        items=list_experiments(
            session,
            status_filter=status_filter.value if status_filter else None,
        )
    )


@admin_router.get(
    "/experiments/{experiment_id}",
    response_model=ExperimentReportOut,
    summary="Laporan eksperimen",
    responses=_RESPONSES,
)
def get_experiment_report(
    experiment_id: uuid.UUID,
    session: Session = Depends(get_db_session),
) -> ExperimentReportOut:
    experiment = get_experiment(session, experiment_id)
    return experiment_report(session, experiment=experiment)


@admin_router.patch(
    "/experiments/{experiment_id}",
    response_model=ExperimentOut,
    summary="Perbarui eksperimen",
    responses=_RESPONSES,
)
def update_experiment_endpoint(
    experiment_id: uuid.UUID,
    payload: ExperimentUpdate,
    principal: Principal = Depends(require_platform_admin),
    session: Session = Depends(get_db_session),
) -> ExperimentOut:
    experiment = update_experiment(
        session,
        experiment_id=experiment_id,
        payload=payload,
        user_id=principal.user.id,
        actor_role=actor_role_label(principal.roles),
    )
    return serialize_experiment(experiment)


@admin_router.post(
    "/quality-reviews",
    response_model=QualityReviewOut,
    status_code=status.HTTP_201_CREATED,
    summary="Buat quality review",
    responses=_RESPONSES,
)
def create_quality_review_endpoint(
    payload: QualityReviewCreate,
    principal: Principal = Depends(require_platform_admin),
    session: Session = Depends(get_db_session),
) -> QualityReviewOut:
    review = create_quality_review(
        session,
        payload=payload,
        reviewer_user_id=principal.user.id,
        actor_role=actor_role_label(principal.roles),
    )
    return serialize_quality_review(review)


@admin_router.get(
    "/quality-reviews",
    response_model=QualityReviewListResponse,
    summary="Daftar quality review",
    responses=_RESPONSES,
)
def list_quality_reviews_endpoint(
    subject_type: Optional[QualitySubjectType] = Query(default=None),
    subject_id: Optional[str] = Query(default=None, max_length=64),
    status_filter: Optional[QualityReviewStatus] = Query(
        default=None, alias="status"
    ),
    limit: int = Query(default=100, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> QualityReviewListResponse:
    return QualityReviewListResponse(
        items=list_quality_reviews(
            session,
            subject_type=subject_type.value if subject_type else None,
            subject_id=subject_id,
            status_filter=status_filter.value if status_filter else None,
            limit=limit,
        )
    )


@admin_router.get(
    "/quality-reviews/{review_id}",
    response_model=QualityReviewOut,
    summary="Detail quality review",
    responses=_RESPONSES,
)
def get_quality_review_endpoint(
    review_id: uuid.UUID,
    session: Session = Depends(get_db_session),
) -> QualityReviewOut:
    return serialize_quality_review(get_quality_review(session, review_id))


@admin_router.patch(
    "/quality-reviews/{review_id}",
    response_model=QualityReviewOut,
    summary="Perbarui quality review",
    responses=_RESPONSES,
)
def update_quality_review_endpoint(
    review_id: uuid.UUID,
    payload: QualityReviewUpdate,
    principal: Principal = Depends(require_platform_admin),
    session: Session = Depends(get_db_session),
) -> QualityReviewOut:
    review = update_quality_review(
        session,
        review_id=review_id,
        payload=payload,
        reviewer_user_id=principal.user.id,
        actor_role=actor_role_label(principal.roles),
    )
    return serialize_quality_review(review)
