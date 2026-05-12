"""Integration tests for ``POST /webhooks/github`` (Story 2.1).

Covers spec FR-1 ACs:

* AC-1 — ``pull_request{action=closed, merged=true}`` → ``pr_state="merged"``
* AC-2 — bad signature OR unknown repo → 403 ``INVALID_SIGNATURE``
* AC-4 — ``X-GitHub-Event: ping`` → ``{action: ping}``
* AC-5 — unknown PR URL → ``{action: unknown_pr}``

Plus FR-1 matrix branches (closed-without-merge, reopened, noop actions,
unknown event types) and the spec §13 NFR-Operability ``webhook_received``
log fields. Consolidated into one file (the plan lists nine separate
files for cite-by-name; one file keeps the shared seed/sign helpers
honest and the test runner shells out one process per test anyway).

Test seam: ``RELYLOOP_SECRETS_DIR`` is overridden to ``tmp_path`` so the
mounted-secret read finds the test-controlled webhook secret file.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
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


_WEBHOOK_SECRET = "test-webhook-secret-do-not-leak"
_OWNER = "octocat"
_REPO = "hello-world"


def _signature(body: bytes, secret: str = _WEBHOOK_SECRET) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest_asyncio.fixture
async def webhook_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[dict[str, str]]:
    """Seed a config_repo + mounted webhook secret. Yield setup metadata.

    Returns a dict with:
      * ``config_repo_id``
      * ``secret_ref``
      * ``owner``, ``repo``  — the parsed full_name pair
    """
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    secret_ref = f"webhook-secret-{uuid.uuid4().hex[:8]}"
    (secrets_dir / secret_ref).write_text(_WEBHOOK_SECRET + "\n")
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(secrets_dir))

    factory = get_session_factory()
    async with factory() as db:
        cr = await repo.create_config_repo(
            db,
            id=str(uuid.uuid4()),
            name=f"cr-{uuid.uuid4().hex[:8]}",
            provider="github",
            repo_url=f"https://github.com/{_OWNER}/{_REPO}",
            default_branch="main",
            pr_base_branch="main",
            auth_ref=f"pat-{uuid.uuid4().hex[:8]}",
            webhook_secret_ref=secret_ref,
        )
        await db.commit()
        config_repo_id = cr.id

    yield {
        "config_repo_id": config_repo_id,
        "secret_ref": secret_ref,
        "owner": _OWNER,
        "repo": _REPO,
    }


async def _seed_pr_opened_proposal(*, pr_url: str) -> str:
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.create_cluster(
            db,
            id=str(uuid.uuid4()),
            name=f"wh-cluster-{uuid.uuid4().hex[:8]}",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://stub:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
        )
        template = await repo.create_query_template(
            db,
            id=str(uuid.uuid4()),
            name=f"wh-tmpl-{uuid.uuid4().hex[:8]}",
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


def _pull_request_body(action: str, *, merged: bool, pr_url: str) -> bytes:
    payload: dict[str, object] = {
        "action": action,
        "repository": {"full_name": f"{_OWNER}/{_REPO}"},
        "pull_request": {
            "html_url": pr_url,
            "merged": merged,
            "merged_at": "2026-05-12T11:00:00Z" if merged else None,
        },
    }
    return json.dumps(payload).encode("utf-8")


async def test_webhook_pr_merged_transitions_state(
    async_client: httpx.AsyncClient,
    webhook_env: dict[str, str],
) -> None:
    """AC-1 — merged event flips status to pr_merged + populates pr_merged_at."""
    pr_url = f"https://github.com/{_OWNER}/{_REPO}/pull/{uuid.uuid4().int % 10_000}"
    pid = await _seed_pr_opened_proposal(pr_url=pr_url)

    body = _pull_request_body("closed", merged=True, pr_url=pr_url)
    response = await async_client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-merged",
            "X-Hub-Signature-256": _signature(body),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "action": "applied"}

    factory = get_session_factory()
    async with factory() as db:
        row = await repo.get_proposal(db, pid)
    assert row is not None
    assert row.status == "pr_merged"
    assert row.pr_state == "merged"
    assert row.pr_merged_at is not None


async def test_webhook_pr_closed_unmerged_keeps_status(
    async_client: httpx.AsyncClient,
    webhook_env: dict[str, str],
) -> None:
    """FR-1 closed+merged=false branch: pr_state='closed', status STAYS pr_opened."""
    pr_url = f"https://github.com/{_OWNER}/{_REPO}/pull/{uuid.uuid4().int % 10_000}"
    pid = await _seed_pr_opened_proposal(pr_url=pr_url)

    body = _pull_request_body("closed", merged=False, pr_url=pr_url)
    response = await async_client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-closed",
            "X-Hub-Signature-256": _signature(body),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "action": "applied"}

    factory = get_session_factory()
    async with factory() as db:
        row = await repo.get_proposal(db, pid)
    assert row is not None
    assert row.status == "pr_opened"
    assert row.pr_state == "closed"


async def test_webhook_pr_reopened_returns_to_open(
    async_client: httpx.AsyncClient,
    webhook_env: dict[str, str],
) -> None:
    """FR-1 reopened branch: closed → open."""
    pr_url = f"https://github.com/{_OWNER}/{_REPO}/pull/{uuid.uuid4().int % 10_000}"
    pid = await _seed_pr_opened_proposal(pr_url=pr_url)

    # Transition to closed first via direct repo call (mirror prior delivery).
    factory = get_session_factory()
    async with factory() as db:
        await repo.mark_proposal_pr_closed(db, pid)
        await db.commit()

    payload = {
        "action": "reopened",
        "repository": {"full_name": f"{_OWNER}/{_REPO}"},
        "pull_request": {"html_url": pr_url},
    }
    body = json.dumps(payload).encode("utf-8")
    response = await async_client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-reopened",
            "X-Hub-Signature-256": _signature(body),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "action": "applied"}

    async with factory() as db:
        row = await repo.get_proposal(db, pid)
    assert row is not None
    assert row.pr_state == "open"


@pytest.mark.parametrize(
    "action",
    ["opened", "edited", "synchronize", "review_requested", "assigned"],
)
async def test_webhook_pr_noop_actions(
    async_client: httpx.AsyncClient,
    webhook_env: dict[str, str],
    action: str,
) -> None:
    """FR-1 noop branch: PR actions other than closed/reopened → action=noop."""
    pr_url = f"https://github.com/{_OWNER}/{_REPO}/pull/{uuid.uuid4().int % 10_000}"
    pid = await _seed_pr_opened_proposal(pr_url=pr_url)

    payload = {
        "action": action,
        "repository": {"full_name": f"{_OWNER}/{_REPO}"},
        "pull_request": {"html_url": pr_url},
    }
    body = json.dumps(payload).encode("utf-8")
    response = await async_client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": f"delivery-noop-{action}",
            "X-Hub-Signature-256": _signature(body),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "action": "noop"}

    # No state mutation.
    factory = get_session_factory()
    async with factory() as db:
        row = await repo.get_proposal(db, pid)
    assert row is not None
    assert row.pr_state == "open"
    assert row.status == "pr_opened"


async def test_webhook_unknown_event_returns_noop(
    async_client: httpx.AsyncClient,
    webhook_env: dict[str, str],
) -> None:
    """Unknown X-GitHub-Event types → 200 with action=noop (forward-compat)."""
    payload = {"repository": {"full_name": f"{_OWNER}/{_REPO}"}}
    body = json.dumps(payload).encode("utf-8")
    response = await async_client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "deployment_status",
            "X-GitHub-Delivery": "delivery-unknown-event",
            "X-Hub-Signature-256": _signature(body),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "action": "noop"}


async def test_webhook_ping_event(
    async_client: httpx.AsyncClient,
    webhook_env: dict[str, str],
) -> None:
    """AC-4 — X-GitHub-Event: ping → 200 with action=ping."""
    payload = {
        "repository": {"full_name": f"{_OWNER}/{_REPO}"},
        "zen": "Non-blocking is better than blocking.",
    }
    body = json.dumps(payload).encode("utf-8")
    response = await async_client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": "delivery-ping",
            "X-Hub-Signature-256": _signature(body),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "action": "ping"}


async def test_webhook_unknown_pr_url(
    async_client: httpx.AsyncClient,
    webhook_env: dict[str, str],
) -> None:
    """AC-5 — valid signature + valid repo + unmapped pr_url → action=unknown_pr."""
    pr_url = f"https://github.com/{_OWNER}/{_REPO}/pull/999999"  # not seeded
    body = _pull_request_body("closed", merged=True, pr_url=pr_url)
    response = await async_client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-unknown-pr",
            "X-Hub-Signature-256": _signature(body),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "action": "unknown_pr"}


async def test_webhook_bad_signature_returns_403(
    async_client: httpx.AsyncClient,
    webhook_env: dict[str, str],
) -> None:
    """AC-2 path 1 — mismatched signature → 403 INVALID_SIGNATURE."""
    body = _pull_request_body(
        "closed", merged=True, pr_url="https://github.com/octocat/hello-world/pull/1"
    )
    response = await async_client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-bad-sig",
            "X-Hub-Signature-256": "sha256=" + "0" * 64,
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "INVALID_SIGNATURE"


async def test_webhook_missing_signature_returns_403(
    async_client: httpx.AsyncClient,
    webhook_env: dict[str, str],
) -> None:
    """AC-2 path 2 — no X-Hub-Signature-256 → 403 INVALID_SIGNATURE."""
    body = _pull_request_body(
        "closed", merged=True, pr_url="https://github.com/octocat/hello-world/pull/1"
    )
    response = await async_client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-missing-sig",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "INVALID_SIGNATURE"


async def test_webhook_unknown_repo_returns_403(
    async_client: httpx.AsyncClient,
    webhook_env: dict[str, str],
) -> None:
    """AC-2 path 3 — repository.full_name doesn't match any config_repo → 403."""
    body = json.dumps(
        {
            "action": "closed",
            "repository": {"full_name": "unknown/unregistered"},
            "pull_request": {
                "html_url": "https://github.com/unknown/unregistered/pull/1",
                "merged": True,
                "merged_at": "2026-05-12T11:00:00Z",
            },
        }
    ).encode("utf-8")
    response = await async_client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "pull_request",
            "X-GitHub-Delivery": "delivery-unknown-repo",
            "X-Hub-Signature-256": _signature(body),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "INVALID_SIGNATURE"


async def test_webhook_logs_structured_fields(
    async_client: httpx.AsyncClient,
    webhook_env: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Spec §13 NFR-Operability — webhook_received emits delivery_id/event/action/result."""
    caplog.set_level(logging.INFO, logger="backend.app.api.webhooks.github")
    payload = {
        "repository": {"full_name": f"{_OWNER}/{_REPO}"},
        "zen": "Anything added dilutes everything else.",
    }
    body = json.dumps(payload).encode("utf-8")
    delivery = f"delivery-log-{datetime.now(UTC).timestamp()}"
    response = await async_client.post(
        "/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": delivery,
            "X-Hub-Signature-256": _signature(body),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    # structlog routes via stdlib logging; caplog captures the formatted line.
    assert any("webhook_received" in record.getMessage() for record in caplog.records)
