"""Response Validation Module.

Every model response passes through here before a customer can see it. The
checks are deterministic rules -- the platform deliberately does not rely on an
undefined numeric confidence score.
"""

import re
from dataclasses import dataclass, field

from app.config import get_settings
from app.modules.ai_integration.contracts import AIOutcome, AIResult
from app.schemas import EscalationReason

# Patterns that must never appear in a customer-facing response.
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD = re.compile(r"\b(?:\d[ -]?){13,16}\b")
_PROMPT_LEAK = re.compile(
    r"you are the customer service assistant|system instruction|knowledge base article --",
    re.IGNORECASE,
)
# The assistant may explain an action but must never claim to have performed one.
_ACTION_CLAIM = re.compile(
    r"\bi (?:have |'ve |has )?(?:already )?"
    r"(?:issued|processed|refunded|cancelled|canceled|reset|closed|deleted|updated) "
    r"(?:your|the|a|an) ",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    failures: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        return "; ".join(self.failures) if self.failures else "passed"


@dataclass(frozen=True)
class EscalationDecision:
    required: bool
    reason: EscalationReason | None = None
    detail: str = ""


class ResponseValidationService:
    def validate_response(self, result: AIResult) -> ValidationResult:
        if result.outcome is not AIOutcome.ANSWERED:
            # Non-answers are handled by the escalation rules, not by content checks.
            return ValidationResult(valid=True)

        failures: list[str] = []
        text = result.text.strip()
        max_length = get_settings().max_response_length

        if not text:
            failures.append("empty response")
        if len(text) > max_length:
            failures.append(f"response exceeds {max_length} characters")
        if _SSN.search(text) or _CARD.search(text):
            failures.append("response contains sensitive identifiers")
        if _PROMPT_LEAK.search(text):
            failures.append("response leaks internal instructions")
        if _ACTION_CLAIM.search(text):
            failures.append("response claims an account action the assistant cannot perform")

        return ValidationResult(valid=not failures, failures=failures)

    def requires_escalation(
        self, result: AIResult, validation: ValidationResult
    ) -> EscalationDecision:
        if result.outcome is AIOutcome.PROVIDER_FAILURE:
            return EscalationDecision(
                required=True,
                reason=EscalationReason.AI_SERVICE_FAILURE,
                detail=result.error_detail or "AI provider unavailable",
            )
        if result.outcome is AIOutcome.UNSUPPORTED:
            return EscalationDecision(
                required=True,
                reason=EscalationReason.UNSUPPORTED_TOPIC,
                detail="Assistant reported the request is outside supported material",
            )
        if not validation.valid:
            return EscalationDecision(
                required=True,
                reason=EscalationReason.VALIDATION_FAILURE,
                detail=validation.summary,
            )
        return EscalationDecision(required=False)
