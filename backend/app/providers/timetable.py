"""Offline timetable provider — the terminal fallback that cannot fail.

Reads the seeded schedule from our own database. It has no live delay
information, so its trust is low and the confidence score reflects that. But it
is *always available*, which means "all providers are down" never becomes "the
app shows nothing" (failure mode F3).
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import IST, to_ist, to_utc
from app.db.models import TimetableEntry
from app.domain import (
    Direction,
    ProviderHealth,
    RunStatus,
    TrainSighting,
    classify_train,
)
from app.providers.base import BaseProvider, FetchContext

SessionMaker = Callable[[], AbstractContextManager[Session]]


class TimetableProvider(BaseProvider):
    name = "timetable"
    trust = 0.45

    def __init__(self, session_scope: SessionMaker) -> None:
        self._session_scope = session_scope

    async def fetch_sightings(self, ctx: FetchContext) -> list[TrainSighting]:
        horizon_end = ctx.now + timedelta(minutes=ctx.horizon_minutes)
        window_start = ctx.now - timedelta(minutes=15)

        with self._session_scope() as session:
            entries = list(
                session.scalars(
                    select(TimetableEntry).where(
                        TimetableEntry.crossing_id == ctx.crossing.id
                    )
                )
            )

        sightings: list[TrainSighting] = []
        for entry in entries:
            for pass_at in self._occurrences(entry, window_start, horizon_end):
                sightings.append(
                    TrainSighting(
                        train_number=entry.train_number,
                        train_name=entry.train_name,
                        provider=self.name,
                        provider_trust=self.trust,
                        observed_at=ctx.now,
                        train_class=classify_train(entry.train_type, entry.train_name),
                        train_type=entry.train_type,
                        status=RunStatus.SCHEDULED,
                        delay_minutes=0,
                        direct_pass_estimate=pass_at,
                        direct_speed_kmph=entry.typical_speed_kmph,
                        direct_direction=Direction(entry.direction),
                        raw={"source": "timetable", "entry_id": entry.id},
                    )
                )
        return sightings

    def _occurrences(
        self, entry: TimetableEntry, start: datetime, end: datetime
    ) -> list[datetime]:
        """Expand a recurring schedule row into concrete instants in the window.

        We probe yesterday/today/tomorrow in IST because a window can straddle
        midnight and run-day flags are defined in local time.
        """
        out: list[datetime] = []
        today_ist = to_ist(start).date()
        for day_offset in (-1, 0, 1):
            day = today_ist + timedelta(days=day_offset)
            if not entry.runs_on(day.weekday()):
                continue
            local = datetime(day.year, day.month, day.day, tzinfo=IST) + timedelta(
                minutes=entry.scheduled_pass_minute
            )
            moment = to_utc(local)
            if start <= moment <= end:
                out.append(moment)
        return out

    async def health(self) -> ProviderHealth:
        try:
            with self._session_scope() as session:
                session.execute(select(TimetableEntry.id).limit(1))
            return ProviderHealth(name=self.name, healthy=True, detail="ok")
        except Exception as exc:  # pragma: no cover - DB failure path
            return ProviderHealth(name=self.name, healthy=False, detail=str(exc))
