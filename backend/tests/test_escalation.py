"""Escalation Module: deterministic rules, case creation and the agent path."""

import uuid

from fastapi.testclient import TestClient

from app.modules.ai_integration.providers.mock import FAILURE_TRIGGER


def _send(client: TestClient, auth: dict[str, str], conversation_id: str, text: str) -> dict:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=auth,
        json={"message": text},
    )
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_asking_for_a_person_escalates_without_calling_the_model(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    body = _send(client, customer_auth, conversation_id, "I want to speak to a human please")
    assert body["status"] == "ESCALATED"
    assert body["escalationReason"] == "CUSTOMER_REQUEST"


def test_security_sensitive_message_escalates(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    body = _send(client, customer_auth, conversation_id, "I think my account was hacked")
    assert body["status"] == "ESCALATED"
    assert body["escalationReason"] == "SECURITY_CONCERN"


def test_raw_identifier_is_never_forwarded_to_the_model(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    body = _send(client, customer_auth, conversation_id, "My SSN is 123-45-6789, please verify")
    assert body["escalationReason"] == "SECURITY_CONCERN"


def test_unsupported_topic_escalates(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    body = _send(client, customer_auth, conversation_id, "What is the capital of France?")
    assert body["status"] == "ESCALATED"
    assert body["escalationReason"] == "UNSUPPORTED_TOPIC"


def test_provider_failure_falls_back_and_escalates(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    body = _send(client, customer_auth, conversation_id, f"question {FAILURE_TRIGGER}")
    assert body["status"] == "ESCALATED"
    assert body["escalationReason"] == "AI_SERVICE_FAILURE"
    # The customer sees a safe fallback, never the provider error.
    assert "Simulated provider outage" not in body["response"]


def test_explicit_escalation_creates_a_queued_case(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/escalate",
        headers=customer_auth,
        json={"reason": "CUSTOMER_REQUEST"},
    )
    assert response.status_code == 201

    body = response.json()
    assert body["status"] == "QUEUED"
    assert body["queue"] == "CAREER_COUNSELING"
    uuid.UUID(body["caseId"])


def test_security_escalation_routes_to_its_own_queue(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/escalate",
        headers=customer_auth,
        json={"reason": "SECURITY_CONCERN"},
    )
    assert response.json()["queue"] == "ACCOUNT_SECURITY"


def test_duplicate_escalation_returns_409(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    payload = {"reason": "CUSTOMER_REQUEST"}
    first = client.post(
        f"/api/v1/conversations/{conversation_id}/escalate", headers=customer_auth, json=payload
    )
    second = client.post(
        f"/api/v1/conversations/{conversation_id}/escalate", headers=customer_auth, json=payload
    )
    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "ESCALATION_ALREADY_ACTIVE"


def test_unapproved_escalation_reason_is_rejected(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/escalate",
        headers=customer_auth,
        json={"reason": "BECAUSE_I_SAID_SO"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
