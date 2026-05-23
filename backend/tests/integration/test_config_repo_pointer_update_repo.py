"""Repo-layer tests for the last-merged-pointer helpers.

feat_config_repo_baseline_tracking Story 1.2. Real-Postgres AsyncSession
fixture; no mocks. Covers:

* :func:`update_config_repo_last_merged_pointer` — 3 monotonic-guard branches
  (NULL pointer → write; newer → write; older → skip) + same-timestamp no-op
  + concurrent-merge serialization via paired sessions on the same config_repo.
* :func:`find_currently_live_proposal_ids` — positive, negative, cross-repo.
* :func:`get_config_repo_with_last_merged_proposal` — missing config_repo
  returns None; NULL pointer returns tuple-with-Nones; populated pointer
  returns the full embed tuple.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

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


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


async def _seed_repo_cluster_template(suffix: str) -> tuple[str, str, str]:
    """Create one config_repo + one cluster wired to it + one query_template.

    Returns (config_repo_id, cluster_id, template_id).
    """
    factory = get_session_factory()
    async with factory() as db:
        cr = await repo.create_config_repo(
            db,
            id=str(uuid.uuid4()),
            name=f"pointer-cr-{suffix}",
            provider="github",
            repo_url=f"https://github.com/example/pointer-{suffix}",
            default_branch="main",
            pr_base_branch="main",
            auth_ref=f"ref-{suffix}",
        )
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"pointer-cluster-{suffix}",
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
            name=f"pointer-tpl-{suffix}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        await db.commit()
        return cr.id, cluster.id, template.id


async def _seed_merged_proposal(
    cluster_id: str,
    template_id: str,
    *,
    pr_merged_at: datetime,
) -> str:
    """Create one merged proposal wired to the given cluster + template. Returns id."""
    factory = get_session_factory()
    async with factory() as db:
        p = await repo.create_proposal(
            db,
            id=str(uuid.uuid4()),
            cluster_id=cluster_id,
            template_id=template_id,
            config_diff={},
            metric_delta={},
            status="pr_merged",
            pr_state="merged",
            pr_url=f"https://github.com/example/pull/{uuid.uuid4().hex[:6]}",
            pr_merged_at=pr_merged_at,
        )
        await db.commit()
        return p.id


# --------------------------------------------------------------------------
# update_config_repo_last_merged_pointer — monotonic-guard branches
# --------------------------------------------------------------------------


async def test_pointer_null_branch_writes() -> None:
    suffix = uuid.uuid4().hex[:6]
    cr_id, cluster_id, template_id = await _seed_repo_cluster_template(suffix)
    ts = datetime.now(UTC)
    p_id = await _seed_merged_proposal(cluster_id, template_id, pr_merged_at=ts)

    factory = get_session_factory()
    async with factory() as db:
        result = await repo.update_config_repo_last_merged_pointer(
            db,
            config_repo_id=cr_id,
            proposal_id=p_id,
            pr_merged_at=ts,
        )
        await db.commit()

    assert result is True
    async with factory() as db:
        row = await repo.get_config_repo(db, cr_id)
        assert row is not None
        assert row.last_merged_proposal_id == p_id


async def test_pointer_newer_timestamp_overwrites() -> None:
    suffix = uuid.uuid4().hex[:6]
    cr_id, cluster_id, template_id = await _seed_repo_cluster_template(suffix)
    ts_old = datetime.now(UTC) - timedelta(hours=2)
    ts_new = datetime.now(UTC)
    p_old = await _seed_merged_proposal(cluster_id, template_id, pr_merged_at=ts_old)
    p_new = await _seed_merged_proposal(cluster_id, template_id, pr_merged_at=ts_new)

    factory = get_session_factory()
    async with factory() as db:
        await repo.update_config_repo_last_merged_pointer(
            db, config_repo_id=cr_id, proposal_id=p_old, pr_merged_at=ts_old
        )
        await db.commit()
    async with factory() as db:
        result = await repo.update_config_repo_last_merged_pointer(
            db, config_repo_id=cr_id, proposal_id=p_new, pr_merged_at=ts_new
        )
        await db.commit()

    assert result is True
    async with factory() as db:
        row = await repo.get_config_repo(db, cr_id)
        assert row is not None
        assert row.last_merged_proposal_id == p_new


async def test_pointer_older_timestamp_skipped() -> None:
    suffix = uuid.uuid4().hex[:6]
    cr_id, cluster_id, template_id = await _seed_repo_cluster_template(suffix)
    ts_old = datetime.now(UTC) - timedelta(hours=2)
    ts_new = datetime.now(UTC)
    p_old = await _seed_merged_proposal(cluster_id, template_id, pr_merged_at=ts_old)
    p_new = await _seed_merged_proposal(cluster_id, template_id, pr_merged_at=ts_new)

    factory = get_session_factory()
    async with factory() as db:
        await repo.update_config_repo_last_merged_pointer(
            db, config_repo_id=cr_id, proposal_id=p_new, pr_merged_at=ts_new
        )
        await db.commit()
    async with factory() as db:
        result = await repo.update_config_repo_last_merged_pointer(
            db, config_repo_id=cr_id, proposal_id=p_old, pr_merged_at=ts_old
        )
        await db.commit()

    assert result is False
    async with factory() as db:
        row = await repo.get_config_repo(db, cr_id)
        assert row is not None
        assert row.last_merged_proposal_id == p_new  # not regressed


async def test_pointer_same_timestamp_skipped() -> None:
    suffix = uuid.uuid4().hex[:6]
    cr_id, cluster_id, template_id = await _seed_repo_cluster_template(suffix)
    ts = datetime.now(UTC)
    p_a = await _seed_merged_proposal(cluster_id, template_id, pr_merged_at=ts)
    p_b = await _seed_merged_proposal(cluster_id, template_id, pr_merged_at=ts)

    factory = get_session_factory()
    async with factory() as db:
        await repo.update_config_repo_last_merged_pointer(
            db, config_repo_id=cr_id, proposal_id=p_a, pr_merged_at=ts
        )
        await db.commit()
    async with factory() as db:
        result = await repo.update_config_repo_last_merged_pointer(
            db, config_repo_id=cr_id, proposal_id=p_b, pr_merged_at=ts
        )
        await db.commit()

    assert result is False  # strict-monotonic: equal timestamp does not overwrite
    async with factory() as db:
        row = await repo.get_config_repo(db, cr_id)
        assert row is not None
        assert row.last_merged_proposal_id == p_a


async def test_pointer_concurrent_merges_serialize() -> None:
    """Two parallel transactions on the same config_repo: row lock determinism.

    The newer-timestamp merge MUST end as the pointer regardless of which
    transaction acquires the SELECT … FOR UPDATE lock first.
    """
    suffix = uuid.uuid4().hex[:6]
    cr_id, cluster_id, template_id = await _seed_repo_cluster_template(suffix)
    ts_a = datetime.now(UTC)
    ts_b = ts_a + timedelta(seconds=1)
    p_a = await _seed_merged_proposal(cluster_id, template_id, pr_merged_at=ts_a)
    p_b = await _seed_merged_proposal(cluster_id, template_id, pr_merged_at=ts_b)

    factory = get_session_factory()

    async def _update(p_id: str, ts: datetime) -> bool:
        async with factory() as db:
            res = await repo.update_config_repo_last_merged_pointer(
                db, config_repo_id=cr_id, proposal_id=p_id, pr_merged_at=ts
            )
            await db.commit()
            return res

    results = await asyncio.gather(
        _update(p_a, ts_a),
        _update(p_b, ts_b),
    )
    # Both transactions ran; at least one wrote (whichever acquired the
    # SELECT FOR UPDATE first; the other either also wrote if its order
    # was monotone or skipped if it was older relative to the committed
    # value). Final state must be the newer-timestamp pointer.
    assert any(results), "neither transaction wrote — deadlock or contention bug"

    async with factory() as db:
        row = await repo.get_config_repo(db, cr_id)
        assert row is not None
        assert row.last_merged_proposal_id == p_b, (
            f"newer timestamp lost serialization: {row.last_merged_proposal_id}"
        )


# --------------------------------------------------------------------------
# find_currently_live_proposal_ids
# --------------------------------------------------------------------------


async def test_find_currently_live_positive_and_negative() -> None:
    suffix = uuid.uuid4().hex[:6]
    cr_id, cluster_id, template_id = await _seed_repo_cluster_template(suffix)
    ts = datetime.now(UTC)
    p_live = await _seed_merged_proposal(cluster_id, template_id, pr_merged_at=ts)
    p_other = await _seed_merged_proposal(cluster_id, template_id, pr_merged_at=ts)

    factory = get_session_factory()
    async with factory() as db:
        await repo.update_config_repo_last_merged_pointer(
            db, config_repo_id=cr_id, proposal_id=p_live, pr_merged_at=ts
        )
        await db.commit()

    async with factory() as db:
        live_set = await repo.find_currently_live_proposal_ids(db, [p_live, p_other])

    assert p_live in live_set
    assert p_other not in live_set


async def test_find_currently_live_empty_input_returns_empty() -> None:
    factory = get_session_factory()
    async with factory() as db:
        live_set = await repo.find_currently_live_proposal_ids(db, [])
    assert live_set == set()


async def test_find_currently_live_cross_repo() -> None:
    """One proposal per repo (each is live for its own repo); both appear."""
    suffix = uuid.uuid4().hex[:6]
    cr_a_id, cluster_a_id, template_id = await _seed_repo_cluster_template(suffix)
    cr_b_id, cluster_b_id, _template_id = await _seed_repo_cluster_template(f"{suffix}-b")
    ts = datetime.now(UTC)
    p_a = await _seed_merged_proposal(cluster_a_id, template_id, pr_merged_at=ts)
    p_b = await _seed_merged_proposal(cluster_b_id, template_id, pr_merged_at=ts)

    factory = get_session_factory()
    async with factory() as db:
        await repo.update_config_repo_last_merged_pointer(
            db, config_repo_id=cr_a_id, proposal_id=p_a, pr_merged_at=ts
        )
        await repo.update_config_repo_last_merged_pointer(
            db, config_repo_id=cr_b_id, proposal_id=p_b, pr_merged_at=ts
        )
        await db.commit()

    async with factory() as db:
        live_set = await repo.find_currently_live_proposal_ids(db, [p_a, p_b])

    assert {p_a, p_b} == live_set


# --------------------------------------------------------------------------
# get_config_repo_with_last_merged_proposal
# --------------------------------------------------------------------------


async def test_get_with_last_merged_missing_config_repo_returns_none() -> None:
    factory = get_session_factory()
    async with factory() as db:
        result = await repo.get_config_repo_with_last_merged_proposal(db, str(uuid.uuid4()))
    assert result is None


async def test_get_with_last_merged_null_pointer_returns_tuple_with_nones() -> None:
    suffix = uuid.uuid4().hex[:6]
    cr_id, _cluster_id, _template_id = await _seed_repo_cluster_template(suffix)

    factory = get_session_factory()
    async with factory() as db:
        result = await repo.get_config_repo_with_last_merged_proposal(db, cr_id)

    assert result is not None
    config_repo, proposal, cluster, template = result
    assert config_repo.id == cr_id
    assert proposal is None
    assert cluster is None
    assert template is None


async def test_get_with_last_merged_populated_pointer_returns_full_embed() -> None:
    suffix = uuid.uuid4().hex[:6]
    cr_id, cluster_id, template_id = await _seed_repo_cluster_template(suffix)
    ts = datetime.now(UTC)
    p_id = await _seed_merged_proposal(cluster_id, template_id, pr_merged_at=ts)

    factory = get_session_factory()
    async with factory() as db:
        await repo.update_config_repo_last_merged_pointer(
            db, config_repo_id=cr_id, proposal_id=p_id, pr_merged_at=ts
        )
        await db.commit()

    async with factory() as db:
        result = await repo.get_config_repo_with_last_merged_proposal(db, cr_id)

    assert result is not None
    config_repo, proposal, cluster, template = result
    assert config_repo.id == cr_id
    assert proposal is not None and proposal.id == p_id
    assert cluster is not None and cluster.id == cluster_id
    assert template is not None and template.id == template_id
