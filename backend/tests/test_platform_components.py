"""Components the architecture declares that the Alpha implements in barebones form.

Cache, Monitoring and Logging, and the reviewed-AI-configuration path each have
a real interface and real call sites; the tests here pin the behaviour that
matters rather than the depth that is deliberately missing.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.bootstrap import CUSTOMER_ID
from app.modules.cache.service import InMemoryCache, NullCache, get_cache
from app.modules.customer_data.adapter import CustomerDataAdapter
from app.modules.knowledge.service import KnowledgeBaseService


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
def test_cache_returns_stored_values_and_counts_hits() -> None:
    cache = InMemoryCache()
    assert cache.get("missing") is None

    cache.set("k", ["a", "b"])
    assert cache.get("k") == ["a", "b"]

    stats = cache.stats()
    assert stats.hits == 1
    assert stats.misses == 1
    assert stats.entries == 1


def test_cache_expires_entries() -> None:
    cache = InMemoryCache()
    cache.set("k", "v", ttl_seconds=0)
    assert cache.get("k") is None
    assert cache.stats().evictions == 1


def test_cache_invalidates_by_prefix() -> None:
    cache = InMemoryCache()
    cache.set("customer:1:BILLING", "a")
    cache.set("customer:1:ORDER", "b")
    cache.set("customer:2:ORDER", "c")

    assert cache.invalidate("customer:1:") == 2
    assert cache.get("customer:1:BILLING") is None
    assert cache.get("customer:2:ORDER") == "c"


def test_null_cache_never_stores() -> None:
    cache = NullCache()
    cache.set("k", "v")
    assert cache.get("k") is None


def test_knowledge_search_is_served_from_cache_on_repeat(db_session: Session) -> None:
    service = KnowledgeBaseService(db_session)
    first = service.search_articles("certification credential exam", limit=2)
    second = service.search_articles("certification credential exam", limit=2)

    assert first == second
    assert get_cache().stats().hits >= 1


def test_member_context_cache_is_keyed_by_inquiry_type(db_session: Session) -> None:
    """A cached context must never be served to a different inquiry type.

    Each type is permitted a different subset of fields, so a shared key would
    widen what reaches the AI provider.
    """
    adapter = CustomerDataAdapter(db_session)
    general = adapter.get_relevant_account_data(CUSTOMER_ID, "GENERAL")
    credential = adapter.get_relevant_account_data(CUSTOMER_ID, "CREDENTIAL")

    assert general.available_fields == ["service_branch"]
    assert "completed_training" in credential.available_fields


# ---------------------------------------------------------------------------
# Monitoring and Logging
# ---------------------------------------------------------------------------
def test_metrics_require_an_agent(client: TestClient, customer_auth: dict[str, str]) -> None:
    assert client.get("/api/v1/ops/metrics").status_code == 401
    assert client.get("/api/v1/ops/metrics", headers=customer_auth).status_code == 403


def test_metrics_record_live_traffic(
    client: TestClient,
    customer_auth: dict[str, str],
    agent_auth: dict[str, str],
    conversation_id: str,
) -> None:
    client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=customer_auth,
        json={"message": "Which certification should I work toward next?"},
    )
    client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=customer_auth,
        json={"message": "I want to speak to a human"},
    )

    body = client.get("/api/v1/ops/metrics", headers=agent_auth).json()

    assert body["requests"]["total"] > 0
    assert body["conversationTurns"]["byStatus"]["ANSWERED"] == 1
    assert body["conversationTurns"]["byStatus"]["ESCALATED"] == 1
    assert body["conversationTurns"]["escalationsByReason"]["CUSTOMER_REQUEST"] == 1
    assert body["cache"]["implementation"] in {"in-memory", "disabled"}
    assert body["instanceId"]


def test_health_reports_the_instance_and_cache(client: TestClient) -> None:
    body = client.get("/api/v1/health").json()
    assert body["instanceId"]
    assert body["dependencies"]["cache"] == "ok"


# ---------------------------------------------------------------------------
# Reviewed AI configuration
# ---------------------------------------------------------------------------
def _generate_recommendations(client: TestClient, customer_auth: dict[str, str]) -> None:
    """Two unsupported topics make one recurring pattern worth reviewing."""
    for question in ("What is the capital of France?", "Who won the game last night?"):
        conversation_id = client.post("/api/v1/conversations", headers=customer_auth).json()[
            "conversationId"
        ]
        client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            headers=customer_auth,
            json={"message": question},
        )


def test_analytics_run_produces_recommendations_pending_review(
    client: TestClient, customer_auth: dict[str, str], agent_auth: dict[str, str]
) -> None:
    _generate_recommendations(client, customer_auth)

    run = client.post("/api/v1/agent/analytics/run", headers=agent_auth)
    assert run.status_code == 200
    assert run.json()["recommendationsCreated"] >= 1

    listed = client.get("/api/v1/agent/recommendations", headers=agent_auth).json()
    assert listed
    # Nothing is ever applied automatically.
    assert all(item["reviewStatus"] == "PENDING_REVIEW" for item in listed)


def test_a_human_decision_is_recorded_and_final(
    client: TestClient, customer_auth: dict[str, str], agent_auth: dict[str, str]
) -> None:
    _generate_recommendations(client, customer_auth)
    client.post("/api/v1/agent/analytics/run", headers=agent_auth)

    recommendation_id = client.get("/api/v1/agent/recommendations", headers=agent_auth).json()[0][
        "recommendationId"
    ]

    approved = client.patch(
        f"/api/v1/agent/recommendations/{recommendation_id}",
        headers=agent_auth,
        json={"reviewStatus": "APPROVED"},
    )
    assert approved.status_code == 200
    assert approved.json()["reviewStatus"] == "APPROVED"

    again = client.patch(
        f"/api/v1/agent/recommendations/{recommendation_id}",
        headers=agent_auth,
        json={"reviewStatus": "REJECTED"},
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "RECOMMENDATION_ALREADY_REVIEWED"


@pytest.mark.parametrize("path", ["/api/v1/agent/recommendations", "/api/v1/agent/analytics/run"])
def test_recommendation_routes_require_an_agent(
    client: TestClient, customer_auth: dict[str, str], path: str
) -> None:
    method = client.post if path.endswith("run") else client.get
    assert method(path, headers=customer_auth).status_code == 403


def test_missing_recommendation_returns_404(client: TestClient, agent_auth: dict[str, str]) -> None:
    response = client.patch(
        f"/api/v1/agent/recommendations/{uuid.uuid4()}",
        headers=agent_auth,
        json={"reviewStatus": "APPROVED"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RECOMMENDATION_NOT_FOUND"
