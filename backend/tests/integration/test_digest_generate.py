"""AC-1 happy-path test for ``generate_digest`` (Story 2.1).

Seeds a completed study with a pending proposal; mocks OpenAI; runs the
worker; asserts the digest row exists with the deterministic
recommended_config, the pending proposal is UPDATED in place (id
unchanged, status still 'pending', config_diff + metric_delta
populated), and no second proposal row is created.
"""

from __future__ import annotations

from typing import Any

import optuna
import optuna.importance
import pytest
from redis.asyncio import Redis

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.models import Proposal
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable
from backend.tests.integration._digest_helpers import (
    make_openai_response,
    patch_async_openai,
    seed_completed_study,
    stub_capability,
)
from backend.workers.digest import generate_digest


class _RecordingLogger:
    """Tiny stub that records `.warning()` / `.error()` calls.

    Avoids `structlog.testing.capture_logs()` which can't intercept loggers
    that were cached under the project's `configure_logging` (uses
    `cache_logger_on_first_use=True`). Monkeypatching the module-level
    `logger` attribute is reliable regardless of cache state.

    Tracked for repo-wide factoring as
    `infra_structlog_test_level_helper/idea.md`.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def warning(self, event: str, **kwargs: Any) -> None:
        self.calls.append(("warning", event, dict(kwargs)))

    def error(self, event: str, **kwargs: Any) -> None:
        self.calls.append(("error", event, dict(kwargs)))

    def info(self, event: str, **kwargs: Any) -> None:
        self.calls.append(("info", event, dict(kwargs)))

    def find(self, *, level: str, event_type: str) -> list[dict[str, Any]]:
        return [
            kw
            for lvl, _evt, kw in self.calls
            if lvl == level and kw.get("event_type") == event_type
        ]


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def test_happy_path_updates_pending_proposal(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-1: digest row created; pending proposal UPDATED in place."""
    monkeypatch.setattr(
        get_settings(), "_openai_api_key" if False else "openai_api_key", "sk-test", raising=False
    )
    # Pydantic-settings cached_property: set the underlying via __dict__.
    settings = get_settings()
    settings.__dict__["openai_api_key"] = "sk-test"

    settings_redis_url = settings.redis_url
    redis_client = Redis.from_url(settings_redis_url, decode_responses=False)
    try:
        await stub_capability(redis_client)
    finally:
        await redis_client.aclose()

    seeded = await seed_completed_study()
    create_mock = patch_async_openai(monkeypatch, make_openai_response())

    await generate_digest({}, seeded["study_id"])

    factory = get_session_factory()
    async with factory() as db:
        digest = await repo.get_digest_for_study(db, seeded["study_id"])
        assert digest is not None
        assert digest.narrative.startswith("Test digest narrative")
        # Deterministic recommendation: best-trial params filtered to declared.
        assert digest.recommended_config == {"field_boosts.title": 4.7, "tie_breaker": 0.34}
        assert digest.parameter_importance is not None
        assert len(digest.suggested_followups) >= 1
        assert digest.generated_by.startswith("openai:")

        # Pending proposal UPDATED in place — id unchanged, status still pending.
        proposal = await repo.get_proposal(db, seeded["proposal_id"])
        assert proposal is not None
        assert proposal.id == seeded["proposal_id"]
        assert proposal.status == "pending"
        assert proposal.config_diff == {
            "field_boosts.title": {"from": 3.0, "to": 4.7},  # midpoint of 1..5 = 3.0
            "tie_breaker": {"from": 0.5, "to": 0.34},  # midpoint of 0..1 = 0.5
        }
        assert proposal.metric_delta is not None
        assert proposal.metric_delta["ndcg@10"]["achieved"] == 0.762
        assert proposal.metric_delta["ndcg@10"]["baseline"] == 0.612

        # No second proposal row created.
        from sqlalchemy import func, select

        n = (
            await db.execute(
                select(func.count(Proposal.id)).where(Proposal.study_id == seeded["study_id"])
            )
        ).scalar_one()
        assert n == 1

    create_mock.assert_called_once()


async def test_unexpected_importance_exception_surfaces_as_error_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The canonical PR #92 regression guard.

    ``optuna.importance.get_param_importances`` raises an ``ImportError``
    (simulating the scikit-learn-missing regression from PR #92). The digest
    worker MUST:

    1. Still produce a digest (soft-fail per
       ``chore_digest_worker_narrow_except`` fork #2 lock — MVP1 has no
       PagerDuty, so we don't hard-fail user-facing flow).
    2. Persist ``parameter_importance == {}`` (empty fallback unchanged).
    3. Emit the new ``digest_importance_failed_unexpected`` event_type at
       ERROR level (NOT WARN; ERROR is what observability alarms on).

    Without this routing, the same regression would silently ship empty
    importance maps for days again — exactly the PR #92 incident pattern.
    """
    settings = get_settings()
    settings.__dict__["openai_api_key"] = "sk-test"

    redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    try:
        await stub_capability(redis_client)
    finally:
        await redis_client.aclose()

    seeded = await seed_completed_study()
    patch_async_openai(monkeypatch, make_openai_response())

    # Simulate the PR #92 regression: get_param_importances raises ImportError.
    monkeypatch.setattr(
        optuna.importance,
        "get_param_importances",
        lambda _study: (_ for _ in ()).throw(ImportError("No module named 'sklearn'")),
    )

    # Capture digest-worker log calls by replacing the module-level logger
    # with a recording stub. Bypasses structlog's cache_logger_on_first_use
    # issue that affects capture_logs() in CI (see _RecordingLogger above).
    rec = _RecordingLogger()
    monkeypatch.setattr("backend.workers.digest.logger", rec)
    await generate_digest({}, seeded["study_id"])

    # 1. Digest was created (soft-fail behaviour preserved).
    factory = get_session_factory()
    async with factory() as db:
        digest = await repo.get_digest_for_study(db, seeded["study_id"])
        assert digest is not None
        # 2. Empty importance map (the fallback both paths return).
        assert digest.parameter_importance == {}

    # 3. ERROR-level event_type fired exactly once.
    error_calls = rec.find(level="error", event_type="digest_importance_failed_unexpected")
    assert len(error_calls) == 1
    assert error_calls[0]["error_type"] == "ImportError"
    assert error_calls[0]["study_id"] == seeded["study_id"]

    # 4. The benign WARN-level event_type did NOT fire on this unexpected path.
    assert not rec.find(level="warning", event_type="digest_importance_failed")
