"""Tests for the DEPS_ALL_BACKEND time-ordered expansion in
``scripts/build_mvp1_dashboard.py``.

Covers the fix for
[bug_dashboard_depends_on_column_bloat](../../../../docs/02_product/planned_features/bug_dashboard_depends_on_column_bloat/idea.md):
shipped features that use the "ALL prior backend features" prose marker
must inherit only backend peers that merged on or before them — not the
full current-snapshot roster (which historically included features
shipped weeks later AND still-planned ideas).
"""

from __future__ import annotations

import sys
from pathlib import Path

# scripts/build_mvp1_dashboard.py is at the repo root, not on sys.path.
_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT))

from scripts.build_mvp1_dashboard import (  # noqa: E402
    DEPS_ALL_BACKEND,
    Feature,
    _expand_transitive_deps,
    _merge_order_key,
)


def _feat(
    folder: str,
    *,
    prefix: str,
    merged_date: str | None,
    pr_number: int | None = None,
    depends_on: list[str] | None = None,
) -> Feature:
    """Minimal Feature factory — only fields the expansion cares about."""
    return Feature(
        folder=folder,
        prefix=prefix,
        short_name=folder.split("_", 1)[1] if "_" in folder else folder,
        path=Path("/tmp") / folder,
        location="implemented" if merged_date else "planned",
        stage="done" if merged_date else "idea",
        status_line="Complete" if merged_date else "Idea",
        one_liner="test fixture",
        depends_on=list(depends_on) if depends_on else [],
        pr_number=pr_number,
        merged_date=merged_date,
    )


class TestExpandTransitiveDeps:
    def test_shipped_feature_only_inherits_earlier_backend_peers(self) -> None:
        """The canonical bloat case: feat_chat_agent shipped 2026-05-12 and
        must NOT inherit features that shipped after it (or planned ideas).
        """
        before = _feat("infra_foundation", prefix="infra", merged_date="2026-05-09", pr_number=4)
        same_day_earlier_pr = _feat(
            "feat_studies_ui", prefix="feat", merged_date="2026-05-12", pr_number=50
        )
        chat_agent = _feat(
            "feat_chat_agent",
            prefix="feat",
            merged_date="2026-05-12",
            pr_number=60,
            depends_on=[DEPS_ALL_BACKEND],
        )
        after = _feat(
            "feat_pr_metric_confidence", prefix="feat", merged_date="2026-05-21", pr_number=180
        )
        planned = _feat("feat_ubi_judgments", prefix="feat", merged_date=None)

        _expand_transitive_deps([before, same_day_earlier_pr, chat_agent, after, planned])

        assert chat_agent.depends_on == ["feat_studies_ui", "infra_foundation"]

    def test_planned_feature_inherits_full_backend_snapshot(self) -> None:
        """Planned features with the transitive marker keep current behavior —
        they genuinely depend on every backend sibling in the queue.
        """
        before = _feat("infra_foundation", prefix="infra", merged_date="2026-05-09", pr_number=4)
        shipped = _feat("feat_studies_ui", prefix="feat", merged_date="2026-05-12", pr_number=50)
        future = _feat(
            "feat_pr_metric_confidence", prefix="feat", merged_date="2026-05-21", pr_number=180
        )
        planned_target = _feat(
            "feat_some_planned_thing",
            prefix="feat",
            merged_date=None,
            depends_on=[DEPS_ALL_BACKEND],
        )

        _expand_transitive_deps([before, shipped, future, planned_target])

        assert planned_target.depends_on == [
            "feat_pr_metric_confidence",
            "feat_studies_ui",
            "infra_foundation",
        ]

    def test_explicit_deps_alongside_sentinel_are_preserved(self) -> None:
        """If a feature declares both explicit deps and the transitive marker,
        the explicit ones are unioned with the time-scoped expansion.
        """
        a = _feat("infra_foundation", prefix="infra", merged_date="2026-05-09", pr_number=4)
        b = _feat("feat_extra", prefix="feat", merged_date="2026-05-10", pr_number=10)
        target = _feat(
            "feat_target",
            prefix="feat",
            merged_date="2026-05-12",
            pr_number=20,
            depends_on=["infra_external_dep", DEPS_ALL_BACKEND],
        )

        _expand_transitive_deps([a, b, target])

        assert target.depends_on == ["feat_extra", "infra_external_dep", "infra_foundation"]

    def test_feature_without_sentinel_is_unchanged(self) -> None:
        """No DEPS_ALL_BACKEND → no expansion path runs; depends_on stays as-is."""
        a = _feat("infra_foundation", prefix="infra", merged_date="2026-05-09", pr_number=4)
        target = _feat(
            "feat_target",
            prefix="feat",
            merged_date="2026-05-12",
            pr_number=20,
            depends_on=["infra_foundation"],
        )

        _expand_transitive_deps([a, target])

        assert target.depends_on == ["infra_foundation"]

    def test_non_backend_prefixes_excluded_from_expansion(self) -> None:
        """The expansion only includes infra_*/feat_* peers — chore_/bug_/epic_
        are not part of the backend dependency surface.
        """
        infra = _feat("infra_foundation", prefix="infra", merged_date="2026-05-09", pr_number=4)
        chore = _feat(
            "chore_tutorial_polish", prefix="chore", merged_date="2026-05-12", pr_number=64
        )
        bug = _feat("bug_some_fix", prefix="bug", merged_date="2026-05-11", pr_number=55)
        target = _feat(
            "feat_chat_agent",
            prefix="feat",
            merged_date="2026-05-12",
            pr_number=60,
            depends_on=[DEPS_ALL_BACKEND],
        )

        _expand_transitive_deps([infra, chore, bug, target])

        # Only infra_foundation is included — bug_ and chore_ are excluded
        # by prefix even though they shipped first.
        assert target.depends_on == ["infra_foundation"]

    def test_self_dep_in_sentinel_expansion_is_dropped(self) -> None:
        """The pre-existing guard drops the feature's own folder from the
        sentinel-expansion side. Self-references that arrived via the
        EXPLICIT side of ``depends_on`` are preserved (pre-existing
        behavior — out of scope for this bug fix).
        """
        # Self-folder slips into the backend set; the sentinel expansion
        # must exclude it. The explicit self-reference is preserved.
        target = _feat(
            "feat_self",
            prefix="feat",
            merged_date="2026-05-12",
            pr_number=20,
            depends_on=["feat_self", DEPS_ALL_BACKEND],
        )

        _expand_transitive_deps([target])

        # No backend peers earlier than feat_self → expansion contributes
        # nothing. The explicit "feat_self" survives — pre-existing
        # behavior locked by this test, NOT changed by this fix.
        assert target.depends_on == ["feat_self"]


class TestMergeOrderKey:
    def test_earlier_date_sorts_first(self) -> None:
        a = _feat("a", prefix="feat", merged_date="2026-05-09", pr_number=4)
        b = _feat("b", prefix="feat", merged_date="2026-05-12", pr_number=60)
        assert _merge_order_key(a) < _merge_order_key(b)

    def test_same_date_lower_pr_sorts_first(self) -> None:
        a = _feat("a", prefix="feat", merged_date="2026-05-12", pr_number=50)
        b = _feat("b", prefix="feat", merged_date="2026-05-12", pr_number=60)
        assert _merge_order_key(a) < _merge_order_key(b)

    def test_missing_merge_date_sorts_after_shipped(self) -> None:
        shipped = _feat("a", prefix="feat", merged_date="2026-05-12", pr_number=60)
        planned = _feat("b", prefix="feat", merged_date=None)
        assert _merge_order_key(shipped) < _merge_order_key(planned)

    def test_missing_pr_sorts_after_shipped_same_day(self) -> None:
        with_pr = _feat("a", prefix="feat", merged_date="2026-05-12", pr_number=60)
        no_pr = _feat("b", prefix="feat", merged_date="2026-05-12", pr_number=None)
        assert _merge_order_key(with_pr) < _merge_order_key(no_pr)
