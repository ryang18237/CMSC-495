"""Human agent escalation path -- HTTP surface.

OWNER: Benjamin Madden (Integration Lead)

Kept in its own router rather than added to `agent.py` so that the escalation
path lands as one reviewable unit. Registering it costs one line in `main.py`.

The request and response models live in `app/schemas.py` with every other
interface contract, and the four routes are documented in `docs/API.md`.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import parse_uuid
from app.api.v1.views import to_case_summary, to_message_view
from app.db import get_db
from app.models import User
from app.modules.escalation.handoff import AgentHandoffService
from app.schemas import (
    AgentCaseSummary,
    AgentReplyRequest,
    AgentWorkloadResponse,
    MessageView,
)
from app.security import require_agent

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])


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
    return to_message_view(message)


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
    return to_case_summary(case)


@router.get("/cases/{case_id}/replies", response_model=list[MessageView])
def list_replies(
    case_id: str,
    db: Session = Depends(get_db),
    agent: User = Depends(require_agent),
) -> list[MessageView]:
    """Counsellor replies on this case, oldest first."""
    replies = AgentHandoffService(db).replies_for_case(parse_uuid(case_id, "caseId"))
    return [to_message_view(message) for message in replies]


@router.get("/workload", response_model=AgentWorkloadResponse)
def my_workload(
    db: Session = Depends(get_db),
    agent: User = Depends(require_agent),
) -> AgentWorkloadResponse:
    """How many open cases the signed-in counsellor holds."""
    return AgentWorkloadResponse(open_cases=AgentHandoffService(db).workload(agent))
