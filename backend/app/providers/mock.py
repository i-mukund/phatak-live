"""Deterministic mock provider.

Used for local development without an API key, for demos, and as the
controllable double in tests. It synthesises a plausible Siraspur-like traffic
pattern from the clock alone, so behaviour is reproducible.
"""

from __future__ import annotations

from datetime import timedelta

from app.core.clock import to_ist
from app.domain import (
    Direction,
    ProviderHealth,
    RunStatus,
    TrainSighting,
    classify_train,
)
from app.providers.base import BaseProvider, FetchContext

#: (minutes past IST midnight, number, name, type, speed kmph, direction)
_PATTERN: tuple[tuple[int, str, str, str, float, Direction], ...] = (
    (0, "64901", "Delhi-Panipat EMU", "EMU", 55.0, Direction.UP),
    (17, "12045", "Kalka Shatabdi", "Shatabdi Express", 95.0, Direction.UP),
    (33, "54303", "Delhi-Kurukshetra Passenger", "Passenger", 45.0, Direction.DOWN),
    (48, "12471", "Swaraj Express", "Superfast Express", 88.0, Direction.DOWN),
)


class MockProvider(BaseProvider):
    name = "mock"
    trust = 0.35

    def __init__(self, *, period_minutes: int = 60, trust: float | None = None) -> None:
        self._period = period_minutes
        if trust is not None:
            self.trust = trust

    async def fetch_sightings(self, ctx: FetchContext) -> list[TrainSighting]:
        out: list[TrainSighting] = []
        local = to_ist(ctx.now)
        period_start = local.replace(minute=0, second=0, microsecond=0)
        periods = range(0, (ctx.horizon_minutes // self._period) + 2)

        for p in periods:
            base = period_start + timedelta(minutes=self._period * p)
            for offset, number, name, ttype, speed, direction in _PATTERN:
                pass_at = base + timedelta(minutes=offset)
                if not (ctx.now - timedelta(minutes=10) <= pass_at <=
                        ctx.now + timedelta(minutes=ctx.horizon_minutes)):
                    continue
                out.append(
                    TrainSighting(
                        train_number=number,
                        train_name=name,
                        provider=self.name,
                        provider_trust=self.trust,
                        observed_at=ctx.now,
                        train_class=classify_train(ttype, name),
                        train_type=ttype,
                        status=RunStatus.RUNNING,
                        delay_minutes=(p * 3) % 12,
                        direct_pass_estimate=pass_at,
                        direct_speed_kmph=speed,
                        direct_direction=direction,
                        raw={"source": "mock"},
                    )
                )
        return out

    async def health(self) -> ProviderHealth:
        return ProviderHealth(name=self.name, healthy=True, detail="mock always healthy")
