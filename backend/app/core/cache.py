"""Cache abstraction.

In-process TTL cache by default (zero dependencies, correct for a single
instance). ``RedisCache`` implements the same protocol for multi-instance
deployments — callers never learn which one they got.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Protocol

from cachetools import TTLCache


class Cache(Protocol):
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl: int) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def clear(self) -> None: ...


class MemoryCache:
    """Thread/task-safe TTL cache.

    ``cachetools.TTLCache`` uses a single expiry per store, so we keep one
    store per distinct TTL. That keeps semantics exact instead of approximate.
    """

    def __init__(self, maxsize: int = 2048) -> None:
        self._maxsize = maxsize
        self._stores: dict[int, TTLCache] = {}
        self._lock = asyncio.Lock()

    def _store(self, ttl: int) -> TTLCache:
        store = self._stores.get(ttl)
        if store is None:
            store = TTLCache(maxsize=self._maxsize, ttl=ttl)
            self._stores[ttl] = store
        return store

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            for store in self._stores.values():
                if key in store:
                    return store[key]
        return None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        async with self._lock:
            for t, store in self._stores.items():
                if t != ttl:
                    store.pop(key, None)
            self._store(ttl)[key] = value

    async def delete(self, key: str) -> None:
        async with self._lock:
            for store in self._stores.values():
                store.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            for store in self._stores.values():
                store.clear()


class RedisCache:
    """Redis-backed cache. Values are JSON-encoded."""

    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis  # imported lazily: optional dependency

        self._redis = aioredis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> Any | None:
        raw = await self._redis.get(key)
        return None if raw is None else json.loads(raw)

    async def set(self, key: str, value: Any, ttl: int) -> None:
        await self._redis.set(key, json.dumps(value, default=str), ex=ttl)

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)

    async def clear(self) -> None:
        await self._redis.flushdb()


def build_cache(backend: str, redis_url: str | None) -> Cache:
    if backend == "redis":
        if not redis_url:
            raise ValueError("cache_backend='redis' requires redis_url")
        return RedisCache(redis_url)
    return MemoryCache()
