"""Managed AI model provider -- Anthropic Claude Messages API.

OWNER: Benjamin Madden (Integration Lead)

Selecting this provider is configuration, not code:

    AI_PROVIDER=anthropic
    ANTHROPIC_API_KEY=sk-ant-...
    ANTHROPIC_MODEL=claude-sonnet-4-5

With `AI_PROVIDER=mock` (the default, and what CI uses) this module is never
called, so the pipeline needs no API key and makes no paid requests.

Contract
--------
`generate(prompt)` returns a `ProviderResponse`, or raises `AIProviderError`.
It never raises an httpx exception and never retries internally --
`AIIntegrationService` owns the retry policy and the customer-facing fallback,
so retrying here would multiply the request count.

`retryable=True` marks failures worth another attempt (timeout, transport
error, 429, 5xx). `retryable=False` marks failures that will fail again the
same way (missing or rejected key, malformed request, truncated output).

Privacy
-------
Prompt and response bodies are never logged. They may contain customer data,
and the Design Specification requires data sent to the provider to be
minimised. Error messages raised from here describe the failure class and the
HTTP status only; they never include request or response content.
"""

import httpx

from app.config import get_settings
from app.modules.ai_integration.contracts import AIProviderError, Prompt, ProviderResponse
from app.modules.ai_integration.providers.base import AIProvider

ANTHROPIC_VERSION = "2023-06-01"
MAX_TOKENS = 1024
UNSUPPORTED_MARKER = "UNSUPPORTED_TOPIC"

# Characters a model may add around the marker when it declines.
_MARKER_TRIM = " \t\n\r.!\"'*`"

# One connection pool is shared across requests. `build_provider()` constructs a
# new provider object per turn, so a per-instance client would open a fresh
# pool (and leak sockets) on every customer message.
_shared_client: httpx.Client | None = None


def _shared_http_client(timeout: float) -> httpx.Client:
    global _shared_client
    if _shared_client is None or _shared_client.is_closed:
        _shared_client = httpx.Client(
            timeout=timeout,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=10),
        )
    return _shared_client


def reset_shared_client() -> None:
    """Close the shared pool. Used by tests and by an orderly shutdown."""
    global _shared_client
    if _shared_client is not None and not _shared_client.is_closed:
        _shared_client.close()
    _shared_client = None


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, client: httpx.Client | None = None) -> None:
        settings = get_settings()
        self._api_key = settings.anthropic_api_key
        self._model = settings.anthropic_model
        self._base_url = settings.anthropic_base_url.rstrip("/")
        self._timeout = settings.ai_timeout_seconds
        # Injected only by tests; production uses the shared pool.
        self._client = client

    # ------------------------------------------------------------------
    # Readiness
    # ------------------------------------------------------------------
    def health(self) -> str:
        """Configuration-level readiness. Performs no network call.

        A missing key makes /api/v1/health report `degraded` rather than
        failing: the platform still answers, and AI calls escalate instead.
        """
        if not self._api_key:
            return "unavailable"
        return "ok"

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    def generate(self, prompt: Prompt) -> ProviderResponse:
        if not self._api_key:
            raise AIProviderError("ANTHROPIC_API_KEY is not configured.", retryable=False)

        response = self._post(self._build_body(prompt))
        self._raise_for_status(response.status_code)
        return self._parse(response)

    def _build_body(self, prompt: Prompt) -> dict[str, object]:
        """Map the provider-neutral prompt onto the Messages API request.

        `prompt.messages` is already `[{"role", "content"}, ...]` with
        alternating roles and the newest customer turn last, so it passes
        through unchanged. Widening this body would widen what leaves the
        platform, so nothing is added here that the prompt did not carry.
        """
        return {
            "model": self._model,
            "max_tokens": MAX_TOKENS,
            "system": prompt.system,
            "messages": prompt.messages,
        }

    def _post(self, body: dict[str, object]) -> httpx.Response:
        client = self._client or _shared_http_client(self._timeout)
        try:
            return client.post(
                f"{self._base_url}/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                json=body,
                timeout=self._timeout,
            )
        except httpx.TimeoutException as exc:
            raise AIProviderError(
                f"Provider did not respond within {self._timeout:.0f}s.", retryable=True
            ) from exc
        except httpx.HTTPError as exc:
            raise AIProviderError(
                f"Provider transport failure ({type(exc).__name__}).", retryable=True
            ) from exc

    @staticmethod
    def _raise_for_status(status_code: int) -> None:
        """Map HTTP status onto the retry policy. Response bodies are not read."""
        if status_code < 400:
            return

        if status_code in (401, 403):
            raise AIProviderError("Provider rejected the credentials.", retryable=False)
        if status_code == 400:
            raise AIProviderError("Provider rejected the request as malformed.", retryable=False)
        if status_code == 404:
            raise AIProviderError("Provider endpoint or model was not found.", retryable=False)
        if status_code == 413:
            raise AIProviderError("Prompt exceeded the provider's size limit.", retryable=False)
        if status_code == 429 or status_code >= 500:
            raise AIProviderError(f"Provider returned {status_code}.", retryable=True)

        raise AIProviderError(f"Provider returned {status_code}.", retryable=False)

    def _parse(self, response: httpx.Response) -> ProviderResponse:
        try:
            payload = response.json()
        except ValueError as exc:
            raise AIProviderError("Provider returned a non-JSON body.", retryable=True) from exc

        if not isinstance(payload, dict):
            raise AIProviderError("Provider returned an unexpected body.", retryable=True)

        stop_reason = payload.get("stop_reason")
        model = str(payload.get("model") or self._model)

        blocks = payload.get("content")
        if not isinstance(blocks, list):
            raise AIProviderError("Provider response had no content array.", retryable=True)

        text = "".join(
            str(block.get("text", ""))
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()

        if not text:
            raise AIProviderError("Provider returned an empty response.", retryable=True)

        # A response cut off at the token limit ends mid-sentence. It would
        # otherwise pass response validation and reach the customer truncated,
        # so it is treated as a failure and handed to a human instead.
        #
        # FOLLOW-UP: this currently surfaces to the customer as
        # AI_SERVICE_FAILURE, which is not strictly accurate. A dedicated
        # escalation reason (or reusing VALIDATION_FAILURE) would describe it
        # better, but that changes the approved enumeration in the interface
        # contract, so it belongs in a separate change with Ryan.
        if stop_reason == "max_tokens":
            raise AIProviderError(
                f"Provider response was truncated at {MAX_TOKENS} tokens.", retryable=False
            )

        return ProviderResponse(
            text=self._normalise_marker(text),
            model=model,
            stop_reason=str(stop_reason) if stop_reason is not None else None,
        )

    @staticmethod
    def _normalise_marker(text: str) -> str:
        """Recognise the decline marker even when the model dresses it up.

        The system prompt asks for exactly `UNSUPPORTED_TOPIC`, but a model may
        return `"UNSUPPORTED_TOPIC."` or `**UNSUPPORTED_TOPIC**`. Without this,
        the reply would be treated as a real answer and shown to the customer.
        """
        if text.strip(_MARKER_TRIM).upper() == UNSUPPORTED_MARKER:
            return UNSUPPORTED_MARKER
        return text
