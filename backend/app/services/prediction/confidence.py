"""Confidence scoring.

The number shown next to a countdown is a promise. We compute it from factors
we can name, combine them as a weighted geometric mean (so one terrible factor
cannot be averaged away by good ones), and never return 1.0 — we are predicting
the behaviour of a human gatekeeper reacting to a train we cannot see.
"""

from __future__ import annotations

from datetime import datetime

from app.core.geo import clamp
from app.services.prediction.calibration import Calibration
from app.services.prediction.model import ConfidenceBreakdown, CrossingTransit

CEILING = 0.97
FLOOR = 0.05

_WEIGHTS: dict[str, float] = {
    "provider_trust": 1.3,
    "freshness": 1.2,
    "horizon": 1.0,
    "position_quality": 0.9,
    "estimator_agreement": 0.8,
    "calibration": 0.7,
}


def score_transit(
    transit: CrossingTransit,
    *,
    now: datetime,
    max_age_seconds: float,
    horizon_seconds: float,
    calibration: Calibration,
    degraded: bool = False,
) -> ConfidenceBreakdown:
    age = max(0.0, (now - transit.observed_at).total_seconds())
    horizon = max(0.0, (transit.pass_at - now).total_seconds())

    factors: dict[str, float] = {
        "provider_trust": clamp(transit.provider_trust, 0.1, 1.0),
        "freshness": _freshness(age, max_age_seconds),
        "horizon": _horizon(horizon, horizon_seconds),
        "position_quality": _position_quality(transit),
        "estimator_agreement": _agreement(transit),
        "calibration": _calibration(calibration),
    }

    notes: list[str] = []
    score = _geometric_mean(factors)
    if degraded:
        score *= 0.75
        notes.append("Running on fallback data — no live provider responded.")
    if transit.delay_minutes >= 30:
        score *= 0.9
        notes.append(f"Train is {transit.delay_minutes} min late; timings drift when delayed.")
    if not transit.is_actual_position:
        notes.append("Position is interpolated, not GPS-observed.")

    return ConfidenceBreakdown(
        score=round(clamp(score, FLOOR, CEILING), 3),
        factors={k: round(v, 3) for k, v in factors.items()},
        notes=tuple(notes),
    )


def combine(scores: list[ConfidenceBreakdown]) -> ConfidenceBreakdown:
    """A merged window is only as trustworthy as its weakest contributor."""
    if not scores:
        return ConfidenceBreakdown(score=FLOOR, factors={}, notes=("No train data available.",))
    weakest = min(scores, key=lambda s: s.score)
    notes: list[str] = []
    for item in scores:
        for note in item.notes:
            if note not in notes:
                notes.append(note)
    return ConfidenceBreakdown(score=weakest.score, factors=weakest.factors, notes=tuple(notes))


# ---------------------------------------------------------------- factors


def _freshness(age_seconds: float, max_age_seconds: float) -> float:
    if max_age_seconds <= 0:
        return 0.5
    return clamp(1.0 - (age_seconds / max_age_seconds) ** 1.5, 0.15, 1.0)


def _horizon(horizon_seconds: float, max_horizon_seconds: float) -> float:
    """Full marks inside 10 minutes, decaying to ~0.5 at the horizon edge."""
    if horizon_seconds <= 600:
        return 1.0
    if max_horizon_seconds <= 600:
        return 0.6
    ratio = (horizon_seconds - 600) / (max_horizon_seconds - 600)
    return clamp(1.0 - 0.5 * ratio, 0.4, 1.0)


def _position_quality(transit: CrossingTransit) -> float:
    if transit.is_actual_position:
        return 1.0
    if transit.estimator.value == "direct":
        return 0.7  # timetable-only: no live evidence at all
    return 0.85


def _agreement(transit: CrossingTransit) -> float:
    spread = transit.estimator_disagreement_seconds
    if spread <= 0:
        return 0.95  # only one estimator available: not wrong, but unverified
    return clamp(1.0 - spread / 900.0, 0.4, 1.0)


def _calibration(calibration: Calibration) -> float:
    if calibration.sample_count <= 0:
        return 0.82  # uncalibrated but physically modelled
    maturity = clamp(calibration.sample_count / 25.0, 0.0, 1.0)
    base = 0.82 + 0.18 * maturity
    if calibration.pass_mae_seconds > 0:
        # A large residual error means our model is genuinely wrong here.
        base *= clamp(1.0 - calibration.pass_mae_seconds / 1200.0, 0.55, 1.0)
    return clamp(base, 0.4, 1.0)


def _geometric_mean(factors: dict[str, float]) -> float:
    total_weight = sum(_WEIGHTS.get(k, 1.0) for k in factors)
    if total_weight <= 0:
        return FLOOR
    acc = 0.0
    for key, value in factors.items():
        acc += _WEIGHTS.get(key, 1.0) * _log(clamp(value, 1e-3, 1.0))
    return _exp(acc / total_weight)


def _log(x: float) -> float:
    from math import log

    return log(x)


def _exp(x: float) -> float:
    from math import exp

    return exp(x)
