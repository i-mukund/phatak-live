"""Turning a train sighting into a crossing transit.

This is the geometric heart of the product. Two independent estimators are
computed and blended (ARCHITECTURE.md §5.3):

* **schedule** — interpolate between the timings of the stops bracketing the
  crossing. Robust at long range; it already accounts for halts and delays.
* **kinematic** — remaining distance ÷ current speed. Sharp at short range;
  meaningless at long range because it assumes constant speed and no stops.

Blend weight rises as the train gets close, and is damped when the reported
position is interpolated rather than observed.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.core.geo import clamp, lerp
from app.domain import CrossingRef, Direction, RouteStop, TrainSighting
from app.services.prediction.model import CrossingTransit, Estimator

#: Never trust an implied speed outside this band; providers do emit zeroes
#: and absurd values, and a bad speed poisons the whole window.
MIN_SPEED_KMPH = 8.0
MAX_SPEED_KMPH = 180.0


def resolve_transit(
    crossing: CrossingRef,
    sighting: TrainSighting,
    now: datetime,
    *,
    blend_horizon_km: float = 12.0,
    default_speed_kmph: float = 50.0,
) -> CrossingTransit | None:
    """Return the transit, or ``None`` if this train cannot be placed."""
    geo = _locate_crossing(crossing, sighting)
    if geo is None:
        return _direct_transit(sighting, default_speed_kmph)

    direction, crossing_km, stops = geo
    schedule_at = _schedule_estimate(stops, crossing_km, sighting)
    current_km, speed_from_position, is_actual = _train_position(sighting, stops)

    remaining_km = None if current_km is None else crossing_km - current_km
    speed = _resolve_speed(
        sighting, stops, crossing_km, speed_from_position, default_speed_kmph
    )

    kinematic_at = None
    if remaining_km is not None and remaining_km > 0:
        kinematic_at = now + timedelta(hours=remaining_km / speed)

    pass_at, estimator = _blend(
        schedule_at, kinematic_at, remaining_km, blend_horizon_km, is_actual
    )
    if pass_at is None:
        return None

    return CrossingTransit(
        train_number=sighting.train_number,
        train_name=sighting.train_name,
        train_class=sighting.train_class,
        provider=sighting.provider,
        provider_trust=sighting.provider_trust,
        direction=direction,
        pass_at=pass_at,
        speed_kmph=speed,
        estimator=estimator,
        observed_at=sighting.observed_at,
        delay_minutes=sighting.delay_minutes,
        remaining_km=remaining_km,
        is_actual_position=is_actual,
        schedule_pass_at=schedule_at,
        kinematic_pass_at=kinematic_at,
    )


# --------------------------------------------------------------- placement


def _locate_crossing(
    crossing: CrossingRef, sighting: TrainSighting
) -> tuple[Direction, float, list[RouteStop]] | None:
    """Find the crossing's chainage on this train's route.

    Requires both bracketing stations to appear on the route; their order
    determines the direction of travel. Returns ``None`` for trains that never
    traverse our segment — a train on a different line is not our problem.
    """
    stops = sorted(sighting.route, key=lambda s: s.sequence)
    if len(stops) < 2:
        return None
    index = {s.station_code: i for i, s in enumerate(stops)}
    i_prev = index.get(crossing.prev_station_code)
    i_next = index.get(crossing.next_station_code)
    if i_prev is None or i_next is None or i_prev == i_next:
        return None

    forward = i_prev < i_next
    direction = Direction.UP if forward else Direction.DOWN
    a, b = (stops[i_prev], stops[i_next]) if forward else (stops[i_next], stops[i_prev])
    span_km = b.distance_km - a.distance_km
    if span_km <= 0:
        return None

    nominal = crossing.segment_length_km or span_km
    offset = crossing.distance_from_prev_km if forward else crossing.distance_from_next_km
    # Rescale our surveyed offset onto the provider's chainage so a small
    # disagreement in segment length does not shift the crossing off the track.
    crossing_km = a.distance_km + clamp(offset * (span_km / nominal), 0.0, span_km)
    return direction, crossing_km, stops


def _schedule_estimate(
    stops: list[RouteStop], crossing_km: float, sighting: TrainSighting
) -> datetime | None:
    """Interpolate a pass time from the timings of the bracketing stops."""
    before = _last_stop_before(stops, crossing_km)
    after = _first_stop_after(stops, crossing_km)
    if before is None or after is None:
        return None

    t_before = before.actual_departure or before.scheduled_departure or before.best_arrival
    t_after = after.best_arrival or after.best_departure
    if t_before is None or t_after is None or t_after <= t_before:
        return None

    span = after.distance_km - before.distance_km
    fraction = 0.5 if span <= 0 else (crossing_km - before.distance_km) / span
    seconds = (t_after - t_before).total_seconds()
    estimate = t_before + timedelta(seconds=lerp(0.0, seconds, fraction))

    # Only apply the reported delay when neither anchor is an *actual* time —
    # actuals already contain the delay, and double-counting it is a classic
    # 15-minute error.
    if not (before.has_actuals or after.has_actuals) and sighting.delay_minutes:
        estimate += timedelta(minutes=sighting.delay_minutes)
    return estimate


def _train_position(
    sighting: TrainSighting, stops: list[RouteStop]
) -> tuple[float | None, float | None, bool]:
    """Current chainage, live speed and whether the position was observed."""
    position = sighting.position
    if position is not None:
        idx = next(
            (i for i, s in enumerate(stops) if s.station_code == position.station_code), None
        )
        if idx is None and position.sequence:
            idx = next((i for i, s in enumerate(stops) if s.sequence == position.sequence), None)
        if idx is not None:
            here = stops[idx]
            nxt = stops[idx + 1] if idx + 1 < len(stops) else None
            span = (nxt.distance_km - here.distance_km) if nxt else 0.0
            chainage = here.distance_km + span * clamp(position.segment_progress, 0.0, 1.0)
            return chainage, position.speed_kmph, position.is_actual

    # No explicit position: the furthest stop with a recorded actual departure
    # is a reliable lower bound on where the train is.
    departed = [s for s in stops if s.actual_departure is not None]
    if departed:
        return max(departed, key=lambda s: s.distance_km).distance_km, None, False
    return None, None, False


def _resolve_speed(
    sighting: TrainSighting,
    stops: list[RouteStop],
    crossing_km: float,
    live_speed: float | None,
    default_speed: float,
) -> float:
    """Best available speed, clamped to a physically sane band."""
    candidates = (
        live_speed,
        sighting.direct_speed_kmph,
        _segment_speed(stops, crossing_km),
        sighting.average_speed_kmph,
        default_speed,
    )
    for candidate in candidates:
        if candidate and MIN_SPEED_KMPH <= candidate <= MAX_SPEED_KMPH:
            return float(candidate)
    return clamp(default_speed, MIN_SPEED_KMPH, MAX_SPEED_KMPH)


def _segment_speed(stops: list[RouteStop], crossing_km: float) -> float | None:
    before = _last_stop_before(stops, crossing_km)
    return before.speed_to_next_kmph if before else None


def _blend(
    schedule_at: datetime | None,
    kinematic_at: datetime | None,
    remaining_km: float | None,
    blend_horizon_km: float,
    is_actual: bool,
) -> tuple[datetime | None, Estimator]:
    if schedule_at is None and kinematic_at is None:
        return None, Estimator.SCHEDULE
    if kinematic_at is None:
        return schedule_at, Estimator.SCHEDULE
    if schedule_at is None:
        return kinematic_at, Estimator.KINEMATIC

    if remaining_km is None or blend_horizon_km <= 0:
        weight = 0.0
    else:
        weight = clamp(1.0 - (remaining_km / blend_horizon_km), 0.0, 1.0)
    if not is_actual:
        weight *= 0.4  # interpolated positions do not deserve full authority

    if weight <= 0.01:
        return schedule_at, Estimator.SCHEDULE
    if weight >= 0.99:
        return kinematic_at, Estimator.KINEMATIC

    delta = (kinematic_at - schedule_at).total_seconds() * weight
    return schedule_at + timedelta(seconds=delta), Estimator.BLEND


def _direct_transit(sighting: TrainSighting, default_speed: float) -> CrossingTransit | None:
    """Providers that already know the pass time (timetable, mock, generic)."""
    if sighting.direct_pass_estimate is None:
        return None
    speed = sighting.direct_speed_kmph or sighting.average_speed_kmph or default_speed
    return CrossingTransit(
        train_number=sighting.train_number,
        train_name=sighting.train_name,
        train_class=sighting.train_class,
        provider=sighting.provider,
        provider_trust=sighting.provider_trust,
        direction=sighting.direct_direction,
        pass_at=sighting.direct_pass_estimate + timedelta(minutes=sighting.delay_minutes),
        speed_kmph=clamp(speed, MIN_SPEED_KMPH, MAX_SPEED_KMPH),
        estimator=Estimator.DIRECT,
        observed_at=sighting.observed_at,
        delay_minutes=sighting.delay_minutes,
        schedule_pass_at=sighting.direct_pass_estimate,
    )


def _last_stop_before(stops: list[RouteStop], chainage: float) -> RouteStop | None:
    candidates = [s for s in stops if s.distance_km <= chainage]
    return max(candidates, key=lambda s: s.distance_km) if candidates else None


def _first_stop_after(stops: list[RouteStop], chainage: float) -> RouteStop | None:
    candidates = [s for s in stops if s.distance_km >= chainage]
    return min(candidates, key=lambda s: s.distance_km) if candidates else None
