"""Application configuration.

All environment-specific values live here.  The rest of the code receives a
``Settings`` instance instead of reading ``os.environ`` directly.  This keeps
tests deterministic and makes deployment configuration explicit.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import field_validator
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

    max_request_bytes: int = 16_384
    request_timeout_seconds: float = 15.0

    # Genetic algorithm defaults.  They can be overridden per deployment.
    ga_num_generations: int = 25
    ga_sol_per_pop: int = 20
    ga_num_parents_mating: int = 8
    ga_mutation_percent_genes: int = 12
    ga_keep_parents: int = 3
    ga_stop_criteria: str = "saturate_8"
    ga_random_seed: Optional[int] = None

    docs_enabled: bool = True
    metrics_enabled: bool = True

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

    @property
    def cors_origin_list(self) -> List[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def allowed_host_list(self) -> List[str]:
        return [item.strip() for item in self.allowed_hosts.split(",") if item.strip()]

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
