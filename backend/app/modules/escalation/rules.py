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

# Account security is handled by a different team from career counselling, and
# these messages must never be answered by the model, so they are matched on the
# way in rather than after a response has been generated.
_SECURITY_SENSITIVE = re.compile(
    r"\b(?:fraud|fraudulent|identity theft|data breach|"
    r"unauthori[sz]ed (?:access|login|use)|"
    r"account (?:was |been )?(?:hacked|compromised|stolen)|"
    r"(?:hacked|compromised) my account|"
    r"someone (?:else )?(?:has |is |was )?(?:using|accessing|logged into) my account|"
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


# What the member sees when a conversation is handed over. Each one says what
# happened and what comes next, because "escalated" on its own tells the person
# nothing useful.
ACKNOWLEDGEMENT: dict[EscalationReason, str] = {
    EscalationReason.CUSTOMER_REQUEST: (
        "Of course -- I'm connecting you with a career counsellor now. They can see "
        "this conversation, so you won't need to start over."
    ),
    EscalationReason.SECURITY_CONCERN: (
        "This looks like an account security issue, so I'm routing you straight to "
        "someone authorised to handle it. Please don't share passwords, financial "
        "account numbers or identification numbers in this chat."
    ),
    EscalationReason.UNSUPPORTED_TOPIC: (
        "That's outside what I can answer reliably, so I've passed it to a career "
        "counsellor along with what you've told me."
    ),
    EscalationReason.VALIDATION_FAILURE: (
        "I wasn't able to produce an answer I'm confident is correct, so a career "
        "counsellor will take this from here."
    ),
    EscalationReason.AI_SERVICE_FAILURE: (
        "I'm sorry -- I can't reach the assistant service right now, and I'd rather "
        "not guess at an answer about your education or career plans. I've made a "
        "career counsellor available to pick this up for you."
    ),
}
