"""AI Integration Module.

Owns prompt construction, the retry policy and the fallback path. The rest of
the application talks to this service and never to a provider directly.
"""

import time
from dataclasses import dataclass

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
from app.modules.ai_integration.providers.builtin import MODEL, BuiltInAdvisor
from app.modules.ai_integration.providers.ollama_provider import OllamaProvider
from app.modules.ai_integration.providers.openai_provider import OpenAIProvider

FALLBACK_MESSAGE = (
    "I'm sorry -- I can't reach the assistant service right now, and I'd rather not "
    "guess at an answer about your education or career plans. I've made a career "
    "counsellor available to pick this up for you."
)

SYSTEM_INSTRUCTION = (
    "You are the assistant for SkillBridge AI, a free education and professional "
    "development service for military members and veterans. "
    "Answer only from the knowledge base excerpts and the member facts provided "
    "below. Ground your suggestions in the training the member has already "
    "completed -- that is the point of the service. "
    "Be concise, practical and respectful. "
    "You provide information and suggestions only. You must never make an "
    "eligibility determination, promise admission, funding or employment, or state "
    "that you have taken an action such as enrolling, applying or approving "
    "anything -- a human career counsellor does those. "
    "Never ask for or repeat a password, financial account number or government "
    "identification number. "
    "If the question falls outside the provided material, or the member needs a "
    "decision you cannot make, reply with exactly UNSUPPORTED_TOPIC and nothing else."
)


# Long enough for a failure class and an HTTP status; too short to carry a
# meaningful excerpt of member content if a provider ever included one.
ERROR_DETAIL_LIMIT = 200


def shutdown() -> None:
    """Release resources held across requests. Called once, at application shutdown."""
    from app.modules.ai_integration.providers._http import reset_shared_http_client

    reset_shared_http_client()


# Every provider the platform knows, with the name a member sees. The built-in
# advisor needs no key and is therefore always available, which is what lets
# the platform be installed and used with no sign-ups and nothing to configure.
_PROVIDERS: dict[str, tuple[str, type[AIProvider]]] = {
    "builtin": ("Built-in advisor", BuiltInAdvisor),
    "ollama": ("Local model", OllamaProvider),
    "anthropic": ("Claude", AnthropicProvider),
    "openai": ("ChatGPT", OpenAIProvider),
}

# `mock` was this provider's name while it was a test double. Configuration
# files and CI still say it, so it keeps working.
_ALIASES = {"mock": "builtin", "": "builtin"}

# What "auto" tries, in order. A local model first: it is the only option that
# is both a real language model and free of keys, accounts and cost, so it is
# what someone who has configured nothing should get when their machine can
# run it. The built-in advisor is last because it always works.
_AUTO_ORDER = ("ollama", "builtin")

AUTO = "auto"


def _canonical(name: str) -> str:
    cleaned = name.strip().lower()
    return _ALIASES.get(cleaned, cleaned)


def resolve_auto() -> str:
    """The provider `auto` means on this machine, right now.

    Resolved on each call rather than at import: starting Ollama should be
    noticed without restarting the platform.
    """
    for provider_id in _AUTO_ORDER:
        _, provider_class = _PROVIDERS[provider_id]
        if provider_class().health() == "ok":
            return provider_id
    return "builtin"


def configured_provider() -> str:
    """The provider configuration asks for, with `auto` already resolved."""
    configured = _canonical(get_settings().ai_provider)
    return resolve_auto() if configured == AUTO else configured


@dataclass(frozen=True)
class ProviderOption:
    provider_id: str
    label: str
    model: str
    is_default: bool


def build_provider(name: str | None = None) -> AIProvider:
    """Provider factory. Selection is configuration, or a member's choice.

    An unknown name falls back to the built-in advisor rather than failing:
    a typo in configuration should degrade the answers, not the platform.
    """
    selected = _canonical(name) if name else configured_provider()
    if selected == AUTO:
        selected = resolve_auto()
    _, provider_class = _PROVIDERS.get(selected, _PROVIDERS["builtin"])
    return provider_class()


def _model_for(provider_id: str) -> str:
    settings = get_settings()
    return {
        "anthropic": settings.anthropic_model,
        "openai": settings.openai_model,
        "ollama": settings.ollama_model,
    }.get(provider_id, MODEL)


def available_providers() -> list[ProviderOption]:
    """Providers a member may choose: those with a key configured, plus the mock.

    Availability is decided here, on the server, from configuration. The keys
    themselves never leave the process -- a member only ever sees a name.
    """
    ready = [
        provider_id
        for provider_id, (_, provider_class) in _PROVIDERS.items()
        if provider_class().health() == "ok"
    ]
    configured = configured_provider()
    default = configured if configured in ready else "builtin"
    return [
        ProviderOption(
            provider_id=provider_id,
            label=_PROVIDERS[provider_id][0],
            model=_model_for(provider_id),
            is_default=provider_id == default,
        )
        for provider_id in ready
    ]


def is_available(provider_id: str) -> bool:
    wanted = _canonical(provider_id)
    return any(option.provider_id == wanted for option in available_providers())


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
                # A retry that starts after the budget can only finish after the
                # member has already waited too long. Hand them to a person now.
                if time.monotonic() - started >= settings.ai_retry_budget_seconds:
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
                truncated=provider_response.stop_reason == "max_tokens",
            )

        return self.handle_provider_failure(
            last_error or AIProviderError("Provider produced no response."),
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    def handle_provider_failure(self, error: AIProviderError, latency_ms: int = 0) -> AIResult:
        """Convert a provider failure into a safe, customer-facing fallback.

        Provider error text is kept in `error_detail` for server-side logging and
        is never returned to the customer.

        Invariant: `error_detail` is the failure class and HTTP status, never
        content. Today's providers only raise such messages, but a future one
        that quoted a response excerpt would write member data into the log, so
        the length is capped here where every provider passes through.
        """
        return AIResult(
            outcome=AIOutcome.PROVIDER_FAILURE,
            text=FALLBACK_MESSAGE,
            model=self._provider.name,
            sources=[],
            latency_ms=latency_ms,
            error_detail=str(error)[:ERROR_DETAIL_LIMIT],
        )
