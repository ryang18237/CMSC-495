"""ChatGPT as a second provider, the member's choice of model, and a demo
assistant that answers from the member's own record.

The OpenAI tests stub HTTP with httpx.MockTransport, like the Anthropic ones,
so no key and no network are needed.
"""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.modules.ai_integration.contracts import AIProviderError, Prompt
from app.modules.ai_integration.providers.builtin import BuiltInAdvisor
from app.modules.ai_integration.providers.openai_provider import MAX_TOKENS, OpenAIProvider
from app.modules.ai_integration.service import (
    AIIntegrationService,
    available_providers,
    build_provider,
    is_available,
)

PROMPT = Prompt(
    system="You are the SkillBridge assistant.",
    messages=[{"role": "user", "content": "Which certification should I work toward next?"}],
)


def _completion(text="Network+ is a good next step.", finish="stop", **message_extra):
    return {
        "model": "gpt-6-luna",
        "choices": [
            {
                "message": {"role": "assistant", "content": text, **message_extra},
                "finish_reason": finish,
            }
        ],
    }


def _openai(handler) -> OpenAIProvider:
    return OpenAIProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))


@pytest.fixture
def openai_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "openai_api_key", "sk-openai-test-key")


@pytest.fixture
def no_keys(monkeypatch):
    monkeypatch.setattr(get_settings(), "openai_api_key", "")
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")


# ---------------------------------------------------------------------------
# OpenAI provider
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("openai_key")
def test_request_matches_chat_completions():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["auth"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_completion())

    response = _openai(handler).generate(PROMPT)

    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["auth"] == "Bearer sk-openai-test-key"
    body = captured["body"]
    assert set(body) == {"model", "max_completion_tokens", "messages"}
    assert body["max_completion_tokens"] == MAX_TOKENS
    # The system prompt travels as the first message; nothing else is added.
    assert body["messages"][0] == {"role": "system", "content": PROMPT.system}
    assert body["messages"][1:] == PROMPT.messages
    assert response.text == "Network+ is a good next step."


@pytest.mark.usefixtures("openai_key")
@pytest.mark.parametrize(
    ("status", "retryable"),
    [(400, False), (401, False), (403, False), (404, False), (429, True), (500, True), (503, True)],
)
def test_status_maps_to_the_same_retry_policy(status, retryable):
    with pytest.raises(AIProviderError) as caught:
        _openai(lambda r: httpx.Response(status, json={"error": {"message": "detail"}})).generate(
            PROMPT
        )
    assert caught.value.retryable is retryable
    assert "detail" not in str(caught.value)


@pytest.mark.usefixtures("openai_key")
def test_length_cut_off_is_reported_as_truncation():
    response = _openai(
        lambda r: httpx.Response(200, json=_completion("Start with", "length"))
    ).generate(PROMPT)
    assert response.stop_reason == "max_tokens"


@pytest.mark.usefixtures("openai_key")
def test_refusal_becomes_the_decline_marker():
    body = _completion(text=None, refusal="I can't help with that.")
    assert _openai(lambda r: httpx.Response(200, json=body)).generate(PROMPT).text == (
        "UNSUPPORTED_TOPIC"
    )


@pytest.mark.usefixtures("openai_key")
@pytest.mark.parametrize("payload", [{}, {"choices": []}, _completion(text="")])
def test_malformed_bodies_are_retryable(payload):
    with pytest.raises(AIProviderError) as caught:
        _openai(lambda r: httpx.Response(200, json=payload)).generate(PROMPT)
    assert caught.value.retryable is True


@pytest.mark.usefixtures("no_keys")
def test_without_a_key_it_is_unavailable_and_never_calls_out():
    called = []
    provider = _openai(lambda r: called.append(r) or httpx.Response(200, json=_completion()))
    assert provider.health() == "unavailable"
    with pytest.raises(AIProviderError):
        provider.generate(PROMPT)
    assert called == []


# ---------------------------------------------------------------------------
# Which providers are offered
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("no_keys")
def test_the_builtin_advisor_is_never_offered_to_a_member():
    """It is a test double. Offered beside a real model it gets picked by accident."""
    assert [option.provider_id for option in available_providers()] == []
    assert not is_available("builtin")
    assert not is_available("mock")


def test_a_provider_is_offered_once_its_key_is_set(monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "sk-ant-test")
    monkeypatch.setattr(get_settings(), "openai_api_key", "sk-openai-test")
    monkeypatch.setattr(get_settings(), "ai_provider", "anthropic")
    options = {option.provider_id: option for option in available_providers()}
    assert set(options) == {"anthropic", "openai"}
    assert options["anthropic"].is_default
    assert options["openai"].label == "ChatGPT"


def test_factory_builds_each_provider():
    assert isinstance(build_provider("openai"), OpenAIProvider)
    # A typo in configuration resolves like `auto` rather than taking the
    # platform down -- and never silently to the advisor.
    assert not isinstance(build_provider("unknown"), BuiltInAdvisor)


@pytest.mark.usefixtures("no_keys")
def test_providers_endpoint_never_exposes_a_key(client: TestClient, customer_auth, monkeypatch):
    monkeypatch.setattr(get_settings(), "openai_api_key", "sk-openai-secret-value")
    response = client.get("/api/v1/ai/providers", headers=customer_auth)
    assert response.status_code == 200
    assert {item["providerId"] for item in response.json()} == {"openai"}
    assert "sk-openai-secret-value" not in response.text


def test_providers_endpoint_requires_sign_in(client: TestClient):
    assert client.get("/api/v1/ai/providers").status_code == 401


# ---------------------------------------------------------------------------
# The member's choice, per message
# ---------------------------------------------------------------------------
def _conversation(client, auth):
    return client.post("/api/v1/conversations", headers=auth).json()["conversationId"]


@pytest.mark.usefixtures("no_keys")
def test_choosing_an_unconfigured_model_is_refused(client: TestClient, customer_auth):
    conversation = _conversation(client, customer_auth)
    response = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        headers=customer_auth,
        json={"message": "Which certification should I work toward next?", "provider": "openai"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "AI_PROVIDER_UNAVAILABLE"


def test_the_chosen_model_answers(client: TestClient, customer_auth, monkeypatch):
    monkeypatch.setattr(get_settings(), "openai_api_key", "sk-openai-test")
    seen = []

    def fake_generate(self, prompt):
        seen.append(self.name)
        from app.modules.ai_integration.contracts import ProviderResponse

        return ProviderResponse(text="A reply from the chosen model.", model="gpt-6-luna")

    monkeypatch.setattr(OpenAIProvider, "generate", fake_generate)
    conversation = _conversation(client, customer_auth)
    response = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        headers=customer_auth,
        json={"message": "Which certification should I work toward next?", "provider": "openai"},
    ).json()

    assert seen == ["openai"]
    assert response["answeredBy"] == "openai"
    assert response["response"] == "A reply from the chosen model."


def test_without_a_choice_the_default_answers(client: TestClient, customer_auth):
    conversation = _conversation(client, customer_auth)
    response = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        headers=customer_auth,
        json={"message": "Which certification should I work toward next?"},
    ).json()
    assert response["answeredBy"] == "builtin"


# ---------------------------------------------------------------------------
# The demo assistant answers from the member's own record
# ---------------------------------------------------------------------------
# Members no longer arrive with a history: the personnel feed supplies the
# posting, and the member supplies what they have done. A test about two
# different people therefore has to make them different.
ARMY_IT_HISTORY = [
    {"kind": "CREDENTIAL", "name": "CompTIA A+"},
    {"kind": "TRAINING", "name": "Network Administration Course"},
    {"kind": "TRAINING", "name": "Information Assurance Fundamentals"},
]

NAVY_MEDICAL_HISTORY = [
    {"kind": "CREDENTIAL", "name": "EMT-Basic"},
    {"kind": "TRAINING", "name": "Hospital Corpsman A School"},
    {"kind": "TRAINING", "name": "Field Medical Service Technician"},
]


def give_profile(client, auth, items):
    response = client.post("/api/v1/profile/record/items/bulk", headers=auth, json={"items": items})
    assert response.status_code in (200, 201), response.text


def _ask(client, auth, question="Which certification should I work toward next?"):
    conversation = _conversation(client, auth)
    return client.post(
        f"/api/v1/conversations/{conversation}/messages", headers=auth, json={"message": question}
    ).json()["response"]


def test_two_members_get_different_answers(client: TestClient, customer_auth, other_customer_auth):
    give_profile(client, customer_auth, ARMY_IT_HISTORY)
    give_profile(client, other_customer_auth, NAVY_MEDICAL_HISTORY)

    it_member = _ask(client, customer_auth)
    corpsman = _ask(client, other_customer_auth)

    assert "CompTIA A+" in it_member
    assert "Network+" in it_member
    assert "EMT-Basic" in corpsman
    assert "Paramedic" in corpsman
    assert it_member != corpsman


def test_the_answer_changes_when_my_record_changes(client: TestClient, customer_auth):
    before = _ask(client, customer_auth)
    client.post(
        "/api/v1/profile/record/items",
        headers=customer_auth,
        json={"kind": "CREDENTIAL", "name": "CompTIA Security+"},
    )
    after = _ask(client, customer_auth)

    assert "CompTIA Security+" in after
    assert "CySA+" in after  # the next step after Security+
    assert before != after


def test_personal_answers_still_pass_validation(client: TestClient, customer_auth):
    """Nothing the demo assistant builds may promise or claim an action."""
    for question in (
        "Which certification should I work toward next?",
        "Should I do a degree or a certification first?",
        "How do I describe my training on a civilian resume?",
    ):
        conversation = _conversation(client, customer_auth)
        reply = client.post(
            f"/api/v1/conversations/{conversation}/messages",
            headers=customer_auth,
            json={"message": question},
        ).json()
        assert reply["status"] == "ANSWERED", question


@pytest.mark.usefixtures("no_keys")
@pytest.mark.parametrize(
    "question",
    [
        # The phrasing that was escalated as unsupported: "certs" matched no
        # keyword, so the single most common question this service exists for
        # never reached the advisor.
        "what are the next certs I should get?",
        "What cert should I go for next?",
        "Any certifications worth getting?",
        "What should I do next?",
        "What do you recommend for my career?",
        "Which licences could I qualify for?",
    ],
)
def test_ordinary_phrasings_are_answered_not_escalated(
    client: TestClient, customer_auth, question: str
):
    """A member should not have to guess the vocabulary the matcher knows."""
    conversation = _conversation(client, customer_auth)
    reply = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        headers=customer_auth,
        json={"message": question},
    ).json()

    assert reply["status"] == "ANSWERED", question
    assert reply.get("escalationReason") is None, question


@pytest.mark.usefixtures("no_keys")
def test_a_genuinely_off_topic_question_still_escalates(client: TestClient, customer_auth):
    """The wider vocabulary must not turn the advisor into a general chatbot."""
    conversation = _conversation(client, customer_auth)
    reply = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        headers=customer_auth,
        json={"message": "What is the capital of France?"},
    ).json()

    assert reply["escalationReason"] == "UNSUPPORTED_TOPIC"


def test_service_reports_which_provider_is_in_use():
    assert AIIntegrationService(BuiltInAdvisor()).provider_name == "builtin"


# ---------------------------------------------------------------------------
# The built-in advisor: usable with no key at all
# ---------------------------------------------------------------------------
@pytest.mark.usefixtures("no_keys")
def test_the_platform_answers_with_no_keys_configured(client: TestClient, member_with_history):
    """The whole point: install it, sign in, get a personal answer. No setup."""
    customer_auth = member_with_history
    conversation = _conversation(client, customer_auth)
    reply = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        headers=customer_auth,
        json={"message": "Which certification should I work toward next?"},
    ).json()

    assert reply["status"] == "ANSWERED"
    assert reply["answeredBy"] == "builtin"
    assert "CompTIA A+" in reply["response"]  # grounded in this member's record


@pytest.mark.usefixtures("no_keys")
def test_the_advisor_uses_education_and_experience(client: TestClient, member_with_history):
    customer_auth = member_with_history
    for item in (
        {"kind": "EDUCATION", "name": "Associate of Applied Science", "organization": "CTC"},
        {"kind": "EXPERIENCE", "name": "Help Desk Technician", "organization": "Fort Hood"},
    ):
        client.post("/api/v1/profile/record/items", headers=customer_auth, json=item)

    resume = _ask(client, customer_auth, "How do I describe my training on a civilian resume?")
    assert "Help Desk Technician" in resume

    studied = _ask(client, customer_auth, "Should I do a degree or a certification first?")
    assert "Associate of Applied Science" in studied


@pytest.mark.usefixtures("no_keys")
def test_the_advisor_can_read_back_the_profile(client: TestClient, customer_auth):
    client.post(
        "/api/v1/profile/record/items",
        headers=customer_auth,
        json={"kind": "EXPERIENCE", "name": "Help Desk Technician"},
    )
    answer = _ask(client, customer_auth, "What experience do I have on file?")
    assert "Help Desk Technician" in answer
    assert "My profile" in answer


@pytest.mark.usefixtures("no_keys")
def test_an_unrecognised_question_reaches_a_person_rather_than_being_guessed(
    client: TestClient, customer_auth
):
    """The advisor's coverage is narrower than a model's, and it says so honestly."""
    conversation = _conversation(client, customer_auth)
    reply = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        headers=customer_auth,
        json={"message": "What is the capital of France?"},
    ).json()
    assert reply["status"] == "ESCALATED"
    assert reply["escalationReason"] == "UNSUPPORTED_TOPIC"


def test_the_advisor_is_reachable_only_by_naming_it_outright():
    """CI pins AI_PROVIDER=builtin (or the older `mock`) and gets it.

    That is the whole remaining use: a deterministic, instant, daemon-free
    stand-in for a language model in a test run. A member cannot reach it,
    because nothing offers it and nothing resolves to it.
    """
    assert isinstance(build_provider("builtin"), BuiltInAdvisor)
    assert isinstance(build_provider("mock"), BuiltInAdvisor)
    assert not is_available("builtin")


@pytest.mark.usefixtures("no_keys")
def test_an_empty_profile_is_asked_for_rather_than_guessed_about(client: TestClient, customer_auth):
    """A new member has nothing on file. Say so and ask, do not improvise."""
    conversation = _conversation(client, customer_auth)
    reply = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        headers=customer_auth,
        json={"message": "Given my background what should I do next?"},
    ).json()

    assert reply["status"] == "ANSWERED"
    assert "My profile" in reply["response"]
    assert reply.get("escalationReason") is None


@pytest.mark.usefixtures("no_keys")
def test_the_answer_changes_as_soon_as_there_is_something_to_go_on(
    client: TestClient, customer_auth
):
    """One entry is enough to stop asking and start advising."""
    before = _ask(client, customer_auth)
    assert "My profile" in before

    give_profile(client, customer_auth, [{"kind": "CREDENTIAL", "name": "CompTIA A+"}])
    after = _ask(client, customer_auth)

    assert "My profile" not in after
    assert "CompTIA A+" in after


@pytest.mark.usefixtures("no_keys")
def test_an_empty_profile_does_not_make_everything_answerable(client: TestClient, customer_auth):
    """Asking for the member's details is not a licence to answer anything."""
    conversation = _conversation(client, customer_auth)
    reply = client.post(
        f"/api/v1/conversations/{conversation}/messages",
        headers=customer_auth,
        json={"message": "What is the capital of France?"},
    ).json()

    assert reply["escalationReason"] == "UNSUPPORTED_TOPIC"


@pytest.mark.usefixtures("no_keys")
def test_background_as_context_is_not_a_question_about_the_profile(
    client: TestClient, customer_auth
):
    """ "Given my background, what next?" wants advice, not a list read back."""
    give_profile(client, customer_auth, ARMY_IT_HISTORY)
    answer = _ask(client, customer_auth, "Given my background what should I do next?")

    assert "Your profile currently lists" not in answer
    assert "next step" in answer.lower() or "closest" in answer.lower()


@pytest.mark.usefixtures("no_keys")
def test_asking_what_is_on_file_still_reads_the_profile_back(client: TestClient, customer_auth):
    give_profile(client, customer_auth, ARMY_IT_HISTORY)
    answer = _ask(client, customer_auth, "What do you have on file for me?")

    assert "Your profile currently lists" in answer
