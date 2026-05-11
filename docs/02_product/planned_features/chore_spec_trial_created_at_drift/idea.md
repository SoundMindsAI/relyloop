# chore — spec `?sort=created_at_*` vs. trials' missing `created_at` column

**Date:** 2026-05-10
**Type:** `chore_` — spec/schema drift correction (doc + potentially schema).
**Origin:** GPT-5.5 Epic 1 phase-gate review of `feat_study_lifecycle` Phase 2 (finding E1-F2, 2026-05-10).

## Problem

`feat_study_lifecycle/feature_spec.md` §7.4 defines wire values for the trials list `?sort=` query parameter:

```
?sort  →  primary_metric_desc | primary_metric_asc
       |  created_at_desc | created_at_asc
       |  optuna_trial_number_asc
```

But the `trials` table (Phase 1 schema, migration `0003_study_lifecycle_schema.py`) **has no `created_at` column** — only `started_at` (when `ask()` was called) and `ended_at` (when `tell()` completed). The closest semantic to "when did this trial happen" is `ended_at`.

Story 1.4's [`list_trials_paginated`](../../../../backend/app/db/repo/trial.py) currently maps `created_at_desc` / `created_at_asc` to `ended_at` ordering. This is functionally reasonable but documentation-divergent — the API surface promises one thing and delivers another.

## Why deferred

Two options to converge:

**Option A (doc-only):** Rename the wire values to `ended_at_desc` / `ended_at_asc` in the spec + the `TrialSortKey` Literal everywhere. No schema change. Forward-only.

**Option B (schema):** Add a `created_at TIMESTAMPTZ NOT NULL DEFAULT now()` column to `trials` via a follow-up migration; backfill with `started_at` for existing rows. Keep the spec wording.

Either option is one PR. Both require:
- Migration (B only)
- Update `backend/app/db/models/trial.py`
- Update the repo function to use the chosen column
- Update the wire enum (A only)
- Update the spec wording (A only)
- Update Phase 2's tests

Neither option blocks Story 3.4 from shipping — the current `ended_at` mapping works correctly.

## Recommended fix

**Option A** — rename the wire enum. `ended_at_*` is more honest about what the user gets, and the migration cost of (B) is unjustified for cosmetic alignment.

When this chore ships:

1. Update `feat_study_lifecycle/feature_spec.md` §7.4 (move text from `implemented_features/<date>_feat_study_lifecycle/feature_spec.md` if Phase 2 has shipped by then).
2. Rename `TrialSortKey` in `backend/app/db/repo/trial.py` and `backend/app/api/v1/schemas.py`:
   - `created_at_desc` → `ended_at_desc`
   - `created_at_asc` → `ended_at_asc`
3. Update test fixtures in `test_phase2_repos.py`, `test_pagination.py`, and contract tests.

## Cross-references

- [`feat_study_lifecycle/feature_spec.md`](../feat_study_lifecycle/feature_spec.md) §7.4.
- [`migrations/versions/0003_study_lifecycle_schema.py`](../../../../migrations/versions/0003_study_lifecycle_schema.py) — trials table DDL.
- [`backend/app/db/repo/trial.py:list_trials_paginated`](../../../../backend/app/db/repo/trial.py) — current mapping site.
- GPT-5.5 finding E1-F2 (Epic 1 phase-gate review, 2026-05-10).
