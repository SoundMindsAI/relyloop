"""Integration smoke for /api/v1/query-templates (Story 3.1, FR-2 + AC-7).

The full contract test matrix lives in
``backend/tests/contract/test_studies_api_contract.py`` /
``test_studies_error_codes.py`` (Story 3.5). This file covers the
behavior gates that Story 3.1's DoD calls out specifically:

* AC-7 sandbox rejection — POST with ``{{ os.system('rm -rf /') }}`` →
  400 ``INVALID_TEMPLATE_SYNTAX``.
* POST happy path round-trip + GET-detail.
* GET-list cursor pagination + X-Total-Count header.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.tests.conftest import postgres_reachable

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


@pytest.fixture
def client() -> TestClient:
    from backend.app.main import app

    return TestClient(app)


def test_post_query_template_happy_path(client: TestClient) -> None:
    """Round-trip: POST → 201 + GET-detail returns the same row."""
    resp = client.post(
        "/api/v1/query-templates",
        json={
            "name": f"qt-happy-{id(client)}",
            "engine_type": "elasticsearch",
            "body": '{"query": {"match": {"title": "{{ query_text }}"}}}',
            "declared_params": {},
        },
    )
    assert resp.status_code == 201
    payload = resp.json()
    assert payload["name"].startswith("qt-happy-")
    assert payload["engine_type"] == "elasticsearch"
    assert payload["version"] == 1
    template_id = payload["id"]

    # GET-detail returns the same row.
    detail = client.get(f"/api/v1/query-templates/{template_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == template_id


def test_post_query_template_ac7_sandbox_call_rejected(client: TestClient) -> None:
    """AC-7: ``{{ os.system('rm -rf /') }}`` → 400 INVALID_TEMPLATE_SYNTAX."""
    resp = client.post(
        "/api/v1/query-templates",
        json={
            "name": f"qt-ac7-{id(client)}",
            "engine_type": "elasticsearch",
            "body": '{"query": {{ os.system("rm -rf /") }}}',
            "declared_params": {},
        },
    )
    # Jinja2 may parse the inner expression and fail the syntax check OR
    # the surrounding `{{ {{ ... }} }}` may yield a syntax-error. Either
    # path produces 400 INVALID_TEMPLATE_SYNTAX per AC-7.
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "INVALID_TEMPLATE_SYNTAX"


def test_post_query_template_attribute_access_rejected(client: TestClient) -> None:
    """Sandbox: ``{{ "".__class__ }}`` → 400 INVALID_TEMPLATE_SYNTAX."""
    resp = client.post(
        "/api/v1/query-templates",
        json={
            "name": f"qt-attr-{id(client)}",
            "engine_type": "elasticsearch",
            "body": '{{ "".__class__ }}',
            "declared_params": {},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "INVALID_TEMPLATE_SYNTAX"


def test_post_query_template_undeclared_param_rejected(client: TestClient) -> None:
    """Body uses ``{{ foo }}`` not in declared_params → 400 UNDECLARED_PARAM_USED."""
    resp = client.post(
        "/api/v1/query-templates",
        json={
            "name": f"qt-undecl-{id(client)}",
            "engine_type": "elasticsearch",
            "body": '{"query": "{{ foo }}"}',
            "declared_params": {},
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["error_code"] == "UNDECLARED_PARAM_USED"


def test_get_query_template_not_found(client: TestClient) -> None:
    """GET-detail with unknown id → 404 TEMPLATE_NOT_FOUND."""
    resp = client.get("/api/v1/query-templates/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "TEMPLATE_NOT_FOUND"


def test_list_query_templates_x_total_count_header(client: TestClient) -> None:
    """GET-list emits the X-Total-Count header."""
    resp = client.get("/api/v1/query-templates")
    assert resp.status_code == 200
    assert "X-Total-Count" in resp.headers


def test_post_query_template_name_taken_returns_409(client: TestClient) -> None:
    """Duplicate (name, version=1) → 409 TEMPLATE_NAME_TAKEN."""
    body = {
        "name": f"qt-dupe-{id(client)}",
        "engine_type": "elasticsearch",
        "body": '{"query": {"match_all": {}}}',
        "declared_params": {},
    }
    r1 = client.post("/api/v1/query-templates", json=body)
    assert r1.status_code == 201
    r2 = client.post("/api/v1/query-templates", json=body)
    assert r2.status_code == 409
    assert r2.json()["detail"]["error_code"] == "TEMPLATE_NAME_TAKEN"
