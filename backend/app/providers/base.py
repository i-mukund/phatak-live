"""Provider contract.

Adding a data source means implementing this protocol and registering it.
Nothing else in the codebase changes (ADR 0001).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.core.budget import ApiBudget
from app.domain import CrossingRef, ProviderHealth, TrainSighting


@dataclass(frozen=True, slots=True)
class FetchContext:
    """Everything a provider needs, and nothing more."""

    crossing: CrossingRef
    now: datetime
    horizon_minutes: int = 120
    #: Optional shared budget. Providers that cost money must respect it.
    budget: ApiBudget | None = None
    #: Max expensive per-train detail calls this tick.
    live_call_allowance: int = 2


@runtime_checkable
class TrainDataProvider(Protocol):
    """A source of train sightings near a crossing."""

    #: Stable identifier used in logs, metrics and persisted rows.
    name: str
    #: Trust weight in [0, 1]; flows into the confidence score.
    trust: float

    async def fetch_sightings(self, ctx: FetchContext) -> list[TrainSighting]:
        """Return sightings relevant to ``ctx.crossing``.

        Raise :class:`app.core.errors.ProviderError` on failure — never return
        partial garbage. The chain decides what to do next.
        """
        ...

    async def health(self) -> ProviderHealth:
        """Cheap liveness probe. Must not consume request budget."""
        ...

    async def close(self) -> None:
        """Release transport resources."""
        ...


class BaseProvider:
    """Convenience base: sane defaults for ``health`` and ``close``."""

    name: str = "base"
    trust: float = 0.5

    async def fetch_sightings(self, ctx: FetchContext) -> list[TrainSighting]:
        raise NotImplementedError

    async def health(self) -> ProviderHealth:
        return ProviderHealth(name=self.name, healthy=True, detail="ok")

    async def close(self) -> None:
        return None
