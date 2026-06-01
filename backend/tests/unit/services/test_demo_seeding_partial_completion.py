# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the all-engines-unreachable typed exception + worker mapping.

Covers the contract pieces that don't need a live orchestrator run:
- ``AllEnginesUnreachableError`` carries the skip list and stringifies to the
  stable ``all_engines_unreachable`` marker (and is a ``DemoSeedingError``).
- ``_is_all_engines_unreachable`` — the verdict helper that decides hard-fail
  vs partial: True only when EVERY reachability-relevant scenario was skipped
  (so a reachable-but-tolerated-failure does NOT get misclassified as engine
  absence — GPT-5.5 phase-gate Finding 4).
- The worker's ``_build_failed_status`` maps the typed exception to a failed
  ``ReseedStatusResponse`` carrying ``failed_reason`` token + ``scenarios_skipped``
  + ``scenarios_completed=0``, and maps any OTHER exception to the generic reason.

The orchestrator's partial-completion path (status="complete" + non-empty
scenarios_skipped + WARN) and AC-3 (a reachable scenario failing mid-seed stays
a generic DemoSeedingError, never a skip) are exercised end-to-end by the
heavy-lane integration test in ``test_demo_seeding_ubi_full.py`` against the
real reachability probe + full seeding stack.
"""

from __future__ import annotations

from backend.app.services.demo_seeding import (
    _RICH_SCENARIO_SLUG,
    ALL_ENGINES_UNREACHABLE_MARKER,
    SCENARIOS,
    AllEnginesUnreachableError,
    DemoSeedingError,
    _is_all_engines_unreachable,
)
from backend.workers.demo_reseed import _build_failed_status


def test_all_engines_unreachable_error_carries_slugs_and_marker() -> None:
    exc = AllEnginesUnreachableError(["acme-products-prod", "acme-kb-docs-solr"])
    assert exc.scenarios_skipped == ["acme-products-prod", "acme-kb-docs-solr"]
    assert str(exc) == ALL_ENGINES_UNREACHABLE_MARKER
    assert str(exc) == "all_engines_unreachable"
    # It must be a DemoSeedingError so the worker's existing barrier catches it.
    assert isinstance(exc, DemoSeedingError)


def test_verdict_all_six_skipped_is_all_unreachable() -> None:
    every_slug = [str(s["slug"]) for s in SCENARIOS] + [_RICH_SCENARIO_SLUG]
    assert len(every_slug) == len(SCENARIOS) + 1
    assert _is_all_engines_unreachable(every_slug) is True


def test_verdict_partial_skip_is_not_all_unreachable() -> None:
    # Only Solr skipped (CI posture) -> partial, NOT all-unreachable.
    assert _is_all_engines_unreachable(["acme-kb-docs-solr"]) is False
    # Empty skip set (full completion) -> not all-unreachable.
    assert _is_all_engines_unreachable([]) is False


def test_verdict_rich_reachable_but_failed_is_not_all_unreachable() -> None:
    # GPT-5.5 phase-gate Finding 4: if every SCENARIOS slug skipped but the rich
    # ES scenario was REACHABLE (and then failed tolerated), rich is NOT in the
    # skip list -> count is len(SCENARIOS) (< total) -> NOT all-unreachable, so
    # the rich failure isn't masked as engine absence.
    only_scenarios = [str(s["slug"]) for s in SCENARIOS]
    assert _is_all_engines_unreachable(only_scenarios) is False


def test_build_failed_status_for_all_unreachable() -> None:
    slugs = [
        "acme-products-prod",
        "corp-docs-search",
        "news-search-staging",
        "jobs-marketplace-prod",
        "acme-products-rich-prod",
        "acme-kb-docs-solr",
    ]
    status = _build_failed_status(AllEnginesUnreachableError(slugs))
    assert status.status == "failed"
    assert status.failed_reason == "all_engines_unreachable"
    assert status.scenarios_skipped == slugs
    assert status.scenarios_completed == 0


def test_build_failed_status_for_generic_failure() -> None:
    status = _build_failed_status(DemoSeedingError("acme-products-prod/put_index: HTTP 503"))
    assert status.status == "failed"
    # Generic reason — NOT the stable token; carries the type prefix.
    assert status.failed_reason is not None
    assert status.failed_reason.startswith("DemoSeedingError:")
    assert "all_engines_unreachable" != status.failed_reason
    assert status.scenarios_skipped == []
