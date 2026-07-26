"""Seed data.

The target crossing plus an approximate timetable that powers the offline
fallback provider.

⚠️ **These numbers are configuration, not truth.** Chainages and pass times are
derived from public map/timetable data and must be field-verified. They are
deliberately kept in one file so they can be corrected without touching code —
and the learning engine will absorb residual bias in the meantime.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import Crossing, Direction, TimetableEntry

logger = get_logger(__name__)

SIRASPUR_SLUG = "siraspur"

#: (HH, MM, number, name, type, direction, speed kmph, run days)
_TIMETABLE: tuple[tuple[int, int, str, str, str, Direction, float, str], ...] = (
    (5, 12, "64901", "Delhi–Panipat EMU", "EMU", Direction.UP, 55.0, "1111111"),
    (6, 5, "54301", "Delhi–Kurukshetra Passenger", "Passenger", Direction.UP, 45.0, "1111111"),
    (6, 48, "12445", "Uttar Sampark Kranti Express", "Superfast Express",
     Direction.UP, 90.0, "1111111"),
    (7, 22, "64902", "Panipat–Delhi EMU", "EMU", Direction.DOWN, 55.0, "1111110"),
    (7, 55, "12011", "Kalka Shatabdi Express", "Shatabdi Express", Direction.UP, 95.0, "1111111"),
    (8, 40, "54302", "Kurukshetra–Delhi Passenger", "Passenger", Direction.DOWN, 45.0, "1111111"),
    (9, 30, "22447", "Delhi–Bathinda Superfast", "Superfast Express",
     Direction.UP, 85.0, "1010100"),
    (11, 15, "64903", "Delhi–Panipat EMU", "EMU", Direction.UP, 55.0, "1111111"),
    (13, 5, "12481", "Sri Ganganagar Express", "Superfast Express",
     Direction.UP, 82.0, "1111111"),
    (14, 40, "64904", "Panipat–Delhi EMU", "EMU", Direction.DOWN, 55.0, "1111111"),
    (16, 25, "12013", "Amritsar Shatabdi Express", "Shatabdi Express",
     Direction.UP, 95.0, "1111111"),
    (17, 50, "64905", "Delhi–Panipat EMU", "EMU", Direction.UP, 55.0, "1111111"),
    (18, 35, "12057", "Jan Shatabdi Express", "Superfast Express",
     Direction.DOWN, 88.0, "1111110"),
    (19, 40, "54303", "Delhi–Ambala Passenger", "Passenger", Direction.UP, 45.0, "1111111"),
    (21, 10, "12471", "Swaraj Express", "Superfast Express", Direction.UP, 88.0, "1101011"),
    (22, 30, "64906", "Panipat–Delhi EMU", "EMU", Direction.DOWN, 55.0, "1111111"),
)


def seed_siraspur(session: Session) -> Crossing:
    """Idempotent: safe to run on every boot."""
    existing = session.scalars(
        select(Crossing).where(Crossing.slug == SIRASPUR_SLUG)
    ).first()
    if existing is not None:
        return existing

    crossing = Crossing(
        slug=SIRASPUR_SLUG,
        name="Siraspur Railway Crossing",
        city="Delhi",
        state="Delhi",
        # Approximate — Siraspur Road, Kankar Khera village, North West Delhi 110042.
        latitude=28.75650,
        longitude=77.12730,
        line_name="Northern Railway — Delhi Jn ↔ Panipat / Ambala",
        prev_station_code="BHD",
        prev_station_name="Badli",
        next_station_code="KHKN",
        next_station_name="Khera Kalan",
        # Live RailRadar chainages (2026-07-26) put BHD -> KHKN at 3.3 km of
        # track; the crossing sits nearer Badli. Split pro-rata from the earlier
        # map estimate — the geometry calibrator refines it from graded data.
        distance_from_prev_km=1.2,
        distance_from_next_km=2.1,
        track_count=2,
        approach_distance_km=2.5,
        min_close_lead_seconds=120,
        max_close_lead_seconds=600,
        reopen_lag_seconds=75,
        min_gate_cycle_seconds=210,
        notes=(
            "Segment length (3.3 km) verified against live railway chainages; the "
            "crossing's position within it is an estimate the geometry calibrator "
            "refines from live data. "
            "Freight traffic on this corridor is not visible to any public data source."
        ),
    )
    session.add(crossing)
    session.flush()

    for hour, minute, number, name, ttype, direction, speed, run_days in _TIMETABLE:
        session.add(
            TimetableEntry(
                crossing_id=crossing.id,
                train_number=number,
                train_name=name,
                train_type=ttype,
                direction=direction.value,
                scheduled_pass_minute=hour * 60 + minute,
                run_days=run_days,
                typical_speed_kmph=speed,
            )
        )
    logger.info("seeded crossing '%s' with %d timetable entries",
                SIRASPUR_SLUG, len(_TIMETABLE))
    return crossing


def seed_if_empty(session: Session) -> None:
    if session.scalar(select(func.count(Crossing.id))) == 0:
        seed_siraspur(session)
