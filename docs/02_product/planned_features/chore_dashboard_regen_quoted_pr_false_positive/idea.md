# `_extract_pr_number` priority-3 fuzzy regex matches quoted PR-merge phrases in narrative text

**Date:** 2026-05-23
**Status:** Idea — surfaced during `chore_dashboard_pr_extraction_from_idea` empirical verification (2026-05-23)
**Priority:** P3 — cosmetic-only; affects planned-feature rows in `MVP1_DASHBOARD.md`'s Plan/Spec sections when a feature's spec/plan/idea body cites other features' PR-merge phrases in narrative text. No effect on shipped-feature accuracy.
**Origin:** During `chore_dashboard_pr_extraction_from_idea` (this chore's sibling) empirical verification, `_load_planned` for the chore's own folder extracted `PR #4` (which belongs to `infra_foundation`) because the chore's spec content includes AC-4's example body `**Depends on:** [infra_foundation] — merged via PR #4 (2026-05-09)`. The pre-existing priority-3 fuzzy regex `merged[^.\n]{0,80}PR[^a-zA-Z\n]{0,5}#(\d+)` matched the narrative quote and returned `4` as this feature's PR number. Multiple other AC bodies in the spec (AC-9, AC-10) had similar patterns; the rendered dashboard row for the chore in the Plan section showed misleading values like `[PR #4] merged 2026-05-15` despite the chore being planned-only.
**Depends on:** None. (Builds on top of [`bug_dashboard_depends_on_column_bloat`](../../../00_overview/implemented_features/2026_05_23_bug_dashboard_depends_on_column_bloat/) PR #208 + `chore_dashboard_pr_extraction_from_idea` PR-TBD.)

## Problem

[`_extract_pr_number`](../../../../scripts/build_mvp1_dashboard.py#L572)'s priority-3 fuzzy match has two regexes:

```python
m = re.search(r"PR[^a-zA-Z\n]{0,5}#(\d+)[^.\n]{0,80}merged", combined)
m = re.search(r"merged[^.\n]{0,80}PR[^a-zA-Z\n]{0,5}#(\d+)", combined)
```

Both scan `pipe + "\n" + plan + "\n" + spec` for any `PR #N` adjacent to the word `merged` (in either order) within 80 non-period non-newline chars. They were designed to catch features that describe their own ship event in narrative form (e.g., `## Status\n\nThis feature merged on 2026-05-15 as PR #N`). They successfully catch own-PR cites — but they also catch:

1. **Narrative descriptions of OTHER features' merge events** in the spec body — e.g., a Dependencies section paragraph mentioning `PR #208 ... merged 2026-05-23` for an upstream dependency.
2. **AC-body example text** in feature_spec.md files that document patterns for an idea-aware extraction layer — the very pattern the AC describes is the literal text that trips the regex.
3. **Code/test fixture quotes** like `**Status:** **Implemented — PR #161 (squash ...)**, merged 2026-05-20` quoted in prose to ground a spec's AC.

The current `_strip_dependency_table_rows` helper at [`scripts/build_mvp1_dashboard.py:488`](../../../../scripts/build_mvp1_dashboard.py#L488) only strips MARKDOWN TABLE ROWS that contain `Implemented` / `Depends on` / `Depended` keywords. It doesn't touch narrative paragraphs, bullet lists, or backtick-fenced inline examples.

## Concrete impact

Examples observed during `chore_dashboard_pr_extraction_from_idea`'s empirical verification (2026-05-23):

- The chore's spec contains the AC-4 example `**Depends on:** [infra_foundation] — merged via PR #4`. Priority-3 fuzzy regex matches → `_load_planned` returns `pr_number=4` for THIS chore. Rendered dashboard row: `chore_dashboard_pr_extraction_from_idea | [PR #4](...) merged 2026-05-15`.
- The same spec contains the AC-1 precedent `**Status:** **Shipped** as PR [#124](...) (squash-merged 2026-05-15, ...)`. Priority-3 also matches → `pr_number=124` if AC-4 weren't present.
- Multiple ACs cite literal merge-context phrases like `PR #N ... merged YYYY-MM-DD` for didactic clarity.

The chore tried to scrub the literal triggers from its own spec but found they're pervasive — `merged` is a domain term used in many legitimate non-PR-attribution contexts (e.g., `**Dependency:** bug_X shipped 2026-05-23 as PR #208. Created the regression-visibility surface. Hard dependency; merged before this chore starts.`). Aggressive scrubbing destroys readability.

## Why deferred from `chore_dashboard_pr_extraction_from_idea`

Out of scope for that chore — its scope was extending `_extract_pr_number` with strict idea-body patterns (priorities 3.5 and 3.6), NOT modifying the pre-existing priority-3 fuzzy match. The strict patterns work correctly; the fuzzy match's quoted-PR false positives are an independent surface.

The cosmetic effect (one wrong PR# on the chore's own planned-feature row in the dashboard until it merges) was accepted because (a) it's planned-only — once merged, `_load_implemented` takes over and the chore's actual PR number replaces the rendered value, AND (b) it does not affect any shipped-feature row's accuracy.

## Proposed capabilities

Three options for tightening priority-3, in increasing scope:

### Option A — Strip narrative-quoted PR-merge phrases via backtick scope

Strip backtick-fenced inline code AND triple-backtick code blocks BEFORE running the fuzzy regex. Most quoted PR-merge phrases in spec narrative are inside backticks (e.g., `` `merged via PR #4` ``). The current code already has `_strip_dependency_table_rows`; add `_strip_backtick_quoted_segments`.

**Pros:** Captures the most common false-positive shape.
**Cons:** Doesn't catch un-backticked narrative ("This feature merged on YYYY-MM-DD as PR #N" in prose).

### Option B — Tighten the fuzzy regex to require structural anchors

Replace `merged[^.\n]{0,80}PR` with stricter shapes:
- `^.*\bmerged\b.*PR\s*#(\d+).*$` with `re.MULTILINE` — require both on the same line AND not inside a table cell.
- Require `merged` to be the first word of a sentence or after a known status anchor (`**Status:**`, `## Status`, etc.).

**Pros:** Stronger guarantee.
**Cons:** Risk breaking legitimate own-PR extractions; needs careful regression testing against the existing shipped-feature corpus.

### Option C — Move priority-3 above the new priority 3.5/3.6 strictly, AND make priority 3 opt-in via a `merged-context-fuzzy-match: true` marker in the spec frontmatter

Most ideas don't need the fuzzy match anymore — they have strict patterns (3.5) or frontmatter (3.6). The fuzzy match's value is only for legacy features that have narrative-only status assertions. Make it opt-in to confine its blast radius.

**Pros:** Most surgical; preserves backward compat.
**Cons:** Requires backfilling the marker on features that genuinely need the fuzzy match.

**Recommendation:** Option A as the lowest-friction fix; document a planned move to Option C as a follow-up if Option A leaves residual false positives.

## Scope signals

- **Backend:** ~10–30 LOC in `scripts/build_mvp1_dashboard.py` depending on chosen option.
- **Frontend:** none.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A.
- **Tests:** ~5–10 new test cases in `backend/tests/unit/scripts/test_dashboard_pr_extraction.py` (or a new sibling file) locking the false-positive rejection.

## Relationship to other work

- **Surfaced by [`chore_dashboard_pr_extraction_from_idea`](../chore_dashboard_pr_extraction_from_idea/)** during empirical verification.
- **Composes with [`bug_dashboard_depends_on_column_bloat`](../../../00_overview/implemented_features/2026_05_23_bug_dashboard_depends_on_column_bloat/)** — that fix introduced the time-ordered transitive-dep expansion that makes PR-number accuracy matter for same-day tiebreakers; this idea polishes the priority-3 extraction surface that feeds the PR-number column.
- **Independent of the idea-aware extraction layer** (3.5/3.6) added by `chore_dashboard_pr_extraction_from_idea`. The strict patterns work correctly; only the legacy fuzzy match needs hardening.
