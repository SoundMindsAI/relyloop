# Phase 2 — Orchestrator + API (deferred from Phase 1)

**Date:** 2026-05-10
**Status:** Idea — deferred from Phase 1 (Schema) implementation. Generates a fresh `implementation_plan.md` when Phase 1 + `infra_optuna_eval` have both shipped.
**Origin:** [`feature_spec.md` §3 Phase boundaries](feature_spec.md) — split decided 2026-05-10 to unblock `infra_optuna_eval`'s `run_trial` job (which depends on `studies` + `trials` tables existing). Phase 1's `implementation_plan.md` ships the schema; Phase 2 ships the API + orchestrator.

## Depends on

- **Phase 1 of `feat_study_lifecycle` merged** — provides the 7 tables (`query_templates`, `query_sets`, `queries`, `studies`, `trials`, `judgment_lists`, `proposals`) and minimal repos.
- **`infra_optuna_eval` merged** — provides the `run_trial` Arq job that the orchestrator (FR-4) enqueues. Without `run_trial`, `start_study` has nothing to dispatch.

## Problem (gap remaining after Phase 1)

After Phase 1 ships, the 7 tables exist but nothing populates them through user-facing code paths. Operators can't:

- Create studies via API
- Create / list query-sets, query-templates
- Upload queries to a query-set (CSV or JSON)
- Cancel a running study
- Watch trials accumulate
- Resume a `running` study after orchestrator restart

## Proposed capabilities (from spec §7)

The seven FRs deferred to Phase 2:

| FR | Surface | Notes |
|---|---|---|
| **FR-1** Study CRUD endpoints | `POST /api/v1/studies`, `GET /api/v1/studies` (cursor-paginated + status filter + `?since=`), `GET /api/v1/studies/{id}` (incl. live trials summary), `POST /api/v1/studies/{id}/cancel` | The `cancel` endpoint flips `status` to `cancelled`; the orchestrator polls and drains. |
| **FR-2** Query-template CRUD | `POST /api/v1/query-templates`, `GET /api/v1/query-templates`, `GET /api/v1/query-templates/{id}` | Templates are versioned via `(name, version)` UNIQUE in Phase 1's schema. |
| **FR-3** Query-set CRUD | `POST /api/v1/query-sets`, `GET /api/v1/query-sets`, `GET /api/v1/query-sets/{id}`, `POST /api/v1/query-sets/{id}/queries` (bulk JSON or CSV upload) | Cluster-scoped per spec §3. |
| **FR-4** Orchestrator process | `start_study` Arq job in `backend/worker/orchestrator.py` — transitions `studies.status: queued → running`, enqueues `studies.config.parallelism` `run_trial` jobs, polls for `cancelled`, fires stop conditions (`max_trials` reached OR `time_budget_min` exceeded), denormalizes `best_metric` + `best_trial_id`, enqueues digest job (`feat_digest_proposal` consumes). | Hot path — depends on `infra_optuna_eval`. |
| **FR-5** Resume-after-restart | Orchestrator process picks up `running` studies on startup and re-enters the polling loop. | No data loss on worker restart. |
| **FR-6** Trials list endpoint | `GET /api/v1/studies/{id}/trials` (cursor-paginated, sortable by `primary_metric`) | Uses Phase 1's `trials_study_metric` index. |
| **FR-7** State-transition guard | Service-layer functions (`start_study()`, `cancel_study()`, `complete_study()`) are the only legal mutators of `studies.status`. Direct `UPDATE studies SET status = ...` outside the service layer is forbidden. | Test layer asserts a contract test that bypassing the service raises. |

## Scope signals

- **Backend:** **12 endpoints** + the orchestrator Arq job + a service layer (state machine + guards) + ~15 additional repo functions (cursor pagination, status filtering, `since=` filtering, bulk CSV upload helper). Endpoint count enumerated from spec §8 (mislabeled `### 7.1` due to known template drift):
  - `POST /api/v1/studies`
  - `GET /api/v1/studies` — list endpoint: cursor-paginated + status filter + `?since=` + `X-Total-Count`
  - `GET /api/v1/studies/{id}` (incl. `trials_summary`)
  - `POST /api/v1/studies/{id}/cancel`
  - `GET /api/v1/studies/{id}/trials` — list endpoint: cursor-paginated + sortable + `?since=` + `X-Total-Count`
  - `POST /api/v1/query-templates`
  - `GET /api/v1/query-templates` — list endpoint: cursor-paginated + `?since=` + `X-Total-Count`
  - `GET /api/v1/query-templates/{id}`
  - `POST /api/v1/query-sets`
  - `POST /api/v1/query-sets/{id}/queries` (JSON or CSV upload)
  - `GET /api/v1/query-sets` — list endpoint: cursor-paginated + `?since=` + `X-Total-Count`
  - `GET /api/v1/query-sets/{id}` (incl. count)

  **All 4 list endpoints** (`/studies`, `/studies/{id}/trials`, `/query-sets`, `/query-templates`) inherit the spec's §3 API convention check: cursor pagination (default `limit=50`, max `200`); `?since=<iso8601>` filter; `X-Total-Count` response header. Phase 2's plan must include integration + contract tests for each of these 4 cross-cutting behaviors per endpoint (12 test combinations).
- **Frontend:** N/A in Phase 2 — UI is `feat_studies_ui`.
- **Migration:** N/A in Phase 2 — Phase 1 already created every table in its full MVP1 shape per spec §3 ("downstream features only INSERT/UPDATE rows, they don't ALTER schemas").
- **Config:** Possibly a `STUDIES_DEFAULT_PARALLELISM` setting (default 4); a `STUDIES_DEFAULT_TIMEOUT_S` setting (default 60s, per `infra_optuna_eval` decision-log).
- **Worker pool:** Adds the `start_study` job to `WorkerSettings.functions` alongside `run_trial`.

## Why deferred

Per the spec line 16:

> ship the schema migration as the first story (unblocks `infra_optuna_eval` and downstream feature migrations). API endpoints (FR-1..6) and the orchestrator (FR-4 + FR-5) ship as later stories AFTER `infra_optuna_eval` lands the `run_trial` job. The plan generator should split this feature into a "schema" epic (no orchestrator dependency) and an "orchestrator + API" epic (depends on `infra_optuna_eval`).

The orchestrator (FR-4) calls `run_trial` from `infra_optuna_eval`. Without that job shipped, the orchestrator has nothing to dispatch — the `start_study` job would be a stub, the integration tests for the full ask/tell loop would have nothing to assert, and the AC-1 (`create a study, watch it run, completes via max_trials`) would be unverifiable.

The cleanest sequence is therefore:
1. **Phase 1** (this PR) — schema + minimal repos.
2. **`infra_optuna_eval`** — Optuna RDB bootstrap + pytrec_eval helper + `run_trial` job. Now that Phase 1's tables exist, `run_trial` can read `studies` and write `trials`.
3. **Phase 2** (this idea file) — orchestrator + API. Now that `run_trial` exists, `start_study` has something to dispatch.

## Acceptance criteria (from spec §12, all 10 ACs)

When Phase 2 lands, every AC in the spec must pass:

- AC-1: Create study via API → trials accumulate → completes via `max_trials`.
- AC-2: Stop via `time_budget_min` exceeded.
- AC-3: `POST /studies/{id}/cancel` → drained + status `cancelled`.
- AC-4: Orchestrator restart mid-study → resume loop picks up `running` study.
- AC-5: Cluster failure mid-study → individual trials transition to `failed`; **after 5 consecutive failures** the study transitions to `failed` with `failed_reason` populated; subsequent `GET /studies/{id}` returns the failure detail.
- AC-6: Service-layer guard prevents direct DB UPDATE of `studies.status` — direct ORM writes raise `StudyStateProtectionError`.
- AC-7: Template Jinja2 sandbox security — a `POST /query-templates` with body `{{ os.system('rm -rf /') }}` returns HTTP 400 `INVALID_TEMPLATE_SYNTAX` (Jinja2 SandboxedEnvironment rejects forbidden access); no row is created. (StrictUndefined / declared_params↔body cross-check is FR-2 functional behavior tested by `test_template_validator.py`, not AC-7.)
- AC-8: CSV upload to query-set works end-to-end (`POST /query-sets/{id}/queries` with `Content-Type: text/csv`).
- AC-9: Cursor pagination on every list endpoint (`/studies`, `/studies/{id}/trials`, `/query-sets`, `/query-templates`).
- AC-10: Trials list is sortable by `primary_metric_desc` / `primary_metric_asc` / `created_at_desc` / `created_at_asc` / `optuna_trial_number_asc` (uses Phase 1's `trials_study_metric` index for the metric-sorted variants).

## Test files: Phase 1 vs Phase 2 trace

Per cycle 1 GPT-5.5 F4 — explicit trace so Phase 2 plan-generation knows what tests already exist vs what's still to write:

**Phase 1 ships** (in `implementation_plan.md` §3.2):
- `backend/tests/integration/test_study_lifecycle_migration.py` — schema round-trip + CHECK + FK + UNIQUE + index assertions.
- `backend/tests/integration/test_study_repos.py` — 15 repo function round-trips.

**Phase 2 ships** (from spec §14 — write when generating Phase 2's `implementation_plan.md`):
- `backend/tests/unit/services/test_study_state.py` — state-machine: legal transitions succeed, illegal raise `StudyStateProtectionError`.
- `backend/tests/unit/domain/test_template_validator.py` — Jinja2 SandboxedEnvironment + declared_params ↔ body cross-check.
- `backend/tests/unit/domain/test_search_space_validator.py` — Pydantic `search_space` schema rejects malformed inputs.
- `backend/tests/integration/test_study_lifecycle.py` — full create → run → complete cycle against seeded local-es; asserts AC-1, AC-2, AC-5, AC-10.
- `backend/tests/integration/test_study_cancel.py` — AC-3 (cancel during running).
- `backend/tests/integration/test_study_resume.py` — AC-4 (kill + restart orchestrator).
- `backend/tests/integration/test_csv_upload.py` — AC-8.
- `backend/tests/integration/test_pagination.py` — AC-9 (cursor pagination on all 4 list endpoints).
- `backend/tests/contract/test_studies_api_contract.py` — request/response shapes vs OpenAPI.
- `backend/tests/contract/test_error_codes.py` — every code in spec §8.5 produces the documented HTTP + envelope.

## Plan generation

When Phase 2 is unblocked (Phase 1 + `infra_optuna_eval` both merged), generate the Phase 2 implementation_plan.md by:

```bash
/impl-plan-gen docs/02_product/planned_features/feat_study_lifecycle/feature_spec.md
```

The plan generator should auto-detect from the spec's §3 Phase boundaries that Phase 1 is shipped (folder will have moved to `implemented_features/<date>_feat_study_lifecycle_phase1/` after merge — actually no, the folder stays in `planned_features/` until **Phase 2 ships** because the feature isn't done; only Phase 1's plan flips status to "Complete"). The Phase 2 plan supersedes this idea file.

Actually clarification needed: when Phase 1 ships, the canonical post-merge finalization (impl-execute Step 8) usually moves the feature folder to `implemented_features/`. For multi-phase features, the folder should **stay** in `planned_features/` until the LAST phase ships. The Phase 1 finalization should:

- Flip Phase 1's `implementation_plan.md` status to "Phase 1 Complete (PR #N, merged YYYY-MM-DD); Phase 2 deferred"
- Flip `pipeline_status.md` Implement section to "Phase 1 complete"
- **Leave the folder in `planned_features/`** — it's not done.
- Add a top-level `phase2_idea.md` (this file) to the folder, surfaced in `/pipeline status`.

The impl-execute Step 8 finalization workflow's existing "Step 6: Check for unimplemented phase idea files" handler is designed for exactly this case — when it sees `phase*_idea.md`, it stops and asks for instructions before moving the folder. The right answer for `feat_study_lifecycle` Phase 1 is "do not move the folder yet."

## Cross-references

- [`feature_spec.md`](feature_spec.md) — full feature spec; §3 Phase boundaries documents the split; §7 lists FR-1 through FR-7.
- [`implementation_plan.md`](implementation_plan.md) — Phase 1 plan (schema + minimal repos).
- [`infra_optuna_eval/feature_spec.md`](../infra_optuna_eval/feature_spec.md) — the dependency that gates Phase 2.
- [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md) — the 7-table column-level shapes (Phase 1 implements these; Phase 2 doesn't `ALTER`).
