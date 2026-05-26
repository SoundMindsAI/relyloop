# Bug fix — `bug_seed_demo_if_empty_counts_soft_deleted`

**Source idea:** [idea.md](./idea.md)
**Branch:** `bug/stuck-stack-self-rescue-bundle`
**Type:** bug fix — medium (this skill's scope; bundled with sibling [`bug_dashboard_reset_disclosure_gating_too_strict`](../bug_dashboard_reset_disclosure_gating_too_strict/idea.md) per the "Relationship to other work" section of both ideas)
**Date:** 2026-05-26

## Problem

[`scripts/seed_meaningful_demos.py:824`](../../../../scripts/seed_meaningful_demos.py#L824) ran `SELECT COUNT(*) FROM clusters` with no `WHERE deleted_at IS NULL` filter. The `--if-empty` branch ([line 866-887](../../../../scripts/seed_meaningful_demos.py#L866-L887)) uses the count to decide whether `make up`'s auto-seed step ([`scripts/install.sh:95`](../../../../scripts/install.sh#L95)) should fire. Soft-deleted cluster rows (left behind by E2E tests, operator manual deletes, or previous seed-then-wipe cycles) counted toward "exists" and permanently false-skipped the auto-seed on every subsequent `make up` — leaving operators on an empty dashboard with no in-product recovery path.

The bug was empirically reproduced **during this same session**: after `make down && make up`, the operator's `/` showed zero clusters despite `make up` having "successfully" run the auto-seed step. The DB had 7 cluster rows but all with non-null `deleted_at` (from earlier E2E test cleanup ~2026-05-26 13:32 UTC). `count_existing_clusters()` returned 7; auto-seed printed "skipping — 7 cluster(s) already exist"; the public API correctly filtered the dead rows and returned `data: []` to the UI.

## Reproduction

The pre-fix SQL is a 1-line static assertion failure (no DB needed):

```python
from scripts.seed_meaningful_demos import _COUNT_LIVE_CLUSTERS_SQL
normalized = _COUNT_LIVE_CLUSTERS_SQL.upper().replace(" ", "")
assert "WHEREDELETED_ATISNULL" in normalized  # pre-fix: FAILS; post-fix: PASSES
```

Run the static unit test:

```bash
.venv/bin/pytest backend/tests/unit/scripts/test_seed_meaningful_demos_sql.py -v
```

Pre-fix: `test_count_live_clusters_sql_filters_soft_deleted` fails with `AssertionError: ... must include WHERE deleted_at IS NULL`. Post-fix: passes.

The end-to-end semantic guard at `backend/tests/integration/test_seed_meaningful_demos_if_empty.py::test_count_live_clusters_sql_excludes_soft_deleted_row` exercises the SQL against a real Postgres with a known soft-deleted row; skips when Postgres isn't reachable from the host shell.

## Root cause

- **Owning layer:** install/seed script (cross-cutting with the public `/api/v1/clusters` endpoint, which already filters `deleted_at`).
- **Origin:** [`scripts/seed_meaningful_demos.py:824`](../../../../scripts/seed_meaningful_demos.py#L824) — `SELECT COUNT(*) FROM clusters;`.
- **Propagation:** [`scripts/seed_meaningful_demos.py:866-887`](../../../../scripts/seed_meaningful_demos.py#L866-L887) — `--if-empty` reads the count and false-skips `auto-seed` when count > 0 regardless of liveness.

## Fix design (locked decisions)

1. **Add `WHERE deleted_at IS NULL` to the count SQL.** Cites: idea.md "Proposed fix" (the user-recommended 1-line path) + alignment with the public API's view of "exists" at [`backend/app/db/repo/cluster.py`](../../../../backend/app/db/repo/cluster.py) which filters soft-deleted rows everywhere it lists/counts clusters.
2. **Extract SQL to a module-level constant** (`_COUNT_LIVE_CLUSTERS_SQL`). Cites: enables a fast static guard at the unit-test layer without needing the full docker stack running. Same pattern as `test_dockerfile_runtime_stage.py` from PR #263.
3. **Two-layer regression coverage**: a unit test on the constant (catches the regression-by-edit case — someone deletes the WHERE clause) AND an integration test that runs the SQL end-to-end against a Postgres with a known soft-deleted row (catches the regression-by-semantic case — someone changes the SQL in a way that breaks the actual filter, like swapping `IS NULL` for `= NULL`). Cites: CLAUDE.md Testing Conventions — unit catches static drift, integration catches behavioral drift.

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| unit | [`backend/tests/unit/scripts/test_seed_meaningful_demos_sql.py`](../../../../backend/tests/unit/scripts/test_seed_meaningful_demos_sql.py) | `_COUNT_LIVE_CLUSTERS_SQL` includes `WHERE deleted_at IS NULL` (whitespace-normalized) AND reads `FROM clusters`. Catches regression-by-edit. |
| integration | [`backend/tests/integration/test_seed_meaningful_demos_if_empty.py`](../../../../backend/tests/integration/test_seed_meaningful_demos_if_empty.py) | Seeds 1 soft-deleted cluster row directly via raw SQL; runs the constant via test DB; asserts COUNT = 0. Pre-fix SQL would return 1. Skips when Postgres unreachable. |

## Rollout

Code-only change. No migration, no env var, no operator action. Forward-only — once shipped, the next `make up` on a stack with soft-deleted-only clusters will correctly auto-seed. The bundled sibling fix ([`bug_dashboard_reset_disclosure_gating_too_strict`](../bug_dashboard_reset_disclosure_gating_too_strict/idea.md)) restores the in-product self-rescue path for operators whose stacks predate the auto-seed fix.

## Tangential observations

- [`bug_dashboard_reset_disclosure_gating_too_strict`](../bug_dashboard_reset_disclosure_gating_too_strict/idea.md) — sibling fix shipping in the same PR. The disclosure's predicate is independently too-strict (hides whenever `hasQuerySetsWithJudgments` or `hasStudies` is true), so an operator with orphan data but no live clusters can't see the rescue affordance. Bundling both fixes together fully restores the recovery path.
