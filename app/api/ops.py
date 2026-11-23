"""P2.3 platform-admin operational status endpoint."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_dataset, get_settings
from app.auth.dependencies import get_db_session, require_platform_admin
from app.core.config import Settings
from app.schemas.ops import OpsStatusOut
from app.schemas.recommendation import ErrorResponse
from app.services.dataset import Dataset
from app.services.ops import ops_status

router = APIRouter(dependencies=[Depends(require_platform_admin)])

_RESPONSES: Dict[int | str, Dict[str, Any]] = {
    401: {"model": ErrorResponse, "description": "Token tidak valid atau tidak dikirim"},
    403: {"model": ErrorResponse, "description": "Akses admin ditolak"},
    503: {"model": ErrorResponse, "description": "Database belum dikonfigurasi"},
}


@router.get(
    "/ops/status",
    response_model=OpsStatusOut,
    summary="Status operasional",
    responses=_RESPONSES,
)
def get_ops_status(
    session: Session = Depends(get_db_session),
    dataset: Dataset = Depends(get_dataset),
    settings: Settings = Depends(get_settings),
) -> OpsStatusOut:
    return ops_status(session, settings=settings, dataset=dataset)
