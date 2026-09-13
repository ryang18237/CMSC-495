"""Data contracts for the AI Integration Module.

These types are the boundary between the core application and any model
provider. Nothing outside this module imports a provider SDK, so the provider
can be swapped without touching conversation handling.
"""

from dataclasses import dataclass, field
from enum import Enum


class AIOutcome(str, Enum):
    ANSWERED = "ANSWERED"
    UNSUPPORTED = "UNSUPPORTED"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"


@dataclass(frozen=True)
class ChatContext:
    """Everything the AI module is permitted to see for one turn."""

    conversation_id: str
    inquiry_type: str
    customer_message: str
    history: list[tuple[str, str]] = field(default_factory=list)
    customer_facts: list[str] = field(default_factory=list)
    knowledge_snippets: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class Prompt:
    """Provider-neutral prompt: a system instruction plus ordered turns."""

    system: str
    messages: list[dict[str, str]]

    def token_estimate(self) -> int:
        text = self.system + " ".join(message.get("content", "") for message in self.messages)
        return max(1, len(text) // 4)


@dataclass(frozen=True)
class ProviderResponse:
    """Raw provider output, before validation."""

    text: str
    model: str
    stop_reason: str | None = None


@dataclass(frozen=True)
class AIResult:
    """Normalised result handed back to the Conversation Management Module."""

    outcome: AIOutcome
    text: str
    model: str
    sources: list[str] = field(default_factory=list)
    latency_ms: int = 0
    error_detail: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.outcome is AIOutcome.ANSWERED


class AIProviderError(RuntimeError):
    """Raised by a provider when it cannot produce a usable response."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable
