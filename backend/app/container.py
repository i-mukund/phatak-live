"""Composition root.

Builds every long-lived collaborator once and hands them out. Constructor
injection everywhere else — no module-level singletons, no service locators, so
tests can build a container with fakes and nothing else changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.budget import ApiBudget
from app.core.cache import Cache, build_cache
from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.db.session import session_scope
from app.providers.chain import FailoverChain
from app.providers.registry import build_budget, build_chain
from app.providers.timetable import TimetableProvider
from app.services.crossing_service import CrossingService
from app.services.ingest import IngestService
from app.services.learning.engine import LearningEngine
from app.services.learning.geometry import GeometryCalibrator
from app.services.prediction.engine import PredictionEngine
from app.services.refresh_service import RefreshService
from app.services.report_service import ReportService
from app.services.status_service import StatusService


@dataclass
class Container:
    settings: Settings
    clock: Clock
    cache: Cache
    budget: ApiBudget
    chain: FailoverChain
    engine: PredictionEngine
    learning: LearningEngine
    geometry: GeometryCalibrator
    ingest: IngestService
    refresh: RefreshService
    reports: ReportService
    status: StatusService
    crossings: CrossingService
    started_at: datetime

    async def aclose(self) -> None:
        await self.chain.close()


def build_container(settings: Settings, clock: Clock | None = None) -> Container:
    clock = clock or SystemClock()
    cache = build_cache(settings.cache_backend, settings.redis_url)
    budget = build_budget(settings, clock)
    chain = build_chain(settings, session_scope=session_scope, cache=cache, clock=clock)

    engine = PredictionEngine(
        blend_horizon_km=settings.blend_horizon_km,
        default_speed_kmph=settings.default_speed_kmph,
        max_sighting_age_seconds=settings.max_sighting_age_seconds,
        horizon_minutes=settings.prediction_horizon_minutes,
    )
    learning = LearningEngine()
    geometry = GeometryCalibrator()
    ingest = IngestService(
        chain=chain,
        engine=engine,
        learning=learning,
        settings=settings,
        budget=budget,
        clock=clock,
    )
    refresh = RefreshService(ingest=ingest, settings=settings, budget=budget)
    reports = ReportService(settings=settings)
    status = StatusService(
        engine=engine,
        learning=learning,
        settings=settings,
        fallback_provider=TimetableProvider(session_scope=session_scope),
    )
    return Container(
        settings=settings,
        clock=clock,
        cache=cache,
        budget=budget,
        chain=chain,
        engine=engine,
        learning=learning,
        geometry=geometry,
        ingest=ingest,
        refresh=refresh,
        reports=reports,
        status=status,
        crossings=CrossingService(),
        started_at=clock.now(),
    )
