"""Application configuration.

All environment-specific values live here.  The rest of the code receives a
``Settings`` instance instead of reading ``os.environ`` directly.  This keeps
tests deterministic and makes deployment configuration explicit.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.db.url import normalize_database_url

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET_PATH = PROJECT_ROOT / "data" / "fitness_dataset.csv"


class Settings(BaseSettings):
    """Runtime settings, loaded from environment variables / ``.env``."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Fitness-RS API"
    app_version: str = "2.0.0"
    environment: str = "development"  # development | staging | production | test
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"

    dataset_path: Path = DEFAULT_DATASET_PATH

    # CORS is a comma-separated string so it can be configured from a plain
    # environment variable without JSON encoding. The wildcard is kept as the
    # default because the existing frontend was built against the old API;
    # set explicit origins in production as soon as they are known.
    cors_origins: str = "*"
    allowed_hosts: str = "*"

    # Optional API key.  When empty the API stays public (useful for demos).
    api_key: Optional[str] = None

    # Postgres (or SQLite for local development).  P0.1 endpoints are disabled
    # unless AUTH_PROFILES_ENABLED=true, so the recommendation-only deployment
    # keeps working without a database.
    database_url: Optional[str] = None
    # Convenience for local/test only. Production schema changes use Alembic.
    db_auto_create: bool = False

    # OIDC authentication and the P0.1 profile/consent endpoints.
    auth_enabled: bool = False
    auth_profiles_enabled: bool = False
    auth_issuer: Optional[str] = None
    auth_audience: Optional[str] = None
    auth_jwks_url: Optional[str] = None
    auth_algorithms: str = "EdDSA,RS256,ES256"
    auth_jwks_cache_seconds: int = Field(default=3600, ge=60, le=86_400)
    auth_leeway_seconds: int = Field(default=30, ge=0, le=300)

    # Neon Auth convenience: derives issuer/audience (origin) and JWKS URL.
    neon_auth_base_url: Optional[str] = None

    # Test/local-only symmetric signing. Never allowed in production.
    auth_dev_mode: bool = False
    auth_dev_secret: Optional[SecretStr] = None

    consent_policy_version: str = "2026-01"
    account_deletion_grace_days: int = Field(default=30, ge=1, le=365)

    # P0.2 plan lifecycle. Requires P0.1 auth/profile endpoints and a database.
    plans_enabled: bool = False

    # P0.3 workout execution. Requires P0.2 plans and a database.
    workouts_enabled: bool = False

    # P0.4 feedback and safety reports. Requires P0.1 auth and a database.
    feedback_enabled: bool = False
    feedback_rate_limit_per_hour: int = Field(default=20, ge=1, le=1000)
    safety_report_rate_limit_per_hour: int = Field(default=10, ge=1, le=1000)
    alert_webhook_url: Optional[str] = None

    # P1.1 progress aggregates and insights. Requires P0.3 workouts.
    progress_enabled: bool = False

    # Rate limiting.  memory:// is fine for a single instance; use a Redis URI
    # when running more than one worker/instance.
    rate_limit_enabled: bool = True
    rate_limit: str = "120/minute"
    rate_limit_storage_uri: str = "memory://"
    # Render/Cloud Run sit in front of the app, so the forwarded client IP is
    # needed to avoid putting every user in one shared bucket. Set this to
    # false only when the app is directly exposed.
    trust_proxy_headers: bool = True

    max_request_bytes: int = Field(default=16_384, gt=0, le=10_000_000)
    request_timeout_seconds: float = Field(default=15.0, gt=0, le=120)

    # Genetic algorithm defaults.  They can be overridden per deployment.
    ga_num_generations: int = Field(default=25, ge=1, le=1000)
    ga_sol_per_pop: int = Field(default=20, ge=2, le=1000)
    ga_num_parents_mating: int = Field(default=8, ge=1, le=1000)
    ga_mutation_percent_genes: int = Field(default=12, ge=1, le=100)
    ga_keep_parents: int = Field(default=3, ge=0, le=1000)
    ga_stop_criteria: str = "saturate_8"
    ga_random_seed: Optional[int] = Field(default=None, ge=0, le=2**32 - 1)

    docs_enabled: bool = True
    metrics_enabled: bool = True

    @field_validator("ga_random_seed", mode="before")
    @classmethod
    def _empty_seed_is_none(cls, value):
        if value == "":
            return None
        return value

    @field_validator("dataset_path", mode="after")
    @classmethod
    def _resolve_dataset_path(cls, value: Path) -> Path:
        if value.is_absolute():
            return value
        return (PROJECT_ROOT / value).resolve()

    @field_validator("database_url", mode="after")
    @classmethod
    def _normalise_database_url(cls, value: Optional[str]) -> Optional[str]:
        return normalize_database_url(value)

    @field_validator("auth_algorithms")
    @classmethod
    def _normalise_auth_algorithms(cls, value: str) -> str:
        allowed = {
            "RS256",
            "RS384",
            "RS512",
            "ES256",
            "ES384",
            "ES512",
            "PS256",
            "PS384",
            "PS512",
            "EdDSA",
            "HS256",
        }
        canonical = {"EDDSA": "EdDSA"}
        items = [
            canonical.get(item.strip().upper(), item.strip().upper())
            for item in value.split(",")
            if item.strip()
        ]
        if not items:
            raise ValueError("AUTH_ALGORITHMS tidak boleh kosong")
        unknown = sorted(set(items) - allowed)
        if unknown:
            raise ValueError(f"AUTH_ALGORITHMS tidak didukung: {', '.join(unknown)}")
        return ",".join(dict.fromkeys(items))

    @field_validator("neon_auth_base_url", mode="after")
    @classmethod
    def _normalise_neon_auth_base_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        base = value.strip().rstrip("/")
        if not base:
            return None
        if not base.startswith(("https://", "http://")):
            raise ValueError("NEON_AUTH_BASE_URL harus URL HTTP(S)")
        return base

    @field_validator("log_level")
    @classmethod
    def _normalise_log_level(cls, value: str) -> str:
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}")
        return upper

    @field_validator("environment")
    @classmethod
    def _normalise_environment(cls, value: str) -> str:
        allowed = {"development", "staging", "production", "test"}
        lower = value.lower()
        if lower not in allowed:
            raise ValueError(f"ENVIRONMENT must be one of {sorted(allowed)}")
        return lower

    @model_validator(mode="after")
    def _validate_ga_relationships(self) -> Settings:
        if self.ga_num_parents_mating > self.ga_sol_per_pop:
            raise ValueError("GA_NUM_PARENTS_MATING tidak boleh melebihi GA_SOL_PER_POP")
        if self.ga_keep_parents > self.ga_sol_per_pop:
            raise ValueError("GA_KEEP_PARENTS tidak boleh melebihi GA_SOL_PER_POP")
        return self

    @model_validator(mode="after")
    def _infer_cloud_environment(self) -> Settings:
        if self.environment == "development" and any(
            os.getenv(name)
            for name in (
                "RENDER",
                "RENDER_SERVICE_ID",
                "FLY_APP_NAME",
                "K_SERVICE",
                "K_REVISION",
            )
        ):
            self.environment = "production"
        return self

    @model_validator(mode="after")
    def _validate_auth_configuration(self) -> Settings:
        if self.db_auto_create and self.is_production:
            raise ValueError("DB_AUTO_CREATE tidak boleh aktif di production")

        if self.neon_auth_base_url:
            parsed = urlparse(self.neon_auth_base_url)
            if not parsed.scheme or not parsed.netloc:
                raise ValueError("NEON_AUTH_BASE_URL tidak valid")
            origin = f"{parsed.scheme}://{parsed.netloc}"
            if not self.auth_issuer:
                self.auth_issuer = origin
            if not self.auth_audience:
                self.auth_audience = origin
            if not self.auth_jwks_url:
                self.auth_jwks_url = f"{self.neon_auth_base_url}/.well-known/jwks.json"
            if "EdDSA" not in self.auth_algorithm_list:
                self.auth_algorithms = f"{self.auth_algorithms},EdDSA"

        if self.auth_dev_mode:
            if self.is_production:
                raise ValueError("AUTH_DEV_MODE tidak boleh aktif di production")
            secret = self.auth_dev_secret_value
            if not secret or len(secret) < 32:
                raise ValueError("AUTH_DEV_SECRET minimal 32 karakter di dev mode")
            if not self.auth_issuer or not self.auth_audience:
                raise ValueError("AUTH_ISSUER dan AUTH_AUDIENCE wajib di dev mode")

        if self.auth_enabled and not self.auth_dev_mode:
            missing = [
                name
                for name, value in (
                    ("AUTH_ISSUER", self.auth_issuer),
                    ("AUTH_AUDIENCE", self.auth_audience),
                    ("AUTH_JWKS_URL", self.auth_jwks_url),
                )
                if not value
            ]
            if missing:
                raise ValueError(f"Konfigurasi auth belum lengkap: {', '.join(missing)}")
            if self.auth_jwks_url and not self.auth_jwks_url.startswith("https://"):
                raise ValueError("AUTH_JWKS_URL harus HTTPS")
            if "HS256" in self.auth_algorithm_list:
                raise ValueError("HS256 hanya diizinkan saat AUTH_DEV_MODE=true")

        if self.auth_profiles_enabled:
            if not self.auth_enabled:
                raise ValueError("AUTH_PROFILES_ENABLED membutuhkan AUTH_ENABLED=true")
            if self.is_production and not self.database_url:
                raise ValueError("DATABASE_URL wajib di production saat profil aktif")

        if self.plans_enabled:
            if not self.auth_profiles_enabled:
                raise ValueError("PLANS_ENABLED membutuhkan AUTH_PROFILES_ENABLED=true")
            if self.is_production and not self.database_url:
                raise ValueError("DATABASE_URL wajib di production saat plan aktif")

        if self.workouts_enabled:
            if not self.plans_enabled:
                raise ValueError("WORKOUTS_ENABLED membutuhkan PLANS_ENABLED=true")
            if self.is_production and not self.database_url:
                raise ValueError("DATABASE_URL wajib di production saat workout aktif")

        if self.feedback_enabled:
            if not self.auth_profiles_enabled:
                raise ValueError("FEEDBACK_ENABLED membutuhkan AUTH_PROFILES_ENABLED=true")
            if self.is_production and not self.database_url:
                raise ValueError("DATABASE_URL wajib di production saat feedback aktif")

        if self.progress_enabled:
            if not self.workouts_enabled:
                raise ValueError("PROGRESS_ENABLED membutuhkan WORKOUTS_ENABLED=true")
            if self.is_production and not self.database_url:
                raise ValueError("DATABASE_URL wajib di production saat progress aktif")

        return self

    @property
    def cors_origin_list(self) -> List[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def allowed_host_list(self) -> List[str]:
        hosts = [item.strip() for item in self.allowed_hosts.split(",") if item.strip()]
        return hosts or ["*"]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_test(self) -> bool:
        return self.environment == "test"

    @property
    def auth_algorithm_list(self) -> List[str]:
        return [item.strip() for item in self.auth_algorithms.split(",") if item.strip()]

    @property
    def auth_dev_secret_value(self) -> Optional[str]:
        if self.auth_dev_secret is None:
            return None
        return self.auth_dev_secret.get_secret_value()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""

    return Settings()
