"""One HTTP connection pool for every managed AI provider.

`build_provider()` constructs a new provider object per turn, so a per-instance
client would open a fresh pool (and leak sockets) on every member message.
Anthropic and OpenAI live on different hosts, and httpx keeps connections per
host inside one pool, so sharing it costs nothing and closes cleanly in one call.
"""

import threading

import httpx

_client: httpx.Client | None = None

# FastAPI runs these synchronous routes on a thread pool, so two first requests
# can arrive at once. Without the lock both see no client, both build one, and
# the loser's pool is never closed. Checked once outside the lock so the normal
# path -- a client already exists -- costs nothing.
_lock = threading.Lock()


def shared_http_client(timeout: float) -> httpx.Client:
    global _client
    client = _client
    if client is not None and not client.is_closed:
        return client
    with _lock:
        if _client is None or _client.is_closed:
            _client = httpx.Client(
                timeout=timeout,
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
            )
        return _client


def reset_shared_http_client() -> None:
    """Close the shared pool. Used by tests and by an orderly shutdown."""
    global _client
    with _lock:
        if _client is not None and not _client.is_closed:
            _client.close()
        _client = None
