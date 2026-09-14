"""Conversation Management Module through the public API."""

import uuid

from fastapi.testclient import TestClient


def test_create_conversation_returns_201(client: TestClient, customer_auth: dict[str, str]) -> None:
    response = client.post("/api/v1/conversations", headers=customer_auth)
    assert response.status_code == 201

    body = response.json()
    assert body["status"] == "ACTIVE"
    uuid.UUID(body["conversationId"])
    assert "createdAt" in body


def test_message_is_answered_end_to_end(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=customer_auth,
        json={"message": "Which certification should I work toward next?"},
    )
    assert response.status_code == 200

    body = response.json()
    assert body["conversationId"] == conversation_id
    assert body["status"] == "ANSWERED"
    assert body["escalationReason"] is None
    assert 0 < len(body["response"]) <= 4000
    uuid.UUID(body["messageId"])


def test_history_records_both_turns_with_sources(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=customer_auth,
        json={"message": "Which certification should I work toward next?"},
    )
    response = client.get(f"/api/v1/conversations/{conversation_id}", headers=customer_auth)
    assert response.status_code == 200

    messages = response.json()["messages"]
    assert [m["sender"] for m in messages] == ["CUSTOMER", "ASSISTANT"]
    # Explainability: the answer names the knowledge articles it drew on.
    assert messages[1]["sources"]


def test_multi_turn_conversation_keeps_context(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    for text in ("How do I describe this on a resume?", "What about an apprenticeship instead?"):
        response = client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=customer_auth,
            json={"message": text},
        )
        assert response.status_code == 200

    history = client.get(f"/api/v1/conversations/{conversation_id}", headers=customer_auth).json()
    assert len(history["messages"]) == 4


def test_another_customer_cannot_read_the_conversation(
    client: TestClient, other_customer_auth: dict[str, str], conversation_id: str
) -> None:
    response = client.get(f"/api/v1/conversations/{conversation_id}", headers=other_customer_auth)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_another_customer_cannot_post_into_the_conversation(
    client: TestClient, other_customer_auth: dict[str, str], conversation_id: str
) -> None:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=other_customer_auth,
        json={"message": "Show me their service record."},
    )
    assert response.status_code == 403


def test_missing_conversation_returns_404(
    client: TestClient, customer_auth: dict[str, str]
) -> None:
    response = client.get(f"/api/v1/conversations/{uuid.uuid4()}", headers=customer_auth)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CONVERSATION_NOT_FOUND"


def test_malformed_identifier_returns_400(
    client: TestClient, customer_auth: dict[str, str]
) -> None:
    response = client.get("/api/v1/conversations/not-a-uuid", headers=customer_auth)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_IDENTIFIER"


def test_blank_message_returns_422(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=customer_auth,
        json={"message": "   "},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_MESSAGE"


def test_over_long_message_returns_422(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=customer_auth,
        json={"message": "x" * 2001},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_MESSAGE"


def test_missing_field_returns_422_invalid_request(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=customer_auth,
        json={},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_oversized_payload_returns_413(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=customer_auth,
        json={"message": "y" * 70000},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


def test_closed_conversation_returns_409(
    client: TestClient,
    customer_auth: dict[str, str],
    agent_auth: dict[str, str],
    conversation_id: str,
) -> None:
    escalated = client.post(
        f"/api/v1/conversations/{conversation_id}/escalate",
        headers=customer_auth,
        json={"reason": "CUSTOMER_REQUEST"},
    )
    case_id = escalated.json()["caseId"]

    closed = client.patch(
        f"/api/v1/agent/cases/{case_id}", headers=agent_auth, json={"status": "CLOSED"}
    )
    assert closed.status_code == 200

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=customer_auth,
        json={"message": "One more question about my resume."},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONVERSATION_CLOSED"


def test_rate_limit_returns_429(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str, monkeypatch
) -> None:
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_messages_per_minute", 2)

    statuses = []
    for _ in range(3):
        response = client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=customer_auth,
            json={"message": "How do I describe this on a resume?"},
        )
        statuses.append(response.status_code)

    assert statuses[-1] == 429
