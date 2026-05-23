# Bug fix — dashboard_depends_on_column_bloat

**Source idea:** [idea.md](./idea.md)
**Branch:** `bug/dashboard-depends-on-column-bloat`
**Type:** bug fix — medium (this skill's scope; ~100 LOC across script + new test file)
**Date:** 2026-05-23

## Problem

The MVP1 dashboard's "Depends on" column rendered 41-42 backtick'd entries for two shipped features (`feat_chat_agent` and `chore_tutorial_polish`, both 2026-05-12), including features that shipped weeks later (e.g., `feat_pr_metric_confidence` 2026-05-21) and still-planned ideas (e.g., `feat_ubi_judgments`). A shipped feature can't depend on something that didn't exist yet — the column was bloated and operator-misleading. Pre-existing on `main`; only Gemini Code Assist's review of PR #200 surfaced it.

## Reproduction

```bash
# Pre-fix on main: bloated rows
git checkout main
grep -m1 "feat_chat_agent" docs/00_overview/MVP1_DASHBOARD.md | grep -oE '\`[a-z_]+\`' | sort -u | wc -l
# → 41 entries (should be ~10 — only the features that shipped on or before 2026-05-12)
```

Regression test (in [`backend/tests/unit/scripts/test_dashboard_expand_transitive_deps.py`](../../../../backend/tests/unit/scripts/test_dashboard_expand_transitive_deps.py)) fails on `main` with `ImportError: cannot import name '_expand_transitive_deps'` (the helper doesn't exist there); passes on this branch.

```bash
.venv/bin/python -m pytest backend/tests/unit/scripts/test_dashboard_expand_transitive_deps.py -v
```

## Root cause

The diagnosis in the original `idea.md` was wrong (claimed the parser scanned the whole document); the actual cause is in the sentinel-expansion logic, not the parser.

- **Owning layer:** scripts (regen script — not application code)
- **Parser (already correct):** [`scripts/build_mvp1_dashboard.py:445`](../../../../scripts/build_mvp1_dashboard.py#L445) — `re.search(r"^-\s+Depends on:\s*(.+)$", ..., re.MULTILINE)` is already scoped to the `- Depends on:` bullet line.
- **Bug site:** [`scripts/build_mvp1_dashboard.py:707-714`](../../../../scripts/build_mvp1_dashboard.py) (pre-fix) — the `DEPS_ALL_BACKEND` sentinel was expanded against the **current snapshot** of `infra_*`/`feat_*` folders with no time-ordering filter. Two features use the transitive marker (`_TRANSITIVE_DEP_PHRASES` at [line 413](../../../../scripts/build_mvp1_dashboard.py#L413)): `feat_chat_agent` says `- Depends on: ALL prior backend features`, `chore_tutorial_polish` says `ALL prior MVP1 features`. Both inherited today's full backend roster.

## Fix design (locked decisions)

1. **Extract `_expand_transitive_deps(features)` as a module-level helper.** Cites: standard testable-unit refactor pattern; the existing `_extract_*` helpers in the same file (e.g., `_extract_pr_number`, `_extract_merged_date`) are module-level and unit-tested similarly.
2. **Time-order the expansion via `(merged_date, pr_number, folder)` sort key.** For a shipped feature `f` using the sentinel, include only backend peers `g` where `_merge_order_key(g) < _merge_order_key(f)`. For a planned feature (no `merged_date`), keep the full-snapshot expansion (planned features genuinely depend on every backend sibling in the queue). Cites: idea.md's Phase 4 lock — folder date prefix is the canonical merge date; PR# is the same-day tiebreaker.
3. **Sort key — `("9999-99-99", 999999, folder)` for missing fields.** Anything without a `merged_date` sorts to end-of-time; anything without a `pr_number` sorts to end-of-day. Cites: preserves the conservative-exclusion property — when merge order is ambiguous, the helper excludes the ambiguous peer rather than risk including a post-shipment one.
4. **Preserve the pre-existing self-dep guard.** `f.folder` is still subtracted from the scoped expansion. The explicit-side self-reference (rare; would mean the spec author wrote their own folder name in `- Depends on:`) is left alone — out of scope for this bug. Cites: minimal-change rule from CLAUDE.md Bug Fix Protocol Step 3.

### Open questions

None — every fork was an engineering judgment call; all locked above.

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| unit | `backend/tests/unit/scripts/test_dashboard_expand_transitive_deps.py` | 10 cases: shipped-feature time-scoped expansion (the canonical bloat case), planned-feature full-snapshot expansion, explicit-deps union with sentinel, no-sentinel pass-through, non-backend prefixes excluded, self-dep guard preserved, and 4 `_merge_order_key` cases locking date / PR# / missing-fields tiebreakers. Verified to fail on `main` with `ImportError` (the helper doesn't exist there). |

End-to-end verification on the live filesystem:

- `feat_chat_agent` row: **41 → 10** backtick'd entries.
- `chore_tutorial_polish` row: **42 → 11** backtick'd entries.
- All other dashboard rows: byte-identical (no collateral churn).
- 10 entries match exactly the set of `infra_*`/`feat_*` folders shipped on or before 2026-05-12 minus `feat_chat_agent` itself (verified by `ls docs/00_overview/implemented_features/`).

## Rollout

None — code-only change to the regen script.

- No schema, no API, no migration.
- The pre-commit `mvp1-dashboard-regen` hook regenerates [`MVP1_DASHBOARD.md`](../../../00_overview/MVP1_DASHBOARD.md), [`DASHBOARD.md`](../../../00_overview/DASHBOARD.md), and the `.html` siblings automatically on commit. Those files travel with the fix.
- No operator action required.

## Tangential observations

- [`chore_dashboard_pr_extraction_from_idea`](../chore_dashboard_pr_extraction_from_idea/idea.md) — `_extract_pr_number` only reads `pipeline_status.md` / `implementation_plan.md` / `feature_spec.md`, not `idea.md`. Legacy implemented features that shipped before the `/pipeline` ceremony (e.g., `infra_frontend_stack_refresh`) only have `idea.md`, so their PR# is `None` and they sort to end-of-day in `_merge_order_key`. Net effect: ~1 missing edge per legacy feature in same-day peers' deps. Operator-cosmetic, not a correctness regression. Worth a polish PR next time someone is touching the regen script.
