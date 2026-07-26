"""Upstream request budget.

RailRadar's free tier allows 50 requests/day. Rather than discovering that by
collecting 429s, we spend deliberately: cheap calls first, expensive calls only
while budget remains, and graceful degradation to board-only mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.core.clock import Clock, SystemClock, to_ist


@dataclass
class ApiBudget:
    """Daily request budget, reset at IST midnight (when the vendor resets)."""

    daily_limit: int
    clock: Clock = field(default_factory=SystemClock)
    #: Fraction of the daily budget reserved for cheap, mandatory calls.
    reserve_fraction: float = 0.5

    _spent: int = 0
    _day: date | None = None

    def _roll(self) -> None:
        today = to_ist(self.clock.now()).date()
        if self._day != today:
            self._day = today
            self._spent = 0

    @property
    def spent(self) -> int:
        self._roll()
        return self._spent

    @property
    def remaining(self) -> int:
        self._roll()
        return max(0, self.daily_limit - self._spent)

    def can_spend(self, cost: int = 1, *, essential: bool = True) -> bool:
        """Essential calls may use the whole budget; optional calls only the
        unreserved portion, so enrichment never starves core ingestion."""
        self._roll()
        floor = 0 if essential else int(self.daily_limit * self.reserve_fraction)
        return self._spent + cost <= self.daily_limit - floor

    def spend(self, cost: int = 1) -> None:
        self._roll()
        self._spent += cost

    def snapshot(self) -> dict[str, object]:
        return {
            "daily_limit": self.daily_limit,
            "spent": self.spent,
            "remaining": self.remaining,
            "day_ist": self._day.isoformat() if self._day else None,
        }
