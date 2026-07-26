"""Shared HTTP plumbing for REST providers."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.cache import Cache
from app.core.errors import (
    ProviderError,
    ProviderRateLimited,
    ProviderUnavailable,
)
from app.core.logging import get_logger
from app.core.metrics import PROVIDER_LATENCY, PROVIDER_REQUESTS

logger = get_logger(__name__)


class RestClient:
    """Thin httpx wrapper that translates transport/status failures into typed
    :class:`ProviderError`s and optionally memoises GETs.

    Caching lives here rather than in each provider because the whole point of
    caching upstream calls is quota protection, which is a cross-provider concern.
    """

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 8.0,
        cache: Cache | None = None,
        cache_ttl: int = 60,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self._cache = cache
        self._cache_ttl = cache_ttl
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url,
            headers=headers or {},
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
        )

    async def get_json(
        self, path: str, params: dict[str, Any] | None = None, *, use_cache: bool = True
    ) -> dict[str, Any]:
        key = f"{self.provider}:{path}:{sorted((params or {}).items())}"
        if use_cache and self._cache is not None:
            cached = await self._cache.get(key)
            if cached is not None:
                return cached

        started = time.perf_counter()
        try:
            response = await self._client.get(path, params=params)
        except httpx.TimeoutException as exc:
            PROVIDER_REQUESTS.labels(self.provider, "timeout").inc()
            raise ProviderUnavailable(self.provider, f"timeout: {exc}") from exc
        except httpx.HTTPError as exc:
            PROVIDER_REQUESTS.labels(self.provider, "transport_error").inc()
            raise ProviderUnavailable(self.provider, f"transport error: {exc}") from exc
        finally:
            PROVIDER_LATENCY.labels(self.provider).observe(time.perf_counter() - started)

        self._raise_for_status(response)

        try:
            payload = response.json()
        except ValueError as exc:
            PROVIDER_REQUESTS.labels(self.provider, "bad_json").inc()
            raise ProviderError(self.provider, "response was not valid JSON",
                                retryable=False) from exc
        if not isinstance(payload, dict):
            PROVIDER_REQUESTS.labels(self.provider, "bad_shape").inc()
            raise ProviderError(self.provider, "expected a JSON object", retryable=False)

        PROVIDER_REQUESTS.labels(self.provider, "ok").inc()
        if use_cache and self._cache is not None:
            await self._cache.set(key, payload, self._cache_ttl)
        return payload

    def _raise_for_status(self, response: httpx.Response) -> None:
        code = response.status_code
        if code < 400:
            return
        if code == 429:
            PROVIDER_REQUESTS.labels(self.provider, "rate_limited").inc()
            retry_after = response.headers.get("Retry-After")
            raise ProviderRateLimited(
                self.provider, float(retry_after) if retry_after else None
            )
        if code in (401, 403):
            PROVIDER_REQUESTS.labels(self.provider, "unauthorized").inc()
            raise ProviderError(self.provider, f"authentication failed ({code})",
                                retryable=False)
        if code == 404:
            PROVIDER_REQUESTS.labels(self.provider, "not_found").inc()
            raise ProviderError(self.provider, "not found", retryable=False)
        PROVIDER_REQUESTS.labels(self.provider, f"http_{code}").inc()
        raise ProviderUnavailable(self.provider, f"HTTP {code}")

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
