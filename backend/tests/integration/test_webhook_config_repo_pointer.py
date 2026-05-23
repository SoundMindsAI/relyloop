"""Webhook integration tests for config_repos.last_merged_proposal_id pointer.

feat_config_repo_baseline_tracking Story 1.3 (FR-3). Covers AC-3, AC-4, AC-5,
AC-6, AC-7, AC-15 — all webhook-driven pointer-maintenance ACs.

Builds on the seed helpers and HMAC-signing utilities established by
``test_webhook_github.py``; uses a local seed that WIRES the cluster to the
config_repo (the existing helper leaves cluster.config_repo_id NULL, which
exercises AC-6 specifically but isn't suitable for AC-3 et al.).
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

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


_WEBHOOK_SECRET = "test-webhook-pointer-secret"


def _signature(body: bytes, secret: str = _WEBHOOK_SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest_asyncio.fixture
async def wired_webhook_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[dict[str, str]]:
    """Seed config_repo + cluster wired to it + webhook-secret with unique owner/repo."""
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    secret_ref = f"webhook-secret-{uuid.uuid4().hex[:8]}"
    (secrets_dir / secret_ref).write_text(_WEBHOOK_SECRET + "\n")
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(secrets_dir))

    suffix = uuid.uuid4().hex[:8]
    owner = f"ptr-owner-{suffix}"
    repo_name = f"ptr-repo-{suffix}"

    factory = get_session_factory()
    async with factory() as db:
        cr = await repo.create_config_repo(
            db,
            id=str(uuid.uuid4()),
            name=f"cr-ptr-{suffix}",
            provider="github",
            repo_url=f"https://github.com/{owner}/{repo_name}",
            default_branch="main",
            pr_base_branch="main",
            auth_ref=f"pat-{suffix}",
            webhook_secret_ref=secret_ref,
        )
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"cluster-ptr-{suffix}",
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
            name=f"tmpl-ptr-{suffix}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        await db.commit()

    yield {
        "config_repo_id": cr.id,
        "cluster_id": cluster.id,
        "template_id": template.id,
        "owner": owner,
        "repo": repo_name,
    }


async def _seed_pr_opened_proposal_under_cluster(
    *, cluster_id: str, template_id: str, pr_url: str
) -> str:
    """Create a pending proposal under a specific cluster + template, then mark pr_opened."""
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
            status="pending",
        )
        await db.commit()
        pid = proposal.id
    async with factory() as db:
        await repo.mark_proposal_pr_opened(db, pid, pr_url=pr_url)
        await db.commit()
    return pid


def _merge_body(*, pr_url: str, owner: str, repo_name: str, merged_at_iso: str) -> bytes:
    payload: dict[str, object] = {
        "action": "closed",
        "repository": {"full_name": f"{owner}/{repo_name}"},
        "pull_request": {
            "html_url": pr_url,
            "merged": True,
            "merged_at": merged_at_iso,
        },
    }
    return json.dumps(payload).encode("utf-8")


async def _send_merge_webhook(
    async_client: httpx.AsyncClient,
    *,
    pr_url: str,
    owner: str,
    repo_name: str,
    merged_at_iso: str,
    delivery_id: str,
) -> httpx.Response:
    body = _merge_body(pr_url=pr_url, owner=owner, repo_name=repo_name, merged_at_iso=merged_at_iso)
    return await async_client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": delivery_id,
            "X-Hub-Signature-256": _signature(body),
            "Content-Type": "application/json",
        },
    )


# --------------------------------------------------------------------------
# AC-3: first merge sets the pointer + persists all state-transition fields
# --------------------------------------------------------------------------


async def test_ac3_webhook_first_merge_sets_pointer(
    async_client: httpx.AsyncClient,
    wired_webhook_env: dict[str, str],
) -> None:
    pr_url = (
        f"https://github.com/{wired_webhook_env['owner']}/{wired_webhook_env['repo']}"
        f"/pull/{uuid.uuid4().int % 10_000}"
    )
    pid = await _seed_pr_opened_proposal_under_cluster(
        cluster_id=wired_webhook_env["cluster_id"],
        template_id=wired_webhook_env["template_id"],
        pr_url=pr_url,
    )

    merged_at = "2026-05-22T14:30:00+00:00"
    response = await _send_merge_webhook(
        async_client,
        pr_url=pr_url,
        owner=wired_webhook_env["owner"],
        repo_name=wired_webhook_env["repo"],
        merged_at_iso=merged_at,
        delivery_id="ac3-first-merge",
    )
    assert response.status_code == 200, response.text

    factory = get_session_factory()
    async with factory() as db:
        # All four AC-3 state pieces.
        prop = await repo.get_proposal(db, pid)
        assert prop is not None
        assert prop.status == "pr_merged"
        assert prop.pr_state == "merged"
        assert prop.pr_merged_at is not None
        assert prop.pr_merged_at.isoformat().startswith("2026-05-22T14:30:00")
        # And the pointer.
        cr = await repo.get_config_repo(db, wired_webhook_env["config_repo_id"])
        assert cr is not None
        assert cr.last_merged_proposal_id == pid


# --------------------------------------------------------------------------
# AC-4: out-of-order merge does NOT regress the pointer
# --------------------------------------------------------------------------


async def test_ac4_out_of_order_merge_does_not_regress_pointer(
    async_client: httpx.AsyncClient,
    wired_webhook_env: dict[str, str],
) -> None:
    owner = wired_webhook_env["owner"]
    repo_name = wired_webhook_env["repo"]

    # P2 merged at t2 = 2026-05-22T14:30:00Z (newer).
    pr_url_2 = f"https://github.com/{owner}/{repo_name}/pull/{uuid.uuid4().int % 10_000}"
    pid_2 = await _seed_pr_opened_proposal_under_cluster(
        cluster_id=wired_webhook_env["cluster_id"],
        template_id=wired_webhook_env["template_id"],
        pr_url=pr_url_2,
    )
    resp_2 = await _send_merge_webhook(
        async_client,
        pr_url=pr_url_2,
        owner=owner,
        repo_name=repo_name,
        merged_at_iso="2026-05-22T14:30:00+00:00",
        delivery_id="ac4-p2-merge",
    )
    assert resp_2.status_code == 200

    # P1 merged at t1 = 2026-05-22T10:00:00Z (older) — late-arriving webhook.
    pr_url_1 = f"https://github.com/{owner}/{repo_name}/pull/{uuid.uuid4().int % 10_000}"
    pid_1 = await _seed_pr_opened_proposal_under_cluster(
        cluster_id=wired_webhook_env["cluster_id"],
        template_id=wired_webhook_env["template_id"],
        pr_url=pr_url_1,
    )
    resp_1 = await _send_merge_webhook(
        async_client,
        pr_url=pr_url_1,
        owner=owner,
        repo_name=repo_name,
        merged_at_iso="2026-05-22T10:00:00+00:00",
        delivery_id="ac4-p1-late",
    )
    assert resp_1.status_code == 200

    factory = get_session_factory()
    async with factory() as db:
        # Both proposals transitioned to merged.
        prop_1 = await repo.get_proposal(db, pid_1)
        prop_2 = await repo.get_proposal(db, pid_2)
        assert prop_1 is not None and prop_1.status == "pr_merged"
        assert prop_2 is not None and prop_2.status == "pr_merged"
        # Pointer stays at P2 (newer) — NOT regressed by P1's late delivery.
        cr = await repo.get_config_repo(db, wired_webhook_env["config_repo_id"])
        assert cr is not None
        assert cr.last_merged_proposal_id == pid_2


# --------------------------------------------------------------------------
# AC-5: duplicate webhook is a no-op (pointer-update function not invoked)
# --------------------------------------------------------------------------


async def test_ac5_duplicate_merge_webhook_is_noop(
    async_client: httpx.AsyncClient,
    wired_webhook_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = wired_webhook_env["owner"]
    repo_name = wired_webhook_env["repo"]

    pr_url = f"https://github.com/{owner}/{repo_name}/pull/{uuid.uuid4().int % 10_000}"
    pid = await _seed_pr_opened_proposal_under_cluster(
        cluster_id=wired_webhook_env["cluster_id"],
        template_id=wired_webhook_env["template_id"],
        pr_url=pr_url,
    )

    # First delivery — sets the pointer.
    resp_first = await _send_merge_webhook(
        async_client,
        pr_url=pr_url,
        owner=owner,
        repo_name=repo_name,
        merged_at_iso="2026-05-22T14:30:00+00:00",
        delivery_id="ac5-first",
    )
    assert resp_first.status_code == 200

    # Spy: now wrap update_config_repo_last_merged_pointer. Re-fire the
    # same webhook and assert the spy was NOT invoked (the proposal is
    # already pr_merged, so mark_proposal_pr_merged returns None and the
    # downstream pointer-update branch is skipped entirely).
    call_count = {"n": 0}
    real_update = repo.update_config_repo_last_merged_pointer

    async def _spy(*args: object, **kwargs: object) -> bool:
        call_count["n"] += 1
        return await real_update(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "backend.app.api.webhooks.github.repo.update_config_repo_last_merged_pointer",
        _spy,
    )

    resp_dup = await _send_merge_webhook(
        async_client,
        pr_url=pr_url,
        owner=owner,
        repo_name=repo_name,
        merged_at_iso="2026-05-22T14:30:00+00:00",
        delivery_id="ac5-duplicate",
    )
    assert resp_dup.status_code == 200
    assert call_count["n"] == 0, "pointer-update fired on duplicate delivery"

    factory = get_session_factory()
    async with factory() as db:
        cr = await repo.get_config_repo(db, wired_webhook_env["config_repo_id"])
        assert cr is not None
        assert cr.last_merged_proposal_id == pid  # unchanged


# --------------------------------------------------------------------------
# AC-6: cluster with NULL config_repo_id is silently skipped
# --------------------------------------------------------------------------


async def test_ac6_null_cluster_config_repo_id_skipped(
    async_client: httpx.AsyncClient,
    wired_webhook_env: dict[str, str],
) -> None:
    owner = wired_webhook_env["owner"]
    repo_name = wired_webhook_env["repo"]

    # Create a SECOND cluster, NOT wired to any config_repo. Proposal goes
    # under this orphan cluster; webhook fires; proposal flips to merged
    # but the pointer-update path falls through to the DEBUG skip log.
    factory = get_session_factory()
    async with factory() as db:
        orphan = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"orphan-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
            # config_repo_id deliberately omitted — NULL.
        )
        await db.commit()
        orphan_cluster_id = orphan.id

    pr_url = f"https://github.com/{owner}/{repo_name}/pull/{uuid.uuid4().int % 10_000}"
    pid = await _seed_pr_opened_proposal_under_cluster(
        cluster_id=orphan_cluster_id,
        template_id=wired_webhook_env["template_id"],
        pr_url=pr_url,
    )

    resp = await _send_merge_webhook(
        async_client,
        pr_url=pr_url,
        owner=owner,
        repo_name=repo_name,
        merged_at_iso="2026-05-22T14:30:00+00:00",
        delivery_id="ac6-no-repo",
    )
    assert resp.status_code == 200

    factory = get_session_factory()
    async with factory() as db:
        # Proposal transitioned to merged (the orphan cluster doesn't block that).
        prop = await repo.get_proposal(db, pid)
        assert prop is not None and prop.status == "pr_merged"
        # But the original config_repo's pointer is untouched (orphan
        # cluster has no config_repo_id).
        cr = await repo.get_config_repo(db, wired_webhook_env["config_repo_id"])
        assert cr is not None
        assert cr.last_merged_proposal_id is None


# --------------------------------------------------------------------------
# AC-7: concurrent merges on the same config_repo serialize via row lock
# --------------------------------------------------------------------------


async def test_ac7_concurrent_merges_serialize_via_row_lock(
    async_client: httpx.AsyncClient,
    wired_webhook_env: dict[str, str],
) -> None:
    owner = wired_webhook_env["owner"]
    repo_name = wired_webhook_env["repo"]

    pr_url_a = f"https://github.com/{owner}/{repo_name}/pull/{uuid.uuid4().int % 10_000}"
    pr_url_b = f"https://github.com/{owner}/{repo_name}/pull/{uuid.uuid4().int % 10_000}"
    pid_a = await _seed_pr_opened_proposal_under_cluster(
        cluster_id=wired_webhook_env["cluster_id"],
        template_id=wired_webhook_env["template_id"],
        pr_url=pr_url_a,
    )
    pid_b = await _seed_pr_opened_proposal_under_cluster(
        cluster_id=wired_webhook_env["cluster_id"],
        template_id=wired_webhook_env["template_id"],
        pr_url=pr_url_b,
    )

    # Fire both webhooks in parallel. P_B has the strictly-newer timestamp.
    resp_a, resp_b = await asyncio.gather(
        _send_merge_webhook(
            async_client,
            pr_url=pr_url_a,
            owner=owner,
            repo_name=repo_name,
            merged_at_iso="2026-05-22T10:00:00+00:00",
            delivery_id="ac7-A-parallel",
        ),
        _send_merge_webhook(
            async_client,
            pr_url=pr_url_b,
            owner=owner,
            repo_name=repo_name,
            merged_at_iso="2026-05-22T14:30:00+00:00",
            delivery_id="ac7-B-parallel",
        ),
    )
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200

    factory = get_session_factory()
    async with factory() as db:
        prop_a = await repo.get_proposal(db, pid_a)
        prop_b = await repo.get_proposal(db, pid_b)
        assert prop_a is not None and prop_a.status == "pr_merged"
        assert prop_b is not None and prop_b.status == "pr_merged"
        cr = await repo.get_config_repo(db, wired_webhook_env["config_repo_id"])
        assert cr is not None
        # Newer timestamp wins regardless of webhook delivery order.
        assert cr.last_merged_proposal_id == pid_b


# --------------------------------------------------------------------------
# AC-15: hard-delete of pointer-target via test endpoint reverts FK to NULL
# --------------------------------------------------------------------------


async def test_ac15_proposal_hard_delete_reverts_pointer_to_null(
    async_client: httpx.AsyncClient,
    wired_webhook_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Ensure the test-only endpoint is callable (it is gated on
    # Settings.environment == "development"; the test env should be dev).
    monkeypatch.setenv("ENVIRONMENT", "development")

    owner = wired_webhook_env["owner"]
    repo_name = wired_webhook_env["repo"]
    pr_url = f"https://github.com/{owner}/{repo_name}/pull/{uuid.uuid4().int % 10_000}"
    pid = await _seed_pr_opened_proposal_under_cluster(
        cluster_id=wired_webhook_env["cluster_id"],
        template_id=wired_webhook_env["template_id"],
        pr_url=pr_url,
    )

    # Merge the proposal so the pointer is set.
    resp = await _send_merge_webhook(
        async_client,
        pr_url=pr_url,
        owner=owner,
        repo_name=repo_name,
        merged_at_iso="2026-05-22T14:30:00+00:00",
        delivery_id="ac15-merge",
    )
    assert resp.status_code == 200

    # Drive the delete via the test-only HTTP endpoint per spec AC-15.
    del_resp = await async_client.delete(f"/api/v1/_test/proposals/{pid}")
    assert del_resp.status_code in (200, 204), del_resp.text

    factory = get_session_factory()
    async with factory() as db:
        cr = await repo.get_config_repo(db, wired_webhook_env["config_repo_id"])
        assert cr is not None
        # ON DELETE SET NULL reverts the pointer.
        assert cr.last_merged_proposal_id is None
