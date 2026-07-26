"""Value objects produced by the prediction engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from app.domain import Direction, TrainClass


class GateState(str, Enum):
    OPEN = "open"
    CLOSING_SOON = "closing_soon"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class Estimator(str, Enum):
    SCHEDULE = "schedule"
    KINEMATIC = "kinematic"
    BLEND = "blend"
    DIRECT = "direct"


@dataclass(frozen=True, slots=True)
class CrossingTransit:
    """One train's predicted traversal of one crossing."""

    train_number: str
    train_name: str
    train_class: TrainClass
    provider: str
    provider_trust: float
    direction: Direction
    pass_at: datetime
    speed_kmph: float
    estimator: Estimator
    observed_at: datetime
    delay_minutes: int = 0
    remaining_km: float | None = None
    is_actual_position: bool = False
    schedule_pass_at: datetime | None = None
    kinematic_pass_at: datetime | None = None

    @property
    def estimator_disagreement_seconds(self) -> float:
        """Spread between the two independent estimators — a free uncertainty
        signal. When physics and timetable agree, we are much more sure."""
        if self.schedule_pass_at is None or self.kinematic_pass_at is None:
            return 0.0
        return abs((self.schedule_pass_at - self.kinematic_pass_at).total_seconds())


@dataclass(frozen=True, slots=True)
class TrainCause:
    """A train's contribution to a closure window (what the UI shows)."""

    train_number: str
    train_name: str
    train_class: TrainClass
    direction: Direction
    pass_at: datetime
    speed_kmph: float
    delay_minutes: int
    provider: str
    estimator: Estimator


@dataclass(frozen=True, slots=True)
class ClosureWindow:
    """An interval during which the gate is expected to be shut.

    Adjacent train passages are merged into a single window: a gate that
    reopens for 40 seconds has not, in any way the user cares about, reopened.
    """

    close_at: datetime
    open_at: datetime
    confidence: float
    causes: tuple[TrainCause, ...] = ()

    @property
    def duration_seconds(self) -> float:
        return (self.open_at - self.close_at).total_seconds()

    def contains(self, moment: datetime) -> bool:
        return self.close_at <= moment < self.open_at

    def merged_with(self, other: ClosureWindow) -> ClosureWindow:
        return ClosureWindow(
            close_at=min(self.close_at, other.close_at),
            open_at=max(self.open_at, other.open_at),
            # A merged window is only as certain as its least certain cause.
            confidence=min(self.confidence, other.confidence),
            causes=tuple(
                sorted(self.causes + other.causes, key=lambda c: c.pass_at)
            ),
        )


@dataclass(frozen=True, slots=True)
class ConfidenceBreakdown:
    """Confidence with its factors exposed.

    We show the number to users, so we must be able to explain it — both to
    them and to ourselves at 3 a.m.
    """

    score: float
    factors: dict[str, float] = field(default_factory=dict)
    notes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Prediction:
    """Complete answer to "should I leave now?" for one crossing."""

    crossing_slug: str
    generated_at: datetime
    state: GateState
    windows: tuple[ClosureWindow, ...]
    confidence: ConfidenceBreakdown
    transits: tuple[CrossingTransit, ...] = ()
    degraded: bool = False
    providers_used: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def current_window(self) -> ClosureWindow | None:
        return next((w for w in self.windows if w.contains(self.generated_at)), None)

    @property
    def next_window(self) -> ClosureWindow | None:
        return next((w for w in self.windows if w.close_at > self.generated_at), None)

    @property
    def seconds_until_close(self) -> float | None:
        window = self.next_window
        if window is None:
            return None
        return (window.close_at - self.generated_at).total_seconds()

    @property
    def seconds_until_open(self) -> float | None:
        window = self.current_window
        if window is None:
            return None
        return (window.open_at - self.generated_at).total_seconds()

    def safe_to_leave(self, travel_seconds: float) -> bool:
        """Would someone leaving now, taking ``travel_seconds`` to arrive, get
        through? The literal product question."""
        arrival = self.generated_at + timedelta(seconds=travel_seconds)
        return not any(w.contains(arrival) for w in self.windows)
