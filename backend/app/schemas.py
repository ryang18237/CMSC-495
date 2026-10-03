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


class ReviewStatus(str, Enum):
    """Lifecycle of a Learning Analytics recommendation.

    Nothing reaches the production AI without an explicit APPROVED decision --
    the "approved changes only" constraint in the architecture diagram.
    """

    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


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
# Counsellor replies -- /api/v1/agent/cases/{caseId}/reply, /claim, /replies
# and /api/v1/agent/workload
# --------------------------------------------------------------------------

# Longest reply a counsellor can send. Lives here rather than in the Escalation
# Module because it is part of the contract: the client reads it to validate
# before a round trip, and the request model below enforces it at the edge.
MAX_REPLY_LENGTH = 4000


class AgentReplyRequest(ApiModel):
    """A counsellor's reply to a member.

    Length is validated in the Escalation Module, the same way a member's
    message is, so that every bad reply -- empty, whitespace only or too long --
    returns the one documented code, 422 INVALID_REPLY. Bounding it here as
    well would split that into INVALID_REQUEST for some cases and INVALID_REPLY
    for others. An enormous body is still stopped at the edge by the 413
    request-size check in main.py.
    """

    message: str


class AgentWorkloadResponse(ApiModel):
    """Open cases held by the signed-in counsellor."""

    open_cases: int


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
    instance_id: str
    dependencies: dict[str, str]


# --------------------------------------------------------------------------
# Reviewed AI configuration (agent-facing)
# --------------------------------------------------------------------------
class RecommendationView(ApiModel):
    recommendation_id: uuid.UUID
    category: str
    detail: str
    occurrences: int
    review_status: ReviewStatus
    period_start: datetime
    period_end: datetime
    created_at: datetime


class RecommendationDecisionRequest(ApiModel):
    review_status: ReviewStatus


class AnalyticsRunResponse(ApiModel):
    """Result of running the Learning Analytics Worker on demand."""

    recommendations_created: int
    ran_at: datetime


# --------------------------------------------------------------------------
# My record -- /api/v1/profile/record (member-facing)
# --------------------------------------------------------------------------
class RecordItemKind(str, Enum):
    CREDENTIAL = "CREDENTIAL"
    TRAINING = "TRAINING"
    EDUCATION = "EDUCATION"
    EXPERIENCE = "EXPERIENCE"
    # Something the member intends to do, not something they hold.
    GOAL = "GOAL"


class RecordItemSource(str, Enum):
    MANUAL = "MANUAL"
    UPLOAD = "UPLOAD"


class RecordItemRequest(ApiModel):
    # Plain strings, validated in the service, so every bad item returns the
    # one documented code (422 INVALID_RECORD_ITEM) rather than two.
    kind: str
    name: str
    # Issuer, school or employer, and anything else worth keeping. Both
    # optional: a profile filled in a little at a time is still useful.
    organization: str | None = None
    detail: str | None = None


class RecordItemsRequest(ApiModel):
    items: list[RecordItemRequest]


class MemberRecordItemView(ApiModel):
    item_id: uuid.UUID
    kind: RecordItemKind
    name: str
    organization: str | None = None
    detail: str | None = None
    source: RecordItemSource
    added_at: datetime


class ServiceRecordSummary(ApiModel):
    service_branch: str
    occupational_specialty: str | None
    completed_training: list[str]
    credentials: list[str]


class ProfileCompleteness(ApiModel):
    # 0-100. Four kinds, each worth the same, plus the service record.
    percent: int
    # Kinds with nothing in them yet, in the order worth filling.
    missing_kinds: list[RecordItemKind]


class MemberRecordResponse(ApiModel):
    # What the personnel system holds -- read-only, null if there is no record.
    service_record: ServiceRecordSummary | None
    # The member's own profile. Used in every conversation alongside the above.
    added: list[MemberRecordItemView]
    # How complete the profile looks, so the client can prompt for what is
    # missing rather than leaving the member guessing.
    completeness: ProfileCompleteness


class RecordItemsAddedResponse(ApiModel):
    added: list[MemberRecordItemView]
    already_on_record: int


class RecordImportRequest(ApiModel):
    filename: str
    content_base64: str


class RecordCandidate(ApiModel):
    kind: RecordItemKind
    name: str
    organization: str | None = None
    detail: str | None = None


class RecordImportResponse(ApiModel):
    # Nothing is saved yet. The member confirms, then the client posts the
    # chosen items to /api/v1/profile/record/items/bulk.
    candidates: list[RecordCandidate]
    skipped_lines: int
