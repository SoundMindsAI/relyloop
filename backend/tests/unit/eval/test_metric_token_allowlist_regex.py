# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""AC-3 strict-regex enumeration tests for the user-facing metric-token allowlist.

These tests prove the leakage assertion in
``backend/tests/contract/test_trial_row_shape.py`` (and the parallel
assertion in ``backend/tests/integration/test_run_trial_per_query_persistence.py``)
is SUBSTANTIVE — i.e., it rejects every known forbidden library wire-form
explicitly. Without these enumerations a regex bug that accidentally
matches everything (e.g., the loose ``^(ndcg|map|precision|recall)(@(...))?$``
the spec called out as buggy in plan cycle-1 F2) would pass silently.

The regex below MUST stay in sync with:
- ``backend/tests/contract/test_trial_row_shape.py`` (_STRICT_USER_FACING_KEY)
- ``backend/tests/integration/test_run_trial_per_query_persistence.py``
  (_STRICT_USER_FACING_KEY)
- ``backend/app/eval/scoring.py`` (SUPPORTED_METRICS + SUPPORTED_K_VALUES)

Added by infra_ir_measures_migration Story 1.5 per spec AC-3 + plan cycle-1 F2/F3.

Why this file lives at unit/ and not contract/: the regex is a pure-Python
predicate; it doesn't need Postgres or the Trial table to verify. The
contract test's module-level postgres_reachable skip would otherwise hide
the regex assertions in dev environments.
"""

from __future__ import annotations

import re

import pytest

from backend.app.eval.scoring import SUPPORTED_K_VALUES

# Authoritative strict regex — must match exactly the version in the
# contract + integration tests. (When this regex changes, both call sites
# must change in lock-step; the duplication is intentional to keep the
# allowlist visible at every assertion site.)
_STRICT_USER_FACING_KEY = re.compile(
    r"^(?:mrr|map|(?:ndcg|precision|recall|map)@(?:1|3|5|10|20|50|100))$"
)


def _all_allowed_keys() -> list[str]:
    """Generate every user-facing token in the allowlist from the source-of-truth.

    Per phase-gate F9: this enumeration MUST be dynamic so adding a value to
    ``SUPPORTED_K_VALUES`` automatically expands the positive-case coverage
    (and surfaces a regex update if the new value isn't covered).
    """
    allowed: list[str] = ["map", "mrr"]
    for k in sorted(SUPPORTED_K_VALUES):
        for base in ("ndcg", "precision", "recall", "map"):
            allowed.append(f"{base}@{k}")
    return allowed


@pytest.mark.parametrize(
    "forbidden_key",
    [
        # Uncut user-facing bases — invalid for ndcg/precision/recall:
        "ndcg",
        "precision",
        "recall",
        # ir_measures PascalCase metric-object reprs:
        "nDCG@10",
        "P@10",
        "R@10",
        "AP@5",
        "AP@10",
        "RR",
        # pytrec_eval legacy wire prefixes:
        "ndcg_cut_10",
        "recip_rank",
        "map_cut_10",
        "P_10",
        "recall_10",
        # Other invalid tokens:
        "ndcg@15",  # k not in SUPPORTED_K_VALUES
        "ndcg@",  # missing k
        "@10",  # missing metric base
        "",  # empty string
        "MRR",  # case mismatch
        "Ndcg@10",  # case mismatch
    ],
)
def test_strict_key_regex_rejects_forbidden(forbidden_key: str) -> None:
    """The AC-3 strict regex rejects every known forbidden key explicitly."""
    assert _STRICT_USER_FACING_KEY.match(forbidden_key) is None, (
        f"strict-key regex should REJECT {forbidden_key!r} but matched it — "
        f"library wire-form leakage check is not substantive"
    )


@pytest.mark.parametrize("allowed_key", _all_allowed_keys())
def test_strict_key_regex_accepts_allowed(allowed_key: str) -> None:
    """The AC-3 strict regex accepts every user-facing token in the allowlist.

    Parametrized dynamically from ``SUPPORTED_K_VALUES`` so adding a new k value
    automatically expands coverage. Total cases: 2 plain (map, mrr) + 4 metric
    bases (ndcg, precision, recall, map) × 7 k-values = 30 — the same cross
    enumerated by the FR-2 parity test.
    """
    assert _STRICT_USER_FACING_KEY.match(allowed_key) is not None, (
        f"strict-key regex should ACCEPT {allowed_key!r} but rejected it — "
        f"user-facing token allowlist is too tight"
    )


def test_allowed_keys_count_matches_supported_cross() -> None:
    """Sanity check: the dynamic enumeration covers every supported cell."""
    allowed = _all_allowed_keys()
    # 2 plain (map, mrr) + 4 cut-aware metrics × SUPPORTED_K_VALUES.
    expected_count = 2 + 4 * len(SUPPORTED_K_VALUES)
    assert len(allowed) == expected_count, (
        f"dynamic enumeration count drift: got {len(allowed)}, "
        f"expected 2 + 4*{len(SUPPORTED_K_VALUES)} = {expected_count}. "
        f"Did SUPPORTED_K_VALUES change without a regex update?"
    )
