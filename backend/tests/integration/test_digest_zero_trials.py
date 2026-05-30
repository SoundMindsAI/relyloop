# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""AC-2 zero-trials test for ``generate_digest`` (Story 2.1).

Seeds a completed study with ``best_metric=None``; runs the worker;
asserts the failure-narrative digest is persisted, the pending proposal
is DELETED, no OpenAI call is made.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.tests.conftest import postgres_reachable
from backend.tests.integration._digest_helpers import seed_completed_study
from backend.workers.digest import generate_digest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not postgres_reachable(),
        reason="Postgres not reachable — see docs/03_runbooks/local-dev.md",
    ),
]


async def test_zero_trials_writes_failure_narrative_and_deletes_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-2: best_metric IS NULL → placeholder digest + DELETE pending proposal."""
    seeded = await seed_completed_study(best_metric=None, baseline_metric=None)

    # Patch AsyncOpenAI to fail loudly if invoked — zero-trials must NOT call OpenAI.
    create_mock = AsyncMock(side_effect=AssertionError("OpenAI must not be called"))

    class _StubChat:
        completions = type("_C", (), {"create": create_mock})()

    class _StubClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        chat = _StubChat()

        async def close(self) -> None:
            pass

    monkeypatch.setattr("backend.workers.digest.AsyncOpenAI", _StubClient)

    await generate_digest({}, seeded["study_id"])

    factory = get_session_factory()
    async with factory() as db:
        digest = await repo.get_digest_for_study(db, seeded["study_id"])
        assert digest is not None
        assert digest.narrative.startswith("No successful trials")
        assert digest.parameter_importance == {}
        assert digest.recommended_config == {}
        assert digest.suggested_followups == []
        assert digest.generated_by == "local:zero_trials"

        # Pending proposal DELETED.
        proposal = await repo.get_proposal(db, seeded["proposal_id"])
        assert proposal is None

    create_mock.assert_not_called()
