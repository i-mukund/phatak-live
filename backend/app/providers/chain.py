"""Failover chain.

Providers are grouped into tiers. Every **primary** provider is attempted (they
may see different trains); if none yields a usable result, the **fallback** tier
runs. The fallback tier terminates in the offline timetable provider, which
cannot fail — so the chain always returns something.

Each provider is wrapped in its own circuit breaker and timeout, so one sick
source cannot slow down or take out the others.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import IntEnum

from app.core.circuit_breaker import CircuitBreaker
from app.core.errors import CircuitOpenError, ProviderError
from app.core.logging import get_logger
from app.core.metrics import CIRCUIT_STATE, SIGHTINGS_SEEN
from app.core.retry import retry_async
from app.domain import ProviderHealth, TrainSighting
from app.providers.base import FetchContext, TrainDataProvider

logger = get_logger(__name__)


class ProviderTier(IntEnum):
    PRIMARY = 0
    FALLBACK = 1


@dataclass
class RegisteredProvider:
    provider: TrainDataProvider
    tier: ProviderTier = ProviderTier.PRIMARY
    breaker: CircuitBreaker | None = None

    @property
    def name(self) -> str:
        return self.provider.name

    @property
    def trust(self) -> float:
        return self.provider.trust


@dataclass
class ChainResult:
    sightings: list[TrainSighting] = field(default_factory=list)
    providers_used: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    #: True when no primary provider contributed — the UI shows a softer claim.
    degraded: bool = True

    @property
    def best_trust(self) -> float:
        return max((s.provider_trust for s in self.sightings), default=0.0)


class FailoverChain:
    def __init__(
        self,
        providers: list[RegisteredProvider],
        *,
        timeout: float = 8.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
    ) -> None:
        self._providers = sorted(providers, key=lambda r: (r.tier, -r.trust))
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base = backoff_base

    @property
    def providers(self) -> list[RegisteredProvider]:
        return list(self._providers)

    async def fetch(self, ctx: FetchContext) -> ChainResult:
        result = ChainResult()
        for tier in (ProviderTier.PRIMARY, ProviderTier.FALLBACK):
            members = [r for r in self._providers if r.tier == tier]
            if not members:
                continue
            for registered in members:
                sightings = await self._attempt(registered, ctx, result)
                if sightings:
                    result.providers_used.append(registered.name)
                    result.sightings.extend(sightings)
                    SIGHTINGS_SEEN.labels(registered.name).inc(len(sightings))
            if result.sightings:
                result.degraded = tier is not ProviderTier.PRIMARY
                break
        result.sightings = _merge(result.sightings)
        return result

    async def _attempt(
        self, registered: RegisteredProvider, ctx: FetchContext, result: ChainResult
    ) -> list[TrainSighting]:
        breaker = registered.breaker
        if breaker is not None:
            CIRCUIT_STATE.labels(registered.name).set(0.0 if breaker.allows() else 1.0)
            if not breaker.allows():
                result.errors[registered.name] = "circuit open"
                logger.warning("skipping %s: circuit open", registered.name)
                return []
        try:
            sightings = await retry_async(
                lambda: asyncio.wait_for(
                    registered.provider.fetch_sightings(ctx), timeout=self._timeout
                ),
                attempts=self._max_retries,
                base_delay=self._backoff_base,
                label=f"provider:{registered.name}",
            )
        except (ProviderError, CircuitOpenError) as exc:
            result.errors[registered.name] = str(exc)
            if breaker is not None:
                breaker.record_failure()
                CIRCUIT_STATE.labels(registered.name).set(0.0 if breaker.allows() else 1.0)
            logger.error("provider %s failed: %s", registered.name, exc)
            return []
        except (TimeoutError, asyncio.TimeoutError) as exc:
            result.errors[registered.name] = f"timeout: {exc}"
            if breaker is not None:
                breaker.record_failure()
            logger.error("provider %s timed out", registered.name)
            return []
        except Exception as exc:  # defensive: a provider bug must not kill ingest
            result.errors[registered.name] = f"unexpected: {exc}"
            if breaker is not None:
                breaker.record_failure()
            logger.exception("provider %s raised unexpectedly", registered.name)
            return []

        if breaker is not None:
            breaker.record_success()
            CIRCUIT_STATE.labels(registered.name).set(0.0)
        return [s for s in sightings if s.is_actionable]

    async def health(self) -> list[ProviderHealth]:
        out: list[ProviderHealth] = []
        for registered in self._providers:
            try:
                health = await asyncio.wait_for(
                    registered.provider.health(), timeout=self._timeout
                )
            except Exception as exc:
                health = ProviderHealth(name=registered.name, healthy=False, detail=str(exc))
            if registered.breaker is not None:
                health = ProviderHealth(
                    name=health.name,
                    healthy=health.healthy and registered.breaker.allows(),
                    detail=health.detail,
                    latency_ms=health.latency_ms,
                    circuit_state=registered.breaker.state.value,
                )
            out.append(health)
        return out

    def snapshot(self) -> list[dict[str, object]]:
        return [
            {
                "name": r.name,
                "trust": r.trust,
                "tier": r.tier.name.lower(),
                "circuit": r.breaker.snapshot() if r.breaker else None,
            }
            for r in self._providers
        ]

    async def close(self) -> None:
        for registered in self._providers:
            try:
                await registered.provider.close()
            except Exception:  # pragma: no cover - shutdown best effort
                logger.warning("error closing provider %s", registered.name)


#: Two sightings of the same train number closer together than this are the
#: same run seen by two providers. Wider apart, they are two genuine services.
_SAME_RUN_WINDOW = timedelta(minutes=90)


def _merge(sightings: list[TrainSighting]) -> list[TrainSighting]:
    """Deduplicate by train number; the most trusted, then richest, wins.

    Grouping is by *time proximity* rather than by clock buckets: a fixed
    hourly bucket would split one run seen at 10:59 and 11:01 into two, which
    is exactly the case that produces a phantom closure.
    """
    by_number: dict[str, list[TrainSighting]] = defaultdict(list)
    for sighting in sightings:
        by_number[sighting.train_number].append(sighting)

    winners: list[TrainSighting] = []
    for group in by_number.values():
        group.sort(key=_moment)
        cluster: list[TrainSighting] = []
        for sighting in group:
            if cluster and _moment(sighting) - _moment(cluster[-1]) > _SAME_RUN_WINDOW:
                winners.append(max(cluster, key=_rank))
                cluster = []
            cluster.append(sighting)
        if cluster:
            winners.append(max(cluster, key=_rank))
    return sorted(winners, key=_moment)


def _moment(sighting: TrainSighting) -> datetime:
    return sighting.direct_pass_estimate or sighting.observed_at


def _rank(sighting: TrainSighting) -> tuple[float, float, float]:
    return (
        sighting.provider_trust,
        1.0 if sighting.route else 0.0,
        sighting.observed_at.timestamp(),
    )
