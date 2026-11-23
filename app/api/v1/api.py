"""Version 1 router assembly.

The recommendation router is always mounted.  P0.1 profile endpoints are
feature-flagged so the existing deployment keeps working until auth and a
database are configured.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    feedback,
    me,
    notifications,
    organizations,
    plans,
    progress,
    recommendation,
    research,
    trainer,
    workouts,
)
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

    if settings.feedback_enabled:
        router.include_router(
            feedback.router,
            prefix="/feedback",
            tags=["feedback"],
        )
        router.include_router(
            feedback.safety_router,
            prefix="/safety-reports",
            tags=["safety"],
        )
        router.include_router(
            feedback.admin_router,
            prefix="/admin",
            tags=["admin"],
        )

    if settings.progress_enabled:
        router.include_router(
            progress.router,
            prefix="/me",
            tags=["progress"],
        )

    if settings.trainer_enabled:
        router.include_router(
            trainer.trainer_router,
            prefix="/trainer",
            tags=["trainer"],
        )
        router.include_router(
            trainer.client_trainer_router,
            prefix="/me",
            tags=["trainer"],
        )

    if settings.notifications_enabled:
        router.include_router(
            notifications.router,
            prefix="/me",
            tags=["notifications"],
        )
        router.include_router(
            notifications.public_router,
            tags=["notifications"],
        )

    if settings.organizations_enabled:
        router.include_router(
            organizations.router,
            prefix="/orgs",
            tags=["organizations"],
        )
        router.include_router(
            organizations.me_router,
            prefix="/me",
            tags=["organizations"],
        )
        router.include_router(
            organizations.invitation_router,
            prefix="/org-invitations",
            tags=["organizations"],
        )

    if settings.research_enabled:
        router.include_router(
            research.user_router,
            prefix="/me",
            tags=["research"],
        )
        router.include_router(
            research.admin_router,
            prefix="/admin",
            tags=["research"],
        )

    return router
