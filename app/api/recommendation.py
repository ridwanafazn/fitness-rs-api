"""Recommendation endpoints (thin HTTP layer)."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.api.deps import get_recommender
from app.core.errors import ServiceUnavailableError
from app.core.security import require_api_key
from app.domain.models import UserProfile
from app.schemas.recommendation import (
    ByFocusRequest,
    ByFocusResponse,
    ErrorResponse,
    RecommendationRequest,
    RecommendationResponse,
)
from app.services.recommender import Recommender

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(require_api_key)])


async def _run_with_timeout(recommender: Recommender, func, *args, **kwargs):
    timeout = recommender.settings.request_timeout_seconds
    try:
        return await asyncio.wait_for(
            run_in_threadpool(func, *args, **kwargs),
            timeout=timeout,
        )
    except TimeoutError as exc:
        logger.warning(
            "recommendation_timeout",
            extra={"timeout_seconds": timeout},
        )
        raise ServiceUnavailableError("Waktu komputasi rekomendasi habis. Coba lagi.") from exc


@router.post(
    "/",
    response_model=RecommendationResponse,
    status_code=200,
    summary="Buat rencana latihan mingguan",
    responses={
        401: {"model": ErrorResponse, "description": "API key tidak valid"},
        413: {"model": ErrorResponse, "description": "Body request terlalu besar"},
        422: {"model": ErrorResponse, "description": "Input atau constraint tidak valid"},
        429: {"model": ErrorResponse, "description": "Rate limit terlampaui"},
        500: {"model": ErrorResponse, "description": "Kesalahan internal"},
        503: {"model": ErrorResponse, "description": "Komputasi timeout"},
    },
)
async def create_recommendation(
    payload: RecommendationRequest,
    recommender: Recommender = Depends(get_recommender),
) -> RecommendationResponse:
    profile = UserProfile(
        gender=payload.gender,
        height_cm=payload.height_cm,
        weight_kg=payload.weight_kg,
        injuries=tuple(payload.injuries),
        available_days=payload.available_days,
        preferred_body_part=tuple(payload.preferred_body_part),
        preferred_equipment=tuple(payload.preferred_equipment),
        seed=payload.seed,
    )

    plan = await _run_with_timeout(recommender, recommender.recommend, profile)
    return RecommendationResponse.from_plan(plan)


@router.post(
    "/by-focus",
    response_model=ByFocusResponse,
    status_code=200,
    summary="Buat satu sesi latihan untuk fokus tertentu",
    responses={
        401: {"model": ErrorResponse, "description": "API key tidak valid"},
        413: {"model": ErrorResponse, "description": "Body request terlalu besar"},
        422: {"model": ErrorResponse, "description": "Input atau constraint tidak valid"},
        429: {"model": ErrorResponse, "description": "Rate limit terlampaui"},
        500: {"model": ErrorResponse, "description": "Kesalahan internal"},
        503: {"model": ErrorResponse, "description": "Komputasi timeout"},
    },
)
async def recommend_by_focus(
    payload: ByFocusRequest,
    recommender: Recommender = Depends(get_recommender),
) -> ByFocusResponse:
    day, seed = await _run_with_timeout(
        recommender,
        recommender.recommend_day,
        focus=payload.day_focus,
        injuries=tuple(payload.injuries),
        preferred_equipment=tuple(payload.preferred_equipment),
        preferred_body_part=tuple(payload.preferred_body_part),
        seed=payload.seed,
    )

    return ByFocusResponse.from_day(
        day,
        seed=seed,
        dataset_version=recommender.dataset.version,
        algorithm_version=recommender.settings.app_version,
    )
