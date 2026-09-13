"""Conversation Management Module.

Orchestrates one customer turn: authorization, deterministic escalation rules,
customer context retrieval, knowledge retrieval, AI generation, response
validation and persistence. It is the only module that coordinates the others.
"""

import json
import logging
import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from app.models import Conversation, ConversationMessage
from app.modules.ai_integration.contracts import AIOutcome, AIResult, ChatContext
from app.modules.ai_integration.service import AIIntegrationService
from app.modules.customer_data.adapter import CustomerDataAdapter, classify_inquiry
from app.modules.escalation.rules import ACKNOWLEDGEMENT, detect_pre_ai_reason
from app.modules.escalation.service import EscalationService
from app.modules.knowledge.service import KnowledgeBaseService
from app.modules.validation.service import ResponseValidationService
from app.schemas import ChatResponse, EscalationReason, MessageStatus

logger = logging.getLogger("app.conversation")

RESPONSE_TARGET_SECONDS = 5.0


class ConversationService:
    """Coordinates a customer turn across the core modules."""

    def __init__(
        self,
        db: Session,
        ai_service: AIIntegrationService | None = None,
    ) -> None:
        self._db = db
        self._ai = ai_service or AIIntegrationService()
        self._customers = CustomerDataAdapter(db)
        self._knowledge = KnowledgeBaseService(db)
        self._validation = ResponseValidationService()
        self._escalation = EscalationService(db)

    # ------------------------------------------------------------------
    # Conversation lifecycle
    # ------------------------------------------------------------------
    def create_conversation(self, user_id: uuid.UUID) -> Conversation:
        conversation = Conversation(user_id=user_id, status="ACTIVE")
        self._db.add(conversation)
        self._db.flush()
        return conversation

    def get_conversation(self, conversation_id: uuid.UUID, user_id: uuid.UUID) -> Conversation:
        """Load a conversation, enforcing ownership.

        Authorization is decided from the authenticated user only; a
        client-supplied identifier is never consulted.
        """
        conversation = self._db.get(Conversation, conversation_id)
        if conversation is None:
            raise NotFoundError("Conversation not found.", code="CONVERSATION_NOT_FOUND")
        if conversation.user_id != user_id:
            raise ForbiddenError("You do not have access to this conversation.")
        return conversation

    def save_message(
        self,
        conversation_id: uuid.UUID,
        sender: str,
        content: str,
        *,
        status: str | None = None,
        escalation_reason: str | None = None,
        sources: list[str] | None = None,
    ) -> ConversationMessage:
        message = ConversationMessage(
            conversation_id=conversation_id,
            sender=sender,
            content=content,
            status=status,
            escalation_reason=escalation_reason,
            sources=json.dumps(sources) if sources else None,
        )
        self._db.add(message)
        self._db.flush()
        return message

    # ------------------------------------------------------------------
    # The core turn
    # ------------------------------------------------------------------
    def process_message(
        self, conversation_id: uuid.UUID, user_id: uuid.UUID, message: str
    ) -> ChatResponse:
        settings = get_settings()
        started = time.monotonic()

        cleaned = message.strip()
        if not cleaned or len(cleaned) > settings.max_message_length:
            raise UnprocessableError(
                f"Message must contain between 1 and {settings.max_message_length} characters.",
                code="INVALID_MESSAGE",
            )

        conversation = self.get_conversation(conversation_id, user_id)
        if conversation.status == "CLOSED":
            raise ConflictError(
                "This conversation is closed and cannot accept new messages.",
                code="CONVERSATION_CLOSED",
            )

        self.save_message(conversation.id, "CUSTOMER", cleaned)

        # Rule 1 -- security-sensitive content and explicit requests for a
        # person never reach the model.
        pre_reason = detect_pre_ai_reason(cleaned)
        if pre_reason is not None:
            return self._escalate(conversation, pre_reason, started)

        # Rule 2 -- gather only the context this inquiry needs.
        inquiry_type = classify_inquiry(cleaned)
        customer_context = self._customers.get_relevant_account_data(user_id, inquiry_type)
        articles = self._knowledge.search_articles(cleaned, limit=2)

        context = ChatContext(
            conversation_id=str(conversation.id),
            inquiry_type=inquiry_type,
            customer_message=cleaned,
            history=self._recent_history(conversation.id),
            customer_facts=customer_context.to_prompt_facts(),
            knowledge_snippets=[(article.title, article.body) for article in articles],
        )

        result = self._ai.generate_response(context)
        validation = self._validation.validate_response(result)
        decision = self._validation.requires_escalation(result, validation)

        if decision.required and decision.reason is not None:
            logger.info(
                "escalating conversation=%s reason=%s detail=%s",
                conversation.id,
                decision.reason.value,
                decision.detail,
            )
            return self._escalate(conversation, decision.reason, started, ai_result=result)

        stored = self.save_message(
            conversation.id,
            "ASSISTANT",
            result.text,
            status=MessageStatus.ANSWERED.value,
            sources=result.sources,
        )
        self._log_latency(conversation.id, started, MessageStatus.ANSWERED.value)

        return ChatResponse(
            conversation_id=conversation.id,
            message_id=stored.id,
            response=result.text,
            status=MessageStatus.ANSWERED,
            escalation_reason=None,
            timestamp=_as_utc(stored.created_at),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _escalate(
        self,
        conversation: Conversation,
        reason: EscalationReason,
        started: float,
        ai_result: AIResult | None = None,
    ) -> ChatResponse:
        self._escalation.create_case(conversation.id, reason)

        text = ACKNOWLEDGEMENT[reason]
        if ai_result is not None and ai_result.outcome is AIOutcome.PROVIDER_FAILURE:
            text = ai_result.text

        stored = self.save_message(
            conversation.id,
            "ASSISTANT",
            text,
            status=MessageStatus.ESCALATED.value,
            escalation_reason=reason.value,
        )
        self._log_latency(conversation.id, started, MessageStatus.ESCALATED.value)

        return ChatResponse(
            conversation_id=conversation.id,
            message_id=stored.id,
            response=text,
            status=MessageStatus.ESCALATED,
            escalation_reason=reason,
            timestamp=_as_utc(stored.created_at),
        )

    def _recent_history(self, conversation_id: uuid.UUID) -> list[tuple[str, str]]:
        rows = list(
            self._db.query(ConversationMessage)
            .filter(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at)
            .all()
        )
        # Exclude the message just saved; it is supplied separately as the turn.
        history: list[tuple[str, str]] = []
        for row in rows[:-1]:
            role = "user" if row.sender == "CUSTOMER" else "assistant"
            history.append((role, row.content))
        return history[-6:]

    @staticmethod
    def _log_latency(conversation_id: uuid.UUID, started: float, status: str) -> None:
        elapsed = time.monotonic() - started
        level = logging.WARNING if elapsed > RESPONSE_TARGET_SECONDS else logging.INFO
        logger.log(
            level,
            "turn complete conversation=%s status=%s elapsed_ms=%d target_ms=%d",
            conversation_id,
            status,
            int(elapsed * 1000),
            int(RESPONSE_TARGET_SECONDS * 1000),
        )


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
