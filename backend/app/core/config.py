"""Application configuration.

Single source of truth for every tunable. Nothing in the codebase may read
``os.environ`` directly; everything goes through :func:`get_settings`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # ---- application ------------------------------------------------------
    app_name: str = "Phatak Live"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    timezone: str = "Asia/Kolkata"
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    # ---- database ---------------------------------------------------------
    # SQLite by default; set DATABASE_URL=postgresql+psycopg://... for production.
    database_url: str = "sqlite+pysqlite:///./phatak.db"
    db_echo: bool = False
    #: Bring the schema up to date on boot (Alembic in production,
    #: ``create_all`` elsewhere). Disable when migrations are run by a
    #: separate release step.
    auto_migrate: bool = True

    # ---- cache ------------------------------------------------------------
    cache_backend: Literal["memory", "redis"] = "memory"
    redis_url: str | None = None
    cache_status_ttl_seconds: int = 15
    cache_provider_ttl_seconds: int = 60
    cache_crossing_ttl_seconds: int = 300

    # ---- providers --------------------------------------------------------
    railradar_api_key: str | None = None
    railradar_base_url: str = "https://api.railradar.in/v1"
    generic_rest_api_key: str | None = None
    generic_rest_base_url: str | None = None

    provider_timeout_seconds: float = 8.0
    provider_max_retries: int = 3
    provider_backoff_base_seconds: float = 0.5
    circuit_breaker_failure_threshold: int = 4
    circuit_breaker_reset_seconds: float = 120.0

    #: Daily upstream request budget (RailRadar free tier: 100/day once activated).
    api_daily_request_budget: int = 100
    #: Per-tick allowance of expensive per-train "live status" calls.
    api_live_calls_per_tick: int = 2
    #: Enable the mock provider. Forced on when no real key is configured.
    enable_mock_provider: bool = False

    # ---- scheduler --------------------------------------------------------
    scheduler_enabled: bool = True
    ingest_interval_seconds: int = 90
    observation_interval_seconds: int = 300
    calibration_interval_seconds: int = 900
    retention_interval_seconds: int = 3600

    # ---- prediction defaults (per-crossing values override these) ---------
    prediction_horizon_minutes: int = 120
    max_sighting_age_seconds: int = 900
    blend_horizon_km: float = 12.0
    default_speed_kmph: float = 50.0
    retention_days: int = 30

    # ---- security ---------------------------------------------------------
    admin_api_key: str | None = None

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalise_database_url(cls, v: object) -> object:
        """Accept the bare ``postgres://`` URLs that Render, Heroku and Fly hand
        out, and bind them to the driver we actually ship."""
        if isinstance(v, str):
            for prefix in ("postgres://", "postgresql://"):
                if v.startswith(prefix):
                    return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def has_live_provider(self) -> bool:
        return bool(self.railradar_api_key or self.generic_rest_base_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
