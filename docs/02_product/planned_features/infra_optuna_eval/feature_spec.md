# Feature Specification — infra_optuna_eval

**Date:** 2026-05-09
**Status:** Draft
**Owners:** TBD
**Related docs:**
- [docs/02_product/mvp1-user-stories.md](../../mvp1-user-stories.md) — covers US-7, US-8
- [docs/01_architecture/optimization.md](../../../01_architecture/optimization.md) — Optuna + pytrec_eval architecture
- [docs/01_architecture/data-model.md](../../../01_architecture/data-model.md) — `studies`, `trials` tables (consumed; created by `feat_study_lifecycle`)
- [docs/01_architecture/system-overview.md](../../../01_architecture/system-overview.md) — worker pool detail
- Depends on: [`infra_foundation/feature_spec.md`](../infra_foundation/feature_spec.md)
- Consumed by: [`feat_study_lifecycle/feature_spec.md`](../feat_study_lifecycle/feature_spec.md)

---

## 1) Purpose

- **Problem:** RelyLoop tunes search relevance by running thousands of trials per study and picking the winner. Without (a) an optimizer that suggests good parameter combinations from prior trials and (b) a metric scorer that evaluates each trial against ground-truth judgments, the loop has no engine. The `feat_study_lifecycle` orchestrator depends on both.
- **Outcome:** Optuna RDB storage co-tenants with the application Postgres; TPE sampler + median pruner are the MVP1 defaults; pytrec_eval scores trials against judgment lists for nDCG@10, MAP, P@K, recall@K, MRR, and ERR@K. The `run_trial` Arq job is the hot-path worker.
- **Non-goal:** No multi-objective optimization (v2). No CMA-ES sampler (MVP2). No click-derived judgments (v1.5+). No intermediate-step pruning (MVP2 — MVP1 trials are single-step). The scorer evaluates whatever judgments the configured `judgment_list` provides; this feature does not generate judgments (that's `feat_llm_judgments`).

## 2) Current state audit

After `infra_foundation` ships:
- Postgres exists with the `alembic_version` table; this feature adds Optuna's RDB schema (`optuna.*`) via Optuna's own migration mechanism.
- Redis exists; this feature adds the `trials` Arq queue.
- The worker process exists as a placeholder (`workers.all.WorkerSettings`); this feature adds the `run_trial` job to that worker pool.
- No `studies` or `trials` tables yet — those are created by `feat_study_lifecycle` (which depends on this feature for the trial runner). This feature provides the worker; `feat_study_lifecycle` provides the schema and orchestrator.

## 3) Scope

### In scope

- `optuna` and `pytrec_eval` added to `pyproject.toml`.
- `optuna.storages.RDBStorage` configured against the application Postgres with the `optuna.*` schema isolated via `options=-csearch_path=optuna` (per [`optimization.md` §"Optuna configuration"](../../../01_architecture/optimization.md)).
- Optuna RDB schema initialization wired into `make migrate` (Optuna's own `optuna.storages._rdb.alembic` runs after RelyLoop's Alembic migrations).
- TPE sampler default; `MedianPruner(n_warmup_steps=10)` default; random sampler available as a baseline-comparison option (selectable via `studies.config.sampler`).
- pytrec_eval evaluator helper in `backend/eval/scoring.py`:
  - Input: `qrels` (dict of `{query_id: {doc_id: rating}}`) + `run` (dict of `{query_id: {doc_id: score}}`) + metric set
  - Output: per-query metric dict + aggregated metric values
  - Supports nDCG@k, MAP, precision@k, recall@k, MRR, ERR@k
- `run_trial` Arq job at `backend/worker/trials.py`:
  - Loads the study + adapter + judgments + template
  - Calls `study.ask()` for params
  - Renders + executes via the adapter (depends on `infra_adapter_elastic`)
  - Scores via pytrec_eval
  - Writes a `trials` row (table created by `feat_study_lifecycle`)
  - Calls `study.tell()`
  - Handles failure modes: `complete` / `failed` / `pruned` (pruned is reserved — not active in MVP1 single-step trials)
- The worker process consumes the `trials` Arq queue (added to `WorkerSettings.functions`).

### Out of scope

- The `studies` and `trials` table migrations — owned by `feat_study_lifecycle`.
- Study orchestration (creating studies, polling for completion, stop conditions) — owned by `feat_study_lifecycle`.
- Judgment generation — owned by `feat_llm_judgments`.
- CMA-ES sampler implementation — MVP2 per [`optimization.md` §"Optuna configuration"](../../../01_architecture/optimization.md).
- Multi-objective optimization — v2.
- Click-derived judgments — v1.5+ (Fusion Signals dependency).
- Intermediate-step pruning — MVP2 (requires multi-step trial design).

### API convention check

This feature has no HTTP endpoints. The `run_trial` job is Arq-internal. Conventions for naming + telemetry follow [`api-conventions.md` §"Trace / request correlation"](../../../01_architecture/api-conventions.md): each trial gets a `trial_id` (the row PK) propagated as the structlog context for that job's log records.

### Phase boundaries

Single-phase. The MVP1 deliverable is "a `run_trial` job that successfully completes a trial against a seeded study, writing the `trials` row, with metrics matching a hand-computed baseline within rounding error."

## 4) Product principles and constraints

- **One Postgres, two schemas.** Optuna co-tenants with the app DB to keep operator setup simple. No separate Optuna DB.
- **pytrec_eval everywhere.** Engine-native `_rank_eval` is forbidden. Per [`optimization.md` §"pytrec_eval configuration"](../../../01_architecture/optimization.md), cross-engine metric comparability requires one scorer.
- **Trial failures are persistent.** Every `study.ask()` corresponds to a `trials` row even if the trial fails or prunes. No silent drops.
- **Worker is stateless.** State lives in Postgres + Redis; the worker process can be killed and restarted at any point without losing trials in flight (Arq retries on visibility-timeout expiry).

### Anti-patterns

- **Do not** call the engine via per-query `_search` — use `_msearch` via `SearchAdapter.search_batch` (per [`adapters.md`](../../../01_architecture/adapters.md)). Per-query is a 10× regression.
- **Do not** put pytrec_eval calls on the API process. Scoring runs in the worker, never inline with an HTTP request.
- **Do not** persist Optuna state outside RDBStorage (e.g., to in-memory `InMemoryStorage`). RDB is the contract — multi-worker parallelism depends on it.
- **Do not** swallow trial failures into the success path. A failed trial writes a `trials` row with `status='failed'` and `error` populated; it does NOT count against `study.best_metric`.

## 5) Assumptions and dependencies

- **Dependency: `infra_foundation` shipped** — provides Postgres, Alembic, Arq worker scaffolding, structlog.
- **Dependency: `infra_adapter_elastic` shipped** — provides `SearchAdapter` Protocol + `ElasticAdapter` (the `search_batch` callee).
- **Dependency: `feat_study_lifecycle` schema** — `studies` and `trials` tables. This feature's `run_trial` job reads from `studies` and writes to `trials`. The schema is owned by `feat_study_lifecycle` but this feature can land first if `feat_study_lifecycle`'s migration is in flight; verify ordering during plan.
- **Optuna ≥ 3.6** — required for `RDBStorage` async-friendly behavior in 3.12.
- **pytrec_eval ≥ 0.5** — Python 3.12 wheel availability.

## 6) Actors and roles

- **Primary actor:** the worker process (system actor; no human in this feature's loop).
- **Role model:** N/A — single-tenant, no auth.

### Authorization

N/A — single-tenant install, no auth surface (per [`tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md)).

### Audit events

N/A — `audit_log` lands at MVP2. When MVP2 ships, `feat_study_lifecycle` will emit `study.start` / `study.complete` events; this feature's `run_trial` job is per-trial and doesn't warrant audit events (volume is too high).

## 7) Functional requirements

### FR-1: Optuna RDBStorage configured against the app Postgres
- The system **MUST** initialize Optuna's RDBStorage at worker startup against the same `DATABASE_URL` as the application, with `options=-csearch_path=optuna` to isolate Optuna's tables in the `optuna.*` schema.
- The system **MUST** run Optuna's RDB migrations on `make migrate` (via `optuna.storages._rdb.alembic`).
- The system **MUST NOT** create Optuna tables in the `public` schema.
- Notes: per [`optimization.md` §"Optuna configuration"](../../../01_architecture/optimization.md).

### FR-2: TPE sampler + MedianPruner are MVP1 defaults
- The system **MUST** default `studies.config.sampler` to `tpe`; permitted values: `tpe`, `random`.
- The system **MUST** default `studies.config.pruner` to `median` (with `n_warmup_steps=10`); permitted values: `median`, `none`.
- The system **MUST** auto-disable pruning if `studies.config.max_trials < 50` (override: explicit `pruner='median'` in config keeps pruning regardless).
- Notes: CMA-ES + intermediate-step pruning reserved for MVP2.

### FR-3: pytrec_eval evaluator helper
- The system **MUST** provide `backend/eval/scoring.py:score(qrels, run, metrics)` returning `{aggregate: {metric: value}, per_query: {query_id: {metric: value}}}`.
- The system **MUST** support metric set: `ndcg@k`, `map`, `precision@k`, `recall@k`, `mrr`, `err@k` for k ∈ {1, 3, 5, 10, 20, 50, 100}.
- The system **MUST** handle both graded (0..3) and binary (0..1) judgment ratings.
- The system **SHOULD** complete scoring in <100ms per query for a 50-query set with top_k=10 (verified by benchmark in `tests/benchmarks/test_scoring_perf.py`).

### FR-4: `run_trial` Arq job
- The system **MUST** define `run_trial(ctx, study_id, optuna_trial_number)` as an Arq job in `backend/worker/trials.py`, registered with the `WorkerSettings.functions` list.
- The system **MUST** load the study, fetch the configured adapter via the `clusters` row, fetch the judgment list, fetch the template, render N native queries via `adapter.render(template, params, query_text)`, call `adapter.search_batch(target, native_queries, top_k)`, score via pytrec_eval, write a `trials` row, and call `study.tell()` — in that order.
- The system **MUST** persist `trials.status = 'failed'` with the exception message in `trials.error` if any step raises (adapter, render, search, score). The job does NOT re-raise unless the failure is infra-level (DB unreachable).
- The system **MUST** propagate the trial_id as structlog context for all log records emitted during the job.
- Notes: covers US-7, US-8.

### FR-5: Trial metrics persisted with primary denormalized
- The `trials.metrics` JSONB column **MUST** contain all configured metrics (the study's primary + every other metric requested by `studies.objective`).
- The `trials.primary_metric` REAL column **MUST** be denormalized from `metrics[study.objective.metric]` for fast index-backed sort.
- The `trials.duration_ms` INT column **MUST** record wall-clock time from `study.ask()` to `study.tell()`.

## 8) API and data contract baseline

### 7.1 Endpoint surface

N/A — no HTTP endpoints. This feature is worker-internal.

### 7.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth |
|---|---|---|
| `studies.config.sampler` | `tpe`, `random` | `backend/db/models/study.py` (`SamplerKind` `Literal[...]`) |
| `studies.config.pruner` | `median`, `none` | `backend/db/models/study.py` (`PrunerKind` `Literal[...]`) |
| `studies.objective.metric` | `ndcg`, `map`, `precision`, `recall`, `mrr`, `err` | `backend/eval/scoring.py` (`SUPPORTED_METRICS` frozenset) |
| `studies.objective.k` | positive int ∈ {1, 3, 5, 10, 20, 50, 100} | `backend/eval/scoring.py` (`SUPPORTED_K_VALUES` frozenset) |
| `trials.status` | `complete`, `failed`, `pruned` | `backend/db/models/trial.py` (`TrialStatus` `Literal[...]`) |

### 7.5 Error code catalog

N/A — no HTTP-level errors from this feature. Trial failures land in `trials.status='failed'` with `trials.error` populated.

## 9) Data model and state transitions

This feature does NOT define new tables. It depends on `studies` + `trials` (both owned by `feat_study_lifecycle` per [`data-model.md` §"MVP1 table inventory"](../../../01_architecture/data-model.md)).

It DOES add Optuna's `optuna.*` schema, but that schema is managed by Optuna itself, not Alembic. The application interacts with it only via `optuna.storages.RDBStorage`.

### State transitions

`trials.status`: created with one of `complete | failed | pruned`. No transitions after creation (trials are append-only / hard-delete only on study cascade).

## 10) Security, privacy, and compliance

- **Threats:**
  1. Optuna RDB schema co-tenant with app schema could leak app data via SQL injection. **Mitigation:** Optuna uses parameterized queries via SQLAlchemy; schema isolation via `search_path` provides defense-in-depth.
  2. Long-running trials could exhaust the worker pool (DoS-by-misconfiguration). **Mitigation:** the per-trial deadline is `studies.config.trial_timeout_s` (default 60s); workers kill trials exceeding it.
- **Secrets handling:** N/A — no new secrets.
- **Auditability:** N/A — `audit_log` is MVP2.

## 11) UX flows and edge cases

N/A — worker-internal feature, no UI.

### Edge/error flows

- **Adapter raises (e.g., cluster unreachable mid-trial).** Trial status → `failed`; error message recorded; `study.tell()` is called with the exception so Optuna doesn't deadlock on missing trials.
- **pytrec_eval raises (e.g., empty judgment list).** Same — trial fails, study continues with the next trial.
- **Optuna RDB lock contention** at high parallelism. Optuna's locking is row-level; expected throughput is 10–50 trials/sec on a 4-worker pool against a single-instance Postgres. Beyond that, scale Postgres or reduce `parallelism`.
- **Worker process restart mid-trial.** Arq's visibility-timeout (default 300s) re-enqueues the job; the same trial_number may run twice if it didn't complete before the timeout. Optuna's `study.ask()` is idempotent on the trial_number, so no duplicate `trials` row is created.

## 12) Given/When/Then acceptance criteria

### AC-1: Optuna schema isolated

- Given a fresh `make migrate` run.
- When the operator queries `SELECT schema_name FROM information_schema.schemata`.
- Then both `public` and `optuna` schemas exist; Optuna's tables (`studies`, `trials`, etc. in Optuna's namespace) live in `optuna.*` and do NOT collide with RelyLoop's `studies` / `trials` tables in `public.*`.

### AC-2: TPE sampler is the default

- Given a study created without an explicit sampler config.
- When the worker initializes the Optuna study.
- Then `study.sampler.__class__.__name__ == 'TPESampler'`.

### AC-3: pytrec_eval matches a hand-computed baseline

- Given a fixture: 5 queries × 10 docs/query, with hand-curated judgments and a known ranking.
- When `score(qrels, run, {'ndcg_cut_10', 'map'})` is called.
- Then the returned `aggregate.ndcg@10` matches the hand-computed baseline within 1e-6, and the returned `aggregate.map` matches within 1e-6.
- Example values:
  - Input: `qrels = {"q1": {"d1": 3, "d2": 2}, ...}`, `run = {"q1": {"d2": 0.9, "d1": 0.7}, ...}`
  - Expected: `aggregate.ndcg@10 = 0.789` (computed offline; pinned in the fixture)

### AC-4: `run_trial` writes a complete trial

- Given a seeded study with the local-es cluster, a 50-query set, a hand-built judgment list, and `objective.metric = 'ndcg'`, `objective.k = 10`.
- When the worker dequeues a `run_trial(study_id, trial_number=1)` job.
- Then within 5 seconds, a `trials` row exists with `status='complete'`, `params` populated, `metrics` containing `ndcg@10`, `primary_metric` denormalized to `metrics.ndcg@10`, and `duration_ms` non-null.

### AC-5: Adapter failure surfaces as `status='failed'`

- Given the cluster `local-es` has been stopped (`docker compose stop elasticsearch`).
- When a `run_trial` job runs against a study targeting `local-es`.
- Then a `trials` row is written with `status='failed'`, `error` containing "CLUSTER_UNREACHABLE" (or similar), `metrics={}`, and `study.tell()` was called so Optuna does not deadlock.

### AC-6: Pruning auto-disables for small studies

- Given a study with `config.max_trials = 30` (below the 50-trial pruning threshold).
- When the worker initializes the Optuna study.
- Then `study.pruner.__class__.__name__ == 'NopPruner'` regardless of the configured `pruner` value.

### AC-7: Search uses _msearch, not per-query _search

- Given a `run_trial` invocation with 50 queries.
- When the trial executes (cassette-replayed).
- Then exactly one HTTP call to `_msearch` is made; zero calls to `_search`.

## 13) Non-functional requirements

- **Performance:** A 50-query trial against a 10K-doc local-es index completes in <500ms p99 (adapter call ~200ms, pytrec_eval scoring <50ms, Optuna ask/tell <100ms, DB write <100ms).
- **Reliability:** Worker survives Postgres restart cleanly (Arq retries with backoff; in-flight trials re-enqueue).
- **Operability:** Every trial logs a single INFO record at completion with `study_id`, `trial_number`, `status`, `primary_metric`, `duration_ms`. Failures log at WARN with the exception trace.

## 14) Test strategy requirements

- **Unit tests** (`backend/tests/unit/eval/`):
  - `test_scoring.py` — pytrec_eval helper against a hand-curated qrels/run pair; assert known nDCG@10, MAP, P@10 values within 1e-6.
  - `test_metric_validation.py` — `studies.objective.metric` and `studies.objective.k` validators reject out-of-allowlist values.
- **Integration tests** (`backend/tests/integration/`):
  - `test_optuna_rdb.py` — `RDBStorage` creates the `optuna.*` schema isolated from `public.*`; concurrent ask/tell calls from two workers don't deadlock.
  - `test_run_trial.py` — full `run_trial` invocation against a seeded study + cassette-replayed local-es; asserts AC-4.
  - `test_run_trial_adapter_failure.py` — `run_trial` against a stopped cluster produces a `failed` trial row (AC-5).
- **Contract tests** (`backend/tests/contract/`):
  - `test_trial_row_shape.py` — written `trials` row matches the Pydantic `Trial` model exactly (no extra/missing columns).
- **E2E tests:** N/A — no UI.
- **Benchmarks** (`backend/tests/benchmarks/`):
  - `test_scoring_perf.py` — pytrec_eval scoring completes in <100ms per query for a 50-query × top_k=10 fixture.

## 15) Documentation update requirements

- `docs/01_architecture/optimization.md` already documents the patterns; update if implementation diverges from the spec.
- `docs/03_runbooks/`: add `optuna-debugging.md` — how to inspect Optuna's RDB tables, replay a trial, diagnose pruner false-positives.
- `docs/05_quality/testing.md`: add the cassette pattern for `run_trial` integration tests.
- `docs/02_product/mvp1-user-stories.md`: mark US-7 / US-8 as "implemented" when this feature ships.

## 16) Rollout and migration readiness

- **Feature flags:** None.
- **Migration/backfill:** Optuna's RDB migrations run on `make migrate`. No application-table migrations in this feature.
- **Operational readiness gates:**
  - `make migrate` creates the `optuna` schema cleanly on a fresh database.
  - The benchmark in `test_scoring_perf.py` passes on the CI runner.
- **Release gate:** `feat_study_lifecycle` can call into `run_trial` without modification.

## 17) Traceability matrix

| FR ID | AC IDs | Planned story IDs (TBD) | Test files | Docs to update |
|---|---|---|---|---|
| FR-1 (RDBStorage) | AC-1 | TBD | `tests/integration/test_optuna_rdb.py` | `docs/01_architecture/optimization.md` |
| FR-2 (TPE + MedianPruner) | AC-2, AC-6 | TBD | `tests/integration/test_optuna_rdb.py`, `tests/unit/eval/test_metric_validation.py` | `docs/01_architecture/optimization.md` |
| FR-3 (pytrec_eval helper) | AC-3 | TBD | `tests/unit/eval/test_scoring.py`, `tests/benchmarks/test_scoring_perf.py` | `docs/01_architecture/optimization.md` |
| FR-4 (run_trial job) | AC-4, AC-5, AC-7 | TBD | `tests/integration/test_run_trial.py`, `tests/integration/test_run_trial_adapter_failure.py` | `docs/03_runbooks/optuna-debugging.md` |
| FR-5 (trial metrics persisted) | AC-4 | TBD | `tests/contract/test_trial_row_shape.py` | — |

## 18) Definition of feature done

- [ ] All AC-1 through AC-7 pass in CI.
- [ ] All test layers green; ≥80% coverage on `backend/eval/scoring.py` and `backend/worker/trials.py`.
- [ ] Benchmark `test_scoring_perf.py` passes (<100ms/query).
- [ ] `docs/03_runbooks/optuna-debugging.md` merged.
- [ ] `feat_study_lifecycle` author confirms the `run_trial` interface meets their orchestrator's needs.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

1. **Trial timeout default** — `studies.config.trial_timeout_s` default of 60s — confirm with `feat_study_lifecycle` author. Some trials against large indices may legitimately take 30s+. — Owner: TBD — Due: before plan.
2. **Optuna RDB Alembic integration** — Optuna runs its own Alembic; should our `make migrate` invoke Optuna's Alembic explicitly, or rely on Optuna's lazy table creation on first connection? — Owner: TBD — Due: before plan.

### Decision log

- 2026-05-09 — pytrec_eval everywhere (no engine-native `_rank_eval`) — per umbrella spec §14 + [`optimization.md`](../../../01_architecture/optimization.md).
- 2026-05-09 — Optuna co-tenants with app Postgres (separate schema) — per umbrella spec §13.
- 2026-05-09 — Multi-objective deferred to v2; CMA-ES deferred to MVP2 — per [`optimization.md` §"Reserved for later releases"](../../../01_architecture/optimization.md).
