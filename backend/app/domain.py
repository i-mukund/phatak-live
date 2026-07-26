"""Provider-neutral domain objects.

Everything downstream of the provider layer speaks *only* these types. They are
frozen dataclasses with no ORM, no HTTP and no framework imports, which is what
lets the prediction engine be a pure function (ADR 0002).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TrainClass(str, Enum):
    """Normalised train classes. Also the calibration key: a Rajdhani and a
    goods train produce very different gate behaviour at the same crossing."""

    RAJDHANI = "rajdhani"
    VANDE_BHARAT = "vande_bharat"
    SHATABDI = "shatabdi"
    SUPERFAST = "superfast"
    EXPRESS = "express"
    PASSENGER = "passenger"
    EMU = "emu"
    MEMU = "memu"
    FREIGHT = "freight"
    UNKNOWN = "unknown"


#: Nominal length (m) used to compute how long a train takes to clear the gate.
TRAIN_LENGTH_M: dict[TrainClass, float] = {
    TrainClass.RAJDHANI: 600.0,
    TrainClass.VANDE_BHARAT: 400.0,
    TrainClass.SHATABDI: 500.0,
    TrainClass.SUPERFAST: 600.0,
    TrainClass.EXPRESS: 600.0,
    TrainClass.PASSENGER: 500.0,
    TrainClass.EMU: 250.0,
    TrainClass.MEMU: 300.0,
    TrainClass.FREIGHT: 700.0,
    TrainClass.UNKNOWN: 500.0,
}

_CLASS_KEYWORDS: tuple[tuple[str, TrainClass], ...] = (
    ("vande", TrainClass.VANDE_BHARAT),
    ("rajdhani", TrainClass.RAJDHANI),
    ("shatabdi", TrainClass.SHATABDI),
    ("duronto", TrainClass.SUPERFAST),
    ("tejas", TrainClass.SUPERFAST),
    ("garib rath", TrainClass.SUPERFAST),
    ("humsafar", TrainClass.SUPERFAST),
    ("superfast", TrainClass.SUPERFAST),
    ("memu", TrainClass.MEMU),
    ("demu", TrainClass.MEMU),
    ("emu", TrainClass.EMU),
    ("local", TrainClass.EMU),
    ("suburban", TrainClass.EMU),
    ("goods", TrainClass.FREIGHT),
    ("freight", TrainClass.FREIGHT),
    ("express", TrainClass.EXPRESS),
    ("mail", TrainClass.EXPRESS),
    ("passenger", TrainClass.PASSENGER),
)


def classify_train(train_type: str | None, train_name: str | None = None) -> TrainClass:
    """Map free-text provider labels onto :class:`TrainClass`.

    Providers are inconsistent ("SF Express", "Superfast Express", "EMU/Local"),
    so we match on keywords over the type *and* the name, most specific first.
    """
    haystack = " ".join(p for p in (train_type, train_name) if p).lower()
    if not haystack:
        return TrainClass.UNKNOWN
    for keyword, cls in _CLASS_KEYWORDS:
        if keyword in haystack:
            return cls
    return TrainClass.UNKNOWN


class Direction(str, Enum):
    UP = "up"
    DOWN = "down"
    UNKNOWN = "unknown"


class RunStatus(str, Enum):
    RUNNING = "running"
    NOT_STARTED = "not-started"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    SCHEDULED = "scheduled"


@dataclass(frozen=True, slots=True)
class CrossingRef:
    """Immutable snapshot of a crossing, decoupled from the ORM."""

    id: int
    slug: str
    name: str
    latitude: float
    longitude: float
    prev_station_code: str
    next_station_code: str
    distance_from_prev_km: float
    distance_from_next_km: float
    approach_distance_km: float = 2.5
    min_close_lead_seconds: int = 120
    max_close_lead_seconds: int = 600
    reopen_lag_seconds: int = 75
    min_gate_cycle_seconds: int = 210
    track_count: int = 2
    prev_station_name: str | None = None
    next_station_name: str | None = None
    line_name: str | None = None

    @property
    def segment_length_km(self) -> float:
        return self.distance_from_prev_km + self.distance_from_next_km


@dataclass(frozen=True, slots=True)
class RouteStop:
    """One stop on a train's route, normalised across providers."""

    sequence: int
    station_code: str
    station_name: str | None = None
    distance_km: float = 0.0
    is_halt: bool = True
    scheduled_arrival: datetime | None = None
    scheduled_departure: datetime | None = None
    actual_arrival: datetime | None = None
    actual_departure: datetime | None = None
    status: str = "upcoming"
    speed_to_next_kmph: float | None = None
    latitude: float | None = None
    longitude: float | None = None

    @property
    def best_departure(self) -> datetime | None:
        return self.actual_departure or self.scheduled_departure

    @property
    def best_arrival(self) -> datetime | None:
        return self.actual_arrival or self.scheduled_arrival

    @property
    def has_actuals(self) -> bool:
        return self.actual_arrival is not None or self.actual_departure is not None


@dataclass(frozen=True, slots=True)
class LivePosition:
    station_code: str
    sequence: int
    segment_progress: float = 0.0
    speed_kmph: float | None = None
    is_actual: bool = False


@dataclass(frozen=True, slots=True)
class TrainSighting:
    """What a provider knows about one train, right now.

    Two evidence shapes are supported and both are optional:

    * ``route`` + ``position`` — rich live data (RailRadar-class provider).
    * ``direct_pass_estimate`` — a provider that already knows when the train
      reaches this crossing (our offline timetable provider).

    A sighting with neither is inert and is dropped by the engine.
    """

    train_number: str
    train_name: str
    provider: str
    provider_trust: float
    observed_at: datetime
    train_class: TrainClass = TrainClass.UNKNOWN
    train_type: str | None = None
    status: RunStatus = RunStatus.RUNNING
    delay_minutes: int = 0
    route: tuple[RouteStop, ...] = ()
    position: LivePosition | None = None
    direct_pass_estimate: datetime | None = None
    direct_speed_kmph: float | None = None
    direct_direction: Direction = Direction.UNKNOWN
    average_speed_kmph: float | None = None
    raw: dict = field(default_factory=dict, compare=False, repr=False)

    @property
    def is_actionable(self) -> bool:
        if self.status in (RunStatus.CANCELLED, RunStatus.COMPLETED):
            return False
        return bool(self.route) or self.direct_pass_estimate is not None


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    name: str
    healthy: bool
    detail: str = ""
    latency_ms: float | None = None
    circuit_state: str = "closed"
