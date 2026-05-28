# Phase 2 — Orchestrator + API (unblocked 2026-05-10)

**Date:** 2026-05-10 (idea written) · **Unblocked:** 2026-05-10 (both deps shipped today) · **Preflight audit:** 2026-05-10
**Status:** Ready for `/pipeline` — both gating dependencies have shipped. Phase 2 generates the Phase 2 implementation plan from the existing approved `feature_spec.md` (the spec covers both phases per its §3 "Phase boundaries"; Phase 1 is now done and Phase 2's FRs are FR-1..FR-7 minus the schema work already completed in Phase 1).
**Origin:** [`feature_spec.md` §3 Phase boundaries](feature_spec.md) — split decided 2026-05-10 to unblock `infra_optuna_eval`'s `run_trial` job (which depends on `studies` + `trials` tables existing). Phase 1's `implementation_plan.md` shipped the schema; Phase 2 ships the API + orchestrator.

## Depends on

- ✅ **Phase 1 of `feat_study_lifecycle` merged** (PR #18, 2026-05-10, squash commit `d74e1be`) — shipped the 7 tables (`query_templates`, `query_sets`, `queries`, `studies`, `trials`, `judgment_lists`, `proposals`) and 15 minimal repos.
- ✅ **`infra_optuna_eval` merged** (PR #23, 2026-05-10, squash commit `c4f1aab`) — shipped the `run_trial` Arq job that the orchestrator (FR-4) enqueues, plus `WorkerSettings.on_startup` that constructs Optuna `RDBStorage` at boot. `start_study` can now dispatch concrete work.

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
| **FR-4** Orchestrator process | `start_study` Arq job in `backend/workers/orchestrator.py` — transitions `studies.status: queued → running`, enqueues `studies.config.parallelism` `run_trial` jobs, polls for `cancelled`, fires stop conditions (`max_trials` reached OR `time_budget_min` exceeded), denormalizes `best_metric` + `best_trial_id`, enqueues digest job (`feat_digest_proposal` consumes). | Hot path — calls into `backend/workers/trials.py:run_trial` (shipped 2026-05-10 by `infra_optuna_eval`). |
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

  **All 4 list endpoints** (`/studies`, `/studies/{id}/trials`, `/query-sets`, `/query-templates`) inherit the spec's §3 API convention check: cursor pagination (default `limit=50`, max `200`); `?since=<iso8601>` filter; `X-Total-Count` response header. Phase 2's plan must include integration + contract tests for each of these **3 cross-cutting behaviors** per endpoint (12 test combinations — 4 endpoints × 3 behaviors).
- **Frontend:** N/A in Phase 2 — UI is `feat_studies_ui`.
- **Migration:** N/A in Phase 2 — Phase 1 already created every table in its full MVP1 shape per spec §3 ("downstream features only INSERT/UPDATE rows, they don't ALTER schemas").
- **Config:** Two backend Settings fields to introduce, matching the existing plain-env-var convention from [`CLAUDE.md` §"Settings & Secrets"](../../../../CLAUDE.md): `STUDIES_DEFAULT_PARALLELISM` (default 4) and `STUDIES_DEFAULT_TIMEOUT_S` (default 60s). These provide the **fallback** when an operator's `POST /studies` payload omits `config.parallelism` / `config.trial_timeout_s`; the per-study JSON values in `studies.config` (already in the Phase 1 schema and consumed by `infra_optuna_eval`'s `run_trial`) take precedence when present. Open for spec-gen: should the API materialize defaults into the stored row, or leave the keys omitted (matching `infra_optuna_eval` spec FR-2's "Phase 2's API is required NOT to materialize defaults into the stored row" — the pruner key-presence contract relies on this)? Recommended default: leave omitted; the worker reads Settings at job time. See "Open questions" below.
- **Worker pool:** `WorkerSettings.functions` already lists `run_trial` (added 2026-05-10 by `infra_optuna_eval`). Phase 2 appends `start_study`. `WorkerSettings.on_startup` already seeds `ctx["optuna_storage"]` once per worker — `start_study` can read it directly without re-constructing.

## Why this was deferred (historical — now unblocked)

Per the spec line 16:

> ship the schema migration as the first story (unblocks `infra_optuna_eval` and downstream feature migrations). API endpoints (FR-1..6) and the orchestrator (FR-4 + FR-5) ship as later stories AFTER `infra_optuna_eval` lands the `run_trial` job. The plan generator should split this feature into a "schema" epic (no orchestrator dependency) and an "orchestrator + API" epic (depends on `infra_optuna_eval`).

The orchestrator (FR-4) calls `run_trial` from `infra_optuna_eval`. Until that job shipped, the orchestrator would have had nothing to dispatch — the `start_study` job would have been a stub, the integration tests for the full ask/tell loop would have had nothing to assert, and AC-1 (`create a study, watch it run, completes via max_trials`) would have been unverifiable.

The sequence executed cleanly:
1. ✅ **Phase 1** — schema + minimal repos (PR #18, merged 2026-05-10).
2. ✅ **`infra_optuna_eval`** — Optuna RDB bootstrap + pytrec_eval helper + `run_trial` job (PR #23, merged 2026-05-10). Phase 1's tables let `run_trial` read `studies` and write `trials`.
3. **Phase 2** (this idea file) — orchestrator + API. **Both upstream PRs landed today; Phase 2 is now ready to enter the pipeline.** `start_study` will dispatch the shipped `run_trial`.

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

The canonical invocation for Phase 2 is:

```bash
/impl-plan-gen docs/00_overview/planned_features/feat_study_lifecycle/feature_spec.md
```

The spec covers both phases — its §3 "Phase boundaries" enumerates which FRs land in Phase 1 vs Phase 2. The plan generator reads the existing approved `feature_spec.md` (which Phase 1's plan already shipped against), detects that Phase 1 is complete (via the marker in `implementation_plan.md`'s status header), and emits a Phase 2-only implementation plan. No new spec generation is required — the existing spec is authoritative.

**Coordination with `/pipeline`:** the pipeline orchestrator's PARTIAL handling (see [`.claude/skills/pipeline/SKILL.md`](../../../../.claude/skills/pipeline/SKILL.md)) prescribes `/pipeline <feature>/phase<N+1>_idea.md`, which would run `/spec-gen` FIRST against the idea file. For this feature that would regenerate a spec we already have. The simpler invocation above bypasses spec-gen. **If pipeline-mode is preferred for the audit trail, run `/pipeline ... --from plan` to skip the spec-gen stage** — same outcome, slightly more ceremony.

When Phase 2's plan exists alongside Phase 1's:

- Both `implementation_plan.md` (Phase 1, Complete) and `phase2_implementation_plan.md` (Phase 2, to be generated) coexist in the folder until Phase 2 ships.
- This idea file is superseded by the Phase 2 plan and becomes historical.
- The feature folder finally moves to `implemented_features/2026_XX_XX_feat_study_lifecycle/` only when Phase 2 ships. Per impl-execute Step 8.6, the presence of `phase*_idea.md` blocks the move until the deferred phase lands.

## Cross-references

- [`feature_spec.md`](feature_spec.md) — full feature spec; §3 Phase boundaries documents the split; §7 lists FR-1 through FR-7.
- [`implementation_plan.md`](implementation_plan.md) — Phase 1 plan (schema + minimal repos), now Complete.
- [`infra_optuna_eval` (implemented)](../../../00_overview/implemented_features/2026_05_10_infra_optuna_eval/feature_spec.md) — the dependency that gated Phase 2; now shipped. Phase 2's orchestrator dispatches that feature's `run_trial` job.
- [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md) — the 7-table column-level shapes (Phase 1 implements these; Phase 2 doesn't `ALTER`).
- [`docs/03_runbooks/optuna-debugging.md`](../../../03_runbooks/optuna-debugging.md) — runbook from `infra_optuna_eval`; the orchestrator's behavior should align with this runbook's reaper / orphan-trial guidance.

## Open questions for `/spec-gen` (carry through to plan-gen)

1. **Settings vs JSON-only defaults for `parallelism` / `trial_timeout_s`.** Should `STUDIES_DEFAULT_PARALLELISM` and `STUDIES_DEFAULT_TIMEOUT_S` ship as backend Settings env-vars (matching `OPENAI_BASE_URL` / `ES_HEAP_SIZE` convention) OR be hardcoded in `backend/app/domain/study/...`? Recommended default: backend Settings, plain env-vars (operator-tunable without redeploy is the existing project convention). Cross-cutting: the API layer must NOT materialize these defaults into `studies.config` at create time — keep keys omitted in the stored row so `infra_optuna_eval`'s pruner key-presence contract (spec FR-2 — explicit-override semantics) remains intact.

2. **Failed-study threshold AC-5: 5 consecutive failures.** The spec §AC-5 locks this number, but the orchestrator implementation needs to decide WHAT counts as a "consecutive failure": (a) any `trials.status='failed'` row regardless of `trials.error` content, (b) only rows whose error indicates infra failure (e.g. `CLUSTER_UNREACHABLE`), excluding scoring/render bugs, or (c) the most recent 5 across all parallelism slots. The spec is silent. Recommended default: (c) — most recent 5 across the entire study, any failure type — simplest and matches the operator's mental model.

3. **Orchestrator backoff on `run_trial` infra-level re-raise.** When `run_trial` re-raises an `OperationalError` (Postgres lost), Arq retries the job with backoff. The orchestrator counts that as a `running` trial — does it wait indefinitely for the retry, or does it have its own timeout? Recommended default: orchestrator does NOT impose a separate timeout — it relies on Arq's visibility-timeout to clean up zombies and on `studies.config.time_budget_min` to bound study wall-clock.

These are decisions `/spec-gen` should lock (or kick to product) during Phase 2's spec-review cycle; they aren't blockers for /pipeline kickoff.
