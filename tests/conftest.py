"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = PROJECT_ROOT / "data" / "fitness_dataset.csv"


@pytest.fixture(scope="session")
def dataset_path() -> Path:
    return DATASET_PATH


@pytest.fixture()
def settings(dataset_path: Path) -> Settings:
    return Settings(
        environment="test",
        dataset_path=dataset_path,
        rate_limit_enabled=False,
        metrics_enabled=False,
        docs_enabled=True,
        ga_num_generations=8,
        ga_sol_per_pop=10,
        ga_num_parents_mating=4,
        ga_keep_parents=2,
        request_timeout_seconds=30.0,
    )


@pytest.fixture()
def app(settings: Settings):
    return create_app(settings)


@pytest.fixture()
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def valid_payload() -> dict:
    return {
        "gender": "male",
        "height_cm": 175.0,
        "weight_kg": 72.0,
        "injuries": [],
        "available_days": 2,
        "preferred_body_part": [],
        "preferred_equipment": [],
        "seed": 42,
    }
