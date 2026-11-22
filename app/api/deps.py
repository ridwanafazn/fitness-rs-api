"""FastAPI dependencies."""

from __future__ import annotations

from fastapi import Request

from app.core.config import Settings
from app.core.errors import ServiceUnavailableError
from app.services.dataset import Dataset
from app.services.recommender import Recommender


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_dataset(request: Request) -> Dataset:
    dataset = getattr(request.app.state, "dataset", None)
    if dataset is None:
        raise ServiceUnavailableError("Dataset belum siap.")
    return dataset


def get_recommender(request: Request) -> Recommender:
    settings = get_settings(request)
    dataset = get_dataset(request)
    return Recommender(dataset=dataset, settings=settings)
