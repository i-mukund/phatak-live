"""Failure-mode tests.

Each test here maps to a row in the ARCHITECTURE.md failure table (F1–F6).
The system is allowed to degrade; it is not allowed to fail.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.circuit_breaker import CircuitBreaker
from app.core.clock import FrozenClock
from app.core.errors import ProviderError, ProviderUnavailable
from app.domain import ProviderHealth
from app.providers.base import BaseProvider, FetchContext
from app.providers.chain import FailoverChain, ProviderTier, RegisteredProvider
from tests.factories import direct_sighting


class _Stub(BaseProvider):
    def __init__(self, name, trust, *, sightings=None, error=None, hang=False):
        self.name = name
        self.trust = trust
        self._sightings = sightings or []
        self._error = error
        self._hang = hang
        self.calls = 0

    async def fetch_sightings(self, ctx):
        self.calls += 1
        if self._hang:
            import asyncio

            await asyncio.sleep(5)
        if self._error:
            raise self._error
        return list(self._sightings)

    async def health(self):
        return ProviderHealth(name=self.name, healthy=self._error is None)


def _chain(*registered, timeout=0.2, retries=1):
    return FailoverChain(list(registered), timeout=timeout, max_retries=retries,
                         backoff_base=0.001)


@pytest.fixture
def ctx(ref, now):
    return FetchContext(crossing=ref, now=now)


class TestFailover:
    async def test_f1_primary_failure_falls_through_to_the_fallback_tier(self, ctx, now):
        primary = _Stub("primary", 0.9, error=ProviderUnavailable("primary", "500"))
        fallback = _Stub("timetable", 0.45,
                         sightings=[direct_sighting(now=now, minutes_ahead=20)])
        result = await _chain(
            RegisteredProvider(primary, ProviderTier.PRIMARY),
            RegisteredProvider(fallback, ProviderTier.FALLBACK),
        ).fetch(ctx)

        assert result.sightings, "fallback must still answer"
        assert result.degraded is True
        assert "primary" in result.errors

    async def test_healthy_primary_short_circuits_the_fallback(self, ctx, now):
        primary = _Stub("primary", 0.9,
                        sightings=[direct_sighting(now=now, minutes_ahead=20)])
        fallback = _Stub("timetable", 0.45,
                         sightings=[direct_sighting(now=now, minutes_ahead=99)])
        result = await _chain(
            RegisteredProvider(primary, ProviderTier.PRIMARY),
            RegisteredProvider(fallback, ProviderTier.FALLBACK),
        ).fetch(ctx)

        assert result.degraded is False
        assert fallback.calls == 0, "we must not pay for a fallback we do not need"

    async def test_f3_total_outage_returns_empty_without_raising(self, ctx):
        chain = _chain(
            RegisteredProvider(_Stub("a", 0.9, error=ProviderUnavailable("a", "down"))),
            RegisteredProvider(_Stub("b", 0.4, error=ProviderUnavailable("b", "down")),
                               ProviderTier.FALLBACK),
        )
        result = await chain.fetch(ctx)
        assert result.sightings == []
        assert set(result.errors) == {"a", "b"}

    async def test_a_provider_that_hangs_is_timed_out_not_waited_on(self, ctx, now):
        slow = _Stub("slow", 0.9, hang=True)
        fast = _Stub("timetable", 0.45,
                     sightings=[direct_sighting(now=now, minutes_ahead=20)])
        result = await _chain(
            RegisteredProvider(slow, ProviderTier.PRIMARY),
            RegisteredProvider(fast, ProviderTier.FALLBACK),
        ).fetch(ctx)
        assert result.sightings
        assert "timeout" in result.errors["slow"]

    async def test_a_provider_raising_an_unexpected_exception_is_contained(self, ctx, now):
        broken = _Stub("broken", 0.9, error=RuntimeError("null pointer in a python program"))
        good = _Stub("timetable", 0.45,
                     sightings=[direct_sighting(now=now, minutes_ahead=20)])
        result = await _chain(
            RegisteredProvider(broken, ProviderTier.PRIMARY),
            RegisteredProvider(good, ProviderTier.FALLBACK),
        ).fetch(ctx)
        assert result.sightings
        assert "unexpected" in result.errors["broken"]

    async def test_circuit_opens_and_then_stops_calling_the_provider(self, ctx, now):
        clock = FrozenClock(now)
        breaker = CircuitBreaker("flaky", failure_threshold=1, reset_timeout=60, clock=clock)
        flaky = _Stub("flaky", 0.9, error=ProviderError("flaky", "boom"))
        chain = _chain(RegisteredProvider(flaky, ProviderTier.PRIMARY, breaker))

        await chain.fetch(ctx)
        calls_after_first = flaky.calls
        result = await chain.fetch(ctx)

        assert flaky.calls == calls_after_first, "open circuit must not issue calls"
        assert result.errors["flaky"] == "circuit open"

    async def test_higher_trust_wins_when_two_providers_see_the_same_train(self, ctx, now):
        low = _Stub("low", 0.3,
                    sightings=[direct_sighting(now=now, minutes_ahead=20,
                                               number="12345", trust=0.3)])
        high = _Stub("high", 0.9,
                     sightings=[direct_sighting(now=now, minutes_ahead=22,
                                                number="12345", trust=0.9)])
        result = await _chain(
            RegisteredProvider(low, ProviderTier.PRIMARY),
            RegisteredProvider(high, ProviderTier.PRIMARY),
        ).fetch(ctx)

        assert len(result.sightings) == 1
        assert result.sightings[0].provider_trust == 0.9

    async def test_the_same_train_twice_in_one_day_is_not_collapsed(self, ctx, now):
        """A number that runs twice a day is two services, not one."""
        provider = _Stub(
            "p", 0.9,
            sightings=[
                direct_sighting(now=now, minutes_ahead=10, number="12345"),
                direct_sighting(now=now, minutes_ahead=200, number="12345"),
            ],
        )
        result = await _chain(RegisteredProvider(provider)).fetch(ctx)
        assert len(result.sightings) == 2

    async def test_one_run_straddling_an_hour_boundary_is_not_duplicated(self, ctx, now):
        """Two providers disagreeing by a few minutes must not become two
        closures — the bug a fixed hourly dedup bucket would introduce."""
        low = _Stub("low", 0.4,
                    sightings=[direct_sighting(now=now, minutes_ahead=59, number="12345",
                                               trust=0.4)])
        high = _Stub("high", 0.9,
                     sightings=[direct_sighting(now=now, minutes_ahead=61, number="12345",
                                                trust=0.9)])
        result = await _chain(
            RegisteredProvider(low, ProviderTier.PRIMARY),
            RegisteredProvider(high, ProviderTier.PRIMARY),
        ).fetch(ctx)
        assert len(result.sightings) == 1
        assert result.sightings[0].provider_trust == 0.9

    async def test_health_reports_circuit_state(self, ctx, now):
        clock = FrozenClock(now)
        breaker = CircuitBreaker("p", failure_threshold=1, reset_timeout=60, clock=clock)
        breaker.record_failure()
        chain = _chain(RegisteredProvider(_Stub("p", 0.9), ProviderTier.PRIMARY, breaker))
        health = await chain.health()
        assert health[0].circuit_state == "open"
        assert health[0].healthy is False


class TestEngineRobustness:
    def test_missing_train_data_yields_an_honest_open_state(self, ref, now):
        from app.services.prediction.engine import PredictionEngine
        from app.services.prediction.model import GateState

        prediction = PredictionEngine().predict(crossing=ref, sightings=[], now=now)
        assert prediction.state is GateState.OPEN
        assert prediction.confidence.score < 0.8
        assert any("freight" in n.lower() for n in prediction.confidence.notes)

    def test_a_sighting_with_no_usable_evidence_is_skipped(self, ref, now):
        from dataclasses import replace

        from app.services.prediction.engine import PredictionEngine

        useless = replace(
            direct_sighting(now=now, minutes_ahead=10), direct_pass_estimate=None, route=()
        )
        prediction = PredictionEngine().predict(crossing=ref, sightings=[useless], now=now)
        assert prediction.windows == ()

    def test_a_train_that_already_passed_does_not_create_a_window(self, ref, now):
        from app.services.prediction.engine import PredictionEngine

        prediction = PredictionEngine().predict(
            crossing=ref,
            sightings=[direct_sighting(now=now - timedelta(minutes=1), minutes_ahead=-30)],
            now=now,
        )
        assert prediction.windows == ()
