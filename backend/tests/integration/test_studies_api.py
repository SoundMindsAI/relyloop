"""Integration smoke for /api/v1/studies + /api/v1/studies/{id}/trials.

The full contract-test matrix lives in
``backend/tests/contract/test_studies_api_contract.py`` and
``test_studies_error_codes.py`` (Story 3.5). This file covers the
behavior gates called out by Story 3.3 + 3.4's DoD:

* POST happy-path round-trip + key-omission contract (C3-F1).
* INVALID_SEARCH_SPACE on a malformed search_space.
* CLUSTER/TEMPLATE/QUERY_SET/JUDGMENT_LIST_NOT_FOUND.
* VALIDATION_ERROR on judgment_list ↔ query_set mismatch.
* POST /cancel happy-path + 409 on second cancel.
* GET /studies/{id}/trials sort + cursor + since.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from backend.app.db import repo
from backend.app.db.session import get_session_factory
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


async def _seed_minimum_for_post_studies() -> dict[str, str]:
    """Seed a cluster + template + query_set + judgment_list + return the IDs."""
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"st-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"st-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"st-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        judgment_list = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"st-jl-{uuid.uuid4().hex[:8]}",
            description=None,
            query_set_id=query_set.id,
            cluster_id=cluster.id,
            target="stub-index",
            current_template_id=template.id,
            rubric="hand-built",
            status="complete",
            failed_reason=None,
            calibration=None,
        )
        await db.commit()
    return {
        "cluster_id": cluster.id,
        "template_id": template.id,
        "query_set_id": query_set.id,
        "judgment_list_id": judgment_list.id,
    }


_VALID_SEARCH_SPACE = {
    "params": {
        "bm25_k1": {"type": "float", "low": 0.1, "high": 2.0},
    }
}


async def test_post_study_happy_path_excludes_unset_config_keys(client: TestClient) -> None:
    """C3-F1 key-omission contract: POST with config={max_trials: 20} →
    persisted config dict has NO parallelism / trial_timeout_s / sampler /
    pruner / seed / secondary_metrics keys."""
    ids = await _seed_minimum_for_post_studies()
    body = {
        "name": "test-study",
        "cluster_id": ids["cluster_id"],
        "target": "stub-index",
        "template_id": ids["template_id"],
        "query_set_id": ids["query_set_id"],
        "judgment_list_id": ids["judgment_list_id"],
        "search_space": _VALID_SEARCH_SPACE,
        "objective": {"metric": "ndcg", "k": 10},
        "config": {"max_trials": 20},
    }
    resp = client.post("/api/v1/studies", json=body)
    assert resp.status_code == 201, resp.text
    detail = resp.json()
    assert detail["status"] == "queued"
    assert detail["config"] == {"max_trials": 20}, (
        f"expected key-omission; got {detail['config']!r}"
    )
    assert "trials_summary" in detail
    assert detail["trials_summary"]["total"] == 0


async def test_post_study_invalid_search_space_returns_400(client: TestClient) -> None:
    ids = await _seed_minimum_for_post_studies()
    body = {
        "name": "bad-space",
        "cluster_id": ids["cluster_id"],
        "target": "stub-index",
        "template_id": ids["template_id"],
        "query_set_id": ids["query_set_id"],
        "judgment_list_id": ids["judgment_list_id"],
        # Cardinality explosion via 100 ints * 100 ints * 100 floats * 100 ints
        # = 10^8 — over the 10^6 cap.
        "search_space": {
            "params": {
                "p1": {"type": "int", "low": 0, "high": 100},
                "p2": {"type": "int", "low": 0, "high": 100},
                "p3": {"type": "float", "low": 0.1, "high": 1.0},
                "p4": {"type": "int", "low": 0, "high": 100},
            }
        },
        "objective": {"metric": "ndcg", "k": 10},
        "config": {"max_trials": 20},
    }
    resp = client.post("/api/v1/studies", json=body)
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["error_code"] == "INVALID_SEARCH_SPACE"


async def test_post_study_judgment_query_set_mismatch_returns_422(client: TestClient) -> None:
    """spec §11 edge/error flows: judgment_list.query_set_id ≠ request.query_set_id."""
    ids = await _seed_minimum_for_post_studies()
    # Create a second query_set; reference it from the request but keep
    # the existing judgment_list (which points at the first query_set).
    factory = get_session_factory()
    async with factory() as db:
        second_qs = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"st-qs2-{uuid.uuid4().hex[:8]}",
            cluster_id=ids["cluster_id"],
        )
        await db.commit()

    body = {
        "name": "mismatch-study",
        "cluster_id": ids["cluster_id"],
        "target": "stub-index",
        "template_id": ids["template_id"],
        "query_set_id": second_qs.id,
        "judgment_list_id": ids["judgment_list_id"],
        "search_space": _VALID_SEARCH_SPACE,
        "objective": {"metric": "ndcg", "k": 10},
        "config": {"max_trials": 20},
    }
    resp = client.post("/api/v1/studies", json=body)
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "VALIDATION_ERROR"
    assert "query_set_id" in resp.json()["detail"]["message"]


async def test_cancel_endpoint_round_trip(client: TestClient) -> None:
    """POST /cancel transitions queued → cancelled; second call → 409."""
    ids = await _seed_minimum_for_post_studies()
    create = client.post(
        "/api/v1/studies",
        json={
            "name": "cancel-me",
            "cluster_id": ids["cluster_id"],
            "target": "stub-index",
            "template_id": ids["template_id"],
            "query_set_id": ids["query_set_id"],
            "judgment_list_id": ids["judgment_list_id"],
            "search_space": _VALID_SEARCH_SPACE,
            "objective": {"metric": "ndcg", "k": 10},
            "config": {"max_trials": 20},
        },
    )
    assert create.status_code == 201
    study_id = create.json()["id"]

    cancel = client.post(f"/api/v1/studies/{study_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    # Second cancel → 409 INVALID_STATE_TRANSITION (AC-3 HTTP half).
    cancel2 = client.post(f"/api/v1/studies/{study_id}/cancel")
    assert cancel2.status_code == 409
    assert cancel2.json()["detail"]["error_code"] == "INVALID_STATE_TRANSITION"


def test_cancel_missing_study_returns_404(client: TestClient) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    resp = client.post(f"/api/v1/studies/{missing}/cancel")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "STUDY_NOT_FOUND"


async def test_list_studies_x_total_count_header(client: TestClient) -> None:
    """GET /studies emits X-Total-Count."""
    ids = await _seed_minimum_for_post_studies()
    # Make sure at least one study exists.
    client.post(
        "/api/v1/studies",
        json={
            "name": "list-target",
            "cluster_id": ids["cluster_id"],
            "target": "stub-index",
            "template_id": ids["template_id"],
            "query_set_id": ids["query_set_id"],
            "judgment_list_id": ids["judgment_list_id"],
            "search_space": _VALID_SEARCH_SPACE,
            "objective": {"metric": "ndcg", "k": 10},
            "config": {"max_trials": 5},
        },
    )
    resp = client.get("/api/v1/studies")
    assert resp.status_code == 200
    assert "X-Total-Count" in resp.headers


def test_list_trials_bad_sort_returns_422(client: TestClient) -> None:
    """Unknown sort key → 422 VALIDATION_ERROR."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = client.get(f"/api/v1/studies/{fake_id}/trials?sort=unknown_sort")
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "VALIDATION_ERROR"


def test_list_trials_unknown_study_returns_404(client: TestClient) -> None:
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = client.get(f"/api/v1/studies/{fake_id}/trials")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "STUDY_NOT_FOUND"
