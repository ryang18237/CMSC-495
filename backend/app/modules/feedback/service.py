"""Feedback Module.

Records customer and agent feedback and publishes an event for asynchronous
analysis. Recording feedback never changes production AI behaviour directly.
"""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import NotFoundError, UnprocessableError
from app.models import Conversation, ConversationMessage, FeedbackEvent, FeedbackRecord
from app.schemas import FeedbackRating, FeedbackRequest

FEEDBACK_EVENT_TYPE = "CUSTOMER_FEEDBACK_SUBMITTED"


class FeedbackService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def record_feedback(
        self,
        conversation: Conversation,
        request: FeedbackRequest,
        submitted_by: uuid.UUID,
    ) -> FeedbackRecord:
        settings = get_settings()

        if request.comment is not None and len(request.comment) > settings.max_comment_length:
            raise UnprocessableError(
                f"Comment must not exceed {settings.max_comment_length} characters.",
                code="INVALID_COMMENT",
            )

        message = self._db.get(ConversationMessage, request.message_id)
        if message is None or message.conversation_id != conversation.id:
            raise NotFoundError(
                "Message not found in the referenced conversation.",
                code="MESSAGE_NOT_FOUND",
            )

        duplicate = self._db.scalars(
            select(FeedbackRecord)
            .where(FeedbackRecord.message_id == request.message_id)
            .where(FeedbackRecord.submitted_by == submitted_by)
        ).first()
        if duplicate is not None:
            raise UnprocessableError(
                "Feedback has already been recorded for this message.",
                code="FEEDBACK_ALREADY_RECORDED",
            )

        record = FeedbackRecord(
            conversation_id=conversation.id,
            message_id=request.message_id,
            submitted_by=submitted_by,
            rating=request.rating.value,
            comment=request.comment,
        )
        self._db.add(record)
        self._db.flush()

        self.publish_feedback_event(record, message)
        return record

    def publish_feedback_event(
        self, record: FeedbackRecord, message: ConversationMessage
    ) -> FeedbackEvent:
        """Write to the event outbox that the Learning Analytics Worker drains.

        Only aggregate-relevant attributes are published -- never the customer
        identifier and never the message body.
        """
        payload = {
            "feedbackId": str(record.id),
            "rating": record.rating,
            "hasComment": record.comment is not None,
            "assistantStatus": message.status,
            "escalationReason": message.escalation_reason,
            "occurredAt": datetime.now(timezone.utc).isoformat(),
        }
        event = FeedbackEvent(
            feedback_id=record.id,
            event_type=FEEDBACK_EVENT_TYPE,
            payload=json.dumps(payload),
        )
        self._db.add(event)
        self._db.flush()
        return event

    def unhelpful_count(self) -> int:
        return len(
            list(
                self._db.scalars(
                    select(FeedbackRecord).where(
                        FeedbackRecord.rating == FeedbackRating.UNHELPFUL.value
                    )
                )
            )
        )
