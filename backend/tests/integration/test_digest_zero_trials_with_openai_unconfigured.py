"""Cycle-2 F5 test: zero-trials path fires regardless of OpenAI configuration.

Pre-cycle-2-F5 design gated zero-trials behind OpenAI key/capability/budget
checks; that meant a study with ``best_metric IS NULL`` would NEVER get its
failure digest if the operator hadn't configured OpenAI yet. Spec AC-2
explicitly requires the failure digest is persisted regardless.

This test sets ``best_metric=None`` AND ``openai_api_key=None`` and asserts
the failure digest IS still persisted + the pending proposal is DELETED.
"""

from __future__ import annotations

import pytest

from backend.app.core.settings import get_settings
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


async def test_zero_trials_writes_failure_digest_even_when_no_openai_key() -> None:
    """Cycle-2 F5: AC-2 path fires regardless of OpenAI configuration."""
    settings = get_settings()
    settings.__dict__["openai_api_key"] = None

    seeded = await seed_completed_study(best_metric=None, baseline_metric=None)

    await generate_digest({}, seeded["study_id"])

    factory = get_session_factory()
    async with factory() as db:
        digest = await repo.get_digest_for_study(db, seeded["study_id"])
        assert digest is not None
        assert digest.narrative.startswith("No successful trials")
        assert digest.generated_by == "local:zero_trials"
        # Pending proposal DELETED.
        proposal = await repo.get_proposal(db, seeded["proposal_id"])
        assert proposal is None
