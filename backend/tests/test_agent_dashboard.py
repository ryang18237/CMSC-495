"""Human Agent Dashboard endpoints and their role-based authorization."""

import uuid

from fastapi.testclient import TestClient


def _escalated_case(client: TestClient, auth: dict[str, str], conversation_id: str) -> str:
    client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=auth,
        json={"message": "Which certification should I work toward next?"},
    )
    response = client.post(
        f"/api/v1/conversations/{conversation_id}/escalate",
        headers=auth,
        json={"reason": "CUSTOMER_REQUEST"},
    )
    return str(response.json()["caseId"])


def test_agent_sees_the_case_with_conversation_context(
    client: TestClient,
    customer_auth: dict[str, str],
    agent_auth: dict[str, str],
    conversation_id: str,
) -> None:
    case_id = _escalated_case(client, customer_auth, conversation_id)

    response = client.get(f"/api/v1/agent/cases/{case_id}", headers=agent_auth)
    assert response.status_code == 200

    body = response.json()
    assert body["reason"] == "CUSTOMER_REQUEST"
    assert body["status"] == "QUEUED"
    # The handover carries the conversation so the customer does not repeat themselves.
    assert len(body["messages"]) >= 2
    assert body["summary"]


def test_customer_cannot_read_an_agent_case(
    client: TestClient, customer_auth: dict[str, str], conversation_id: str
) -> None:
    case_id = _escalated_case(client, customer_auth, conversation_id)

    response = client.get(f"/api/v1/agent/cases/{case_id}", headers=customer_auth)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_agent_case_requires_authentication(client: TestClient) -> None:
    response = client.get(f"/api/v1/agent/cases/{uuid.uuid4()}")
    assert response.status_code == 401


def test_missing_case_returns_404(client: TestClient, agent_auth: dict[str, str]) -> None:
    response = client.get(f"/api/v1/agent/cases/{uuid.uuid4()}", headers=agent_auth)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CASE_NOT_FOUND"


def test_agent_queue_lists_open_cases(
    client: TestClient,
    customer_auth: dict[str, str],
    agent_auth: dict[str, str],
    conversation_id: str,
) -> None:
    case_id = _escalated_case(client, customer_auth, conversation_id)

    response = client.get("/api/v1/agent/cases", headers=agent_auth)
    assert response.status_code == 200
    assert case_id in [item["caseId"] for item in response.json()]


def test_agent_can_advance_a_case(
    client: TestClient,
    customer_auth: dict[str, str],
    agent_auth: dict[str, str],
    conversation_id: str,
) -> None:
    case_id = _escalated_case(client, customer_auth, conversation_id)

    assigned = client.patch(
        f"/api/v1/agent/cases/{case_id}", headers=agent_auth, json={"status": "ASSIGNED"}
    )
    assert assigned.json()["status"] == "ASSIGNED"

    resolved = client.patch(
        f"/api/v1/agent/cases/{case_id}", headers=agent_auth, json={"status": "RESOLVED"}
    )
    assert resolved.json()["status"] == "RESOLVED"
