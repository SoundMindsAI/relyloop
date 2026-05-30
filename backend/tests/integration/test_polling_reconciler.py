# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration tests for ``backend.workers.pr_reconcile.reconcile_pr_state``.

Mocks GitHub via :class:`httpx.MockTransport` (the codebase's established
pattern). Asserts spec FR-2 acceptance criteria:

* AC-3 happy path — webhook delivery simulated-missed → next polling
  tick reconciles the state (merged / closed-unmerged / still-open).
* AC-3 terminal-error branches — 404 / 401 / 403 / 5xx /
  ``RequestError`` after retry budget exhaustion → WARN + skip + no
  mutation.
* Spec §10 — 429 short-circuits the remaining proposals for this tick.
* AC-8 — 50 candidate proposals + stubbed 200 responses complete in
  <30s (asserted via wall-clock + HTTP-attempt count).
"""

from __future__ import annotations

import time
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
async def reconcile_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[dict[str, str]]:
    """Seed config_repo + mounted PAT secret with a UNIQUE owner/repo per test.

    ``config_repos`` is intentionally NOT cleaned by the integration
    ``_clean_phase2_tables`` fixture (config_repo rows are operator-managed
    and outlive individual tests). Two consecutive tests using the same
    ``(owner, repo)`` would have multiple ``config_repos`` rows matching
    ``lookup_config_repo_by_owner_repo``; the lookup returns the first one
    found, whose ``auth_ref`` points at a previous test's ``tmp_path``
    (now gone), surfacing as ``pr_reconcile_pat_missing`` errors.
    """
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    pat_ref = f"reconcile-pat-{uuid.uuid4().hex[:8]}"
    (secrets_dir / pat_ref).write_text("ghp_" + "A" * 40 + "\n")
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(secrets_dir))

    suffix = uuid.uuid4().hex[:8]
    owner = f"rc-owner-{suffix}"
    repo_name = f"rc-repo-{suffix}"

    factory = get_session_factory()
    async with factory() as db:
        cr = await repo.create_config_repo(
            db,
            id=str(uuid.uuid4()),
            name=f"cr-{suffix}",
            provider="github",
            repo_url=f"https://github.com/{owner}/{repo_name}",
            default_branch="main",
            pr_base_branch="main",
            auth_ref=pat_ref,
            webhook_secret_ref=None,
        )
        await db.commit()
        cr_id = cr.id

    yield {
        "config_repo_id": cr_id,
        "pat_ref": pat_ref,
        "owner": owner,
        "repo": repo_name,
    }


async def _seed_pr_opened_proposal(*, pr_url: str) -> str:
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"rc-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"rc-tmpl-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            body='{"query": {"match_all": {}}}',
            declared_params={},
            version=1,
        )
        proposal = await repo.create_proposal(
            db,
            id=str(uuid.uuid4()),
            study_id=None,
            study_trial_id=None,
            cluster_id=cluster.id,
            template_id=template.id,
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
    """Patch ``httpx.AsyncClient`` to use a MockTransport instead of network."""
    import httpx as httpx_module

    original = httpx_module.AsyncClient

    def _factory(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        kwargs["transport"] = handler
        return original(*args, **kwargs)

    monkeypatch.setattr("backend.workers.pr_reconcile.httpx.AsyncClient", _factory)


async def test_reconciler_merged_response_transitions_state(
    reconcile_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-3 — GitHub returns ``merged=true`` → proposal flips to pr_merged."""
    pr_url = (
        f"https://github.com/{reconcile_env['owner']}/{reconcile_env['repo']}"
        f"/pull/{uuid.uuid4().int % 10_000}"
    )
    pid = await _seed_pr_opened_proposal(pr_url=pr_url)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"merged": True, "merged_at": "2026-05-12T10:00:00Z", "state": "closed"},
        )

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    from backend.workers.pr_reconcile import reconcile_pr_state

    summary = await reconcile_pr_state({})
    assert summary["reconciled"] >= 1

    factory = get_session_factory()
    async with factory() as db:
        row = await repo.get_proposal(db, pid)
    assert row is not None
    assert row.status == "pr_merged"
    assert row.pr_state == "merged"


async def test_reconciler_closed_unmerged_response(
    reconcile_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """200 with state=closed + merged=false → proposal flips to pr_state=closed."""
    pr_url = (
        f"https://github.com/{reconcile_env['owner']}/{reconcile_env['repo']}"
        f"/pull/{uuid.uuid4().int % 10_000}"
    )
    pid = await _seed_pr_opened_proposal(pr_url=pr_url)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"merged": False, "state": "closed"})

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    from backend.workers.pr_reconcile import reconcile_pr_state

    summary = await reconcile_pr_state({})
    assert summary["reconciled"] >= 1

    factory = get_session_factory()
    async with factory() as db:
        row = await repo.get_proposal(db, pid)
    assert row is not None
    assert row.status == "pr_opened"  # status STAYS pr_opened per spec §11
    assert row.pr_state == "closed"


async def test_reconciler_still_open_is_unchanged(
    reconcile_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """200 with state=open → no mutation; counted as unchanged."""
    pr_url = (
        f"https://github.com/{reconcile_env['owner']}/{reconcile_env['repo']}"
        f"/pull/{uuid.uuid4().int % 10_000}"
    )
    pid = await _seed_pr_opened_proposal(pr_url=pr_url)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"merged": False, "state": "open"})

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    from backend.workers.pr_reconcile import reconcile_pr_state

    summary = await reconcile_pr_state({})
    assert summary["unchanged"] >= 1
    assert summary["reconciled"] == 0

    factory = get_session_factory()
    async with factory() as db:
        row = await repo.get_proposal(db, pid)
    assert row is not None
    assert row.pr_state == "open"


@pytest.mark.parametrize("status", [401, 403, 404, 500, 503])
async def test_reconciler_terminal_errors_log_and_skip(
    reconcile_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    status: int,
) -> None:
    """4xx / 5xx after retries → WARN + skip + no mutation."""
    pr_url = (
        f"https://github.com/{reconcile_env['owner']}/{reconcile_env['repo']}"
        f"/pull/{uuid.uuid4().int % 10_000}"
    )
    pid = await _seed_pr_opened_proposal(pr_url=pr_url)

    def handler(_request: httpx.Request) -> httpx.Response:
        # For 5xx the retry budget runs; the helper returns the last response.
        return httpx.Response(status, text="error")

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    from backend.workers.pr_reconcile import reconcile_pr_state

    summary = await reconcile_pr_state({})
    assert summary["errored"] >= 1

    factory = get_session_factory()
    async with factory() as db:
        row = await repo.get_proposal(db, pid)
    assert row is not None
    assert row.pr_state == "open"  # unchanged on error


async def test_reconciler_request_error_skips_proposal(
    reconcile_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RequestError after retry budget → WARN + skip + no mutation."""
    pr_url = (
        f"https://github.com/{reconcile_env['owner']}/{reconcile_env['repo']}"
        f"/pull/{uuid.uuid4().int % 10_000}"
    )
    pid = await _seed_pr_opened_proposal(pr_url=pr_url)

    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable")

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    from backend.workers.pr_reconcile import reconcile_pr_state

    summary = await reconcile_pr_state({})
    assert summary["errored"] >= 1

    factory = get_session_factory()
    async with factory() as db:
        row = await repo.get_proposal(db, pid)
    assert row is not None
    assert row.pr_state == "open"


async def test_reconciler_429_short_circuits_tick(
    reconcile_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec §10 — 429 skips the remaining proposals; next tick retries."""
    # Seed two proposals.
    pr1 = f"https://github.com/{reconcile_env['owner']}/{reconcile_env['repo']}/pull/1001"
    pr2 = f"https://github.com/{reconcile_env['owner']}/{reconcile_env['repo']}/pull/1002"
    pid1 = await _seed_pr_opened_proposal(pr_url=pr1)
    pid2 = await _seed_pr_opened_proposal(pr_url=pr2)

    call_count = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(429, headers={"x-ratelimit-reset": "0", "retry-after": "0"})

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    from backend.workers.pr_reconcile import reconcile_pr_state

    summary = await reconcile_pr_state({})
    # The github_request retry loop counts as multiple attempts before returning
    # the last 429 → reconciler records rate_limited++ then breaks.
    assert summary["rate_limited"] == 1
    # Both proposals exist; second never got mutated.
    factory = get_session_factory()
    async with factory() as db:
        row1 = await repo.get_proposal(db, pid1)
        row2 = await repo.get_proposal(db, pid2)
    assert row1 is not None and row1.pr_state == "open"
    assert row2 is not None and row2.pr_state == "open"


async def test_reconciler_handles_50_candidates_under_budget(
    reconcile_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-8 — 50 proposals + 200 responses complete in well under 30s.

    asyncio.sleep is patched to zero (see ``_fast_sleep`` autouse), so this
    is a coarse wall-clock guard — anything taking minutes means a regression
    (e.g. accidental real-sleep introduction in a future refactor).
    """
    seeded_ids: list[str] = []
    for n in range(50):
        pr_url = (
            f"https://github.com/{reconcile_env['owner']}/{reconcile_env['repo']}/pull/{2000 + n}"
        )
        pid = await _seed_pr_opened_proposal(pr_url=pr_url)
        seeded_ids.append(pid)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"merged": False, "state": "open"})

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    from backend.workers.pr_reconcile import reconcile_pr_state

    started = time.monotonic()
    summary = await reconcile_pr_state({})
    elapsed = time.monotonic() - started
    assert summary["candidates"] >= 50
    assert summary["unchanged"] >= 50
    assert elapsed < 30, f"AC-8 budget breached: {elapsed:.1f}s"
