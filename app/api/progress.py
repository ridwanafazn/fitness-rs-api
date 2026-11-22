"""P1.1 progress, history, and insights endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import Principal, get_current_principal, get_db_session
from app.schemas.progress import (
    InsightsResponse,
    ProgressHistoryResponse,
    ProgressResponse,
)
from app.schemas.recommendation import ErrorResponse
from app.services.progress import get_insights, get_progress, get_progress_history

router = APIRouter()

_PROGRESS_RESPONSES: Dict[int | str, Dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Token tidak valid atau tidak dikirim"},
    403: {"model": ErrorResponse, "description": "Akses ditolak"},
    422: {"model": ErrorResponse, "description": "Rentang/timezone tidak valid"},
    503: {"model": ErrorResponse, "description": "Auth/database belum dikonfigurasi"},
}


@router.get(
    "/progress",
    response_model=ProgressResponse,
    summary="Progress harian dan total",
    responses=_PROGRESS_RESPONSES,
)
def get_progress_endpoint(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
    timezone: Optional[str] = Query(default=None, max_length=64),
) -> ProgressResponse:
    return get_progress(
        session,
        owner_user_id=principal.user.id,
        from_date=from_date,
        to_date=to_date,
        timezone_name=timezone,
    )


@router.get(
    "/history",
    response_model=ProgressHistoryResponse,
    summary="Riwayat workout selesai",
    responses=_PROGRESS_RESPONSES,
)
def get_history_endpoint(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
    limit: int = Query(default=20, ge=1, le=50),
    cursor: Optional[str] = Query(default=None, max_length=64),
) -> ProgressHistoryResponse:
    return get_progress_history(
        session,
        owner_user_id=principal.user.id,
        limit=limit,
        cursor=cursor,
    )


@router.get(
    "/insights",
    response_model=InsightsResponse,
    summary="Streak, weekly review, body-part balance, dan PR",
    responses=_PROGRESS_RESPONSES,
)
def get_insights_endpoint(
    principal: Principal = Depends(get_current_principal),
    session: Session = Depends(get_db_session),
    timezone: Optional[str] = Query(default=None, max_length=64),
) -> InsightsResponse:
    return get_insights(
        session,
        owner_user_id=principal.user.id,
        timezone_name=timezone,
    )
