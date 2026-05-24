# Home-page demo-data "Reset to demo state" affordance

**Date:** 2026-05-22 (originally drafted 2026-05-21 as `phase2_idea.md` inside `feat_home_first_run_demo_nudge/`; split to this dedicated planned folder at Phase 1 finalization on 2026-05-22 so it surfaces in `/pipeline --status`)
**Status:** Idea — deferred Phase 2 work from `feat_home_first_run_demo_nudge` (Phase 1 merged 2026-05-22 as PR #188 squash `21325432`)
**Priority:** P2
**Origin:** Deferred from `feat_home_first_run_demo_nudge` `feature_spec.md` §3 Out of scope + §19 Decision log. Path resolves to [`docs/00_overview/implemented_features/2026_05_22_feat_home_first_run_demo_nudge/feature_spec.md`](../../../00_overview/implemented_features/2026_05_22_feat_home_first_run_demo_nudge/feature_spec.md) post-finalization.
**Depends on:** `feat_home_first_run_demo_nudge` Phase 1 (PR #188) — merged.

**Still-needed verification (2026-05-23):** confirmed against `main` HEAD —
- PR #188 (`feat(home-first-run-demo-nudge): demo-data banner + cluster Demo indicator + CI parity guard`) merged 2026-05-22 with squash commit `21325432cb4826ed2e2cc01f7fb7698f222498d7` (gh pr view 188).
- [`scripts/seed_meaningful_demos.py:67-78`](../../../../scripts/seed_meaningful_demos.py#L67-L78) declares `TRUNCATE_TABLES` with the exact 10 tables this idea proposes to truncate.
- [`scripts/seed_meaningful_demos.py:702`](../../../../scripts/seed_meaningful_demos.py#L702) `_psql` uses `docker compose exec ... postgres psql ...` (the host-only path this idea cites).
- [`scripts/seed_meaningful_demos.py:579`](../../../../scripts/seed_meaningful_demos.py#L579) — the actual per-scenario function is named `seed_scenario`, NOT `seed_one_scenario`. The proposed shared symbol name is updated accordingly below.
- [`scripts/seed_meaningful_demos.py:724-749`](../../../../scripts/seed_meaningful_demos.py#L724-L749) `truncate_demo_state` ALSO deletes `DEMO_ES_INDICES` + `DEMO_OS_INDICES` after the Postgres TRUNCATE. The original idea's Step 1 only mentioned the Postgres TRUNCATE — capability §1 below now covers the ES/OS index-cleanup step too, without which reseed's first `PUT /{target}` fails on the still-extant index mapping.
- [`backend/app/api/v1/_test.py`](../../../../backend/app/api/v1/_test.py) hosts 7 dev-gated endpoints today (1 POST `seed-completed` at `:127`; 6 DELETEs at `:193,:213,:233,:277,:316,:366`), all guarded by `_require_development_env` (`:56`); the canonical error-envelope helper is `_err` at `:40`.
- [`docs/01_architecture/data-model.md` §317](../../../01_architecture/data-model.md) confirms `audit_log` lands at MVP2.

## Problem

Phase 1 ships the banner + badges that signal "this is demo data." It does NOT close the recovery loop for operators who blew away their dev DB and want to re-seed the meaningful demos from inside the UI rather than dropping back to the host shell to run `make seed-demo FORCE=1`.

The original idea (capability C) proposed a `POST /api/v1/_test/demo/reseed` endpoint gated by the same `_require_development_env` dependency the other test-only endpoints use, paired with a "Reset to demo state" button on the dashboard's empty state.

Implementing C from inside the API container is non-trivial because [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py)'s truncate step uses `docker compose exec postgres psql -c ...` (see [`_psql` at line 702](../../../../scripts/seed_meaningful_demos.py)) — the script is designed to run from the host. Inside the API container there is no docker socket, no `psql` client by default, and no `docker compose` CLI; the truncate must instead use an async SQLAlchemy session.

## Proposed capabilities

### 1. Extract seed orchestration into a service module

- New module: `backend/app/services/demo_seeding.py`
- New function: `async def reseed_demo_state(db: AsyncSession, http_client: httpx.AsyncClient) -> ReseedSummary`. Three steps mirror the CLI's `truncate_demo_state` + `seed_scenario` loop:
  - **Step 1a — Postgres TRUNCATE.** `db.execute(text("TRUNCATE proposals, digests, trials, studies, judgments, judgment_lists, queries, query_sets, query_templates, clusters RESTART IDENTITY CASCADE"))` — same table order as the CLI's `TRUNCATE_TABLES` tuple at [`scripts/seed_meaningful_demos.py:67-78`](../../../../scripts/seed_meaningful_demos.py#L67-L78).
  - **Step 1b — ES/OS index cleanup.** `DELETE` every demo index that the CLI's `truncate_demo_state` clears at [`scripts/seed_meaningful_demos.py:735-749`](../../../../scripts/seed_meaningful_demos.py#L735-L749): `DEMO_ES_INDICES = ("products", "docs-articles", "job-listings")` against ES, `DEMO_OS_INDICES = ("news-articles",)` against OpenSearch. Tolerate 404 on each delete (the demo indices may not exist on a brand-new stack). Without this step Step 2's first `PUT /{target}` would fail because the prior mapping still owns the index.
  - **Step 2 — re-seed the 4 scenarios** using the existing HTTP orchestration (`POST /api/v1/clusters`, `PUT` to ES/OS for index + docs, `POST /api/v1/_test/studies/seed-completed`, etc.). The `httpx.AsyncClient` makes the same calls the CLI's `urllib.request` calls do. Note: the seed flow also calls back into the very `POST /api/v1/_test/studies/seed-completed` endpoint hosted in this same API process — that endpoint is the dev-gate-protected sibling at [`backend/app/api/v1/_test.py:127`](../../../../backend/app/api/v1/_test.py#L127), so the loopback works in development without auth.
  - **Step 3 — return** a `ReseedSummary` Pydantic model carrying `{clusters_created: 4, query_sets_created: 4, studies_completed: 4, duration_ms: int}`.
- The CLI script keeps its existing `docker compose exec` truncate path + `urllib.request` API client unchanged in this phase (locked decision D2 below). Its scenario-loop body at [`scripts/seed_meaningful_demos.py:579`](../../../../scripts/seed_meaningful_demos.py#L579) (`def seed_scenario(s: dict) -> dict`) is what `demo_seeding.py` re-implements in async form; the two stay independent for now (sync `urllib` CLI + async `httpx` service module) to avoid coupling the CLI's risk surface to the new endpoint.

### 2. New gated endpoint

- Route: `POST /api/v1/_test/demo/reseed`
- Module: [`backend/app/api/v1/_test.py`](../../../../backend/app/api/v1/_test.py) (joins the existing 7 dev-gated endpoints: 1 POST at `:127` + 6 DELETEs at `:193,:213,:233,:277,:316,:366`).
- Gating: same `dependencies=[Depends(_require_development_env)]` as the existing endpoints (helper at `:56`). Returns 404 `RESOURCE_NOT_FOUND` outside `ENVIRONMENT=development`.
- Error envelope: raises via the canonical `_err(status_code, code, message, retryable)` helper at [`backend/app/api/v1/_test.py:40`](../../../../backend/app/api/v1/_test.py#L40) so the response shape matches `{detail: {error_code, message, retryable}}` per [`docs/01_architecture/api-conventions.md` §"Error envelope"](../../../01_architecture/api-conventions.md).
- Response body: `ReseedSummary` (HTTP 200) on success.
- Failure modes:
  - 503 `SEED_FAILED` (retryable=true) — the seed orchestration errored mid-flight. The endpoint rolls back the SQLAlchemy session AND attempts a best-effort ES/OS index re-cleanup before returning so the stack lands in a known-empty state rather than partial-seeded; partial-state recovery is the open question Q3 below.
  - 504 `SEED_TIMEOUT` (retryable=true) — the seed exceeded the configured timeout. (Seeds take ~5-10s in dev today; budget defaults to 60s per locked decision D3 below — surfaced as `Settings.demo_reseed_timeout_s`.)
  - 409 `SEED_IN_PROGRESS` (retryable=true) — a concurrent reseed is already running. Default mechanism: `pg_advisory_xact_lock(<demo-reseed-key>)` with `nowait=true` so the second caller immediately 409s instead of blocking; recommended default surfaced as open question Q1.

### 3. UI "Reset to demo state" button

- Placement: dashboard at [`ui/src/app/page.tsx`](../../../../ui/src/app/page.tsx). The empty-data surface today is the `StartHereChecklist` component ([`ui/src/components/dashboard/start-here-checklist.tsx`](../../../../ui/src/components/dashboard/start-here-checklist.tsx)) which is gated on `hasClusters && hasQuerySetsWithJudgments && hasStudies` (renders only when at least one is false). The button rides this same surface — visible when `clustersCount.data === 0 AND recent.data?.totalCount === 0` (a fully-wiped stack). On a partial-state stack the button is hidden (operator might still have work to preserve). Exact placement inside `StartHereChecklist` vs as a sibling card is open question Q2 below.
- Confirmation dialog: identical wording to `make seed-demo`'s `confirm_wipe` prompt at [`scripts/seed_meaningful_demos.py:765`](../../../../scripts/seed_meaningful_demos.py#L765) — quotes the TRUNCATE blast radius before firing the POST.
- Toast on success: "Demo state reset — 4 clusters, 4 query sets, 4 completed studies. Reload to see the dashboard."
- Toast on failure: "Reseed failed: {error_code}. Try again, or run `make seed-demo FORCE=1` from the host."

### 4. Audit-event instrumentation (MVP2+)

- When [`audit_log` lands at MVP2](../../../01_architecture/data-model.md), emit one event per reseed:
  - `event_type`: `demo.reseed.completed`
  - `metadata`: `{clusters_created: int, studies_completed: int, duration_ms: int}`
  - `visibility`: `system` (no tenant context yet in MVP2).
- The endpoint inserts the audit row in the same transaction as the TRUNCATE+seed, per CLAUDE.md's audit-emission discipline.

## Decisions locked

- **D1 — `httpx.AsyncClient` self-call over service-function extraction.** The new `reseed_demo_state` POSTs back into its own API process via `httpx.AsyncClient(base_url="http://localhost:8000/api/v1")` rather than refactoring `seed_scenario`'s body to call the underlying service functions directly. **Why:** the CLI already proves the HTTP-orchestration path is correct; calling service functions directly would require auditing every call site (`POST /clusters` → cluster service; `POST /query-templates` → templates service; etc.) for transaction-boundary semantics, which is a much larger refactor for no operator-visible win. **How to apply:** the service module imports `httpx` and constructs a per-request client; the existing test-only `_test/studies/seed-completed` POST is a loopback call from within the same process.
- **D2 — CLI script unchanged in this phase.** `scripts/seed_meaningful_demos.py` keeps its `docker compose exec` truncate + `urllib.request` API client. The new `backend/app/services/demo_seeding.py` is purely additive — no shared imports between CLI and service module in this phase. **Why:** unifying the two would couple this feature's risk surface to a working CLI tool and double the test matrix without operator-visible value. **How to apply:** the spec/plan explicitly call out that the CLI's behavior MUST remain bit-exact; CI smoke against `make seed-demo` continues to assert this.
- **D3 — Reseed timeout configurable via settings, default 60s.** New `demo_reseed_timeout_s: int = 60` field on `Settings` (no `_FILE` suffix — not a secret). **Why:** seeds take 5-10s in dev today, but slower laptops or CI runners may need headroom; surfacing as a setting avoids a future code change. **How to apply:** orchestrator wraps `reseed_demo_state(...)` in `asyncio.wait_for(..., timeout=settings.demo_reseed_timeout_s)`; on timeout raise `_err(504, "SEED_TIMEOUT", ..., retryable=True)`.

## Open questions for /spec-gen

- **Q1 — Concurrent reseed guard.** Two operators hitting "Reset to demo state" simultaneously would interleave TRUNCATEs and POSTs unsafely. **Recommended default:** `pg_advisory_xact_lock(<demo-reseed-key>)` with `nowait=true`; second caller gets 409 `SEED_IN_PROGRESS` (retryable=true). Alternative considered: single-flight queue with cancellation token — over-engineered for a dev-only endpoint.
- **Q2 — UI button placement.** Phase 1 already owns the dashboard's empty surface via `StartHereChecklist` + `DemoDataBanner`. **Recommended default:** add the Reset button as a secondary action *inside* `StartHereChecklist` (e.g., below the existing onboarding steps, behind a `<details>` disclosure labeled "or skip ahead — reset to demo state") so it doesn't compete visually with the primary onboarding path. Alternative: a separate `<Card>` below the checklist, hidden unless both `clustersCount.data === 0` AND `recent.data?.totalCount === 0`.
- **Q3 — Partial-state recovery on `SEED_FAILED`.** The reseed touches three side-effect surfaces (Postgres + ES + OpenSearch). A mid-flight failure rolls back only Postgres; ES/OS indices created so far stay. **Recommended default:** on 503, attempt a best-effort `truncate_demo_state`-equivalent cleanup (re-TRUNCATE the Postgres tables that may have partial inserts + re-DELETE every demo index, ignoring 404s) before returning. Log the cleanup outcome. **Alternative:** leave partial state in place and instruct the operator to run `make seed-demo FORCE=1` from the host. Hidden in the alternative: a stuck stack the operator has to debug.

## Scope signals

- **Backend:** ~250 LOC (seed_demos service module: ~180 + endpoint: ~50 + tests: ~20). Three new error codes (`SEED_FAILED`, `SEED_TIMEOUT`, `SEED_IN_PROGRESS`).
- **Frontend:** ~50 LOC (button + confirmation dialog + toast wiring + 2 vitest cases + 1 E2E assertion).
- **Migration:** none.
- **Config:** one new `Settings.demo_reseed_timeout_s` (int, default 60).
- **Audit events:** 1 new (`demo.reseed.completed`) — activates at MVP2.
- **Dependencies on third-party libs already in `pyproject.toml`:** `httpx` (already used by the contract-test layer + capability check) — confirm during impl-plan-gen; `sqlalchemy.ext.asyncio` (already in MVP1 via `backend/app/db/session.py`).

## Why deferred

Phase 1 is a polish layer over data PR #182 already plants on `make up`. The banner + badges deliver the "is this demo data?" UX in a frontend-only PR with zero backend risk. Capability C requires:

1. Extracting `scripts/seed_meaningful_demos.py`'s truncate logic out of `docker compose exec` (and possibly all of the seed orchestration) into a Python module that's importable from inside the API container.
2. Adding `httpx` import + ~180 LOC of service code that's currently CLI-only.
3. A new endpoint with two new error codes.
4. UI work for the confirmation dialog + toast pattern.

That's a feature, not a polish layer. Bundling it with Phase 1 would (a) push the PR to ~600 LOC, (b) mix frontend and backend in one PR (against the "scope-blur" rubric for cross-subsystem work), and (c) couple the banner UX to the seed-script refactor's risk.

Phase 2 ships when (a) Phase 1 has been live long enough to observe whether the "Reset" affordance is actually requested, and (b) someone is already in the seed-script codebase for unrelated reasons (cheaper to refactor when context is loaded).

## Relationship to other work

- **Supersedes:** capability C from the original [`feat_home_first_run_demo_nudge/idea.md`](../../../00_overview/implemented_features/2026_05_22_feat_home_first_run_demo_nudge/idea.md).
- **Composes with:** Phase 1 of [`feat_home_first_run_demo_nudge`](../../../00_overview/implemented_features/2026_05_22_feat_home_first_run_demo_nudge/feature_spec.md) — the reseed button shares the dashboard's empty-state real estate; Phase 1 reserved no UI space for it, so Phase 2 adds the button as a new empty-state slot.
- **Coordinates with:** future MVP2 audit-log work — the reseed endpoint MUST emit an audit event once `audit_log` exists.
