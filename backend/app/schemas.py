"""Request and response data contracts (the public interface of the platform).

These models are the single source of truth for the API documented in
docs/API.md. Field names on the wire are camelCase; the Python attributes stay
snake_case and are mapped through aliases.
"""

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    """Base contract model.

    Python attributes stay snake_case; the wire format is camelCase, produced by
    a single alias generator rather than per-field aliases.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class MessageStatus(str, Enum):
    ANSWERED = "ANSWERED"
    ESCALATED = "ESCALATED"
    ERROR = "ERROR"


class EscalationReason(str, Enum):
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    UNSUPPORTED_TOPIC = "UNSUPPORTED_TOPIC"
    SECURITY_CONCERN = "SECURITY_CONCERN"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"
    AI_SERVICE_FAILURE = "AI_SERVICE_FAILURE"


class ConversationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ESCALATED = "ESCALATED"
    CLOSED = "CLOSED"


class CaseStatus(str, Enum):
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class FeedbackRating(str, Enum):
    HELPFUL = "HELPFUL"
    UNHELPFUL = "UNHELPFUL"


# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------
class LoginRequest(ApiModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)


class LoginResponse(ApiModel):
    access_token: str
    token_type: str = Field(default="Bearer")
    expires_in: int
    role: str
    display_name: str


# --------------------------------------------------------------------------
# POST /api/v1/conversations
# --------------------------------------------------------------------------
class ConversationCreatedResponse(ApiModel):
    conversation_id: uuid.UUID
    status: ConversationStatus
    created_at: datetime


# --------------------------------------------------------------------------
# POST /api/v1/conversations/{conversationId}/messages
# --------------------------------------------------------------------------
class MessageRequest(ApiModel):
    # Length is validated in the service layer so that an over-long message
    # returns 422 INVALID_MESSAGE with the documented wording.
    message: str


class ChatResponse(ApiModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    response: str = Field(max_length=4000)
    status: MessageStatus
    escalation_reason: EscalationReason | None = None
    timestamp: datetime


# --------------------------------------------------------------------------
# GET /api/v1/conversations/{conversationId}
# --------------------------------------------------------------------------
class MessageView(ApiModel):
    message_id: uuid.UUID
    sender: str
    content: str
    status: MessageStatus | None = None
    escalation_reason: EscalationReason | None = None
    sources: list[str] = Field(default_factory=list)
    timestamp: datetime


class ConversationDetailResponse(ApiModel):
    conversation_id: uuid.UUID
    status: ConversationStatus
    created_at: datetime
    messages: list[MessageView]


# --------------------------------------------------------------------------
# POST /api/v1/conversations/{conversationId}/escalate
# --------------------------------------------------------------------------
class EscalationRequest(ApiModel):
    reason: EscalationReason


class EscalationResponse(ApiModel):
    case_id: uuid.UUID
    status: CaseStatus
    queue: str


# --------------------------------------------------------------------------
# GET /api/v1/agent/cases/{caseId}
# --------------------------------------------------------------------------
class AgentCaseResponse(ApiModel):
    case_id: uuid.UUID
    conversation_id: uuid.UUID
    reason: EscalationReason
    status: CaseStatus
    queue: str
    summary: str
    created_at: datetime
    messages: list[MessageView]


class AgentCaseSummary(ApiModel):
    case_id: uuid.UUID
    conversation_id: uuid.UUID
    reason: EscalationReason
    status: CaseStatus
    queue: str
    summary: str
    created_at: datetime


class CaseStatusUpdateRequest(ApiModel):
    status: CaseStatus


# --------------------------------------------------------------------------
# POST /api/v1/conversations/{conversationId}/feedback
# --------------------------------------------------------------------------
class FeedbackRequest(ApiModel):
    message_id: uuid.UUID
    rating: FeedbackRating
    comment: str | None = None


class FeedbackResponse(ApiModel):
    feedback_id: uuid.UUID
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    rating: FeedbackRating
    recorded_at: datetime


# --------------------------------------------------------------------------
# GET /api/v1/health
# --------------------------------------------------------------------------
class HealthResponse(ApiModel):
    status: str
    timestamp: datetime
    version: str
    dependencies: dict[str, str]
