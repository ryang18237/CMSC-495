"""Tests for the Anthropic provider.

Every test stubs the HTTP layer with `httpx.MockTransport`, so the suite needs
no API key and makes no network call. That is what lets CI run these on every
push while `AI_PROVIDER` stays `mock`.
"""

import json

import httpx
import pytest

from app.config import get_settings
from app.modules.ai_integration.contracts import AIProviderError, Prompt
from app.modules.ai_integration.providers.anthropic_provider import (
    ANTHROPIC_VERSION,
    MAX_TOKENS,
    AnthropicProvider,
    reset_shared_client,
)
from app.modules.ai_integration.service import AIIntegrationService, build_provider

PROMPT = Prompt(
    system="You are the customer service assistant.",
    messages=[
        {"role": "user", "content": "Where is my order?"},
        {"role": "assistant", "content": "Let me check."},
        {"role": "user", "content": "Thanks"},
    ],
)


def _answer(text="Tracking updates within one business day.", stop_reason="end_turn"):
    return {
        "content": [{"type": "text", "text": text}],
        "model": "claude-sonnet-4-5",
        "stop_reason": stop_reason,
    }


def _provider_returning(handler):
    """Build a provider whose HTTP calls are served by `handler`."""
    return AnthropicProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))


def _provider_with(status, payload=None, *, body=None):
    def handler(request):
        if body is not None:
            return httpx.Response(status, content=body)
        return httpx.Response(status, json=payload if payload is not None else {})

    return _provider_returning(handler)


@pytest.fixture(autouse=True)
def _configured_key(monkeypatch):
    """Give the provider a key for the duration of each test."""
    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test-key")
    yield
    reset_shared_client()


# ---------------------------------------------------------------------------
# Request construction
# ---------------------------------------------------------------------------
def test_request_matches_the_messages_api_contract():
    captured = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json=_answer())

    _provider_returning(handler).generate(PROMPT)

    assert captured["url"].endswith("/v1/messages")
    assert captured["headers"]["x-api-key"] == "sk-ant-test-key"
    assert captured["headers"]["anthropic-version"] == ANTHROPIC_VERSION

    body = captured["body"]
    assert body["model"] == get_settings().anthropic_model
    assert body["max_tokens"] == MAX_TOKENS
    assert body["system"] == PROMPT.system
    # The prompt's turns must pass through untouched -- widening the body here
    # would widen what leaves the platform.
    assert body["messages"] == PROMPT.messages
    assert set(body) == {"model", "max_tokens", "system", "messages"}


def test_missing_key_fails_without_calling_the_provider(monkeypatch):
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")

    def handler(request):  # pragma: no cover - must never run
        raise AssertionError("provider was called without a key")

    with pytest.raises(AIProviderError) as caught:
        _provider_returning(handler).generate(PROMPT)

    assert caught.value.retryable is False


def test_health_reports_configuration_state(monkeypatch):
    assert AnthropicProvider().health() == "ok"
    monkeypatch.setattr(get_settings(), "anthropic_api_key", "")
    assert AnthropicProvider().health() == "unavailable"


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------
def test_successful_response_is_parsed():
    result = _provider_with(200, _answer()).generate(PROMPT)

    assert result.text == "Tracking updates within one business day."
    assert result.model == "claude-sonnet-4-5"
    assert result.stop_reason == "end_turn"


def test_multiple_text_blocks_are_concatenated():
    payload = {
        "content": [
            {"type": "text", "text": "First part. "},
            {"type": "thinking", "text": "ignored"},
            {"type": "text", "text": "Second part."},
        ],
        "model": "claude-sonnet-4-5",
        "stop_reason": "end_turn",
    }
    assert _provider_with(200, payload).generate(PROMPT).text == "First part. Second part."


@pytest.mark.parametrize(
    "text",
    ["UNSUPPORTED_TOPIC", "UNSUPPORTED_TOPIC.", "**UNSUPPORTED_TOPIC**", " unsupported_topic "],
)
def test_decline_marker_is_normalised(text):
    """A dressed-up marker must still trigger the escalation path."""
    assert _provider_with(200, _answer(text)).generate(PROMPT).text == "UNSUPPORTED_TOPIC"


def test_a_real_answer_is_not_mistaken_for_the_marker():
    text = "I cannot answer that, so UNSUPPORTED_TOPIC would apply here."
    assert _provider_with(200, _answer(text)).generate(PROMPT).text == text


@pytest.mark.parametrize(
    "payload",
    [
        {"content": [], "model": "m", "stop_reason": "end_turn"},
        {"content": [{"type": "text", "text": "   "}], "model": "m"},
        {"model": "m", "stop_reason": "end_turn"},
    ],
)
def test_empty_or_malformed_content_is_retryable(payload):
    with pytest.raises(AIProviderError) as caught:
        _provider_with(200, payload).generate(PROMPT)
    assert caught.value.retryable is True


def test_non_json_body_is_retryable():
    with pytest.raises(AIProviderError) as caught:
        _provider_with(200, body=b"<html>gateway</html>").generate(PROMPT)
    assert caught.value.retryable is True


def test_truncated_response_never_reaches_the_customer():
    """A reply cut off at the token limit is a failure, not an answer."""
    with pytest.raises(AIProviderError) as caught:
        _provider_with(200, _answer("The refund process begins when", "max_tokens")).generate(
            PROMPT
        )
    assert caught.value.retryable is False
    assert "truncated" in str(caught.value).lower()


# ---------------------------------------------------------------------------
# Failure mapping
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("status", "retryable"),
    [
        (400, False),
        (401, False),
        (403, False),
        (404, False),
        (413, False),
        (429, True),
        (500, True),
        (502, True),
        (503, True),
        (529, True),
    ],
)
def test_http_status_maps_to_the_retry_policy(status, retryable):
    with pytest.raises(AIProviderError) as caught:
        _provider_with(status, {"error": {"message": "provider detail"}}).generate(PROMPT)

    assert caught.value.retryable is retryable
    # Provider error bodies are never echoed outward.
    assert "provider detail" not in str(caught.value)


@pytest.mark.parametrize(
    "exception",
    [httpx.ConnectTimeout("slow"), httpx.ReadTimeout("slow"), httpx.ConnectError("refused")],
)
def test_transport_failures_are_retryable(exception):
    def handler(request):
        raise exception

    with pytest.raises(AIProviderError) as caught:
        _provider_returning(handler).generate(PROMPT)
    assert caught.value.retryable is True


# ---------------------------------------------------------------------------
# Behaviour through the service the rest of the application uses
# ---------------------------------------------------------------------------
def test_service_retries_a_retryable_failure_then_falls_back():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        return httpx.Response(503, json={})

    result = AIIntegrationService(_provider_returning(handler)).generate_response(_chat_context())

    assert calls["count"] == get_settings().ai_max_retries + 1
    assert result.outcome.value == "PROVIDER_FAILURE"
    # The customer sees a safe fallback, never the provider's error.
    assert "503" not in result.text


def test_service_does_not_retry_a_non_retryable_failure():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1
        return httpx.Response(401, json={})

    AIIntegrationService(_provider_returning(handler)).generate_response(_chat_context())
    assert calls["count"] == 1


def test_service_reports_unsupported_for_a_declined_answer():
    result = AIIntegrationService(
        _provider_with(200, _answer("UNSUPPORTED_TOPIC."))
    ).generate_response(_chat_context())
    assert result.outcome.value == "UNSUPPORTED"


def test_factory_selects_this_provider_by_configuration():
    assert isinstance(build_provider("anthropic"), AnthropicProvider)


def _chat_context():
    from app.modules.ai_integration.contracts import ChatContext

    return ChatContext(
        conversation_id="00000000-0000-4000-8000-000000000000",
        inquiry_type="ORDER",
        customer_message="Where is my order?",
    )
