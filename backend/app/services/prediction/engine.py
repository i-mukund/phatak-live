"""The prediction engine.

Pure function of ``(now, crossing, sightings, calibration)`` — no I/O, no
ambient clock, no globals (ADR 0002). Everything the product claims is derived
here, so this module is the one that must be obviously correct.

Pipeline
--------
1. Drop stale and non-actionable sightings.
2. Resolve each sighting into a :class:`CrossingTransit` (geometry.py).
3. Convert each transit into a raw closure window using a *physical* gate model.
4. Merge windows that are closer together than the gate can realistically cycle.
5. Derive the gate state and the headline confidence.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.core.geo import clamp
from app.core.logging import get_logger
from app.domain import TRAIN_LENGTH_M, CrossingRef, TrainSighting
from app.services.prediction.calibration import CalibrationSet
from app.services.prediction.confidence import combine, score_transit
from app.services.prediction.geometry import resolve_transit
from app.services.prediction.model import (
    ClosureWindow,
    ConfidenceBreakdown,
    CrossingTransit,
    GateState,
    Prediction,
    TrainCause,
)

logger = get_logger(__name__)


class PredictionEngine:
    def __init__(
        self,
        *,
        blend_horizon_km: float = 12.0,
        default_speed_kmph: float = 50.0,
        max_sighting_age_seconds: int = 900,
        horizon_minutes: int = 120,
        closing_soon_seconds: int = 300,
    ) -> None:
        self.blend_horizon_km = blend_horizon_km
        self.default_speed_kmph = default_speed_kmph
        self.max_sighting_age_seconds = max_sighting_age_seconds
        self.horizon_minutes = horizon_minutes
        self.closing_soon_seconds = closing_soon_seconds

    # ------------------------------------------------------------------ API

    def predict(
        self,
        *,
        crossing: CrossingRef,
        sightings: list[TrainSighting],
        now: datetime,
        calibration: CalibrationSet | None = None,
        degraded: bool = False,
        providers_used: tuple[str, ...] = (),
    ) -> Prediction:
        calibration = calibration or CalibrationSet.empty()
        notes: list[str] = []

        fresh = self._drop_stale(sightings, now, notes)
        transits = self._resolve(crossing, fresh, now)
        horizon_end = now + timedelta(minutes=self.horizon_minutes)

        windows: list[ClosureWindow] = []
        for transit in transits:
            window = self._window_for(crossing, transit, now, calibration, degraded)
            if window is None:
                continue
            if window.open_at <= now - timedelta(minutes=5) or window.close_at > horizon_end:
                continue
            windows.append(window)

        merged = merge_windows(windows, crossing.min_gate_cycle_seconds)
        state = self._state(merged, now)
        confidence = self._headline_confidence(merged, state, degraded, notes)

        if not merged:
            notes.append("No train is expected at this crossing within the prediction horizon.")

        return Prediction(
            crossing_slug=crossing.slug,
            generated_at=now,
            state=state,
            windows=tuple(merged),
            confidence=confidence,
            transits=tuple(transits),
            degraded=degraded,
            providers_used=providers_used,
            notes=tuple(notes),
        )

    # -------------------------------------------------------------- stages

    def _drop_stale(
        self, sightings: list[TrainSighting], now: datetime, notes: list[str]
    ) -> list[TrainSighting]:
        fresh: list[TrainSighting] = []
        stale = 0
        for sighting in sightings:
            if not sighting.is_actionable:
                continue
            age = (now - sighting.observed_at).total_seconds()
            if age > self.max_sighting_age_seconds:
                stale += 1
                continue
            fresh.append(sighting)
        if stale:
            notes.append(f"Ignored {stale} stale train update(s).")
        return fresh

    def _resolve(
        self, crossing: CrossingRef, sightings: list[TrainSighting], now: datetime
    ) -> list[CrossingTransit]:
        transits: list[CrossingTransit] = []
        for sighting in sightings:
            transit = resolve_transit(
                crossing,
                sighting,
                now,
                blend_horizon_km=self.blend_horizon_km,
                default_speed_kmph=self.default_speed_kmph,
            )
            if transit is not None:
                transits.append(transit)
        return sorted(transits, key=lambda t: t.pass_at)

    def _window_for(
        self,
        crossing: CrossingRef,
        transit: CrossingTransit,
        now: datetime,
        calibration: CalibrationSet,
        degraded: bool,
    ) -> ClosureWindow | None:
        cal = calibration.for_class(transit.train_class)
        pass_at = transit.pass_at + timedelta(seconds=cal.pass_offset_seconds)

        lead = gate_close_lead_seconds(
            approach_distance_km=crossing.approach_distance_km,
            speed_kmph=transit.speed_kmph,
            minimum=crossing.min_close_lead_seconds,
            maximum=crossing.max_close_lead_seconds,
        )
        clear = gate_clear_seconds(
            train_length_m=TRAIN_LENGTH_M.get(transit.train_class, 500.0),
            speed_kmph=transit.speed_kmph,
            operator_lag_seconds=crossing.reopen_lag_seconds,
        )

        close_at = pass_at - timedelta(seconds=lead) + timedelta(seconds=cal.close_offset_seconds)
        open_at = pass_at + timedelta(seconds=clear) + timedelta(seconds=cal.open_offset_seconds)
        if open_at <= close_at:  # calibration can never invert a window
            open_at = close_at + timedelta(seconds=30)

        breakdown = score_transit(
            transit,
            now=now,
            max_age_seconds=self.max_sighting_age_seconds,
            horizon_seconds=self.horizon_minutes * 60,
            calibration=cal,
            degraded=degraded,
        )
        cause = TrainCause(
            train_number=transit.train_number,
            train_name=transit.train_name,
            train_class=transit.train_class,
            direction=transit.direction,
            pass_at=pass_at,
            speed_kmph=round(transit.speed_kmph, 1),
            delay_minutes=transit.delay_minutes,
            provider=transit.provider,
            estimator=transit.estimator,
        )
        return ClosureWindow(
            close_at=close_at,
            open_at=open_at,
            confidence=breakdown.score,
            causes=(cause,),
        )

    def _state(self, windows: list[ClosureWindow], now: datetime) -> GateState:
        for window in windows:
            if window.contains(now):
                return GateState.CLOSED
        upcoming = next((w for w in windows if w.close_at > now), None)
        if upcoming and (upcoming.close_at - now).total_seconds() <= self.closing_soon_seconds:
            return GateState.CLOSING_SOON
        return GateState.OPEN

    def _headline_confidence(
        self,
        windows: list[ClosureWindow],
        state: GateState,
        degraded: bool,
        notes: list[str],
    ) -> ConfidenceBreakdown:
        relevant = list(windows[:2])
        if not relevant:
            # "The gate is open and nothing is coming" is itself a claim, and
            # it is only as good as our coverage of freight and unknown trains.
            score = 0.55 if degraded else 0.7
            return ConfidenceBreakdown(
                score=score,
                factors={"coverage": score},
                notes=("No trains detected; freight movements are not visible to any public "
                       "data source.",),
            )
        return combine(
            [
                ConfidenceBreakdown(score=w.confidence, factors={}, notes=())
                for w in relevant
            ]
        )


# ------------------------------------------------------------ gate physics


def gate_close_lead_seconds(
    *, approach_distance_km: float, speed_kmph: float, minimum: int, maximum: int
) -> float:
    """Seconds between the gate closing and the train reaching it.

    The gate is ordered shut when the train passes a fixed *distance* from the
    crossing, so the lead *time* is inversely proportional to speed. Modelling
    it this way (instead of "5 minutes") is why a 95 km/h Shatabdi and a
    40 km/h goods train produce different, and correct, windows.
    """
    speed = max(speed_kmph, 1.0)
    return clamp((approach_distance_km / speed) * 3600.0, float(minimum), float(maximum))


def gate_clear_seconds(
    *, train_length_m: float, speed_kmph: float, operator_lag_seconds: float
) -> float:
    """Seconds from the locomotive reaching the gate until the gate reopens."""
    speed = max(speed_kmph, 1.0)
    traverse = (train_length_m / 1000.0) / speed * 3600.0
    return traverse + operator_lag_seconds


def merge_windows(windows: list[ClosureWindow], min_gate_cycle_seconds: int) -> list[ClosureWindow]:
    """Collapse overlapping or near-adjacent closures into single windows.

    Domain logic, not presentation: a gate that would reopen for less than
    ``min_gate_cycle_seconds`` is not reopened by the operator at all.
    """
    if not windows:
        return []
    ordered = sorted(windows, key=lambda w: w.close_at)
    merged = [ordered[0]]
    for window in ordered[1:]:
        current = merged[-1]
        gap = (window.close_at - current.open_at).total_seconds()
        if gap <= min_gate_cycle_seconds:
            merged[-1] = current.merged_with(window)
        else:
            merged.append(window)
    return merged
