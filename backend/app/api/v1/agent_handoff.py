"""Human agent escalation path -- HTTP surface.

OWNER: Benjamin Madden (Integration Lead)

Kept in its own router rather than added to `agent.py` so that the escalation
path lands as one reviewable unit. Registering it costs one line in `main.py`.

The request model is defined here for the same reason. Interface contracts
normally live in `app/schemas.py`, which is Ryan's file -- once this merges,
`AgentReplyRequest` should move there and into `docs/API.md` alongside the
other documented contracts.
"""

from fastapi import APIRouter, Depends, status
from pydantic import Field
from sqlalchemy.orm import Session

from app.api.deps import parse_uuid
from app.api.v1.conversations import _to_message_view
from app.db import get_db
from app.models import User
from app.modules.escalation.handoff import MAX_REPLY_LENGTH, AgentHandoffService
from app.schemas import AgentCaseSummary, ApiModel, CaseStatus, EscalationReason, MessageView
from app.security import require_agent

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


class AgentReplyRequest(ApiModel):
    """A counsellor's reply to a member.

    The length is validated again in the service layer: this bound stops an
    enormous body at the edge, while the service produces the documented
    422 INVALID_REPLY for anything that is merely too long or blank.
    """

    message: str = Field(min_length=1, max_length=MAX_REPLY_LENGTH)


@router.post(
    "/cases/{case_id}/reply",
    response_model=MessageView,
    status_code=status.HTTP_201_CREATED,
)
def reply_to_member(
    case_id: str,
    payload: AgentReplyRequest,
    db: Session = Depends(get_db),
    agent: User = Depends(require_agent),
) -> MessageView:
    """Post a counsellor's reply into the member's conversation.

    Replying also claims the case, because answering a member is taking
    responsibility for them. The member sees the reply in the same thread on
    their next poll -- no separate endpoint and no second inbox.
    """
    message = AgentHandoffService(db).post_reply(
        parse_uuid(case_id, "caseId"), agent, payload.message
    )
    db.commit()
    return _to_message_view(message)


@router.post("/cases/{case_id}/claim", response_model=AgentCaseSummary)
def claim_case(
    case_id: str,
    db: Session = Depends(get_db),
    agent: User = Depends(require_agent),
) -> AgentCaseSummary:
    """Take ownership of a queued case without replying yet.

    Useful when a counsellor wants to read a long conversation before writing
    anything, and wants colleagues to see it is being handled.
    """
    case = AgentHandoffService(db).claim_case(parse_uuid(case_id, "caseId"), agent)
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


@router.get("/cases/{case_id}/replies", response_model=list[MessageView])
def list_replies(
    case_id: str,
    db: Session = Depends(get_db),
    agent: User = Depends(require_agent),
) -> list[MessageView]:
    """Counsellor replies on this case, oldest first."""
    replies = AgentHandoffService(db).replies_for_case(parse_uuid(case_id, "caseId"))
    return [_to_message_view(message) for message in replies]


@router.get("/workload")
def my_workload(
    db: Session = Depends(get_db),
    agent: User = Depends(require_agent),
) -> dict[str, int]:
    """How many open cases the signed-in counsellor holds."""
    return {"openCases": AgentHandoffService(db).workload(agent)}
