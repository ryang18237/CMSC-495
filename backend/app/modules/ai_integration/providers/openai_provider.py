"""Managed AI model provider -- OpenAI Chat Completions (ChatGPT models).

OWNER: Benjamin Madden (Integration Lead)

A second managed provider behind the same `AIProvider` interface, so a member
can choose ChatGPT instead of Claude. Everything that makes the Anthropic
provider safe applies here unchanged, because it lives in the service rather
than the provider: prompt minimisation, the retry budget, response validation
and the fallback to a counsellor.

Selecting it is configuration:

    OPENAI_API_KEY=sk-...
    OPENAI_MODEL=gpt-6-luna

With no key the provider reports `unavailable` and is not offered to members.

Contract (identical to AnthropicProvider)
-----------------------------------------
- Returns a `ProviderResponse`, or raises `AIProviderError` with `retryable`
  set. Never raises an httpx exception, never retries itself.
- A response cut off at the token limit comes back with stop_reason
  "max_tokens" -- OpenAI calls it "length" -- so Response Validation rejects it
  the same way whichever provider produced it.
- Prompt and response bodies are never logged; error messages carry only the
  failure class and HTTP status.
"""

import httpx

from app.config import get_settings
from app.modules.ai_integration.contracts import AIProviderError, Prompt, ProviderResponse
from app.modules.ai_integration.providers._http import shared_http_client
from app.modules.ai_integration.providers.base import AIProvider

# Same ceiling as the Anthropic provider, for the same reason: it is coupled to
# `max_response_length` in config.py.
MAX_TOKENS = 1024
UNSUPPORTED_MARKER = "UNSUPPORTED_TOPIC"
_MARKER_TRIM = " \t\n\r.!\"'*`"


class OpenAIProvider(AIProvider):
    name = "openai"

    # OpenAI renamed the cap to `max_completion_tokens` and rejects the old
    # name on its newer models. Other servers that speak this wire format did
    # not follow, and an unrecognised field is *ignored* rather than refused --
    # so naming it wrongly does not fail loudly, it silently removes the cap
    # and lets a reply run until the model stops on its own. Each provider
    # names the field its own server reads.
    token_limit_field = "max_completion_tokens"

    def __init__(self, client: httpx.Client | None = None) -> None:
        settings = get_settings()
        self._api_key = settings.openai_api_key
        self._model = settings.openai_model
        self._base_url = settings.openai_base_url.rstrip("/")
        self._timeout = settings.ai_timeout_seconds
        self._client = client  # injected only by tests

    def health(self) -> str:
        return "ok" if self._api_key else "unavailable"

    def generate(self, prompt: Prompt) -> ProviderResponse:
        if not self._api_key:
            raise AIProviderError("OPENAI_API_KEY is not configured.", retryable=False)
        response = self._post(self._build_body(prompt))
        self._raise_for_status(response.status_code)
        return self._parse(response)

    def _build_body(self, prompt: Prompt) -> dict[str, object]:
        """Chat Completions takes the system prompt as the first message.

        Nothing is added that the provider-neutral prompt did not carry.
        """
        return {
            "model": self._model,
            self.token_limit_field: MAX_TOKENS,
            "messages": [{"role": "system", "content": prompt.system}, *prompt.messages],
        }

    def _post(self, body: dict[str, object]) -> httpx.Response:
        client = self._client or shared_http_client(self._timeout)
        try:
            return client.post(
                f"{self._base_url}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self._api_key}",
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
        if status_code < 400:
            return
        if status_code in (401, 403):
            raise AIProviderError("Provider rejected the credentials.", retryable=False)
        if status_code in (400, 404, 413, 422):
            raise AIProviderError(
                f"Provider rejected the request ({status_code}).", retryable=False
            )
        if status_code == 429 or status_code >= 500:
            raise AIProviderError(f"Provider returned {status_code}.", retryable=True)
        raise AIProviderError(f"Provider returned {status_code}.", retryable=False)

    @staticmethod
    def _first_choice(payload: object) -> dict[str, object]:
        choices = payload.get("choices") if isinstance(payload, dict) else None
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise AIProviderError("Provider response had no choices.", retryable=True)
        return choices[0]

    @staticmethod
    def _text_of(choice: dict[str, object]) -> str:
        raw_message = choice.get("message")
        message: dict[str, object] = raw_message if isinstance(raw_message, dict) else {}
        text = str(message.get("content") or "").strip()
        # A refusal is the model declining, which is exactly what the
        # UNSUPPORTED_TOPIC marker means to the rest of the platform.
        if not text and message.get("refusal"):
            return UNSUPPORTED_MARKER
        # A reasoning model can put the whole answer in `reasoning` and leave
        # `content` empty. Throwing that away and escalating would hand a
        # member to a counsellor while holding the answer they asked for.
        if not text:
            text = str(message.get("reasoning") or message.get("reasoning_content") or "").strip()
        if not text:
            raise AIProviderError("Provider returned an empty response.", retryable=True)
        if text.strip(_MARKER_TRIM).upper() == UNSUPPORTED_MARKER:
            return UNSUPPORTED_MARKER
        return text

    def _parse(self, response: httpx.Response) -> ProviderResponse:
        try:
            payload = response.json()
        except ValueError as exc:
            raise AIProviderError("Provider returned a non-JSON body.", retryable=True) from exc

        choice = self._first_choice(payload)
        finish = choice.get("finish_reason")
        # OpenAI says "length" where Anthropic says "max_tokens"; the rest of the
        # platform only knows the latter.
        stop_reason = "max_tokens" if finish == "length" else (str(finish) if finish else None)
        return ProviderResponse(
            text=self._text_of(choice),
            model=str(payload.get("model") or self._model),
            stop_reason=stop_reason,
        )
