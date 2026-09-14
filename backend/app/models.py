"""SQLAlchemy models for the application data layer.

Note the deliberate split: `LegacyCustomerMaster` models the *existing customer
database* that the platform must integrate with. Its column names mirror a
legacy schema on purpose -- only the Customer Data Adapter reads it, and it
translates those rows into the stable `CustomerContext` contract so that no
other module depends on the legacy shape.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import GUID, Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_new_id)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # CUSTOMER or AGENT -- authorization for agent-only resources depends on this.
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="CUSTOMER")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_new_id)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("users.id"), nullable=False, index=True
    )
    # ACTIVE, ESCALATED or CLOSED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation",
        order_by="ConversationMessage.created_at",
        cascade="all, delete-orphan",
    )


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_new_id)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("conversations.id"), nullable=False, index=True
    )
    # CUSTOMER, ASSISTANT or AGENT
    sender: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # ANSWERED, ESCALATED or ERROR (assistant messages only)
    status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    escalation_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Explainability: which knowledge-base articles informed the answer.
    sources: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class EscalationCase(Base):
    __tablename__ = "escalation_cases"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_new_id)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID, ForeignKey("conversations.id"), nullable=False, index=True
    )
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    # QUEUED, ASSIGNED, RESOLVED or CLOSED
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="QUEUED")
    # The default matches EscalationService.DEFAULT_QUEUE; the service sets it
    # explicitly on every case, so this only covers a row created by hand.
    queue: Mapped[str] = mapped_column(String(40), nullable=False, default="CAREER_COUNSELING")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(GUID, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class FeedbackRecord(Base):
    __tablename__ = "feedback_records"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_new_id)
    conversation_id: Mapped[uuid.UUID] = mapped_column(GUID, nullable=False, index=True)
    message_id: Mapped[uuid.UUID] = mapped_column(GUID, nullable=False)
    submitted_by: Mapped[uuid.UUID] = mapped_column(GUID, nullable=False)
    rating: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class FeedbackEvent(Base):
    """Durable outbox row standing in for the Message/Event Queue.

    The Feedback Module writes here; the Learning Analytics Worker drains it.
    Nothing on this table can change production AI behaviour directly.
    """

    __tablename__ = "feedback_events"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_new_id)
    feedback_id: Mapped[uuid.UUID] = mapped_column(GUID, nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ImprovementRecommendation(Base):
    """Output of the Learning Analytics Worker -- reviewed by a human before use."""

    __tablename__ = "improvement_recommendations"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_new_id)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    occurrences: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # PENDING_REVIEW, APPROVED or REJECTED -- never applied automatically.
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING_REVIEW")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class KnowledgeArticle(Base):
    __tablename__ = "knowledge_articles"

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=_new_id)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    tags: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class LegacyMemberMaster(Base):
    """Stand-in for the existing personnel system of record.

    The column names are abbreviated and the two list columns are semicolon
    delimited because that is what records from an older system actually look
    like. Untangling that is the entire job of the Customer Data Adapter, and
    only the adapter is allowed to read this table -- if these names ever leaked
    into the rest of the application, a schema change over there would become a
    change everywhere.

    Every row is synthetic. No real service member's information appears
    anywhere in this repository.
    """

    __tablename__ = "legacy_member_master"

    mbr_nbr: Mapped[str] = mapped_column(String(20), primary_key=True)
    app_user_id: Mapped[uuid.UUID] = mapped_column(GUID, nullable=False, index=True)

    # Branch of service and pay grade, as the legacy system codes them.
    svc_brnch_cd: Mapped[str] = mapped_column(String(8), nullable=False, default="ARMY")
    pay_grd_cd: Mapped[str] = mapped_column(String(6), nullable=False, default="E5")

    # Occupational specialty code. Each branch uses its own scheme, which is
    # why the adapter carries a lookup rather than showing the raw code.
    occ_spec_cd: Mapped[str] = mapped_column(String(12), nullable=False, default="25B")

    svc_yrs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sep_dt: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Semicolon delimited. The whole point of the platform is grounding advice
    # in what the member has already finished, so these two columns are the
    # most important thing the adapter translates.
    cmpltd_trng_txt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cred_erned_txt: Mapped[str] = mapped_column(Text, nullable=False, default="")

    open_case_cnt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
