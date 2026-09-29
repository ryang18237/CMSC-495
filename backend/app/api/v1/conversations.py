"""Customer-facing conversation endpoints.

Every route derives the customer identity from the verified access token. No
route accepts a customer identifier from the client.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_conversation_service, parse_uuid
from app.api.v1.views import to_message_view
from app.db import get_db
from app.errors import UnprocessableError
from app.models import User
from app.modules.ai_integration.service import AIIntegrationService, build_provider, is_available
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
    EscalationRequest,
    EscalationResponse,
    FeedbackRequest,
    FeedbackResponse,
    MessageRequest,
)
from app.security import get_current_user

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


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
    if payload.provider:
        # The member chose a model. Only a configured one is accepted, so a
        # request can never make the server call a provider it has no key for.
        chosen = payload.provider.strip().lower()
        if not is_available(chosen):
            raise UnprocessableError(
                "That AI model is not available on this server.",
                code="AI_PROVIDER_UNAVAILABLE",
            )
        service = ConversationService(db, ai_service=AIIntegrationService(build_provider(chosen)))
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
        messages=[to_message_view(message) for message in conversation.messages],
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
