# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Regression guard for the FR-1 compute_default_params extension (Story 1.2).

The spec cycle-2 review caught that without a reserved-key short-circuit, a
normalizer-aware template would crash inside the adapter with
``ValueError("unknown normalizer: ")`` on the very first baseline trial or
LLM-judgment hit — because the simple-form fallback yields ``""`` and the
rich-form fallback yields the first categorical value, neither of which is a
valid normalizer choice. This test locks the fix: ``query_normalizer`` always
defaults to ``DEFAULT_NORMALIZER`` ("none"), the only no-op choice.
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.app.domain.study.normalizers import DEFAULT_NORMALIZER
from backend.app.domain.study.template_defaults import compute_default_params


def _row(declared: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(declared_params=declared)


def test_default_normalizer_value_lock() -> None:
    # Mirrors the STUDIES_TPE_WARMUP_FLOOR value-lock discipline: the import
    # must be literally "none" so this story's guarantee is meaningful.
    assert DEFAULT_NORMALIZER == "none"


def test_simple_form_query_normalizer_defaults_to_none() -> None:
    row = _row({"query_normalizer": "string", "title_boost": "float"})
    result = compute_default_params(row)
    # NOT {"query_normalizer": "", ...} — the reserved short-circuit wins
    # over the simple-form "string" -> "" fallback.
    assert result == {"query_normalizer": "none", "title_boost": 1.0}


def test_rich_form_query_normalizer_defaults_to_none_not_first_categorical() -> None:
    row = _row(
        {
            "query_normalizer": {
                "type": "categorical",
                "values": ["lowercase", "lowercase+trim"],
            },
            "title_boost": {"type": "float", "min": 0.5, "max": 2.5},
        }
    )
    result = compute_default_params(row)
    # NOT {"query_normalizer": "lowercase", ...} — even though "lowercase" is
    # the first categorical value, the reserved key overrides to "none".
    assert result == {"query_normalizer": "none", "title_boost": 1.5}


def test_absent_query_normalizer_is_not_injected() -> None:
    row = _row({"title_boost": "float"})
    result = compute_default_params(row)
    assert "query_normalizer" not in result
    assert result == {"title_boost": 1.0}
