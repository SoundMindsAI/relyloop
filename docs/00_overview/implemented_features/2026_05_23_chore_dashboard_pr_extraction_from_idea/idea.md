# Extend `_extract_pr_number` to read PR# from idea.md for legacy implemented features

**Date:** 2026-05-23
**Status:** Idea — surfaced during the tangential-observations sweep of `bug_dashboard_depends_on_column_bloat` (PR pending)
**Priority:** P2 — minor data gap; affects only same-day tiebreakers for early-shipped features without a `feature_spec.md` or `pipeline_status.md`. Practical impact is one or two missing edges in the dependency graph; not a correctness regression.
**Origin:** Investigating the post-fix dependency list for `feat_chat_agent` (10 entries down from 41), I noticed `infra_frontend_stack_refresh` (shipped 2026-05-12) was excluded. Root cause: it has no `feature_spec.md` / `pipeline_status.md` / `implementation_plan.md` — only `idea.md`. The regen script's `_extract_pr_number` at [`scripts/build_mvp1_dashboard.py:499`](../../../../scripts/build_mvp1_dashboard.py#L499) (was L476 when this idea was drafted; +23 line drift since) reads `pipe + plan + spec` looking for the PR#, so for idea-only features it returns `None`. With `pr_number=None`, the new `_merge_order_key` helper at [`scripts/build_mvp1_dashboard.py:716`](../../../../scripts/build_mvp1_dashboard.py#L716) sorts the feature to end-of-day (key tuple `(merged_date, pr_number or 999_999, folder)`), placing it AFTER same-day peers with concrete PR numbers. The fix's time-order filter then excludes it from those peers' `DEPS_ALL_BACKEND` expansion.
**Depends on:** [`bug_dashboard_depends_on_column_bloat`](../../../00_overview/implemented_features/2026_05_23_bug_dashboard_depends_on_column_bloat/) — shipped 2026-05-23 as PR #208 (squash `8bb7148`). The time-order filter introduced by that fix created the regression-surface where missing PR numbers became visible.

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

Extend `_extract_pr_number` to also accept an `idea` text argument (or add `idea` to the existing concat at the call site), and have `_load_implemented` at [`scripts/build_mvp1_dashboard.py:661`](../../../../scripts/build_mvp1_dashboard.py#L661) read `idea.md` and pass it through.

**⚠️ Audit finding (added 2026-05-23 preflight):** The original idea's premise — "most legacy idea.md files cite their own PR# in the format `merged via PR #N` or `(PR #N)` somewhere in the body" — does **not** hold up when surveyed against the actual ~50 idea-only legacy features under `implemented_features/`. Out of that population:

- **Most (~35) have no own-PR mention at all** in the idea body.
- **A few (~5–8) have own-PR mentions in usable form**, e.g., `**Status:** **Shipped** as PR #N`, `**shipped … as PR #N**`, `**Implemented — PR #N**`.
- **Many (~10) mention OTHER features' PRs** — dependencies (`merged via PR #4` for `infra_foundation`), parent features that surfaced the idea (`PR #50` for `feat_studies_ui`), siblings that already merged. A naive `merged`-context regex against the idea body would extract these false positives.

A simple "pass idea text through the existing regex" approach therefore needs hardening or augmentation. See `Open questions for /spec-gen` §1 below for the locked default and alternatives.

- **Scope:** ~30–40 LOC in [`scripts/build_mvp1_dashboard.py`](../../../../scripts/build_mvp1_dashboard.py) — read `idea.md` in `_load_implemented`, pass it through `_extract_pr_number`, with the strict-pattern + frontmatter-fallback logic decided in §1.
- **Tests:** ~3–5 new test cases in [`backend/tests/unit/scripts/test_dashboard_expand_transitive_deps.py`](../../../../backend/tests/unit/scripts/test_dashboard_expand_transitive_deps.py) (or a dedicated `test_dashboard_pr_extraction.py`) covering: (1) idea-only feature with `**Status:** ... PR #N` pattern → extracted; (2) idea-only feature mentioning ONLY a dependency PR → returns `None` (no false positive); (3) idea-only feature with `**PR:**` frontmatter field → extracted; (4) own-PR + dependency-PR both present → own-PR wins; (5) existing `_load_implemented` behavior unchanged for features with `pipeline_status.md` (regression lock).
- **Verification:** after the fix, run `make dashboard` and grep for the affected legacy features in the regenerated `MVP1_DASHBOARD.md`'s shipped table — features with extractable PRs should show `[PR #N](url) merged YYYY-MM-DD` instead of `Complete`. Same-day peers' `DEPS_ALL_BACKEND` expansions should include the legacy feature where applicable.

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

## Open questions for /spec-gen

These need spec-time decisions. Each has a recommended default so /spec-gen doesn't start from zero.

1. **PR# extraction strategy for idea-only legacy features.** The original idea proposed running the existing `merged`-context regex against `idea.md`. The preflight survey showed this would produce false positives (extracting dependency PR# instead of own PR#) for ~10 features and silently miss ~35 others. Three options:
   - **(a, recommended) Strict-pattern-only extraction.** Only match patterns that strongly assert "this is THIS feature's PR": `^\*\*Status:\*\*\s+\*\*Shipped\*\*\s+as\s+PR\s*#(\d+)`, `^\*\*Status:\*\*\s+\*\*Implemented\s*—\s*PR\s*#(\d+)`, `\*\*shipped\s+[0-9-]+\s+as\s+PR\s*#(\d+)\*\*`. These line patterns appear in ~5–8 legacy idea files (`chore_precommit_node_path_resolution`, `chore_data_table_columnvisibility_tanstack`, `chore_create_study_modal_e2e_stability`, `feat_contextual_help_mvp2`, possibly others). They never appear in dependency or sibling cites because those don't carry the `**Status: Shipped/Implemented**` markers. Captures ~10–15% of the affected population — a real improvement over the current 0% — without introducing false positives.
   - **(b) Add a `**PR:**` frontmatter field convention** and backfill the ~50 idea-only legacy features. 100% reliable but ~50 edits per legacy feature × N PRs to backfill ~= scope creep that drowns out the chore.
   - **(c) Combine: strict patterns first, then optional `**PR:**` frontmatter field fallback.** Best of both — strict patterns are cheap and catch the natural cases for free; `**PR:**` provides an escape hatch for truly silent legacy ideas without forcing a 50-feature backfill. The convention can be applied opportunistically when someone touches a legacy idea for another reason.

   **Recommendation: (c).** Ship the strict-pattern extraction now; document the `**PR:**` frontmatter convention in the chore's spec for future opportunistic backfills. Cost is ~10 LOC of additional logic over (a) and prevents future "we need to add PR# extraction for legacy features" being a NEW chore.

2. **Should the chore backfill any specific legacy features in the same PR?** The chore's main value is the extraction logic. Backfilling specific legacy features is a separate-but-related operation. Two options:
   - **(a, recommended) No backfill in this chore.** Ship the extraction logic + `**PR:**` frontmatter convention. Legacy features get fixed opportunistically by future work that touches their folders. Keeps the chore narrowly scoped and reviewable.
   - **(b) Backfill the 5–6 features cited in §"Problem" as examples.** Adds ~10 LOC across 6 idea.md files. Acceptable scope creep if the operator agrees to bundle.

   **Recommendation: (a).** This chore is about extraction logic; backfill is its own scope.

3. **Should `_extract_pr_number` priority change?** The existing function has 4 priorities (pipeline_status.md `## Implement`, plan `**Status:**` header, `merged`-context fuzzy match, last-resort `#N`). Where does idea.md insert?
   - **(a, recommended) After (3) `merged`-context fuzzy match, before (4) last-resort.** The strict patterns identified in §1 are reliable enough to beat the last-resort fallback but should yield to pipe/plan if those exist (a feature with both `pipeline_status.md` AND `idea.md` should trust the canonical artifact, not the historical idea).
   - **(b) New priority 0, beats everything.** Wrong — would defeat the purpose of having pipeline_status.md as the authoritative source.

   **Recommendation: (a).** Strict idea patterns slot between fuzzy-merge and last-resort.

## Relationship to other work

- **Predicated on [`bug_dashboard_depends_on_column_bloat`](../../../00_overview/implemented_features/2026_05_23_bug_dashboard_depends_on_column_bloat/)** (shipped 2026-05-23 as PR #208 squash `8bb7148`) — the time-order filter created the regression-surface for missing PR numbers. Without the bloat fix, the missing PR# had no visible effect (everything got expanded anyway).
- **Touches the same `_extract_pr_number` surface as the early dashboard work**. No conflicts; purely additive.
- **Composes with `chore_dashboard_classifier_half_step_releases`** ([shipped 2026-05-23 as PR #211 squash `ab8674a`](../../../00_overview/implemented_features/2026_05_23_bug_dashboard_classifier_half_step_releases/)) — that chore tightened the release-classifier; this one tightens the PR-extractor. Both are quality polishes on the same regen surface.
