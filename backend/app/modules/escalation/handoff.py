"""Human agent escalation path -- the counsellor's side of a handover.

OWNER: Benjamin Madden (Integration Lead)

Up to this point an escalation was one directional. A conversation reached a
counsellor, the counsellor could read it, and that was where the platform
stopped: there was no way to answer the member. This module closes that loop.

Where it sits
-------------
It belongs to the Escalation Module because the rules about who may speak into
a conversation, and when, are escalation rules. It deliberately does not build
prompts, call the AI module, or read the personnel tables -- a counsellor's
reply is a human's words, and nothing here should quietly become a second
place where conversations get answered.

Two rules worth stating plainly, because they are easy to get wrong later:

1.  A reply may only be posted into a conversation that is actually escalated.
    Without that check a counsellor could interject into a live assistant
    conversation, and the member would see two voices with no explanation.
2.  Replying claims the case. Someone who answers a member has taken
    responsibility for it, so the assignment follows the reply rather than
    waiting for a separate button nobody remembers to press.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import ConflictError, ForbiddenError, NotFoundError, UnprocessableError
from app.models import Conversation, ConversationMessage, EscalationCase, User
from app.schemas import CaseStatus

# A counsellor's reply is a person typing, so the limit is generous compared
# with the 2,000 character limit on a member's message -- but it is still a
# limit, because an unbounded field is an unbounded database column.
MAX_REPLY_LENGTH = 4000

# Statuses where the case is still someone's live responsibility.
_OPEN_STATUSES = (CaseStatus.QUEUED.value, CaseStatus.ASSIGNED.value)


class AgentHandoffService:
    """Everything a counsellor can do to a case after it reaches the queue."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def _load_case(self, case_id: uuid.UUID) -> EscalationCase:
        case = self._db.get(EscalationCase, case_id)
        if case is None:
            raise NotFoundError("Escalation case not found.", code="CASE_NOT_FOUND")
        return case

    def _load_open_case(self, case_id: uuid.UUID) -> EscalationCase:
        """Load a case that can still be worked on.

        A resolved or closed case is not an error to look at -- the dashboard
        still shows it -- but it is an error to keep talking into, because the
        member has been told the conversation is finished.
        """
        case = self._load_case(case_id)
        if case.status not in _OPEN_STATUSES:
            raise ConflictError(
                f"This case is {case.status.lower()} and can no longer be replied to.",
                code="CASE_NOT_OPEN",
            )
        return case

    # ------------------------------------------------------------------
    # Claiming
    # ------------------------------------------------------------------
    def claim_case(self, case_id: uuid.UUID, agent: User) -> EscalationCase:
        """Take ownership of a queued case.

        Claiming is idempotent for the counsellor who already holds the case,
        so a double click does nothing. Claiming a case someone else holds is
        refused: silently stealing it would leave the first counsellor writing
        a reply to a member who has already been handed to somebody else.
        """
        case = self._load_open_case(case_id)

        if case.assigned_agent_id is not None and case.assigned_agent_id != agent.id:
            raise ConflictError(
                "This case is already assigned to another counsellor.",
                code="CASE_ALREADY_ASSIGNED",
            )

        case.assigned_agent_id = agent.id
        case.status = CaseStatus.ASSIGNED.value
        case.updated_at = datetime.now(timezone.utc)
        self._db.flush()
        return case

    # ------------------------------------------------------------------
    # Replying
    # ------------------------------------------------------------------
    def post_reply(self, case_id: uuid.UUID, agent: User, text: str) -> ConversationMessage:
        """Write a counsellor's reply into the member's conversation.

        The message is stored on the conversation itself rather than on the
        case, so the member sees one continuous thread instead of a chat and a
        separate ticket. `GET /api/v1/conversations/{id}` already returns every
        message regardless of sender, so nothing on the member's side needs a
        new endpoint to read it.
        """
        cleaned = text.strip()
        if not cleaned:
            raise UnprocessableError("A reply cannot be empty.", code="INVALID_REPLY")
        if len(cleaned) > MAX_REPLY_LENGTH:
            raise UnprocessableError(
                f"A reply must not exceed {MAX_REPLY_LENGTH} characters.",
                code="INVALID_REPLY",
            )

        case = self._load_open_case(case_id)

        if case.assigned_agent_id is not None and case.assigned_agent_id != agent.id:
            raise ForbiddenError("This case is assigned to another counsellor.")

        conversation = self._db.get(Conversation, case.conversation_id)
        if conversation is None:
            # The case points at a conversation that no longer exists. That is a
            # data problem rather than something the counsellor did wrong.
            raise NotFoundError(
                "The conversation for this case no longer exists.",
                code="CONVERSATION_NOT_FOUND",
            )

        # Answering is taking the case, so the two happen together.
        if case.assigned_agent_id is None:
            case.assigned_agent_id = agent.id
            case.status = CaseStatus.ASSIGNED.value
        case.updated_at = datetime.now(timezone.utc)

        message = ConversationMessage(
            conversation_id=conversation.id,
            sender="AGENT",
            content=cleaned,
            # Deliberately no `status`: ANSWERED and ESCALATED describe what the
            # assistant did with a turn. A human reply is not one of those, and
            # reusing them would corrupt the counters in the ops panel.
            status=None,
            escalation_reason=None,
        )
        self._db.add(message)

        # The conversation stays ESCALATED while a person is handling it. It
        # returns to the member's control only when the case is resolved.
        conversation.status = "ESCALATED"
        self._db.flush()
        return message

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def replies_for_case(self, case_id: uuid.UUID) -> list[ConversationMessage]:
        """Every counsellor reply on this case's conversation, oldest first."""
        case = self._load_case(case_id)
        return list(
            self._db.scalars(
                select(ConversationMessage)
                .where(ConversationMessage.conversation_id == case.conversation_id)
                .where(ConversationMessage.sender == "AGENT")
                .order_by(ConversationMessage.created_at)
            )
        )

    def workload(self, agent: User) -> int:
        """How many open cases this counsellor currently holds.

        Used by the dashboard to show a counsellor what they have taken on. It
        is not a limit -- capping assignments is a staffing decision, and the
        Alpha has no basis for choosing a number.
        """
        return len(
            list(
                self._db.scalars(
                    select(EscalationCase)
                    .where(EscalationCase.assigned_agent_id == agent.id)
                    .where(EscalationCase.status.in_(_OPEN_STATUSES))
                )
            )
        )


def reply_length_limit() -> int:
    """Exposed so the client can validate before a round trip."""
    # Kept as a function rather than a bare import so the limit could later come
    # from configuration without changing callers.
    _ = get_settings()
    return MAX_REPLY_LENGTH
