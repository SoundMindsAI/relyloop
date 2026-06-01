# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit test for the all-engines-unreachable orchestrator path (Story 1.2 / AC-10).

When ``is_engine_reachable`` returns ``False`` for every scenario, the orchestrator
loop skips all scenarios (skipped iterations touch neither the DB nor the API
client), so ``reseed_demo_state`` is unit-testable with mocked ``db`` +
``engine_client``: the only real DB op before the loop is a TRUNCATE + commit,
and the only engine ops are the pre-loop ES/OS index DELETEs (which return 404).

Asserts: ``reseed_demo_state`` raises ``AllEnginesUnreachableError`` carrying all
6 scenario slugs (5 ``SCENARIOS`` + the rich ESCI scenario) and never returns a
no-op ``complete``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.app.services import demo_seeding
from backend.app.services.demo_seeding import (
    _RICH_SCENARIO_SLUG,
    SCENARIOS,
    AllEnginesUnreachableError,
    reseed_demo_state,
)


class _DeleteResponse:
    status_code = 404
    text = ""


@pytest.mark.asyncio
async def test_all_engines_unreachable_raises_with_every_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Every engine probe returns False -> every scenario (incl. rich) skips.
    async def always_unreachable(_url: str, _engine_type: str, **_kw: Any) -> bool:
        return False

    monkeypatch.setattr(demo_seeding, "is_engine_reachable", always_unreachable)

    # Mocked DB: TRUNCATE + commit are no-ops.
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()

    # Mocked engine client: the pre-loop ES/OS index DELETEs return 404 (the
    # tolerated "already absent" path). No scenario seeding runs (all skipped).
    engine_client = AsyncMock()
    engine_client.delete = AsyncMock(return_value=_DeleteResponse())

    api_client = AsyncMock()  # never used — all scenarios skip before any API call

    with pytest.raises(AllEnginesUnreachableError) as excinfo:
        await reseed_demo_state(db, api_client, engine_client)

    skipped = excinfo.value.scenarios_skipped
    expected = {scenario["slug"] for scenario in SCENARIOS} | {_RICH_SCENARIO_SLUG}
    assert set(skipped) == expected
    assert len(skipped) == len(SCENARIOS) + 1  # 6: no duplicates
    # api_client must never have been touched (every scenario skipped pre-dispatch).
    api_client.post.assert_not_called()
