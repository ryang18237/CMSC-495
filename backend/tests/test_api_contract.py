"""The written API contract and the running code must agree.

docs/API.md is what a client developer reads. These tests fail when the two
drift apart: a route added without being documented, a documented route that
no longer exists, or an error code the client could receive but has never been
told about.
"""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.schemas import MAX_REPLY_LENGTH

REPO_ROOT = Path(__file__).resolve().parents[2]
API_DOC = REPO_ROOT / "docs" / "API.md"
APP_DIR = REPO_ROOT / "backend" / "app"

# `{conversationId}` in the document and `{conversation_id}` in the code name
# the same slot. Only the position of a parameter is part of the contract.
_PARAM = re.compile(r"\{[^}]+\}")


def _normalise(path: str) -> str:
    return _PARAM.sub("{}", path)


def _documented_routes() -> set[tuple[str, str]]:
    """Rows of the endpoint summary table: | METHOD | `/path` | ... |"""
    row = re.compile(r"^\|\s*(GET|POST|PATCH|PUT|DELETE)\s*\|\s*`([^`]+)`\s*\|", re.M)
    return {(method, _normalise(path)) for method, path in row.findall(API_DOC.read_text())}


def _implemented_routes() -> set[tuple[str, str]]:
    """Read the routes from the generated OpenAPI document.

    That is the app's own public statement of what it serves, and it does not
    depend on how FastAPI stores included routers internally, which changed
    between versions.
    """
    paths = create_app().openapi()["paths"]
    return {
        (method.upper(), _normalise(path))
        for path, operations in paths.items()
        if path.startswith("/api/")
        for method in operations
    }


def test_every_route_is_documented() -> None:
    missing = _implemented_routes() - _documented_routes()
    assert not missing, f"Routes missing from the docs/API.md summary table: {sorted(missing)}"


def test_every_documented_route_exists() -> None:
    stale = _documented_routes() - _implemented_routes()
    assert not stale, f"docs/API.md lists routes the API does not serve: {sorted(stale)}"


def test_every_error_code_is_documented() -> None:
    """A client can only handle a code it has been told about."""
    source = "\n".join(path.read_text() for path in APP_DIR.rglob("*.py"))
    raised = set(re.findall(r'code="([A-Z][A-Z_]+)"', source))
    # Codes the shared handlers in errors.py produce for framework failures.
    raised |= set(re.findall(r'"([A-Z][A-Z_]{4,})"', (APP_DIR / "errors.py").read_text()))

    document = API_DOC.read_text()
    undocumented = sorted(code for code in raised if f"`{code}`" not in document)
    assert not undocumented, f"Error codes missing from docs/API.md: {undocumented}"


# ---------------------------------------------------------------------------
# Counsellor reply contract
# ---------------------------------------------------------------------------
def _case_id(client: TestClient, member: dict[str, str], agent: dict[str, str]) -> str:
    conversation_id = client.post("/api/v1/conversations", headers=member).json()["conversationId"]
    client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        headers=member,
        json={"message": "I want to speak to a human please"},
    )
    return str(client.get("/api/v1/agent/cases", headers=agent).json()[0]["caseId"])


def test_every_bad_reply_returns_the_same_code(
    client: TestClient, customer_auth: dict[str, str], agent_auth: dict[str, str]
) -> None:
    """Empty, blank and over-long replies all get 422 INVALID_REPLY.

    Before the request model moved into schemas.py an empty string was refused
    by schema validation (INVALID_REQUEST) while a blank one reached the
    service (INVALID_REPLY). A client should not need two branches for one rule.
    """
    case_id = _case_id(client, customer_auth, agent_auth)

    for bad in ("", "     ", "x" * (MAX_REPLY_LENGTH + 1)):
        response = client.post(
            f"/api/v1/agent/cases/{case_id}/reply", headers=agent_auth, json={"message": bad}
        )
        assert response.status_code == 422, bad[:10]
        body = response.json()["error"]
        assert body["code"] == "INVALID_REPLY"
        assert body["requestId"] == response.headers["X-Request-ID"]


def test_a_reply_at_the_limit_is_accepted(
    client: TestClient, customer_auth: dict[str, str], agent_auth: dict[str, str]
) -> None:
    case_id = _case_id(client, customer_auth, agent_auth)
    response = client.post(
        f"/api/v1/agent/cases/{case_id}/reply",
        headers=agent_auth,
        json={"message": "x" * MAX_REPLY_LENGTH},
    )
    assert response.status_code == 201


def test_workload_uses_the_documented_shape(
    client: TestClient, customer_auth: dict[str, str], agent_auth: dict[str, str]
) -> None:
    assert client.get("/api/v1/agent/workload", headers=agent_auth).json() == {"openCases": 0}

    case_id = _case_id(client, customer_auth, agent_auth)
    client.post(f"/api/v1/agent/cases/{case_id}/claim", headers=agent_auth)

    assert client.get("/api/v1/agent/workload", headers=agent_auth).json() == {"openCases": 1}


def test_workload_is_agent_only(client: TestClient, customer_auth: dict[str, str]) -> None:
    response = client.get("/api/v1/agent/workload", headers=customer_auth)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_docs_page_loads_no_third_party_assets(client: TestClient) -> None:
    """The API reference has to render on a machine with no internet.

    FastAPI's stock /docs pulls Swagger UI from a public CDN, so behind a
    proxy or offline the page arrives as unstyled text. We serve our own
    copies instead; this fails if anyone points it back at a CDN.
    """
    page = client.get("/docs")
    assert page.status_code == 200
    assert "cdn.jsdelivr.net" not in page.text
    assert "fastapi.tiangolo.com" not in page.text
    assert "/static/swagger-ui.css" in page.text
    assert "/static/swagger-ui-bundle.js" in page.text


def test_docs_assets_are_served_locally(client: TestClient) -> None:
    for path in ("/static/swagger-ui.css", "/static/swagger-ui-bundle.js"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert len(response.content) > 10_000, path
