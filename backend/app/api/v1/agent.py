"""Human Agent Dashboard endpoints. Every route requires the AGENT role."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import parse_uuid
from app.api.v1.conversations import _to_message_view
from app.db import get_db
from app.errors import ConflictError, NotFoundError
from app.models import Conversation, ImprovementRecommendation, User
from app.modules.analytics.worker import DateRange, LearningAnalyticsWorker
from app.modules.escalation.service import EscalationService
from app.schemas import (
    AgentCaseResponse,
    AgentCaseSummary,
    AnalyticsRunResponse,
    CaseStatus,
    CaseStatusUpdateRequest,
    EscalationReason,
    RecommendationDecisionRequest,
    RecommendationView,
    ReviewStatus,
)
from app.security import require_agent

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


@router.get("/cases", response_model=list[AgentCaseSummary])
def list_cases(
    db: Session = Depends(get_db),
    agent: User = Depends(require_agent),
) -> list[AgentCaseSummary]:
    cases = EscalationService(db).list_open_cases()
    return [
        AgentCaseSummary(
            case_id=case.id,
            conversation_id=case.conversation_id,
            reason=EscalationReason(case.reason),
            status=CaseStatus(case.status),
            queue=case.queue,
            summary=case.summary,
            created_at=case.created_at,
        )
        for case in cases
    ]


@router.get("/cases/{case_id}", response_model=AgentCaseResponse)
def get_case(
    case_id: str,
    db: Session = Depends(get_db),
    agent: User = Depends(require_agent),
) -> AgentCaseResponse:
    case_uuid = parse_uuid(case_id, "caseId")
    case = EscalationService(db).get_case(case_uuid, agent.id)
    conversation = db.get(Conversation, case.conversation_id)
    messages = conversation.messages if conversation is not None else []

    return AgentCaseResponse(
        case_id=case.id,
        conversation_id=case.conversation_id,
        reason=EscalationReason(case.reason),
        status=CaseStatus(case.status),
        queue=case.queue,
        summary=case.summary,
        created_at=case.created_at,
        messages=[_to_message_view(message) for message in messages],
    )


@router.patch("/cases/{case_id}", response_model=AgentCaseSummary)
def update_case(
    case_id: str,
    payload: CaseStatusUpdateRequest,
    db: Session = Depends(get_db),
    agent: User = Depends(require_agent),
) -> AgentCaseSummary:
    case_uuid = parse_uuid(case_id, "caseId")
    case = EscalationService(db).update_case_status(case_uuid, payload.status, agent.id)
    db.commit()

    return AgentCaseSummary(
        case_id=case.id,
        conversation_id=case.conversation_id,
        reason=EscalationReason(case.reason),
        status=CaseStatus(case.status),
        queue=case.queue,
        summary=case.summary,
        created_at=case.created_at,
    )


# ---------------------------------------------------------------------------
# Reviewed AI Configuration / Routing Improvements
#
# ALPHA SCOPE -- barebones. The review workflow is real: the Learning Analytics
# Worker writes candidates as PENDING_REVIEW and a human approves or rejects
# them here. What an approval does NOT do yet is apply anything. Nothing in the
# platform reads an APPROVED recommendation and changes a prompt or a routing
# rule; that application step is deliberately out of scope for the Alpha.
#
# The important property is already enforced: an individual conversation can
# never alter production AI behaviour. It can only contribute to an aggregate
# that a person must act on.
# ---------------------------------------------------------------------------


def _to_recommendation_view(row: ImprovementRecommendation) -> RecommendationView:
    return RecommendationView(
        recommendation_id=row.id,
        category=row.category,
        detail=row.detail,
        occurrences=row.occurrences,
        review_status=ReviewStatus(row.review_status),
        period_start=row.period_start,
        period_end=row.period_end,
        created_at=row.created_at,
    )


@router.get("/recommendations", response_model=list[RecommendationView])
def list_recommendations(
    status: ReviewStatus | None = None,
    db: Session = Depends(get_db),
    agent: User = Depends(require_agent),
) -> list[RecommendationView]:
    """Improvement candidates produced by the Learning Analytics Worker."""
    query = select(ImprovementRecommendation).order_by(ImprovementRecommendation.created_at.desc())
    if status is not None:
        query = query.where(ImprovementRecommendation.review_status == status.value)
    return [_to_recommendation_view(row) for row in db.scalars(query.limit(50))]


@router.patch("/recommendations/{recommendation_id}", response_model=RecommendationView)
def review_recommendation(
    recommendation_id: str,
    payload: RecommendationDecisionRequest,
    db: Session = Depends(get_db),
    agent: User = Depends(require_agent),
) -> RecommendationView:
    """Record a human decision on a recommendation.

    A decision is final: re-reviewing an already decided item is a conflict
    rather than a silent overwrite, so the audit trail stays meaningful.
    """
    row = db.get(ImprovementRecommendation, parse_uuid(recommendation_id, "recommendationId"))
    if row is None:
        raise NotFoundError("Recommendation not found.", code="RECOMMENDATION_NOT_FOUND")

    if payload.review_status is ReviewStatus.PENDING_REVIEW:
        raise ConflictError(
            "A review decision must be APPROVED or REJECTED.",
            code="INVALID_REVIEW_DECISION",
        )
    if row.review_status != ReviewStatus.PENDING_REVIEW.value:
        raise ConflictError(
            f"This recommendation was already {row.review_status.lower()}.",
            code="RECOMMENDATION_ALREADY_REVIEWED",
        )

    row.review_status = payload.review_status.value
    db.commit()
    return _to_recommendation_view(row)


@router.post("/analytics/run", response_model=AnalyticsRunResponse)
def run_analytics(
    days: int = 7,
    db: Session = Depends(get_db),
    agent: User = Depends(require_agent),
) -> AnalyticsRunResponse:
    """Run the Learning Analytics Worker once, on demand.

    ALPHA SCOPE -- barebones. In the target system the worker is triggered by
    the message queue on a schedule. Exposing it here lets the asynchronous
    path be demonstrated without waiting for a scheduler, and it runs the same
    code the command-line entry point does.
    """
    worker = LearningAnalyticsWorker(db)
    created = worker.run_once(DateRange.last_days(max(1, min(days, 90))))
    db.commit()
    return AnalyticsRunResponse(
        recommendations_created=len(created),
        ran_at=datetime.now(timezone.utc),
    )
