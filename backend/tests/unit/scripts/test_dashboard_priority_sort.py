# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Lock the canonical Idea-table sort key in scripts/build_mvp1_dashboard.py.

The order is documented in two places that MUST stay in sync:

* `_md_sort_key` (markdown renderer) at ``scripts/build_mvp1_dashboard.py:~1799``
* `.claude/skills/pipeline/SKILL.md` § "Project-wide status mode" Algorithm step 3

If you change the tiebreaker on either side, update both — and update this
test. The whole point of the test is to make silent drift impossible.

Canonical sort tuple: ``(priority_value, type_order[prefix], short_name)`` —
priority tier first (P0 < P1 < P2 < Backlog), then prefix order
(feat → infra → epic → chore → bug; ``type_order = {"feat": 0, "infra": 1,
"epic": 2, "chore": 3, "bug": 4}``), then alphabetical by short_name.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT))

from scripts.build_mvp1_dashboard import (  # noqa: E402
    DEFAULT_PRIORITY,
    Feature,
    render_markdown,
)


def _feat(folder: str, *, priority: str = DEFAULT_PRIORITY, stage: str = "idea") -> Feature:
    """Minimal Feature factory for sort-key tests."""
    prefix, short = folder.split("_", 1)
    return Feature(
        folder=folder,
        prefix=prefix,
        short_name=short,
        path=Path("/tmp") / folder,
        location="planned",
        stage=stage,
        status_line="Idea",
        one_liner="test fixture one-liner",
        depends_on=[],
        priority=priority,
    )


def _idea_rows(md: str) -> list[str]:
    """Pull `| N | Priority | feature_link | ...` data rows out of the rendered Idea table.

    Skips the header row (`| # | Priority | …`) and the separator row
    (`|---|---|…`, which doesn't match `"| "` because it has no space
    after the pipe — already excluded by the startswith filter below).
    Returns data rows only — those that start `| <digit>`.
    """
    lines = md.splitlines()
    in_idea = False
    rows: list[str] = []
    for line in lines:
        if line.startswith("### Idea ("):
            in_idea = True
            continue
        if in_idea and line.startswith("## "):
            break
        # Match data rows: `| <digit> | ...`. Excludes the header (`| # |`)
        # and the separator (`|---|...` — no space after the first pipe).
        if in_idea and len(line) >= 3 and line.startswith("| ") and line[2].isdigit():
            rows.append(line)
    return rows


class TestIdeaTableSort:
    def test_priority_tier_dominates_prefix_and_name(self) -> None:
        """P0 wins over P1 wins over P2 wins over Backlog regardless of
        prefix or alphabetical position.
        """
        features = [
            _feat("bug_aaa_first_alphabetically", priority="Backlog"),
            _feat("chore_zzz_last_alphabetically", priority="P0"),
            _feat("feat_middle_alphabetically", priority="P2"),
            _feat("infra_other", priority="P1"),
        ]
        md = render_markdown(features)
        rows = _idea_rows(md)
        # Expected order: P0 chore_zzz, P1 infra_other, P2 feat_middle, Backlog bug_aaa
        assert "chore_zzz_last_alphabetically" in rows[0]
        assert "infra_other" in rows[1]
        assert "feat_middle_alphabetically" in rows[2]
        assert "bug_aaa_first_alphabetically" in rows[3]

    def test_within_tier_prefix_order_is_feat_infra_epic_chore_bug(self) -> None:
        """All same priority; prefix order is the documented canonical sort."""
        features = [
            _feat("bug_alpha", priority="P2"),
            _feat("chore_alpha", priority="P2"),
            _feat("epic_alpha", priority="P2"),
            _feat("infra_alpha", priority="P2"),
            _feat("feat_alpha", priority="P2"),
        ]
        md = render_markdown(features)
        rows = _idea_rows(md)
        prefixes_in_order = ["feat_alpha", "infra_alpha", "epic_alpha", "chore_alpha", "bug_alpha"]
        for expected, row in zip(prefixes_in_order, rows, strict=True):
            assert expected in row, f"Expected {expected} at this row position; got: {row[:100]}"

    def test_within_prefix_alphabetical_by_short_name(self) -> None:
        """Same priority + same prefix → alphabetical by the part after the prefix."""
        features = [
            _feat("feat_zebra", priority="P2"),
            _feat("feat_apple", priority="P2"),
            _feat("feat_mango", priority="P2"),
        ]
        md = render_markdown(features)
        rows = _idea_rows(md)
        assert "feat_apple" in rows[0]
        assert "feat_mango" in rows[1]
        assert "feat_zebra" in rows[2]

    def test_idea_table_has_ordinal_column(self) -> None:
        """The `#` column must be present so the dashboard's row order is
        machine-extractable, not just visually implied.
        """
        features = [_feat("feat_only", priority="P2")]
        md = render_markdown(features)
        # Header row must include `#` before `Priority`.
        assert "| # | Priority | Feature | Type | One-liner | Depends on | Status |" in md
        # The single row must start `| 1 |`.
        rows = _idea_rows(md)
        assert rows[0].startswith("| 1 |"), f"Expected ordinal `1` first; got: {rows[0][:60]}"

    def test_ordinals_are_contiguous(self) -> None:
        """`#` column is 1..N with no gaps, regardless of tier mix."""
        features = [
            _feat("feat_a", priority="P0"),
            _feat("infra_a", priority="P1"),
            _feat("chore_a", priority="P2"),
            _feat("bug_a", priority="Backlog"),
        ]
        md = render_markdown(features)
        rows = _idea_rows(md)
        for expected, row in enumerate(rows, start=1):
            assert row.startswith(f"| {expected} |"), (
                f"Expected ordinal {expected}; got: {row[:30]}"
            )
