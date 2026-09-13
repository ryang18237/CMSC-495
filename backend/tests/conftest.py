"""Shared pytest fixtures.

The environment is configured before any application module is imported so that
the engine is built against the test database rather than the developer's.
"""

import os
import tempfile
from collections.abc import Iterator

import pytest

_TMP_DB = os.path.join(tempfile.gettempdir(), "csp_test.sqlite3")
os.environ.setdefault("DATABASE_URL", f"sqlite+pysqlite:///{_TMP_DB}")
os.environ.setdefault("JWT_SECRET", "test-only-secret-value-that-is-long-enough-for-hs256")
os.environ.setdefault("AI_PROVIDER", "mock")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("SEED_PASSWORD", "DemoPassw0rd!")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app import rate_limit  # noqa: E402
from app.bootstrap import AGENT_ID, CUSTOMER_ID, CUSTOMER_TWO_ID, create_schema, seed  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402

SEED_PASSWORD = "DemoPassw0rd!"

__all__ = ["AGENT_ID", "CUSTOMER_ID", "CUSTOMER_TWO_ID", "SEED_PASSWORD"]


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    Base.metadata.drop_all(bind=engine)
    create_schema()
    db = SessionLocal()
    try:
        seed(db)
    finally:
        db.close()
    yield
    Base.metadata.drop_all(bind=engine)
    if os.path.exists(_TMP_DB):
        os.remove(_TMP_DB)


@pytest.fixture(autouse=True)
def _clean_transactional_tables() -> Iterator[None]:
    """Reset per-conversation state between tests; seeded reference data stays."""
    rate_limit.reset()
    yield
    db = SessionLocal()
    try:
        for table in (
            "feedback_events",
            "feedback_records",
            "improvement_recommendations",
            "escalation_cases",
            "conversation_messages",
            "conversations",
        ):
            db.execute(Base.metadata.tables[table].delete())
        db.commit()
    finally:
        db.close()


@pytest.fixture
def db_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.rollback()
        db.close()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _token(client: TestClient, email: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": SEED_PASSWORD})
    assert response.status_code == 200, response.text
    return str(response.json()["accessToken"])


@pytest.fixture
def customer_auth(client: TestClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(client, 'customer@example.com')}"}


@pytest.fixture
def other_customer_auth(client: TestClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(client, 'customer2@example.com')}"}


@pytest.fixture
def agent_auth(client: TestClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(client, 'agent@example.com')}"}


@pytest.fixture
def conversation_id(client: TestClient, customer_auth: dict[str, str]) -> str:
    response = client.post("/api/v1/conversations", headers=customer_auth)
    assert response.status_code == 201, response.text
    return str(response.json()["conversationId"])
