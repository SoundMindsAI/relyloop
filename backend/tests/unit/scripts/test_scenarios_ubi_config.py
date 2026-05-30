# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the SCENARIOS UBI config additions (Story 2.1 / FR-8).

These tests pin the per-scenario ``ubi_target_rung`` / ``ubi_converter``
values added by :mod:`scripts.seed_meaningful_demos` and verify that the
(slug, target) pairs for UBI-enabled scenarios match the backend's
:data:`backend.app.services.demo_ubi_seed.DEMO_UBI_SCENARIO_ALLOWLIST`.

The single source of truth for the allowlist lives in the backend module
(D-5); SCENARIOS-side drift here would silently break Story 2.2's
allowlist guard at runtime — these tests catch it at import time instead.
"""

from __future__ import annotations

from typing import get_args

import pytest

from backend.app.api.v1.schemas import UbiConverterKind
from backend.app.services.demo_ubi_seed import DEMO_UBI_SCENARIO_ALLOWLIST
from backend.app.services.ubi_readiness import UbiReadinessRung
from scripts.seed_meaningful_demos import SCENARIOS


def test_scenarios_ubi_keys_present_on_every_entry() -> None:
    """FR-8: both keys must appear on every SCENARIOS entry (None-or-value).

    Missing keys would let a future scenario silently bypass the
    invariant assertion since ``dict.get`` returns ``None`` for absent
    keys — explicit presence keeps the failure mode loud.
    """
    for scenario in SCENARIOS:
        assert "ubi_target_rung" in scenario, (
            f"SCENARIOS[{scenario['slug']}] missing ubi_target_rung key"
        )
        assert "ubi_converter" in scenario, (
            f"SCENARIOS[{scenario['slug']}] missing ubi_converter key"
        )


def test_invariant_converter_iff_target_rung() -> None:
    """FR-8: ubi_converter is None iff ubi_target_rung is None."""
    for scenario in SCENARIOS:
        target = scenario.get("ubi_target_rung")
        converter = scenario.get("ubi_converter")
        assert (target is None) == (converter is None), (
            f"SCENARIOS[{scenario['slug']}] violates FR-8 invariant: "
            f"target={target!r}, converter={converter!r}"
        )


def test_exactly_three_scenarios_have_ubi_config() -> None:
    """D-2: acme + corp + jobs are UBI-enabled; news + rich are not.

    The rich scenario (seed_rich_scenario) is a separate function and
    not in SCENARIOS; only news here is the negative case among the
    four small scenarios.
    """
    ubi_enabled = [s for s in SCENARIOS if s.get("ubi_target_rung") is not None]
    assert len(ubi_enabled) == 3, (
        f"Expected exactly 3 UBI-enabled SCENARIOS; "
        f"found {len(ubi_enabled)}: {[s['slug'] for s in ubi_enabled]}"
    )

    news_scenarios = [s for s in SCENARIOS if s["slug"] == "news-search-staging"]
    assert len(news_scenarios) == 1
    assert news_scenarios[0]["ubi_target_rung"] is None
    assert news_scenarios[0]["ubi_converter"] is None


def test_ubi_enabled_pairs_match_backend_allowlist() -> None:
    """D-5: every UBI-enabled (slug, target) pair must be in the backend allowlist.

    Drift here would make :func:`seed_synthetic_ubi` raise ``ValueError``
    at reseed time. Asserting at unit-test time keeps the failure cheap.
    """
    ubi_pairs = frozenset(
        (s["slug"], s["target"]) for s in SCENARIOS if s.get("ubi_target_rung") is not None
    )
    assert ubi_pairs == DEMO_UBI_SCENARIO_ALLOWLIST, (
        f"SCENARIOS UBI-enabled pairs {ubi_pairs!r} drift from "
        f"DEMO_UBI_SCENARIO_ALLOWLIST {DEMO_UBI_SCENARIO_ALLOWLIST!r}"
    )


def test_specific_d2_assignments() -> None:
    """D-2: pin the exact (slug → rung, converter) assignments.

    A reviewer-side regression that flips acme to dwell_time or moves
    corp off rung_1 changes the demo's pedagogical story. Pin the
    triples explicitly so the change is forced through this test.
    """
    expected: dict[str, tuple[str, str]] = {
        "acme-products-prod": ("rung_3", "ctr_threshold"),
        "corp-docs-search": ("rung_1", "hybrid_ubi_llm"),
        "jobs-marketplace-prod": ("rung_2", "hybrid_ubi_llm"),
    }
    actual = {
        s["slug"]: (s["ubi_target_rung"], s["ubi_converter"])
        for s in SCENARIOS
        if s.get("ubi_target_rung") is not None
    }
    assert actual == expected, (
        f"D-2 scenario → (rung, converter) drift: expected {expected!r}, got {actual!r}"
    )


def test_ubi_converter_values_are_backend_literals() -> None:
    """8.4 wire-value discipline: ubi_converter values must match UbiConverterKind."""
    allowed_converters = set(get_args(UbiConverterKind))
    for scenario in SCENARIOS:
        converter = scenario.get("ubi_converter")
        if converter is None:
            continue
        assert converter in allowed_converters, (
            f"SCENARIOS[{scenario['slug']}].ubi_converter={converter!r} "
            f"not in UbiConverterKind {allowed_converters!r}"
        )


def test_ubi_target_rung_values_are_backend_literals() -> None:
    """8.4 wire-value discipline: ubi_target_rung values must be valid rung literals.

    UbiReadinessRung includes ``rung_0`` for completeness, but the
    SCENARIOS allowlist excludes it (rung_0 means "no UBI" and is
    expressed via target=None).
    """
    allowed_rungs = set(get_args(UbiReadinessRung)) - {"rung_0"}
    for scenario in SCENARIOS:
        target = scenario.get("ubi_target_rung")
        if target is None:
            continue
        assert target in allowed_rungs, (
            f"SCENARIOS[{scenario['slug']}].ubi_target_rung={target!r} "
            f"not a synthetic-UBI-eligible rung {allowed_rungs!r}"
        )


def test_module_import_does_not_raise() -> None:
    """The module-level FR-8 assertion must not fire on the current SCENARIOS."""
    # Reimport-by-reload would re-execute the assertion. Importing again
    # is a no-op (cached), so reload via importlib for a real check.
    import importlib

    import scripts.seed_meaningful_demos as mod

    try:
        importlib.reload(mod)
    except AssertionError as exc:  # pragma: no cover — defensive
        pytest.fail(f"SCENARIOS module-level FR-8 invariant failed: {exc}")
