"""Provider interface every AI backend must implement."""

from abc import ABC, abstractmethod

from app.config import get_settings
from app.modules.ai_integration.contracts import Prompt, ProviderResponse


class AIProvider(ABC):
    """Contract for a managed AI model provider.

    Implementations must translate a provider-neutral `Prompt` into their own
    wire format, and must raise `AIProviderError` (never a provider-specific
    exception) so the calling module can apply one retry and fallback policy.
    """

    name: str = "base"

    @abstractmethod
    def generate(self, prompt: Prompt) -> ProviderResponse:
        """Return the model's reply, or raise AIProviderError."""

    def health(self) -> str:
        """Report provider readiness: 'ok', 'degraded' or 'unavailable'."""
        return "ok"

    @property
    def retry_budget_seconds(self) -> float:
        """How long the service may keep retrying this provider.

        A property rather than one global setting because the right answer
        depends on what is at the other end. Retrying a hosted API after a
        network blip is sensible and cheap. Retrying a local model that was
        simply still thinking just makes the member wait twice.
        """
        return get_settings().ai_retry_budget_seconds
