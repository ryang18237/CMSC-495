"""Provider interface every AI backend must implement."""

from abc import ABC, abstractmethod

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
