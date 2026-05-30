# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the markdown-aware truncation in scripts/build_mvp1_dashboard.py.

Covers `_safe_truncate_markdown` + `_strip_unclosed_markdown` — the fix for
[chore_mvp1_dashboard_truncation](../../../../docs/00_overview/planned_features/chore_mvp1_dashboard_truncation/idea.md)
(folded into PR #73 rather than deferred as an idea file, per the calibration
rubric being added to CLAUDE.md "Tangential discoveries").
"""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/build_mvp1_dashboard.py is at the repo root, not on sys.path.
_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT))

from scripts.build_mvp1_dashboard import (  # noqa: E402
    _safe_truncate_markdown,
    _strip_unclosed_markdown,
)


class TestSafeTruncateMarkdown:
    def test_short_input_returned_unchanged(self) -> None:
        text = "Short prose under the cap."
        assert _safe_truncate_markdown(text, 240) == text

    def test_input_at_exact_limit_returned_unchanged(self) -> None:
        text = "x" * 240
        assert _safe_truncate_markdown(text, 240) == text

    def test_truncates_at_sentence_boundary(self) -> None:
        text = "First sentence ends here. " + "filler " * 100
        result = _safe_truncate_markdown(text, 60)
        assert result.startswith("First sentence ends here.")
        assert result.endswith("…")
        assert len(result) <= 60

    def test_strips_unclosed_markdown_link(self) -> None:
        # Long input ending mid-`[label](url` after the natural cut
        text = "Description with [a partial markdown link going past the cap" + " filler word" * 50
        result = _safe_truncate_markdown(text, 60)
        assert result.count("[") == result.count("]")
        assert result.count("(") == result.count(")")
        assert result.endswith("…")

    def test_strips_unclosed_code_span(self) -> None:
        text = "Description with `unclosed inline code span " + "y " * 100
        result = _safe_truncate_markdown(text, 50)
        assert result.count("`") % 2 == 0
        assert result.endswith("…")

    def test_falls_back_to_word_boundary_when_no_sentence_end(self) -> None:
        # No sentence-ending punctuation within the last 50 chars.
        text = "alpha bravo charlie delta echo foxtrot " * 20
        result = _safe_truncate_markdown(text, 100)
        # Should end at a word boundary (followed by ellipsis), not mid-word.
        stripped = result.rstrip("…").rstrip()
        assert not stripped.endswith(("alph", "brav", "charli", "delt"))

    def test_appends_single_char_ellipsis_when_truncated(self) -> None:
        text = "x " * 200
        result = _safe_truncate_markdown(text, 50)
        assert result.endswith("…")
        # Single-char ellipsis, not three dots.
        assert not result.endswith("...")

    def test_no_spaces_falls_back_to_hard_cut(self) -> None:
        # Pathological input — one long unbroken token. The fix should
        # still produce something ≤max_len, even if it's empty + ellipsis
        # (because _strip_unclosed_markdown can't find a balanced prefix
        # with no spaces).
        text = "a" * 500
        result = _safe_truncate_markdown(text, 50)
        assert len(result) <= 50


class TestStripUnclosedMarkdown:
    def test_balanced_input_unchanged(self) -> None:
        text = "Balanced [link](url) and `code` are fine."
        assert _strip_unclosed_markdown(text) == text

    def test_strips_unclosed_open_bracket(self) -> None:
        text = "Some text [partial link"
        result = _strip_unclosed_markdown(text)
        assert "[" not in result

    def test_strips_unclosed_paren(self) -> None:
        text = "Some text [label](url-without-close"
        result = _strip_unclosed_markdown(text)
        assert result.count("(") == result.count(")")
        assert result.count("[") == result.count("]")

    def test_strips_odd_backtick_count(self) -> None:
        text = "Some text with `unclosed code"
        result = _strip_unclosed_markdown(text)
        assert result.count("`") % 2 == 0

    def test_returns_empty_when_no_balanced_prefix(self) -> None:
        # Pathological — opening bracket at the very start, no spaces.
        text = "[noprefix"
        assert _strip_unclosed_markdown(text) == ""
