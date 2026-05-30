# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""AC-10 test: ``OPENAI_NOT_CONFIGURED`` defers without writing.

Seeds a completed study; clears ``Settings.openai_api_key``; runs the
worker; asserts NO digest row, NO mutation of the pending proposal.
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


async def test_no_key_does_not_write_digest_or_mutate_proposal() -> None:
    """AC-10: OPENAI_NOT_CONFIGURED → log + return; no row, no mutation."""
    settings = get_settings()
    settings.__dict__["openai_api_key"] = None

    seeded = await seed_completed_study()

    await generate_digest({}, seeded["study_id"])

    factory = get_session_factory()
    async with factory() as db:
        digest = await repo.get_digest_for_study(db, seeded["study_id"])
        assert digest is None
        proposal = await repo.get_proposal(db, seeded["proposal_id"])
        assert proposal is not None
        assert proposal.status == "pending"
        assert proposal.config_diff == {}
        assert proposal.metric_delta is None
