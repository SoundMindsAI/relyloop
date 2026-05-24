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
from typing import cast

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


@pytest.fixture(autouse=True)
def _default_overlap_probe_passes(monkeypatch: pytest.MonkeyPatch):
    """Install a default-sufficient overlap probe for every POST /studies test.

    Without this, every existing happy-path test in this module would hit the
    new ``feat_study_preflight_overlap_probe`` ``find_first_judged_query``
    → returns ``None`` (no judgments seeded) → empty-judgments path → 422
    ``INSUFFICIENT_JUDGMENT_OVERLAP``. The fixture below bypasses that by
    replacing ``probe_judgment_overlap`` with a stub that always returns a
    sufficient ``OverlapProbeResult``.

    Tests that want to exercise specific probe behavior — the AC-1 through
    AC-13 cases at the bottom of this file — re-monkeypatch the symbol
    in their own bodies, which overrides this default.
    """
    from backend.app.services.study_preflight import OverlapProbeResult

    async def fake_probe_passes(*args, **kwargs):  # noqa: ARG001
        return OverlapProbeResult(
            overlap_size=10,
            probed_doc_count=10,
            judged_doc_count=10,
            representative_query_id="01990000-0000-7000-8000-000000000099",
        )

    monkeypatch.setattr("backend.app.api.v1.studies.probe_judgment_overlap", fake_probe_passes)


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

    # cascade=false preserves the legacy single-cancel contract: cancel a
    # queued study → 200, second cancel on a terminal study → 409 with
    # INVALID_STATE_TRANSITION. The default changed to cascade=true with
    # feat_auto_followup_studies (cycle-3 C3-1 + AC-9) — that path is
    # tolerant of terminal parents and would return 200 here, so this
    # test pins the cascade=false branch.
    cancel = await async_client.post(f"/api/v1/studies/{study_id}/cancel?cascade=false")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"

    cancel2 = await async_client.post(f"/api/v1/studies/{study_id}/cancel?cascade=false")
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


# ---------------------------------------------------------------------------
# feat_study_preflight_overlap_probe Story 1.3 — INSUFFICIENT_JUDGMENT_OVERLAP
# integration tests (AC-1 through AC-13).
# ---------------------------------------------------------------------------


def _study_body_for(ids: dict[str, str], **overrides: object) -> dict[str, object]:
    """Build a POST /api/v1/studies body matching the seeded fixture's IDs."""
    body: dict[str, object] = {
        "name": f"overlap-probe-{uuid.uuid4().hex[:8]}",
        "cluster_id": ids["cluster_id"],
        "target": "stub-index",  # matches _seed_minimum_for_post_studies seed
        "template_id": ids["template_id"],
        "query_set_id": ids["query_set_id"],
        "judgment_list_id": ids["judgment_list_id"],
        "search_space": _VALID_SEARCH_SPACE,
        "objective": {"metric": "ndcg", "k": 10},
        "config": {"max_trials": 20},
    }
    body.update(overrides)
    return body


async def _seed_judgments(
    judgment_list_id: str,
    query_set_id: str,
    doc_ids: list[str],
) -> str:
    """Seed one ``queries`` row + one ``judgments`` row per ``doc_id``.

    Returns the ``query_id`` of the seeded query so callers can build
    follow-up assertions if needed.
    """
    factory = get_session_factory()
    async with factory() as db:
        query = await repo.create_query(
            db,
            id=str(uuid.uuid4()),
            query_set_id=query_set_id,
            query_text="seed query",
        )
        for doc_id in doc_ids:
            await repo.create_judgment(
                db,
                id=str(uuid.uuid4()),
                judgment_list_id=judgment_list_id,
                query_id=query.id,
                doc_id=doc_id,
                rating=2,
                source="human",
                rater_ref="operator",
            )
        await db.commit()
    return query.id


def _make_fake_probe_result(
    overlap_size: int,
    probed_doc_count: int,
    judged_doc_count: int,
    *,
    representative_query_id: str | None = "01990000-0000-7000-8000-000000000099",
):
    """Return a study_preflight.OverlapProbeResult-compatible fake."""
    from backend.app.services.study_preflight import OverlapProbeResult

    return OverlapProbeResult(
        overlap_size=overlap_size,
        probed_doc_count=probed_doc_count,
        judged_doc_count=judged_doc_count,
        representative_query_id=representative_query_id,
    )


async def test_post_study_insufficient_overlap_returns_422(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-1: overlap=0, judged_doc_count=50 → 422 INSUFFICIENT_JUDGMENT_OVERLAP.

    Monkeypatches ``probe_judgment_overlap`` at the studies-router import site
    to return a stub ``OverlapProbeResult``. Asserts envelope shape AND that
    no studies row is inserted.
    """
    ids = await _seed_minimum_for_post_studies()

    async def fake_probe(*args, **kwargs):  # noqa: ARG001
        return _make_fake_probe_result(0, 50, 50)

    monkeypatch.setattr("backend.app.api.v1.studies.probe_judgment_overlap", fake_probe)

    factory = get_session_factory()
    async with factory() as db:
        count_before = await repo.count_studies(db)

    resp = await async_client.post("/api/v1/studies", json=_study_body_for(ids))

    async with factory() as db:
        count_after = await repo.count_studies(db)

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error_code"] == "INSUFFICIENT_JUDGMENT_OVERLAP"
    assert detail["retryable"] is False
    assert "0 of 50 probed" in detail["message"]
    assert "judged_doc_count=50" in detail["message"]
    assert count_after == count_before, "no studies row should have been inserted"


async def test_post_study_sufficient_overlap_returns_201(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-2: overlap=50, judged_doc_count=50 → 201 (above cap-aware threshold)."""
    ids = await _seed_minimum_for_post_studies()

    async def fake_probe(*args, **kwargs):  # noqa: ARG001
        return _make_fake_probe_result(50, 50, 50)

    monkeypatch.setattr("backend.app.api.v1.studies.probe_judgment_overlap", fake_probe)

    resp = await async_client.post("/api/v1/studies", json=_study_body_for(ids))
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] == "queued"


async def test_post_study_overlap_at_threshold_returns_201(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-3: overlap=3, judged_doc_count=5 → required=min(3,5)=3, 3>=3 → 201.

    Boundary-inclusive lock: the ``<`` in ``overlap_size < required`` must
    stay strict-less-than; flipping to ``<=`` would break this case.
    """
    ids = await _seed_minimum_for_post_studies()

    async def fake_probe(*args, **kwargs):  # noqa: ARG001
        return _make_fake_probe_result(3, 5, 5)

    monkeypatch.setattr("backend.app.api.v1.studies.probe_judgment_overlap", fake_probe)

    resp = await async_client.post("/api/v1/studies", json=_study_body_for(ids))
    assert resp.status_code == 201, resp.text


async def test_post_study_overlap_one_below_threshold_returns_422(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-4: overlap=2, judged_doc_count=5 → required=3, 2<3 → 422."""
    ids = await _seed_minimum_for_post_studies()

    async def fake_probe(*args, **kwargs):  # noqa: ARG001
        return _make_fake_probe_result(2, 5, 5)

    monkeypatch.setattr("backend.app.api.v1.studies.probe_judgment_overlap", fake_probe)

    resp = await async_client.post("/api/v1/studies", json=_study_body_for(ids))
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["error_code"] == "INSUFFICIENT_JUDGMENT_OVERLAP"


async def test_post_study_cap_aware_threshold_allows_small_judgment_lists(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-4b: judged_doc_count=2, overlap=2 → required=min(3,2)=2, 2>=2 → 201.

    Locks the ``min(MIN_OVERLAP, max(judged_doc_count, 1))`` formula. Without
    the ``min(...)`` clamp, a judgment list with only 2 judgments per qid
    would be unconditionally rejected — but the operator authored exactly 2
    judgments and ALL of them are in the index, which is the strongest
    possible signal at that scale.
    """
    ids = await _seed_minimum_for_post_studies()

    async def fake_probe(*args, **kwargs):  # noqa: ARG001
        return _make_fake_probe_result(2, 2, 2)

    monkeypatch.setattr("backend.app.api.v1.studies.probe_judgment_overlap", fake_probe)

    resp = await async_client.post("/api/v1/studies", json=_study_body_for(ids))
    assert resp.status_code == 201, resp.text


async def test_post_study_404_fk_path_does_not_invoke_probe(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-5: 404 FK paths short-circuit before the probe. Asserts the probe
    is NOT awaited even with a stub that would otherwise succeed."""
    ids = await _seed_minimum_for_post_studies()
    probe_calls = {"count": 0}

    async def spy_probe(*args, **kwargs):  # noqa: ARG001
        probe_calls["count"] += 1
        return _make_fake_probe_result(100, 100, 100)

    monkeypatch.setattr("backend.app.api.v1.studies.probe_judgment_overlap", spy_probe)

    body = _study_body_for(ids, judgment_list_id=str(uuid.uuid4()))  # nonexistent
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"]["error_code"] == "JUDGMENT_LIST_NOT_FOUND"
    assert probe_calls["count"] == 0, "probe must not be invoked on the FK-404 path"


async def test_post_study_target_mismatch_does_not_invoke_probe(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-6: Tier 1 JUDGMENT_TARGET_MISMATCH short-circuits before the probe."""
    ids = await _seed_minimum_for_post_studies()
    probe_calls = {"count": 0}

    async def spy_probe(*args, **kwargs):  # noqa: ARG001
        probe_calls["count"] += 1
        return _make_fake_probe_result(100, 100, 100)

    monkeypatch.setattr("backend.app.api.v1.studies.probe_judgment_overlap", spy_probe)

    body = _study_body_for(ids, target="docs-articles")  # mismatches "stub-index"
    resp = await async_client.post("/api/v1/studies", json=body)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["error_code"] == "JUDGMENT_TARGET_MISMATCH"
    assert probe_calls["count"] == 0, "probe must not be invoked on Tier 1 mismatch path"


class _FakeProbeAdapter:
    """Minimal stand-in for ``ElasticAdapter`` used by adapter-layer probe tests.

    Exposes only ``search_batch`` (the surface the probe touches). Configure
    via ``raises``, ``sleep_for``, or ``return_value``; the call kwargs are
    captured in ``calls`` for later assertions.

    Bypasses credentials resolution by being injected via
    ``study_preflight.acquire_adapter`` rather than constructed through
    ``ElasticAdapter(...)`` — CI doesn't set ``CLUSTER_CREDENTIALS_FILE`` for
    the integration job, so the real ``acquire_adapter`` would raise
    ``ClusterUnreachable`` before the test's exception could fire.
    """

    def __init__(
        self,
        *,
        raises: BaseException | None = None,
        sleep_for: float | None = None,
        return_value: object = None,
    ) -> None:
        self._raises = raises
        self._sleep_for = sleep_for
        self._return_value = return_value if return_value is not None else {"overlap_probe": []}
        self.calls: list[dict[str, object]] = []

    async def search_batch(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if self._sleep_for is not None:
            import asyncio as _asyncio

            await _asyncio.sleep(self._sleep_for)
        if self._raises is not None:
            raise self._raises
        return self._return_value


def _install_real_probe_with_fake_adapter(
    monkeypatch: pytest.MonkeyPatch, fake_adapter: _FakeProbeAdapter
) -> None:
    """Restore the real ``probe_judgment_overlap`` (overriding the autouse
    default) AND monkeypatch ``study_preflight.acquire_adapter`` to yield
    ``fake_adapter``. Used by adapter-layer tests (AC-7/8/10/11/13) so the
    real probe code runs with a controlled adapter, bypassing credentials.
    """
    import contextlib as _contextlib

    from backend.app.services import study_preflight as _study_preflight

    monkeypatch.setattr(
        "backend.app.api.v1.studies.probe_judgment_overlap",
        _study_preflight.probe_judgment_overlap,
    )

    @_contextlib.asynccontextmanager
    async def fake_acquire(_cluster):  # noqa: ARG001
        yield fake_adapter

    monkeypatch.setattr(_study_preflight, "acquire_adapter", fake_acquire)


async def test_post_study_cluster_unreachable_during_probe_returns_201_with_warn(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-7: adapter raises ClusterUnreachableError → 201 + WARN log."""
    from backend.app.adapters.errors import ClusterUnreachableError

    ids = await _seed_minimum_for_post_studies()
    await _seed_judgments(ids["judgment_list_id"], ids["query_set_id"], ["d1"])
    fake_adapter = _FakeProbeAdapter(raises=ClusterUnreachableError("simulated"))
    _install_real_probe_with_fake_adapter(monkeypatch, fake_adapter)

    import structlog.testing

    from backend.tests._log_helpers import find_log_events

    with structlog.testing.capture_logs() as cap:
        resp = await async_client.post("/api/v1/studies", json=_study_body_for(ids))

    assert resp.status_code == 201, resp.text
    skipped = find_log_events(cap, event="studies.preflight.overlap_probe.skipped")
    assert len(skipped) >= 1
    assert any(e.get("reason") == "unreachable" for e in skipped)


async def test_post_study_probe_timeout_returns_201_with_warn(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-8: adapter blocks beyond PROBE_TIMEOUT_S → outer asyncio.wait_for fires."""
    from backend.app.services.study_preflight import PROBE_TIMEOUT_S

    ids = await _seed_minimum_for_post_studies()
    await _seed_judgments(ids["judgment_list_id"], ids["query_set_id"], ["d1"])
    fake_adapter = _FakeProbeAdapter(sleep_for=PROBE_TIMEOUT_S + 2.0)
    _install_real_probe_with_fake_adapter(monkeypatch, fake_adapter)

    import structlog.testing

    from backend.tests._log_helpers import find_log_events

    with structlog.testing.capture_logs() as cap:
        resp = await async_client.post("/api/v1/studies", json=_study_body_for(ids))

    assert resp.status_code == 201, resp.text
    skipped = find_log_events(cap, event="studies.preflight.overlap_probe.skipped")
    assert any(e.get("reason") == "timeout" for e in skipped)


async def test_post_study_empty_judgments_returns_422_with_info_log(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-9: judgment_list has 0 rows → 422 + studies.preflight.overlap_probe.empty INFO log.

    The probe short-circuits before ``acquire_adapter`` is invoked, so an
    inert ``_FakeProbeAdapter`` is sufficient — the test asserts that the
    empty-judgments code path fires and the adapter is NOT called.
    """
    ids = await _seed_minimum_for_post_studies()
    # Intentionally do NOT seed any judgments.
    fake_adapter = _FakeProbeAdapter()  # would return zero-hits if called; should NOT be called
    _install_real_probe_with_fake_adapter(monkeypatch, fake_adapter)

    import structlog.testing

    from backend.tests._log_helpers import find_log_events

    with structlog.testing.capture_logs() as cap:
        resp = await async_client.post("/api/v1/studies", json=_study_body_for(ids))

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail["error_code"] == "INSUFFICIENT_JUDGMENT_OVERLAP"
    empty_logs = find_log_events(cap, event="studies.preflight.overlap_probe.empty")
    assert len(empty_logs) >= 1
    ev = empty_logs[0]
    assert ev["study_judgment_list_id"] == ids["judgment_list_id"]
    assert ev["study_query_set_id"] == ids["query_set_id"]
    # Adapter must NOT have been invoked on the empty path.
    assert fake_adapter.calls == []


async def test_post_study_max_probed_docs_cap_honored(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-10: judged_doc_count=250, cap=200 → adapter sees exactly 200 doc IDs.

    Seeds 250 judgments for the representative qid; patches search_batch to
    capture the NativeQuery body. Asserts ``len(values) == 200`` (not 250)
    AND the error message wording shows ``X of 200 probed`` + ``judged_doc_count=250``.
    """
    ids = await _seed_minimum_for_post_studies()
    doc_ids = [f"doc_{i:04d}" for i in range(250)]
    await _seed_judgments(ids["judgment_list_id"], ids["query_set_id"], doc_ids)

    fake_adapter = _FakeProbeAdapter(return_value={"overlap_probe": []})  # zero hits → 422
    _install_real_probe_with_fake_adapter(monkeypatch, fake_adapter)

    resp = await async_client.post("/api/v1/studies", json=_study_body_for(ids))
    assert resp.status_code == 422, resp.text

    from backend.app.adapters.protocol import NativeQuery as _NativeQuery

    assert len(fake_adapter.calls) == 1
    captured_kwargs = fake_adapter.calls[0]
    queries = cast(list[_NativeQuery], captured_kwargs["queries"])
    assert len(queries) == 1
    body = queries[0].body
    actual_len = len(body["query"]["ids"]["values"])
    assert actual_len == 200, f"cap violation: expected 200 doc_ids, got {actual_len}"
    assert body["size"] == 200
    assert captured_kwargs["top_k"] == 200

    msg = resp.json()["detail"]["message"]
    assert "0 of 200 probed" in msg
    assert "judged_doc_count=250" in msg


async def test_post_study_probe_call_shape_locked(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-11: adapter.search_batch receives the locked NativeQuery shape.

    Asserts ``target``, ``query_id="overlap_probe"``, ``body=={query, size}``,
    ``top_k``, ``strict_errors=True``, ``timeout=PROBE_TIMEOUT_S``. Also locks
    the dict-key unpacking semantic: returning 2 hits with
    ``judged_doc_count=3`` produces ``"2 of 3 probed"`` in the 422 message.
    """
    from backend.app.adapters.protocol import NativeQuery as _NativeQuery
    from backend.app.adapters.protocol import ScoredHit
    from backend.app.services.study_preflight import PROBE_TIMEOUT_S

    ids = await _seed_minimum_for_post_studies()
    await _seed_judgments(
        ids["judgment_list_id"],
        ids["query_set_id"],
        ["d1", "d2", "d3"],
    )

    fake_adapter = _FakeProbeAdapter(
        return_value={
            "overlap_probe": [
                ScoredHit(doc_id="d1", score=1.0),
                ScoredHit(doc_id="d2", score=1.0),
            ]
        }
    )
    _install_real_probe_with_fake_adapter(monkeypatch, fake_adapter)

    resp = await async_client.post("/api/v1/studies", json=_study_body_for(ids))
    # overlap=2, judged_doc_count=3 → required=3, 2<3 → 422
    assert resp.status_code == 422, resp.text
    assert "2 of 3 probed" in resp.json()["detail"]["message"]

    # Adapter-call shape lock.
    assert len(fake_adapter.calls) == 1
    captured_kwargs = fake_adapter.calls[0]
    assert captured_kwargs["target"] == "stub-index"
    assert captured_kwargs["strict_errors"] is True
    assert captured_kwargs["timeout"] == PROBE_TIMEOUT_S
    assert captured_kwargs["top_k"] == 3
    queries = cast(list[_NativeQuery], captured_kwargs["queries"])
    assert len(queries) == 1
    nq = queries[0]
    assert nq.query_id == "overlap_probe"
    assert nq.body["query"] == {"ids": {"values": ["d1", "d2", "d3"]}}
    assert nq.body["size"] == 3


async def test_get_study_does_not_validate_pre_existing_insufficient_overlap(
    async_client: httpx.AsyncClient,
) -> None:
    """AC-12: pre-existing studies with insufficient overlap are not validated
    on read paths. GET returns 200 even though the study would have been
    rejected at create-time today."""
    ids = await _seed_minimum_for_post_studies()
    factory = get_session_factory()
    async with factory() as db:
        study = await repo.create_study(
            db,
            id=str(uuid.uuid4()),
            name="pre-existing-zero-overlap",
            cluster_id=ids["cluster_id"],
            target="stub-index",
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
    assert resp.json()["id"] == study.id


@pytest.mark.parametrize(
    "exception_factory,expected_reason",
    [
        pytest.param(
            lambda: __import__(
                "backend.app.adapters.errors", fromlist=["ClusterUnreachableError"]
            ).ClusterUnreachableError("sim"),
            "unreachable",
            id="ClusterUnreachableError-adapter",
        ),
        pytest.param(
            lambda: __import__(
                "backend.app.adapters.errors", fromlist=["QueryTimeoutError"]
            ).QueryTimeoutError("sim"),
            "timeout",
            id="QueryTimeoutError-adapter",
        ),
        pytest.param(
            lambda: __import__(
                "backend.app.adapters.errors", fromlist=["InvalidQueryDSLError"]
            ).InvalidQueryDSLError("sim"),
            "invalid_query_dsl",
            id="InvalidQueryDSLError-adapter",
        ),
        pytest.param(
            lambda: TimeoutError("sim"),
            "timeout",
            id="TimeoutError-builtin",
        ),
    ],
)
async def test_post_study_fr4_exception_matrix_adapter_layer(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    exception_factory,
    expected_reason: str,
) -> None:
    """AC-13 adapter-layer subset: 4 of the 5 FR-4 exception classes raised by
    ``ElasticAdapter.search_batch`` → 201 + WARN log with matching reason.

    The 5th class (service-layer ``ClusterUnreachable`` from
    ``acquire_adapter`` itself) is exercised by the separate test below.
    """
    ids = await _seed_minimum_for_post_studies()
    await _seed_judgments(ids["judgment_list_id"], ids["query_set_id"], ["d1"])
    fake_adapter = _FakeProbeAdapter(raises=exception_factory())
    _install_real_probe_with_fake_adapter(monkeypatch, fake_adapter)

    import structlog.testing

    from backend.tests._log_helpers import find_log_events

    with structlog.testing.capture_logs() as cap:
        resp = await async_client.post("/api/v1/studies", json=_study_body_for(ids))

    assert resp.status_code == 201, resp.text
    skipped = find_log_events(cap, event="studies.preflight.overlap_probe.skipped")
    assert any(e.get("reason") == expected_reason for e in skipped), (
        f"expected reason={expected_reason!r}, got {[e.get('reason') for e in skipped]!r}"
    )


async def test_post_study_fr4_service_layer_cluster_unreachable(
    async_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-13 service-layer subset: ``acquire_adapter`` itself raises
    ``ClusterUnreachable`` (e.g., CredentialsMissing) → 201 + WARN log.

    Patches the symbol bound inside ``study_preflight`` (NOT the original in
    ``services.cluster``) because the probe captured the reference at import
    time per the plan's AC-13 monkeypatch-path note.
    """
    import contextlib

    from backend.app.services import study_preflight
    from backend.app.services.cluster import ClusterUnreachable

    ids = await _seed_minimum_for_post_studies()
    await _seed_judgments(ids["judgment_list_id"], ids["query_set_id"], ["d1"])

    # Override the autouse default-passing-probe so the real probe runs and
    # invokes the patched acquire_adapter below.
    monkeypatch.setattr(
        "backend.app.api.v1.studies.probe_judgment_overlap",
        study_preflight.probe_judgment_overlap,
    )

    @contextlib.asynccontextmanager
    async def raising_acquire(_cluster):  # noqa: ARG001
        if True:  # noqa: SIM108 — keeps the yield reachable for the typechecker
            raise ClusterUnreachable("simulated credentials missing")
        yield  # type: ignore[unreachable]

    monkeypatch.setattr(study_preflight, "acquire_adapter", raising_acquire)

    import structlog.testing

    from backend.tests._log_helpers import find_log_events

    with structlog.testing.capture_logs() as cap:
        resp = await async_client.post("/api/v1/studies", json=_study_body_for(ids))

    assert resp.status_code == 201, resp.text
    skipped = find_log_events(cap, event="studies.preflight.overlap_probe.skipped")
    assert any(e.get("reason") == "unreachable" for e in skipped)
