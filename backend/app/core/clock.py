"""Time utilities.

Time is injected, never read ambiently, so predictions are reproducible
(see ADR 0002). :class:`Clock` is the only place that touches the wall clock.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc


class Clock(Protocol):
    def now(self) -> datetime:  # pragma: no cover - protocol
        ...


class SystemClock:
    """Real wall clock, always timezone-aware UTC."""

    def now(self) -> datetime:
        return datetime.now(tz=UTC)


class FrozenClock:
    """Deterministic clock for tests and replay."""

    def __init__(self, at: datetime) -> None:
        self._at = ensure_aware(at)

    def now(self) -> datetime:
        return self._at

    def advance(self, seconds: float) -> None:
        self._at += timedelta(seconds=seconds)


def ensure_aware(dt: datetime) -> datetime:
    """Coerce naive datetimes to UTC. Naive datetimes are a bug magnet."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def to_ist(dt: datetime) -> datetime:
    return ensure_aware(dt).astimezone(IST)


def to_utc(dt: datetime) -> datetime:
    return ensure_aware(dt).astimezone(UTC)


def isoformat_ist(dt: datetime | None) -> str | None:
    """Serialise as IST with offset — what an Indian commuter expects to read."""
    return None if dt is None else to_ist(dt).isoformat(timespec="seconds")
