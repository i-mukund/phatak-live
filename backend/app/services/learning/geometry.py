"""Autonomous geometry calibration.

The troubleshooting guide tells a human how to spot a wrong chainage: the
prediction bias is *directional*. This module is that page of the guide,
automated.

The physics
-----------
The crossing's pass time is interpolated at fraction ``d / L`` of the segment
(``d`` = surveyed distance from the previous station, ``L`` = segment length).
If the true distance is ``d* > d``:

* **UP trains** (prev → next) reach the real crossing *later* than predicted →
  positive pass error.
* **DOWN trains** (next → prev) reach it *earlier* → negative pass error.

A plain timing bias (wrong dwell assumptions, provider lag) shifts both
directions the **same** way. Opposite-signed, speed-consistent biases are the
fingerprint of a geometry error, and each direction independently estimates the
same correction::

    delta_km ≈  bias_up_seconds  × v_up  / 3600
    delta_km ≈ −bias_down_seconds × v_down / 3600

When both estimates agree in sign, the calibrator applies their mean — clamped,
rate-limited, and audited — by moving the crossing along the segment while
keeping the segment length fixed. The EWMA pass offsets that had been absorbing
the bias are then decayed so the correction is not applied twice.

Safety properties, in order of importance:

1. **Never adjusts on a same-signed bias** — that is timing, not geometry.
2. **Bounded step** (``max_step_km``) and **cooldown** between adjustments, so a
   burst of bad data cannot walk the crossing off the map.
3. **Median, not mean**, so one absurd residual cannot fake a signature.
4. **Every change is written to ``geometry_adjustments``** with its evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.geo import clamp
from app.core.logging import get_logger
from app.db.models import (
    CalibrationProfile,
    Crossing,
    GeometryAdjustment,
    PredictionRecord,
)
from app.domain import Direction

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class GeometryReview:
    """Outcome of one review pass, whether or not anything changed."""

    crossing_slug: str
    adjusted: bool
    delta_km: float = 0.0
    reason: str = ""
    bias_up_seconds: float | None = None
    bias_down_seconds: float | None = None
    samples_up: int = 0
    samples_down: int = 0


class GeometryCalibrator:
    def __init__(
        self,
        *,
        window_days: int = 14,
        min_samples_per_direction: int = 12,
        min_bias_seconds: float = 45.0,
        min_delta_km: float = 0.1,
        max_step_km: float = 0.35,
        cooldown_days: int = 3,
        default_speed_kmph: float = 55.0,
        edge_margin_km: float = 0.2,
        offset_decay: float = 0.25,
    ) -> None:
        self.window_days = window_days
        self.min_samples_per_direction = min_samples_per_direction
        self.min_bias_seconds = min_bias_seconds
        self.min_delta_km = min_delta_km
        self.max_step_km = max_step_km
        self.cooldown_days = cooldown_days
        self.default_speed_kmph = default_speed_kmph
        self.edge_margin_km = edge_margin_km
        self.offset_decay = offset_decay

    # ------------------------------------------------------------------ API

    def review(self, session: Session, crossing: Crossing, now: datetime) -> GeometryReview:
        slug = crossing.slug

        last = self._last_adjustment(session, crossing.id)
        if last is not None and now - last.applied_at < timedelta(days=self.cooldown_days):
            return GeometryReview(slug, False, reason="cooldown")

        since = now - timedelta(days=self.window_days)
        if last is not None:
            # Only evidence gathered *after* the previous correction counts;
            # older residuals describe the geometry we already fixed.
            since = max(since, last.applied_at)

        up, down = self._residuals(session, crossing.id, since)
        if len(up) < self.min_samples_per_direction or len(down) < self.min_samples_per_direction:
            return GeometryReview(
                slug, False, reason="insufficient samples",
                samples_up=len(up), samples_down=len(down),
            )

        bias_up = median(e for e, _ in up)
        bias_down = median(e for e, _ in down)

        if abs(bias_up) < self.min_bias_seconds or abs(bias_down) < self.min_bias_seconds:
            return self._no_change(slug, "bias below threshold", bias_up, bias_down, up, down)
        if bias_up * bias_down > 0:
            # Same sign in both directions: a timing bias. The EWMA offsets
            # already handle it, and moving the crossing would be wrong.
            return self._no_change(slug, "same-signed bias (timing, not geometry)",
                                   bias_up, bias_down, up, down)

        v_up = self._speed(up)
        v_down = self._speed(down)
        delta_from_up = bias_up * v_up / 3600.0
        delta_from_down = -bias_down * v_down / 3600.0
        if delta_from_up * delta_from_down <= 0:
            return self._no_change(slug, "direction estimates disagree",
                                   bias_up, bias_down, up, down)

        delta = clamp(
            (delta_from_up + delta_from_down) / 2.0, -self.max_step_km, self.max_step_km
        )
        if abs(delta) < self.min_delta_km:
            return self._no_change(slug, "estimated correction too small",
                                   bias_up, bias_down, up, down)

        self._apply(session, crossing, delta, now, bias_up, bias_down, up, down, v_up, v_down)
        return GeometryReview(
            slug, True, delta_km=round(delta, 3), reason="applied",
            bias_up_seconds=round(bias_up, 1), bias_down_seconds=round(bias_down, 1),
            samples_up=len(up), samples_down=len(down),
        )

    def history(self, session: Session, crossing_id: int) -> list[GeometryAdjustment]:
        return list(
            session.scalars(
                select(GeometryAdjustment)
                .where(GeometryAdjustment.crossing_id == crossing_id)
                .order_by(GeometryAdjustment.applied_at.desc())
            )
        )

    # ------------------------------------------------------------- internals

    def _last_adjustment(
        self, session: Session, crossing_id: int
    ) -> GeometryAdjustment | None:
        return session.scalars(
            select(GeometryAdjustment)
            .where(GeometryAdjustment.crossing_id == crossing_id)
            .order_by(GeometryAdjustment.applied_at.desc())
            .limit(1)
        ).first()

    def _residuals(
        self, session: Session, crossing_id: int, since: datetime
    ) -> tuple[list[tuple[float, float | None]], list[tuple[float, float | None]]]:
        rows = session.execute(
            select(
                PredictionRecord.pass_error_seconds,
                PredictionRecord.speed_kmph,
                PredictionRecord.direction,
            ).where(
                PredictionRecord.crossing_id == crossing_id,
                PredictionRecord.graded.is_(True),
                PredictionRecord.pass_error_seconds.is_not(None),
                PredictionRecord.predicted_at >= since,
            )
        ).all()
        up = [(e, v) for e, v, d in rows if d == Direction.UP.value]
        down = [(e, v) for e, v, d in rows if d == Direction.DOWN.value]
        return up, down

    def _speed(self, residuals: list[tuple[float, float | None]]) -> float:
        speeds = [v for _, v in residuals if v and v > 0]
        return median(speeds) if speeds else self.default_speed_kmph

    def _apply(
        self,
        session: Session,
        crossing: Crossing,
        delta: float,
        now: datetime,
        bias_up: float,
        bias_down: float,
        up: list,
        down: list,
        v_up: float,
        v_down: float,
    ) -> None:
        length = crossing.segment_length_km
        old_prev = crossing.distance_from_prev_km
        new_prev = clamp(
            old_prev + delta, self.edge_margin_km, length - self.edge_margin_km
        )
        crossing.distance_from_prev_km = round(new_prev, 3)
        crossing.distance_from_next_km = round(length - new_prev, 3)

        session.add(
            GeometryAdjustment(
                crossing_id=crossing.id,
                applied_at=now,
                delta_km=round(new_prev - old_prev, 3),
                old_distance_from_prev_km=round(old_prev, 3),
                new_distance_from_prev_km=round(new_prev, 3),
                evidence={
                    "bias_up_seconds": round(bias_up, 1),
                    "bias_down_seconds": round(bias_down, 1),
                    "samples_up": len(up),
                    "samples_down": len(down),
                    "speed_up_kmph": round(v_up, 1),
                    "speed_down_kmph": round(v_down, 1),
                },
                note="Automatic correction from opposite-signed directional pass bias.",
            )
        )

        # The EWMA pass offsets were absorbing this bias; leave them intact and
        # the correction is applied twice. Decay rather than zero them, because
        # they also carry genuine (non-geometric) timing bias.
        for profile in session.scalars(
            select(CalibrationProfile).where(CalibrationProfile.crossing_id == crossing.id)
        ):
            profile.pass_offset_seconds *= self.offset_decay

        logger.warning(
            "geometry auto-correction on '%s': distance_from_prev %.3f -> %.3f km "
            "(bias up %+.0fs / down %+.0fs over %d+%d samples)",
            crossing.slug, old_prev, new_prev, bias_up, bias_down, len(up), len(down),
        )

    def _no_change(
        self, slug: str, reason: str, bias_up: float, bias_down: float,
        up: list, down: list,
    ) -> GeometryReview:
        return GeometryReview(
            slug, False, reason=reason,
            bias_up_seconds=round(bias_up, 1), bias_down_seconds=round(bias_down, 1),
            samples_up=len(up), samples_down=len(down),
        )
