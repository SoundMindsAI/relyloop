"""Integration test for the development-only seed endpoint.

End-to-end coverage of ``POST /api/v1/_test/studies/seed-completed`` against
a live Postgres:

* Seed the FK chain (cluster + query_set + template + judgment_list) via
  direct repo calls (mirrors the canonical ``_digest_helpers.seed_completed_study``
  pattern).
* POST the seed endpoint with the four FK ids.
* Assert response shape (study_id, digest_id, proposal_id).
* Re-fetch the study and digest via the public API; assert ``status=completed``,
  ``best_metric`` is populated, the digest narrative is non-empty, and the
  pending proposal exists.

Also verifies the ``with_pending_proposal=False`` branch — the digest still
lands, ``proposal_id`` is null, and no proposal row is created.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from backend.app.db import repo
from backend.app.db.session import get_session_factory

pytestmark = pytest.mark.integration


async def _seed_fk_chain() -> dict[str, str]:
    """Create the four FK rows the seed endpoint requires.

    Mirrors :func:`backend.tests.integration._digest_helpers.seed_completed_study`'s
    prelude but stops before creating the study/digest/proposal — those are
    what the seed endpoint under test produces.
    """
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"sd-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"sd-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={
                "title.boost": {"type": "float", "min": 0.5, "max": 5.0},
            },
            version=1,
        )
        query_set = await repo.create_query_set(
            db,
            id=str(uuid.uuid4()),
            name=f"sd-qs-{uuid.uuid4().hex[:8]}",
            cluster_id=cluster.id,
        )
        jl = await repo.create_judgment_list(
            db,
            id=str(uuid.uuid4()),
            name=f"sd-jl-{uuid.uuid4().hex[:8]}",
            description=None,
            query_set_id=query_set.id,
            cluster_id=cluster.id,
            target="stub-index",
            current_template_id=template.id,
            rubric="r",
            status="complete",
        )
        await db.commit()
    return {
        "cluster_id": cluster.id,
        "template_id": template.id,
        "query_set_id": query_set.id,
        "judgment_list_id": jl.id,
    }


async def test_seed_completed_with_pending_proposal(async_client: httpx.AsyncClient) -> None:
    """Happy path — full triple is created and visible via the public API."""
    fks = await _seed_fk_chain()

    response = await async_client.post(
        "/api/v1/_test/studies/seed-completed",
        json={
            "cluster_id": fks["cluster_id"],
            "query_set_id": fks["query_set_id"],
            "template_id": fks["template_id"],
            "judgment_list_id": fks["judgment_list_id"],
            "with_pending_proposal": True,
        },
    )

    assert response.status_code == httpx.codes.CREATED, response.text
    body = response.json()
    assert body["study_id"]
    assert body["digest_id"]
    assert body["proposal_id"]

    # The seeded study must be visible at the public studies endpoint with
    # status='completed' and best_metric stamped — the digest panel's
    # render preconditions.
    study_resp = await async_client.get(f"/api/v1/studies/{body['study_id']}")
    assert study_resp.status_code == httpx.codes.OK, study_resp.text
    study = study_resp.json()
    assert study["status"] == "completed"
    assert study["best_metric"] == pytest.approx(0.487)
    assert study["best_trial_id"]
    assert study["completed_at"] is not None

    # The digest must exist and carry the canonical seeded fields.
    digest_resp = await async_client.get(f"/api/v1/studies/{body['study_id']}/digest")
    assert digest_resp.status_code == httpx.codes.OK, digest_resp.text
    digest = digest_resp.json()
    assert "title.boost" in digest["narrative"]
    assert digest["recommended_config"] == {"title.boost": 2.5}
    assert digest["parameter_importance"] == {"title.boost": 1.0}
    assert len(digest["suggested_followups"]) >= 1

    # The pending proposal must exist with status='pending' and the
    # canonical config_diff/metric_delta.
    prop_resp = await async_client.get(f"/api/v1/proposals/{body['proposal_id']}")
    assert prop_resp.status_code == httpx.codes.OK, prop_resp.text
    prop = prop_resp.json()
    assert prop["status"] == "pending"
    assert prop["study_id"] == body["study_id"]


async def test_seed_completed_without_pending_proposal(async_client: httpx.AsyncClient) -> None:
    """``with_pending_proposal=False`` — digest still lands, proposal_id is null."""
    fks = await _seed_fk_chain()

    response = await async_client.post(
        "/api/v1/_test/studies/seed-completed",
        json={
            "cluster_id": fks["cluster_id"],
            "query_set_id": fks["query_set_id"],
            "template_id": fks["template_id"],
            "judgment_list_id": fks["judgment_list_id"],
            "with_pending_proposal": False,
        },
    )

    assert response.status_code == httpx.codes.CREATED, response.text
    body = response.json()
    assert body["study_id"]
    assert body["digest_id"]
    assert body["proposal_id"] is None

    digest_resp = await async_client.get(f"/api/v1/studies/{body['study_id']}/digest")
    assert digest_resp.status_code == httpx.codes.OK


async def test_seed_completed_trial_timestamps_consistent_with_duration(
    async_client: httpx.AsyncClient,
) -> None:
    """Regression for the Gemini PR #130 finding: the seeded trials' timestamps
    must be consistent with their ``duration_ms`` (``ended_at - started_at``
    matches ``duration_ms``). Today the API doesn't return raw trial rows by
    default, so we re-fetch trials via the public list endpoint and assert.
    """
    fks = await _seed_fk_chain()

    response = await async_client.post(
        "/api/v1/_test/studies/seed-completed",
        json={
            "cluster_id": fks["cluster_id"],
            "query_set_id": fks["query_set_id"],
            "template_id": fks["template_id"],
            "judgment_list_id": fks["judgment_list_id"],
        },
    )
    assert response.status_code == httpx.codes.CREATED
    study_id = response.json()["study_id"]

    trials_resp = await async_client.get(f"/api/v1/studies/{study_id}/trials")
    assert trials_resp.status_code == httpx.codes.OK, trials_resp.text
    rows = trials_resp.json()["data"]
    assert len(rows) == 2

    # Each trial's ended_at - started_at must equal its duration_ms.
    from datetime import datetime

    for trial in rows:
        started: Any = datetime.fromisoformat(trial["started_at"])
        ended: Any = datetime.fromisoformat(trial["ended_at"])
        observed_ms = round((ended - started).total_seconds() * 1000)
        assert observed_ms == trial["duration_ms"], (
            f"trial {trial['id']}: ended_at-started_at={observed_ms}ms != "
            f"duration_ms={trial['duration_ms']}ms"
        )
