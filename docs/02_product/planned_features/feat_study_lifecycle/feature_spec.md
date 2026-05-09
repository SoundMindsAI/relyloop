# Feature Specification — feat_study_lifecycle

**Date:** 2026-05-09
**Status:** Draft
**Owners:** TBD
**Related docs:**
- [docs/02_product/mvp1-user-stories.md](../../mvp1-user-stories.md) — covers US-9, US-10, US-11, US-12
- [docs/01_architecture/data-model.md](../../../01_architecture/data-model.md) — `studies`, `trials`, `query_templates`, `query_sets`, `queries` tables
- [docs/01_architecture/optimization.md](../../../01_architecture/optimization.md) — Optuna integration consumed via `run_trial`
- [docs/01_architecture/system-overview.md](../../../01_architecture/system-overview.md) — worker pool detail
- [docs/01_architecture/api-conventions.md](../../../01_architecture/api-conventions.md)
- Depends on: [`infra_foundation`](../infra_foundation/feature_spec.md), [`infra_adapter_elastic`](../infra_adapter_elastic/feature_spec.md), [`infra_optuna_eval`](../infra_optuna_eval/feature_spec.md)
- Consumed by: [`feat_llm_judgments`](../feat_llm_judgments/feature_spec.md), [`feat_digest_proposal`](../feat_digest_proposal/feature_spec.md), [`feat_studies_ui`](../feat_studies_ui/feature_spec.md), [`feat_chat_agent`](../feat_chat_agent/feature_spec.md)

---

## 1) Purpose

- **Problem:** A study is the atomic unit of relevance work — define query set + judgments + search space + objective + stop conditions, run N parallel trials, get the winner. Without an orchestrator that creates, enqueues, monitors, and stops studies, the trial worker (`infra_optuna_eval`) has nothing to drive it.
- **Outcome:** A relevance engineer creates a study via API or chat, the orchestrator enqueues N parallel `run_trial` jobs, trials accumulate in real time on the study detail page, the orchestrator detects stop-condition completion, and the study transitions to `completed` (handing off to `feat_digest_proposal`).
- **Non-goal:** No digest generation (that's `feat_digest_proposal`). No LLM judgment generation (that's `feat_llm_judgments`). No UI (that's `feat_studies_ui`). No PR creation (that's `feat_github_pr_worker`). No study forking with narrowed search-space (MVP2).

## 2) Current state audit

After `infra_foundation`, `infra_adapter_elastic`, and `infra_optuna_eval` ship:
- `clusters` and `config_repos` tables exist.
- The `run_trial` Arq job exists and works against any seeded study.
- No `studies`, `trials`, `query_templates`, `query_sets`, `queries` tables yet — this feature creates all five.
- No orchestrator process — this feature adds it as the `studies` Arq queue consumer.

## 3) Scope

### In scope

- Migrations creating the **full MVP1 shape** of these 6 tables per [`data-model.md`](../../../01_architecture/data-model.md):
  - `query_templates`
  - `query_sets`
  - `queries`
  - `studies` (including `failed_reason TEXT`, `baseline_metric REAL`)
  - `trials`
  - `judgment_lists` (full shape — `cluster_id`, `target`, `current_template_id`, `status`, `failed_reason`, `calibration` columns are all created here so `feat_llm_judgments` can read/write without further migration)
  - `proposals` (full shape — `pr_url`, `pr_state`, `pr_merged_at`, `pr_open_error`, `rejected_reason` all nullable; populated by `feat_digest_proposal` / `feat_github_pr_worker` / `feat_github_webhook`)

  Per [`data-model.md` §"MVP1 table inventory + migration ownership"](../../../01_architecture/data-model.md), this feature owns 6 of the 13 MVP1 application tables; downstream features only INSERT/UPDATE rows, they don't ALTER schemas.
- API endpoints:
  - `POST /api/v1/query-sets` + `GET /api/v1/query-sets` + `GET /api/v1/query-sets/{id}` (cluster-scoped)
  - `POST /api/v1/query-sets/{id}/queries` (bulk add via JSON or CSV upload)
  - `POST /api/v1/query-templates` + `GET /api/v1/query-templates` + `GET /api/v1/query-templates/{id}`
  - `POST /api/v1/studies` + `GET /api/v1/studies` (with cursor pagination + status filter) + `GET /api/v1/studies/{id}` (includes live `trials` summary) + `POST /api/v1/studies/{id}/cancel`
  - `GET /api/v1/studies/{id}/trials` (cursor pagination, sortable by `primary_metric`)
- Orchestrator: `start_study` Arq job (in `backend/worker/orchestrator.py`) that:
  - Transitions `studies.status: queued → running` and stamps `started_at`
  - Enqueues `studies.config.parallelism` trials (uses `optuna.study.optimize` semantics — ask/tell loop driven by the worker pool)
  - Polls `studies.status` for `cancelled`; if cancelled, drains in-flight trials and transitions to `cancelled`
  - On stop-condition fire (`max_trials` reached OR `time_budget_min` exceeded), transitions to `completed` and stamps `completed_at`, denormalizes `best_metric` and `best_trial_id`, then enqueues the digest job (`feat_digest_proposal` consumes this)
- State machine for `studies.status`: `queued → running → completed | cancelled | failed` (per umbrella §12 lines 648–674)
- Service-layer guards preventing direct DB UPDATE of `studies.status` outside the orchestrator
- Resume-after-restart support: orchestrator process picks up `running` studies on startup and re-enters the polling loop

### Out of scope

- Study forking with narrowed search-space (`fork_study` agent tool) — MVP2.
- Multi-objective studies — v2.
- Per-tenant study quotas — MVP4.
- Digest narrative generation — `feat_digest_proposal`.
- LLM judgment generation — `feat_llm_judgments` (this feature CONSUMES `judgment_lists` rows but does not create them).
- UI — `feat_studies_ui`.

### API convention check

Per [`api-conventions.md`](../../../01_architecture/api-conventions.md):
- All endpoints under `/api/v1/`
- Cursor pagination on `GET /api/v1/studies`, `GET /api/v1/studies/{id}/trials`, `GET /api/v1/query-sets`, `GET /api/v1/query-templates` (default `limit=50`, max `200`)
- Structured error envelope per `api-conventions.md` §"Error envelope"
- `X-Request-ID` propagated to structlog context

### Phase boundaries

Single-phase. The MVP1 deliverable is "create a study via API, watch trials accumulate over a few minutes, study completes when stop conditions hit, status transitions are correct."

## 4) Product principles and constraints

- **State transitions go through the orchestrator.** Direct `UPDATE studies SET status = ...` outside the orchestrator service layer is forbidden. Service-layer functions (`start_study()`, `cancel_study()`, `complete_study()`) are the only legal mutators.
- **Resume on restart.** A `running` study survives orchestrator restart. The orchestrator polls `studies WHERE status = 'running'` on startup and re-enters the loop.
- **Fail loudly.** A study transitions to `failed` only on infra-level catastrophe (DB unreachable, all workers crashed). Per-trial failures are recorded in `trials.status='failed'` and do NOT fail the study; the study completes when it hits its trial budget regardless of trial-level failures.
- **Optuna study name = RelyLoop study UUID.** `studies.optuna_study_name = str(studies.id)` so the Optuna RDB row is trivially traceable to the application row.
- **Trials are append-only.** Hard-delete on study cascade; no `deleted_at` (per [`data-model.md`](../../../01_architecture/data-model.md)).

### Anti-patterns

- **Do not** allow the API to enqueue trials directly. Trial enqueuing happens inside the orchestrator only.
- **Do not** poll Postgres from the API for live trial counts. The `GET /api/v1/studies/{id}` endpoint returns a summary computed from a single query (`COUNT trials GROUP BY status`); the UI polls this endpoint, not Postgres directly.
- **Do not** use `studies.status='running'` as a "lock" — it's a state, not a mutex. Two orchestrator processes both seeing `running` is a recoverable condition (Optuna's RDB locking handles trial dedup).
- **Do not** store live trial history in Redis. Postgres is the source of truth; Redis is only the Arq queue.

## 5) Assumptions and dependencies

- **Dependency: `infra_foundation`** — Postgres, Alembic, Arq, settings.
- **Dependency: `infra_adapter_elastic`** — `clusters` rows exist for the orchestrator to look up cluster details.
- **Dependency: `infra_optuna_eval`** — `run_trial` Arq job + `optimization.py` config helpers.
- **Dependency: `judgment_lists` table is OWNED by this feature** — full MVP1 shape created here so `feat_llm_judgments` can land later without further migration.
- **Pydantic v2** for request/response models.

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (creates, monitors, cancels studies).
- **Role model:** N/A — single-tenant, no auth.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP2. When MVP2 ships, this feature's `start_study` and `cancel_study` mutations will emit `study.start` and `study.cancel` audit events; `complete_study` (system-driven) will emit `study.complete`.

## 7) Functional requirements

### FR-1: Study CRUD endpoints
- `POST /api/v1/studies` accepts `{name, cluster_id, target, template_id, query_set_id, judgment_list_id, search_space, objective, config}` and returns the created study with `status='queued'`.
- `GET /api/v1/studies?status=<...>&cursor=<...>&limit=<...>` returns the cursor-paginated list filtered by status (allowed values: `queued`, `running`, `completed`, `cancelled`, `failed`, or omit for all).
- `GET /api/v1/studies/{id}` returns the study detail including a `trials_summary` field: `{total, complete, failed, pruned, best_primary_metric}`.
- `POST /api/v1/studies/{id}/cancel` transitions a `queued` or `running` study to `cancelled`; returns 409 `INVALID_STATE_TRANSITION` for `completed`/`failed`/already-`cancelled` studies.

### FR-2: Query-template CRUD
- `POST /api/v1/query-templates` accepts `{name, engine_type, body, declared_params, parent_id?}` and returns the created template.
- `GET /api/v1/query-templates` (paginated) and `GET /api/v1/query-templates/{id}` (returns full body + declared_params).
- The system **MUST** validate `body` is parseable Jinja2 at create time (fail with `INVALID_TEMPLATE_SYNTAX` otherwise).
- The system **MUST** validate `declared_params` is a JSONB object whose keys are referenced in `body` (fail with `UNDECLARED_PARAM_USED` or `DECLARED_PARAM_UNUSED`).

### FR-3: Query-set CRUD
- `POST /api/v1/query-sets` accepts `{name, description?, cluster_id?}`.
- `POST /api/v1/query-sets/{id}/queries` accepts either JSON (`{queries: [{query_text, reference_answer?, metadata?}]}`) or CSV (`Content-Type: text/csv` with columns `query_text`, optional `reference_answer`, optional metadata as additional columns).
- `GET /api/v1/query-sets` (paginated) and `GET /api/v1/query-sets/{id}` (includes query count).

### FR-4: Orchestrator process
- The orchestrator **MUST** be an Arq job consumer on the `studies` queue.
- The orchestrator **MUST** transition `queued → running` atomically (Postgres row-level lock) when it picks up a `start_study(study_id)` job.
- The orchestrator **MUST** initialize the Optuna study via RDBStorage with `optuna_study_name = str(study_id)`, then enqueue `parallelism` × `run_trial` jobs initially, replenishing as they complete (via Arq job-completion callback or a polling tick).
- The orchestrator **MUST** poll `studies.status` every 10s; if `cancelled`, drain in-flight trials (wait up to 30s for `study.tell()`s) and transition to `cancelled`.
- The orchestrator **MUST** detect stop conditions: `trial_count >= max_trials` OR `now() - started_at >= time_budget_min minutes`. Either fires `complete_study(study_id)`.
- `complete_study` denormalizes `best_metric` (from `MAX(trials.primary_metric WHERE status='complete')`) and `best_trial_id`, stamps `completed_at`, transitions `running → completed`, and enqueues the digest job (consumed by `feat_digest_proposal`).
- Notes: covers US-9, US-10, US-11.

### FR-5: Resume-after-restart
- On orchestrator startup, the system **MUST** query `studies WHERE status = 'running'`, enqueue a `resume_study(study_id)` job for each, and re-enter the orchestrator loop. Optuna's RDBStorage already has the trial history; new `run_trial` jobs pick up from where they left off.
- Notes: covers US-12.

### FR-6: Trials list endpoint
- `GET /api/v1/studies/{id}/trials?cursor=<...>&limit=<...>&sort=<...>` returns paginated trials.
- Supported `sort` values: `primary_metric_desc` (default), `primary_metric_asc`, `created_at_desc`, `created_at_asc`, `optuna_trial_number_asc`.

### FR-7: State-transition guard
- The system **MUST** centralize all `studies.status` mutations in `backend/services/study_state.py`. Direct ORM writes are forbidden (enforced via a domain-layer SQLAlchemy event listener that raises `StudyStateProtectionError` on illegal direct UPDATEs).

## 8) API and data contract baseline

### 7.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/studies` | Create a study (status=queued); enqueues `start_study` | `VALIDATION_ERROR`, `CLUSTER_NOT_FOUND`, `TEMPLATE_NOT_FOUND`, `QUERY_SET_NOT_FOUND`, `JUDGMENT_LIST_NOT_FOUND`, `INVALID_SEARCH_SPACE` |
| `GET` | `/api/v1/studies` | List studies with cursor pagination + status filter | (none) |
| `GET` | `/api/v1/studies/{id}` | Study detail + `trials_summary` | `STUDY_NOT_FOUND` |
| `POST` | `/api/v1/studies/{id}/cancel` | Cancel a queued/running study | `STUDY_NOT_FOUND`, `INVALID_STATE_TRANSITION` |
| `GET` | `/api/v1/studies/{id}/trials` | Paginated trial list, sortable | `STUDY_NOT_FOUND` |
| `POST` | `/api/v1/query-templates` | Create a query template | `VALIDATION_ERROR`, `INVALID_TEMPLATE_SYNTAX`, `UNDECLARED_PARAM_USED`, `DECLARED_PARAM_UNUSED`, `TEMPLATE_NAME_TAKEN` |
| `GET` | `/api/v1/query-templates` | List templates (paginated) | (none) |
| `GET` | `/api/v1/query-templates/{id}` | Template detail | `TEMPLATE_NOT_FOUND` |
| `POST` | `/api/v1/query-sets` | Create a query set | `VALIDATION_ERROR`, `CLUSTER_NOT_FOUND`, `QUERY_SET_NAME_TAKEN` |
| `POST` | `/api/v1/query-sets/{id}/queries` | Bulk-add queries (JSON or CSV) | `QUERY_SET_NOT_FOUND`, `INVALID_CSV` |
| `GET` | `/api/v1/query-sets` | List query sets (paginated) | (none) |
| `GET` | `/api/v1/query-sets/{id}` | Query set detail + count | `QUERY_SET_NOT_FOUND` |

### 7.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth |
|---|---|---|
| `studies.status` | `queued`, `running`, `completed`, `cancelled`, `failed` | `backend/db/models/study.py` (`StudyStatus` `Literal[...]`) |
| `studies.config.sampler` | `tpe`, `random` | `backend/db/models/study.py` (per `infra_optuna_eval` FR-2) |
| `studies.config.pruner` | `median`, `none` | same |
| `studies.objective.metric` | `ndcg`, `map`, `precision`, `recall`, `mrr`, `err` | `backend/eval/scoring.py` (`SUPPORTED_METRICS`) |
| `studies.objective.k` | `1`, `3`, `5`, `10`, `20`, `50`, `100` | `backend/eval/scoring.py` (`SUPPORTED_K_VALUES`) |
| `studies.objective.direction` | `maximize`, `minimize` | `backend/db/models/study.py` (`ObjectiveDirection` `Literal[...]`) |
| `?sort` (trials list) | `primary_metric_desc`, `primary_metric_asc`, `created_at_desc`, `created_at_asc`, `optuna_trial_number_asc` | `backend/api/studies.py` (`TrialSortKey` `Literal[...]`) |

### 7.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| `STUDY_NOT_FOUND` | 404 | Study ID not found or soft-deleted |
| `INVALID_STATE_TRANSITION` | 409 | Attempted transition not allowed by the state machine (e.g., cancel a `completed` study) |
| `INVALID_SEARCH_SPACE` | 400 | `search_space` JSON failed Pydantic validation (unknown sampler kind, malformed range) |
| `TEMPLATE_NOT_FOUND` | 404 | `template_id` not found |
| `QUERY_SET_NOT_FOUND` | 404 | `query_set_id` not found |
| `JUDGMENT_LIST_NOT_FOUND` | 404 | `judgment_list_id` not found |
| `INVALID_TEMPLATE_SYNTAX` | 400 | Jinja2 parse failed |
| `UNDECLARED_PARAM_USED` | 400 | Template body uses a param not in `declared_params` |
| `DECLARED_PARAM_UNUSED` | 400 | `declared_params` lists a param not used in body |
| `TEMPLATE_NAME_TAKEN` | 409 | Template name already exists at the same version |
| `QUERY_SET_NAME_TAKEN` | 409 | Query-set name already taken |
| `INVALID_CSV` | 400 | CSV upload failed parse or missing required columns |

## 9) Data model and state transitions

This feature creates the full MVP1 shape of 6 tables per [`data-model.md`](../../../01_architecture/data-model.md): `query_templates`, `query_sets`, `queries`, `studies`, `trials`, `judgment_lists`, plus `proposals`. (Counting wise: 7 tables — see in-scope.) Downstream features author rows but do NOT ALTER any of these tables.

### State transitions

```
studies.status:    queued → running → completed
                                   → cancelled
                                   → failed (failed_reason populated)
```

- `queued → running`: orchestrator picks up the `start_study` job.
- `running → completed`: stop condition fires (`max_trials` reached OR `time_budget_min` elapsed).
- `running → cancelled`: user cancels via `POST /api/v1/studies/{id}/cancel`; orchestrator drains and stamps.
- `running → failed`: orchestrator catches an unrecoverable infra error (DB unreachable >5min, all workers crashed). `studies.failed_reason` populated.
- All other transitions raise `INVALID_STATE_TRANSITION`.

## 10) Security, privacy, and compliance

- **Threats:**
  1. A user creates a study with a search space that explodes (e.g., 10⁹ trial combinations) and DoS's the worker pool. **Mitigation:** Pydantic validation rejects search spaces with cardinality > 10⁶; `studies.config.max_trials` is hard-capped at 100,000 in MVP1.
  2. A user uploads a malicious CSV (CSV injection / formula injection). **Mitigation:** CSV parsing validates each cell as text; no eval.
  3. A user's template body contains a Jinja2 expression that imports + executes Python code. **Mitigation:** Jinja2 SandboxedEnvironment for template rendering; no `import`, `eval`, or attribute access on built-ins.
- **Secrets handling:** N/A — no new secrets.
- **Auditability:** N/A — `audit_log` is MVP2.

## 11) UX flows and edge cases

This feature has no UI surface; UI is owned by `feat_studies_ui`. The API is consumed by both the UI and the chat agent.

### Edge/error flows

- **Study created with `judgment_list_id` whose `query_set_id` doesn't match `studies.query_set_id`.** Reject at create time with `VALIDATION_ERROR`.
- **Cluster deleted while study is `running`.** Trials start failing with `CLUSTER_UNREACHABLE`; if all workers fail their first trial, the orchestrator tolerates 5 consecutive failures before transitioning the study to `failed`.
- **`time_budget_min` elapses with zero completed trials** (e.g., cluster was unreachable the whole time). Study transitions to `completed` (the budget honored its contract); `best_metric = NULL`, `best_trial_id = NULL`. Digest job receives this and reports "no successful trials" rather than crashing.
- **Cancel race**: user cancels at the exact moment the orchestrator detects `max_trials` hit. The state-transition guard wins whichever transition's UPDATE commits first; the loser raises `INVALID_STATE_TRANSITION` and is silently swallowed by the orchestrator.

## 12) Given/When/Then acceptance criteria

### AC-1: Create a study, watch it run, completes via max_trials

- Given a registered cluster `local-es`, a query set with 50 queries, a judgment list, a query template, and a 4-worker pool.
- When the operator POSTs `{name, cluster_id, target, template_id, query_set_id, judgment_list_id, search_space, objective: {metric: 'ndcg', k: 10, direction: 'maximize'}, config: {max_trials: 20, parallelism: 4}}` to `/api/v1/studies`.
- Then the response is HTTP 201 with `status: 'queued'`. Within 5s, polling `GET /api/v1/studies/{id}` shows `status: 'running'`. Within 60s (allowing for 20 trials × ~200ms each + 4-way parallelism), polling shows `status: 'completed'`, `trials_summary.complete = 20`, `best_metric` non-null, `best_trial_id` non-null.

### AC-2: Stop via time_budget_min

- Given the same setup but `config: {max_trials: 10000, time_budget_min: 1, parallelism: 4}` (1 minute budget, far more trials than will fit).
- When the study runs.
- Then within 90s (60s budget + 30s drain), `status: 'completed'` and `trials_summary.complete > 0` (some trials succeeded; far less than 10000).

### AC-3: Cancel a running study

- Given a study with `max_trials: 1000, parallelism: 4` is `running`.
- When the operator POSTs to `/api/v1/studies/{id}/cancel`.
- Then within 30s, `status: 'cancelled'`; in-flight trials completed cleanly (no `failed` rows from the cancel itself); subsequent `cancel` returns 409 `INVALID_STATE_TRANSITION`.

### AC-4: Resume after orchestrator restart

- Given a `running` study with 20 of 100 trials complete.
- When the worker process is killed and restarted.
- Then within 30s of restart, the study is back to `running`, new trials accumulate from trial-number 21 onward (Optuna RDB has the prior history), and the study eventually completes at trial 100.

### AC-5: Cluster failure mid-study

- Given a `running` study targeting `local-es`.
- When `docker compose stop elasticsearch` is executed mid-study.
- Then trials transition to `failed` (per `infra_optuna_eval` AC-5); after 5 consecutive failures the study transitions to `failed` with `failed_reason` populated; subsequent `GET /api/v1/studies/{id}` returns the failure detail.

### AC-6: Service-layer guard prevents direct UPDATE

- Given a developer attempts `UPDATE studies SET status = 'completed' WHERE id = ...` via the SQLAlchemy session (bypassing `study_state.py`).
- When the session flushes.
- Then a `StudyStateProtectionError` is raised; no row is updated.

### AC-7: Template Jinja2 validation

- Given a `POST /api/v1/query-templates` with body containing `{{ os.system('rm -rf /') }}`.
- When the request lands.
- Then the response is HTTP 400 with `error_code: INVALID_TEMPLATE_SYNTAX` (Jinja2 SandboxedEnvironment rejects the access); no row is created.

### AC-8: CSV upload to query-set

- Given an empty query set.
- When the operator POSTs a CSV file with 50 rows to `/api/v1/query-sets/{id}/queries` with `Content-Type: text/csv`.
- Then the response is HTTP 201 with `{added: 50}`; subsequent `GET /api/v1/query-sets/{id}` reports `query_count: 50`.

### AC-9: Cursor pagination

- Given 75 studies exist.
- When the operator hits `GET /api/v1/studies?limit=50`.
- Then the response is `{data: [50 studies], next_cursor: "<opaque>", has_more: true}`. Following the next_cursor returns the remaining 25 studies with `next_cursor: null, has_more: false`.

### AC-10: Trials list sorted by primary_metric_desc

- Given a completed study with 20 trials.
- When the operator hits `GET /api/v1/studies/{id}/trials?sort=primary_metric_desc&limit=10`.
- Then the response is the top-10 trials by `primary_metric` descending, with the best at index 0.

## 13) Non-functional requirements

- **Performance:** `POST /api/v1/studies` returns in <200ms p99 (single INSERT + Arq enqueue). `GET /api/v1/studies/{id}` returns in <100ms p99 (single JOIN with `trials_summary` aggregation). `GET /api/v1/studies/{id}/trials?limit=50` returns in <200ms p99.
- **Reliability:** Orchestrator survives Postgres restart with backoff; in-flight trials retry on visibility-timeout per Arq.
- **Operability:** Every state transition logs at INFO with `study_id`, `from_status`, `to_status`, `actor` (operator email when MVP4 brings auth; `system` for orchestrator-initiated transitions). Stop-condition fires log `reason` (`max_trials_reached` or `time_budget_exceeded`).

## 14) Test strategy requirements

- **Unit tests** (`backend/tests/unit/`):
  - `services/test_study_state.py` — state machine: every legal transition succeeds, every illegal transition raises `StudyStateProtectionError`.
  - `domain/test_template_validator.py` — Jinja2 SandboxedEnvironment correctly rejects forbidden constructs; `declared_params` ↔ body cross-check.
  - `domain/test_search_space_validator.py` — Pydantic search_space schema rejects malformed inputs.
- **Integration tests** (`backend/tests/integration/`):
  - `test_study_lifecycle.py` — full create → run → complete cycle against seeded local-es; asserts AC-1.
  - `test_study_cancel.py` — AC-3.
  - `test_study_resume.py` — AC-4 (kill + restart worker).
  - `test_csv_upload.py` — AC-8.
  - `test_pagination.py` — AC-9.
- **Contract tests** (`backend/tests/contract/`):
  - `test_studies_api_contract.py` — request/response shapes match OpenAPI.
  - `test_error_codes.py` — every code in §7.5 produces the documented HTTP + body.
- **E2E tests:** N/A (UI in `feat_studies_ui`).

## 15) Documentation update requirements

- `docs/01_architecture/data-model.md` already documents the schemas; update if implementation diverges (e.g., `studies.failed_reason` column).
- `docs/03_runbooks/`: add `study-lifecycle-debugging.md` — how to inspect a stuck study, manually transition state (escape hatch via direct service-layer call), purge a study.
- `docs/02_product/mvp1-user-stories.md`: mark US-9 / US-10 / US-11 / US-12 as "implemented".

## 16) Rollout and migration readiness

- **Feature flags:** None.
- **Migration/backfill:** First migration that creates business tables. No backfill needed.
- **Operational readiness gates:** state-transition guard verified by unit + integration tests; stop-condition reasons logged.
- **Release gate:** `feat_llm_judgments` author confirms the stub `judgment_lists` table interface meets their needs.

## 17) Traceability matrix

| FR ID | AC IDs | Stories (TBD) | Test files | Docs |
|---|---|---|---|---|
| FR-1 (study CRUD) | AC-1, AC-3, AC-9 | TBD | `tests/integration/test_study_lifecycle.py`, `tests/integration/test_study_cancel.py`, `tests/integration/test_pagination.py` | runbook |
| FR-2 (template CRUD) | AC-7 | TBD | `tests/unit/domain/test_template_validator.py` | — |
| FR-3 (query-set + CSV) | AC-8 | TBD | `tests/integration/test_csv_upload.py` | runbook |
| FR-4 (orchestrator) | AC-1, AC-2, AC-5 | TBD | `tests/integration/test_study_lifecycle.py` | runbook |
| FR-5 (resume) | AC-4 | TBD | `tests/integration/test_study_resume.py` | runbook |
| FR-6 (trials list) | AC-10 | TBD | `tests/integration/test_study_lifecycle.py` | — |
| FR-7 (state guard) | AC-6 | TBD | `tests/unit/services/test_study_state.py` | — |

## 18) Definition of feature done

- [ ] All AC-1 through AC-10 pass in CI.
- [ ] All test layers green; ≥80% coverage on `backend/services/study_state.py`, `backend/api/studies.py`, `backend/worker/orchestrator.py`.
- [ ] Runbook `study-lifecycle-debugging.md` merged.
- [ ] `feat_digest_proposal` author confirms the digest-job enqueue interface meets their needs.
- [ ] `feat_studies_ui` author confirms the API surface (especially `trials_summary` and pagination) is sufficient for the UI.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None — all resolved (see Decision log).

### Decision log

- 2026-05-09 — State transitions go through `backend/services/study_state.py`; direct ORM writes raise — per spec §12 lines 648–674 + the no-mutex-via-state principle.
- 2026-05-09 — `studies.optuna_study_name = str(studies.id)` for traceability — convention rather than spec mandate.
- 2026-05-09 — `studies.failed_reason TEXT` added to schema in [`data-model.md`](../../../01_architecture/data-model.md) — required by FR-4 + AC-5.
- 2026-05-09 — Orchestrator cancel-poll interval: **10s** — fast enough for UI responsiveness; doesn't hammer Postgres.
- 2026-05-09 — Trial replenishment: **periodic tick (1s)** — simpler than Arq job-completion callback; couples nothing to Arq's internal API.
- 2026-05-09 — This feature owns 7 tables in full MVP1 shape — `query_templates`, `query_sets`, `queries`, `studies`, `trials`, `judgment_lists`, `proposals` — per [`data-model.md` §"MVP1 table inventory + migration ownership"](../../../01_architecture/data-model.md). Downstream features (`feat_llm_judgments`, `feat_digest_proposal`, `feat_github_pr_worker`, `feat_github_webhook`) write rows but do NOT migrate any of these tables.
