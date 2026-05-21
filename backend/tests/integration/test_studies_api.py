"""Integration smoke for /api/v1/studies + /api/v1/studies/{id}/trials.

Covers the behavior gates called out by Story 3.3 + 3.4's DoD:

* POST happy-path round-trip + key-omission contract (C3-F1).
* INVALID_SEARCH_SPACE on a malformed search_space.
* judgment_list ↔ query_set mismatch VALIDATION_ERROR.
* POST /cancel happy-path + 409 on second cancel.
* GET /studies/{id}/trials sort + cursor + since.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

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
            # Must declare every param used in _VALID_SEARCH_SPACE because the
            # POST /studies handler now validates search_space.params keys
            # against template.declared_params (chore_create_study_wizard_polish
            # FR-2 + FR-3, Story 1.1). Empty declared_params would trigger
            # SEARCH_SPACE_UNKNOWN_PARAM at create time.
            declared_params={"bm25_k1": "float"},
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


async def test_post_study_happy_path_excludes_unset_config_keys(
    async_client: httpx.AsyncClient,
) -> None:
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
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 201, resp.text
    detail = resp.json()
    assert detail["status"] == "queued"
    assert detail["config"] == {"max_trials": 20}, (
        f"expected key-omission; got {detail['config']!r}"
    )
    assert "trials_summary" in detail
    assert detail["trials_summary"]["total"] == 0


async def test_post_study_invalid_search_space_returns_400(
    async_client: httpx.AsyncClient,
) -> None:
    ids = await _seed_minimum_for_post_studies()
    body = {
        "name": "bad-space",
        "cluster_id": ids["cluster_id"],
        "target": "stub-index",
        "template_id": ids["template_id"],
        "query_set_id": ids["query_set_id"],
        "judgment_list_id": ids["judgment_list_id"],
        # Cardinality explosion → over 10^6 cap.
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
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["error_code"] == "INVALID_SEARCH_SPACE"


async def test_post_study_judgment_query_set_mismatch_returns_422(
    async_client: httpx.AsyncClient,
) -> None:
    """spec §11: judgment_list.query_set_id ≠ request.query_set_id → 422."""
    ids = await _seed_minimum_for_post_studies()
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
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "VALIDATION_ERROR"
    assert "query_set_id" in resp.json()["detail"]["message"]


# ---------------------------------------------------------------------------
# feat_study_target_judgment_mismatch_guard FR-1 + FR-1b — cluster + target
# validators on POST /studies. The four tests below cover AC-1, AC-2, AC-4,
# AC-11, plus the "no insert + no enqueue" assertion required by the spec's
# DoD ("And no row is inserted into studies / And no Arq job is enqueued").
# ---------------------------------------------------------------------------


async def _count_studies(db_factory: object) -> int:
    """Return the current row count of `studies`. Used to assert no-insert
    on rejected create-study POSTs."""
    from sqlalchemy import func as _func
    from sqlalchemy import select

    from backend.app.db.models import Study

    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(select(_func.count()).select_from(Study))
        return int(result.scalar_one())


async def test_post_study_rejects_target_mismatch(async_client: httpx.AsyncClient) -> None:
    """AC-1: judgment_list.target != body.target → 422 JUDGMENT_TARGET_MISMATCH;
    no studies row inserted; no Arq job enqueued."""
    ids = await _seed_minimum_for_post_studies()
    before = await _count_studies(None)

    body = {
        "name": "target-mismatch-study",
        "cluster_id": ids["cluster_id"],
        "target": "docs-articles",  # judgment_list was seeded with target="stub-index"
        "template_id": ids["template_id"],
        "query_set_id": ids["query_set_id"],
        "judgment_list_id": ids["judgment_list_id"],
        "search_space": _VALID_SEARCH_SPACE,
        "objective": {"metric": "ndcg", "k": 10},
        "config": {"max_trials": 20},
    }
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error_code"] == "JUDGMENT_TARGET_MISMATCH"
    assert detail["retryable"] is False
    assert "stub-index" in detail["message"]
    assert "docs-articles" in detail["message"]

    # No studies row inserted.
    after = await _count_studies(None)
    assert after == before, "JUDGMENT_TARGET_MISMATCH must NOT insert a studies row"


async def test_post_study_rejects_cluster_mismatch(async_client: httpx.AsyncClient) -> None:
    """AC-11: judgment_list.cluster_id != body.cluster_id → 422
    JUDGMENT_CLUSTER_MISMATCH; fires BEFORE the target check; no insert."""
    seed_a = await _seed_minimum_for_post_studies()
    factory = get_session_factory()
    async with factory() as db:
        cluster_b = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"st-cluster-b-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub-b:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        # Query-set is in cluster A so the cross-cluster body resolves the
        # query_set successfully (matching cluster_b on the body) but the
        # judgment_list (in cluster A) mismatches.
        qs_b = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"st-qs-b-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster_b.id,
        )
        # Create a judgment_list bound to cluster A but query_set in cluster B
        # — for this test we want cluster mismatch, not query_set mismatch, so
        # the judgment_list points at cluster A's query_set.
        jl_a = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"st-jl-b-{uuid.uuid4().hex[:8]}",
            description=None,
            query_set_id=qs_b.id,  # match the body's query_set_id
            cluster_id=seed_a["cluster_id"],  # cluster_id mismatch vs body.cluster_id (B)
            target="stub-index",  # target matches body — proves cluster fires first
            current_template_id=seed_a["template_id"],
            rubric="hand-built",
            status="complete",
            failed_reason=None,
            calibration=None,
        )
        await db.commit()

    before = await _count_studies(None)
    body = {
        "name": "cluster-mismatch-study",
        "cluster_id": cluster_b.id,  # B
        "target": "stub-index",
        "template_id": seed_a["template_id"],
        "query_set_id": qs_b.id,
        "judgment_list_id": jl_a.id,
        "search_space": _VALID_SEARCH_SPACE,
        "objective": {"metric": "ndcg", "k": 10},
        "config": {"max_trials": 20},
    }
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error_code"] == "JUDGMENT_CLUSTER_MISMATCH"
    assert detail["retryable"] is False
    assert seed_a["cluster_id"] in detail["message"]
    assert cluster_b.id in detail["message"]
    # No studies row inserted.
    after = await _count_studies(None)
    assert after == before, "JUDGMENT_CLUSTER_MISMATCH must NOT insert a studies row"


async def test_post_study_cluster_mismatch_fires_before_target(
    async_client: httpx.AsyncClient,
) -> None:
    """AC-11 ordering: when BOTH cluster_id AND target differ, the cluster
    error wins (fires first). This locks the FR-1b BEFORE FR-1 ordering."""
    seed_a = await _seed_minimum_for_post_studies()
    factory = get_session_factory()
    async with factory() as db:
        cluster_b = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"st-cluster-b2-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub-b2:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        qs_b = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"st-qs-b2-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster_b.id,
        )
        # judgment_list with BOTH cluster AND target mismatched vs the body.
        jl_a = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"st-jl-both-{uuid.uuid4().hex[:8]}",
            description=None,
            query_set_id=qs_b.id,
            cluster_id=seed_a["cluster_id"],  # cluster mismatch vs body cluster B
            target="other-index",  # target mismatch vs body target
            current_template_id=seed_a["template_id"],
            rubric="hand-built",
            status="complete",
            failed_reason=None,
            calibration=None,
        )
        await db.commit()

    body = {
        "name": "both-mismatch-study",
        "cluster_id": cluster_b.id,
        "target": "docs-articles",  # mismatch vs jl_a.target
        "template_id": seed_a["template_id"],
        "query_set_id": qs_b.id,
        "judgment_list_id": jl_a.id,
        "search_space": _VALID_SEARCH_SPACE,
        "objective": {"metric": "ndcg", "k": 10},
        "config": {"max_trials": 20},
    }
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["error_code"] == "JUDGMENT_CLUSTER_MISMATCH", (
        f"cluster check must fire BEFORE target check; got {resp.json()['detail']['error_code']!r}"
    )


async def test_post_study_target_check_fires_after_query_set_check(
    async_client: httpx.AsyncClient,
) -> None:
    """AC-4 ordering: query_set_id mismatch (existing VALIDATION_ERROR) fires
    before the new target check. Locks the FR-1/FR-1b ordering relative to
    the pre-existing validator at studies.py:241-247."""
    ids = await _seed_minimum_for_post_studies()
    factory = get_session_factory()
    async with factory() as db:
        second_qs = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"st-qs3-{uuid.uuid4().hex[:8]}",
            cluster_id=ids["cluster_id"],
        )
        await db.commit()

    body = {
        "name": "qs-vs-target",
        "cluster_id": ids["cluster_id"],
        "target": "docs-articles",  # mismatches judgment_list.target="stub-index"
        "template_id": ids["template_id"],
        "query_set_id": second_qs.id,  # mismatches judgment_list.query_set_id
        "judgment_list_id": ids["judgment_list_id"],
        "search_space": _VALID_SEARCH_SPACE,
        "objective": {"metric": "ndcg", "k": 10},
        "config": {"max_trials": 20},
    }
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 422
    # query_set check fires FIRST (existing behavior, generic VALIDATION_ERROR).
    assert resp.json()["detail"]["error_code"] == "VALIDATION_ERROR"


async def test_get_study_does_not_validate_pre_existing_target_mismatch(
    async_client: httpx.AsyncClient,
) -> None:
    """AC-10: pre-existing studies with mismatched target are not retroactively
    rejected by read paths. Seed a study row directly with a mismatched target
    (bypassing POST) and confirm GET /studies/{id} returns 200."""
    ids = await _seed_minimum_for_post_studies()
    factory = get_session_factory()
    async with factory() as db:
        study = await repo.create_study(
            db,
            id=str(uuid.uuid4()),
            name="pre-existing-mismatch",
            cluster_id=ids["cluster_id"],
            target="some-other-index",  # mismatches judgment_list.target="stub-index"
            template_id=ids["template_id"],
            query_set_id=ids["query_set_id"],
            judgment_list_id=ids["judgment_list_id"],
            search_space=_VALID_SEARCH_SPACE,
            objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
            config={"max_trials": 20},
            status="queued",
            optuna_study_name=str(uuid.uuid4()),
        )
        await db.commit()

    resp = await async_client.get(f"/api/v1/studies/{study.id}")
    assert resp.status_code == 200, resp.text
    detail = resp.json()
    assert detail["target"] == "some-other-index"
    assert detail["id"] == study.id


async def test_cancel_endpoint_round_trip(async_client: httpx.AsyncClient) -> None:
    """POST /cancel transitions queued → cancelled; second call → 409."""
    ids = await _seed_minimum_for_post_studies()
    create = await async_client.post(
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

    cancel = await async_client.post(f"/api/v1/studies/{study_id}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    cancel2 = await async_client.post(f"/api/v1/studies/{study_id}/cancel")
    assert cancel2.status_code == 409
    assert cancel2.json()["detail"]["error_code"] == "INVALID_STATE_TRANSITION"


async def test_cancel_missing_study_returns_404(
    async_client: httpx.AsyncClient,
) -> None:
    missing = "00000000-0000-0000-0000-000000000000"
    resp = await async_client.post(f"/api/v1/studies/{missing}/cancel")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "STUDY_NOT_FOUND"


async def test_list_studies_x_total_count_header(
    async_client: httpx.AsyncClient,
) -> None:
    """GET /studies emits X-Total-Count."""
    ids = await _seed_minimum_for_post_studies()
    await async_client.post(
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
    resp = await async_client.get("/api/v1/studies")
    assert resp.status_code == 200
    assert "X-Total-Count" in resp.headers


async def test_list_trials_bad_sort_returns_422(
    async_client: httpx.AsyncClient,
) -> None:
    """Unknown sort key → 422 VALIDATION_ERROR."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = await async_client.get(f"/api/v1/studies/{fake_id}/trials?sort=unknown_sort")
    assert resp.status_code == 422
    assert resp.json()["detail"]["error_code"] == "VALIDATION_ERROR"


async def test_list_trials_unknown_study_returns_404(
    async_client: httpx.AsyncClient,
) -> None:
    fake_id = "00000000-0000-0000-0000-000000000000"
    resp = await async_client.get(f"/api/v1/studies/{fake_id}/trials")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "STUDY_NOT_FOUND"


# ---------------------------------------------------------------------------
# Story 3.5 error-code coverage (post-impl GPT-5.5 review F7)
# ---------------------------------------------------------------------------


async def test_post_study_unknown_judgment_list_returns_404(
    async_client: httpx.AsyncClient,
) -> None:
    """Unknown judgment_list_id → 404 JUDGMENT_LIST_NOT_FOUND."""
    ids = await _seed_minimum_for_post_studies()
    body = {
        "name": "missing-jl",
        "cluster_id": ids["cluster_id"],
        "target": "stub-index",
        "template_id": ids["template_id"],
        "query_set_id": ids["query_set_id"],
        "judgment_list_id": "00000000-0000-0000-0000-000000000000",
        "search_space": _VALID_SEARCH_SPACE,
        "objective": {"metric": "ndcg", "k": 10},
        "config": {"max_trials": 5},
    }
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "JUDGMENT_LIST_NOT_FOUND"


async def test_post_study_unknown_template_returns_404(
    async_client: httpx.AsyncClient,
) -> None:
    """Unknown template_id → 404 TEMPLATE_NOT_FOUND."""
    ids = await _seed_minimum_for_post_studies()
    body = {
        "name": "missing-tmpl",
        "cluster_id": ids["cluster_id"],
        "target": "stub-index",
        "template_id": "00000000-0000-0000-0000-000000000000",
        "query_set_id": ids["query_set_id"],
        "judgment_list_id": ids["judgment_list_id"],
        "search_space": _VALID_SEARCH_SPACE,
        "objective": {"metric": "ndcg", "k": 10},
        "config": {"max_trials": 5},
    }
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "TEMPLATE_NOT_FOUND"


async def test_post_study_unknown_query_set_returns_404(
    async_client: httpx.AsyncClient,
) -> None:
    """Unknown query_set_id → 404 QUERY_SET_NOT_FOUND."""
    ids = await _seed_minimum_for_post_studies()
    body = {
        "name": "missing-qs",
        "cluster_id": ids["cluster_id"],
        "target": "stub-index",
        "template_id": ids["template_id"],
        "query_set_id": "00000000-0000-0000-0000-000000000000",
        "judgment_list_id": ids["judgment_list_id"],
        "search_space": _VALID_SEARCH_SPACE,
        "objective": {"metric": "ndcg", "k": 10},
        "config": {"max_trials": 5},
    }
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "QUERY_SET_NOT_FOUND"


async def test_post_study_unknown_cluster_returns_404(
    async_client: httpx.AsyncClient,
) -> None:
    """Unknown cluster_id → 404 CLUSTER_NOT_FOUND."""
    ids = await _seed_minimum_for_post_studies()
    body = {
        "name": "missing-cluster",
        "cluster_id": "00000000-0000-0000-0000-000000000000",
        "target": "stub-index",
        "template_id": ids["template_id"],
        "query_set_id": ids["query_set_id"],
        "judgment_list_id": ids["judgment_list_id"],
        "search_space": _VALID_SEARCH_SPACE,
        "objective": {"metric": "ndcg", "k": 10},
        "config": {"max_trials": 5},
    }
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "CLUSTER_NOT_FOUND"


async def test_get_study_unknown_id_returns_404(
    async_client: httpx.AsyncClient,
) -> None:
    """GET /studies/{id} with unknown id → 404 STUDY_NOT_FOUND."""
    resp = await async_client.get("/api/v1/studies/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404
    assert resp.json()["detail"]["error_code"] == "STUDY_NOT_FOUND"


# ---------------------------------------------------------------------------
# cluster_id filter (bug_cluster_detail_studies_unfiltered fix)
# ---------------------------------------------------------------------------


async def test_list_studies_filters_by_cluster_id(
    async_client: httpx.AsyncClient,
) -> None:
    """GET /studies?cluster_id={id} scopes to that cluster only.

    Regression for the bug surfaced during guide 01 audit: the frontend's
    "Studies using this cluster" section sent ?cluster_id= but the backend
    silently ignored it (no Query param declared) → unfiltered global list.

    Seeds two independent clusters (each with its own template/query-set/
    judgment-list/study), then asserts GET /studies?cluster_id=A returns
    only A's study and excludes B's.
    """
    ids_a = await _seed_minimum_for_post_studies()
    ids_b = await _seed_minimum_for_post_studies()

    body_a = {
        "name": f"study-a-{uuid.uuid4().hex[:8]}",
        "cluster_id": ids_a["cluster_id"],
        "target": "stub-index",
        "template_id": ids_a["template_id"],
        "query_set_id": ids_a["query_set_id"],
        "judgment_list_id": ids_a["judgment_list_id"],
        "search_space": _VALID_SEARCH_SPACE,
        "objective": {"metric": "ndcg", "k": 10},
        "config": {"max_trials": 5},
    }
    body_b = {
        **body_a,
        "name": f"study-b-{uuid.uuid4().hex[:8]}",
        "cluster_id": ids_b["cluster_id"],
        "template_id": ids_b["template_id"],
        "query_set_id": ids_b["query_set_id"],
        "judgment_list_id": ids_b["judgment_list_id"],
    }
    post_a = await async_client.post("/api/v1/studies", json=body_a)
    post_b = await async_client.post("/api/v1/studies", json=body_b)
    assert post_a.status_code == 201
    assert post_b.status_code == 201
    study_a_id = post_a.json()["id"]
    study_b_id = post_b.json()["id"]

    # Scoped to A: returns A's study, excludes B's.
    resp_a = await async_client.get(f"/api/v1/studies?cluster_id={ids_a['cluster_id']}")
    assert resp_a.status_code == 200
    ids_returned_a = {row["id"] for row in resp_a.json()["data"]}
    assert study_a_id in ids_returned_a
    assert study_b_id not in ids_returned_a
    # X-Total-Count parity — also scoped.
    total_a = int(resp_a.headers["X-Total-Count"])
    assert total_a == len(ids_returned_a)

    # Scoped to B: mirrors.
    resp_b = await async_client.get(f"/api/v1/studies?cluster_id={ids_b['cluster_id']}")
    assert resp_b.status_code == 200
    ids_returned_b = {row["id"] for row in resp_b.json()["data"]}
    assert study_b_id in ids_returned_b
    assert study_a_id not in ids_returned_b

    # No cluster_id filter → both studies visible (global list still works).
    resp_all = await async_client.get("/api/v1/studies")
    assert resp_all.status_code == 200
    ids_returned_all = {row["id"] for row in resp_all.json()["data"]}
    assert study_a_id in ids_returned_all
    assert study_b_id in ids_returned_all
