"""The learning engine.

Every prediction is written down. Later, ground truth arrives — from provider
*actual* times at the bracketing stations, or from a user tapping "gate is
closed" — and each prediction is graded. The signed errors drive an EWMA
calibration per (crossing, train class), which the prediction engine reads on
its next run.

Why EWMA and not a regression model: at launch there is no labelled data, gate
behaviour drifts (staff, signalling upgrades, doubling of a line), and a
commuter deserves an explanation. A running offset with a sample count is
honest, adapts to drift, and can be inspected in one SQL query.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import to_ist
from app.core.geo import clamp
from app.core.logging import get_logger
from app.core.metrics import PREDICTION_ERROR
from app.db.models import (
    CalibrationProfile,
    GateReport,
    Observation,
    ObservationSource,
    PredictionRecord,
)
from app.domain import CrossingRef, TrainSighting
from app.services.prediction.calibration import DEFAULT_KEY, Calibration, CalibrationSet
from app.services.prediction.model import Prediction

logger = get_logger(__name__)

#: A prediction and an observation refer to the same event if their pass times
#: are within this tolerance. Wider than typical error, narrower than headway.
MATCH_TOLERANCE = timedelta(minutes=25)
#: Ignore absurd residuals — they are data errors, not gate behaviour, and
#: letting them into the EWMA would poison it for days.
MAX_PLAUSIBLE_ERROR_SECONDS = 45 * 60


class LearningEngine:
    def __init__(
        self,
        *,
        min_alpha: float = 0.06,
        max_alpha: float = 0.5,
        maturity_samples: int = 30,
    ) -> None:
        self.min_alpha = min_alpha
        self.max_alpha = max_alpha
        self.maturity_samples = maturity_samples

    # ------------------------------------------------------------- writing

    def record_predictions(
        self, session: Session, crossing_id: int, prediction: Prediction
    ) -> int:
        """Persist one row per train cause, deduplicated within the tolerance.

        We re-predict every 90 s; without dedup a single train would produce
        dozens of rows and dominate the calibration average.
        """
        written = 0
        for window in prediction.windows:
            for cause in window.causes:
                if self._already_recorded(session, crossing_id, cause.train_number,
                                          cause.pass_at):
                    continue
                horizon = int((cause.pass_at - prediction.generated_at).total_seconds())
                session.add(
                    PredictionRecord(
                        crossing_id=crossing_id,
                        train_number=cause.train_number,
                        train_class=cause.train_class.value,
                        direction=cause.direction.value,
                        speed_kmph=cause.speed_kmph,
                        provider=cause.provider,
                        predicted_at=prediction.generated_at,
                        predicted_pass_at=cause.pass_at,
                        predicted_close_at=window.close_at,
                        predicted_open_at=window.open_at,
                        horizon_seconds=max(0, horizon),
                        confidence=window.confidence,
                    )
                )
                written += 1
        return written

    def _already_recorded(
        self, session: Session, crossing_id: int, train_number: str, pass_at: datetime
    ) -> bool:
        existing = session.scalar(
            select(func.count(PredictionRecord.id)).where(
                PredictionRecord.crossing_id == crossing_id,
                PredictionRecord.train_number == train_number,
                PredictionRecord.predicted_pass_at >= pass_at - MATCH_TOLERANCE,
                PredictionRecord.predicted_pass_at <= pass_at + MATCH_TOLERANCE,
            )
        )
        return bool(existing)

    def derive_observations(
        self,
        session: Session,
        crossing: CrossingRef,
        sightings: list[TrainSighting],
    ) -> int:
        """Extract ground truth from provider *actual* times.

        When a train has recorded actual departures/arrivals at both bracketing
        stations, it has demonstrably traversed our segment, and interpolating
        between the two actuals gives an observed pass time. This is free,
        automatic supervision — no user input required.
        """
        created = 0
        for sighting in sightings:
            observed = self._observed_pass_time(crossing, sighting)
            if observed is None:
                continue
            if self._observation_exists(session, crossing.id, sighting.train_number, observed):
                continue
            session.add(
                Observation(
                    crossing_id=crossing.id,
                    train_number=sighting.train_number,
                    train_class=sighting.train_class.value,
                    source=ObservationSource.PROVIDER_ACTUALS.value,
                    observed_pass_at=observed,
                    detail={"provider": sighting.provider},
                )
            )
            created += 1
        return created

    def _observed_pass_time(
        self, crossing: CrossingRef, sighting: TrainSighting
    ) -> datetime | None:
        stops = {s.station_code: s for s in sighting.route}
        prev = stops.get(crossing.prev_station_code)
        nxt = stops.get(crossing.next_station_code)
        if prev is None or nxt is None:
            return None
        if not (prev.has_actuals and nxt.has_actuals):
            return None

        forward = prev.sequence < nxt.sequence
        first, second = (prev, nxt) if forward else (nxt, prev)
        t_first = first.actual_departure or first.actual_arrival
        t_second = second.actual_arrival or second.actual_departure
        if t_first is None or t_second is None or t_second <= t_first:
            return None

        offset = (
            crossing.distance_from_prev_km if forward else crossing.distance_from_next_km
        )
        total = crossing.segment_length_km or 1.0
        fraction = clamp(offset / total, 0.0, 1.0)
        return t_first + (t_second - t_first) * fraction

    def _observation_exists(
        self, session: Session, crossing_id: int, train_number: str, at: datetime
    ) -> bool:
        return bool(
            session.scalar(
                select(func.count(Observation.id)).where(
                    Observation.crossing_id == crossing_id,
                    Observation.train_number == train_number,
                    Observation.observed_pass_at >= at - MATCH_TOLERANCE,
                    Observation.observed_pass_at <= at + MATCH_TOLERANCE,
                )
            )
        )

    def record_user_report(
        self,
        session: Session,
        crossing_id: int,
        state: str,
        reported_at: datetime,
        *,
        client_hash: str | None = None,
        note: str | None = None,
    ) -> GateReport:
        """A person at the gate is the highest-quality sensor we have."""
        report = GateReport(
            crossing_id=crossing_id,
            state=state,
            reported_at=reported_at,
            client_hash=client_hash,
            note=note,
        )
        session.add(report)
        session.flush()
        session.add(
            Observation(
                crossing_id=crossing_id,
                train_number=None,
                source=ObservationSource.USER_REPORT.value,
                observed_close_at=reported_at if state == "closed" else None,
                observed_open_at=reported_at if state == "open" else None,
                detail={"report_id": report.id},
            )
        )
        return report

    # ------------------------------------------------------------- grading

    def grade_pending(
        self, session: Session, crossing_id: int, now: datetime, *, limit: int = 200
    ) -> int:
        """Match ungraded predictions to observations and update calibration."""
        pending = list(
            session.scalars(
                select(PredictionRecord)
                .where(
                    PredictionRecord.crossing_id == crossing_id,
                    PredictionRecord.graded.is_(False),
                    # Only grade events that are safely in the past.
                    PredictionRecord.predicted_pass_at < now - timedelta(minutes=5),
                )
                .order_by(PredictionRecord.predicted_pass_at)
                .limit(limit)
            )
        )
        graded = 0
        for record in pending:
            observation = self._find_observation(session, record)
            if observation is None:
                # Give it one tolerance window to arrive, then give up so the
                # queue cannot grow without bound.
                if record.predicted_pass_at < now - MATCH_TOLERANCE * 2:
                    record.graded = True
                continue
            self._apply(session, record, observation)
            graded += 1
        if graded:
            logger.info("graded %d prediction(s) for crossing %s", graded, crossing_id)
        return graded

    def _find_observation(
        self, session: Session, record: PredictionRecord
    ) -> Observation | None:
        stmt = select(Observation).where(
            Observation.crossing_id == record.crossing_id,
            Observation.observed_pass_at.is_not(None),
            Observation.observed_pass_at >= record.predicted_pass_at - MATCH_TOLERANCE,
            Observation.observed_pass_at <= record.predicted_pass_at + MATCH_TOLERANCE,
        )
        if record.train_number:
            stmt = stmt.where(Observation.train_number == record.train_number)
        return session.scalars(stmt.limit(1)).first()

    def _apply(self, session: Session, record: PredictionRecord, obs: Observation) -> None:
        record.graded = True
        record.observation_id = obs.id
        if obs.observed_pass_at is not None:
            error = (obs.observed_pass_at - record.predicted_pass_at).total_seconds()
            if abs(error) > MAX_PLAUSIBLE_ERROR_SECONDS:
                logger.warning(
                    "discarding implausible residual %.0fs for train %s",
                    error, record.train_number,
                )
                return
            record.pass_error_seconds = error
            PREDICTION_ERROR.labels(str(record.crossing_id), "pass").observe(error)
        if obs.observed_close_at is not None:
            record.close_error_seconds = (
                obs.observed_close_at - record.predicted_close_at
            ).total_seconds()
            PREDICTION_ERROR.labels(str(record.crossing_id), "close").observe(
                record.close_error_seconds
            )
        if obs.observed_open_at is not None:
            record.open_error_seconds = (
                obs.observed_open_at - record.predicted_open_at
            ).total_seconds()
            PREDICTION_ERROR.labels(str(record.crossing_id), "open").observe(
                record.open_error_seconds
            )

        for key in (record.train_class, DEFAULT_KEY):
            self._update_profile(session, record.crossing_id, key, record)

    def _update_profile(
        self, session: Session, crossing_id: int, train_class: str, record: PredictionRecord
    ) -> None:
        profile = session.scalars(
            select(CalibrationProfile).where(
                CalibrationProfile.crossing_id == crossing_id,
                CalibrationProfile.train_class == train_class,
            )
        ).first()
        if profile is None:
            profile = CalibrationProfile(crossing_id=crossing_id, train_class=train_class)
            session.add(profile)
            session.flush()

        alpha = self._alpha(profile.sample_count)
        if record.pass_error_seconds is not None:
            profile.pass_offset_seconds = _ewma(
                profile.pass_offset_seconds, record.pass_error_seconds, alpha
            )
            profile.pass_mae_seconds = _ewma(
                profile.pass_mae_seconds, abs(record.pass_error_seconds), alpha
            )
        if record.close_error_seconds is not None:
            profile.close_offset_seconds = _ewma(
                profile.close_offset_seconds, record.close_error_seconds, alpha
            )
        if record.open_error_seconds is not None:
            profile.open_offset_seconds = _ewma(
                profile.open_offset_seconds, record.open_error_seconds, alpha
            )
        profile.sample_count += 1
        profile.last_sample_at = record.predicted_pass_at

    def _alpha(self, sample_count: int) -> float:
        """Behaves like a running mean while young, then settles into an EWMA
        so the model keeps tracking drift instead of freezing."""
        return clamp(
            2.0 / (min(sample_count, self.maturity_samples) + 1),
            self.min_alpha,
            self.max_alpha,
        )

    # ------------------------------------------------------------- reading

    def load_calibration(self, session: Session, crossing_id: int) -> CalibrationSet:
        profiles = session.scalars(
            select(CalibrationProfile).where(CalibrationProfile.crossing_id == crossing_id)
        )
        return CalibrationSet(
            by_class={
                p.train_class: Calibration(
                    pass_offset_seconds=p.pass_offset_seconds,
                    close_offset_seconds=p.close_offset_seconds,
                    open_offset_seconds=p.open_offset_seconds,
                    pass_mae_seconds=p.pass_mae_seconds,
                    sample_count=p.sample_count,
                )
                for p in profiles
            }
        )

    def accuracy_summary(
        self, session: Session, crossing_id: int, now: datetime, *, days: int = 14
    ) -> dict[str, object]:
        """Human-readable "is this thing actually working?" report.

        ``now`` is injected rather than read, so this is reproducible and can be
        run against a historical window.
        """
        since = now - timedelta(days=days)
        rows = list(
            session.scalars(
                select(PredictionRecord).where(
                    PredictionRecord.crossing_id == crossing_id,
                    PredictionRecord.graded.is_(True),
                    PredictionRecord.pass_error_seconds.is_not(None),
                    PredictionRecord.predicted_at >= since,
                )
            )
        )
        errors = [r.pass_error_seconds for r in rows if r.pass_error_seconds is not None]
        if not errors:
            return {"samples": 0, "days": days}
        errors.sort()
        abs_errors = sorted(abs(e) for e in errors)
        return {
            "samples": len(errors),
            "days": days,
            "bias_seconds": round(sum(errors) / len(errors), 1),
            "mae_seconds": round(sum(abs_errors) / len(abs_errors), 1),
            "p50_abs_seconds": round(abs_errors[len(abs_errors) // 2], 1),
            "p90_abs_seconds": round(abs_errors[int(len(abs_errors) * 0.9)], 1),
            "within_2min_pct": round(
                100 * sum(1 for e in abs_errors if e <= 120) / len(abs_errors), 1
            ),
        }

    def freight_risk(self, session: Session, crossing_id: int, now: datetime) -> float:
        """Share of recent closures at this hour that no known train explained.

        Surfaced as a risk band, never as a countdown — we will not invent a
        train we cannot see.
        """
        hour = to_ist(now).hour
        since = now - timedelta(days=30)
        rows = list(
            session.scalars(
                select(Observation).where(
                    Observation.crossing_id == crossing_id,
                    Observation.created_at >= since,
                )
            )
        )
        same_hour = [o for o in rows if to_ist(o.created_at).hour == hour]
        if len(same_hour) < 5:
            return 0.0
        unexplained = sum(1 for o in same_hour if o.is_unexplained)
        return round(unexplained / len(same_hour), 3)


def _ewma(previous: float, sample: float, alpha: float) -> float:
    return (1 - alpha) * previous + alpha * sample
