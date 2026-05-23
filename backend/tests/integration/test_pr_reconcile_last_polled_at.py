"""PR reconciler integration tests for chore_reconciler_terminal_closed_no_poll.

Six scenarios mapping to the FR-2 / FR-3 / FR-4 acceptance criteria:

* **AC-3a** — Steady-state case (b): a (pr_opened, closed) candidate with
  GitHub still reporting closed gets `last_polled_at` stamped; the close
  helper is NOT called (FR-2 branch-on-selection-pr_state rule).
* **AC-3b** — First-observation case (b): a (pr_opened, open) candidate
  that GitHub reports as closed gets transitioned via
  `mark_proposal_pr_closed`; `last_polled_at` stays NULL on this tick.
* **AC-4** — Case-(a) recovery: a (pr_opened, closed, NULL) candidate that
  GitHub reports merged transitions to (pr_merged, merged); the stamp
  helper is NOT touched.
* **AC-5** — Still-open: a (pr_opened, open) candidate that GitHub still
  reports open leaves the row unchanged (no stamp).
* **AC-10** — Two-tick cadence: a stamped case-(b) row is excluded from
  the candidate set on the next tick, so GitHub is called exactly once
  across two ticks.
* **AC-9-race** — Webhook reopens the row between candidate selection and
  the worker's branch: the stamp helper's `WHERE pr_state='closed'` guard
  returns None; the reopen is preserved; `last_polled_at` stays NULL.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import update

from backend.app.db import repo
from backend.app.db.models import Proposal
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
async def wired_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[dict[str, str]]:
    """Seed config_repo + cluster wired to it + a PAT secret. Unique per test."""
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    pat_ref = f"lp-pat-{uuid.uuid4().hex[:8]}"
    (secrets_dir / pat_ref).write_text("ghp_" + "A" * 40 + "\n")
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(secrets_dir))

    suffix = uuid.uuid4().hex[:8]
    owner = f"lp-owner-{suffix}"
    repo_name = f"lp-repo-{suffix}"

    factory = get_session_factory()
    async with factory() as db:
        cr = await repo.create_config_repo(
            db,
            id=str(uuid.uuid4()),
            name=f"cr-lp-{suffix}",
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
            name=f"cluster-lp-{suffix}",
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
            name=f"tmpl-lp-{suffix}",
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


async def _seed_pr_opened_under_cluster(
    *,
    cluster_id: str,
    template_id: str,
    pr_url: str,
    pr_state: str = "open",
    last_polled_at: datetime | None = None,
) -> str:
    """Seed a proposal as (pr_opened, <pr_state>) with optional last_polled_at."""
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

    if pr_state != "open" or last_polled_at is not None:
        async with factory() as db:
            stmt = (
                update(Proposal)
                .where(Proposal.id == pid)
                .values(pr_state=pr_state, last_polled_at=last_polled_at)
            )
            await db.execute(stmt)
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
# AC-3a — steady-state case (b): selected as closed → stamp, no close call
# --------------------------------------------------------------------------


async def test_steady_state_case_b_stamps_without_calling_close_helper(
    wired_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-3a: candidate selected as pr_state='closed' gets last_polled_at stamped.

    Verifies the FR-2 branch-on-selection-pr_state rule:
    * mark_proposal_pr_closed is NOT called (would race against webhook reopens).
    * stamp_proposal_last_polled_at writes the timestamp.
    """
    pr_url = (
        f"https://github.com/{wired_env['owner']}/{wired_env['repo']}"
        f"/pull/{uuid.uuid4().int % 10_000}"
    )
    pid = await _seed_pr_opened_under_cluster(
        cluster_id=wired_env["cluster_id"],
        template_id=wired_env["template_id"],
        pr_url=pr_url,
        pr_state="closed",
        last_polled_at=None,
    )

    # Spy on mark_proposal_pr_closed to detect the wrong-branch path.
    close_call_count = 0
    original_close = repo.mark_proposal_pr_closed

    async def _spy_mark_pr_closed(db, proposal_id):  # noqa: ANN001, ANN202
        nonlocal close_call_count
        close_call_count += 1
        return await original_close(db, proposal_id)

    monkeypatch.setattr(
        "backend.workers.pr_reconcile.repo.mark_proposal_pr_closed", _spy_mark_pr_closed
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"merged": False, "state": "closed", "merged_at": None})

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    before = datetime.now(UTC)
    from backend.workers.pr_reconcile import reconcile_pr_state

    summary = await reconcile_pr_state({})

    assert close_call_count == 0, (
        "mark_proposal_pr_closed must NOT be called on selected-closed branch"
    )
    assert summary["unchanged"] >= 1

    factory = get_session_factory()
    async with factory() as db:
        prop = await repo.get_proposal(db, pid)
    assert prop is not None
    assert prop.status == "pr_opened"
    assert prop.pr_state == "closed"
    assert prop.last_polled_at is not None
    assert prop.last_polled_at >= before


# --------------------------------------------------------------------------
# AC-3b — first observation: selected as open, GitHub now closed → close transition
# --------------------------------------------------------------------------


async def test_first_observation_case_b_runs_close_transition_no_stamp(
    wired_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-3b: candidate selected as pr_state='open' that GitHub reports closed → close transition.

    The reconciler's legacy path runs: mark_proposal_pr_closed transitions
    (pr_opened, open) → (pr_opened, closed). last_polled_at stays NULL on
    THIS tick — the next tick will select the row as closed and stamp it
    via the AC-3a path.
    """
    pr_url = (
        f"https://github.com/{wired_env['owner']}/{wired_env['repo']}"
        f"/pull/{uuid.uuid4().int % 10_000}"
    )
    pid = await _seed_pr_opened_under_cluster(
        cluster_id=wired_env["cluster_id"],
        template_id=wired_env["template_id"],
        pr_url=pr_url,
        pr_state="open",
        last_polled_at=None,
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"merged": False, "state": "closed", "merged_at": None})

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    from backend.workers.pr_reconcile import reconcile_pr_state

    summary = await reconcile_pr_state({})
    assert summary["reconciled"] >= 1

    factory = get_session_factory()
    async with factory() as db:
        prop = await repo.get_proposal(db, pid)
    assert prop is not None
    assert prop.pr_state == "closed"
    assert prop.last_polled_at is None


# --------------------------------------------------------------------------
# AC-4 — case-(a) recovery: merged=true on closed candidate → recover, no stamp
# --------------------------------------------------------------------------


async def test_case_a_recovery_does_not_stamp_last_polled_at(
    wired_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-4: recovery branch (merged=true, merged_at non-null) leaves last_polled_at NULL."""
    pr_url = (
        f"https://github.com/{wired_env['owner']}/{wired_env['repo']}"
        f"/pull/{uuid.uuid4().int % 10_000}"
    )
    pid = await _seed_pr_opened_under_cluster(
        cluster_id=wired_env["cluster_id"],
        template_id=wired_env["template_id"],
        pr_url=pr_url,
        pr_state="closed",
        last_polled_at=None,
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "merged": True,
                "merged_at": "2026-05-23T12:00:00Z",
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
    assert prop.last_polled_at is None, "case-a recovery must not touch last_polled_at"


# --------------------------------------------------------------------------
# AC-5 — still-open poll: nothing changes
# --------------------------------------------------------------------------


async def test_still_open_does_not_stamp_last_polled_at(
    wired_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-5: state='open' branch leaves the row untouched."""
    pr_url = (
        f"https://github.com/{wired_env['owner']}/{wired_env['repo']}"
        f"/pull/{uuid.uuid4().int % 10_000}"
    )
    pid = await _seed_pr_opened_under_cluster(
        cluster_id=wired_env["cluster_id"],
        template_id=wired_env["template_id"],
        pr_url=pr_url,
        pr_state="open",
        last_polled_at=None,
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"merged": False, "state": "open", "merged_at": None})

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    from backend.workers.pr_reconcile import reconcile_pr_state

    summary = await reconcile_pr_state({})
    assert summary["unchanged"] >= 1

    factory = get_session_factory()
    async with factory() as db:
        prop = await repo.get_proposal(db, pid)
    assert prop is not None
    assert prop.pr_state == "open"
    assert prop.last_polled_at is None


# --------------------------------------------------------------------------
# AC-10 — two-tick cadence: 30 min apart, exactly one GitHub call
# --------------------------------------------------------------------------


async def test_two_sequential_ticks_invoke_github_exactly_once(
    wired_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-10: stamped row excluded on tick 2; GitHub called exactly once across both ticks."""
    pr_url = (
        f"https://github.com/{wired_env['owner']}/{wired_env['repo']}"
        f"/pull/{uuid.uuid4().int % 10_000}"
    )
    pid = await _seed_pr_opened_under_cluster(
        cluster_id=wired_env["cluster_id"],
        template_id=wired_env["template_id"],
        pr_url=pr_url,
        pr_state="closed",
        last_polled_at=None,
    )

    call_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"merged": False, "state": "closed", "merged_at": None})

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    from backend.workers.pr_reconcile import reconcile_pr_state

    # Tick 1: row is in candidates (last_polled_at NULL) → 1 GitHub call → stamp.
    await reconcile_pr_state({})
    assert call_count == 1

    # Tick 2: row is excluded by the 24h filter → no additional GitHub call.
    await reconcile_pr_state({})
    assert call_count == 1, "Second tick must skip the row via the 24h exclusion"

    factory = get_session_factory()
    async with factory() as db:
        prop = await repo.get_proposal(db, pid)
    assert prop is not None
    assert prop.last_polled_at is not None


# --------------------------------------------------------------------------
# AC-9-race — webhook reopen between candidate selection and worker branch
# --------------------------------------------------------------------------


async def test_webhook_reopen_mid_tick_does_not_clobber_or_stamp(
    wired_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-9-race: mid-tick webhook reopen → no re-close, no stamp.

    Simulates the race by monkeypatching the reconciler's candidate
    loader (`_list_candidates`) to return an ORM object with the
    *previous* `pr_state='closed'` shape, while the DB row has already
    been flipped to `(pr_opened, open)` by the webhook. The reconciler's
    branch-on-selection rule reads `proposal.pr_state` from the loaded
    ORM object (pr_state='closed'), so it enters the steady-state
    case-(b) branch and calls only `stamp_proposal_last_polled_at`.
    The stamp helper's defensive WHERE pr_state='closed' clause then
    matches zero rows (the DB row is open) and returns None.

    After the tick:
    * mark_proposal_pr_closed was NOT called (selected as closed branch).
    * The DB row remains (pr_opened, open) — the reopen is preserved.
    * last_polled_at stays NULL — stamp returned None benignly.
    """
    pr_url = (
        f"https://github.com/{wired_env['owner']}/{wired_env['repo']}"
        f"/pull/{uuid.uuid4().int % 10_000}"
    )
    # Seed in the "previously closed" shape. Then flip the DB row to open
    # before invoking the reconciler — simulating the webhook reopen that
    # arrives between candidate selection and the worker's branch.
    pid = await _seed_pr_opened_under_cluster(
        cluster_id=wired_env["cluster_id"],
        template_id=wired_env["template_id"],
        pr_url=pr_url,
        pr_state="closed",
        last_polled_at=None,
    )

    # Load the row in its "stale closed" form to seed _list_candidates.
    factory = get_session_factory()
    async with factory() as db:
        stale_candidate = await repo.get_proposal(db, pid)
    assert stale_candidate is not None
    assert stale_candidate.pr_state == "closed"

    # Now flip the DB row to open (the "webhook arrived" event).
    async with factory() as db:
        await repo.mark_proposal_pr_reopened(db, pid)
        await db.commit()

    # Override _list_candidates to return the stale ORM object so the
    # reconciler branches as if the row were still closed.
    async def _stale_candidates():  # noqa: ANN202
        return [stale_candidate]

    monkeypatch.setattr("backend.workers.pr_reconcile._list_candidates", _stale_candidates)

    # Spy on mark_proposal_pr_closed to assert it is NOT called.
    close_call_count = 0
    original_close = repo.mark_proposal_pr_closed

    async def _spy_mark_pr_closed(db, proposal_id):  # noqa: ANN001, ANN202
        nonlocal close_call_count
        close_call_count += 1
        return await original_close(db, proposal_id)

    monkeypatch.setattr(
        "backend.workers.pr_reconcile.repo.mark_proposal_pr_closed", _spy_mark_pr_closed
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"merged": False, "state": "closed", "merged_at": None})

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    from backend.workers.pr_reconcile import reconcile_pr_state

    await reconcile_pr_state({})

    assert close_call_count == 0, "selected-as-closed branch must skip mark_proposal_pr_closed"

    async with factory() as db:
        prop = await repo.get_proposal(db, pid)
    assert prop is not None
    assert prop.pr_state == "open", "reopen must be preserved (stamp helper's WHERE guard)"
    assert prop.last_polled_at is None, "stamp must not fire on open rows"


# --------------------------------------------------------------------------
# Coverage for the FR-2 invariant under reopen-then-reclose-within-24h race
# (already integration-tested in test_proposal_repo_last_polled_at.py; this
# is the worker-side parity test)
# --------------------------------------------------------------------------


async def test_reopen_reclose_within_24h_is_not_re_polled(
    wired_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Worker-level AC-9-reclose: a (pr_opened, closed) row whose stamp is
    1h old does not trigger a GitHub poll even after a reopen+reclose
    sequence — the exclusion is based purely on last_polled_at + pr_state.
    """
    pr_url = (
        f"https://github.com/{wired_env['owner']}/{wired_env['repo']}"
        f"/pull/{uuid.uuid4().int % 10_000}"
    )
    pid = await _seed_pr_opened_under_cluster(
        cluster_id=wired_env["cluster_id"],
        template_id=wired_env["template_id"],
        pr_url=pr_url,
        pr_state="closed",
        last_polled_at=datetime.now(UTC) - timedelta(hours=1),
    )

    # Simulate reopen + reclose via webhook handlers (last_polled_at survives).
    factory = get_session_factory()
    async with factory() as db:
        await repo.mark_proposal_pr_reopened(db, pid)
        await db.commit()
    async with factory() as db:
        await repo.mark_proposal_pr_closed(db, pid)
        await db.commit()

    call_count = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(200, json={"merged": False, "state": "closed", "merged_at": None})

    _install_mock_transport(monkeypatch, httpx.MockTransport(handler))

    from backend.workers.pr_reconcile import reconcile_pr_state

    await reconcile_pr_state({})
    assert call_count == 0, "reopened-then-reclosed-within-24h row must stay excluded"
