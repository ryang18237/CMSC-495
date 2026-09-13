"""Deterministic escalation rules applied to the inbound customer message.

These run *before* the AI Integration Module so that a security-sensitive
message or an explicit request for a person never reaches the model at all.
"""

import re

from app.schemas import EscalationReason

_HUMAN_REQUEST = re.compile(
    r"\b(?:speak|talk|connect|transfer|escalate)\b[^.?!]{0,30}\b"
    r"(?:human|person|agent|representative|rep|someone|manager|supervisor)\b"
    r"|\breal person\b|\blive agent\b|\bhuman being\b",
    re.IGNORECASE,
)

_SECURITY_SENSITIVE = re.compile(
    r"\b(?:fraud|fraudulent|unauthori[sz]ed charge|identity theft|stolen card|"
    r"account (?:was )?hacked|hacked my account|data breach|"
    r"social security number|ssn)\b",
    re.IGNORECASE,
)

# A message containing raw sensitive identifiers must not be forwarded either.
_RAW_IDENTIFIER = re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b(?:\d[ -]?){15,16}\b")


def detect_pre_ai_reason(message: str) -> EscalationReason | None:
    """Return an escalation reason if the message must bypass the AI, else None."""
    if _SECURITY_SENSITIVE.search(message) or _RAW_IDENTIFIER.search(message):
        return EscalationReason.SECURITY_CONCERN
    if _HUMAN_REQUEST.search(message):
        return EscalationReason.CUSTOMER_REQUEST
    return None


ACKNOWLEDGEMENT: dict[EscalationReason, str] = {
    EscalationReason.CUSTOMER_REQUEST: (
        "Of course -- I'm connecting you with a human support specialist now. "
        "They can see this conversation, so you won't need to repeat yourself."
    ),
    EscalationReason.SECURITY_CONCERN: (
        "This looks like a security-sensitive issue, so I'm routing you straight to a "
        "specialist who is authorised to handle it. Please don't share passwords, full "
        "card numbers or identification numbers in this chat."
    ),
    EscalationReason.UNSUPPORTED_TOPIC: (
        "That's outside what I can answer reliably, so I've passed it to a human "
        "specialist along with the details you've given me."
    ),
    EscalationReason.VALIDATION_FAILURE: (
        "I wasn't able to produce an answer I'm confident is correct, so a human "
        "specialist will take this from here."
    ),
    EscalationReason.AI_SERVICE_FAILURE: (
        "I'm sorry -- I can't reach our assistant service right now, so I don't want to "
        "guess at an answer. I've made a human support specialist available to pick this "
        "up for you."
    ),
}
