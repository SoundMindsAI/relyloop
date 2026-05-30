# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Telemetry tests for ``agent.create_study.invoked`` (Story 3.3 / spec FR-6).

The create-side tool emits one INFO event after search-space validation
(before FK resolution). Tests assert:

- Happy-path search_space validation succeeds → INFO event fires with the
  expected fields, including ``study_id_pending`` (the pre-INSERT UUIDv7)
  and ``conversation_id`` from ctx.
- Subsequent failure (e.g., unknown cluster_id 404) still fires the event
  because it's emitted before FK resolution.
- Invalid search_space (400) does NOT fire the event because validation
  raises first.
- Logger failure is swallowed.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.app.agent.tools.studies.create_study import (
    CreateStudyArgs,
    create_study_impl,
)


def _valid_args() -> CreateStudyArgs:
    """Build a valid CreateStudyArgs payload using uuid4 UUIDs."""
    return CreateStudyArgs(
        name="test-study",
        cluster_id=str(uuid4()),
        target="products",
        template_id=str(uuid4()),
        query_set_id=str(uuid4()),
        judgment_list_id=str(uuid4()),
        search_space={
            "params": {"title_boost": {"type": "float", "low": 0.5, "high": 10.0, "log": True}}
        },
        objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
        config={"max_trials": 100},
    )


_REPO_PATH = "backend.app.agent.tools.studies.create_study.repo"


def _patch_repo_for_failure_at_cluster(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch so cluster fetch returns None (404) — runs telemetry before raising."""
    monkeypatch.setattr(f"{_REPO_PATH}.get_cluster", AsyncMock(return_value=None))


async def test_event_fires_when_cluster_lookup_raises(
    fake_ctx: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Telemetry fires before FK resolution, so even a CLUSTER_NOT_FOUND raise emits the event."""
    _patch_repo_for_failure_at_cluster(monkeypatch)
    caplog.set_level(logging.INFO, logger="backend.app.agent.tools.studies.create_study")
    args = _valid_args()
    with pytest.raises(HTTPException):
        await create_study_impl(args, fake_ctx)

    matches = [r for r in caplog.records if "agent.create_study.invoked" in r.message]
    assert len(matches) == 1
    record = matches[0]
    assert record.levelno == logging.INFO
    assert f"conversation_id={fake_ctx.conversation_id}" in record.message
    assert "study_id_pending=" in record.message
    assert "search_space_param_names=['title_boost']" in record.message


async def test_event_does_not_fire_on_invalid_search_space(
    fake_ctx: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """INVALID_SEARCH_SPACE 400 raises before the telemetry block → no event."""
    caplog.set_level(logging.INFO, logger="backend.app.agent.tools.studies.create_study")
    # Empty params → Pydantic rejects via min_length=1.
    invalid = CreateStudyArgs(
        name="bad",
        cluster_id=str(uuid4()),
        target="x",
        template_id=str(uuid4()),
        query_set_id=str(uuid4()),
        judgment_list_id=str(uuid4()),
        search_space={"params": {}},
        objective={"metric": "ndcg", "k": 10, "direction": "maximize"},
        config={"max_trials": 1},
    )
    with pytest.raises(HTTPException):
        await create_study_impl(invalid, fake_ctx)

    assert not [r for r in caplog.records if "agent.create_study.invoked" in r.message]


async def test_logger_failure_is_swallowed(fake_ctx: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the logger raises, the impl still proceeds (failing later only on the FK 404)."""
    _patch_repo_for_failure_at_cluster(monkeypatch)
    import backend.app.agent.tools.studies.create_study as tool_mod

    monkeypatch.setattr(
        tool_mod.logger,
        "info",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("structlog blew up")),
    )
    args = _valid_args()
    # The cluster 404 is what we should observe — the logger failure must not propagate.
    with pytest.raises(HTTPException) as exc:
        await create_study_impl(args, fake_ctx)
    assert exc.value.status_code == 404
