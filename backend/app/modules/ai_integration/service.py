"""AI Integration Module.

Owns prompt construction, the retry policy and the fallback path. The rest of
the application talks to this service and never to a provider directly.
"""

import time

from app.config import get_settings
from app.modules.ai_integration.contracts import (
    AIOutcome,
    AIProviderError,
    AIResult,
    ChatContext,
    Prompt,
)
from app.modules.ai_integration.providers.anthropic_provider import AnthropicProvider
from app.modules.ai_integration.providers.base import AIProvider
from app.modules.ai_integration.providers.mock import MockAIProvider

FALLBACK_MESSAGE = (
    "I'm sorry -- I can't reach our assistant service right now, so I don't want to "
    "guess at an answer. I've made a human support specialist available to pick this "
    "up for you."
)

SYSTEM_INSTRUCTION = (
    "You are the customer service assistant for an online retailer. "
    "Answer only from the knowledge base excerpts and account facts provided below. "
    "Be concise, accurate and courteous. "
    "You may explain policy and status, but you must never state that you have "
    "taken an account action such as issuing a refund, cancelling an order or "
    "changing a password -- a human specialist performs those. "
    "Never ask for or repeat a password, full payment card number or government "
    "identification number. "
    "If the question is outside the provided material, or the customer needs an "
    "action you cannot explain, reply with exactly UNSUPPORTED_TOPIC and nothing else."
)


def build_provider(name: str | None = None) -> AIProvider:
    """Provider factory. Selection is configuration, not code."""
    selected = (name or get_settings().ai_provider).strip().lower()
    if selected == "anthropic":
        return AnthropicProvider()
    return MockAIProvider()


class AIIntegrationService:
    def __init__(self, provider: AIProvider | None = None) -> None:
        self._provider = provider or build_provider()

    @property
    def provider_name(self) -> str:
        return self._provider.name

    def provider_health(self) -> str:
        try:
            return self._provider.health()
        except Exception:  # pragma: no cover - health must never raise upward
            return "unavailable"

    def build_prompt(self, context: ChatContext) -> Prompt:
        """Assemble a provider-neutral prompt containing the minimum data needed."""
        sections: list[str] = [SYSTEM_INSTRUCTION]

        if context.customer_facts:
            facts = "\n".join(f"- {fact}" for fact in context.customer_facts)
            sections.append(f"Account facts you may reference:\n{facts}")

        for title, body in context.knowledge_snippets:
            excerpt = body if len(body) <= 700 else body[:700].rstrip() + "..."
            sections.append(f"Knowledge base article -- {title}:\n{excerpt}")

        messages: list[dict[str, str]] = []
        for role, content in context.history[-6:]:
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": context.customer_message})

        return Prompt(system="\n\n".join(sections), messages=messages)

    def generate_response(self, context: ChatContext) -> AIResult:
        """Call the provider with a bounded retry policy for transient failures."""
        settings = get_settings()
        prompt = self.build_prompt(context)
        sources = [title for title, _ in context.knowledge_snippets]
        started = time.monotonic()
        last_error: AIProviderError | None = None

        for attempt in range(settings.ai_max_retries + 1):
            try:
                provider_response = self._provider.generate(prompt)
            except AIProviderError as exc:
                last_error = exc
                if not exc.retryable or attempt == settings.ai_max_retries:
                    break
                time.sleep(min(0.2 * (2**attempt), 1.0))
                continue
            except NotImplementedError as exc:
                last_error = AIProviderError(str(exc), retryable=False)
                break
            except Exception as exc:  # provider raised something undocumented
                last_error = AIProviderError(f"Unexpected provider error: {exc}", retryable=False)
                break

            elapsed_ms = int((time.monotonic() - started) * 1000)
            text = provider_response.text.strip()
            outcome = AIOutcome.UNSUPPORTED if text == "UNSUPPORTED_TOPIC" else AIOutcome.ANSWERED
            return AIResult(
                outcome=outcome,
                text=text,
                model=provider_response.model,
                sources=sources,
                latency_ms=elapsed_ms,
            )

        return self.handle_provider_failure(
            last_error or AIProviderError("Provider produced no response."),
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    def handle_provider_failure(self, error: AIProviderError, latency_ms: int = 0) -> AIResult:
        """Convert a provider failure into a safe, customer-facing fallback.

        Provider error text is kept in `error_detail` for server-side logging and
        is never returned to the customer.
        """
        return AIResult(
            outcome=AIOutcome.PROVIDER_FAILURE,
            text=FALLBACK_MESSAGE,
            model=self._provider.name,
            sources=[],
            latency_ms=latency_ms,
            error_detail=str(error),
        )
