# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Orchestrator-level state-stamping tests for the reseed scenario manifest.

feat_reseed_scenario_manifest_live_state Story 1.2 — drives the REAL
``reseed_demo_state`` with every I/O helper monkeypatched (the
``test_demo_reseed_partial_completion_fast`` harness, reused here so this stays
a pure, DB-free unit) and asserts the per-scenario ``scenarios`` manifest is
stamped pending → active → done / skipped, that ``scenarios_completed`` is
derived from the manifest (FR-6a), and that skip reasons are carried (AC-3/4/5).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.app.services import demo_seeding
from backend.app.services.demo_seeding import (
    _RICH_SCENARIO_SLUG,
    SCENARIOS,
    ReseedStatusResponse,
    reseed_demo_state,
)

# Reuse the canned-seed-path harness from the sibling fast test (locked
# approach b' — patch the module-level I/O helpers, orchestrator structure
# untouched). Importing the helpers avoids duplicating ~130 lines of stubs.
from backend.tests.unit.services.test_demo_reseed_partial_completion_fast import (
    _all_engines_reachable,
    _install_canned_seed_path,
    _mock_db,
    _mock_engine_client,
    _only_solr_unreachable,
)

_CANONICAL_SLUGS = [s["slug"] for s in SCENARIOS] + [_RICH_SCENARIO_SLUG]


def _snapshotting_callback(
    snapshots: list[ReseedStatusResponse],
) -> Any:
    """Status callback that deep-copies each emitted progress so intermediate
    states (e.g. a scenario held ``active``) survive — the orchestrator mutates
    one ``progress`` object in place and re-emits it, so live references would
    all collapse to the final state."""

    async def _cb(progress: ReseedStatusResponse) -> None:
        snapshots.append(progress.model_copy(deep=True))

    return _cb


async def test_manifest_stamped_pending_active_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-1/AC-3/AC-4: manifest present + ordered; a scenario is observed
    ``active`` mid-run; reachable scenarios end ``done`` with a derived counter."""
    _install_canned_seed_path(monkeypatch)
    monkeypatch.setattr(demo_seeding, "is_engine_reachable", _all_engines_reachable())
    # The canned harness skips Solr (only-solr-unreachable); to exercise the
    # ALL-done path we also stub the Solr seed helper so its scenario completes.
    monkeypatch.setattr(demo_seeding, "_seed_solr_scenario", AsyncMock(return_value=None))

    snapshots: list[ReseedStatusResponse] = []
    await reseed_demo_state(
        _mock_db(),
        MagicMock(),
        _mock_engine_client(),
        status_callback=_snapshotting_callback(snapshots),
    )

    final = snapshots[-1]
    # AC-1: manifest present, canonical order.
    assert [e.slug for e in final.scenarios] == _CANONICAL_SLUGS
    # AC-4: every scenario done (all engines reachable), counter derived.
    assert all(e.state == "done" for e in final.scenarios)
    assert final.scenarios_completed == len(_CANONICAL_SLUGS)
    assert final.scenarios_completed == sum(1 for e in final.scenarios if e.state == "done")

    # AC-3: at least one snapshot held some scenario ``active`` (the first
    # snapshot for each scenario flips it active before its seed work).
    saw_active = any(any(e.state == "active" for e in snap.scenarios) for snap in snapshots)
    assert saw_active, "expected at least one snapshot with a scenario state=active"

    # AC-3 (single active): no snapshot has two scenarios active at once
    # (orchestrator is sequential).
    for snap in snapshots:
        assert sum(1 for e in snap.scenarios if e.state == "active") <= 1


async def test_unreachable_scenario_stamped_skipped_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-5: an unreachable engine's scenario is stamped skipped/unreachable
    while the legacy ``scenarios_skipped`` accounting is unchanged."""
    _install_canned_seed_path(monkeypatch)
    monkeypatch.setattr(demo_seeding, "is_engine_reachable", _only_solr_unreachable())

    snapshots: list[ReseedStatusResponse] = []
    await reseed_demo_state(
        _mock_db(),
        MagicMock(),
        _mock_engine_client(),
        status_callback=_snapshotting_callback(snapshots),
    )

    final = snapshots[-1]
    solr = next(e for e in final.scenarios if e.slug == "acme-kb-docs-solr")
    assert solr.state == "skipped"
    assert solr.skip_reason == "unreachable"
    # Legacy field parity (back-compat unchanged).
    assert "acme-kb-docs-solr" in final.scenarios_skipped
    assert final.scenarios_skipped_reasons["acme-kb-docs-solr"] == "unreachable"
    # Derived counter excludes the skipped Solr scenario: 4 small + rich = 5.
    assert final.scenarios_completed == len(SCENARIOS) - 1 + 1


async def test_user_excluded_scenario_stamped_skipped_user_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-6: a POST engines filter pre-marks + stamps excluded scenarios
    skipped/user_excluded (visible from the FIRST emitted snapshot, D-2)."""
    _install_canned_seed_path(monkeypatch)
    monkeypatch.setattr(demo_seeding, "is_engine_reachable", _all_engines_reachable())

    snapshots: list[ReseedStatusResponse] = []
    await reseed_demo_state(
        _mock_db(),
        MagicMock(),
        _mock_engine_client(),
        status_callback=_snapshotting_callback(snapshots),
        engines=["elasticsearch"],
    )

    # D-2: the OpenSearch scenario is skipped/user_excluded in the FIRST snapshot
    # (pre-marked at manifest build, before the loop reaches it).
    first = snapshots[0]
    os_entry = next(e for e in first.scenarios if e.slug == "news-search-staging")
    assert os_entry.state == "skipped"
    assert os_entry.skip_reason == "user_excluded"

    final = snapshots[-1]
    # ES scenarios complete; OS stays skipped/user_excluded.
    es_entry = next(e for e in final.scenarios if e.slug == "acme-products-prod")
    assert es_entry.state == "done"
    os_final = next(e for e in final.scenarios if e.slug == "news-search-staging")
    assert os_final.state == "skipped"
    assert os_final.skip_reason == "user_excluded"
