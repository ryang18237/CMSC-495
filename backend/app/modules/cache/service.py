"""Cache (Data Layer).

ALPHA SCOPE -- barebones. The interface, the call sites and the statistics are
real; the storage is a process-local dictionary rather than the shared cache the
architecture calls for.

Why that is acceptable for now: the Non-Functional Requirements say application
instances must stay stateless so they can scale horizontally. A process-local
cache does not satisfy that, which is exactly why every caller goes through
`CacheService` instead of holding its own dictionary. Swapping in Redis or
ElastiCache means adding one implementation of this interface and selecting it
in configuration -- no caller changes.

What is deliberately NOT built yet: shared storage, eviction under memory
pressure, cache warming, and per-key invalidation on customer-data writes.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.config import get_settings


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    entries: int = 0
    evictions: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return round(self.hits / total, 3) if total else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "entries": self.entries,
            "evictions": self.evictions,
            "hitRate": self.hit_rate,
        }


class CacheService(ABC):
    """Contract every cache implementation must honour."""

    name: str = "base"

    @abstractmethod
    def get(self, key: str) -> Any | None:
        """Return the cached value, or None when absent or expired."""

    @abstractmethod
    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        """Store a value with a time to live."""

    @abstractmethod
    def invalidate(self, prefix: str) -> int:
        """Drop every key starting with `prefix`. Returns how many were removed."""

    @abstractmethod
    def stats(self) -> CacheStats:
        """Operational counters, surfaced by the monitoring endpoint."""

    def health(self) -> str:
        return "ok"


@dataclass
class _Entry:
    value: Any
    expires_at: float


class InMemoryCache(CacheService):
    """Process-local cache. Alpha stand-in for the shared cache."""

    name = "in-memory"

    def __init__(self) -> None:
        self._entries: dict[str, _Entry] = {}
        self._stats = CacheStats()

    def get(self, key: str) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            self._stats.misses += 1
            return None
        if entry.expires_at < time.monotonic():
            del self._entries[key]
            self._stats.evictions += 1
            self._stats.misses += 1
            return None
        self._stats.hits += 1
        return entry.value

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else get_settings().cache_ttl_seconds
        self._entries[key] = _Entry(value=value, expires_at=time.monotonic() + ttl)
        self._stats.entries = len(self._entries)

    def invalidate(self, prefix: str) -> int:
        doomed = [key for key in self._entries if key.startswith(prefix)]
        for key in doomed:
            del self._entries[key]
        self._stats.evictions += len(doomed)
        self._stats.entries = len(self._entries)
        return len(doomed)

    def stats(self) -> CacheStats:
        self._stats.entries = len(self._entries)
        return self._stats

    def clear(self) -> None:
        self._entries.clear()
        self._stats = CacheStats()


class NullCache(CacheService):
    """Caching disabled. Useful for tests that assert on cache-miss behaviour."""

    name = "disabled"

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any, ttl_seconds: int | None = None) -> None:
        return None

    def invalidate(self, prefix: str) -> int:
        return 0

    def stats(self) -> CacheStats:
        return CacheStats()


_cache: CacheService | None = None


def get_cache() -> CacheService:
    """Return the process-wide cache selected by configuration."""
    global _cache
    if _cache is None:
        _cache = InMemoryCache() if get_settings().cache_enabled else NullCache()
    return _cache


def reset_cache() -> None:
    global _cache
    _cache = None
