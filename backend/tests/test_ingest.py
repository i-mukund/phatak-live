"""Ingest service: persistence, supersession and retention."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.clock import FrozenClock
from app.core.config import get_settings
from app.db.models import ClosureWindow as ClosureWindowRow
from app.db.models import SightingSnapshot, WindowSource
from app.providers.base import BaseProvider
from app.providers.chain import FailoverChain, ProviderTier, RegisteredProvider
from app.services.ingest import IngestService
from app.services.learning.engine import LearningEngine
from app.services.prediction.engine import PredictionEngine
from tests.factories import direct_sighting


class _Fixed(BaseProvider):
    name = "fixed"
    trust = 0.9

    def __init__(self, sightings):
        self._sightings = sightings

    async def fetch_sightings(self, ctx):
        return list(self._sightings)


@pytest.fixture
def make_ingest(settings, now):
    def _make(sightings):
        chain = FailoverChain(
            [RegisteredProvider(_Fixed(sightings), ProviderTier.PRIMARY)],
            timeout=1.0,
            max_retries=1,
        )
        return IngestService(
            chain=chain,
            engine=PredictionEngine(),
            learning=LearningEngine(),
            settings=get_settings(),
            clock=FrozenClock(now),
        )

    return _make


class TestIngest:
    async def test_a_tick_persists_sightings_and_windows(
        self, session, crossing_row, make_ingest, now
    ):
        ingest = make_ingest([direct_sighting(now=now, minutes_ahead=25)])
        result = await ingest.run_for_crossing(session, crossing_row)

        assert result.sightings == 1
        assert result.windows == 1
        assert session.query(SightingSnapshot).count() == 1
        assert session.query(ClosureWindowRow).count() == 1
        assert ingest.last_tick_at == now

    async def test_reticking_supersedes_the_previous_future_windows(
        self, session, crossing_row, make_ingest, now
    ):
        await make_ingest([direct_sighting(now=now, minutes_ahead=25)]).run_for_crossing(
            session, crossing_row
        )
        session.flush()
        await make_ingest([direct_sighting(now=now, minutes_ahead=40)]).run_for_crossing(
            session, crossing_row
        )
        session.flush()

        live = session.query(ClosureWindowRow).filter_by(is_superseded=False).all()
        assert len(live) == 1, "only the newest view of the future may be live"
        assert session.query(ClosureWindowRow).count() == 2, "history is retained"

    async def test_a_provider_outage_does_not_raise(
        self, session, crossing_row, make_ingest
    ):
        result = await make_ingest([]).run_for_crossing(session, crossing_row)
        assert result.windows == 0
        assert result.sightings == 0

    async def test_one_broken_crossing_does_not_stop_the_others(
        self, session, crossing_row, make_ingest, now
    ):
        from app.db.models import Crossing

        session.add(
            Crossing(
                slug="second", name="Second Gate", latitude=1.0, longitude=1.0,
                prev_station_code="AAA", next_station_code="BBB",
                distance_from_prev_km=1.0, distance_from_next_km=1.0,
            )
        )
        session.flush()
        results = await make_ingest(
            [direct_sighting(now=now, minutes_ahead=25)]
        ).run_all(session)
        assert len(results) == 2

    def test_retention_purges_old_rows(self, session, crossing_row, make_ingest, now):
        session.add(
            ClosureWindowRow(
                crossing_id=crossing_row.id,
                close_at=now - timedelta(days=90),
                open_at=now - timedelta(days=90) + timedelta(minutes=5),
                source=WindowSource.PREDICTED.value,
                confidence=0.5,
            )
        )
        session.flush()
        purged = make_ingest([]).purge_old(session, now, retention_days=30)
        assert purged == 1


class TestDegradedIsPersisted:
    """Regression: the ingest knew it had fallen back to the offline timetable,
    but that fact died before reaching the database — so the read path served
    fallback windows as though they were live, with `degraded: false` and no
    note. Silently presenting scheduled timings as live data is the one thing
    this product must never do."""

    async def test_a_fallback_tick_marks_its_windows(
        self, session, crossing_row, settings, now
    ):
        from app.core.clock import FrozenClock
        from app.core.config import get_settings
        from app.core.errors import ProviderUnavailable
        from app.db.models import ClosureWindow as Row
        from app.providers.chain import FailoverChain, ProviderTier, RegisteredProvider
        from app.services.ingest import IngestService
        from app.services.learning.engine import LearningEngine
        from app.services.prediction.engine import PredictionEngine
        from tests.factories import direct_sighting

        class _Dead(_Fixed):
            name = "primary"

            async def fetch_sightings(self, ctx):
                raise ProviderUnavailable("primary", "quota exhausted")

        fallback = _Fixed([direct_sighting(now=now, minutes_ahead=25)])
        fallback.name = "timetable"
        chain = FailoverChain(
            [
                RegisteredProvider(_Dead([]), ProviderTier.PRIMARY),
                RegisteredProvider(fallback, ProviderTier.FALLBACK),
            ],
            timeout=1.0,
            max_retries=1,
        )
        ingest = IngestService(
            chain=chain, engine=PredictionEngine(), learning=LearningEngine(),
            settings=get_settings(), clock=FrozenClock(now),
        )
        result = await ingest.run_for_crossing(session, crossing_row)
        session.flush()

        assert result.degraded is True
        rows = session.query(Row).all()
        assert rows and all(r.degraded for r in rows), (
            "fallback windows must carry the flag into the database"
        )

    async def test_a_healthy_tick_does_not_mark_its_windows(
        self, session, crossing_row, make_ingest, now
    ):
        from app.db.models import ClosureWindow as Row
        from tests.factories import direct_sighting

        await make_ingest([direct_sighting(now=now, minutes_ahead=25)]).run_for_crossing(
            session, crossing_row
        )
        session.flush()
        assert not any(r.degraded for r in session.query(Row).all())
