# `_extract_pr_number` priority-4 last-resort fallback matches dependency PR# in idea-body footnotes

**Date:** 2026-05-25
**Status:** Idea — surfaced during `chore_dashboard_regen_quoted_pr_false_positive` final-review (PR #253, 2026-05-25) by GPT-5.5 cross-model review
**Priority:** P2 — cosmetic; affects planned-feature rows whose `idea.md` cites dependency PR#s in narrative "Depends on:" footnotes. Same blast radius as the priority-3 backtick-quoted false positive that `chore_dashboard_regen_quoted_pr_false_positive` (PR #253) fixed: planned-only, replaced by `_load_implemented` once the feature merges, does not affect shipped-feature row accuracy.
**Origin:** During `chore_dashboard_regen_quoted_pr_false_positive` PR #253's final cross-model review, GPT-5.5 caught that the regenerated dashboard still showed the chore's own row with a wrong PR# (`[PR #221] merged 2026-05-25` — that's the sibling `chore_dashboard_pr_extraction_from_idea`'s PR, not this chore's). Tracing showed PR #253's priority-3 fix correctly stripped backtick-quoted phrases, but the remaining false positive came from priority-4 (last-resort `#N` fallback at [`scripts/build_mvp1_dashboard.py:_extract_pr_number`](../../../../scripts/build_mvp1_dashboard.py)) catching `PR #221` in the chore's `idea.md` `**Depends on:** ... PR #221 — both shipped 2026-05-23` footnote.
**Depends on:** None. (Builds on `chore_dashboard_regen_quoted_pr_false_positive` PR #253 — that chore narrowed priority-3 but left priority-4 untouched.)

## Problem

[`_extract_pr_number`](../../../../scripts/build_mvp1_dashboard.py)'s priority-4 last-resort fallback (after pipeline_status / plan-Status / priority-3 fuzzy / priority-3.5 strict idea-body / priority-3.6 frontmatter all fail) scans the combined pipe+plan+spec text for the first `#N` reference outside any dependency-table row. The existing `_strip_dependency_table_rows` helper only strips MARKDOWN TABLE ROWS (lines starting with `|`); it does NOT strip narrative "Depends on:" footnotes in idea-body prose.

Result: if an idea has a footnote like `**Depends on:** Builds on top of foo PR #208 + bar PR #221 — both shipped 2026-05-23.`, priority-4 returns the first `#N` it finds (here PR #221) as the FEATURE's own PR number.

## Concrete impact

Observed during `chore_dashboard_regen_quoted_pr_false_positive` PR #253 final-review (2026-05-25):

- This chore's own `idea.md` Depends-on footnote cites two dependency PRs (#208 and #221). Even AFTER the priority-3 backtick-strip fix (PR #253), the dashboard's Plan row for this chore showed `[PR #221] merged 2026-05-25` — the sibling chore's PR, falsely attributed to this chore.
- Pattern: any planned-feature idea that names its dependencies' PR#s in a narrative footnote will produce the same false attribution on its dashboard row until the feature itself merges.

## Why deferred from `chore_dashboard_regen_quoted_pr_false_positive`

Out of scope for PR #253 — that chore's scope was priority-3 backtick-quoted phrase stripping (Option A in its idea), NOT priority-4 last-resort fallback hardening. The priority-3 fix is correctly implemented and tested (8 ACs); the priority-4 fallback is an independent surface that picks up dependency-cite PR#s NOT in backtick segments.

PR #253's own idea (line 40) pre-emptively acknowledged the cosmetic effect: "the cosmetic effect (one wrong PR# on the chore's own planned-feature row in the dashboard until it merges) was accepted because (a) it's planned-only — once merged, `_load_implemented` takes over and the chore's actual PR number replaces the rendered value, AND (b) it does not affect any shipped-feature row's accuracy." That acknowledgment applied equally to priority-3 and priority-4 paths.

## Proposed capabilities

Two options for tightening priority-4:

### Option A — Extend `_strip_dependency_table_rows` to also strip narrative "Depends on:" lines

Add a regex that matches lines starting with `**Depends on:**` (or `Depends on:` / `**Dependencies:**`) and strips them before priority-4 runs.

**Pros:** Minimal-surface fix; one regex addition.
**Cons:** Pattern is narrative — could miss variants like `## Dependencies\n\nfoo PR #N` (header form). Requires careful coverage.

### Option B — Demote priority-4 to opt-in via a `**PR-fallback-allow:** true` marker

Most ideas don't need the last-resort fallback (they have explicit Status patterns at 3.5 or frontmatter at 3.6). Make priority-4 opt-in.

**Pros:** Most surgical.
**Cons:** Requires backfilling the marker on features that genuinely need the fallback.

### Option C — Tighten priority-4 to scan only idea metadata block (not full pipe+plan+spec)

The metadata block already has bounded scope (per `_extract_metadata_block`). Restricting priority-4 to this scope avoids body-section "Depends on:" footnotes entirely.

**Pros:** Composes with the existing priority-3.6 metadata-block discipline.
**Cons:** May break legacy features whose own-PR# lives in body, not metadata.

**Recommendation:** Option A as lowest-friction; pair with a regression-guard test that loads PR #253's pre-merge `idea.md` and asserts the false-positive is rejected.

## Scope signals

- **Backend:** ~5–15 LOC in `scripts/build_mvp1_dashboard.py` depending on chosen option (extend `_strip_dependency_table_rows` regex, OR add a new `_strip_dependency_footnote_lines` helper).
- **Frontend:** none.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A.
- **Tests:** ~3–5 new test cases in `backend/tests/unit/scripts/test_dashboard_pr_extraction.py` (new class `TestPriority4DependencyFootnoteFalsePositive` or extension of an existing class) using the actual PR #253 idea-body footnote as a regression fixture.

## Relationship to other work

- **Surfaced by [`chore_dashboard_regen_quoted_pr_false_positive`](../chore_dashboard_regen_quoted_pr_false_positive/)** PR #253 final-review.
- **Composes with [`chore_dashboard_pr_extraction_from_idea`](../../../00_overview/implemented_features/2026_05_23_chore_dashboard_pr_extraction_from_idea/)** PR #221 — that work added the 3.5/3.6 strict patterns that work correctly; only the legacy priority-4 fallback needs hardening.
- **Independent of priority-3 backtick-quoted PR fix** (PR #253). Priority-3 handles backtick-quoted false positives; priority-4 handles narrative-footnote false positives. Two different scopes.
