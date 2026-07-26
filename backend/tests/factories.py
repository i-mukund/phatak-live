"""Builders for domain objects. Keeps tests about behaviour, not construction."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.domain import (
    LivePosition,
    RouteStop,
    RunStatus,
    TrainClass,
    TrainSighting,
)


def route_sighting(
    *,
    now: datetime,
    number: str = "12011",
    name: str = "Kalka Shatabdi",
    train_class: TrainClass = TrainClass.SHATABDI,
    minutes_to_prev: float = 6.0,
    minutes_to_next: float = 14.0,
    prev_code: str = "BHD",
    next_code: str = "KHKN",
    prev_km: float = 20.0,
    next_km: float = 23.3,
    reverse: bool = False,
    delay_minutes: int = 0,
    with_position: bool = True,
    progress: float = 0.0,
    speed_kmph: float | None = 80.0,
    is_actual: bool = True,
    with_actuals: bool = False,
    provider: str = "test",
    trust: float = 0.9,
) -> TrainSighting:
    """A train approaching the crossing on a three-stop route."""
    t_prev = now + timedelta(minutes=minutes_to_prev)
    t_next = now + timedelta(minutes=minutes_to_next)
    first_code, second_code = (prev_code, next_code) if not reverse else (next_code, prev_code)

    origin = RouteStop(
        sequence=1,
        station_code="ORG",
        distance_km=0.0,
        scheduled_departure=now - timedelta(minutes=20),
        actual_departure=now - timedelta(minutes=20),
        status="departed",
        speed_to_next_kmph=speed_kmph,
    )
    a = RouteStop(
        sequence=2,
        station_code=first_code,
        distance_km=prev_km,
        scheduled_arrival=t_prev,
        scheduled_departure=t_prev,
        actual_departure=t_prev if with_actuals else None,
        actual_arrival=t_prev if with_actuals else None,
        status="upcoming",
        speed_to_next_kmph=speed_kmph,
    )
    b = RouteStop(
        sequence=3,
        station_code=second_code,
        distance_km=next_km,
        scheduled_arrival=t_next,
        scheduled_departure=t_next,
        actual_arrival=t_next if with_actuals else None,
        status="upcoming",
    )
    position = (
        LivePosition(
            station_code="ORG",
            sequence=1,
            segment_progress=progress,
            speed_kmph=speed_kmph,
            is_actual=is_actual,
        )
        if with_position
        else None
    )
    return TrainSighting(
        train_number=number,
        train_name=name,
        provider=provider,
        provider_trust=trust,
        observed_at=now,
        train_class=train_class,
        train_type=train_class.value,
        status=RunStatus.RUNNING,
        delay_minutes=delay_minutes,
        route=(origin, a, b),
        position=position,
        average_speed_kmph=speed_kmph,
    )


def direct_sighting(
    *,
    now: datetime,
    minutes_ahead: float,
    number: str = "64901",
    name: str = "Delhi-Panipat EMU",
    train_class: TrainClass = TrainClass.EMU,
    speed_kmph: float = 55.0,
    provider: str = "timetable",
    trust: float = 0.45,
    delay_minutes: int = 0,
) -> TrainSighting:
    return TrainSighting(
        train_number=number,
        train_name=name,
        provider=provider,
        provider_trust=trust,
        observed_at=now,
        train_class=train_class,
        train_type=train_class.value,
        status=RunStatus.SCHEDULED,
        delay_minutes=delay_minutes,
        direct_pass_estimate=now + timedelta(minutes=minutes_ahead),
        direct_speed_kmph=speed_kmph,
    )
