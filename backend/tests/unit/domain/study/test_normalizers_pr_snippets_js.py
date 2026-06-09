# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Freshness + parity guard for the JS-snippet corpus fixture (FR-5 / Q-2).

The committed fixture ``ui/src/__tests__/fixtures/normalizer_snippet_parity.json``
is the shared three-way-parity corpus. The JS side is exercised by a frontend
vitest test (``normalizer-snippet-parity.test.ts``, Q-2) that runs each
``jsSnippet`` against the corpus and asserts it equals ``expected``. THIS
backend test keeps the fixture honest from the Python side:

  * ``expected`` for every case equals ``normalize_pipeline`` (so the golden
    the vitest test checks against is the real runtime output), and
  * ``jsSnippet`` for every case equals the current ``build_js_snippet`` output
    (so the fixture can't go stale when the generator changes).

If this test fails, regenerate the fixture (see its ``_comment`` field).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.app.domain.study.normalizers import (
    build_js_snippet,
    normalize_pipeline,
    steps_for_label,
)

_FIXTURE = (
    Path(__file__).resolve().parents[5]
    / "ui"
    / "src"
    / "__tests__"
    / "fixtures"
    / "normalizer_snippet_parity.json"
)


def _load() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text())


def test_fixture_exists_and_has_cases() -> None:
    data = _load()
    assert data["corpus"], "fixture corpus is empty"
    assert data["cases"], "fixture has no cases"


def test_expected_outputs_match_runtime() -> None:
    data = _load()
    corpus = data["corpus"]
    for case in data["cases"]:
        steps = steps_for_label(case["label"])
        recomputed = [normalize_pipeline(text, steps) for text in corpus]
        assert recomputed == case["expected"], (
            f"fixture 'expected' drifted from normalize_pipeline for label={case['label']!r}"
        )


def test_js_snippets_match_generator() -> None:
    data = _load()
    for case in data["cases"]:
        steps = steps_for_label(case["label"])
        assert case["jsSnippet"] == build_js_snippet(steps), (
            f"fixture 'jsSnippet' drifted from build_js_snippet for label={case['label']!r}"
        )
