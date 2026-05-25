"""Tests for `_extract_pr_number`'s idea-aware extraction.

Covers `chore_dashboard_pr_extraction_from_idea` FRs 1-5 and ACs 1-17:
- FR-1 + AC-11: extended signature with backward-compat default arg.
- FR-2 + AC-1/2/3/4/14/15/16: three line-anchored strict idea-body
  patterns (Status/Shipped, Status/Implemented, line-start shipped
  dateline) with `\\b` boundaries that reject partial-token and
  dependency-cite false positives.
- FR-3 + AC-5/6/13/17: `**PR:**` frontmatter fallback bounded to the
  metadata block (contiguous metadata-key lines + 30-line cap), with
  body-section references explicitly excluded.
- FR-4 + AC-12: `_load_implemented` reads `idea.md` and threads it
  through.
- FR-5 + AC-4/13/14/17: line-anchoring (not stripping) is the safeguard
  against false positives.

Priority cascade (AC-7/8/9/10): pipeline_status → plan Status → fuzzy
merged-context → 3.5 idea strict patterns → 3.6 idea frontmatter →
last-resort `#N` fallback.
"""

from __future__ import annotations

from pathlib import Path

from scripts.build_mvp1_dashboard import (
    _IDEA_PR_FRONTMATTER_RE,
    _IDEA_STATUS_IMPLEMENTED_RE,
    _IDEA_STATUS_SHIPPED_RE,
    _METADATA_KEY_RE,
    _extract_metadata_block,
    _extract_pr_number,
    _load_implemented,
    _strip_backtick_quoted_segments,
)

# Canonical precedent idea bodies — derived from real legacy idea.md files
# under `docs/00_overview/implemented_features/`. Verified during preflight
# (2026-05-23) to be representative of the actual frontmatter shapes.

_PRECEDENT_STATUS_SHIPPED_LINKED = (
    "# feat_contextual_help_mvp2\n"
    "\n"
    "**Status:** **Shipped** as PR [#124](https://github.com/SoundMindsAI/relyloop/pull/124)"
    " (squash-merged 2026-05-15, commit `9d22f62`). Operator-driven scope expansion.\n"
)

_PRECEDENT_STATUS_SHIPPED_UNLINKED = (
    "# Feature title\n\n**Status:** **Shipped** as PR #88 (squash 2026-05-10).\n"
)

_PRECEDENT_STATUS_IMPLEMENTED = (
    "# chore_create_study_modal_e2e_stability\n"
    "\n"
    "**Status:** **Implemented — PR #161 (squash `0879df2`)**, merged 2026-05-20."
    " Picked Option B (Playwright-side dispatchEvent fix).\n"
)

_PRECEDENT_SHIPPED_DATELINE = (
    "# chore_precommit_node_path_resolution\n"
    "\n"
    "**Status:** Sibling to PR #171 (Python pin + venv isolation).\n"
    "\n"
    "## Background\n"
    "\n"
    "**shipped 2026-05-21 as PR #171** (squash `861e354`) — the original\n"
    "pre-commit hook failure surfaced when a non-uv shell ran `git commit`.\n"
)

_PRECEDENT_DEPENDENCY_ONLY = (
    "# infra_frontend_stack_refresh\n"
    "\n"
    "**Date:** 2026-05-12\n"
    "**Depends on:** [`infra_foundation`](../2026_05_09_infra_foundation/) — merged"
    " via PR #4 (2026-05-09).\n"
    "\n"
    "## Problem\n"
)


class TestStrictPatternExtraction:
    """AC-1, AC-2, AC-3, AC-16 — positive extraction for each strict pattern."""

    def test_ac1_status_shipped_unlinked_extracts(self) -> None:
        assert _extract_pr_number("", "", "", _PRECEDENT_STATUS_SHIPPED_UNLINKED) == 88

    def test_ac1_ac16_status_shipped_linked_extracts(self) -> None:
        # AC-1 + AC-16: fully-bracketed markdown link form.
        assert _extract_pr_number("", "", "", _PRECEDENT_STATUS_SHIPPED_LINKED) == 124

    def test_ac2_status_implemented_extracts(self) -> None:
        assert _extract_pr_number("", "", "", _PRECEDENT_STATUS_IMPLEMENTED) == 161

    def test_ac3_shipped_dateline_extracts(self) -> None:
        assert _extract_pr_number("", "", "", _PRECEDENT_SHIPPED_DATELINE) == 171


class TestFalsePositiveRejection:
    """AC-4, AC-13, AC-14, AC-15, AC-17 — line-anchor and metadata-block locks."""

    def test_ac4_dependency_only_pr_returns_none(self) -> None:
        # The idea body contains only a `merged via PR #4` reference for the
        # DEPENDENCY (`infra_foundation`), not this feature's own PR.
        assert _extract_pr_number("", "", "", _PRECEDENT_DEPENDENCY_ONLY) is None

    def test_ac14_inline_bold_in_dependency_cite_does_not_match(self) -> None:
        # The exact Pattern C phrase appears MID-LINE inside a dependency cite.
        # The line-anchor `^` must prevent the match — this is the central
        # correctness criterion of FR-5 + AC-14.
        idea = (
            "# Feature title\n"
            "\n"
            "Depends on chore_X (**shipped 2026-05-21 as PR #171**) — see prior work.\n"
        )
        assert _extract_pr_number("", "", "", idea) is None

    def test_ac14_table_row_bold_does_not_match(self) -> None:
        # Pattern C must also reject the inline-bold phrase when it appears
        # inside a markdown table-row cell (lines starting with `|` cannot
        # match `^\*\*shipped...`).
        idea = (
            "# Feature title\n"
            "\n"
            "| Feature | PR |\n"
            "|---|---|\n"
            "| chore_X | **shipped 2026-05-21 as PR #171** |\n"
        )
        assert _extract_pr_number("", "", "", idea) is None

    def test_ac15_pattern_a_rejects_partial_bracket_token(self) -> None:
        # `PR [#124` without closing `]` is malformed; Pattern A must reject.
        idea = "# Feature title\n\n**Status:** **Shipped** as PR [#124 (incomplete bracket)\n"
        assert _extract_pr_number("", "", "", idea) is None

    def test_ac15_pattern_a_rejects_trailing_alphanum_token(self) -> None:
        # `PR #124abc` — the `\b` boundary after the digit must prevent the
        # match because `4` (word) → `a` (word) does not produce a boundary.
        idea = "# Feature title\n\n**Status:** **Shipped** as PR #124abc\n"
        assert _extract_pr_number("", "", "", idea) is None

    def test_ac13_pr_in_body_section_does_not_match(self) -> None:
        # `**PR:** #999` appears INSIDE a body section (after `## Related`),
        # not in the metadata block. Frontmatter-only intent must reject.
        idea = (
            "# Feature title\n"
            "\n"
            "**Date:** 2026-05-23\n"
            "**Status:** Idea — pending\n"
            "\n"
            "## Related\n"
            "\n"
            "**PR:** #999 — see prior PR\n"
        )
        assert _extract_pr_number("", "", "", idea) is None

    def test_ac17_pr_at_line_50_does_not_match_headingless(self) -> None:
        # Headingless idea with the metadata cluster ending at line ~5,
        # then narrative continuing. `**PR:** #99` appears at line 50.
        # The metadata block stops at the first non-blank non-metadata line
        # AND/OR at the 30-line cap — line 50 is outside the bounded scope.
        prefix = (
            "# Headingless idea title\n"
            "\n"
            "**Date:** 2026-05-23\n"
            "**Status:** Idea\n"
            "\n"
            "Some narrative content goes here that is neither a metadata key\n"
            "nor a heading. This line ends the metadata block per FR-3.\n"
        )
        # Pad to push **PR:** past line 30 / past the metadata-block stop.
        padding = "Filler line.\n" * 45
        idea = prefix + padding + "**PR:** #99\n"
        assert _extract_pr_number("", "", "", idea) is None


class TestFrontmatterFallback:
    """AC-5, AC-6 — `**PR:**` frontmatter behavior."""

    def test_ac5_pr_in_metadata_block_extracts(self) -> None:
        idea = (
            "# Feature title\n"
            "\n"
            "**Date:** 2026-05-23\n"
            "**Status:** Idea\n"
            "**PR:** #42\n"
            "\n"
            "## Problem\n"
            "\n"
            "Body content.\n"
        )
        assert _extract_pr_number("", "", "", idea) == 42

    def test_ac6_strict_pattern_beats_frontmatter(self) -> None:
        # When BOTH a strict pattern AND a `**PR:**` frontmatter are
        # present with conflicting PR numbers, the strict pattern (3.5)
        # wins over the frontmatter (3.6).
        idea = "# Feature title\n\n**Status:** **Shipped** as PR #100\n**PR:** #999\n"
        assert _extract_pr_number("", "", "", idea) == 100


class TestPriorityCascade:
    """AC-7, AC-8, AC-9, AC-10 — canonical artifacts beat idea body."""

    def test_ac7_pipeline_status_implement_section_beats_idea(self) -> None:
        # Priority 1 (pipeline_status `## Implement`) wins over priority 3.5.
        pipe = (
            "# Pipeline Status\n"
            "\n"
            "## Implement\n"
            "- Status: Complete\n"
            "- PR: #200 (squash `abc123`) merged 2026-05-22\n"
        )
        idea = _PRECEDENT_STATUS_SHIPPED_LINKED  # carries PR #124
        assert _extract_pr_number(pipe, "", "", idea) == 200

    def test_ac8_plan_status_header_beats_idea(self) -> None:
        # Priority 2 (plan `**Status:**`) wins over priority 3.5.
        plan = "**Status:** Complete (PR #300, squash `def456`)\n"
        idea = _PRECEDENT_STATUS_SHIPPED_LINKED  # carries PR #124
        assert _extract_pr_number("", plan, "", idea) == 300

    def test_ac9_fuzzy_merged_in_spec_beats_idea(self) -> None:
        # Priority 3 (fuzzy `merged`-context match) wins over priority 3.5.
        spec = "# Feature spec\n\nStatus: merged on 2026-05-15 via PR #150 (squash `ghi789`).\n"
        idea = _PRECEDENT_STATUS_SHIPPED_LINKED  # carries PR #124
        assert _extract_pr_number("", "", spec, idea) == 150

    def test_ac10_last_resort_fires_when_idea_empty(self) -> None:
        # Priority 4 (last-resort first `#N` outside dep-table-rows) fires
        # when 1, 2, 3, 3.5, 3.6 all miss. Use a narrative-form spec with
        # a bare `PR #500` reference that isn't in a `merged`-context.
        spec = (
            "# Feature spec\n"
            "\n"
            "Background: this work originated in discussions around PR #500\n"
            "but was scoped separately.\n"
        )
        assert _extract_pr_number("", "", spec, "") == 500


class TestBackwardCompat:
    """AC-11 — three-argument call still works."""

    def test_ac11_three_arg_call_works(self) -> None:
        # Existing call sites that don't pass `idea` continue to work via
        # the `idea: str = ""` default.
        pipe = "# Pipeline Status\n\n## Implement\n- PR: #777 squash `xyz` merged 2026-05-23\n"
        # Three-arg call (no `idea` keyword): must still return 777.
        assert _extract_pr_number(pipe, "", "") == 777


class TestEndToEnd:
    """AC-12 — `_load_implemented` end-to-end with an idea-only folder."""

    def test_ac12_load_implemented_extracts_from_idea_only_folder(self, tmp_path: Path) -> None:
        # Construct a real on-disk folder under `implemented_features/`
        # naming convention with only `idea.md` present.
        folder = tmp_path / "2026_05_20_chore_test_stub"
        folder.mkdir()
        (folder / "idea.md").write_text(_PRECEDENT_STATUS_IMPLEMENTED)
        feature = _load_implemented(folder)
        assert feature is not None
        assert feature.pr_number == 161


class TestMutualExclusion:
    """Pattern A and Pattern B cannot both match the same line.

    Implicit in their distinct `**Status:** **Shipped**` vs
    `**Status:** **Implemented`** prefixes; documenting prevents future
    ambiguity.
    """

    def test_pattern_a_and_b_share_no_lines(self) -> None:
        shipped_line = "**Status:** **Shipped** as PR #100"
        implemented_line = "**Status:** **Implemented — PR #200**"
        # Pattern A matches the Shipped line but NOT the Implemented line.
        assert _IDEA_STATUS_SHIPPED_RE.search(shipped_line) is not None
        assert _IDEA_STATUS_SHIPPED_RE.search(implemented_line) is None
        # Pattern B matches the Implemented line but NOT the Shipped line.
        assert _IDEA_STATUS_IMPLEMENTED_RE.search(implemented_line) is not None
        assert _IDEA_STATUS_IMPLEMENTED_RE.search(shipped_line) is None


class TestMetadataBlockHelper:
    """Direct unit coverage of `_extract_metadata_block` for FR-3."""

    def test_stops_at_first_heading(self) -> None:
        idea = "# Title\n\n**Date:** 2026-05-23\n**PR:** #1\n\n## Problem\n\n**PR:** #999\n"
        block = _extract_metadata_block(idea)
        assert "**PR:** #1" in block
        assert "**PR:** #999" not in block

    def test_stops_at_first_non_metadata_non_blank_line(self) -> None:
        idea = "# Title\n\n**Date:** 2026-05-23\nNarrative line ends the block.\n**PR:** #999\n"
        block = _extract_metadata_block(idea)
        assert "**Date:**" in block
        assert "**PR:** #999" not in block

    def test_30_line_cap_for_headingless_idea(self) -> None:
        # All-metadata-key idea with 40 lines — cap at 30.
        idea = "# Title\n" + "\n".join(f"**Key{i}:** value" for i in range(40))
        block = _extract_metadata_block(idea)
        # Block must be capped: line count cannot exceed 30.
        assert len(block.splitlines()) <= 30

    def test_later_h1_heading_does_not_extend_block(self) -> None:
        # Only the FIRST `# ` line counts as the title. A later H1 stops
        # the block, preventing a body `**PR:**` after it from matching.
        idea = (
            "# Title\n"
            "\n"
            "**Date:** 2026-05-23\n"
            "\n"
            "# Body H1 heading (rare but possible in malformed ideas)\n"
            "**PR:** #999\n"
        )
        block = _extract_metadata_block(idea)
        assert "**PR:** #999" not in block

    def test_h1_after_metadata_is_body_heading_not_title(self) -> None:
        # GPT-5.5 final-review regression: when an idea begins with
        # metadata lines (NO `# ` title), a later `# ` is a body
        # heading, not a title — must stop the block. Otherwise the
        # `**PR:**` line after the body heading would be incorrectly
        # included in the metadata-block search scope.
        idea = (
            "**Date:** 2026-05-23\n"
            "**Status:** Idea\n"
            "\n"
            "# Body H1 heading after metadata (no title at top)\n"
            "**PR:** #999\n"
        )
        block = _extract_metadata_block(idea)
        assert "**PR:** #999" not in block
        # End-to-end: _extract_pr_number must not return 999 either.
        assert _extract_pr_number("", "", "", idea) != 999

    def test_empty_idea_returns_empty(self) -> None:
        assert _extract_metadata_block("") == ""


class TestRegexConstants:
    """Lock the regex contracts that other tests depend on."""

    def test_metadata_key_pattern_matches_common_keys(self) -> None:
        # Common idea-template metadata keys must all match.
        for key in (
            "**Date:**",
            "**Status:**",
            "**Priority:**",
            "**Origin:**",
            "**Depends on:**",
            "**PR:**",
            "**Owners:**",
        ):
            assert _METADATA_KEY_RE.match(key) is not None, f"failed: {key}"

    def test_frontmatter_re_rejects_trailing_alphanum(self) -> None:
        # `\b` boundary must reject `**PR:** #99abc`.
        assert _IDEA_PR_FRONTMATTER_RE.search("**PR:** #99abc") is None
        assert _IDEA_PR_FRONTMATTER_RE.search("**PR:** #99") is not None


class TestBacktickStripPriority3:
    """Locks the false-positive rejection added by chore_dashboard_regen_quoted_pr_false_positive.

    Spec FR-3 / ACs 6-12. The priority-3 fuzzy regexes at
    scripts/build_mvp1_dashboard.py:629 and :632 must not match
    backtick-quoted PR-merge phrases, while still matching legitimate
    un-backticked own-PR prose (regression guard via AC-9).
    """

    def test_ac6_inline_backtick_quoted_merged_pr_returns_none(self) -> None:
        # Inline-backtick `merged ... PR #N` (second-regex order).
        spec = (
            "Some prose.\n\n"
            "Example: `**Depends on:** [infra_foundation] -- merged via PR #4 (2026-05-09)`\n\n"
            "More prose."
        )
        assert _extract_pr_number("", "", spec, "") is None

    def test_ac7_multiline_triple_backtick_block_with_merged_pr_returns_none(self) -> None:
        # Multi-line triple-backtick block whose body contains a merged-PR phrase.
        spec = "Header.\n\n```python\n# Example: see PR #99 (merged 2026-05-15)\n```\n\nFooter."
        assert _extract_pr_number("", "", spec, "") is None

    def test_ac8_inline_backtick_with_pr_first_then_merged_returns_none(self) -> None:
        # First-regex ordering: PR #N ... merged (complement of AC-6).
        spec = "Note: `PR #42 was merged on 2026-05-01` for context."
        assert _extract_pr_number("", "", spec, "") is None

    def test_ac9_unbacktickend_prose_own_pr_still_matches(self) -> None:
        # Regression guard: un-backticked own-PR prose still matches priority-3.
        spec = "## Status\n\nThis feature merged 2026-05-15 as PR #200 (squash)."
        assert _extract_pr_number("", "", spec, "") == 200

    def test_ac10_backtick_strip_runs_before_dependency_table_strip(self) -> None:
        # Verify the helpers compose correctly: backtick strip removes its
        # scope without touching dependency-table-row content (which the
        # sibling helper handles).
        text = "| foo | Implemented (PR #1) |\n\n`Example: merged via PR #99`\n\nMore."
        result = _strip_backtick_quoted_segments(text)
        assert "PR #99" not in result
        assert "| foo | Implemented (PR #1) |" in result

    def test_ac11_empty_backtick_segment_does_not_crash(self) -> None:
        # Empty inline `` and empty triple-backtick ```\n``` must be removed
        # without raising IndexError/TypeError/regex error.
        text = "before `` after\n```\n```\nfinal"
        result = _strip_backtick_quoted_segments(text)
        assert isinstance(result, str)
        # Empty inline span is removed.
        assert "``" not in result
        # Triple-backtick fence is removed.
        assert "```" not in result

    def test_ac12_single_line_triple_backtick_fence_returns_none(self) -> None:
        # Single-line ```...``` (no embedded newline). A regex matching only
        # ```\n...\n``` would miss this and produce a false positive.
        spec = "Inline example: ```PR #77 merged 2026-05-03``` for context."
        assert _extract_pr_number("", "", spec, "") is None
