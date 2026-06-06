# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Lock the pure helpers of scripts/reconcile_tracking_issues.py.

The network-touching paths (``gh`` subprocess) are validated by the in-repo
``--dry-run`` and the workflow itself; these tests pin the deterministic logic
that decides issue identity, dedup, label selection, and idea parsing — the
parts most likely to silently drift and either duplicate or mis-close an issue.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT))

from scripts.reconcile_tracking_issues import (  # noqa: E402
    build_body,
    identity_slug,
    labels_for,
    mentions_slug,
    parse_idea,
    prefix_of,
)


def test_identity_prefers_marker_over_title():
    issue = {
        "title": "Some plain English title",
        "body": "intro\n<!-- tracking-slug: bug_widget_explodes -->\nmore",
    }
    assert identity_slug(issue) == "bug_widget_explodes"


def test_identity_falls_back_to_title_prefix():
    issue = {"title": "feat_foo_bar: a nice summary", "body": "no marker here"}
    assert identity_slug(issue) == "feat_foo_bar"


def test_identity_none_for_plain_title_no_marker():
    # A legacy plain-titled issue with no marker has no derivable identity —
    # this is exactly why such issues need a backfilled marker.
    assert identity_slug({"title": "Fix the thing", "body": "prose only"}) is None


def test_mentions_slug_matches_body_substring():
    issue = {"title": "Plain title", "body": "see planned_features/02_mvp2/chore_x/idea.md"}
    assert mentions_slug(issue, "chore_x") is True
    assert mentions_slug(issue, "chore_y") is False


def test_prefix_of():
    assert prefix_of("infra_pr_yml_split") == "infra"
    assert prefix_of("bug_a") == "bug"


def test_labels_filter_to_existing_only():
    # mvp3 release label does not exist yet → it must be dropped, not break create.
    available = {"mvp2", "type/feature", "priority/P2", "needs-preflight"}
    got = labels_for("03_mvp3", "feat_x", "P2", available)
    assert "mvp3" not in got  # filtered (label absent)
    assert got == ["type/feature", "priority/P2", "needs-preflight"]


def test_labels_backlog_tier_maps_to_priority_backlog():
    available = {"mvp2", "type/chore", "priority/backlog", "needs-preflight"}
    got = labels_for("02_mvp2", "chore_x", "backlog", available)
    assert "mvp2" in got
    assert "priority/backlog" in got
    assert "priority/Backlog" not in got


def test_parse_idea_extracts_summary_and_tier(tmp_path: Path):
    folder = tmp_path / "chore_demo_thing"
    folder.mkdir()
    (folder / "idea.md").write_text(
        "# chore_demo_thing — Make the demo thing better\n\n"
        "**Date:** 2026-01-01\n"
        "**Priority:** Backlog — some rationale\n",
        encoding="utf-8",
    )
    summary, tier = parse_idea(folder, "chore_demo_thing")
    assert summary == "Make the demo thing better"
    assert tier == "backlog"


def test_parse_idea_p3_buckets_as_p2(tmp_path: Path):
    folder = tmp_path / "bug_x"
    folder.mkdir()
    (folder / "idea.md").write_text("# bug_x: title\n\n**Priority:** P3 (low)\n", encoding="utf-8")
    _, tier = parse_idea(folder, "bug_x")
    assert tier == "P2"  # dashboard convention: P3 buckets as P2


def test_build_body_contains_marker_and_artifact(tmp_path: Path):
    folder = _REPO_ROOT / "docs/00_overview/planned_features/02_mvp2/chore_x"
    body = build_body("02_mvp2", "chore_x", folder, "A summary", "P2")
    assert "<!-- tracking-slug: chore_x -->" in body
    assert "docs/00_overview/planned_features/02_mvp2/chore_x/idea.md" in body
    assert "**Stage:** IDEA" in body
