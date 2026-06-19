# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the reseed scenario manifest (per-scenario live state).

feat_reseed_scenario_manifest_live_state — covers:
* ``_build_scenario_manifest`` (all-pending order/copy, D-2 user-excluded pre-mark)
* the AC-7 drift guard (manifest membership/order locked to ``SCENARIOS``)
* ``_stamp_scenario`` transitions + the derived ``scenarios_completed`` (FR-6a)
* ``ScenarioProgress`` validation + legacy-blob deserialization (AC-8)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.services.demo_seeding import (
    _RICH_SCENARIO_SLUG,
    _SCENARIO_COPY,
    ReseedStatusResponse,
    ScenarioProgress,
    _build_scenario_manifest,
    _stamp_scenario,
)
from scripts.seed_meaningful_demos import SCENARIOS

_CANONICAL_SLUGS = [s["slug"] for s in SCENARIOS] + [_RICH_SCENARIO_SLUG]


# ---------------------------------------------------------------------------
# _build_scenario_manifest
# ---------------------------------------------------------------------------
def test_build_manifest_all_pending_in_canonical_order() -> None:
    """No filter → 6 entries, all pending, order == SCENARIOS + rich (AC-2)."""
    manifest = _build_scenario_manifest(None)
    assert [e.slug for e in manifest] == _CANONICAL_SLUGS
    assert all(e.state == "pending" for e in manifest)
    assert all(e.skip_reason is None for e in manifest)
    # Copy is populated from the source-of-truth table.
    for e in manifest:
        assert e.label == _SCENARIO_COPY[e.slug].label
        assert e.description == _SCENARIO_COPY[e.slug].description


def test_build_manifest_drift_guard_matches_scenarios() -> None:
    """AC-7: the copy table's slug set + order is locked to SCENARIOS + rich.

    A SCENARIOS change without a matching ``_SCENARIO_COPY`` update fails CI
    here instead of KeyError-ing at run time.
    """
    assert list(_SCENARIO_COPY.keys()) == _CANONICAL_SLUGS
    # Every canonical slug resolves to copy (no KeyError in the builder).
    manifest = _build_scenario_manifest(None)
    assert {e.slug for e in manifest} == set(_CANONICAL_SLUGS)


def test_build_manifest_premarks_user_excluded_engine() -> None:
    """D-2 / AC-6: an `engines` filter pre-marks excluded scenarios skipped."""
    manifest = _build_scenario_manifest(["elasticsearch"])
    by_engine = {e.slug: e for e in manifest}
    # OpenSearch scenario (news-search-staging) is excluded → skipped at build.
    os_entry = by_engine["news-search-staging"]
    assert os_entry.state == "skipped"
    assert os_entry.skip_reason == "user_excluded"
    # ES scenarios stay pending.
    assert by_engine["acme-products-prod"].state == "pending"
    # The rich scenario is ES → stays pending under an ES-only filter.
    assert by_engine[_RICH_SCENARIO_SLUG].state == "pending"


def test_build_manifest_premarks_rich_when_es_excluded() -> None:
    """Solr-only filter excludes the ES rich scenario at build (D-2)."""
    manifest = _build_scenario_manifest(["solr"])
    by_slug = {e.slug: e for e in manifest}
    assert by_slug[_RICH_SCENARIO_SLUG].state == "skipped"
    assert by_slug[_RICH_SCENARIO_SLUG].skip_reason == "user_excluded"
    assert by_slug["acme-kb-docs-solr"].state == "pending"


# ---------------------------------------------------------------------------
# _stamp_scenario + derived scenarios_completed
# ---------------------------------------------------------------------------
def _running(engines: list[str] | None = None) -> ReseedStatusResponse:
    return ReseedStatusResponse(
        status="running",
        scenarios_total=len(_CANONICAL_SLUGS),
        scenarios=_build_scenario_manifest(engines),  # type: ignore[arg-type]
    )


def test_stamp_active_then_done_updates_state_and_counter() -> None:
    """AC-3 / AC-4: active→done stamps state and recomputes the counter."""
    progress = _running()
    slug = _CANONICAL_SLUGS[0]
    _stamp_scenario(progress, slug, "active")
    assert next(e for e in progress.scenarios if e.slug == slug).state == "active"
    assert progress.scenarios_completed == 0  # active doesn't count
    _stamp_scenario(progress, slug, "done")
    # Re-fetch to read the post-stamp state (avoids mypy narrowing the earlier
    # binding to Literal['active']).
    assert next(e for e in progress.scenarios if e.slug == slug).state == "done"
    assert progress.scenarios_completed == 1  # derived (FR-6a)


def test_scenarios_completed_is_derived_not_incremented() -> None:
    """FR-6a: the counter equals count(state == 'done') after each done stamp."""
    progress = _running()
    done = 0
    for slug in _CANONICAL_SLUGS:
        _stamp_scenario(progress, slug, "done")
        done += 1
        assert progress.scenarios_completed == done


def test_stamp_skipped_carries_reason() -> None:
    """AC-5: a skipped stamp records the reason; done count excludes it."""
    progress = _running()
    _stamp_scenario(progress, "news-search-staging", "skipped", "unreachable")
    entry = next(e for e in progress.scenarios if e.slug == "news-search-staging")
    assert entry.state == "skipped"
    assert entry.skip_reason == "unreachable"
    assert progress.scenarios_completed == 0


def test_stamp_unknown_slug_is_noop() -> None:
    """A stamp for a slug not in the manifest must not raise or mutate."""
    progress = _running()
    before = [(e.slug, e.state) for e in progress.scenarios]
    _stamp_scenario(progress, "does-not-exist", "done")
    after = [(e.slug, e.state) for e in progress.scenarios]
    assert before == after
    assert progress.scenarios_completed == 0


# ---------------------------------------------------------------------------
# ScenarioProgress / ReseedStatusResponse validation
# ---------------------------------------------------------------------------
def test_scenario_progress_rejects_unknown_state() -> None:
    """extra='forbid' + Literal reject an invalid state."""
    with pytest.raises(ValidationError):
        ScenarioProgress(
            slug="x",
            label="X",
            description="x",
            engine="elasticsearch",
            state="bogus",
        )


def test_scenario_progress_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        ScenarioProgress(
            slug="x",
            label="X",
            description="x",
            engine="elasticsearch",
            state="pending",
            extra_field="nope",  # type: ignore[call-arg]
        )


def test_legacy_blob_without_scenarios_deserializes(  # AC-8
) -> None:
    """A Redis blob written before this field landed parses with scenarios=[]."""
    legacy = {
        "status": "complete",
        "scenarios_total": 6,
        "scenarios_completed": 6,
        "scenarios_skipped": [],
        "scenarios_skipped_reasons": {},
        # NOTE: no "scenarios" key (older worker).
    }
    parsed = ReseedStatusResponse(**legacy)
    assert parsed.scenarios == []
