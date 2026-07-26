"""Unit tests for the primitives everything else stands on."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from app.core.budget import ApiBudget
from app.core.cache import MemoryCache
from app.core.circuit_breaker import CircuitBreaker, CircuitState
from app.core.clock import IST, FrozenClock, ensure_aware, to_ist, to_utc
from app.core.errors import ProviderError, ProviderRateLimited
from app.core.geo import bearing_degrees, clamp, haversine_km, lerp
from app.core.retry import retry_async


class TestGeo:
    def test_haversine_known_distance(self):
        # Badli → Khera Kalan, roughly 4.8 km apart on the ground.
        km = haversine_km(28.7300, 77.1330, 28.7730, 77.1250)
        assert 4.0 < km < 5.5

    def test_haversine_is_zero_for_same_point(self):
        assert haversine_km(28.7, 77.1, 28.7, 77.1) == pytest.approx(0.0, abs=1e-9)

    def test_bearing_north(self):
        assert bearing_degrees(28.0, 77.0, 29.0, 77.0) == pytest.approx(0.0, abs=0.5)

    def test_clamp_and_lerp(self):
        assert clamp(5, 0, 3) == 3
        assert clamp(-1, 0, 3) == 0
        assert lerp(0, 100, 0.25) == 25
        assert lerp(0, 100, 5) == 100  # fraction is clamped


class TestClock:
    def test_naive_datetimes_are_coerced_to_utc(self):
        assert ensure_aware(datetime(2026, 1, 1)).tzinfo is not None

    def test_ist_round_trip(self):
        moment = datetime(2026, 7, 21, 8, 0, tzinfo=IST)
        assert to_ist(to_utc(moment)) == moment

    def test_frozen_clock_advances_only_when_told(self):
        clock = FrozenClock(datetime(2026, 7, 21, 8, 0, tzinfo=IST))
        first = clock.now()
        assert clock.now() == first
        clock.advance(60)
        assert (clock.now() - first).total_seconds() == 60


class TestCircuitBreaker:
    def test_opens_after_threshold(self):
        clock = FrozenClock(datetime(2026, 7, 21, 8, 0, tzinfo=IST))
        breaker = CircuitBreaker("p", failure_threshold=3, reset_timeout=60, clock=clock)
        for _ in range(2):
            breaker.record_failure()
        assert breaker.allows()
        breaker.record_failure()
        assert not breaker.allows()
        assert breaker.state is CircuitState.OPEN

    def test_half_opens_after_reset_timeout_then_recovers(self):
        clock = FrozenClock(datetime(2026, 7, 21, 8, 0, tzinfo=IST))
        breaker = CircuitBreaker("p", failure_threshold=1, reset_timeout=60, clock=clock)
        breaker.record_failure()
        assert not breaker.allows()
        clock.advance(61)
        assert breaker.allows()
        assert breaker.state is CircuitState.HALF_OPEN
        breaker.record_success()
        assert breaker.state is CircuitState.CLOSED

    def test_failure_while_half_open_reopens_immediately(self):
        clock = FrozenClock(datetime(2026, 7, 21, 8, 0, tzinfo=IST))
        breaker = CircuitBreaker("p", failure_threshold=5, reset_timeout=10, clock=clock)
        breaker.record_failure()
        breaker._state = CircuitState.HALF_OPEN  # simulate probe admission
        breaker.record_failure()
        assert breaker.state is CircuitState.OPEN


class TestBudget:
    def test_optional_calls_cannot_touch_the_reserve(self):
        clock = FrozenClock(datetime(2026, 7, 21, 8, 0, tzinfo=IST))
        budget = ApiBudget(daily_limit=10, clock=clock, reserve_fraction=0.5)
        for _ in range(5):
            budget.spend()
        assert budget.can_spend(essential=True)
        assert not budget.can_spend(essential=False)

    def test_resets_at_ist_midnight(self):
        clock = FrozenClock(datetime(2026, 7, 21, 23, 59, tzinfo=IST))
        budget = ApiBudget(daily_limit=5, clock=clock)
        for _ in range(5):
            budget.spend()
        assert budget.remaining == 0
        clock.advance(120)
        assert budget.remaining == 5


class TestCache:
    async def test_set_get_delete(self):
        cache = MemoryCache()
        await cache.set("k", {"v": 1}, 30)
        assert await cache.get("k") == {"v": 1}
        await cache.delete("k")
        assert await cache.get("k") is None

    async def test_rewriting_with_a_different_ttl_does_not_duplicate(self):
        cache = MemoryCache()
        await cache.set("k", "a", 30)
        await cache.set("k", "b", 60)
        assert await cache.get("k") == "b"


class TestRetry:
    async def test_retries_then_succeeds(self):
        attempts = {"n": 0}

        async def flaky():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise ProviderError("p", "boom")
            return "ok"

        async def no_sleep(_: float) -> None:
            return None

        assert await retry_async(flaky, attempts=3, sleep=no_sleep) == "ok"
        assert attempts["n"] == 3

    async def test_non_retryable_error_is_not_retried(self):
        attempts = {"n": 0}

        async def unauthorized():
            attempts["n"] += 1
            raise ProviderError("p", "401", retryable=False)

        with pytest.raises(ProviderError):
            await retry_async(unauthorized, attempts=5, sleep=lambda _: asyncio.sleep(0))
        assert attempts["n"] == 1

    async def test_rate_limit_retry_after_is_honoured(self):
        slept: list[float] = []

        async def record(delay: float) -> None:
            slept.append(delay)

        state = {"n": 0}

        async def limited():
            state["n"] += 1
            if state["n"] == 1:
                raise ProviderRateLimited("p", retry_after=2.0)
            return "ok"

        assert await retry_async(limited, attempts=3, sleep=record) == "ok"
        assert slept == [2.0]


class TestSettings:
    def test_render_style_postgres_urls_are_bound_to_our_driver(self, monkeypatch):
        from app.core.config import Settings

        settings = Settings(database_url="postgres://u:p@host:5432/db")
        assert settings.database_url.startswith("postgresql+psycopg://")
        assert settings.is_sqlite is False

    def test_sqlite_urls_are_left_alone(self):
        from app.core.config import Settings

        settings = Settings(database_url="sqlite+pysqlite:///./x.db")
        assert settings.is_sqlite is True

    def test_cors_origins_accept_a_comma_separated_string(self):
        from app.core.config import Settings

        settings = Settings(cors_origins="https://a.example, https://b.example")
        assert settings.cors_origin_list == ["https://a.example", "https://b.example"]

    def test_mock_provider_is_implied_when_no_key_is_configured(self):
        from app.core.config import Settings

        assert Settings(railradar_api_key=None).has_live_provider is False
        assert Settings(railradar_api_key="rr_live_x").has_live_provider is True


class TestCorsOriginsFromEnvironment:
    """Regression: a bare URL in CORS_ORIGINS crashed the app at import time on
    the first real deploy — the container never bound a port. pydantic-settings
    JSON-decodes complex field types from the environment before validators
    run, so these must be exercised through the env source. The original test
    passed the value to the constructor, which skips that path entirely."""

    def _settings(self, monkeypatch, value: str):
        from app.core.config import Settings

        monkeypatch.setenv("CORS_ORIGINS", value)
        return Settings()

    def test_single_bare_url(self, monkeypatch):
        s = self._settings(monkeypatch, "https://phatak-live.vercel.app")
        assert s.cors_origin_list == ["https://phatak-live.vercel.app"]

    def test_comma_separated(self, monkeypatch):
        s = self._settings(monkeypatch, "https://a.example, https://b.example")
        assert s.cors_origin_list == ["https://a.example", "https://b.example"]

    def test_json_array_is_also_accepted(self, monkeypatch):
        s = self._settings(monkeypatch, '["https://a.example","https://b.example"]')
        assert s.cors_origin_list == ["https://a.example", "https://b.example"]

    def test_malformed_json_degrades_to_empty_rather_than_crashing(self, monkeypatch):
        assert self._settings(monkeypatch, '["unclosed').cors_origin_list == []


class TestStalenessGuard:
    """Regression: a 30-minute ingest cadence against a 15-minute staleness
    threshold meant every response between ticks was flagged stale, and the
    live site showed a permanent 'data is delayed' warning."""

    def test_threshold_is_raised_to_outlive_a_slow_poll_interval(self):
        from app.core.config import Settings

        s = Settings(ingest_interval_seconds=1800, max_sighting_age_seconds=900)
        assert s.max_sighting_age_seconds == 2700

    def test_a_generous_threshold_is_left_alone(self):
        from app.core.config import Settings

        s = Settings(ingest_interval_seconds=90, max_sighting_age_seconds=3600)
        assert s.max_sighting_age_seconds == 3600

    def test_defaults_are_self_consistent(self):
        from app.core.config import Settings

        s = Settings()
        assert s.max_sighting_age_seconds > s.ingest_interval_seconds
