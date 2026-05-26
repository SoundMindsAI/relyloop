# Bug fix — `chore_dashboard_regen_priority4_dependency_cite_false_positive`

**Source idea:** [idea.md](./idea.md)
**Branch:** `chore/dashboard-regen-priority4-dependency-cite-false-positive`
**Type:** chore (cosmetic; impact is wrong PR# rendered on planned-feature rows until they merge — not operator-blocking per `feature_templates/README.md`)
**Date:** 2026-05-26

## Problem

`_extract_pr_number`'s priority-4 last-resort fallback at [`scripts/build_mvp1_dashboard.py:694`](../../../../scripts/build_mvp1_dashboard.py#L694) scans the combined `pipe + plan + spec` text for the first `#N` reference, gated only by `_strip_dependency_table_rows` (markdown-table rows starting with `|`). Narrative footnotes like `**Depends on:** foo PR #208 + bar PR #221` are NOT stripped, so the first dependency's PR# is misread as the feature's own PR. Surfaced by GPT-5.5 on PR #253's final review when the chore's own dashboard row showed `PR #221` (a sibling's PR) instead of its own.

## Reproduction

```bash
.venv/bin/pytest backend/tests/unit/scripts/test_dashboard_pr_extraction.py::TestPriority4DependencyFootnoteFalsePositive -v
```

Pre-fix: 4 of 5 new tests fail (`assert 42 is None` / `assert 208 is None` / `assert 221 is None`). Post-fix: all 5 pass.

## Root cause

- **Owning layer:** dashboard-regen script (Python).
- **Origin:** [`_extract_pr_number` priority-4 fallback at `scripts/build_mvp1_dashboard.py:694`](../../../../scripts/build_mvp1_dashboard.py#L694) — `re.findall(r"PR[^a-zA-Z\n]{0,5}#(\d+)", combined)` returns the first `#N` regardless of whether it sits on a dependency-cite line.
- **Propagation:** [`_strip_dependency_table_rows`](../../../../scripts/build_mvp1_dashboard.py#L488) (called at [`scripts/build_mvp1_dashboard.py:664`](../../../../scripts/build_mvp1_dashboard.py#L664)) only matches markdown TABLE rows via `^\s*\|.*` — narrative inline footnotes (`**Depends on:**`, `Depends on:`, `**Dependencies:**`) flow through unchanged.

## Fix design (locked decisions)

Option A from the idea (extend dependency-cite stripping to narrative footnotes), locked over Options B (opt-in marker) and C (metadata-block scope only) per the idea's §"Recommendation" line.

1. **Add a sibling `_strip_dependency_footnote_lines` helper** (separate from `_strip_dependency_table_rows` for single-responsibility — table rows and narrative footnotes are different surface shapes). Cites: existing `_strip_backtick_quoted_segments` precedent at [`scripts/build_mvp1_dashboard.py:499`](../../../../scripts/build_mvp1_dashboard.py#L499) — separate helper for separate concern.
2. **Match `Depends on` / `Dependencies` / `Depended on` only**, NOT `Implemented` (which `_DEP_ROW_RE` catches in tables). `**Implemented:** PR #N` as a narrative line is a status assertion about *this* feature, not a dependency cite, so it must continue to match priority-3/3.5. Cites: minimal-fix discipline; idea §"Concrete impact" cites only `Depends on:` patterns.
3. **Support optional bullet prefix and optional `**` markers** — `^\s*(?:[-*]\s+)?(?:\*\*)?(?:Depends on|...)(?:\*\*)?:` covers the four shapes the idea cites (bolded, unbolded, plural, bulleted).
4. **Apply AFTER `_strip_dependency_table_rows` in the priority-3/4 composition.** Order: backtick-strip → table-row strip → footnote-strip. Each operates on the residual from its predecessor. Cites: existing call chain at [`scripts/build_mvp1_dashboard.py:664`](../../../../scripts/build_mvp1_dashboard.py#L664).
5. **Do NOT extend to multi-line `## Dependencies\n\nfoo PR #N` header form.** The idea explicitly flags this as a known cons of Option A; the documented false-positive is single-line footnotes only. A multi-line `## Dependencies` block with PR cites in body prose is a separate surface that would warrant its own follow-up if observed.

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| Unit (script) | [`backend/tests/unit/scripts/test_dashboard_pr_extraction.py`](../../../../backend/tests/unit/scripts/test_dashboard_pr_extraction.py) | New `TestPriority4DependencyFootnoteFalsePositive` class with 5 tests: minimal two-PR footnote → None; PR #253's canonical footnote in spec position → None; unbolded `- Depends on:` variant → None; `**Dependencies:**` plural variant → None; legitimate own-PR `#N` in priority-4 fallback still returns the PR# (negative guard against over-stripping). |

The 4 failure-mode tests all fail on `main` (`assert 42 is None` / `assert 208 is None` / etc.) and pass post-fix; the 1 negative guard passes on both. Total: 41 tests in the file (was 36); 117 in `backend/tests/unit/scripts/` (no regressions).

## Rollout

- **Code-only change.** No migration, no schema, no new env var, no operator action.
- **No live-dashboard drift.** Verified by running `scripts/build_mvp1_dashboard.py` against the current working tree — reports "no changes (132 features across 3 release(s))". The fix is forward-looking: it only affects future planned-feature rows whose `idea.md` / `feature_spec.md` / `implementation_plan.md` carry narrative dependency footnotes that don't already match priority-1/2/3/3.5/3.6. No shipped-feature row's PR# is recomputed.
- **MVP3 obsoletion path:** none required. Priority-4 remains a legitimate last-resort fallback for legacy idea-only features that don't fit the 3.5/3.6 strict patterns. The footnote-strip is a permanent narrowing of priority-4's scan corpus, not a deprecation.

## Tangential observations

None. The fix is tightly scoped to one regex helper + one composition order; no adjacent issues surfaced during tracing.
