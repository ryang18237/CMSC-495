"""Feedback Module and the event published for asynchronous analysis."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FeedbackEvent


def _answered_message(client: TestClient, auth: dict[str, str], conversation_id: str) -> str:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=auth,
        json={"message": "Which certification should I work toward next?"},
    )
    return str(response.json()["messageId"])


def test_feedback_is_recorded(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    message_id = _answered_message(client, customer_auth, conversation_id)

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/feedback",
        headers=customer_auth,
        json={
            "messageId": message_id,
            "rating": "HELPFUL",
            "comment": "The answer resolved my issue.",
        },
    )
    assert response.status_code == 201

    body = response.json()
    assert body["rating"] == "HELPFUL"
    assert body["messageId"] == message_id


def test_feedback_publishes_an_event_without_customer_identifiers(
    client: TestClient,
    customer_auth: dict[str, str],
    conversation_id: str,
    db_session: Session,
) -> None:
    message_id = _answered_message(client, customer_auth, conversation_id)
    client.post(
        f"/api/v1/conversations/{conversation_id}/feedback",
        headers=customer_auth,
        json={"messageId": message_id, "rating": "UNHELPFUL"},
    )

    events = list(db_session.scalars(select(FeedbackEvent)))
    assert len(events) == 1
    assert events[0].processed is False
    assert "submittedBy" not in events[0].payload
    assert "comment" not in events[0].payload


def test_feedback_for_a_foreign_message_returns_404(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/feedback",
        headers=customer_auth,
        json={"messageId": str(uuid.uuid4()), "rating": "HELPFUL"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "MESSAGE_NOT_FOUND"


def test_duplicate_feedback_is_rejected(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    message_id = _answered_message(client, customer_auth, conversation_id)
    payload = {"messageId": message_id, "rating": "HELPFUL"}

    client.post(
        f"/api/v1/conversations/{conversation_id}/feedback", headers=customer_auth, json=payload
    )
    second = client.post(
        f"/api/v1/conversations/{conversation_id}/feedback", headers=customer_auth, json=payload
    )
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "FEEDBACK_ALREADY_RECORDED"


def test_over_long_comment_is_rejected(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    message_id = _answered_message(client, customer_auth, conversation_id)

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/feedback",
        headers=customer_auth,
        json={"messageId": message_id, "rating": "HELPFUL", "comment": "c" * 1001},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_COMMENT"


def test_invalid_rating_is_rejected(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    message_id = _answered_message(client, customer_auth, conversation_id)

    response = client.post(
        f"/api/v1/conversations/{conversation_id}/feedback",
        headers=customer_auth,
        json={"messageId": message_id, "rating": "AMAZING"},
    )
    assert response.status_code == 422
