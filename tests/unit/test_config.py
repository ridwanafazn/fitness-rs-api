from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


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
def test_cors_origins_are_split():
    settings = Settings(cors_origins="https://a.example, https://b.example ")
    assert settings.cors_origin_list == ["https://a.example", "https://b.example"]


@pytest.mark.unit
def test_allowed_hosts_are_split():
    settings = Settings(allowed_hosts="api.example,localhost")
    assert settings.allowed_host_list == ["api.example", "localhost"]
