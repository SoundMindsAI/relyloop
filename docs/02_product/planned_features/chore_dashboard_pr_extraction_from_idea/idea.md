# Extend `_extract_pr_number` to read PR# from idea.md for legacy implemented features

**Date:** 2026-05-23
**Status:** Idea — surfaced during the tangential-observations sweep of `bug_dashboard_depends_on_column_bloat` (PR pending)
**Priority:** P2 — minor data gap; affects only same-day tiebreakers for early-shipped features without a `feature_spec.md` or `pipeline_status.md`. Practical impact is one or two missing edges in the dependency graph; not a correctness regression.
**Origin:** Investigating the post-fix dependency list for `feat_chat_agent` (10 entries down from 41), I noticed `infra_frontend_stack_refresh` (shipped 2026-05-12) was excluded. Root cause: it has no `feature_spec.md` / `pipeline_status.md` / `implementation_plan.md` — only `idea.md`. The regen script's `_extract_pr_number` at [`scripts/build_mvp1_dashboard.py:476`](../../../../scripts/build_mvp1_dashboard.py#L476) reads `pipe + plan + spec` looking for the PR#, so for idea-only features it returns `None`. With `pr_number=None`, the new `_merge_order_key` helper sorts the feature to end-of-day (key tuple `(date, 999999, folder)`), placing it AFTER same-day peers with concrete PR numbers. The fix's time-order filter then excludes it from those peers' `DEPS_ALL_BACKEND` expansion.
**Depends on:** [`bug_dashboard_depends_on_column_bloat`](../bug_dashboard_depends_on_column_bloat/idea.md) (must merge first — this is a polish layer on top of that fix).

## Problem

Several early MVP1 features shipped before the `/pipeline` ceremony solidified, leaving them with only an `idea.md` in `implemented_features/<date>_<slug>/`. Examples (as of 2026-05-23):

- `2026_05_12_infra_frontend_stack_refresh` — idea.md only
- `2026_05_13_chore_ci_gitleaks_workflow_step` — idea.md only
- `2026_05_13_chore_ci_gitignore_paths_ignore_gap` — idea.md only
- `2026_05_13_chore_cluster_delete_ui` — idea.md only
- `2026_05_13_infra_per_trial_timeout` — idea.md only
- `2026_05_13_infra_nvmrc` — idea.md only

(Plus several more from the same period — `find docs/00_overview/implemented_features/ -maxdepth 1 -type d -exec test '!' -f {}/feature_spec.md ';' -print`.)

For each of these, `_extract_pr_number(pipe, plan, spec)` is called with `pipe == plan == spec == ""` because the script never reads `idea.md`. The function returns `None`. Downstream effects:

1. **Dashboard "Status" column** — these features render as `Complete` (the fallback at line 652) instead of `[PR #N](url) merged YYYY-MM-DD`. Minor cosmetic loss.
2. **`DEPS_ALL_BACKEND` expansion tiebreaker** — these features sort to end-of-day in `_merge_order_key`. Same-day peers with PR numbers (e.g., `feat_chat_agent` PR #60, `chore_tutorial_polish` PR #64) exclude them from the transitive-deps expansion. Net effect on the dashboard: ~1 missing edge per affected legacy feature in the canonical `feat_chat_agent` / `chore_tutorial_polish` rows.

## Proposed fix

Extend `_extract_pr_number` to also accept an `idea` text argument (or add `idea` to the existing concat at the call site). Most legacy idea.md files cite their own PR# in the format `merged via PR #N` or `(PR #N)` somewhere in the body — the existing regex `r"PR[^a-zA-Z\n]{0,5}#(\d+)[^.\n]{0,80}merged"` would match if applied to the idea body.

- **Scope:** ~10 LOC in [`scripts/build_mvp1_dashboard.py`](../../../../scripts/build_mvp1_dashboard.py) — read `idea.md` in `_load_implemented`, pass it to `_extract_pr_number`. Update the function signature accordingly.
- **Tests:** 1 new test case in [`backend/tests/unit/scripts/test_dashboard_expand_transitive_deps.py`](../../../../backend/tests/unit/scripts/test_dashboard_expand_transitive_deps.py) (or a new test file for the loader) asserting an idea-only implemented feature gets its PR# extracted.
- **Verification:** after the fix, `infra_frontend_stack_refresh` should appear in `feat_chat_agent`'s `Depends on` column (it shipped before via PR earlier than #60, assuming the idea cites it).

## Why deferred

Not a correctness regression — the `bug_dashboard_depends_on_column_bloat` fix dramatically improves the dependency surface (41→10, 42→11 entries). The remaining ~1-edge data gap per legacy feature is operator-cosmetic, not a blocker for any planning workflow. Worth picking up when the next dashboard-quality sweep lands.

## Scope signals

- **Backend:** 0 LOC.
- **Scripts:** ~10 LOC in `scripts/build_mvp1_dashboard.py`.
- **Frontend:** 0 LOC.
- **Migration:** None.
- **Config:** None.
- **Audit events:** N/A.
- **Tests:** ~20 LOC test coverage.

## Relationship to other work

- **Predicated on [`bug_dashboard_depends_on_column_bloat`](../bug_dashboard_depends_on_column_bloat/idea.md)** — the time-order filter created the regression-surface for missing PR numbers. Without the bloat fix, the missing PR# had no visible effect (everything got expanded anyway).
- **Touches the same `_extract_pr_number` surface as the early dashboard work**. No conflicts; purely additive.
