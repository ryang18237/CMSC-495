"""Unit tests for the individual modules behind their interfaces."""

import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.bootstrap import CUSTOMER_ID
from app.modules.ai_integration.contracts import (
    AIOutcome,
    AIProviderError,
    AIResult,
    ChatContext,
    Prompt,
    ProviderResponse,
)
from app.modules.ai_integration.providers.anthropic_provider import AnthropicProvider
from app.modules.ai_integration.providers.base import AIProvider
from app.modules.ai_integration.providers.mock import MockAIProvider
from app.modules.ai_integration.service import AIIntegrationService, build_provider
from app.modules.analytics.worker import DateRange, LearningAnalyticsWorker
from app.modules.conversation.service import RESPONSE_TARGET_SECONDS, ConversationService
from app.modules.customer_data.adapter import CustomerDataAdapter, classify_inquiry
from app.modules.escalation.rules import detect_pre_ai_reason
from app.modules.knowledge.service import KnowledgeBaseService
from app.modules.validation.service import ResponseValidationService
from app.schemas import EscalationReason


# ---------------------------------------------------------------------------
# Customer Data Adapter
# ---------------------------------------------------------------------------
def test_adapter_translates_legacy_codes(db_session: Session) -> None:
    """Codes in, readable values out. The raw codes must not escape the adapter."""
    context = CustomerDataAdapter(db_session).get_customer_context(CUSTOMER_ID)

    assert context.customer_ref == "MBR-100241"
    assert context.service_branch == "Army"
    assert context.pay_grade == "E-5"
    assert context.occupational_specialty == "Information Technology Specialist"
    # The legacy column is one semicolon delimited string; callers get a list.
    assert "Network Administration Course" in context.completed_training
    assert context.credentials == ["CompTIA A+"]


def test_adapter_minimises_fields_by_inquiry_type(db_session: Session) -> None:
    """A question about timing must not carry the member's training record."""
    adapter = CustomerDataAdapter(db_session)

    transition = adapter.get_relevant_account_data(CUSTOMER_ID, "TRANSITION")
    credential = adapter.get_relevant_account_data(CUSTOMER_ID, "CREDENTIAL")

    assert "completed_training" not in transition.available_fields
    assert "completed_training" in credential.available_fields

    # What matters is not the permission list but what actually reaches a prompt.
    assert not any("Completed training" in fact for fact in transition.to_prompt_facts())
    assert any("Completed training" in fact for fact in credential.to_prompt_facts())


def test_unknown_member_yields_a_safe_context(db_session: Session) -> None:
    """No personnel record is not an error -- the assistant answers generally."""
    context = CustomerDataAdapter(db_session).get_customer_context(uuid.uuid4())
    assert context.service_branch == "UNKNOWN"
    assert context.completed_training == []


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Which certification should I work toward next?", "CREDENTIAL"),
        ("Is an associate degree worth it?", "EDUCATION"),
        ("When should I start a SkillBridge internship?", "TRANSITION"),
        ("How do I describe this on a resume?", "CAREER"),
        ("Hello there", "GENERAL"),
    ],
)
def test_inquiry_classification(message: str, expected: str) -> None:
    """Classification decides how much of the record may be shared, so it is
    checked directly rather than only through the conversation path."""
    assert classify_inquiry(message) == expected


# ---------------------------------------------------------------------------
# Knowledge Base
# ---------------------------------------------------------------------------
def test_knowledge_search_ranks_relevant_articles(db_session: Session) -> None:
    articles = KnowledgeBaseService(db_session).search_articles(
        "certification credential exam", limit=2
    )
    assert articles
    assert "certification" in articles[0].title.lower()


def test_knowledge_search_ignores_stop_words(db_session: Session) -> None:
    assert KnowledgeBaseService(db_session).search_articles("the a is") == []


# ---------------------------------------------------------------------------
# Escalation rules
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Can I talk to a real person?", EscalationReason.CUSTOMER_REQUEST),
        ("transfer me to an agent", EscalationReason.CUSTOMER_REQUEST),
        ("My account was hacked", EscalationReason.SECURITY_CONCERN),
        ("Someone else is using my account", EscalationReason.SECURITY_CONCERN),
        ("How do I describe this on a resume?", None),
    ],
)
def test_pre_ai_rules(message: str, expected: EscalationReason | None) -> None:
    assert detect_pre_ai_reason(message) == expected


# ---------------------------------------------------------------------------
# AI Integration
# ---------------------------------------------------------------------------
def test_prompt_contains_only_permitted_context() -> None:
    context = ChatContext(
        conversation_id=str(uuid.uuid4()),
        inquiry_type="CREDENTIAL",
        customer_message="Which certification should I work toward next?",
        customer_facts=["Completed training: Network Administration Course"],
        knowledge_snippets=[("Certification pathways", "Completed training often covers it.")],
    )
    prompt = AIIntegrationService(MockAIProvider()).build_prompt(context)

    assert "Completed training: Network Administration Course" in prompt.system
    assert "Certification pathways" in prompt.system
    assert prompt.messages[-1] == {
        "role": "user",
        "content": "Which certification should I work toward next?",
    }
    assert prompt.token_estimate() > 0


def test_prompt_truncates_long_articles() -> None:
    context = ChatContext(
        conversation_id=str(uuid.uuid4()),
        inquiry_type="GENERAL",
        customer_message="Tell me about apprenticeships",
        knowledge_snippets=[("Apprenticeships", "word " * 500)],
    )
    prompt = AIIntegrationService(MockAIProvider()).build_prompt(context)
    assert "..." in prompt.system


def test_prompt_keeps_only_recent_history() -> None:
    history = [("user" if index % 2 == 0 else "assistant", f"turn {index}") for index in range(20)]
    context = ChatContext(
        conversation_id=str(uuid.uuid4()),
        inquiry_type="GENERAL",
        customer_message="latest",
        history=history,
    )
    prompt = AIIntegrationService(MockAIProvider()).build_prompt(context)
    assert len(prompt.messages) == 7  # six history turns plus the new one


class _AlwaysFailingProvider(AIProvider):
    name = "always-failing"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt: Prompt) -> ProviderResponse:
        self.calls += 1
        raise AIProviderError("upstream down", retryable=True)


class _NonRetryableProvider(AIProvider):
    name = "non-retryable"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, prompt: Prompt) -> ProviderResponse:
        self.calls += 1
        raise AIProviderError("bad credentials", retryable=False)


class _PolicyBreakingProvider(AIProvider):
    """Returns something plausible that the assistant is not allowed to say.

    Claiming to have enrolled the member is an action only a counsellor takes,
    and the identifier is the kind of value that must never be echoed back.
    """

    name = "policy-breaking"

    def generate(self, prompt: Prompt) -> ProviderResponse:
        return ProviderResponse(
            text=("I have enrolled you in the programme and confirmed it against 123-45-6789."),
            model="test",
        )


def _context(message: str = "How do I describe this on a resume?") -> ChatContext:
    return ChatContext(
        conversation_id=str(uuid.uuid4()), inquiry_type="CAREER", customer_message=message
    )


def test_retryable_failure_is_retried_then_falls_back() -> None:
    provider = _AlwaysFailingProvider()
    result = AIIntegrationService(provider).generate_response(_context())

    assert provider.calls == 3  # initial attempt plus two retries
    assert result.outcome is AIOutcome.PROVIDER_FAILURE
    assert "upstream down" not in result.text
    assert result.error_detail == "upstream down"


def test_non_retryable_failure_is_not_retried() -> None:
    provider = _NonRetryableProvider()
    result = AIIntegrationService(provider).generate_response(_context())

    assert provider.calls == 1
    assert result.outcome is AIOutcome.PROVIDER_FAILURE


def test_mock_provider_reports_unsupported_topic() -> None:
    result = AIIntegrationService(MockAIProvider()).generate_response(
        _context("What is the capital of France?")
    )
    assert result.outcome is AIOutcome.UNSUPPORTED


def test_provider_factory_selects_by_configuration() -> None:
    assert isinstance(build_provider("mock"), MockAIProvider)
    assert isinstance(build_provider("anthropic"), AnthropicProvider)
    assert isinstance(build_provider("something-else"), MockAIProvider)


def test_anthropic_provider_reports_unavailable_without_a_key() -> None:
    """Guards the handoff: the stub must never be silently selected in CI."""
    provider = AnthropicProvider()
    assert provider.name == "anthropic"
    assert provider.health() == "unavailable"


# ---------------------------------------------------------------------------
# Response validation
# ---------------------------------------------------------------------------
def test_validation_rejects_an_action_claim_and_leaked_identifier() -> None:
    service = AIIntegrationService(_PolicyBreakingProvider())
    result = service.generate_response(_context())

    validation = ResponseValidationService().validate_response(result)
    assert not validation.valid

    decision = ResponseValidationService().requires_escalation(result, validation)
    assert decision.required
    assert decision.reason is EscalationReason.VALIDATION_FAILURE


def test_validation_accepts_a_normal_answer() -> None:
    result = AIResult(
        outcome=AIOutcome.ANSWERED,
        text="A foundational certification builds on the coursework you finished.",
        model="test",
    )
    assert ResponseValidationService().validate_response(result).valid


def test_validation_rejects_a_guaranteed_outcome() -> None:
    """Nobody can promise a job or a place on a programme, including the model."""
    result = AIResult(
        outcome=AIOutcome.ANSWERED,
        text="Finish this course and we guarantee you a job with a partner employer.",
        model="test",
    )
    assert not ResponseValidationService().validate_response(result).valid


def test_validation_rejects_an_over_long_response() -> None:
    result = AIResult(outcome=AIOutcome.ANSWERED, text="x" * 4001, model="test")
    assert not ResponseValidationService().validate_response(result).valid


def test_validation_failure_escalates_through_the_service(db_session: Session) -> None:
    service = ConversationService(
        db_session, ai_service=AIIntegrationService(_PolicyBreakingProvider())
    )
    conversation = service.create_conversation(CUSTOMER_ID)
    response = service.process_message(
        conversation.id, CUSTOMER_ID, "How do I describe this on a resume?"
    )
    db_session.commit()

    assert response.status.value == "ESCALATED"
    assert response.escalation_reason is EscalationReason.VALIDATION_FAILURE


# ---------------------------------------------------------------------------
# Learning Analytics Worker
# ---------------------------------------------------------------------------
def test_worker_aggregates_and_recommends_for_human_review(
    client: TestClient, customer_auth: dict[str, str], db_session: Session
) -> None:
    # Generate two unsupported-topic escalations so a pattern recurs.
    for question in ("What is the capital of France?", "Who won the game last night?"):
        conversation_id = client.post("/api/v1/conversations", headers=customer_auth).json()[
            "conversationId"
        ]
        client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=customer_auth,
            json={"message": question},
        )

    worker = LearningAnalyticsWorker(db_session)
    recommendations = worker.run_once(DateRange.last_days(1))
    db_session.commit()

    categories = [item.category for item in recommendations]
    assert "ESCALATION_UNSUPPORTED_TOPIC" in categories
    # Nothing is ever applied automatically.
    assert all(item.review_status == "PENDING_REVIEW" for item in recommendations)


def test_worker_ignores_patterns_below_the_threshold(db_session: Session) -> None:
    worker = LearningAnalyticsWorker(db_session)
    assert worker.run_once(DateRange.last_days(1)) == []


# ---------------------------------------------------------------------------
# Non-functional requirement
# ---------------------------------------------------------------------------
def test_answer_completes_within_the_response_target(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    started = time.monotonic()
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=customer_auth,
        json={"message": "Which certification should I work toward next?"},
    )
    elapsed = time.monotonic() - started

    assert response.status_code == 200
    assert elapsed < RESPONSE_TARGET_SECONDS
