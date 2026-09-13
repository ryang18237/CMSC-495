"""Fixed-window per-user rate limiter.

Alpha scope: the counters live in process memory, which is adequate for a
single instance. The Non-Functional Requirements call for stateless instances
behind a load balancer, so a production deployment moves these counters into
the shared cache (for example ElastiCache/Redis) without changing callers.
"""

import time
from collections import defaultdict

from app.config import get_settings
from app.errors import RateLimitError

_WINDOW_SECONDS = 60
_counters: dict[str, list[float]] = defaultdict(list)


def enforce(key: str) -> None:
    limit = get_settings().rate_limit_messages_per_minute
    now = time.monotonic()
    hits = [stamp for stamp in _counters[key] if now - stamp < _WINDOW_SECONDS]
    if len(hits) >= limit:
        _counters[key] = hits
        raise RateLimitError()
    hits.append(now)
    _counters[key] = hits


def reset() -> None:
    _counters.clear()
