"""Ingestion: the only place in the system that performs provider I/O.

One tick per crossing:

    fetch → normalise → predict → persist windows → record predictions →
    derive observations

Everything downstream (API, learning) reads what this wrote. Keeping network
access confined here is what lets a user request stay fast and never fail
because an upstream API is slow (failure modes F1–F3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.budget import ApiBudget
from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.core.logging import get_logger, log_event
from app.core.metrics import BUDGET_REMAINING, INGEST_TICKS
from app.db.models import ClosureWindow as ClosureWindowRow
from app.db.models import Crossing, SightingSnapshot, WindowSource
from app.domain import CrossingRef, TrainSighting
from app.providers.base import FetchContext
from app.providers.chain import FailoverChain
from app.services.crossing_service import to_ref
from app.services.learning.engine import LearningEngine
from app.services.prediction.engine import PredictionEngine
from app.services.prediction.geometry import resolve_transit
from app.services.prediction.model import Prediction

logger = get_logger(__name__)


@dataclass
class IngestResult:
    crossing_slug: str
    sightings: int
    windows: int
    predictions_recorded: int
    observations_recorded: int
    providers_used: list[str]
    degraded: bool
    errors: dict[str, str]


class IngestService:
    def __init__(
        self,
        *,
        chain: FailoverChain,
        engine: PredictionEngine,
        learning: LearningEngine,
        settings: Settings,
        budget: ApiBudget | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._chain = chain
        self._engine = engine
        self._learning = learning
        self._settings = settings
        self._budget = budget
        self._clock = clock or SystemClock()
        self.last_tick_at: datetime | None = None

    async def run_for_crossing(self, session: Session, crossing: Crossing) -> IngestResult:
        now = self._clock.now()
        ref = to_ref(crossing)
        ctx = FetchContext(
            crossing=ref,
            now=now,
            horizon_minutes=self._settings.prediction_horizon_minutes,
            budget=self._budget,
            live_call_allowance=self._settings.api_live_calls_per_tick,
        )

        chain_result = await self._chain.fetch(ctx)
        calibration = self._learning.load_calibration(session, crossing.id)
        prediction = self._engine.predict(
            crossing=ref,
            sightings=chain_result.sightings,
            now=now,
            calibration=calibration,
            degraded=chain_result.degraded,
            providers_used=tuple(chain_result.providers_used),
        )

        self._persist_sightings(session, ref, chain_result.sightings, now)
        window_count = self._persist_windows(
            session, crossing.id, prediction, now, degraded=chain_result.degraded
        )
        recorded = self._learning.record_predictions(session, crossing.id, prediction)
        observed = self._learning.derive_observations(session, ref, chain_result.sightings)

        self.last_tick_at = now
        if self._budget is not None:
            BUDGET_REMAINING.set(self._budget.remaining)
        INGEST_TICKS.labels("degraded" if chain_result.degraded else "ok").inc()

        log_event(
            logger,
            "ingest.tick",
            crossing=crossing.slug,
            sightings=len(chain_result.sightings),
            windows=window_count,
            providers=chain_result.providers_used,
            degraded=chain_result.degraded,
            errors=list(chain_result.errors),
        )
        return IngestResult(
            crossing_slug=crossing.slug,
            sightings=len(chain_result.sightings),
            windows=window_count,
            predictions_recorded=recorded,
            observations_recorded=observed,
            providers_used=list(chain_result.providers_used),
            degraded=chain_result.degraded,
            errors=dict(chain_result.errors),
        )

    async def run_all(self, session: Session) -> list[IngestResult]:
        crossings = list(
            session.scalars(select(Crossing).where(Crossing.is_active.is_(True)))
        )
        results: list[IngestResult] = []
        for crossing in crossings:
            try:
                results.append(await self.run_for_crossing(session, crossing))
            except Exception:
                # One bad crossing must never stop the others.
                INGEST_TICKS.labels("error").inc()
                logger.exception("ingest failed for crossing %s", crossing.slug)
        return results

    # ----------------------------------------------------------- persistence

    def _persist_sightings(
        self,
        session: Session,
        ref: CrossingRef,
        sightings: list[TrainSighting],
        now: datetime,
    ) -> None:
        for sighting in sightings:
            transit = resolve_transit(
                ref,
                sighting,
                now,
                blend_horizon_km=self._settings.blend_horizon_km,
                default_speed_kmph=self._settings.default_speed_kmph,
            )
            session.add(
                SightingSnapshot(
                    crossing_id=ref.id,
                    train_number=sighting.train_number,
                    train_name=sighting.train_name,
                    train_type=sighting.train_type,
                    provider=sighting.provider,
                    provider_trust=sighting.provider_trust,
                    direction=(transit.direction.value if transit
                               else sighting.direct_direction.value),
                    observed_at=now,
                    source_updated_at=sighting.observed_at,
                    delay_minutes=sighting.delay_minutes,
                    distance_to_crossing_km=transit.remaining_km if transit else None,
                    speed_kmph=transit.speed_kmph if transit else None,
                    is_actual_position=bool(transit and transit.is_actual_position),
                    estimated_pass_at=transit.pass_at if transit else None,
                    raw_payload={"provider": sighting.provider, **sighting.raw}
                    if sighting.raw else None,
                )
            )

    def _persist_windows(
        self,
        session: Session,
        crossing_id: int,
        prediction: Prediction,
        now: datetime,
        *,
        degraded: bool = False,
    ) -> int:
        """Replace future predicted windows; never touch elapsed history.

        Windows that have already begun are left alone so "today's closures"
        remains a truthful record rather than being rewritten each tick.
        """
        session.execute(
            update(ClosureWindowRow)
            .where(
                ClosureWindowRow.crossing_id == crossing_id,
                ClosureWindowRow.source == WindowSource.PREDICTED.value,
                ClosureWindowRow.close_at > now,
                ClosureWindowRow.is_superseded.is_(False),
            )
            .values(is_superseded=True)
        )
        written = 0
        for window in prediction.windows:
            if window.open_at <= now:
                continue
            if window.close_at <= now:
                # In-progress closure: update the existing row instead of
                # creating a duplicate, so history stays clean.
                existing = session.scalars(
                    select(ClosureWindowRow).where(
                        ClosureWindowRow.crossing_id == crossing_id,
                        ClosureWindowRow.close_at <= now,
                        ClosureWindowRow.open_at > now,
                        ClosureWindowRow.is_superseded.is_(False),
                    )
                ).first()
                if existing is not None:
                    existing.open_at = window.open_at
                    existing.confidence = window.confidence
                    existing.causes = _causes_json(window)
                    existing.degraded = degraded
                    written += 1
                    continue
            session.add(
                ClosureWindowRow(
                    crossing_id=crossing_id,
                    close_at=window.close_at,
                    open_at=window.open_at,
                    source=WindowSource.PREDICTED.value,
                    confidence=window.confidence,
                    causes=_causes_json(window),
                    is_superseded=False,
                    degraded=degraded,
                )
            )
            written += 1
        return written

    def purge_old(self, session: Session, now: datetime, retention_days: int) -> int:
        """Retention. Unbounded tables are an outage waiting to happen."""
        cutoff = now - timedelta(days=retention_days)
        deleted = 0
        for model, column in (
            (SightingSnapshot, SightingSnapshot.observed_at),
            (ClosureWindowRow, ClosureWindowRow.close_at),
        ):
            rows = session.scalars(select(model).where(column < cutoff)).all()
            for row in rows:
                session.delete(row)
            deleted += len(rows)
        return deleted


def _causes_json(window: object) -> list[dict]:
    return [
        {
            "train_number": c.train_number,
            "train_name": c.train_name,
            "train_class": c.train_class.value,
            "direction": c.direction.value,
            "pass_at": c.pass_at.isoformat(),
            "speed_kmph": c.speed_kmph,
            "delay_minutes": c.delay_minutes,
            "provider": c.provider,
            "estimator": c.estimator.value,
        }
        for c in window.causes  # type: ignore[attr-defined]
    ]
