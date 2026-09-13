"""Human Agent Dashboard endpoints. Every route requires the AGENT role."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import parse_uuid
from app.api.v1.conversations import _to_message_view
from app.db import get_db
from app.models import Conversation, User
from app.modules.escalation.service import EscalationService
from app.schemas import (
    AgentCaseResponse,
    AgentCaseSummary,
    CaseStatus,
    CaseStatusUpdateRequest,
    EscalationReason,
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
