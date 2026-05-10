# chore — spec `feat_study_lifecycle` FR-3 `cluster_id?` drift

**Date:** 2026-05-10
**Type:** `chore_` — spec text correction (no code change).
**Origin:** GPT-5.5 cycle-1 cross-model review of `feat_study_lifecycle` Phase 2 implementation plan, finding F2 (re-adjudicated and rejected against the plan but accepted as a spec drift).

## Problem

`docs/02_product/planned_features/feat_study_lifecycle/feature_spec.md` §7 FR-3 says:

> `POST /api/v1/query-sets` accepts `{name, description?, cluster_id?}`.

The `cluster_id?` marker implies the field is optional. **It is not** — Phase 1's
shipped schema (`migrations/versions/0003_study_lifecycle_schema.py:79`,
`backend/app/db/models/query_set.py:26`) declares `query_sets.cluster_id` as
`NOT NULL`. Phase 1 merged 2026-05-10 (PR #18) with this shape, and Phase 2 does
not add migrations.

Therefore the API surface must require `cluster_id` at create time, not allow it
to be omitted. Phase 2's plan correctly mirrors the schema (`CreateQuerySetRequest.cluster_id: str`).

## Why deferred

The spec text drift is documentation-only — it doesn't affect Phase 2's
implementation (the plan ships the correct required-field shape). Patching the
spec is out of scope for the Phase 2 PR (would conflict with Phase 2's
implementation_plan.md cross-references).

## Fix

One-line spec edit:

```diff
-- `POST /api/v1/query-sets` accepts `{name, description?, cluster_id?}`.
++ `POST /api/v1/query-sets` accepts `{name, description?, cluster_id}`. (Required; Phase 1's schema has `query_sets.cluster_id NOT NULL`.)
```

Apply when this chore ships. No code change. No migration. No test impact.

## Cross-references

- [`feat_study_lifecycle/feature_spec.md`](../feat_study_lifecycle/feature_spec.md) §7 FR-3 — the drift site.
- [`feat_study_lifecycle/phase2_implementation_plan.md`](../feat_study_lifecycle/phase2_implementation_plan.md) Story 3.2 — documents the spec-vs-schema reconciliation inline.
- [`migrations/versions/0003_study_lifecycle_schema.py:79`](../../../../migrations/versions/0003_study_lifecycle_schema.py) — authoritative NOT NULL declaration.
- [`backend/app/db/models/query_set.py:26`](../../../../backend/app/db/models/query_set.py) — authoritative ORM model.
