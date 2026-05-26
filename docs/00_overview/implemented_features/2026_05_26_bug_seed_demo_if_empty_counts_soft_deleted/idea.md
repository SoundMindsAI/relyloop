---
name: bug-seed-demo-if-empty-counts-soft-deleted
description: scripts/seed_meaningful_demos.py's count_existing_clusters() doesn't filter deleted_at IS NULL — a single E2E run that soft-deletes clusters permanently disables auto-seed-on-empty until manual `make seed-demo FORCE=1`
metadata:
  type: bug
---

# Bug — `seed_meaningful_demos.py --if-empty` counts soft-deleted clusters, false-skips auto-seed forever

**Date:** 2026-05-26
**Status:** Idea — surfaced during interactive debugging of "no clusters after `make down` + `make up`" (operator session 2026-05-26 evening, immediately after PRs #265/#266 landed).
**Priority:** P2 — every operator who has run E2E tests then restarted the stack sees an empty dashboard with no auto-recovery path. Workaround is `make seed-demo FORCE=1`, but the operator has to know that exists; the dashboard's "Reset to demo state" disclosure is also hidden (separate bug: [`bug_dashboard_reset_disclosure_gating_too_strict`](../bug_dashboard_reset_disclosure_gating_too_strict/idea.md)) so the affordance the spec assumed would self-rescue is missing.
**Depends on:** None.

## Origin

Surfaced during interactive debugging after the operator did `make down && make up` post-PR-#265-merge. Expected behavior (per `install.sh:83-96` comment block): "auto-seed meaningful demo data when the stack is empty (idempotent)." Actual behavior: empty dashboard with `/api/v1/clusters` returning `data: []` despite the auto-seed step apparently running.

Diagnosis trace:
- `docker compose exec postgres psql -c "SELECT count(*) FROM clusters"` → **7**
- `docker compose exec postgres psql -c "SELECT id, name, deleted_at FROM clusters"` → all 7 had non-null `deleted_at` (~2026-05-26 13:32-13:33 UTC, from earlier E2E test cleanup that day).
- `curl http://localhost:8000/api/v1/clusters` → `data: []` (the public list endpoint correctly filters soft-deleted rows).
- `scripts/seed_meaningful_demos.py:824` runs `SELECT COUNT(*) FROM clusters` with NO `WHERE deleted_at IS NULL` filter.
- Auto-seed at `install.sh:95` (`python3 scripts/seed_meaningful_demos.py --if-empty`) saw "7 clusters exist" → skipped.
- Operator was stuck on an empty UI with no in-product affordance to recover.

## Problem

[`scripts/seed_meaningful_demos.py:775-825`](../../../scripts/seed_meaningful_demos.py#L775-L825) — `count_existing_clusters()`:

```python
result = subprocess.run([
    "docker", "compose", "exec", "-T", "postgres",
    "psql", "-U", "relyloop", "-d", "relyloop", "-tA",
    "-c", "SELECT COUNT(*) FROM clusters;",
], ...)
return int(result.stdout.strip())
```

The query is COUNT-all, not COUNT-of-non-deleted. The `--if-empty` branch at line 866-887 uses this count to decide whether to seed:

```python
if args.if_empty:
    existing = count_existing_clusters()
    ...
    if existing > 0:
        print(f"seed-demo: skipping — {existing} cluster(s) already exist. ...")
        return 0
    ...
```

Effect: once any cluster row exists in the table (even soft-deleted from a test cleanup, an operator's manual delete, or a previous seed-then-wipe cycle), the auto-seed permanently false-skips on every subsequent `make up` until someone manually wipes via `make seed-demo FORCE=1` or `make reset`.

## Proposed fix

One-line change at [`scripts/seed_meaningful_demos.py:824`](../../../scripts/seed_meaningful_demos.py#L824):

```diff
-                    "SELECT COUNT(*) FROM clusters;",
+                    "SELECT COUNT(*) FROM clusters WHERE deleted_at IS NULL;",
```

This aligns the auto-seed gate with the public API's view of "exists": both treat soft-deleted rows as gone.

### Regression test

`backend/tests/integration/test_seed_meaningful_demos_if_empty.py` (new file, ~40 LOC):

1. Seed one cluster row directly via repo with `deleted_at=datetime.now(UTC)`.
2. Run `python3 scripts/seed_meaningful_demos.py --if-empty` via subprocess.
3. Assert exit code 0 AND the 4 demo scenarios were created (counts of `clusters WHERE deleted_at IS NULL` go from 0 → 4).

The integration test mirrors `backend/tests/integration/test_test_seeding.py`'s pattern. It would skip locally without Postgres but run in CI.

## Why deferred from this session

Surfaced during operator debugging of "no clusters after restart," not during a planned bug-fix flow. The immediate operator unblock (`make seed-demo FORCE=1`) was applied; the underlying script bug is a separate ~1-line fix + regression test that should ship as its own focused PR. Bundling it into the active session would have mixed an interactive debugging unblock with a deliberate code change.

## Scope signals

- **Backend:** None (script-only fix; `scripts/seed_meaningful_demos.py`).
- **Frontend:** None.
- **Migration:** None.
- **Config:** None.
- **Audit events:** None (pre-MVP2).
- **Tests:** 1 new integration test file (~40 LOC) under `backend/tests/integration/`.

## Relationship to other work

- **Sibling bug:** [`bug_dashboard_reset_disclosure_gating_too_strict`](../bug_dashboard_reset_disclosure_gating_too_strict/idea.md) — the in-product "Reset to demo state" affordance that would normally self-rescue from this state is hidden too aggressively. Together these two bugs leave operators with no recovery path other than CLI knowledge of `make seed-demo FORCE=1`. Fixing either bug alone restores recovery; fixing both is cleaner.
- **Surfaced after** PRs #265 / #266 merged on 2026-05-26. Not related to either of those changes — pre-existing condition activated by E2E tests soft-deleting their fixtures.
