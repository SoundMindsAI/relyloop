# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Phase 3 chain-rollup service helper.

Mocks ``repo.get_chain_for_study`` + ``select_best_link`` +
``derive_chain_stop_reason`` + ``repo.bulk_mark_superseded`` so the test
runs without a DB. Covers the four early-return paths (chain missing,
single-link, in_flight, no winner) and the happy path.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.app.services import chain_rollup


@dataclass(frozen=True)
class _StubLink:
    id: str
    best_metric: float | None = None
    status: str = "completed"


def _stub_traversal(links: list[_StubLink]) -> SimpleNamespace:
    return SimpleNamespace(
        anchor_id=links[0].id if links else "",
        links=links,
        proposal_id_by_link_id={},
        anchor_trials=None,
    )


async def _call(
    monkeypatch: pytest.MonkeyPatch,
    *,
    traversal: SimpleNamespace | None,
    stop_reason: str = "no_lift",
    best_link_id: str | None = "winner",
    bulk_returns: list[str] | None = None,
) -> tuple[int, list[str]]:
    from backend.app.db import repo as repo_mod

    monkeypatch.setattr(
        repo_mod,
        "get_chain_for_study",
        AsyncMock(return_value=traversal),
    )
    monkeypatch.setattr(
        repo_mod,
        "bulk_mark_superseded",
        AsyncMock(return_value=bulk_returns or []),
    )
    monkeypatch.setattr(
        chain_rollup,
        "derive_chain_stop_reason",
        lambda links, anchor_trials: stop_reason,
    )
    monkeypatch.setattr(chain_rollup, "select_best_link", lambda links: best_link_id)
    db_stub: Any = object()
    return await chain_rollup.mark_non_winning_chain_proposals_superseded(db_stub, study_id="any")


async def test_returns_zero_when_chain_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    result = await _call(monkeypatch, traversal=None)
    assert result == (0, [])


async def test_returns_zero_for_single_link_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    result = await _call(monkeypatch, traversal=_stub_traversal([_StubLink("only")]))
    assert result == (0, [])


async def test_returns_zero_when_chain_still_in_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = await _call(
        monkeypatch,
        traversal=_stub_traversal([_StubLink("a"), _StubLink("b")]),
        stop_reason="in_flight",
    )
    assert result == (0, [])


async def test_returns_zero_when_no_best_link(monkeypatch: pytest.MonkeyPatch) -> None:
    result = await _call(
        monkeypatch,
        traversal=_stub_traversal([_StubLink("a"), _StubLink("b")]),
        best_link_id=None,
    )
    assert result == (0, [])


async def test_happy_path_returns_count_and_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two losers, repo returned both IDs; service surfaces ``(2, [...])``."""
    result = await _call(
        monkeypatch,
        traversal=_stub_traversal(
            [_StubLink("loser_a"), _StubLink("winner"), _StubLink("loser_b")]
        ),
        best_link_id="winner",
        bulk_returns=["loser_a_prop", "loser_b_prop"],
    )
    assert result == (2, ["loser_a_prop", "loser_b_prop"])


async def test_happy_path_with_zero_returned_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """Race: repo found no ``pending`` rows to transition; service returns ``(0, [])``."""
    result = await _call(
        monkeypatch,
        traversal=_stub_traversal([_StubLink("a"), _StubLink("b")]),
        best_link_id="a",
        bulk_returns=[],
    )
    assert result == (0, [])


async def test_prefetched_traversal_skips_get_chain_for_study(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini perf finding: when the caller passes ``traversal=``, the service
    must NOT re-issue ``get_chain_for_study``."""
    from backend.app.db import repo as repo_mod

    get_chain_mock = AsyncMock(return_value=None)
    monkeypatch.setattr(repo_mod, "get_chain_for_study", get_chain_mock)
    monkeypatch.setattr(repo_mod, "bulk_mark_superseded", AsyncMock(return_value=["loser_prop"]))
    monkeypatch.setattr(
        chain_rollup, "derive_chain_stop_reason", lambda links, anchor_trials: "no_lift"
    )
    monkeypatch.setattr(chain_rollup, "select_best_link", lambda links: "winner")
    prefetched: Any = _stub_traversal([_StubLink("loser"), _StubLink("winner")])
    db_stub: Any = object()
    result = await chain_rollup.mark_non_winning_chain_proposals_superseded(
        db_stub, study_id="any", traversal=prefetched
    )
    assert result == (1, ["loser_prop"])
    get_chain_mock.assert_not_called()
