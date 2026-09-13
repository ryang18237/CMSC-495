"""Managed AI model provider -- Anthropic Claude Messages API.

OWNER: Benjamin Madden (Integration Lead)
STATUS: interface stub. The class, its registration in the provider factory,
        configuration, error mapping and tests around it are already in place;
        the three TODO blocks below are the implementation work.

Why it is a stub
----------------
The Alpha ships with `MockAIProvider` selected by default so that the CI
pipeline can exercise the full conversation path with no API key and no network
egress. Setting `AI_PROVIDER=anthropic` in the environment switches the running
application to this class with no other code change -- that is the point of the
`AIProvider` interface.

Contract this class must honour
-------------------------------
1. `generate(prompt)` returns a `ProviderResponse(text, model, stop_reason)`.
2. Any failure -- HTTP error, timeout, malformed body, refusal -- must be
   raised as `AIProviderError`, never as an httpx or provider-specific
   exception. Set `retryable=False` for errors that will not succeed on retry
   (401 bad key, 400 malformed request); set `retryable=True` for 429, 5xx and
   timeouts. `AIIntegrationService` owns the retry loop and the fallback path,
   so this class must not retry internally.
3. Return the bare string `"UNSUPPORTED_TOPIC"` as the text when the model
   declines or cannot help. `ResponseValidationService` turns that into an
   `UNSUPPORTED_TOPIC` escalation. The system prompt built by
   `AIIntegrationService.build_prompt()` already instructs the model to do this.
4. Do not log prompt contents or response bodies. They may contain customer
   data, and the Design Specification requires data sent to the provider to be
   minimised.

Wire format reference (Messages API)
------------------------------------
POST {base_url}/v1/messages
Headers:
    x-api-key:         {settings.anthropic_api_key}
    anthropic-version: 2023-06-01
    content-type:      application/json
Body:
    {
      "model": settings.anthropic_model,
      "max_tokens": 1024,
      "system": prompt.system,
      "messages": prompt.messages           # already [{"role","content"}, ...]
    }
Success body:
    {"content": [{"type": "text", "text": "..."}], "model": "...",
     "stop_reason": "end_turn", "usage": {...}}

`prompt.messages` is already in the shape the API expects, with alternating
user/assistant roles and the newest customer turn last. `prompt.system` is a
plain string. No transformation should be needed beyond assembling the body.

Verifying your work
-------------------
    cp backend/.env.example backend/.env      # then set ANTHROPIC_API_KEY
    AI_PROVIDER=anthropic uvicorn app.main:app --reload --app-dir backend
    pytest backend/tests -k provider

Never commit an API key. `.env` is git-ignored; CI reads the key from a GitHub
Actions secret and the pipeline keeps `AI_PROVIDER=mock` regardless.
"""

import httpx

from app.config import get_settings
from app.modules.ai_integration.contracts import AIProviderError, Prompt, ProviderResponse
from app.modules.ai_integration.providers.base import AIProvider

ANTHROPIC_VERSION = "2023-06-01"
MAX_TOKENS = 1024


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.anthropic_api_key
        self._model = settings.anthropic_model
        self._base_url = settings.anthropic_base_url.rstrip("/")
        self._timeout = settings.ai_timeout_seconds

    def health(self) -> str:
        """Configuration-level readiness check. Performs no network call."""
        if not self._api_key:
            return "unavailable"
        return "ok"

    def generate(self, prompt: Prompt) -> ProviderResponse:
        if not self._api_key:
            raise AIProviderError(
                "ANTHROPIC_API_KEY is not configured.",
                retryable=False,
            )

        # ------------------------------------------------------------------
        # TODO(Benjamin) 1 -- build the request body.
        #   body = {
        #       "model": self._model,
        #       "max_tokens": MAX_TOKENS,
        #       "system": prompt.system,
        #       "messages": prompt.messages,
        #   }
        # ------------------------------------------------------------------

        # ------------------------------------------------------------------
        # TODO(Benjamin) 2 -- send it and map transport failures.
        #   try:
        #       with httpx.Client(timeout=self._timeout) as client:
        #           response = client.post(
        #               f"{self._base_url}/v1/messages",
        #               headers={
        #                   "x-api-key": self._api_key,
        #                   "anthropic-version": ANTHROPIC_VERSION,
        #                   "content-type": "application/json",
        #               },
        #               json=body,
        #           )
        #   except httpx.TimeoutException as exc:
        #       raise AIProviderError("Provider timed out.", retryable=True) from exc
        #   except httpx.HTTPError as exc:
        #       raise AIProviderError("Provider transport error.", retryable=True) from exc
        #
        #   if response.status_code in (401, 403):
        #       raise AIProviderError("Provider rejected the credentials.", retryable=False)
        #   if response.status_code == 400:
        #       raise AIProviderError("Provider rejected the request.", retryable=False)
        #   if response.status_code >= 429:
        #       raise AIProviderError(
        #           f"Provider returned {response.status_code}.", retryable=True
        #       )
        # ------------------------------------------------------------------

        # ------------------------------------------------------------------
        # TODO(Benjamin) 3 -- parse the body into a ProviderResponse.
        #   payload = response.json()
        #   blocks = [b for b in payload.get("content", []) if b.get("type") == "text"]
        #   text = "".join(b.get("text", "") for b in blocks).strip()
        #   if not text:
        #       raise AIProviderError("Provider returned an empty response.", retryable=True)
        #   return ProviderResponse(
        #       text=text,
        #       model=payload.get("model", self._model),
        #       stop_reason=payload.get("stop_reason"),
        #   )
        # ------------------------------------------------------------------

        raise NotImplementedError(
            "AnthropicProvider.generate is the Integration Lead's deliverable. "
            "Run with AI_PROVIDER=mock until it is implemented."
        )


# Keeps the import referenced while the body is stubbed; delete once implemented.
_HTTPX_CLIENT_FACTORY = httpx.Client
