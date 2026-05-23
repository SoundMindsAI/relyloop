"""Lock the release classifier in scripts/build_mvp1_dashboard.py.

Covers the fix for
[bug_dashboard_classifier_half_step_releases](../../../../docs/02_product/planned_features/bug_dashboard_classifier_half_step_releases/idea.md):
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
    _target_release,
)


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
