"""PR reconciler integration tests for config_repos.last_merged_proposal_id.

feat_config_repo_baseline_tracking Story 1.4 (FR-3a). Two test cases:

* **Happy path** — webhook delivery NEVER fired; reconciler is the first
  observer of the merge. Proposal is still ``(pr_opened, open)``;
  ``mark_proposal_pr_merged`` succeeds; pointer-update fires.

* **Negative documentation test** — the webhook's ``merged_at=null`` fallback
  closed the proposal. Reconciler tick observes ``merged=true`` +
  non-null ``merged_at`` but ``mark_proposal_pr_merged`` returns None
  because ``pr_state='closed'``. Pointer remains NULL. This is the
  documented limitation captured as
  ``bug_pr_reconciler_blocked_by_closed_fallback`` — NOT a regression.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
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


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Patch retry-loop sleeps so RequestError-after-budget paths are fast."""

    async def _instant(_seconds: float) -> None:
        return None

    monkeypatch.setattr("backend.app.git.github_client.asyncio.sleep", _instant)
    yield


@pytest_asyncio.fixture
async def wired_reconcile_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[dict[str, str]]:
    """Seed config_repo + cluster wired to it + a PAT secret. Unique per test."""
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    pat_ref = f"rcptr-pat-{uuid.uuid4().hex[:8]}"
    (secrets_dir / pat_ref).write_text("ghp_" + "A" * 40 + "\n")
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(secrets_dir))

    suffix = uuid.uuid4().hex[:8]
    owner = f"rcptr-owner-{suffix}"
    repo_name = f"rcptr-repo-{suffix}"

    factory = get_session_factory()
    async with factory() as db:
        cr = await repo.create_config_repo(
            db,
            id=str(uuid.uuid4()),
            name=f"cr-rcptr-{suffix}",
            provider="github",
            repo_url=f"https://github.com/{owner}/{repo_name}",
            default_branch="main",
            pr_base_branch="main",
            auth_ref=pat_ref,
            webhook_secret_ref=None,
        )
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"cluster-rcptr-{suffix}",
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
            name=f"tmpl-rcptr-{suffix}",
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


def _install_mock_transport(monkeypatch: pytest.MonkeyPatch, handler: httpx.MockTransport) -> None:
    import httpx as httpx_module

    original = httpx_module.AsyncClient

    def _factory(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        kwargs["transport"] = handler
        return original(*args, **kwargs)

    monkeypatch.setattr("backend.workers.pr_reconcile.httpx.AsyncClient", _factory)


# --------------------------------------------------------------------------
# FR-3a happy path: reconciler observes a missed merge → pointer updates
# --------------------------------------------------------------------------


async def test_reconciler_observes_missed_merge_updates_pointer(
    wired_reconcile_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The webhook never delivered; reconciler picks up the merge and sets the pointer."""
    pr_url = (
        f"https://github.com/{wired_reconcile_env['owner']}/{wired_reconcile_env['repo']}"
        f"/pull/{uuid.uuid4().int % 10_000}"
    )
    pid = await _seed_pr_opened_proposal_under_cluster(
        cluster_id=wired_reconcile_env["cluster_id"],
        template_id=wired_reconcile_env["template_id"],
        pr_url=pr_url,
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "merged": True,
                "merged_at": "2026-05-22T14:30:00Z",
                "state": "closed",
            },
        )

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    from backend.workers.pr_reconcile import reconcile_pr_state

    summary = await reconcile_pr_state({})
    assert summary["reconciled"] >= 1

    factory = get_session_factory()
    async with factory() as db:
        prop = await repo.get_proposal(db, pid)
        assert prop is not None
        assert prop.status == "pr_merged"
        assert prop.pr_state == "merged"
        cr = await repo.get_config_repo(db, wired_reconcile_env["config_repo_id"])
        assert cr is not None
        assert cr.last_merged_proposal_id == pid


# --------------------------------------------------------------------------
# Negative documentation test: pre-existing limitation
# (bug_pr_reconciler_blocked_by_closed_fallback)
# --------------------------------------------------------------------------


async def test_reconciler_does_not_recover_fallback_closed_proposal(
    wired_reconcile_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Document the pre-existing limitation: reconciler cannot recover a proposal
    that the webhook's merged_at=null fallback already moved to (pr_opened, closed).

    mark_proposal_pr_merged requires pr_state='open' and returns None when the
    state is 'closed' — so FR-3a's pointer-update branch does NOT fire here.
    The proposal stays in (pr_opened, closed) forever until an operator
    manually intervenes.

    This test pins the current behavior. Fixing this gap requires changes to
    the reconciler state machine and is captured as a separate bug:
    docs/02_product/planned_features/bug_pr_reconciler_blocked_by_closed_fallback/idea.md.
    """
    pr_url = (
        f"https://github.com/{wired_reconcile_env['owner']}/{wired_reconcile_env['repo']}"
        f"/pull/{uuid.uuid4().int % 10_000}"
    )
    pid = await _seed_pr_opened_proposal_under_cluster(
        cluster_id=wired_reconcile_env["cluster_id"],
        template_id=wired_reconcile_env["template_id"],
        pr_url=pr_url,
    )

    # Simulate the webhook fallback path: move proposal to (pr_opened, closed)
    # without setting pr_merged_at. This is what mark_proposal_pr_closed
    # does in webhook.github.py:188 when GitHub delivers merged=true with
    # merged_at=null.
    factory = get_session_factory()
    async with factory() as db:
        await repo.mark_proposal_pr_closed(db, pid)
        await db.commit()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "merged": True,
                "merged_at": "2026-05-22T14:30:00Z",
                "state": "closed",
            },
        )

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    from backend.workers.pr_reconcile import reconcile_pr_state

    # Run a tick. The proposal IS NOT in the candidate set
    # (list_pr_opened_proposals_for_reconcile filters to
    # pr_state='open'); it's invisible to the reconciler entirely.
    # This makes the bug stronger than originally stated: the proposal
    # can never be recovered without operator action.
    await reconcile_pr_state({})

    async with factory() as db:
        prop = await repo.get_proposal(db, pid)
        assert prop is not None
        # Proposal is stuck — both fields show the fallback state.
        assert prop.status == "pr_opened"
        assert prop.pr_state == "closed"
        # Pointer was NOT set — this is the documented limitation.
        cr = await repo.get_config_repo(db, wired_reconcile_env["config_repo_id"])
        assert cr is not None
        assert cr.last_merged_proposal_id is None
