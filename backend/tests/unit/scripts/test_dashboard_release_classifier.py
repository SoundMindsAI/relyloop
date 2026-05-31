# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Lock the release classifier in scripts/build_mvp1_dashboard.py.

Covers the fix for
[bug_dashboard_classifier_half_step_releases](../../../../docs/00_overview/planned_features/bug_dashboard_classifier_half_step_releases/idea.md):
the classifier must recognize half-step release tags (MVP1.5, MVP2.5, …)
from both the folder-suffix form (`_mvp1_5`) and the status-line form
(`anchor feature for MVP1.5`, `Held for MVP1.5`). The dashboard rendered
filename for half-step releases must use underscore-form (`MVP1_5_DASHBOARD.md`,
not `MVP1.5_DASHBOARD.md`).
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT))

from scripts.build_mvp1_dashboard import (  # noqa: E402
    DEFAULT_RELEASE,
    Feature,
    _dashboard_paths,
    _extract_explicit_release,
    _load_implemented,
    _load_planned,
    _release_filename_safe,
    _target_release,
)


class TestTargetReleaseBucket:
    """The bucket folder is the authoritative release signal — overrides
    suffix and status-line. Locks in the contract added when the
    operator-curated bucket layout (``01_mvp1/`` / ``02_mvp2/`` / ...)
    was promoted to the primary organization (2026-05-28)."""

    def test_bucket_routes_to_release(self) -> None:
        assert _target_release("foo", "", bucket="01_mvp1") == "mvp1"
        assert _target_release("foo", "", bucket="02_mvp2") == "mvp2"
        assert _target_release("foo", "", bucket="03_mvp3") == "mvp3"
        assert _target_release("foo", "", bucket="04_ga") == "ga"

    def test_backlog_bucket_uses_sentinel_tag(self) -> None:
        """``99_backlog`` / ``00_unsure`` map to sentinel release tags
        (``"backlog"`` / ``"unsure"``) that are NOT in ROADMAP_RELEASES,
        so those features don't fall through to the default-MVP1 bucket
        and don't appear on release dashboards."""
        assert _target_release("foo", "", bucket="99_backlog") == "backlog"
        assert _target_release("foo", "", bucket="00_unsure") == "unsure"

    def test_bucket_wins_over_status_line(self) -> None:
        """Operator filing under ``01_mvp1/`` overrides a stale ``Held for MVP2``
        status line. Prevents the historical drift where a feature's status line
        was updated independent of its folder location."""
        assert (
            _target_release("foo", "Held for MVP2 (decided 2026-05-13)", bucket="01_mvp1") == "mvp1"
        )

    def test_bucket_wins_over_folder_suffix(self) -> None:
        """Folder filed under ``02_mvp2/`` with a legacy ``_mvp3`` suffix
        classifies to mvp2 (the bucket, the operator's current intent)."""
        assert _target_release("foo_mvp3", "", bucket="02_mvp2") == "mvp2"

    def test_no_bucket_falls_through_to_existing_signals(self) -> None:
        """When bucket is None or an unrecognized folder name, the suffix +
        status-line cascade still applies (preserves the legacy contract for
        non-bucketed paths used by tests + edge cases)."""
        assert _target_release("foo_mvp2", "", bucket=None) == "mvp2"
        assert _target_release("foo", "Held for MVP3", bucket=None) == "mvp3"
        assert _target_release("regular", "", bucket="feature_templates") == DEFAULT_RELEASE


class TestTargetReleaseSuffix:
    def test_integer_suffix_still_classifies_correctly(self) -> None:
        """Regression: pre-fix behavior preserved for ``_mvp2`` / ``_mvp3``."""
        assert _target_release("arq_subprocess_test_mvp2", "") == "mvp2"
        assert _target_release("foo_bar_mvp3", "") == "mvp3"

    def test_half_step_suffix_classifies_as_decimal(self) -> None:
        """``_mvp1_5`` folder suffix → ``mvp1.5`` release tag (underscore-to-dot)."""
        assert _target_release("foo_mvp1_5", "") == "mvp1.5"
        assert _target_release("some_feature_mvp2_5", "") == "mvp2.5"

    def test_no_suffix_no_status_falls_back_to_default(self) -> None:
        assert _target_release("regular_feature", "") == DEFAULT_RELEASE
        assert (
            _target_release("regular_feature", "Complete - shipped 2026-05-12") == DEFAULT_RELEASE
        )


class TestTargetReleaseStatusLine:
    def test_held_for_integer_release_still_classifies(self) -> None:
        """Regression: ``**Status:** Held for MVP2`` keeps working."""
        assert _target_release("foo", "Held for MVP2 (decided 2026-05-13)") == "mvp2"

    def test_held_for_half_step_release_classifies(self) -> None:
        """``Held for MVP1.5`` now recognized (was rejected pre-fix because the
        old regex only matched integer release tags).
        """
        assert _target_release("foo", "Held for MVP1.5 (decided 2026-05-23)") == "mvp1.5"

    def test_anchor_feature_for_half_step_classifies(self) -> None:
        """The canonical bug case: ``feat_ubi_judgments``'s status line is
        ``Idea — anchor feature for MVP1.5 / v0.1.5 "Real Signals"``.
        """
        line = 'Idea — anchor feature for MVP1.5 / v0.1.5 "Real Signals"'
        assert _target_release("foo", line) == "mvp1.5"

    def test_anchor_for_integer_release_classifies(self) -> None:
        """``anchor for MVP3`` (no "feature") also valid framing."""
        assert _target_release("foo", "Idea — anchor for MVP3 release") == "mvp3"

    def test_suffix_wins_over_status_line(self) -> None:
        """Pre-fix invariant preserved: folder-suffix is authoritative."""
        assert _target_release("foo_mvp2", "Held for MVP3") == "mvp2"
        assert _target_release("foo_mvp1_5", "Held for MVP2") == "mvp1.5"

    def test_status_line_body_prose_not_matched(self) -> None:
        """The classifier reads ONLY the parsed status_line, not body prose.
        This guards the regression where a feature folder whose body quotes
        release-tag phrases as documentation examples (e.g. this bug's idea.md
        cites "anchor feature for MVP1.5") gets misclassified.

        Caller (``_load_planned``) passes status_line only; that's the
        contract the classifier locks in.
        """
        # The status line itself doesn't carry a release marker — even though
        # the body would, if scanned. Default applies.
        line = "Idea — surfaced when /pipeline status ranked X as #1"
        assert _target_release("foo", line) == DEFAULT_RELEASE


class TestExtractExplicitRelease:
    """The explicit ``**Release:** mvpN`` marker — the deterministic,
    flat-folder-surviving release signal stamped at finalization. Closes the
    gap where a shipped MVP2 feature (e.g. ``feat_ubi_judgments``,
    ``infra_adapter_solr``) moved into the bucket-less ``implemented_features/``
    tree fell back to MVP1 because its only release cue lived in idea-body prose
    that the status-line-scoped classifier deliberately ignores.
    """

    def test_parses_integer_release(self) -> None:
        assert _extract_explicit_release("**Release:** mvp2") == "mvp2"
        assert _extract_explicit_release("foo\n**Release:** mvp3\nbar") == "mvp3"

    def test_normalizes_half_step_underscore_to_dot(self) -> None:
        assert _extract_explicit_release("**Release:** mvp1_5") == "mvp1.5"

    def test_case_insensitive_and_backtick_tolerant(self) -> None:
        assert _extract_explicit_release("**Release:** MVP2") == "mvp2"
        assert _extract_explicit_release("**Release:** `mvp2`") == "mvp2"

    def test_sentinel_tags(self) -> None:
        assert _extract_explicit_release("**Release:** backlog") == "backlog"
        assert _extract_explicit_release("**Release:** ga") == "ga"

    def test_absent_marker_returns_none(self) -> None:
        assert _extract_explicit_release("no marker here") is None
        assert _extract_explicit_release("") is None

    def test_body_prose_mention_does_not_match(self) -> None:
        """Only the dedicated ``**Release:**`` line matches — a prose sentence
        mentioning a release in passing must NOT be picked up (mirrors the
        status-line-only discipline of the rest of the classifier)."""
        assert _extract_explicit_release("This ships in the MVP2 release.") is None
        assert _extract_explicit_release("Release of mvp2 is imminent") is None


class TestTargetReleaseExplicitMarker:
    def test_explicit_release_wins_over_suffix_and_status(self) -> None:
        """The explicit marker is the flat-folder equivalent of the bucket:
        it overrides both the folder suffix and the prose status line."""
        assert _target_release("foo", "Held for MVP3", explicit_release="mvp2") == "mvp2"
        assert _target_release("foo_mvp3", "", explicit_release="mvp2") == "mvp2"

    def test_bucket_still_wins_over_explicit(self) -> None:
        """A live bucket (operator-curated, most recent) beats the explicit
        marker — only flattened implemented features lose their bucket."""
        assert _target_release("foo", "", bucket="01_mvp1", explicit_release="mvp2") == "mvp1"

    def test_no_explicit_marker_preserves_legacy_cascade(self) -> None:
        assert _target_release("foo_mvp2", "", explicit_release=None) == "mvp2"
        assert _target_release("foo", "Held for MVP3", explicit_release=None) == "mvp3"
        assert _target_release("foo", "", explicit_release=None) == DEFAULT_RELEASE


class TestLoadImplementedRelease:
    """End-to-end at the ``_load_implemented`` caller: a shipped feature with a
    bucket-less folder name, a ``Complete`` stage line, and a ``**Release:**``
    marker in its pipeline_status must classify to the marked release — the
    exact infra_adapter_solr / feat_ubi_judgments case.
    """

    def _make(self, tmp_path: Path, *, pipeline_extra: str = "") -> Feature | None:
        folder = tmp_path / "2026_05_31_feat_some_shipped"
        folder.mkdir()
        (folder / "pipeline_status.md").write_text(
            "# Pipeline Status — Some Shipped Feature\n"
            f"{pipeline_extra}"
            "\n## Implementation\n- Status: Complete (PR #999)\n"
        )
        (folder / "feature_spec.md").write_text(
            "# Some Shipped Feature\n**Status:** Approved\nOne-liner here.\n"
        )
        return _load_implemented(folder)

    def test_explicit_release_marker_classifies_mvp2(self, tmp_path: Path) -> None:
        f = self._make(tmp_path, pipeline_extra="\n**Release:** mvp2\n")
        assert f is not None
        assert f.release == "mvp2"
        # The release marker drives classification only — it must NOT leak into
        # the human-facing display status line.
        assert "mvp2" not in f.status_line.lower()
        assert "Release" not in f.status_line

    def test_no_marker_falls_back_to_mvp1(self, tmp_path: Path) -> None:
        f = self._make(tmp_path)
        assert f is not None
        assert f.release == DEFAULT_RELEASE


class TestDashboardPaths:
    def test_integer_release_paths_use_uppercase_md(self) -> None:
        """Regression: ``mvp1`` → ``mvp1_dashboard.html`` + ``MVP1_DASHBOARD.md``."""
        html, md = _dashboard_paths("mvp1")
        assert html.name == "mvp1_dashboard.html"
        assert md.name == "MVP1_DASHBOARD.md"

    def test_half_step_release_paths_normalize_dot_to_underscore(self) -> None:
        """``mvp1.5`` → ``mvp1_5_dashboard.html`` + ``MVP1_5_DASHBOARD.md``.
        Dots in filenames are legal but read confusably (like file extensions).
        """
        html, md = _dashboard_paths("mvp1.5")
        assert html.name == "mvp1_5_dashboard.html"
        assert md.name == "MVP1_5_DASHBOARD.md"

    def test_higher_half_step_release_also_works(self) -> None:
        """``mvp2.5`` future-proofing."""
        html, md = _dashboard_paths("mvp2.5")
        assert html.name == "mvp2_5_dashboard.html"
        assert md.name == "MVP2_5_DASHBOARD.md"


class TestReleaseFilenameSafe:
    """Single point of truth for dot→underscore normalization used by
    both the file-write path (``_dashboard_paths``) AND every link
    renderer (``render_markdown`` "rich local view" callout, the two
    roadmap renderers). PR #211 cycle 1 shipped broken links because
    only the file-write path was normalized; this helper exists to
    prevent that drift from recurring.
    """

    def test_integer_release_unchanged(self) -> None:
        assert _release_filename_safe("mvp1") == "mvp1"
        assert _release_filename_safe("mvp2") == "mvp2"
        assert _release_filename_safe("ga") == "ga"

    def test_half_step_dot_normalized_to_underscore(self) -> None:
        assert _release_filename_safe("mvp1.5") == "mvp1_5"
        assert _release_filename_safe("mvp2.5") == "mvp2_5"

    def test_dashboard_paths_uses_safe_form(self) -> None:
        """File-write site uses the helper — regression guard."""
        html, md = _dashboard_paths("mvp1.5")
        # `stem` strips the file extension; only the dashboard name part
        # should be free of dots (the `.html` / `.md` extension always has one).
        assert "." not in html.stem
        assert "." not in md.stem

    def test_no_raw_release_tag_in_link_renderers(self) -> None:
        """Every link site must use ``_release_filename_safe`` so on-disk
        filenames and inline hrefs converge. This test reads the script
        source and asserts the bare-release-tag forms ``f"{release}_dashboard.html"``
        and ``f"{release_tag}_dashboard.html"`` no longer appear in the
        href-construction paths.

        Sentinel regression for the Gemini #2 finding on PR #211 cycle 1.
        """
        source = Path(_REPO_ROOT / "scripts" / "build_mvp1_dashboard.py").read_text()
        # Forbidden: raw {release}_dashboard.html or {release.upper()}_DASHBOARD.md
        # without going through _release_filename_safe first.
        forbidden_patterns = [
            'f"{release}_dashboard.html"',
            'f"{release_tag}_dashboard.html"',
            'f"{release.upper()}_DASHBOARD.md"',
            'f"{release_tag.upper()}_DASHBOARD.md"',
        ]
        for pattern in forbidden_patterns:
            assert pattern not in source, (
                f"Found `{pattern}` in build_mvp1_dashboard.py — link/file paths "
                "must go through _release_filename_safe() to keep dot-form "
                "release tags (e.g. 'mvp1.5') and underscore-form filenames "
                "(e.g. 'mvp1_5_dashboard.html') in sync."
            )


class TestLoadPlannedReleaseScoping:
    """Lock the caller contract at ``_load_planned`` (not just the helper).

    The classifier helper ``_target_release`` is fed ONLY the parsed
    ``status_line``, not the full idea body. If a future edit reverts
    that decision (concatenating ``status_line + " " + idea`` as the
    pre-fix code did), a feature whose body quotes release-tag phrases
    as documentation examples would get misclassified. These tests
    exercise the actual ``_load_planned`` path on disk so the regression
    surface includes the caller, not just the helper.
    """

    def test_body_prose_does_not_drive_release(self, tmp_path: Path) -> None:
        """Idea body cites ``anchor feature for MVP1.5`` as documentation,
        but the **Status:** line carries no release marker. Result must
        be ``DEFAULT_RELEASE``, NOT ``mvp1.5``.

        This is the canonical regression case from PR #211 — the bug
        folder's own idea.md quoted ``anchor feature for MVP1.5`` as an
        example of the regex pattern it documents; without scoping the
        classifier to the status line only, the bug folder got self-
        classified as MVP1.5.
        """
        folder = tmp_path / "bug_some_doc_example"
        folder.mkdir()
        (folder / "idea.md").write_text(
            "# Some doc example\n"
            "\n"
            "**Date:** 2026-05-23\n"
            "**Status:** Idea — surfaced during a code review\n"
            "**Priority:** P2\n"
            "**Depends on:** None\n"
            "\n"
            "## Problem\n"
            "\n"
            "The classifier needs to match `anchor feature for MVP1.5` "
            "and `Held for MVP1.5` and `Held for MVP2.5`. "
            "These are documentation examples, NOT this feature's release scope.\n"
        )
        feature = _load_planned(folder)
        assert feature is not None
        assert feature.release == DEFAULT_RELEASE, (
            f"Body prose containing `anchor feature for MVP1.5` must NOT drive release "
            f"classification — got {feature.release!r}. The classifier is supposed to "
            f"read only the parsed status_line, not the full idea body. If this test "
            f"fails after a regression that reverts _load_planned line 649 back to "
            f"`status_line + ' ' + (idea or '')`, restore the status_line-only scope."
        )

    def test_status_line_release_marker_still_classified(self, tmp_path: Path) -> None:
        """The status-line-only scoping must not break the legitimate path
        where the **Status:** line itself carries the release marker.
        """
        folder = tmp_path / "feat_some_anchor"
        folder.mkdir()
        (folder / "idea.md").write_text(
            "# Some anchor feature\n"
            "\n"
            "**Date:** 2026-05-23\n"
            '**Status:** Idea — anchor feature for MVP1.5 / v0.1.5 "Real Signals"\n'
            "**Priority:** P1\n"
            "**Depends on:** None\n"
            "\n"
            "## Problem\n"
            "\n"
            "Body content unrelated to release classification.\n"
        )
        feature = _load_planned(folder)
        assert feature is not None
        assert feature.release == "mvp1.5"


class TestFeatureDisplayName:
    def _feat(self, folder: str) -> Feature:
        prefix, short = folder.split("_", 1)
        return Feature(
            folder=folder,
            prefix=prefix,
            short_name=short,
            path=Path("/tmp") / folder,
            location="planned",
            stage="idea",
            status_line="Idea",
            one_liner="test",
        )

    def test_strips_integer_mvp_suffix(self) -> None:
        """Regression: ``_mvp2`` suffix doesn't double-print on cards."""
        f = self._feat("infra_arq_subprocess_test_mvp2")
        # display_name removes the suffix and titles the rest
        assert "Mvp2" not in f.display_name
        assert "Arq Subprocess Test" in f.display_name

    def test_strips_half_step_mvp_suffix(self) -> None:
        """The half-step ``_mvp1_5`` suffix also gets stripped from the
        display name so cards don't read ``Foo Mvp1 5``.
        """
        f = self._feat("feat_foo_mvp1_5")
        assert "Mvp1 5" not in f.display_name
        assert "Foo" in f.display_name
