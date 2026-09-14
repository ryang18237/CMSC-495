"""Escalation Module.

Owns escalation rules, case creation, queue placement and transfer context. It
does not query the legacy customer database and does not build AI prompts.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError
from app.models import Conversation, ConversationMessage, EscalationCase
from app.schemas import CaseStatus, EscalationReason

# Two queues, because the people who staff them are different: counsellors
# advise on education and careers, while account security goes to a team
# authorised to act on it.
DEFAULT_QUEUE = "CAREER_COUNSELING"
SECURITY_QUEUE = "ACCOUNT_SECURITY"
_ACTIVE_STATUSES = (CaseStatus.QUEUED.value, CaseStatus.ASSIGNED.value)


def _queue_for(reason: EscalationReason) -> str:
    return SECURITY_QUEUE if reason is EscalationReason.SECURITY_CONCERN else DEFAULT_QUEUE


class EscalationService:
    def __init__(self, db: Session) -> None:
        self._db = db

    def find_active_case(self, conversation_id: uuid.UUID) -> EscalationCase | None:
        return self._db.scalars(
            select(EscalationCase)
            .where(EscalationCase.conversation_id == conversation_id)
            .where(EscalationCase.status.in_(_ACTIVE_STATUSES))
            .order_by(EscalationCase.created_at.desc())
        ).first()

    def create_case(
        self,
        conversation_id: uuid.UUID,
        reason: EscalationReason,
        *,
        raise_on_duplicate: bool = False,
    ) -> EscalationCase:
        """Create an escalation case, or return the existing active one.

        A duplicate request made through the public escalate endpoint is a
        conflict; an internally triggered escalation simply reuses the case.
        """
        existing = self.find_active_case(conversation_id)
        if existing is not None:
            if raise_on_duplicate:
                raise ConflictError(
                    "An active escalation already exists for this conversation.",
                    code="ESCALATION_ALREADY_ACTIVE",
                )
            return existing

        case = EscalationCase(
            conversation_id=conversation_id,
            reason=reason.value,
            status=CaseStatus.QUEUED.value,
            queue=_queue_for(reason),
            summary=self.build_summary(conversation_id, reason),
        )
        self._db.add(case)

        conversation = self._db.get(Conversation, conversation_id)
        if conversation is not None:
            conversation.status = "ESCALATED"

        self._db.flush()
        return case

    def build_summary(self, conversation_id: uuid.UUID, reason: EscalationReason) -> str:
        """Concise handover context so the member does not have to start over.

        Only the member's own turns go into the summary. The assistant's replies
        are already in the transcript the counsellor can read, and repeating
        them here would bury the question that actually needs answering.
        """
        customer_turns = list(
            self._db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == conversation_id)
                .where(ConversationMessage.sender == "CUSTOMER")
                .order_by(ConversationMessage.created_at)
            )
        )
        opening = customer_turns[0].content if customer_turns else "(no customer message)"
        latest = customer_turns[-1].content if customer_turns else opening
        opening = opening[:200]
        latest = latest[:200]

        lines = [
            f"Escalation reason: {reason.value}.",
            f"Customer turns before handover: {len(customer_turns)}.",
            f"Opening request: {opening}",
        ]
        if latest != opening:
            lines.append(f"Most recent request: {latest}")
        return "\n".join(lines)

    def get_case(self, case_id: uuid.UUID, agent_id: uuid.UUID) -> EscalationCase:
        case = self._db.get(EscalationCase, case_id)
        if case is None:
            raise NotFoundError("Escalation case not found.", code="CASE_NOT_FOUND")
        return case

    def list_open_cases(self, limit: int = 50) -> list[EscalationCase]:
        return list(
            self._db.scalars(
                select(EscalationCase)
                .where(EscalationCase.status.in_(_ACTIVE_STATUSES))
                .order_by(EscalationCase.created_at.desc())
                .limit(limit)
            )
        )

    def update_case_status(
        self, case_id: uuid.UUID, status: CaseStatus, agent_id: uuid.UUID
    ) -> EscalationCase:
        case = self.get_case(case_id, agent_id)
        if case.status == CaseStatus.CLOSED.value:
            raise ConflictError("This case is already closed.", code="CASE_ALREADY_CLOSED")

        case.status = status.value
        case.updated_at = datetime.now(timezone.utc)
        if status is CaseStatus.ASSIGNED:
            case.assigned_agent_id = agent_id

        if status in (CaseStatus.RESOLVED, CaseStatus.CLOSED):
            conversation = self._db.get(Conversation, case.conversation_id)
            if conversation is not None:
                conversation.status = "CLOSED"

        self._db.flush()
        return case
