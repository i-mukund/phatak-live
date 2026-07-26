"""Crossing resources."""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import ApiModel


class StationRef(ApiModel):
    code: str
    name: str | None = None


class CrossingSummary(ApiModel):
    slug: str
    name: str
    city: str | None = None
    state: str | None = None
    latitude: float
    longitude: float
    line_name: str | None = None
    #: Human labels for the two directions of travel, derived from the
    #: bracketing stations. Keeps the UI free of per-crossing special cases.
    up_towards: str | None = None
    down_towards: str | None = None


class CrossingDetail(CrossingSummary):
    previous_station: StationRef
    next_station: StationRef
    distance_from_prev_km: float
    distance_from_next_km: float
    track_count: int
    approach_distance_km: float
    reopen_lag_seconds: int
    min_gate_cycle_seconds: int
    notes: str | None = None


class CrossingCreate(ApiModel):
    """Adding a crossing is pure configuration — no code change (scaling §9)."""

    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    prev_station_code: str = Field(min_length=1, max_length=10)
    next_station_code: str = Field(min_length=1, max_length=10)
    distance_from_prev_km: float = Field(gt=0, le=50)
    distance_from_next_km: float = Field(gt=0, le=50)
    city: str | None = None
    state: str | None = None
    line_name: str | None = None
    prev_station_name: str | None = None
    next_station_name: str | None = None
    track_count: int = Field(default=2, ge=1, le=8)
    approach_distance_km: float = Field(default=2.5, gt=0, le=20)
    reopen_lag_seconds: int = Field(default=75, ge=0, le=900)
    min_gate_cycle_seconds: int = Field(default=210, ge=0, le=1800)
    notes: str | None = None
