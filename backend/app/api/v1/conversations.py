"""Customer-facing conversation endpoints.

Every route derives the customer identity from the verified access token. No
route accepts a customer identifier from the client.
"""

import json

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_conversation_service, parse_uuid
from app.db import get_db
from app.models import ConversationMessage, User
from app.modules.conversation.service import ConversationService
from app.modules.escalation.service import EscalationService
from app.modules.feedback.service import FeedbackService
from app.rate_limit import enforce as enforce_rate_limit
from app.schemas import (
    CaseStatus,
    ChatResponse,
    ConversationCreatedResponse,
    ConversationDetailResponse,
    ConversationStatus,
    EscalationReason,
    EscalationRequest,
    EscalationResponse,
    FeedbackRequest,
    FeedbackResponse,
    MessageRequest,
    MessageStatus,
    MessageView,
)
from app.security import get_current_user

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


def _to_message_view(message: ConversationMessage) -> MessageView:
    """Project a stored message onto the public message contract."""
    sources: list[str] = []
    if message.sources:
        try:
            sources = list(json.loads(message.sources))
        except json.JSONDecodeError:
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


@router.post("", response_model=ConversationCreatedResponse, status_code=status.HTTP_201_CREATED)
def create_conversation(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationCreatedResponse:
    conversation = service.create_conversation(user.id)
    db.commit()
    return ConversationCreatedResponse(
        conversation_id=conversation.id,
        status=ConversationStatus(conversation.status),
        created_at=conversation.created_at,
    )


@router.post("/{conversation_id}/messages", response_model=ChatResponse)
def post_message(
    conversation_id: str,
    payload: MessageRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
) -> ChatResponse:
    enforce_rate_limit(f"messages:{user.id}")
    conversation_uuid = parse_uuid(conversation_id, "conversationId")
    result = service.process_message(conversation_uuid, user.id, payload.message)
    db.commit()
    return result


@router.get("/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(
    conversation_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationDetailResponse:
    conversation_uuid = parse_uuid(conversation_id, "conversationId")
    conversation = service.get_conversation(conversation_uuid, user.id)
    return ConversationDetailResponse(
        conversation_id=conversation.id,
        status=ConversationStatus(conversation.status),
        created_at=conversation.created_at,
        messages=[_to_message_view(message) for message in conversation.messages],
    )


@router.post(
    "/{conversation_id}/escalate",
    response_model=EscalationResponse,
    status_code=status.HTTP_201_CREATED,
)
def escalate(
    conversation_id: str,
    payload: EscalationRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
) -> EscalationResponse:
    conversation_uuid = parse_uuid(conversation_id, "conversationId")
    conversation = service.get_conversation(conversation_uuid, user.id)

    escalation = EscalationService(db)
    case = escalation.create_case(conversation.id, payload.reason, raise_on_duplicate=True)
    db.commit()

    return EscalationResponse(
        case_id=case.id,
        status=CaseStatus(case.status),
        queue=case.queue,
    )


@router.post(
    "/{conversation_id}/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_feedback(
    conversation_id: str,
    payload: FeedbackRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    service: ConversationService = Depends(get_conversation_service),
) -> FeedbackResponse:
    conversation_uuid = parse_uuid(conversation_id, "conversationId")
    conversation = service.get_conversation(conversation_uuid, user.id)

    record = FeedbackService(db).record_feedback(conversation, payload, user.id)
    db.commit()

    return FeedbackResponse(
        feedback_id=record.id,
        conversation_id=record.conversation_id,
        message_id=record.message_id,
        rating=payload.rating,
        recorded_at=record.created_at,
    )
