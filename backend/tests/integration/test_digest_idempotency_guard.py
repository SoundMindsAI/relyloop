# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Cycle-1 F6 idempotency guard test for ``generate_digest``.

Pre-seeds a digest row; runs the worker; asserts:
* No second OpenAI call (mock fails loudly if invoked).
* No state mutated (digest still the original; pending proposal untouched).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

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


async def test_existing_digest_short_circuits_before_llm_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cycle-1 F6: pre-existing digest → log + return; OpenAI not called."""
    settings = get_settings()
    settings.__dict__["openai_api_key"] = "sk-test"

    seeded = await seed_completed_study()
    sentinel_id = str(uuid.uuid4())
    sentinel_narrative = "PRE-SEEDED-CANARY"

    factory = get_session_factory()
    async with factory() as db:
        await repo.create_digest(
            db,
            id=sentinel_id,
            study_id=seeded["study_id"],
            narrative=sentinel_narrative,
            parameter_importance={},
            recommended_config={},
            suggested_followups=[],
            generated_by="local:canary",
        )
        await db.commit()

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

    async with factory() as db:
        digest = await repo.get_digest_for_study(db, seeded["study_id"])
        assert digest is not None
        assert digest.id == sentinel_id  # original still there
        assert digest.narrative == sentinel_narrative
    create_mock.assert_not_called()
