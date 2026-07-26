"""User-triggered refresh (pull-to-refresh).

A pull is a request for the freshest answer *available*, not an instruction to
spend money. Upstream providers are metered — RailRadar's free tier is 100
calls/day and the scheduler already claims most of it — so an unguarded refresh
button would let a handful of enthusiastic pulls exhaust the daily quota before
lunch and leave everyone with timetable-grade predictions.

Three guards, in order of cheapness:

1. **Freshness** — if the newest sighting is younger than
   ``manual_refresh_min_age_seconds`` there is nothing to gain; return what we
   have and say so.
2. **Budget floor** — never spend the last slice of the daily allowance on a
   manual refresh; scheduled ingestion has first claim on it.
3. **Single flight** — concurrent pulls collapse into one upstream fetch, so
   ten people pulling at once costs what one person costs.

Freshness is read from the database rather than in-process state, so the guard
survives restarts and holds across multiple instances.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.budget import ApiBudget
from app.core.config import Settings
from app.core.logging import get_logger
from app.db.models import Crossing, SightingSnapshot
from app.services.ingest import IngestService

logger = get_logger(__name__)


class RefreshOutcome(str, Enum):
    REFRESHED = "refreshed"
    ALREADY_FRESH = "already_fresh"
    BUDGET_PROTECTED = "budget_protected"
    PROVIDER_FAILED = "provider_failed"


#: Human-readable, shown directly in the UI. Honesty is the point: the user
#: pulled and deserves to know whether anything actually happened.
_REASONS: dict[RefreshOutcome, str] = {
    RefreshOutcome.REFRESHED: "Updated with the latest train positions.",
    RefreshOutcome.ALREADY_FRESH: "Already up to date.",
    RefreshOutcome.BUDGET_PROTECTED: (
        "Showing the most recent data — live updates are rate-limited to stay "
        "within the free data allowance."
    ),
    RefreshOutcome.PROVIDER_FAILED: (
        "Couldn't reach the live train feed; showing the last known prediction."
    ),
}


@dataclass(frozen=True, slots=True)
class RefreshResult:
    outcome: RefreshOutcome
    reason: str
    data_age_seconds: float | None
    next_refresh_at: datetime | None

    @property
    def refreshed(self) -> bool:
        return self.outcome is RefreshOutcome.REFRESHED


class RefreshService:
    def __init__(
        self,
        *,
        ingest: IngestService,
        settings: Settings,
        budget: ApiBudget | None = None,
    ) -> None:
        self._ingest = ingest
        self._settings = settings
        self._budget = budget
        #: One lock per crossing: collapses a thundering herd of pulls into a
        #: single upstream fetch.
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock_for(self, crossing_id: int) -> asyncio.Lock:
        lock = self._locks.get(crossing_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[crossing_id] = lock
        return lock

    def last_ingest_at(self, session: Session, crossing_id: int) -> datetime | None:
        return session.scalar(
            select(func.max(SightingSnapshot.observed_at)).where(
                SightingSnapshot.crossing_id == crossing_id
            )
        )

    def _age_seconds(self, last: datetime | None, now: datetime) -> float | None:
        return None if last is None else (now - last).total_seconds()

    async def refresh(
        self, session: Session, crossing: Crossing, now: datetime
    ) -> RefreshResult:
        min_age = self._settings.manual_refresh_min_age_seconds
        last = self.last_ingest_at(session, crossing.id)
        age = self._age_seconds(last, now)

        if last is not None and age is not None and age < min_age:
            return RefreshResult(
                outcome=RefreshOutcome.ALREADY_FRESH,
                reason=_REASONS[RefreshOutcome.ALREADY_FRESH],
                data_age_seconds=round(age, 1),
                next_refresh_at=last + timedelta(seconds=min_age),
            )

        if not self._budget_allows():
            return RefreshResult(
                outcome=RefreshOutcome.BUDGET_PROTECTED,
                reason=_REASONS[RefreshOutcome.BUDGET_PROTECTED],
                data_age_seconds=None if age is None else round(age, 1),
                next_refresh_at=None,
            )

        async with self._lock_for(crossing.id):
            # Re-check inside the lock: whoever held it may have just refreshed.
            recheck = self._age_seconds(self.last_ingest_at(session, crossing.id), now)
            if recheck is not None and recheck < min_age:
                return RefreshResult(
                    outcome=RefreshOutcome.REFRESHED,
                    reason=_REASONS[RefreshOutcome.REFRESHED],
                    data_age_seconds=round(recheck, 1),
                    next_refresh_at=now + timedelta(seconds=min_age),
                )
            try:
                result = await self._ingest.run_for_crossing(session, crossing)
            except Exception:
                logger.exception("manual refresh failed for %s", crossing.slug)
                return RefreshResult(
                    outcome=RefreshOutcome.PROVIDER_FAILED,
                    reason=_REASONS[RefreshOutcome.PROVIDER_FAILED],
                    data_age_seconds=None if age is None else round(age, 1),
                    next_refresh_at=None,
                )

        if result.degraded and not result.sightings:
            return RefreshResult(
                outcome=RefreshOutcome.PROVIDER_FAILED,
                reason=_REASONS[RefreshOutcome.PROVIDER_FAILED],
                data_age_seconds=None if age is None else round(age, 1),
                next_refresh_at=None,
            )

        logger.info("manual refresh for %s: %d sighting(s)", crossing.slug, result.sightings)
        return RefreshResult(
            outcome=RefreshOutcome.REFRESHED,
            reason=_REASONS[RefreshOutcome.REFRESHED],
            data_age_seconds=0.0,
            next_refresh_at=now + timedelta(seconds=min_age),
        )

    def _budget_allows(self) -> bool:
        if self._budget is None:
            return True
        floor = self._settings.manual_refresh_budget_floor
        reserved = self._budget.daily_limit * floor
        # A tick costs two board calls; require both plus the reserve.
        return self._budget.remaining - 2 >= reserved
