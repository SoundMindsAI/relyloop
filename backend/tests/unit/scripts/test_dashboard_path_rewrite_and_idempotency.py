"""Tests for `_rewrite_markdown_links` + `_maybe_write` in scripts/build_mvp1_dashboard.py.

Covers the two fixes shipped via the
[`infra_dashboard_regen_pre_commit_conflict`](../../../../docs/00_overview/planned_features/infra_dashboard_regen_pre_commit_conflict/idea.md)
ad-hoc PR (§2 idempotency + §4 relative-link rewriting). Both surfaced
during the feat_judgments_periodic_resume_sweep + bug_query_inline_crud_...
shipping arc on 2026-05-14 — see the idea file for the full failure
analysis.
"""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/build_mvp1_dashboard.py is at the repo root, not on sys.path.
_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT))

from scripts.build_mvp1_dashboard import (  # noqa: E402
    _extract_idea_problem,
    _maybe_write,
    _rewrite_markdown_links,
)


class TestRewriteMarkdownLinks:
    """Path-rewriting from idea.md depth (5) → dashboard depth (2).

    Idea files live at ``docs/00_overview/planned_features/<bucket>/<folder>/idea.md``
    (the bucket is the MVP grouping: ``00_unsure/``, ``01_mvp1/``, ``02_mvp2/``,
    ``03_mvp3/``, ``04_ga/``, ``99_backlog/``); rendered dashboards live at
    ``docs/00_overview/MVP1_DASHBOARD.md`` and ``docs/00_overview/mvp1_dashboard.html``.
    A relative path ``../../../../../backend/foo`` correctly resolves to
    ``<repo>/backend/foo`` from the idea but resolves *outside* the repo when
    embedded in the dashboard. The rewriter recomputes paths to ``../../backend/foo``.
    """

    FROM_DIR = _REPO_ROOT / "docs/00_overview/planned_features/01_mvp1/some_folder"
    TO_DIR = _REPO_ROOT / "docs/00_overview"

    def test_idea_depth_to_dashboard_depth(self) -> None:
        """The canonical fix: 5 dot-dots in idea.md → 2 dot-dots in dashboard."""
        text = (
            "See [test_query_sets_router_queries.py:202]"
            "(../../../../../backend/tests/integration/"
            "test_query_sets_router_queries.py#L202-L231) "
            "for details."
        )
        rewritten = _rewrite_markdown_links(text, self.FROM_DIR, self.TO_DIR)
        assert (
            "[test_query_sets_router_queries.py:202]"
            "(../../backend/tests/integration/test_query_sets_router_queries.py#L202-L231)"
            in rewritten
        )

    def test_absolute_path_unchanged(self) -> None:
        """Repo-rooted paths like `/README.md` pass through (no rewriting needed)."""
        text = "See [readme](/README.md)."
        assert _rewrite_markdown_links(text, self.FROM_DIR, self.TO_DIR) == text

    def test_http_url_unchanged(self) -> None:
        text = "Check [PR #104](https://github.com/SoundMindsAI/relyloop/pull/104)."
        assert _rewrite_markdown_links(text, self.FROM_DIR, self.TO_DIR) == text

    def test_in_document_anchor_unchanged(self) -> None:
        """In-document anchors (e.g., `#section`) pass through — they're not paths."""
        text = "See [§9](#required-invariants)."
        assert _rewrite_markdown_links(text, self.FROM_DIR, self.TO_DIR) == text

    def test_mailto_link_unchanged(self) -> None:
        text = "Contact [the maintainer](mailto:eric.starr@soundminds.ai)."
        assert _rewrite_markdown_links(text, self.FROM_DIR, self.TO_DIR) == text

    def test_fragment_preserved_after_rewrite(self) -> None:
        """`#L42` fragment on a rewritten path survives the rewriting."""
        text = "See [line](../../../../../backend/foo.py#L42)."
        rewritten = _rewrite_markdown_links(text, self.FROM_DIR, self.TO_DIR)
        assert "[line](../../backend/foo.py#L42)" in rewritten

    def test_sibling_planned_folder_link(self) -> None:
        """`../sibling-folder/idea.md` rewrites correctly across the depth shift."""
        text = "See [sibling](../sibling-folder/idea.md)."
        rewritten = _rewrite_markdown_links(text, self.FROM_DIR, self.TO_DIR)
        # From dashboard at docs/00_overview/, the same-bucket sibling-folder
        # lives at planned_features/01_mvp1/sibling-folder/idea.md (the MVP
        # bucket is part of the path after the 2026-05-28 MVP-grouping
        # restructure).
        assert "[sibling](planned_features/01_mvp1/sibling-folder/idea.md)" in rewritten

    def test_multiple_links_in_one_text(self) -> None:
        """Multiple links in the same paragraph all get rewritten."""
        text = "See [a](../../../../../backend/a.py) and [b](../../../../../backend/b.py)."
        rewritten = _rewrite_markdown_links(text, self.FROM_DIR, self.TO_DIR)
        assert "[a](../../backend/a.py)" in rewritten
        assert "[b](../../backend/b.py)" in rewritten

    def test_extract_idea_problem_rewrites_paths(self) -> None:
        """End-to-end: `_extract_idea_problem` calls the rewriter when `idea_dir` is given."""
        path = "../../../../../backend/tests/integration/test_query_sets_router_queries.py"
        text = (
            "# Test idea\n\n"
            "## Problem\n\n"
            f"The test ([test_router.py:202]({path}#L202-L231)) seeds 5 queries.\n\n"
            "## Other section\n"
        )
        extracted = _extract_idea_problem(text, idea_dir=self.FROM_DIR)
        assert "../../backend/" in extracted
        assert "../../../../../" not in extracted

    def test_extract_idea_problem_without_idea_dir_unchanged(self) -> None:
        """Backward-compat: omitting `idea_dir` leaves paths alone (legacy callers)."""
        text = """# Test idea

## Problem

See [backend/foo](../../../../../backend/foo.py).
"""
        extracted = _extract_idea_problem(text)  # no idea_dir
        assert "../../../../../" in extracted


class TestMaybeWrite:
    """Idempotent file writes: only write when content actually differs."""

    def test_writes_when_file_does_not_exist(self, tmp_path: Path) -> None:
        target = tmp_path / "new.txt"
        assert _maybe_write(target, "hello") is True
        assert target.read_text(encoding="utf-8") == "hello"

    def test_writes_when_content_differs(self, tmp_path: Path) -> None:
        target = tmp_path / "existing.txt"
        target.write_text("old", encoding="utf-8")
        assert _maybe_write(target, "new") is True
        assert target.read_text(encoding="utf-8") == "new"

    def test_no_write_when_content_matches(self, tmp_path: Path) -> None:
        """The load-bearing assertion: pre-commit hashes content, so a no-op write
        on identical content would still register as "files modified by this hook"
        and block the commit. `_maybe_write` returning False means the path is
        untouched and pre-commit sees no diff."""
        target = tmp_path / "existing.txt"
        target.write_text("same", encoding="utf-8")
        # Record mtime before the no-op call.
        before_mtime = target.stat().st_mtime_ns
        assert _maybe_write(target, "same") is False
        # mtime must NOT advance — confirms no write call landed.
        assert target.stat().st_mtime_ns == before_mtime
