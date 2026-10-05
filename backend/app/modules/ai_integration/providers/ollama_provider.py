"""Local model provider -- Ollama on the member's own machine.

OWNER: Benjamin Madden (Integration Lead)

The point of this provider is that nobody has to sign up for anything. Ollama
runs a model on the same machine as the platform and exposes an
OpenAI-compatible endpoint, so a real language model answers the member's
questions with no API key, no account, no per-token cost and no part of their
record leaving the computer. That last point matters here more than it would
elsewhere: the facts in a prompt are a veteran's service record.

Because the wire format is OpenAI's, this subclasses `OpenAIProvider` and
changes only what differs:

- There is no credential. Ollama requires the `Authorization` header to be
  present and then ignores it, so a constant stands in for a key.
- Readiness is a question about the machine, not about configuration. The
  provider is offered only when the daemon answers *and* the configured model
  is actually pulled -- offering a model that is not installed would turn
  every conversation into a 404.

Selecting it is configuration, or nothing at all:

    AI_PROVIDER=auto      # the default: this provider when it is running
    OLLAMA_MODEL=llama3.2

See ADR 0011.
"""

import time

import httpx

from app.config import get_settings
from app.modules.ai_integration.providers._http import shared_http_client
from app.modules.ai_integration.providers.openai_provider import OpenAIProvider

# Ollama documents the Authorization header as "required but ignored".
PLACEHOLDER_KEY = "ollama"

# `available_providers()` is consulted on every conversation turn and on every
# load of the model picker, so the readiness probe is cached briefly. Five
# seconds is long enough to keep a burst of requests down to one probe, and
# short enough that starting Ollama is noticed without a restart.
_PROBE_TTL_SECONDS = 5.0

# (base_url, model) -> (checked_at, status)
_probe_cache: dict[tuple[str, str], tuple[float, str]] = {}


def reset_probe_cache() -> None:
    """Forget what we know about the daemon. For tests, and for `run.py`."""
    _probe_cache.clear()


class OllamaProvider(OpenAIProvider):
    name = "ollama"

    # Ollama's OpenAI shim reads `max_tokens`, not OpenAI's newer
    # `max_completion_tokens`, and ignores fields it does not know rather than
    # rejecting them. Sent under the wrong name the cap simply vanishes: the
    # reply runs to the model's own `num_predict` default of 4096 tokens,
    # which on a CPU is minutes of generation for a question that wanted a
    # paragraph -- so the turn times out and the member is escalated instead
    # of answered. The symptom is a dead assistant; the cause is one key name.
    token_limit_field = "max_tokens"

    def __init__(self, client: httpx.Client | None = None) -> None:
        super().__init__(client=client)
        settings = get_settings()
        self._api_key = PLACEHOLDER_KEY
        self._model = settings.ollama_model
        self._base_url = settings.ollama_base_url.rstrip("/")
        self._timeout = settings.ollama_timeout_seconds

    @property
    def retry_budget_seconds(self) -> float:
        """Never retry. A slow answer is not a transient failure.

        The failures a retry exists to paper over -- a dropped connection, a
        429, a 503 -- barely happen against localhost. What does happen is
        that generation takes longer than the timeout, and retrying that only
        makes the member wait for a second long answer before being handed to
        a counsellor anyway.
        """
        return 0.0

    def health(self) -> str:
        """'ok' only when the daemon is up and the model is pulled."""
        key = (self._base_url, self._model)
        cached = _probe_cache.get(key)
        now = time.monotonic()
        if cached and now - cached[0] < _PROBE_TTL_SECONDS:
            return cached[1]

        status = self._probe()
        _probe_cache[key] = (now, status)
        return status

    def _probe(self) -> str:
        """Ask the daemon which models it has.

        A short timeout on purpose: this runs on the request path, and the
        answer either comes back from localhost immediately or the daemon is
        not there. Any failure is reported as unavailable rather than raised,
        because a provider that cannot be reached is simply one a member is
        not offered.
        """
        client = self._client or shared_http_client(self._timeout)
        try:
            response = client.get(f"{self._base_url}/v1/models", timeout=2.0)
            if response.status_code >= 400:
                return "unavailable"
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return "unavailable"

        return "ok" if self._model in installed_models(payload) else "degraded"


def installed_models(payload: object) -> set[str]:
    """Model ids from a /v1/models body, with Ollama's ':latest' suffix folded in.

    `ollama pull llama3.2` installs a model the API lists as "llama3.2:latest",
    and a member who wrote `OLLAMA_MODEL=llama3.2` means that one.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return set()

    names: set[str] = set()
    for entry in data:
        if not isinstance(entry, dict):
            continue
        model_id = str(entry.get("id") or "")
        if not model_id:
            continue
        names.add(model_id)
        names.add(model_id.removesuffix(":latest"))
    return names
