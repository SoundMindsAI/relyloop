# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""GET /api/v1/proposals — is_currently_live + ?is_last_merged filter.

feat_config_repo_baseline_tracking Stories 2.2 + 2.3 (FR-5 + FR-6).

Covers AC-9 (per-row is_currently_live), AC-10 (?is_last_merged=true filter),
AC-11 (?is_last_merged=false complement), AC-12 (invalid filter → 422 wrapped
envelope), AC-14 (detail endpoint carries is_currently_live), and a
compose-with-existing-filters case.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

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


async def _seed_repo_cluster_template(suffix: str) -> tuple[str, str, str]:
    factory = get_session_factory()
    async with factory() as db:
        cr = await repo.create_config_repo(
            db,
            id=str(uuid.uuid4()),
            name=f"flt-cr-{suffix}",
            provider="github",
            repo_url=f"https://github.com/example/flt-{suffix}",
            default_branch="main",
            pr_base_branch="main",
            auth_ref=f"ref-{suffix}",
        )
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"flt-cluster-{suffix}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
            config_repo_id=cr.id,
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"flt-tpl-{suffix}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        await db.commit()
        return cr.id, cluster.id, template.id


async def _seed_merged_proposal_under(cluster_id: str, template_id: str, *, status: str) -> str:
    factory = get_session_factory()
    async with factory() as db:
        proposal = await repo.create_proposal(
            db,
            id=str(uuid.uuid4()),
            study_id=None,
            study_trial_id=None,
            cluster_id=cluster_id,
            template_id=template_id,
            config_diff={},
            metric_delta=None,
            status=status,
            pr_state="merged" if status == "pr_merged" else None,
            pr_url=f"https://github.com/example/pull/{uuid.uuid4().hex[:6]}",
            pr_merged_at=datetime.now(UTC) if status == "pr_merged" else None,
        )
        await db.commit()
        return proposal.id


async def test_ac9_summary_is_currently_live_per_row(
    async_client: httpx.AsyncClient,
) -> None:
    """One live + several non-live proposals share a cluster; only the live one
    has is_currently_live=true in the list response."""
    suffix = uuid.uuid4().hex[:6]
    cr_id, cluster_id, template_id = await _seed_repo_cluster_template(suffix)
    p_live = await _seed_merged_proposal_under(cluster_id, template_id, status="pr_merged")
    # Other proposals under the same cluster, NOT pointer targets.
    p_other_merged = await _seed_merged_proposal_under(cluster_id, template_id, status="pr_merged")
    p_pending = await _seed_merged_proposal_under(cluster_id, template_id, status="pending")

    factory = get_session_factory()
    async with factory() as db:
        await repo.update_config_repo_last_merged_pointer(
            db,
            config_repo_id=cr_id,
            proposal_id=p_live,
            pr_merged_at=datetime.now(UTC),
        )
        await db.commit()

    resp = await async_client.get(f"/api/v1/proposals?cluster_id={cluster_id}&limit=200")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    rows = {row["id"]: row for row in body["data"]}
    assert p_live in rows
    assert rows[p_live]["is_currently_live"] is True
    assert p_other_merged in rows
    assert rows[p_other_merged]["is_currently_live"] is False
    assert p_pending in rows
    assert rows[p_pending]["is_currently_live"] is False


async def test_ac10_is_last_merged_true_returns_live_only(
    async_client: httpx.AsyncClient,
) -> None:
    """Three config_repos each with a pointer + extras; ?is_last_merged=true
    returns exactly the live proposals (one per config_repo)."""
    suffix = uuid.uuid4().hex[:6]
    live_ids: list[str] = []
    for i in range(3):
        cr_id, cluster_id, template_id = await _seed_repo_cluster_template(f"{suffix}-{i}")
        p_id = await _seed_merged_proposal_under(cluster_id, template_id, status="pr_merged")
        # Add a non-live proposal under the same cluster.
        await _seed_merged_proposal_under(cluster_id, template_id, status="pr_merged")
        factory = get_session_factory()
        async with factory() as db:
            await repo.update_config_repo_last_merged_pointer(
                db,
                config_repo_id=cr_id,
                proposal_id=p_id,
                pr_merged_at=datetime.now(UTC),
            )
            await db.commit()
        live_ids.append(p_id)

    resp = await async_client.get("/api/v1/proposals?is_last_merged=true&limit=200")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    returned_ids = {row["id"] for row in body["data"]}
    # Every live id we just seeded must be in the filtered set.
    for live_id in live_ids:
        assert live_id in returned_ids
        # And every returned row must have is_currently_live=true.
    for row in body["data"]:
        assert row["is_currently_live"] is True


async def test_ac11_is_last_merged_false_returns_complement(
    async_client: httpx.AsyncClient,
) -> None:
    """?is_last_merged=false returns proposals NOT tracked by any config_repo."""
    suffix = uuid.uuid4().hex[:6]
    cr_id, cluster_id, template_id = await _seed_repo_cluster_template(suffix)
    p_live = await _seed_merged_proposal_under(cluster_id, template_id, status="pr_merged")
    p_other = await _seed_merged_proposal_under(cluster_id, template_id, status="pr_merged")

    factory = get_session_factory()
    async with factory() as db:
        await repo.update_config_repo_last_merged_pointer(
            db,
            config_repo_id=cr_id,
            proposal_id=p_live,
            pr_merged_at=datetime.now(UTC),
        )
        await db.commit()

    resp = await async_client.get(
        f"/api/v1/proposals?is_last_merged=false&cluster_id={cluster_id}&limit=200"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {row["id"] for row in body["data"]}
    assert p_live not in ids  # filtered out
    assert p_other in ids
    for row in body["data"]:
        assert row["is_currently_live"] is False


async def test_ac12_invalid_is_last_merged_value_returns_wrapped_envelope(
    async_client: httpx.AsyncClient,
) -> None:
    """Non-bool query value → 422 with standard envelope (global handler)."""
    resp = await async_client.get("/api/v1/proposals?is_last_merged=maybe")
    assert resp.status_code == 422
    body = resp.json()
    assert "detail" in body
    detail = body["detail"]
    # Wrapped envelope per backend/app/api/errors.py:103-118.
    assert isinstance(detail, dict)
    assert detail.get("error_code") == "VALIDATION_ERROR"
    assert detail.get("retryable") is False


async def test_ac14_proposal_detail_carries_is_currently_live(
    async_client: httpx.AsyncClient,
) -> None:
    """GET /api/v1/proposals/{id} response includes is_currently_live."""
    suffix = uuid.uuid4().hex[:6]
    cr_id, cluster_id, template_id = await _seed_repo_cluster_template(suffix)
    p_live = await _seed_merged_proposal_under(cluster_id, template_id, status="pr_merged")
    p_other = await _seed_merged_proposal_under(cluster_id, template_id, status="pr_merged")

    factory = get_session_factory()
    async with factory() as db:
        await repo.update_config_repo_last_merged_pointer(
            db,
            config_repo_id=cr_id,
            proposal_id=p_live,
            pr_merged_at=datetime.now(UTC),
        )
        await db.commit()

    resp_live = await async_client.get(f"/api/v1/proposals/{p_live}")
    assert resp_live.status_code == 200, resp_live.text
    assert resp_live.json()["is_currently_live"] is True

    resp_other = await async_client.get(f"/api/v1/proposals/{p_other}")
    assert resp_other.status_code == 200, resp_other.text
    assert resp_other.json()["is_currently_live"] is False


async def test_is_last_merged_composes_with_status_filter(
    async_client: httpx.AsyncClient,
) -> None:
    """?is_last_merged=true&status=pr_merged returns the same set as ?is_last_merged=true alone
    (live proposals are by definition pr_merged)."""
    suffix = uuid.uuid4().hex[:6]
    cr_id, cluster_id, template_id = await _seed_repo_cluster_template(suffix)
    p_live = await _seed_merged_proposal_under(cluster_id, template_id, status="pr_merged")

    factory = get_session_factory()
    async with factory() as db:
        await repo.update_config_repo_last_merged_pointer(
            db,
            config_repo_id=cr_id,
            proposal_id=p_live,
            pr_merged_at=datetime.now(UTC),
        )
        await db.commit()

    resp_both = await async_client.get(
        f"/api/v1/proposals?is_last_merged=true&status=pr_merged&cluster_id={cluster_id}&limit=200"
    )
    assert resp_both.status_code == 200, resp_both.text
    ids_both = {row["id"] for row in resp_both.json()["data"]}
    assert p_live in ids_both
    for row in resp_both.json()["data"]:
        assert row["is_currently_live"] is True
        assert row["status"] == "pr_merged"
