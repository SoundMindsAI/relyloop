# Phase 2 — Home-page demo-data "Reset to demo state" affordance

**Date:** 2026-05-21
**Status:** Idea — deferred from Phase 1 of [`feat_home_first_run_demo_nudge`](feature_spec.md)
**Priority:** P2
**Origin:** Deferred Phase 2 work from [`feature_spec.md` §3 Out of scope + §19 Decision log](feature_spec.md) (2026-05-21 decision: extracting the seed orchestration is too much for a polish-layer PR)
**Depends on:** Phase 1 of [`feat_home_first_run_demo_nudge`](feature_spec.md) merged

## Problem

Phase 1 ships the banner + badges that signal "this is demo data." It does NOT close the recovery loop for operators who blew away their dev DB and want to re-seed the meaningful demos from inside the UI rather than dropping back to the host shell to run `make seed-demo FORCE=1`.

The original idea (capability C) proposed a `POST /api/v1/_test/demo/reseed` endpoint gated by the same `_require_development_env` dependency the other test-only endpoints use, paired with a "Reset to demo state" button on the dashboard's empty state.

Implementing C from inside the API container is non-trivial because [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py)'s truncate step uses `docker compose exec postgres psql -c ...` (see [`_psql` at line 702](../../../../scripts/seed_meaningful_demos.py)) — the script is designed to run from the host. Inside the API container there is no docker socket, no `psql` client by default, and no `docker compose` CLI; the truncate must instead use an async SQLAlchemy session.

## Proposed capabilities

### 1. Extract seed orchestration into a service module

- New module: `backend/app/services/demo_seeding.py`
- New function: `async def reseed_demo_state(db: AsyncSession, http_client: httpx.AsyncClient) -> ReseedSummary`
  - Step 1: `db.execute(text("TRUNCATE proposals, digests, trials, studies, judgments, judgment_lists, queries, query_sets, query_templates, clusters RESTART IDENTITY CASCADE"))` — same table order as the CLI's `TRUNCATE_TABLES` tuple at [`scripts/seed_meaningful_demos.py:67-78`](../../../../scripts/seed_meaningful_demos.py).
  - Step 2: re-seed the 4 scenarios using the existing HTTP orchestration (POST to `/api/v1/clusters`, ES/OS index creation, etc.). The httpx client makes the same calls the CLI's `urllib.request` calls do.
  - Step 3: return a `ReseedSummary` Pydantic model carrying `{clusters_created: 4, query_sets_created: 4, studies_completed: 4, duration_ms: int}`.
- The CLI script keeps its existing `docker compose exec` truncate path for the host-side use case, but its scenario-loop body imports `from backend.app.services.demo_seeding import seed_one_scenario` so the bulk of orchestration is shared. (Alternative: also adopt the asyncpg path in the CLI, dropping the `docker compose exec` dependency entirely. Decide during impl-plan-gen.)

### 2. New gated endpoint

- Route: `POST /api/v1/_test/demo/reseed`
- Module: [`backend/app/api/v1/_test.py`](../../../../backend/app/api/v1/_test.py)
- Gating: same `dependencies=[Depends(_require_development_env)]` as the existing 7 test-only endpoints. Returns 404 `RESOURCE_NOT_FOUND` outside `ENVIRONMENT=development`.
- Response body: `ReseedSummary` (HTTP 200) on success.
- Failure modes:
  - 503 `SEED_FAILED` (retryable=true) — the seed script errored mid-flight; the endpoint rolls back the SQLAlchemy session before returning.
  - 504 `SEED_TIMEOUT` (retryable=true) — the seed exceeded a 60s budget. (Seeds take ~5-10s in dev today.)

### 3. UI "Reset to demo state" button

- Placement: dashboard empty-state — only renders when `studies==0 AND clusters==0` (i.e., a fully-wiped stack). On a partial-state stack the button is hidden (operator might still have work to preserve).
- Confirmation dialog: identical wording to `make seed-demo`'s prompt — quotes the TRUNCATE blast radius before firing the POST.
- Toast on success: "Demo state reset — 4 clusters, 4 query sets, 4 completed studies. Reload to see the dashboard."
- Toast on failure: "Reseed failed: {error_code}. Try again, or run `make seed-demo FORCE=1` from the host."

### 4. Audit-event instrumentation (MVP2+)

- When [`audit_log` lands at MVP2](../../../01_architecture/data-model.md), emit one event per reseed:
  - `event_type`: `demo.reseed.completed`
  - `metadata`: `{clusters_created: int, studies_completed: int, duration_ms: int}`
  - `visibility`: `system` (no tenant context yet in MVP2).
- The endpoint inserts the audit row in the same transaction as the TRUNCATE+seed, per CLAUDE.md's audit-emission discipline.

## Scope signals

- **Backend:** ~250 LOC (seed_demos service module: ~180 + endpoint: ~50 + tests: ~20). One new error-code group (`SEED_FAILED`, `SEED_TIMEOUT`).
- **Frontend:** ~50 LOC (button + confirmation dialog + toast wiring + 2 vitest cases + 1 E2E assertion).
- **Migration:** none.
- **Config:** none.
- **Audit events:** 1 new (`demo.reseed.completed`) — activates at MVP2.

## Why deferred

Phase 1 is a polish layer over data PR #182 already plants on `make up`. The banner + badges deliver the "is this demo data?" UX in a frontend-only PR with zero backend risk. Capability C requires:

1. Extracting `scripts/seed_meaningful_demos.py`'s truncate logic out of `docker compose exec` (and possibly all of the seed orchestration) into a Python module that's importable from inside the API container.
2. Adding `httpx` import + ~180 LOC of service code that's currently CLI-only.
3. A new endpoint with two new error codes.
4. UI work for the confirmation dialog + toast pattern.

That's a feature, not a polish layer. Bundling it with Phase 1 would (a) push the PR to ~600 LOC, (b) mix frontend and backend in one PR (against the "scope-blur" rubric for cross-subsystem work), and (c) couple the banner UX to the seed-script refactor's risk.

Phase 2 ships when (a) Phase 1 has been live long enough to observe whether the "Reset" affordance is actually requested, and (b) someone is already in the seed-script codebase for unrelated reasons (cheaper to refactor when context is loaded).

## Relationship to other work

- **Supersedes:** capability C from the original [`idea.md`](idea.md).
- **Composes with:** Phase 1 of [`feat_home_first_run_demo_nudge`](feature_spec.md) — the reseed button shares the dashboard's empty-state real estate; Phase 1 reserved no UI space for it, so Phase 2 adds the button as a new empty-state slot.
- **Coordinates with:** future MVP2 audit-log work — the reseed endpoint MUST emit an audit event once `audit_log` exists.
