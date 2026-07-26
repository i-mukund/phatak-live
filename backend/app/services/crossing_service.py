"""Crossing CRUD and ORM ↔ domain translation."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError, ValidationError
from app.db.models import Crossing
from app.domain import CrossingRef
from app.schemas.crossing import CrossingCreate, CrossingDetail, CrossingSummary, StationRef


def to_ref(crossing: Crossing) -> CrossingRef:
    """ORM row → immutable domain snapshot consumed by providers and engine."""
    return CrossingRef(
        id=crossing.id,
        slug=crossing.slug,
        name=crossing.name,
        latitude=crossing.latitude,
        longitude=crossing.longitude,
        prev_station_code=crossing.prev_station_code,
        next_station_code=crossing.next_station_code,
        distance_from_prev_km=crossing.distance_from_prev_km,
        distance_from_next_km=crossing.distance_from_next_km,
        approach_distance_km=crossing.approach_distance_km,
        min_close_lead_seconds=crossing.min_close_lead_seconds,
        max_close_lead_seconds=crossing.max_close_lead_seconds,
        reopen_lag_seconds=crossing.reopen_lag_seconds,
        min_gate_cycle_seconds=crossing.min_gate_cycle_seconds,
        track_count=crossing.track_count,
        prev_station_name=crossing.prev_station_name,
        next_station_name=crossing.next_station_name,
        line_name=crossing.line_name,
    )


def to_summary(crossing: Crossing) -> CrossingSummary:
    return CrossingSummary(
        slug=crossing.slug,
        name=crossing.name,
        city=crossing.city,
        state=crossing.state,
        latitude=crossing.latitude,
        longitude=crossing.longitude,
        line_name=crossing.line_name,
        up_towards=crossing.next_station_name or crossing.next_station_code,
        down_towards=crossing.prev_station_name or crossing.prev_station_code,
    )


def to_detail(crossing: Crossing) -> CrossingDetail:
    return CrossingDetail(
        **to_summary(crossing).model_dump(),
        previous_station=StationRef(
            code=crossing.prev_station_code, name=crossing.prev_station_name
        ),
        next_station=StationRef(
            code=crossing.next_station_code, name=crossing.next_station_name
        ),
        distance_from_prev_km=crossing.distance_from_prev_km,
        distance_from_next_km=crossing.distance_from_next_km,
        track_count=crossing.track_count,
        approach_distance_km=crossing.approach_distance_km,
        reopen_lag_seconds=crossing.reopen_lag_seconds,
        min_gate_cycle_seconds=crossing.min_gate_cycle_seconds,
        notes=crossing.notes,
    )


class CrossingService:
    def list_active(self, session: Session) -> list[Crossing]:
        return list(
            session.scalars(
                select(Crossing).where(Crossing.is_active.is_(True)).order_by(Crossing.name)
            )
        )

    def get_by_slug(self, session: Session, slug: str) -> Crossing:
        crossing = session.scalars(select(Crossing).where(Crossing.slug == slug)).first()
        if crossing is None:
            raise NotFoundError(f"No crossing with slug '{slug}'")
        return crossing

    def create(self, session: Session, payload: CrossingCreate) -> Crossing:
        if session.scalars(select(Crossing).where(Crossing.slug == payload.slug)).first():
            raise ValidationError(f"Crossing '{payload.slug}' already exists")
        if payload.prev_station_code == payload.next_station_code:
            raise ValidationError("Bracketing stations must differ")
        crossing = Crossing(**payload.model_dump())
        session.add(crossing)
        session.flush()
        return crossing
