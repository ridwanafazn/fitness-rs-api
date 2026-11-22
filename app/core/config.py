"""Application configuration.

All environment-specific values live here.  The rest of the code receives a
``Settings`` instance instead of reading ``os.environ`` directly.  This keeps
tests deterministic and makes deployment configuration explicit.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

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
    # environment variable without JSON encoding.
    cors_origins: str = "http://localhost:3000,http://localhost:5173"
    allowed_hosts: str = "*"

    # Optional API key.  When empty the API stays public (useful for demos).
    api_key: Optional[str] = None

    # Rate limiting.  memory:// is fine for a single instance; use a Redis URI
    # when running more than one worker/instance.
    rate_limit_enabled: bool = True
    rate_limit: str = "30/minute"
    rate_limit_storage_uri: str = "memory://"
    # Only enable behind a proxy you control (Render/Cloud Run), otherwise a
    # client can spoof X-Forwarded-For and reset its own rate limit.
    trust_proxy_headers: bool = False

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached settings instance."""

    return Settings()
