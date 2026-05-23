"""Integration tests for GET /api/v1/config-repos/{id} last_merged_proposal field.

feat_config_repo_baseline_tracking Story 2.1 (FR-4). Covers AC-8 (detail
endpoint embeds the proposal summary), the null-pointer case, and the
cluster-rotation case (embed-side is_currently_live=True even after rotation).
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


async def _seed_wired_repo_and_cluster(suffix: str) -> tuple[str, str, str]:
    """Return (config_repo_id, cluster_id, template_id)."""
    factory = get_session_factory()
    async with factory() as db:
        cr = await repo.create_config_repo(
            db,
            id=str(uuid.uuid4()),
            name=f"detail-cr-{suffix}",
            provider="github",
            repo_url=f"https://github.com/example/detail-{suffix}",
            default_branch="main",
            pr_base_branch="main",
            auth_ref=f"ref-{suffix}",
        )
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"detail-cluster-{suffix}",
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
            name=f"detail-tpl-{suffix}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        await db.commit()
        return cr.id, cluster.id, template.id


async def _seed_merged_proposal(cluster_id: str, template_id: str) -> str:
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
            metric_delta={"ndcg@10": {"baseline": 0.4, "achieved": 0.5, "delta_pct": 25.0}},
            status="pr_merged",
            pr_state="merged",
            pr_url=f"https://github.com/example/pull/{uuid.uuid4().hex[:6]}",
            pr_merged_at=datetime.now(UTC),
        )
        await db.commit()
        return proposal.id


async def test_ac8_detail_endpoint_embeds_last_merged_proposal(
    async_client: httpx.AsyncClient,
) -> None:
    """AC-8: pointer set → last_merged_proposal populated with is_currently_live=True."""
    suffix = uuid.uuid4().hex[:6]
    cr_id, cluster_id, template_id = await _seed_wired_repo_and_cluster(suffix)
    p_id = await _seed_merged_proposal(cluster_id, template_id)

    factory = get_session_factory()
    async with factory() as db:
        await repo.update_config_repo_last_merged_pointer(
            db,
            config_repo_id=cr_id,
            proposal_id=p_id,
            pr_merged_at=datetime.now(UTC),
        )
        await db.commit()

    resp = await async_client.get(f"/api/v1/config-repos/{cr_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == cr_id
    assert body["last_merged_proposal"] is not None
    embedded = body["last_merged_proposal"]
    assert embedded["id"] == p_id
    assert embedded["status"] == "pr_merged"
    assert embedded["pr_state"] == "merged"
    assert embedded["is_currently_live"] is True


async def test_detail_endpoint_null_pointer_returns_null_field(
    async_client: httpx.AsyncClient,
) -> None:
    """No merged proposal yet → last_merged_proposal is null."""
    suffix = uuid.uuid4().hex[:6]
    cr_id, _cluster_id, _template_id = await _seed_wired_repo_and_cluster(suffix)

    resp = await async_client.get(f"/api/v1/config-repos/{cr_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == cr_id
    assert body["last_merged_proposal"] is None


async def test_detail_endpoint_embed_is_currently_live_after_cluster_rotation(
    async_client: httpx.AsyncClient,
) -> None:
    """Cluster's config_repo_id later set to NULL (rotation) — embed-side
    is_currently_live MUST still be True because the pointer itself is the
    source of truth (spec §19 "Cluster-with-config_repo-rotated" decision-log).

    The generic JOIN-based is_currently_live derivation used in Story 2.2
    would return False here; the embed-side derivation in Story 2.1's
    endpoint hard-codes True so AC-8 holds even in this edge case.
    """
    suffix = uuid.uuid4().hex[:6]
    cr_id, cluster_id, template_id = await _seed_wired_repo_and_cluster(suffix)
    p_id = await _seed_merged_proposal(cluster_id, template_id)

    factory = get_session_factory()
    async with factory() as db:
        await repo.update_config_repo_last_merged_pointer(
            db,
            config_repo_id=cr_id,
            proposal_id=p_id,
            pr_merged_at=datetime.now(UTC),
        )
        await db.commit()

    # Rotate: unwire the cluster from the config_repo.
    async with factory() as db:
        cluster = await repo.get_cluster(db, cluster_id)
        assert cluster is not None
        cluster.config_repo_id = None
        await db.flush()
        await db.commit()

    resp = await async_client.get(f"/api/v1/config-repos/{cr_id}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    embedded = body["last_merged_proposal"]
    assert embedded is not None, "pointer should still resolve even after rotation"
    assert embedded["id"] == p_id
    assert embedded["is_currently_live"] is True, (
        "embed-side is_currently_live must be True regardless of cluster wiring"
    )


async def test_detail_endpoint_missing_repo_returns_404(
    async_client: httpx.AsyncClient,
) -> None:
    """404 envelope preserved for unknown config_repo id (FR-4 return-None branch)."""
    resp = await async_client.get(f"/api/v1/config-repos/{uuid.uuid4()}")
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"]["error_code"] == "CONFIG_REPO_NOT_FOUND"
