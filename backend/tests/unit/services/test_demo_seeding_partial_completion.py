# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the all-engines-unreachable typed exception + worker mapping.

Covers the contract pieces that don't need a live orchestrator run:
- ``AllEnginesUnreachableError`` carries the skip list and stringifies to the
  stable ``all_engines_unreachable`` marker (and is a ``DemoSeedingError``).
- The worker's ``_build_failed_status`` maps the typed exception to a failed
  ``ReseedStatusResponse`` carrying ``failed_reason`` token + ``scenarios_skipped``
  + ``scenarios_completed=0``, and maps any OTHER exception to the generic reason.

The orchestrator's partial-completion path (status="complete" + non-empty
scenarios_skipped + WARN) is exercised end-to-end by the heavy-lane integration
test in ``test_demo_seeding_ubi_full.py`` against the real reachability probe.
"""

from __future__ import annotations

from backend.app.services.demo_seeding import (
    ALL_ENGINES_UNREACHABLE_MARKER,
    AllEnginesUnreachableError,
    DemoSeedingError,
)
from backend.workers.demo_reseed import _build_failed_status


def test_all_engines_unreachable_error_carries_slugs_and_marker() -> None:
    exc = AllEnginesUnreachableError(["acme-products-prod", "acme-kb-docs-solr"])
    assert exc.scenarios_skipped == ["acme-products-prod", "acme-kb-docs-solr"]
    assert str(exc) == ALL_ENGINES_UNREACHABLE_MARKER
    assert str(exc) == "all_engines_unreachable"
    # It must be a DemoSeedingError so the worker's existing barrier catches it.
    assert isinstance(exc, DemoSeedingError)


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
