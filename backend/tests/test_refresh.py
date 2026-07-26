"""Pull-to-refresh guards.

The refresh endpoint is unauthenticated (it *is* the pull gesture), and it
spends a metered upstream allowance. So most of these tests assert that it
declines to spend.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.budget import ApiBudget
from app.core.clock import FrozenClock
from app.core.config import get_settings
from app.db.models import SightingSnapshot
from app.providers.base import BaseProvider
from app.providers.chain import FailoverChain, ProviderTier, RegisteredProvider
from app.services.ingest import IngestService
from app.services.learning.engine import LearningEngine
from app.services.prediction.engine import PredictionEngine
from app.services.refresh_service import RefreshOutcome, RefreshService
from tests.factories import direct_sighting


class _Fixed(BaseProvider):
    name = "fixed"
    trust = 0.9

    def __init__(self, sightings, fail=False):
        self._sightings = sightings
        self._fail = fail
        self.calls = 0

    async def fetch_sightings(self, ctx):
        self.calls += 1
        if self._fail:
            raise RuntimeError("upstream is down")
        return list(self._sightings)


@pytest.fixture
def build(settings, now):
    def _build(sightings=None, *, budget=None, fail=False, min_age=420):
        provider = _Fixed(sightings or [direct_sighting(now=now, minutes_ahead=25)], fail=fail)
        chain = FailoverChain(
            [RegisteredProvider(provider, ProviderTier.PRIMARY)], timeout=1.0, max_retries=1
        )
        cfg = get_settings()
        object.__setattr__(cfg, "manual_refresh_min_age_seconds", min_age)
        ingest = IngestService(
            chain=chain, engine=PredictionEngine(), learning=LearningEngine(),
            settings=cfg, budget=budget, clock=FrozenClock(now),
        )
        service = RefreshService(ingest=ingest, settings=cfg, budget=budget)
        return service, provider

    return _build


class TestRefresh:
    async def test_first_pull_on_empty_data_fetches(
        self, session, crossing_row, build, now
    ):
        service, provider = build()
        result = await service.refresh(session, crossing_row, now)

        assert result.outcome is RefreshOutcome.REFRESHED
        assert result.refreshed is True
        assert provider.calls == 1
        assert session.query(SightingSnapshot).count() == 1

    async def test_recent_data_is_not_refetched(self, session, crossing_row, build, now):
        """A pull two minutes after the last fetch must not cost an API call."""
        service, provider = build()
        await service.refresh(session, crossing_row, now)
        session.flush()

        later = now + timedelta(minutes=2)
        result = await service.refresh(session, crossing_row, later)

        assert result.outcome is RefreshOutcome.ALREADY_FRESH
        assert result.refreshed is False
        assert provider.calls == 1, "no second upstream call"
        assert result.next_refresh_at is not None

    async def test_stale_data_is_refetched(self, session, crossing_row, build, now):
        service, provider = build()
        await service.refresh(session, crossing_row, now)
        session.flush()

        result = await service.refresh(session, crossing_row, now + timedelta(minutes=15))

        assert result.outcome is RefreshOutcome.REFRESHED
        assert provider.calls == 2

    async def test_budget_floor_protects_scheduled_ingestion(
        self, session, crossing_row, build, now
    ):
        """With the daily allowance nearly gone, a pull must not spend the
        remainder — the scheduler has first claim on it."""
        clock = FrozenClock(now)
        budget = ApiBudget(daily_limit=100, clock=clock)
        for _ in range(90):
            budget.spend()
        service, provider = build(budget=budget)

        result = await service.refresh(session, crossing_row, now)

        assert result.outcome is RefreshOutcome.BUDGET_PROTECTED
        assert provider.calls == 0
        assert "allowance" in result.reason

    async def test_healthy_budget_permits_refresh(self, session, crossing_row, build, now):
        clock = FrozenClock(now)
        budget = ApiBudget(daily_limit=100, clock=clock)
        for _ in range(20):
            budget.spend()
        service, provider = build(budget=budget)

        assert (await service.refresh(session, crossing_row, now)).refreshed is True
        assert provider.calls == 1

    async def test_provider_failure_is_reported_honestly(
        self, session, crossing_row, build, now
    ):
        service, _ = build(fail=True)
        result = await service.refresh(session, crossing_row, now)

        assert result.outcome is RefreshOutcome.PROVIDER_FAILED
        assert result.refreshed is False
        assert "last known" in result.reason

    async def test_concurrent_pulls_collapse_into_one_fetch(
        self, session, crossing_row, build, now
    ):
        """Ten people pulling at once must cost what one person costs."""
        import asyncio

        service, provider = build()
        results = await asyncio.gather(
            *(service.refresh(session, crossing_row, now) for _ in range(10))
        )

        assert provider.calls == 1
        assert sum(1 for r in results if r.refreshed) >= 1
        assert all(r.outcome is not RefreshOutcome.PROVIDER_FAILED for r in results)


class TestRefreshApi:
    def test_endpoint_returns_status_alongside_outcome(self, client_with_admin):
        client = client_with_admin
        body = client.post("/api/v1/crossings/siraspur/refresh").json()

        assert body["outcome"] in {
            "refreshed", "already_fresh", "budget_protected", "provider_failed"
        }
        assert isinstance(body["refreshed"], bool)
        assert body["reason"]
        assert body["status"]["state"] in {"open", "closed", "closing_soon"}

    def test_a_second_immediate_pull_is_declined_not_faked(self, client_with_admin):
        client = client_with_admin
        client.post("/api/v1/crossings/siraspur/refresh")
        second = client.post("/api/v1/crossings/siraspur/refresh").json()

        assert second["refreshed"] is False
        assert second["outcome"] == "already_fresh"
        assert second["status"]["state"] in {"open", "closed", "closing_soon"}

    def test_travel_seconds_is_honoured(self, client_with_admin):
        body = client_with_admin.post(
            "/api/v1/crossings/siraspur/refresh?travel_seconds=600"
        ).json()
        assert body["status"]["advice"]["travel_seconds"] == 600

    def test_unknown_crossing_is_404(self, client_with_admin):
        assert client_with_admin.post("/api/v1/crossings/nope/refresh").status_code == 404
