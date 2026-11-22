from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import PROJECT_ROOT, Settings


@pytest.mark.unit
def test_log_level_is_normalised():
    assert Settings(log_level="debug").log_level == "DEBUG"


@pytest.mark.unit
def test_environment_is_normalised():
    assert Settings(environment="PRODUCTION").environment == "production"


@pytest.mark.unit
@pytest.mark.parametrize("value", ["verbose", "trace", ""])
def test_invalid_log_level_is_rejected(value):
    with pytest.raises(ValidationError):
        Settings(log_level=value)


@pytest.mark.unit
def test_render_environment_is_inferred(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    assert Settings(environment="development").environment == "production"


@pytest.mark.unit
def test_empty_ga_seed_is_none():
    assert Settings(ga_random_seed="").ga_random_seed is None


@pytest.mark.unit
def test_invalid_ga_relationships_are_rejected():
    with pytest.raises(ValidationError):
        Settings(ga_sol_per_pop=4, ga_num_parents_mating=8)
    with pytest.raises(ValidationError):
        Settings(ga_sol_per_pop=4, ga_keep_parents=8)


@pytest.mark.unit
def test_relative_dataset_path_is_resolved_from_project_root():
    settings = Settings(dataset_path="data/fitness_dataset.csv")
    assert settings.dataset_path == (PROJECT_ROOT / "data" / "fitness_dataset.csv").resolve()


@pytest.mark.unit
def test_cors_origins_are_split():
    settings = Settings(cors_origins="https://a.example, https://b.example ")
    assert settings.cors_origin_list == ["https://a.example", "https://b.example"]


@pytest.mark.unit
def test_allowed_hosts_are_split():
    settings = Settings(allowed_hosts="api.example,localhost")
    assert settings.allowed_host_list == ["api.example", "localhost"]
