"""Projections from stored rows onto the public response contracts.

Several routers return the same shapes -- a member's conversation, a case, a
counsellor's reply all carry `MessageView` -- so the translation lives in one
place. Before this module the routers imported a private helper from each
other, which tied the agent routes to the internals of the conversation routes.
"""

import json

from app.models import ConversationMessage, EscalationCase
from app.schemas import (
    AgentCaseSummary,
    CaseStatus,
    EscalationReason,
    MessageStatus,
    MessageView,
)


def to_message_view(message: ConversationMessage) -> MessageView:
    """Project a stored message onto the public message contract."""
    sources: list[str] = []
    if message.sources:
        try:
            sources = list(json.loads(message.sources))
        except json.JSONDecodeError:
            # A malformed sources column should never cost the member their
            # message. The answer is still shown, just without citations.
            sources = []
    return MessageView(
        message_id=message.id,
        sender=message.sender,
        content=message.content,
        status=MessageStatus(message.status) if message.status else None,
        escalation_reason=(
            EscalationReason(message.escalation_reason) if message.escalation_reason else None
        ),
        sources=sources,
        timestamp=message.created_at,
    )


def to_case_summary(case: EscalationCase) -> AgentCaseSummary:
    """Project a stored escalation case onto the queue summary contract."""
    return AgentCaseSummary(
        case_id=case.id,
        conversation_id=case.conversation_id,
        reason=EscalationReason(case.reason),
        status=CaseStatus(case.status),
        queue=case.queue,
        summary=case.summary,
        created_at=case.created_at,
    )
