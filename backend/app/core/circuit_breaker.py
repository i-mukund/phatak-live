"""Circuit breaker.

Stops us from hammering — and paying for — a provider that is already down.
Standard three-state machine: CLOSED → OPEN → HALF_OPEN → CLOSED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum

from app.core.clock import Clock, SystemClock


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 4
    reset_timeout: float = 120.0
    clock: Clock = field(default_factory=SystemClock)

    _failures: int = 0
    _state: CircuitState = CircuitState.CLOSED
    _opened_at: datetime | None = None

    @property
    def state(self) -> CircuitState:
        if (
            self._state is CircuitState.OPEN
            and self._opened_at is not None
            and self.clock.now() - self._opened_at >= timedelta(seconds=self.reset_timeout)
        ):
            self._state = CircuitState.HALF_OPEN
        return self._state

    def allows(self) -> bool:
        """True if a call may proceed. HALF_OPEN admits a single probe."""
        return self.state is not CircuitState.OPEN

    def record_success(self) -> None:
        self._failures = 0
        self._state = CircuitState.CLOSED
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._state is CircuitState.HALF_OPEN or self._failures >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = self.clock.now()

    def snapshot(self) -> dict[str, object]:
        return {
            "name": self.name,
            "state": self.state.value,
            "failures": self._failures,
            "opened_at": self._opened_at.isoformat() if self._opened_at else None,
        }
