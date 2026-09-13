"""Infrastructure layer: health reporting and authentication."""

from fastapi.testclient import TestClient


def test_health_reports_healthy_with_dependencies(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200

    body = response.json()
    assert body["status"] == "healthy"
    assert body["dependencies"]["database"] == "ok"
    assert body["dependencies"]["ai_provider_name"] == "mock"
    assert "timestamp" in body
    # The health endpoint must not expose customer data.
    assert "customer" not in response.text.lower()


def test_health_carries_a_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.headers.get("X-Request-ID")


def test_login_returns_a_bearer_token(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "customer@example.com", "password": "DemoPassw0rd!"},
    )
    assert response.status_code == 200

    body = response.json()
    assert body["tokenType"] == "Bearer"
    assert body["role"] == "CUSTOMER"
    assert body["expiresIn"] > 0


def test_login_with_wrong_password_is_unauthorized(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "customer@example.com", "password": "not-the-password"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_unknown_email_gives_the_same_message_as_a_wrong_password(client: TestClient) -> None:
    unknown = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "DemoPassw0rd!"},
    )
    wrong = client.post(
        "/api/v1/auth/login",
        json={"email": "customer@example.com", "password": "wrong"},
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]


def test_protected_route_requires_a_token(client: TestClient) -> None:
    response = client.post("/api/v1/conversations")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_garbage_token_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/conversations", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


def test_error_contract_shape(client: TestClient) -> None:
    response = client.post("/api/v1/conversations")
    error = response.json()["error"]
    assert set(error) == {"code", "message", "requestId"}
