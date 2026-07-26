"""Composition root for the provider layer.

The only module that knows which concrete providers exist. Everything else
depends on :class:`FailoverChain`.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from sqlalchemy.orm import Session

from app.core.budget import ApiBudget
from app.core.cache import Cache
from app.core.circuit_breaker import CircuitBreaker
from app.core.clock import Clock, SystemClock
from app.core.config import Settings
from app.core.logging import get_logger
from app.providers.chain import FailoverChain, ProviderTier, RegisteredProvider
from app.providers.generic_rest import GenericRestProvider
from app.providers.mock import MockProvider
from app.providers.railradar import RailRadarProvider
from app.providers.timetable import TimetableProvider

logger = get_logger(__name__)

SessionMaker = Callable[[], AbstractContextManager[Session]]


def build_chain(
    settings: Settings,
    *,
    session_scope: SessionMaker,
    cache: Cache | None = None,
    clock: Clock | None = None,
) -> FailoverChain:
    clock = clock or SystemClock()
    registered: list[RegisteredProvider] = []

    def breaker(name: str) -> CircuitBreaker:
        return CircuitBreaker(
            name=name,
            failure_threshold=settings.circuit_breaker_failure_threshold,
            reset_timeout=settings.circuit_breaker_reset_seconds,
            clock=clock,
        )

    if settings.railradar_api_key:
        registered.append(
            RegisteredProvider(
                provider=RailRadarProvider(
                    api_key=settings.railradar_api_key,
                    base_url=settings.railradar_base_url,
                    timeout=settings.provider_timeout_seconds,
                    cache=cache,
                    cache_ttl=settings.cache_provider_ttl_seconds,
                ),
                tier=ProviderTier.PRIMARY,
                breaker=breaker("railradar"),
            )
        )

    if settings.generic_rest_base_url:
        registered.append(
            RegisteredProvider(
                provider=GenericRestProvider(
                    base_url=settings.generic_rest_base_url,
                    api_key=settings.generic_rest_api_key,
                    timeout=settings.provider_timeout_seconds,
                    cache=cache,
                    cache_ttl=settings.cache_provider_ttl_seconds,
                ),
                tier=ProviderTier.PRIMARY,
                breaker=breaker("generic_rest"),
            )
        )

    # Without a real key the app must still be runnable: the mock provider is
    # promoted to primary so `docker compose up` gives a working demo.
    if settings.enable_mock_provider or not settings.has_live_provider:
        if not settings.has_live_provider:
            logger.warning(
                "no live provider configured — using MockProvider. "
                "Set RAILRADAR_API_KEY for real data."
            )
        registered.append(
            RegisteredProvider(
                provider=MockProvider(),
                tier=ProviderTier.PRIMARY if not settings.has_live_provider
                else ProviderTier.FALLBACK,
                breaker=breaker("mock"),
            )
        )

    registered.append(
        RegisteredProvider(
            provider=TimetableProvider(session_scope=session_scope),
            tier=ProviderTier.FALLBACK,
            breaker=breaker("timetable"),
        )
    )

    return FailoverChain(
        registered,
        timeout=settings.provider_timeout_seconds,
        max_retries=settings.provider_max_retries,
        backoff_base=settings.provider_backoff_base_seconds,
    )


def build_budget(settings: Settings, clock: Clock | None = None) -> ApiBudget:
    return ApiBudget(
        daily_limit=settings.api_daily_request_budget, clock=clock or SystemClock()
    )
