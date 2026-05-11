"""AC-9 + FR-2b boot-time pending-proposal scan test for ``backend/workers/all.py``.

Three scenarios:
* a study completed with an orchestrator-inserted pending proposal but
  NO digest → on_startup re-enqueues ``generate_digest:{sid}``.
* a study completed with a pending proposal AND an existing digest →
  on_startup does NOT enqueue (the LEFT JOIN excludes it).
* on_startup uses the deterministic ``_job_id`` per cycle-4 C4-F1
  pattern from feat_llm_judgments (asserted by inspecting Arq's
  ``enqueue_job`` call).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable
from backend.tests.integration._digest_helpers import seed_completed_study
from backend.workers.all import on_startup

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


class _StubArqPool:
    """Records enqueue calls so the test can assert on (job_name, args, _job_id)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def enqueue_job(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    async def close(self) -> None:
        pass


async def _run_on_startup(monkeypatch: pytest.MonkeyPatch) -> _StubArqPool:
    """Patch the Arq pool + storage builders so on_startup runs in-process."""
    pool = _StubArqPool()

    async def _stub_create_pool(*args: Any, **kwargs: Any) -> _StubArqPool:
        return pool

    async def _stub_to_thread(func: Any, *args: Any, **kwargs: Any) -> Any:
        return None  # we don't care about Optuna RDBStorage in this test

    monkeypatch.setattr("backend.workers.all.create_pool", _stub_create_pool)
    monkeypatch.setattr("backend.workers.all.asyncio.to_thread", _stub_to_thread)

    ctx: dict[str, Any] = {}
    await on_startup(ctx)
    return pool


async def test_on_startup_enqueues_pending_proposals_lacking_digests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-9: pending proposal + no digest → boot-scan enqueues generate_digest."""
    seeded = await seed_completed_study()  # pending proposal, no digest
    pool = await _run_on_startup(monkeypatch)
    enqueued_for_digest = [
        c for c in pool.calls if c[0] == "generate_digest" and seeded["study_id"] in c[1]
    ]
    assert len(enqueued_for_digest) == 1


async def test_on_startup_skips_proposals_with_existing_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pending proposal + existing digest → boot-scan does NOT enqueue."""
    seeded = await seed_completed_study()
    factory = get_session_factory()
    async with factory() as db:
        await repo.create_digest(
            db,
            id=str(uuid.uuid4()),
            study_id=seeded["study_id"],
            narrative="already digested",
            parameter_importance={},
            recommended_config={},
            suggested_followups=[],
            generated_by="local:test",
        )
        await db.commit()
    pool = await _run_on_startup(monkeypatch)
    enqueued_for_digest = [
        c for c in pool.calls if c[0] == "generate_digest" and seeded["study_id"] in c[1]
    ]
    assert enqueued_for_digest == []


async def test_on_startup_uses_deterministic_job_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """FR-2b dedup contract: enqueue uses _job_id=f'generate_digest:{study_id}'."""
    seeded = await seed_completed_study()
    pool = await _run_on_startup(monkeypatch)
    digest_calls = [c for c in pool.calls if c[0] == "generate_digest"]
    assert len(digest_calls) == 1
    _, _, kwargs = digest_calls[0]
    assert kwargs.get("_job_id") == f"generate_digest:{seeded['study_id']}"
