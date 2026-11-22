"""Configuration tests for the P0.1 auth/database settings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings

SECRET = "x" * 40


def test_database_url_is_normalised_to_psycopg3() -> None:
    settings = Settings(database_url="postgres://user:pass@host:5432/db")
    assert settings.database_url == "postgresql+psycopg://user:pass@host:5432/db"

    settings = Settings(database_url="postgresql://user:pass@host:5432/db")
    assert settings.database_url == "postgresql+psycopg://user:pass@host:5432/db"

    settings = Settings(database_url="")
    assert settings.database_url is None


def test_dev_auth_mode_is_rejected_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            auth_enabled=True,
            auth_dev_mode=True,
            auth_dev_secret=SECRET,
            auth_issuer="https://issuer.test",
            auth_audience="api",
        )


def test_dev_auth_mode_requires_a_long_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="test",
            auth_enabled=True,
            auth_dev_mode=True,
            auth_dev_secret="short",
            auth_issuer="https://issuer.test",
            auth_audience="api",
        )


def test_profiles_require_auth() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="test",
            auth_profiles_enabled=True,
            auth_enabled=False,
            database_url="sqlite+pysqlite:///./test.db",
        )


def test_profiles_require_database_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            auth_enabled=True,
            auth_profiles_enabled=True,
            auth_issuer="https://issuer.test",
            auth_audience="api",
            auth_jwks_url="https://issuer.test/.well-known/jwks.json",
        )


def test_oidc_configuration_is_required_without_dev_mode() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="test",
            auth_enabled=True,
            auth_dev_mode=False,
        )


def test_hs256_is_rejected_outside_dev_mode() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="test",
            auth_enabled=True,
            auth_dev_mode=False,
            auth_issuer="https://issuer.test",
            auth_audience="api",
            auth_jwks_url="https://issuer.test/.well-known/jwks.json",
            auth_algorithms="HS256",
        )


def test_db_auto_create_is_rejected_in_production() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="production",
            db_auto_create=True,
        )


def test_valid_oidc_configuration_is_accepted() -> None:
    settings = Settings(
        environment="production",
        database_url="postgresql://user:pass@host:5432/db",
        auth_enabled=True,
        auth_profiles_enabled=True,
        auth_issuer="https://issuer.test",
        auth_audience="api",
        auth_jwks_url="https://issuer.test/.well-known/jwks.json",
        auth_algorithms="RS256,ES256",
    )
    assert settings.auth_algorithm_list == ["RS256", "ES256"]
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_cloud_environment_is_inferred(monkeypatch) -> None:
    monkeypatch.setenv("FLY_APP_NAME", "jymz-api")
    settings = Settings(environment="development")
    assert settings.environment == "production"


def test_neon_auth_base_url_derives_issuer_audience_and_jwks() -> None:
    settings = Settings(
        environment="test",
        neon_auth_base_url="https://ep-example.aws.neon.tech/neondb/auth",
        auth_enabled=True,
        auth_profiles_enabled=True,
    )
    assert settings.auth_issuer == "https://ep-example.aws.neon.tech"
    assert settings.auth_audience == "https://ep-example.aws.neon.tech"
    assert (
        settings.auth_jwks_url
        == "https://ep-example.aws.neon.tech/neondb/auth/.well-known/jwks.json"
    )
    assert "EdDSA" in settings.auth_algorithm_list


def test_eddsa_algorithm_is_case_canonicalised() -> None:
    settings = Settings(auth_algorithms="eddsa,rs256")
    assert settings.auth_algorithm_list == ["EdDSA", "RS256"]


def test_invalid_neon_auth_base_url_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="test", neon_auth_base_url="not-a-url")


def test_plans_require_auth_profiles() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="test", plans_enabled=True)
