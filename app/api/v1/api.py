"""Version 1 router assembly.

The recommendation router is always mounted.  P0.1 profile endpoints are
feature-flagged so the existing deployment keeps working until auth and a
database are configured.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import me, plans, recommendation, workouts
from app.core.config import Settings


def build_api_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    router.include_router(
        recommendation.router,
        prefix="/recommendation",
        tags=["recommendation"],
    )

    if settings.auth_profiles_enabled:
        router.include_router(
            me.router,
            prefix="/me",
            tags=["me"],
        )

    if settings.plans_enabled:
        router.include_router(
            plans.router,
            prefix="/plans",
            tags=["plans"],
        )
        router.include_router(
            plans.public_router,
            prefix="/shared",
            tags=["shared"],
        )

    if settings.workouts_enabled:
        router.include_router(
            workouts.router,
            prefix="/workouts",
            tags=["workouts"],
        )
        router.include_router(
            workouts.sets_router,
            prefix="/sets",
            tags=["workouts"],
        )
        router.include_router(
            workouts.sync_router,
            prefix="/sync",
            tags=["workouts"],
        )

    return router
