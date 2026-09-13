"""Deterministic provider used for local development, CI and demos.

Requires no network access and no API key, which is what lets the CI pipeline
exercise the full conversation path on every push. It follows exactly the same
contract as a managed provider, so swapping in the real one changes no caller.
"""

from app.modules.ai_integration.contracts import AIProviderError, Prompt, ProviderResponse
from app.modules.ai_integration.providers.base import AIProvider

# Deterministic trigger strings, used by the automated tests to drive the
# provider-failure and unsupported-topic branches without patching internals.
FAILURE_TRIGGER = "__force_ai_failure__"
UNSUPPORTED_MARKER = "UNSUPPORTED_TOPIC"

_TOPIC_REPLIES: list[tuple[tuple[str, ...], str]] = [
    (
        ("charge", "charged", "billing", "invoice", "refund", "payment"),
        "I can help you review that charge. Duplicate authorisations usually clear on "
        "their own within three to five business days. If the second charge has already "
        "settled rather than being a pending authorisation, a support specialist can "
        "start a refund for you.",
    ),
    (
        ("order", "delivery", "shipment", "shipping", "tracking"),
        "I can help with your order. Tracking details update once the carrier scans the "
        "parcel, which is normally within one business day of dispatch. If the tracking "
        "number has not moved in three days, we can open a carrier trace.",
    ),
    (
        ("password", "sign in", "signin", "log in", "login", "locked"),
        "I can help you get back into your account. Use the 'Forgot password' link on the "
        "sign-in page and a reset email will arrive within a few minutes. For security I "
        "cannot read or set a password for you.",
    ),
    (
        ("cancel", "subscription", "plan", "upgrade", "downgrade"),
        "I can explain how plan changes work. Upgrades take effect immediately and are "
        "prorated, while cancellations take effect at the end of the current billing "
        "period. A specialist can process the change on your account.",
    ),
    (
        ("return", "exchange", "damaged", "broken"),
        "I can walk you through a return. Items can be returned within 30 days of "
        "delivery in their original packaging, and a prepaid label is issued once the "
        "return is approved.",
    ),
]


class MockAIProvider(AIProvider):
    name = "mock"

    def generate(self, prompt: Prompt) -> ProviderResponse:
        last_user_turn = ""
        for message in reversed(prompt.messages):
            if message.get("role") == "user":
                last_user_turn = message.get("content", "")
                break

        lowered = last_user_turn.lower()

        if FAILURE_TRIGGER in lowered:
            raise AIProviderError("Simulated provider outage.", retryable=True)

        for keywords, reply in _TOPIC_REPLIES:
            if any(keyword in lowered for keyword in keywords):
                grounding = self._grounding(prompt)
                return ProviderResponse(
                    text=reply + grounding, model="mock-support-v1", stop_reason="end_turn"
                )

        return ProviderResponse(
            text=UNSUPPORTED_MARKER, model="mock-support-v1", stop_reason="end_turn"
        )

    @staticmethod
    def _grounding(prompt: Prompt) -> str:
        """Mirror how a real model grounds an answer in retrieved articles."""
        if "Knowledge base article" in prompt.system:
            return " This is based on our published support policy."
        return ""
