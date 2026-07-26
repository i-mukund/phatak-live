"""Application configuration.

Single source of truth for every tunable. Nothing in the codebase may read
``os.environ`` directly; everything goes through :func:`get_settings`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    # ---- application ------------------------------------------------------
    app_name: str = "Phaatak"
    environment: Literal["development", "test", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"
    timezone: str = "Asia/Kolkata"
    api_prefix: str = "/api/v1"
    #: Comma-separated origins, e.g. "https://a.example,https://b.example".
    #: Deliberately a ``str``: pydantic-settings JSON-decodes complex types
    #: straight from the environment *before* any validator runs, so a bare URL
    #: in CORS_ORIGINS raises SettingsError at import time.
    cors_origins: str = "http://localhost:3000"

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

    # ---- manual refresh (pull-to-refresh) --------------------------------
    #: A user-triggered refresh only hits the provider if the newest data is
    #: already older than this. Below it we serve what we have — a pull is a
    #: request for the freshest *available* answer, not a licence to spend.
    manual_refresh_min_age_seconds: int = 420
    #: Refuse to spend on manual refreshes below this share of daily budget,
    #: so a burst of pulls can never starve scheduled ingestion.
    manual_refresh_budget_floor: float = 0.15

    # ---- crowd reports ---------------------------------------------------
    #: One report per client, per crossing, per this window. A person standing
    #: at a shut gate will tap once; tapping again 30 seconds later tells us
    #: nothing new and would double-count the same closure.
    report_cooldown_seconds: int = 600
    #: Fallback cap keyed on client IP, for when localStorage is cleared to
    #: mint a fresh identity.
    report_ip_hourly_limit: int = 12
    #: Reports of the same state within this window are treated as describing
    #: the same event, and corroborate rather than duplicate each other.
    report_corroboration_window_seconds: int = 900

    # ---- scheduler --------------------------------------------------------
    scheduler_enabled: bool = True
    #: Background poll cadence. Each tick costs 2 upstream calls, so this and
    #: ``api_daily_request_budget`` are two views of one constraint:
    #: 86400 / interval * 2 must leave headroom for manual refreshes.
    ingest_interval_seconds: int = 90
    observation_interval_seconds: int = 300
    calibration_interval_seconds: int = 900
    retention_interval_seconds: int = 3600

    # ---- prediction defaults (per-crossing values override these) ---------
    prediction_horizon_minutes: int = 120
    #: Sightings older than this are dropped and the response flagged ``stale``.
    #: MUST exceed ``ingest_interval_seconds``, or every response between two
    #: ticks is stale by construction — which is what the first production
    #: deploy did at a 30-minute cadence. Enforced below, not left to docs.
    max_sighting_age_seconds: int = 2700
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

    @property
    def cors_origin_list(self) -> list[str]:
        """Origins as a list, accepting a bare URL, a comma-separated string or
        a JSON array — all three occur in hosting dashboards."""
        raw = self.cors_origins.strip()
        if raw.startswith("["):
            import json

            try:
                decoded = json.loads(raw)
            except ValueError:
                return []
            return [str(o).strip() for o in decoded if str(o).strip()]
        return [o.strip() for o in raw.split(",") if o.strip()]

    @property
    def scheduled_daily_call_estimate(self) -> int:
        """Upstream calls/day consumed by the scheduler alone."""
        if self.ingest_interval_seconds <= 0:
            return 0
        return int(86_400 / self.ingest_interval_seconds) * 2

    @model_validator(mode="after")
    def _staleness_must_outlive_the_poll_interval(self) -> Settings:
        floor = int(self.ingest_interval_seconds * 1.5)
        if self.max_sighting_age_seconds < floor:
            object.__setattr__(self, "max_sighting_age_seconds", floor)
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def has_live_provider(self) -> bool:
        return bool(self.railradar_api_key or self.generic_rest_base_url)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
