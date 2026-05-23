# Bug fix — dashboard_classifier_half_step_releases

**Source idea:** [idea.md](./idea.md)
**Branch:** `bug/dashboard-classifier-missing-mvp1-5` (folder renamed mid-fix from `bug_dashboard_classifier_missing_mvp1_5` — see idea.md folder-name note)
**Type:** bug fix — medium (~30 LOC fix + 14-case regression test, single subsystem: scripts/build_mvp1_dashboard.py)
**Date:** 2026-05-23

## Problem

The MVP1.5 release tier was introduced 2026-05-23 (PR #200) but the dashboard regen script's release classifier was never taught about it. Consequence: `feat_ubi_judgments` (the MVP1.5 anchor) falls through to `DEFAULT_RELEASE = "mvp1"` and renders at the top of `MVP1_DASHBOARD.md`'s Idea table (P1 dominates P2 — sort is correct given wrong input). `/pipeline status` mirrors that wrong-priority answer. Operators can't trust the priority order until fixed.

## Reproduction

Pre-fix on `main`: `python scripts/build_mvp1_dashboard.py` produced `mvp1: 95 features, mvp2: 5 features` — no MVP1.5 dashboard. `MVP1_DASHBOARD.md`'s Idea table started with `| 1 | P1 | feat_ubi_judgments | …` even though `feat_ubi_judgments` is the MVP1.5 anchor. Regression tests in `test_dashboard_release_classifier.py` fail on `main` with `ImportError` (the helper they test doesn't exist there — the new test file references identifiers the pre-fix script doesn't expose differently, but `_target_release("foo_mvp1_5", "")` would return `"mvp10"` instead of `"mvp1.5"` due to `int(m.group(1))` on `"1_5"`).

## Root cause

- **Owning layer:** scripts (developer-tooling)
- **Three gaps** in [`scripts/build_mvp1_dashboard.py`](../../../../scripts/build_mvp1_dashboard.py):
  1. `_RELEASE_SUFFIX_RE` at line 128 — pattern `r"_mvp(\d+)$"` matched only integer release tags. `_mvp1_5` didn't match.
  2. `_RELEASE_STATUS_RE` at line 131 — pattern `r"Held\s+for\s+MVP\s*(\d+)"` matched only "Held for MVPN" framing AND only integer captures. `Idea — anchor feature for MVP1.5 / v0.1.5` missed both.
  3. `ROADMAP_RELEASES` at line 57 — no `mvp1.5` row between `mvp1` and `mvp2`.
- **Plus a secondary bug** revealed during implementation: `_load_planned` passed `status_line + " " + (idea or "")` to `_target_release` at line 649 — feeding the entire idea body to the classifier. Body prose that quoted release-tag phrases as documentation examples (like this bug's idea.md) got misclassified.

## Fix design (locked decisions)

1. **Extend `_RELEASE_SUFFIX_RE`** from `r"_mvp(\d+)$"` to `r"_mvp(\d+(?:_\d+)?)$"`. Normalize captured `"1_5"` → `"1.5"` via `.replace('_', '.')`. Cites: idea.md half-step convention; folder names can't contain dots so underscore-to-dot translation is the natural encoding.
2. **Extend `_RELEASE_STATUS_RE`** to recognize both `Held for MVP<v>` AND `anchor for MVP<v>` / `anchor feature for MVP<v>`, with `<v>` capturing integer (`"2"`) or decimal (`"1.5"`). Cites: idea-template convention — operators use "Held for" for deferrals and "anchor feature for" for release anchors. Both are conventional, neither generic enough to false-positive on random prose.
3. **Add `("mvp1.5", "MVP1.5 / v0.1.5", "Real Signals")`** to `ROADMAP_RELEASES` between `mvp1` and `mvp2`. Cites: canonical release matrix in [`tech-stack.md`](../../../01_architecture/tech-stack.md).
4. **Normalize dot → underscore for filenames** in `_dashboard_paths`. `"mvp1.5"` → `MVP1_5_DASHBOARD.md` + `mvp1_5_dashboard.html`. Cites: dots-in-filenames read confusably (like file extensions); underscores match the folder-suffix convention.
5. **Restrict the classifier input to `status_line` only** at `_load_planned:649`. Drop the `+ " " + (idea or "")` concat that fed the whole body. Cites: status_line is operator-curated and intentional; body prose may quote release-tag phrases as documentation, which would misclassify. `_load_implemented` already followed this pattern (line 694) — convergent fix.
6. **Extend `Feature.display_name` regex** to strip both `_mvp\d+$` and `_mvp\d+_\d+$` suffixes from card labels. Cites: same release-tag suffix shouldn't double-print on the visual card; half-step folders need the same stripping.
7. **Rename this bug's folder** from `bug_dashboard_classifier_missing_mvp1_5` to `bug_dashboard_classifier_half_step_releases`. The original name ended in `_mvp1_5` and triggered the new regex on itself — a self-collision. General convention: feature folders *about* a release (vs. scoped to it) should avoid `_mvpN_M` in their descriptive tail. Captured as a one-line note in the idea.md front matter for future contributors.

### Open questions

None — every fork was an engineering judgment call already locked in idea.md's "Proposed fix" section.

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| unit | `backend/tests/unit/scripts/test_dashboard_release_classifier.py` | 14 cases: integer-suffix regression, half-step-suffix new behavior, default fallback (3 suffix cases); Held-for-integer regression, Held-for-half-step new, anchor-feature-for new, anchor-for new, suffix-wins-over-status regression, body-prose-not-matched (6 status-line cases); `_dashboard_paths` integer regression + half-step + future MVP2.5 (3 path cases); `Feature.display_name` strips integer + half-step suffix (2 display-name cases). |

End-to-end on the live filesystem after the fix:

- Regen produces `mvp1: 96 features, mvp1.5: 1 features, mvp2: 5 features, roadmap: 7 releases in matrix` (was `mvp1: 95, mvp2: 5, 6 releases in matrix`).
- New file `docs/00_overview/MVP1_5_DASHBOARD.md` exists with `feat_ubi_judgments` as its only Idea row.
- `MVP1_DASHBOARD.md`'s Idea table no longer contains `feat_ubi_judgments`.
- `/pipeline status` (re-rendered) shows the new top item — currently this bug fix itself (P1, because the bug distorts ranking until shipped).

## Rollout

None — code-only change to the regen script.

- No schema, no API, no migration.
- The pre-commit `mvp1-dashboard-regen` hook regenerates dashboards automatically; they travel with the fix.
- No operator action required. Existing `feat_ubi_judgments` is auto-reclassified to MVP1.5 on first regen.
- Future MVP1.5 ideas can use either the folder-suffix form (`_mvp1_5`) or the status-line form (`Held for MVP1.5` / `anchor feature for MVP1.5`) — both recognized.

## Tangential observations

- **Folder-name convention drift:** the original bug-folder name `bug_dashboard_classifier_missing_mvp1_5` was descriptive ("about MVP1.5") but collided with the suffix convention ("scoped to MVP1.5"). Idea.md's front-matter note now documents the general rule. Worth a one-line addition to [`feature_templates/README.md`](../feature_templates/README.md) if more cases arise; deferring as a follow-up rather than bundling — bounded LOC, narrow audience.

None other.
