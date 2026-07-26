"""Persistence model.

Design notes
------------
* Enum-ish columns are plain ``str`` for cross-dialect portability; the Python
  enums in ``app.domain_enums`` are the real contract.
* Every timestamp is :class:`UtcDateTime` — tz-aware in, tz-aware out.
* Raw provider payloads are retained on sighting snapshots so a past prediction
  can be replayed byte-for-byte (ADR 0002).
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UtcDateTime


class Direction(str, enum.Enum):
    """Direction of travel relative to the crossing's canonical segment."""

    UP = "up"       # prev_station -> next_station
    DOWN = "down"   # next_station -> prev_station
    UNKNOWN = "unknown"


class GateState(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class WindowSource(str, enum.Enum):
    PREDICTED = "predicted"
    OBSERVED = "observed"
    RECONCILED = "reconciled"


class ObservationSource(str, enum.Enum):
    PROVIDER_ACTUALS = "provider_actuals"
    USER_REPORT = "user_report"
    OPERATOR = "operator"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Crossing(TimestampMixin, Base):
    """A level crossing ("phatak").

    The bracketing-station fields are what let us compute a pass time from
    per-station timings alone — see ARCHITECTURE.md §5.2.
    """

    __tablename__ = "crossings"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    city: Mapped[str | None] = mapped_column(String(80))
    state: Mapped[str | None] = mapped_column(String(80))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    # --- segment geometry -------------------------------------------------
    line_name: Mapped[str | None] = mapped_column(String(120))
    prev_station_code: Mapped[str] = mapped_column(String(10), index=True)
    prev_station_name: Mapped[str | None] = mapped_column(String(120))
    next_station_code: Mapped[str] = mapped_column(String(10), index=True)
    next_station_name: Mapped[str | None] = mapped_column(String(120))
    #: Track distance from the *previous* station to the crossing, km.
    distance_from_prev_km: Mapped[float] = mapped_column(Float, default=1.0)
    #: Track distance from the crossing to the *next* station, km.
    distance_from_next_km: Mapped[float] = mapped_column(Float, default=1.0)
    track_count: Mapped[int] = mapped_column(Integer, default=2)

    # --- gate behaviour (physical defaults; learning refines them) ---------
    #: Distance at which the gate is ordered shut. Lead *time* = this / speed.
    approach_distance_km: Mapped[float] = mapped_column(Float, default=2.5)
    min_close_lead_seconds: Mapped[int] = mapped_column(Integer, default=120)
    max_close_lead_seconds: Mapped[int] = mapped_column(Integer, default=600)
    #: Fixed operator reaction time added after the train clears the gate.
    reopen_lag_seconds: Mapped[int] = mapped_column(Integer, default=75)
    #: Consecutive closures separated by less than this are one closure.
    min_gate_cycle_seconds: Mapped[int] = mapped_column(Integer, default=210)
    notes: Mapped[str | None] = mapped_column(String(500))

    timetable: Mapped[list[TimetableEntry]] = relationship(
        back_populates="crossing", cascade="all, delete-orphan"
    )

    @property
    def segment_length_km(self) -> float:
        return self.distance_from_prev_km + self.distance_from_next_km


class TimetableEntry(TimestampMixin, Base):
    """Offline schedule powering the terminal fallback provider.

    ``scheduled_pass_minute`` is minutes past IST midnight, which makes
    day-of-week recurrence queries trivial and dialect-independent.
    """

    __tablename__ = "timetable_entries"
    __table_args__ = (
        UniqueConstraint("crossing_id", "train_number", "scheduled_pass_minute"),
        Index("ix_timetable_lookup", "crossing_id", "scheduled_pass_minute"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crossing_id: Mapped[int] = mapped_column(ForeignKey("crossings.id", ondelete="CASCADE"))
    train_number: Mapped[str] = mapped_column(String(12), index=True)
    train_name: Mapped[str] = mapped_column(String(120))
    train_type: Mapped[str] = mapped_column(String(40), default="Express")
    direction: Mapped[str] = mapped_column(String(10), default=Direction.UP.value)
    scheduled_pass_minute: Mapped[int] = mapped_column(Integer)
    #: 7 chars, index 0 = Monday, '1' means the train runs that day.
    run_days: Mapped[str] = mapped_column(String(7), default="1111111")
    typical_speed_kmph: Mapped[float] = mapped_column(Float, default=60.0)

    crossing: Mapped[Crossing] = relationship(back_populates="timetable")

    def runs_on(self, weekday: int) -> bool:
        return len(self.run_days) == 7 and self.run_days[weekday] == "1"


class SightingSnapshot(TimestampMixin, Base):
    """A normalised provider observation of one train, relative to one crossing."""

    __tablename__ = "sighting_snapshots"
    __table_args__ = (
        Index("ix_sighting_crossing_time", "crossing_id", "observed_at"),
        Index("ix_sighting_train", "crossing_id", "train_number", "observed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crossing_id: Mapped[int] = mapped_column(ForeignKey("crossings.id", ondelete="CASCADE"))
    train_number: Mapped[str] = mapped_column(String(12))
    train_name: Mapped[str | None] = mapped_column(String(120))
    train_type: Mapped[str | None] = mapped_column(String(40))
    provider: Mapped[str] = mapped_column(String(40))
    provider_trust: Mapped[float] = mapped_column(Float, default=0.5)
    direction: Mapped[str] = mapped_column(String(10), default=Direction.UNKNOWN.value)
    observed_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    delay_minutes: Mapped[int] = mapped_column(Integer, default=0)
    distance_to_crossing_km: Mapped[float | None] = mapped_column(Float)
    speed_kmph: Mapped[float | None] = mapped_column(Float)
    is_actual_position: Mapped[bool] = mapped_column(Boolean, default=False)
    estimated_pass_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    raw_payload: Mapped[dict | None] = mapped_column(JSON)


class ClosureWindow(TimestampMixin, Base):
    """A materialised interval during which the gate is (or was) shut."""

    __tablename__ = "closure_windows"
    __table_args__ = (Index("ix_window_crossing_time", "crossing_id", "close_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    crossing_id: Mapped[int] = mapped_column(ForeignKey("crossings.id", ondelete="CASCADE"))
    close_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    open_at: Mapped[datetime] = mapped_column(UtcDateTime)
    source: Mapped[str] = mapped_column(String(16), default=WindowSource.PREDICTED.value)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    #: Trains responsible for this window: [{number, name, type, pass_at, direction}]
    causes: Mapped[list | None] = mapped_column(JSON)
    is_superseded: Mapped[bool] = mapped_column(Boolean, default=False)

    @property
    def duration_seconds(self) -> float:
        return (self.open_at - self.close_at).total_seconds()


class PredictionRecord(TimestampMixin, Base):
    """One prediction, kept so the learning engine can grade it later."""

    __tablename__ = "prediction_records"
    __table_args__ = (
        Index("ix_pred_match", "crossing_id", "train_number", "predicted_pass_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    crossing_id: Mapped[int] = mapped_column(ForeignKey("crossings.id", ondelete="CASCADE"))
    train_number: Mapped[str] = mapped_column(String(12), index=True)
    train_class: Mapped[str] = mapped_column(String(24), default="express", index=True)
    #: Direction of travel. A chainage error shifts UP and DOWN errors in
    #: *opposite* directions — that signature is what the geometry calibrator
    #: keys on, so it must be stored per prediction.
    direction: Mapped[str] = mapped_column(String(10), default=Direction.UNKNOWN.value)
    speed_kmph: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str] = mapped_column(String(40))
    predicted_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    predicted_pass_at: Mapped[datetime] = mapped_column(UtcDateTime)
    predicted_close_at: Mapped[datetime] = mapped_column(UtcDateTime)
    predicted_open_at: Mapped[datetime] = mapped_column(UtcDateTime)
    #: Seconds between making the prediction and the predicted event — error
    #: is only comparable within a horizon band.
    horizon_seconds: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    graded: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    observation_id: Mapped[int | None] = mapped_column(
        ForeignKey("observations.id", ondelete="SET NULL")
    )
    pass_error_seconds: Mapped[float | None] = mapped_column(Float)
    close_error_seconds: Mapped[float | None] = mapped_column(Float)
    open_error_seconds: Mapped[float | None] = mapped_column(Float)


class Observation(TimestampMixin, Base):
    """Ground truth: what actually happened at the gate."""

    __tablename__ = "observations"
    __table_args__ = (Index("ix_obs_crossing_time", "crossing_id", "observed_pass_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    crossing_id: Mapped[int] = mapped_column(ForeignKey("crossings.id", ondelete="CASCADE"))
    train_number: Mapped[str | None] = mapped_column(String(12), index=True)
    train_class: Mapped[str] = mapped_column(String(24), default="express")
    source: Mapped[str] = mapped_column(
        String(24), default=ObservationSource.PROVIDER_ACTUALS.value
    )
    observed_pass_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    observed_close_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    observed_open_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    #: True when no prediction explained this closure — the freight signal.
    is_unexplained: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    detail: Mapped[dict | None] = mapped_column(JSON)


class CalibrationProfile(TimestampMixin, Base):
    """Learned per-crossing, per-train-class corrections (EWMA)."""

    __tablename__ = "calibration_profiles"
    __table_args__ = (UniqueConstraint("crossing_id", "train_class"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    crossing_id: Mapped[int] = mapped_column(ForeignKey("crossings.id", ondelete="CASCADE"))
    train_class: Mapped[str] = mapped_column(String(24), default="default")
    pass_offset_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    close_offset_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    open_offset_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    pass_mae_seconds: Mapped[float] = mapped_column(Float, default=0.0)
    sample_count: Mapped[int] = mapped_column(Integer, default=0)
    last_sample_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class GateReport(TimestampMixin, Base):
    """Crowd-sourced report from someone standing at the gate."""

    __tablename__ = "gate_reports"
    __table_args__ = (Index("ix_report_crossing_time", "crossing_id", "reported_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    crossing_id: Mapped[int] = mapped_column(ForeignKey("crossings.id", ondelete="CASCADE"))
    state: Mapped[str] = mapped_column(String(10))
    reported_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    #: SHA-256 of a client-generated id. We never store the id itself, and it
    #: identifies a browser, not a person.
    client_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    #: SHA-256 of the client IP, salted. Only used for rate limiting, and only
    #: as a fallback when a client mints a fresh id.
    ip_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    note: Mapped[str | None] = mapped_column(String(280))


class GeometryAdjustment(TimestampMixin, Base):
    """Audit trail for autonomous chainage corrections.

    Every automatic change to a crossing's surveyed distances is recorded with
    the evidence that justified it, so a human can always answer "why did the
    machine move my crossing 200 metres?".
    """

    __tablename__ = "geometry_adjustments"

    id: Mapped[int] = mapped_column(primary_key=True)
    crossing_id: Mapped[int] = mapped_column(ForeignKey("crossings.id", ondelete="CASCADE"))
    applied_at: Mapped[datetime] = mapped_column(UtcDateTime, index=True)
    delta_km: Mapped[float] = mapped_column(Float)
    old_distance_from_prev_km: Mapped[float] = mapped_column(Float)
    new_distance_from_prev_km: Mapped[float] = mapped_column(Float)
    #: {bias_up_s, bias_down_s, samples_up, samples_down, speed_up, speed_down}
    evidence: Mapped[dict | None] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(String(300))


class NotificationSubscription(TimestampMixin, Base):
    """Web Push subscription. Schema shipped in v1; delivery job is Stage-2 scope."""

    __tablename__ = "notification_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    crossing_id: Mapped[int] = mapped_column(ForeignKey("crossings.id", ondelete="CASCADE"))
    endpoint: Mapped[str] = mapped_column(String(500), unique=True)
    p256dh: Mapped[str] = mapped_column(String(255))
    auth: Mapped[str] = mapped_column(String(255))
    lead_minutes: Mapped[int] = mapped_column(Integer, default=10)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
