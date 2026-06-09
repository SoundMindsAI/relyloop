# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""AC-10: ``compute_default_params`` defaults a ``query_normalizer`` param to
the label string ``"none"`` — never a ``[]`` steps list (D-7).

A typed normalizer pipeline is declared under the reserved
``query_normalizer`` key, which Phase 1's ``compute_default_params`` already
short-circuits to :data:`DEFAULT_NORMALIZER`. This test pins that the
single-wire-shape guarantee (label string everywhere, never ``[]``) holds
for the pipeline declaration shapes too, so baseline trials and LLM-judgment
runs never feed an invalid value to ``adapter.render``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.app.domain.study.normalizers import DEFAULT_NORMALIZER
from backend.app.domain.study.template_defaults import compute_default_params


@pytest.mark.parametrize(
    "declared",
    [
        {"query_normalizer": "string"},  # simple form
        {"query_normalizer": {"type": "categorical", "values": ["none", "lowercase"]}},  # rich
        {"query_normalizer": {"type": "normalizer_pipeline"}},  # pipeline-shaped declaration
    ],
)
def test_query_normalizer_defaults_to_none_label(declared: dict[str, Any]) -> None:
    row = SimpleNamespace(declared_params=declared)
    out = compute_default_params(row)
    assert out["query_normalizer"] == DEFAULT_NORMALIZER == "none"
    # Never the empty steps list.
    assert out["query_normalizer"] != []


def test_other_params_still_default_alongside_normalizer() -> None:
    row = SimpleNamespace(declared_params={"title_boost": "float", "query_normalizer": "string"})
    out = compute_default_params(row)
    assert out["title_boost"] == 1.0
    assert out["query_normalizer"] == "none"
