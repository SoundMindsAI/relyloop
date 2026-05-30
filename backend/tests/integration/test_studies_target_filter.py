# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for ``GET /api/v1/studies?target=`` (Story 2.4 / FR-5).

Asserts:

* AC-12 — ``?target=foo`` filters list and X-Total-Count.
* Composes with ``cluster_id`` via AND (intersection, not union).
* Composes with ``status`` via AND.
* Default (no ``?target=``) is unchanged — backward-compatible.
* Cycle-3 F2 — ``?target=foo&cursor=<malformed>`` → 422 (target filter
  doesn't bypass cursor validation).

Reuses the ``async_client`` + ``_seed_minimum_for_post_studies`` fixtures
from ``test_studies_api.py`` (imported via pytest fixture resolution).
"""

from __future__ import annotations

import uuid

import httpx
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _default_overlap_probe_passes(monkeypatch: pytest.MonkeyPatch):
    """Install a default-sufficient overlap probe so POST /studies succeeds
    without seeding real judgments.

    Pattern lifted from ``test_studies_api.py``'s autouse fixture — the
    overlap probe is part of POST /studies preflight and would otherwise
    reject every test body with INSUFFICIENT_JUDGMENT_OVERLAP.
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


async def _post_study(
    client: httpx.AsyncClient,
    *,
    ids: dict[str, str],
    target: str,
    name_prefix: str = "study",
) -> str:
    """POST one study against a seeded id-bundle, return the new study_id."""
    from backend.tests.integration.test_studies_api import _VALID_SEARCH_SPACE

    body = {
        "name": f"{name_prefix}-{uuid.uuid4().hex[:8]}",
        "cluster_id": ids["cluster_id"],
        "target": target,
        "template_id": ids["template_id"],
        "query_set_id": ids["query_set_id"],
        "judgment_list_id": ids["judgment_list_id"],
        "search_space": _VALID_SEARCH_SPACE,
        "objective": {"metric": "ndcg", "k": 10},
        "config": {"max_trials": 5},
    }
    resp = await client.post("/api/v1/studies", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_list_studies_filters_by_target(
    async_client: httpx.AsyncClient,
) -> None:
    """``?target=X`` returns only studies whose ``target`` equals X."""
    from backend.tests.integration.test_studies_api import (
        _seed_minimum_for_post_studies,
    )

    # The seeded judgment_list_id is bound to target="stub-index". To register
    # studies under a different target on the same cluster we'd need a second
    # seed bundle, but the validation is at study-creation time, so we seed
    # two independent bundles (each with target="stub-index" but distinct
    # cluster_ids).
    ids_a = await _seed_minimum_for_post_studies()
    ids_b = await _seed_minimum_for_post_studies()
    study_a = await _post_study(async_client, ids=ids_a, target="stub-index", name_prefix="a")
    study_b = await _post_study(async_client, ids=ids_b, target="stub-index", name_prefix="b")

    # Both studies have target="stub-index" so ?target=stub-index returns both
    # (across multiple clusters), and ?target=different-index returns neither.
    resp_stub = await async_client.get("/api/v1/studies?target=stub-index")
    assert resp_stub.status_code == 200
    ids_stub = {row["id"] for row in resp_stub.json()["data"]}
    assert study_a in ids_stub
    assert study_b in ids_stub

    resp_other = await async_client.get("/api/v1/studies?target=does-not-exist")
    assert resp_other.status_code == 200
    ids_other = {row["id"] for row in resp_other.json()["data"]}
    assert study_a not in ids_other
    assert study_b not in ids_other
    # X-Total-Count parity.
    assert int(resp_other.headers["X-Total-Count"]) == 0


async def test_target_composes_with_cluster_id_via_and(
    async_client: httpx.AsyncClient,
) -> None:
    """``?cluster_id=A&target=stub-index`` returns A's stub-index study
    only, not B's even though B also has target=stub-index."""
    from backend.tests.integration.test_studies_api import (
        _seed_minimum_for_post_studies,
    )

    ids_a = await _seed_minimum_for_post_studies()
    ids_b = await _seed_minimum_for_post_studies()
    study_a = await _post_study(async_client, ids=ids_a, target="stub-index", name_prefix="a")
    study_b = await _post_study(async_client, ids=ids_b, target="stub-index", name_prefix="b")

    resp = await async_client.get(
        f"/api/v1/studies?cluster_id={ids_a['cluster_id']}&target=stub-index"
    )
    assert resp.status_code == 200
    rows = {r["id"] for r in resp.json()["data"]}
    assert study_a in rows
    assert study_b not in rows


async def test_target_composes_with_status_via_and(
    async_client: httpx.AsyncClient,
) -> None:
    """``?status=queued&target=stub-index`` filters by both simultaneously."""
    from backend.tests.integration.test_studies_api import (
        _seed_minimum_for_post_studies,
    )

    ids = await _seed_minimum_for_post_studies()
    study_id = await _post_study(async_client, ids=ids, target="stub-index")

    # New studies start in status="queued" per the study state machine
    # (see backend.app.api.v1.schemas.StudyStatusWire).
    resp = await async_client.get("/api/v1/studies?status=queued&target=stub-index")
    assert resp.status_code == 200
    rows = {r["id"] for r in resp.json()["data"]}
    assert study_id in rows

    # Different target → 0 rows even though status matches.
    resp2 = await async_client.get("/api/v1/studies?status=queued&target=other")
    assert resp2.status_code == 200
    assert study_id not in {r["id"] for r in resp2.json()["data"]}


async def test_no_target_param_is_unchanged_behavior(
    async_client: httpx.AsyncClient,
) -> None:
    """Default (no ``?target=``) returns every study — backward-compatible."""
    from backend.tests.integration.test_studies_api import (
        _seed_minimum_for_post_studies,
    )

    ids = await _seed_minimum_for_post_studies()
    study_id = await _post_study(async_client, ids=ids, target="stub-index")

    resp = await async_client.get("/api/v1/studies")
    assert resp.status_code == 200
    assert study_id in {r["id"] for r in resp.json()["data"]}


async def test_target_filter_with_malformed_cursor_returns_422(
    async_client: httpx.AsyncClient,
) -> None:
    """Cycle-3 F2 — ``?target=foo&cursor=<malformed>`` → 422 VALIDATION_ERROR.

    Confirms the target filter doesn't accidentally bypass cursor decode
    (e.g., if the order of operations swapped). Cursor validation must
    still fire.
    """
    resp = await async_client.get(
        "/api/v1/studies?target=acme-products-rich&cursor=!!!not-a-valid-cursor!!!"
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"]["error_code"] == "VALIDATION_ERROR"
    assert body["detail"]["retryable"] is False


async def test_target_min_length_rejected(
    async_client: httpx.AsyncClient,
) -> None:
    """Empty ``?target=`` is rejected by FastAPI's Query(min_length=1)."""
    resp = await async_client.get("/api/v1/studies?target=")
    assert resp.status_code == 422
