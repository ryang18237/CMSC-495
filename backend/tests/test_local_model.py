"""Tests for the local-model provider (Ollama).

The unit tests stub HTTP with `httpx.MockTransport`, so they need no daemon
and make no network call -- CI runs them on every push with nothing
installed. The last test is different on purpose: it starts a real
OpenAI-compatible server on a loopback port and drives the whole provider
through real sockets, which is the only way to catch a mistake in the URL,
the method or the headers that a mock transport would happily accept.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx
import pytest

from app.config import get_settings
from app.modules.ai_integration.contracts import AIOutcome, AIProviderError, Prompt
from app.modules.ai_integration.providers._http import reset_shared_http_client
from app.modules.ai_integration.providers.ollama_provider import (
    PLACEHOLDER_KEY,
    OllamaProvider,
    installed_models,
    reset_probe_cache,
)
from app.modules.ai_integration.providers.openai_provider import MAX_TOKENS, OpenAIProvider
from app.modules.ai_integration.service import (
    AIIntegrationService,
    available_providers,
    build_provider,
    resolve_auto,
)

PROMPT = Prompt(
    system="You are a career assistant.\n- Credentials already held: CompTIA A+",
    messages=[{"role": "user", "content": "What should I study next?"}],
)

MODEL = "llama3.2"


@pytest.fixture(autouse=True)
def _clean_probe_cache():
    """Readiness is cached for a few seconds; each test starts fresh."""
    reset_probe_cache()
    yield
    reset_probe_cache()
    reset_shared_http_client()


def _provider(handler):
    return OllamaProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))


def _models_body(*names):
    return {"object": "list", "data": [{"id": name, "object": "model"} for name in names]}


def _answer_body(text="Security+ is the natural next step."):
    return {
        "model": MODEL,
        "choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
    }


# ---------------------------------------------------------------------------
# Readiness: a question about the machine, not about configuration
# ---------------------------------------------------------------------------
def test_unavailable_when_the_daemon_is_not_running():
    """Nothing installed is the common case. It must not raise."""

    def handler(request):
        raise httpx.ConnectError("connection refused")

    assert _provider(handler).health() == "unavailable"


def test_degraded_when_the_daemon_is_up_but_the_model_is_not_pulled():
    """Offering a model that is not installed would 404 every conversation."""
    provider = _provider(lambda request: httpx.Response(200, json=_models_body("mistral")))
    assert provider.health() == "degraded"


def test_ok_when_the_model_is_installed():
    provider = _provider(lambda request: httpx.Response(200, json=_models_body(MODEL)))
    assert provider.health() == "ok"


def test_the_latest_suffix_is_not_a_different_model():
    """`ollama pull llama3.2` lists as "llama3.2:latest"; a member means that one."""
    provider = _provider(lambda request: httpx.Response(200, json=_models_body(f"{MODEL}:latest")))
    assert provider.health() == "ok"


@pytest.mark.parametrize("payload", [{}, {"data": "nope"}, {"data": [1, 2]}, []])
def test_a_malformed_model_list_is_not_a_crash(payload):
    assert installed_models(payload) == set()


def test_readiness_is_probed_once_per_burst():
    """It runs on every conversation turn, so it is cached for a few seconds."""
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, json=_models_body(MODEL))

    provider = _provider(handler)
    assert [provider.health() for _ in range(5)] == ["ok"] * 5
    assert calls == ["/v1/models"]


# ---------------------------------------------------------------------------
# Generating
# ---------------------------------------------------------------------------
def test_no_api_key_is_required():
    """The whole point: a real model with nothing to sign up for."""
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json=_answer_body())

    reply = _provider(handler).generate(PROMPT)

    assert reply.text == "Security+ is the natural next step."
    # Ollama documents the header as required and ignored, so a constant
    # stands in for a key. It is not a credential and never has to be one.
    assert seen["auth"] == f"Bearer {PLACEHOLDER_KEY}"


def test_the_member_facts_reach_the_model():
    """A local model is still given the same minimised prompt as a hosted one."""
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_answer_body())

    _provider(handler).generate(PROMPT)

    messages = seen["body"]["messages"]
    assert messages[0]["role"] == "system"
    assert "CompTIA A+" in messages[0]["content"]
    assert messages[-1]["content"] == "What should I study next?"


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------
@pytest.fixture
def auto_selection(monkeypatch):
    """The shipped default. The test suite otherwise pins a provider."""
    monkeypatch.setattr(get_settings(), "ai_provider", "auto")


def test_auto_prefers_a_local_model_when_one_is_running(monkeypatch, auto_selection):
    monkeypatch.setattr(OllamaProvider, "health", lambda self: "ok")
    assert resolve_auto() == "ollama"
    assert build_provider().name == "ollama"


def test_auto_never_falls_back_to_the_builtin_advisor(monkeypatch, auto_selection):
    """No Ollama means no answer, not a canned one.

    Falling back here would be the worst of both: the member reads template
    text as the assistant's considered view, and nobody learns that the model
    was never running. `auto` stays on the local model so the failure is the
    true one, and the member is told what to start.
    """
    monkeypatch.setattr(OllamaProvider, "health", lambda self: "unavailable")
    assert resolve_auto() == "ollama"
    assert build_provider().name == "ollama"


def test_naming_a_provider_overrides_the_guess(monkeypatch):
    """`AI_PROVIDER=builtin` means builtin even on a machine running Ollama."""
    monkeypatch.setattr(OllamaProvider, "health", lambda self: "ok")
    monkeypatch.setattr(get_settings(), "ai_provider", "builtin")
    assert build_provider().name == "builtin"


def test_a_local_model_is_only_offered_when_it_can_answer(monkeypatch):
    monkeypatch.setattr(OllamaProvider, "health", lambda self: "degraded")
    assert "ollama" not in {option.provider_id for option in available_providers()}

    monkeypatch.setattr(OllamaProvider, "health", lambda self: "ok")
    offered = {option.provider_id: option for option in available_providers()}
    assert offered["ollama"].label == "Local model"
    assert offered["ollama"].model == get_settings().ollama_model


# ---------------------------------------------------------------------------
# End to end, over a real socket
# ---------------------------------------------------------------------------
class _StubOllama(BaseHTTPRequestHandler):
    """The two endpoints this provider uses, in OpenAI's shapes."""

    def log_message(self, *args):  # keep the test output clean
        pass

    def _send(self, payload):
        body = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(_models_body(f"{MODEL}:latest"))

    def do_POST(self):
        length = int(self.headers.get("content-length", 0))
        request = json.loads(self.rfile.read(length) or b"{}")
        # Echo a fact back so the test proves the prompt really arrived.
        held = "CompTIA A+" in request["messages"][0]["content"]
        self._send(_answer_body(f"Next after A+: Security+. (facts received: {held})"))


@pytest.fixture
def stub_ollama(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), _StubOllama)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(get_settings(), "ollama_base_url", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr(get_settings(), "ollama_model", MODEL)
    reset_probe_cache()
    yield
    server.shutdown()
    server.server_close()


def test_a_real_request_reaches_a_real_server(stub_ollama):
    """Catches a wrong path, method or header that a mock transport would not."""
    provider = OllamaProvider()

    assert provider.health() == "ok"
    reply = provider.generate(PROMPT)

    assert "Security+" in reply.text
    assert "facts received: True" in reply.text
    assert reply.stop_reason == "stop"


# ---------------------------------------------------------------------------
# Latency: the failure that looked like "the service is down"
# ---------------------------------------------------------------------------
def test_a_local_model_gets_a_timeout_it_can_actually_meet():
    """8 seconds is a network budget. Loading weights off disk is not network.

    The shipped default failed essentially every real local request, and the
    member saw "assistant service unavailable" -- indistinguishable, from the
    chat, from the platform being broken.
    """
    settings = get_settings()
    provider = OllamaProvider()

    assert provider._timeout == settings.ollama_timeout_seconds
    assert provider._timeout >= 60, "a cold local model routinely needs a minute"
    assert settings.ai_timeout_seconds < provider._timeout


def test_a_slow_local_model_is_not_retried():
    """Retrying a slow answer just makes the member wait for two of them."""
    assert OllamaProvider().retry_budget_seconds == 0.0


def test_a_hosted_provider_keeps_its_retry_budget():
    """The change is local-only: nothing about hosted retry behaviour moves."""
    from app.modules.ai_integration.providers.builtin import BuiltInAdvisor

    assert BuiltInAdvisor().retry_budget_seconds == get_settings().ai_retry_budget_seconds


def test_one_slow_turn_is_answered_rather_than_escalated(monkeypatch):
    """End to end: a model that takes longer than the old budget still answers."""
    from app.modules.ai_integration.contracts import ChatContext
    from app.modules.ai_integration.service import AIIntegrationService

    slow = 0.3
    monkeypatch.setattr(get_settings(), "ai_timeout_seconds", 0.05)
    monkeypatch.setattr(get_settings(), "ollama_timeout_seconds", 5.0)

    def handler(request):
        import time as _time

        _time.sleep(slow)
        return httpx.Response(200, json=_answer_body("Network+ next."))

    provider = _provider(handler)
    result = AIIntegrationService(provider).generate_response(
        ChatContext(
            conversation_id="c1",
            inquiry_type="CREDENTIAL",
            customer_message="what next?",
        )
    )

    assert result.outcome.name == "ANSWERED", result.error_detail
    assert "Network+" in result.text


def test_a_provider_failure_is_written_to_the_log(caplog):
    """It was recorded on the result and then dropped, so nothing could be diagnosed."""
    from app.modules.ai_integration.contracts import AIProviderError
    from app.modules.ai_integration.service import AIIntegrationService

    with caplog.at_level("WARNING", logger="app.ai"):
        AIIntegrationService(OllamaProvider()).handle_provider_failure(
            AIProviderError("Provider did not respond within 120s.", retryable=True),
            latency_ms=120_000,
        )

    assert "ollama" in caplog.text
    assert "did not respond within 120s" in caplog.text


# ---------------------------------------------------------------------------
# The reply length cap: the second failure that looked like "the service is down"
# ---------------------------------------------------------------------------
def test_the_length_cap_is_sent_under_the_name_this_server_reads():
    """Ollama reads `max_tokens`. OpenAI's newer name is silently ignored.

    This is the whole bug in one assertion. An unrecognised field is dropped
    rather than refused, so the wrong name does not fail -- it removes the cap
    and lets a one-paragraph question generate until the model's own 4096-token
    default, which on a CPU is minutes. The turn then times out and the member
    is handed to a counsellor, which reads as a broken assistant.
    """
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_answer_body())

    _provider(handler).generate(PROMPT)

    assert seen["body"]["max_tokens"] == MAX_TOKENS
    assert "max_completion_tokens" not in seen["body"]


def test_a_hosted_provider_still_uses_the_name_openai_requires():
    """OpenAI rejects the old name on its newer models, so the two must differ."""
    assert OpenAIProvider.token_limit_field == "max_completion_tokens"
    assert OllamaProvider.token_limit_field == "max_tokens"


def test_an_answer_in_the_reasoning_field_is_still_an_answer():
    """Some local models leave `content` empty and put the reply in `reasoning`.

    Escalating there would hand a member to a person while holding the answer
    they asked for.
    """

    def handler(request):
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "choices": [
                    {
                        "message": {"content": "", "reasoning": "Security+ is the next step."},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    assert _provider(handler).generate(PROMPT).text == "Security+ is the next step."


def test_a_stopped_daemon_is_explained_rather_than_called_an_outage(monkeypatch):
    """"The model is not running" is fixable in a minute. Say which minute.

    The generic outage message gave the reader nothing to act on, so a stopped
    daemon read as a broken product.
    """
    monkeypatch.setattr(OllamaProvider, "health", lambda self: "unavailable")
    service = AIIntegrationService(provider=OllamaProvider())

    result = service.handle_provider_failure(AIProviderError("connect refused"))

    assert result.outcome == AIOutcome.PROVIDER_FAILURE
    assert "not running" in result.text
    assert "run.py" in result.text
    # The reason still never reaches the member.
    assert "connect refused" not in result.text
    assert result.error_detail == "connect refused"


def test_a_running_model_that_fails_is_not_blamed_on_the_daemon(monkeypatch):
    """A 500 from a healthy daemon is an outage, not a setup problem."""
    monkeypatch.setattr(OllamaProvider, "health", lambda self: "ok")
    service = AIIntegrationService(provider=OllamaProvider())

    result = service.handle_provider_failure(AIProviderError("Provider returned 500."))

    assert "not running" not in result.text
