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


def test_health_names_the_live_database_engine(client: TestClient) -> None:
    """The demo has to be able to say which data layer is actually running."""
    dependencies = client.get("/api/v1/health").json()["dependencies"]
    assert dependencies["database_engine"] in {"postgresql", "sqlite"}


def test_health_carries_a_request_id(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.headers.get("X-Request-ID")


def test_login_returns_a_bearer_token(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "member@example.com", "password": "DemoPassw0rd!"},
    )
    assert response.status_code == 200

    body = response.json()
    assert body["tokenType"] == "Bearer"
    assert body["role"] == "CUSTOMER"
    assert body["expiresIn"] > 0


def test_login_with_wrong_password_is_unauthorized(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "member@example.com", "password": "not-the-password"},
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
        json={"email": "member@example.com", "password": "wrong"},
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


def test_seed_realigns_an_account_renamed_by_an_earlier_version(client: TestClient) -> None:
    """A database seeded before an email change must still sign in.

    Seeded accounts are matched by id, so renaming one in `bootstrap.py` used
    to leave existing databases on the old address with no way back except a
    reset. This pins the repair.
    """
    from app.bootstrap import MEMBER_ID, seed
    from app.db import SessionLocal
    from app.models import User

    db = SessionLocal()
    try:
        member = db.get(User, MEMBER_ID)
        assert member is not None
        member.email = "stale-address@example.com"
        member.display_name = "Old Name"
        db.commit()

        seed(db)

        repaired = db.get(User, MEMBER_ID)
        assert repaired is not None
        assert repaired.email == "member@example.com"
        assert repaired.display_name == "Alex Rivera"
    finally:
        db.close()

    # And the documented address works again over HTTP.
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "member@example.com", "password": "DemoPassw0rd!"},
    )
    assert response.status_code == 200
