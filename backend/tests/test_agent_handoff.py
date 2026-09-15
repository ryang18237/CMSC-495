"""Human agent escalation path.

Covers the loop that matters: a member escalates, a counsellor replies, and the
member sees the reply in the same conversation without doing anything special.
"""

import uuid

from fastapi.testclient import TestClient

REPLY = "Happy to help. Based on your network coursework, let's look at two options."


def _escalated_case(client: TestClient, member_auth: dict[str, str]) -> tuple[str, str]:
    """Drive a real escalation and return (conversationId, caseId)."""
    conversation_id = client.post("/api/v1/conversations", headers=member_auth).json()[
        "conversationId"
    ]
    answered = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=member_auth,
        json={"message": "Which certification should I work toward next?"},
    )
    assert answered.json()["status"] == "ANSWERED"

    escalated = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=member_auth,
        json={"message": "I want to speak to a human please"},
    )
    assert escalated.json()["escalationReason"] == "CUSTOMER_REQUEST"

    case_id = client.get("/api/v1/agent/cases", headers=_AGENT_HEADERS[0]).json()[0]["caseId"]
    return conversation_id, case_id


# Filled in by the fixture-using tests below; keeps the helper signature short.
_AGENT_HEADERS: list[dict[str, str]] = [{}]


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------
def test_counsellor_reply_reaches_the_member(
    client: TestClient, customer_auth: dict[str, str], agent_auth: dict[str, str]
) -> None:
    _AGENT_HEADERS[0] = agent_auth
    conversation_id, case_id = _escalated_case(client, customer_auth)

    posted = client.post(
        f"/api/v1/agent/cases/{case_id}/reply",
        headers=agent_auth,
        json={"message": REPLY},
    )
    assert posted.status_code == 201
    assert posted.json()["sender"] == "AGENT"
    assert posted.json()["content"] == REPLY

    # The member reads it through the endpoint they already use.
    history = client.get(f"/api/v1/conversations/{conversation_id}", headers=customer_auth).json()
    senders = [message["sender"] for message in history["messages"]]
    assert senders[-1] == "AGENT"
    assert history["messages"][-1]["content"] == REPLY


def test_replying_claims_the_case(
    client: TestClient, customer_auth: dict[str, str], agent_auth: dict[str, str]
) -> None:
    """Answering a member is taking responsibility, so assignment follows."""
    _AGENT_HEADERS[0] = agent_auth
    _, case_id = _escalated_case(client, customer_auth)

    assert client.get(f"/api/v1/agent/cases/{case_id}", headers=agent_auth).json()["status"] == (
        "QUEUED"
    )

    client.post(f"/api/v1/agent/cases/{case_id}/reply", headers=agent_auth, json={"message": REPLY})

    assert client.get(f"/api/v1/agent/cases/{case_id}", headers=agent_auth).json()["status"] == (
        "ASSIGNED"
    )


def test_a_counsellor_reply_is_not_counted_as_an_assistant_turn(
    client: TestClient, customer_auth: dict[str, str], agent_auth: dict[str, str]
) -> None:
    """A human reply has no ANSWERED/ESCALATED status of its own.

    Reusing those would inflate the assistant's counters in the ops panel and
    make the escalation rate meaningless.
    """
    _AGENT_HEADERS[0] = agent_auth
    conversation_id, case_id = _escalated_case(client, customer_auth)
    client.post(f"/api/v1/agent/cases/{case_id}/reply", headers=agent_auth, json={"message": REPLY})

    history = client.get(f"/api/v1/conversations/{conversation_id}", headers=customer_auth).json()
    agent_message = history["messages"][-1]
    assert agent_message["status"] is None
    assert agent_message["escalationReason"] is None

    metrics = client.get("/api/v1/ops/metrics", headers=agent_auth).json()
    assert metrics["conversationTurns"]["total"] == 2


def test_member_can_continue_the_conversation_after_a_reply(
    client: TestClient, customer_auth: dict[str, str], agent_auth: dict[str, str]
) -> None:
    _AGENT_HEADERS[0] = agent_auth
    conversation_id, case_id = _escalated_case(client, customer_auth)
    client.post(f"/api/v1/agent/cases/{case_id}/reply", headers=agent_auth, json={"message": REPLY})

    follow_up = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=customer_auth,
        json={"message": "Thanks, which one is quicker?"},
    )
    assert follow_up.status_code == 200


# ---------------------------------------------------------------------------
# Claiming
# ---------------------------------------------------------------------------
def test_claiming_assigns_without_replying(
    client: TestClient, customer_auth: dict[str, str], agent_auth: dict[str, str]
) -> None:
    _AGENT_HEADERS[0] = agent_auth
    _, case_id = _escalated_case(client, customer_auth)

    claimed = client.post(f"/api/v1/agent/cases/{case_id}/claim", headers=agent_auth)
    assert claimed.status_code == 200
    assert claimed.json()["status"] == "ASSIGNED"

    # Idempotent for the same counsellor -- a double click must not fail.
    assert client.post(f"/api/v1/agent/cases/{case_id}/claim", headers=agent_auth).status_code == (
        200
    )


def test_workload_counts_open_cases(
    client: TestClient, customer_auth: dict[str, str], agent_auth: dict[str, str]
) -> None:
    _AGENT_HEADERS[0] = agent_auth
    assert client.get("/api/v1/agent/workload", headers=agent_auth).json()["openCases"] == 0

    _, case_id = _escalated_case(client, customer_auth)
    client.post(f"/api/v1/agent/cases/{case_id}/claim", headers=agent_auth)

    assert client.get("/api/v1/agent/workload", headers=agent_auth).json()["openCases"] == 1


# ---------------------------------------------------------------------------
# Guard rails
# ---------------------------------------------------------------------------
def test_a_member_cannot_post_a_counsellor_reply(
    client: TestClient, customer_auth: dict[str, str], agent_auth: dict[str, str]
) -> None:
    _AGENT_HEADERS[0] = agent_auth
    _, case_id = _escalated_case(client, customer_auth)

    response = client.post(
        f"/api/v1/agent/cases/{case_id}/reply",
        headers=customer_auth,
        json={"message": "Approving my own case"},
    )
    assert response.status_code == 403


def test_reply_requires_authentication(client: TestClient) -> None:
    response = client.post(f"/api/v1/agent/cases/{uuid.uuid4()}/reply", json={"message": REPLY})
    assert response.status_code == 401


def test_reply_to_a_missing_case_returns_404(
    client: TestClient, agent_auth: dict[str, str]
) -> None:
    response = client.post(
        f"/api/v1/agent/cases/{uuid.uuid4()}/reply",
        headers=agent_auth,
        json={"message": REPLY},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "CASE_NOT_FOUND"


def test_blank_reply_is_rejected(
    client: TestClient, customer_auth: dict[str, str], agent_auth: dict[str, str]
) -> None:
    _AGENT_HEADERS[0] = agent_auth
    _, case_id = _escalated_case(client, customer_auth)

    response = client.post(
        f"/api/v1/agent/cases/{case_id}/reply", headers=agent_auth, json={"message": "   "}
    )
    assert response.status_code == 422


def test_cannot_reply_to_a_resolved_case(
    client: TestClient, customer_auth: dict[str, str], agent_auth: dict[str, str]
) -> None:
    """Once the member has been told it is finished, the thread is closed."""
    _AGENT_HEADERS[0] = agent_auth
    _, case_id = _escalated_case(client, customer_auth)

    client.patch(f"/api/v1/agent/cases/{case_id}", headers=agent_auth, json={"status": "RESOLVED"})

    response = client.post(
        f"/api/v1/agent/cases/{case_id}/reply", headers=agent_auth, json={"message": REPLY}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CASE_NOT_OPEN"


def test_replies_endpoint_returns_only_counsellor_messages(
    client: TestClient, customer_auth: dict[str, str], agent_auth: dict[str, str]
) -> None:
    _AGENT_HEADERS[0] = agent_auth
    _, case_id = _escalated_case(client, customer_auth)
    client.post(f"/api/v1/agent/cases/{case_id}/reply", headers=agent_auth, json={"message": REPLY})

    replies = client.get(f"/api/v1/agent/cases/{case_id}/replies", headers=agent_auth).json()
    assert [message["sender"] for message in replies] == ["AGENT"]
