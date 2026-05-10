# Feature Specification — infra_optuna_eval

**Date:** 2026-05-09 (review-and-patch 2026-05-10 against shipped `infra_foundation` / `infra_adapter_elastic` / `feat_study_lifecycle` Phase 1)
**Status:** Approved
**Owners:** TBD
**Related docs:**
- [docs/02_product/mvp1-user-stories.md](../../mvp1-user-stories.md) — covers US-7, US-8
- [docs/01_architecture/optimization.md](../../../01_architecture/optimization.md) — Optuna + pytrec_eval architecture
- [docs/01_architecture/data-model.md](../../../01_architecture/data-model.md) — `studies`, `trials` tables (consumed; created by `feat_study_lifecycle`)
- [docs/01_architecture/system-overview.md](../../../01_architecture/system-overview.md) — worker pool detail
- Depends on: [`infra_foundation/feature_spec.md`](../infra_foundation/feature_spec.md)
- Consumed by: [`feat_study_lifecycle` Phase 2 (orchestrator + API)](../feat_study_lifecycle/phase2_idea.md) — Phase 2's `start_study` Arq job dispatches this feature's `run_trial`

---

## 1) Purpose

- **Problem:** RelyLoop tunes search relevance by running thousands of trials per study and picking the winner. Without (a) an optimizer that suggests good parameter combinations from prior trials and (b) a metric scorer that evaluates each trial against ground-truth judgments, the loop has no engine. The `feat_study_lifecycle` Phase 2 orchestrator depends on both — Phase 1 (Schema, PR #18 merged 2026-05-10) shipped the `studies` + `trials` tables this feature reads/writes; Phase 2 will dispatch this feature's `run_trial` job.
- **Outcome:** Optuna RDB storage co-tenants with the application Postgres; TPE sampler + median pruner are the MVP1 defaults; pytrec_eval scores trials against judgment lists for nDCG@k, MAP, P@k, recall@k, and MRR. The `run_trial` Arq job is the hot-path worker.
- **Non-goal:** No multi-objective optimization (v2). No CMA-ES sampler (MVP2). No click-derived judgments (v1.5+). No intermediate-step pruning (MVP2 — MVP1 trials are single-step). **No ERR@k** — pytrec_eval doesn't ship it; deferred to MVP2 alongside any custom-metric expansion. The scorer evaluates whatever judgments the configured `judgment_list` provides; this feature does not generate judgments (that's `feat_llm_judgments`).

## 2) Current state audit (verified 2026-05-10)

All upstream dependencies have shipped — this feature is unblocked:

- **Postgres + Alembic** (`infra_foundation` / PR #4 merged 2026-05-09): the `alembic_version` table exists at head `0003_study_lifecycle_schema`. The `optuna` schema initializer is **already in place** at [`backend/app/db/optuna_schema.py`](../../../../backend/app/db/optuna_schema.py) and wired into `make migrate` (it issues `CREATE SCHEMA IF NOT EXISTS optuna`); Optuna's tables auto-create on first `RDBStorage` use via `create_study()`.
- **Redis** (`infra_foundation`): exists; this feature adds the `trials` Arq queue.
- **Worker process** (`infra_foundation` Story 4.3): exists as a placeholder at [`backend/workers/all.py`](../../../../backend/workers/all.py) with `functions=[]`; this feature adds the `run_trial` job to that list. The file's docstring already pre-declares the slot: "feat_study_lifecycle → run_trial".
- **Engine adapter** (`infra_adapter_elastic` / PR #16 merged 2026-05-10): provides `SearchAdapter` Protocol + `ElasticAdapter.search_batch()` — the engine call this feature's `run_trial` makes.
- **Schema** (`feat_study_lifecycle` Phase 1 / PR #18 merged 2026-05-10): `studies`, `trials`, `judgment_lists`, `query_*`, `proposals` tables exist on `0003`. This feature's `run_trial` job reads `studies` and writes `trials` — both shapes are documented in [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md). 15 minimal repo functions also shipped at [`backend/app/db/repo/`](../../../../backend/app/db/repo/) covering the read/write set this feature needs.
- **Phase 2 of `feat_study_lifecycle`** (orchestrator + 12 endpoints + `start_study` Arq job) is **deferred** via [`phase2_idea.md`](../feat_study_lifecycle/phase2_idea.md). Phase 2 dispatches this feature's `run_trial`; this feature provides the trial runner that Phase 2 enqueues.

## 3) Scope

### In scope

- `optuna` (≥ 3.6) and `pytrec_eval` (≥ 0.5) added to `pyproject.toml`.
- `optuna.storages.RDBStorage` configured against the application Postgres with the `optuna.*` schema isolated via `options=-csearch_path=optuna` (per [`optimization.md` §"Optuna configuration"](../../../01_architecture/optimization.md)). The schema itself is already created idempotently by [`backend/app/db/optuna_schema.py:init_optuna_schema()`](../../../../backend/app/db/optuna_schema.py) (shipped with `infra_foundation` Story 2.2); Optuna's own tables are created lazily on first `optuna.create_study(storage=...)` call. **No call to a non-existent `RDBStorage(...).initialize()`** — the lazy auto-creation is Optuna's documented mechanism.
- TPE sampler default; `MedianPruner(n_warmup_steps=10)` default; random sampler available as a baseline-comparison option (selectable via `studies.config.sampler`).
- Sampler/pruner/metric-set Literal types live at **`backend/app/eval/types.py`** (created by this feature). Phase 2 of `feat_study_lifecycle` reuses these Literals when validating `studies.config` / `studies.objective` payloads at the API layer.
- pytrec_eval evaluator helper at **`backend/app/eval/scoring.py`**:
  - Input: `qrels` (dict of `{query_id: {doc_id: rating}}`) + `run` (dict of `{query_id: {doc_id: score}}`) + metric set
  - Output: per-query metric dict + aggregated metric values
  - Supports nDCG@k, MAP, precision@k, recall@k, MRR (mapped to pytrec_eval's wire names `ndcg_cut_<k>`, `map_cut_<k>`, `P_<k>`, `recall_<k>`, `recip_rank` internally)
  - **No ERR@k** — not in pytrec_eval; deferred to MVP2
- `run_trial` Arq job at **`backend/workers/trials.py`**:
  - Loads the study + adapter + judgments + template
  - Calls `study.ask()` for params (Optuna sync API; wrapped in `asyncio.to_thread()` from the async Arq context)
  - Renders + executes via the adapter (depends on `infra_adapter_elastic`)
  - Scores via pytrec_eval
  - Writes a `trials` row (table created by `feat_study_lifecycle` Phase 1; `0003_study_lifecycle_schema`)
  - Calls `study.tell()`
  - Handles failure modes: `complete` / `failed` / `pruned` (pruned is reserved — not active in MVP1 single-step trials)
- The worker process consumes the `trials` Arq queue (added to `WorkerSettings.functions` in [`backend/workers/all.py`](../../../../backend/workers/all.py)).

### Out of scope

- The `studies` and `trials` table migrations — owned by `feat_study_lifecycle`.
- Study orchestration (creating studies, polling for completion, stop conditions) — owned by `feat_study_lifecycle`.
- Judgment generation — owned by `feat_llm_judgments`.
- CMA-ES sampler implementation — MVP2 per [`optimization.md` §"Optuna configuration"](../../../01_architecture/optimization.md).
- Multi-objective optimization — v2.
- Click-derived judgments — v1.5+ (Fusion Signals dependency).
- Intermediate-step pruning — MVP2 (requires multi-step trial design).
- **ERR@k metric** — MVP2. Not provided by pytrec_eval; needs custom implementation. Deferred until the metric expansion alongside CMA-ES.

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

All cross-feature deps below are already merged on `main`; this feature is unblocked.

- ✅ **`infra_foundation`** (PR #4 merged 2026-05-09) — provides Postgres, Alembic, Arq worker scaffolding, structlog, and the `optuna` schema initializer at `backend/app/db/optuna_schema.py`.
- ✅ **`infra_adapter_elastic`** (PR #16 merged 2026-05-10) — provides `SearchAdapter` Protocol + `ElasticAdapter` (the `search_batch` callee that `run_trial` invokes).
- ✅ **`feat_study_lifecycle` Phase 1 (Schema)** (PR #18 merged 2026-05-10) — Alembic head `0003_study_lifecycle_schema` shipped the `studies`, `trials`, `judgment_lists`, `proposals`, `query_*` tables (full MVP1 shape) and 15 minimal repo functions covering this feature's read/write set. Ordering achieved: Phase 1 schema → `infra_optuna_eval` (this feature) → `feat_study_lifecycle` Phase 2 (orchestrator + API).
- **Optuna ≥ 3.6** — required for Postgres ≥ 14 + Python 3.12 wheel availability + the lifted `engine.connect()` deprecation. (Note: Optuna's `RDBStorage` is **synchronous**; this feature wraps blocking calls in `asyncio.to_thread()` from the async Arq job.)
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
- The system **MUST** rely on the existing `make migrate` step to create the `optuna` schema (already wired to `python -m backend.app.db.optuna_schema` in `infra_foundation` Story 2.2 — issues `CREATE SCHEMA IF NOT EXISTS optuna` idempotently). Optuna's own internal tables are created during the first `RDBStorage` construction or first storage operation against an empty `optuna` schema (Optuna's `_rdb.alembic` machinery runs internally and idempotently inside the storage class — RelyLoop's Alembic does NOT manage Optuna's tables). The exact trigger (constructor-time vs. first method call) is an Optuna implementation detail this spec does not constrain; the only guarantees this spec relies on are: (a) the `optuna` schema exists before `RDBStorage` is touched, and (b) Optuna's tables land in the `optuna.*` namespace, never `public.*`.
- The system **MUST NOT** create Optuna tables in the `public` schema.
- Notes: per [`optimization.md` §"Optuna configuration"](../../../01_architecture/optimization.md).

### FR-2: TPE sampler + MedianPruner are MVP1 defaults
- The system **MUST** default `studies.config.sampler` to `tpe` when the key is omitted from `studies.config`; permitted values when present: `tpe`, `random`.
- The system **MUST** default `studies.config.pruner` to `median` (with `n_warmup_steps=10`) when the key is omitted from `studies.config`; permitted values when present: `median`, `none`.
- The system **MUST** auto-disable pruning when `studies.config.max_trials < 50` AND `studies.config.pruner` is **omitted** (key not present). When `studies.config.pruner = 'median'` is **explicitly present** in the stored config, pruning is forced ON regardless of `max_trials` — operator override.
- The data-contract distinction between "default-omitted" and "explicit-median" lives in `studies.config` itself: Phase 2's API is required NOT to materialize defaults into the stored row (omitted keys stay omitted). The worker reads `studies.config` and treats key presence as the explicitness signal.
- Notes: CMA-ES + intermediate-step pruning reserved for MVP2.

### FR-3: pytrec_eval evaluator helper
- The system **MUST** provide `backend/app/eval/scoring.py:score(qrels, run, metrics)` returning `{aggregate: {metric: value}, per_query: {query_id: {metric: value}}}`.
- The system **MUST** support metric set: `ndcg@k`, `map`, `precision@k`, `recall@k`, `mrr` for k ∈ {1, 3, 5, 10, 20, 50, 100}. ERR@k is **out of scope** (not in pytrec_eval; see §3 Out of scope).
- The system **MUST** translate user-facing metric names to pytrec_eval's wire names before invoking pytrec_eval. Translation table:
  | User-facing | pytrec_eval wire name |
  |---|---|
  | `ndcg@<k>` | `ndcg_cut_<k>` |
  | `map` (full recall, no cut) | `map` |
  | `map@<k>` | `map_cut_<k>` |
  | `precision@<k>` | `P_<k>` |
  | `recall@<k>` | `recall_<k>` |
  | `mrr` | `recip_rank` |

  The user-facing names are what the API accepts and what `studies.objective.metric` stores; the wire names never leak past `score()`. Plain `map` (no `@k`) is the full-recall MAP per pytrec_eval's default; use `map@k` only when an explicit cut is desired.
- The system **MUST** handle both graded (0..3) and binary (0..1) judgment ratings.
- The system **SHOULD** complete scoring in <100ms per query for a 50-query set with top_k=10 (verified by benchmark in `backend/tests/benchmarks/test_scoring_perf.py`).

### FR-4: `run_trial` Arq job
- The system **MUST** define `run_trial(ctx, study_id, optuna_trial_number)` as an Arq job in `backend/workers/trials.py`, registered with the `WorkerSettings.functions` list at `backend/workers/all.py`.
- The system **MUST** execute the trial in this order: load the study + Optuna trial via `study.trials[optuna_trial_number]` (orchestrator pre-assigned per §11), fetch the configured adapter via the `clusters` row, fetch the judgment list, fetch the template, render N native queries via `adapter.render(template, params, query_text)`, call `adapter.search_batch(target, native_queries, top_k)`, score via pytrec_eval, **call `study.tell(optuna_trial, value)` first**, **then INSERT the app `trials` row** (this ordering — tell-before-row — is what makes §11's idempotency contract correct: the Optuna trial's terminal state is the recoverable source of truth if the worker dies between tell and INSERT).
- The system **MUST** persist `trials.status = 'failed'` with the exception message in `trials.error` if any step raises (adapter, render, search, score). The job does NOT re-raise unless the failure is infra-level (DB unreachable).
- The system **MUST** propagate the trial_id as structlog context for all log records emitted during the job.
- Notes: covers US-7, US-8.

### FR-5: Trial metrics persisted with primary denormalized
- The `trials.metrics` JSONB column **MUST** contain all configured metrics, keyed by their **user-facing** name (per FR-3 — e.g., `ndcg@10`, `map@10`, `mrr`, plain `map` for full-recall MAP). Wire-side names (`ndcg_cut_10`, `recip_rank`, etc.) never appear in stored metrics.
- The `trials.primary_metric` REAL column **MUST** be denormalized from `metrics[objective_metric_key(study.objective)]` for fast index-backed sort. The system **MUST** provide `objective_metric_key(objective: dict) -> str` in `backend/app/eval/scoring.py` (alongside `score()`) with this contract:
  - For cut-aware metrics (`ndcg`, `precision`, `recall`): returns `f"{objective.metric}@{objective.k}"` — e.g., `objective.metric='ndcg', objective.k=10` → `"ndcg@10"`.
  - For non-cut metrics (`mrr`): returns `objective.metric` alone — e.g., `"mrr"` (`objective.k` is ignored).
  - For `map`: returns `f"map@{objective.k}"` if `objective.k` is set, else plain `"map"` (full recall).
- The `trials.duration_ms` INT column **MUST** record wall-clock time from `study.ask()` to `study.tell()`.

## 8) API and data contract baseline

### 8.1 Endpoint surface

N/A — no HTTP endpoints. This feature is worker-internal.

### 8.4 Enumerated value contracts

This feature creates two source-of-truth files for the value contracts below:

- `backend/app/eval/types.py` — `Literal[...]` types for the **sampler / pruner / trial-status** enums (`SamplerKind`, `PrunerKind`, `TrialStatus`). Worker code imports these for inline validation. Phase 2 of `feat_study_lifecycle` re-imports them at the API layer when validating `studies.config` payloads.
- `backend/app/eval/scoring.py` — frozenset constants for the **metric-set and k-values**: `SUPPORTED_METRICS: frozenset[str]` and `SUPPORTED_K_VALUES: frozenset[int]`. These are tightly coupled with the `score()` helper's wire-name translation logic (per FR-3), so they live in the scorer module alongside the translator. Phase 2's API layer imports them for `studies.objective` validation.

`trials.status` is also enforced at the DB CHECK level (already shipped in `0003_study_lifecycle_schema`); the `TrialStatus` Literal in `types.py` mirrors that constraint for worker code use.

| Field | Accepted values (exact) | Backend source of truth |
|---|---|---|
| `studies.config.sampler` | `tpe`, `random` | `backend/app/eval/types.py` (`SamplerKind = Literal["tpe", "random"]`) |
| `studies.config.pruner` | `median`, `none` | `backend/app/eval/types.py` (`PrunerKind = Literal["median", "none"]`) |
| `studies.objective.metric` | `ndcg`, `map`, `precision`, `recall`, `mrr` | `backend/app/eval/scoring.py` (`SUPPORTED_METRICS: frozenset[str]`) |
| `studies.objective.k` | positive int ∈ {1, 3, 5, 10, 20, 50, 100}; **optionality is metric-dependent** — REQUIRED for `ndcg` / `precision` / `recall` (cut-aware metrics); OPTIONAL for `map` (presence means `map@k`, absence means full-recall MAP); IGNORED (and SHOULD be omitted) for `mrr`. | `backend/app/eval/scoring.py` (`SUPPORTED_K_VALUES: frozenset[int]`) |
| `trials.status` | `complete`, `failed`, `pruned` | DB CHECK constraint `trials_status_check` in [`migrations/versions/0003_study_lifecycle_schema.py`](../../../../migrations/versions/0003_study_lifecycle_schema.py); re-exported as `TrialStatus = Literal["complete", "failed", "pruned"]` at `backend/app/eval/types.py` for worker code |

### 8.5 Error code catalog

N/A — no HTTP-level errors from this feature. Trial failures land in `trials.status='failed'` with `trials.error` populated.

## 9) Data model and state transitions

This feature does NOT define new tables. It depends on `studies` + `trials` (both owned by `feat_study_lifecycle` per [`data-model.md` §"MVP1 table inventory"](../../../01_architecture/data-model.md)).

It consumes the pre-existing `optuna` schema (whose `CREATE SCHEMA IF NOT EXISTS` already shipped in `infra_foundation` Story 2.2 at [`backend/app/db/optuna_schema.py`](../../../../backend/app/db/optuna_schema.py)) and causes Optuna's own internal tables (`optuna.studies`, `optuna.trials`, etc.) to be created lazily on first `optuna.create_study(storage=RDBStorage(...))` call. Optuna manages those tables itself — they are not part of RelyLoop's Alembic chain. The application interacts with that namespace only via `optuna.storages.RDBStorage`.

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

- **Adapter raises (e.g., cluster unreachable mid-trial).** Trial status → `failed`; error message recorded; `study.tell()` is called with the `TrialState.FAIL` state so Optuna doesn't leave a dangling RUNNING trial.
- **pytrec_eval raises (e.g., empty judgment list).** Same — trial fails, study continues with the next trial.
- **Optuna RDB lock contention** at high parallelism. Optuna's locking is row-level; expected throughput is 10–50 trials/sec on a 4-worker pool against a single-instance Postgres. Beyond that, scale Postgres or reduce `parallelism`.
- **Worker process restart mid-trial.** Arq's visibility-timeout (default 300s) re-enqueues the job; the same `(study_id, optuna_trial_number)` pair may execute more than once. **`Optuna.Study.ask()` is NOT idempotent** — each call creates a new internal Optuna trial — and **Optuna's `RDBStorage` does NOT participate in the caller's app-DB transaction** (it manages its own SQLAlchemy engine). So the spec cannot promise "single-transaction rollback" of Optuna+app state on worker death.

  **Trial-number assignment.** The `optuna_trial_number` in `run_trial(ctx, study_id, optuna_trial_number)` is **pre-assigned by Phase 2's orchestrator before enqueue** by calling `study.ask()` itself (which returns a `FrozenTrial` whose `.number` is the value passed to the worker). This is the only valid contract — the spec does NOT permit "worker-derived" assignment because that would defeat clause 1's pre-work idempotency check (a number not knowable until the worker calls ask is not knowable before the work check). The worker therefore does NOT call `ask()`; it loads the in-flight trial via `study.trials[optuna_trial_number]`.

  **Idempotency check (TWO conditions, in order):**

  1a. **App-table check.** Query `trials` for an existing row matching `(study_id, optuna_trial_number)` with `status IN ('complete', 'failed', 'pruned')`. If found → return no-op.

  1b. **Optuna-side reconciliation.** If no app row exists, load `study.trials[optuna_trial_number]`. If its state is terminal (`COMPLETE` / `FAIL` / `PRUNED`), reconstruct the app `trials` row from the existing Optuna trial's `value` + `params` + `state` and INSERT it. Return after INSERT — DO NOT re-run search/score/tell. (Without this clause, a worker death between `tell()` and the app-row INSERT would corrupt subsequent retries: a fresh `ask()` would create a duplicate Optuna trial that contributes to TPE sampling, which actually does include `COMPLETE` trials.)

  Only if both 1a and 1b miss does the worker proceed to execute search → score → tell → INSERT app row.

  **Operational tolerance.** The contract above guarantees: (a) the app `trials` table has at-most-one terminal row per `(study_id, optuna_trial_number)`; (b) Optuna has at-most-one terminal trial per number once the retry settles; (c) ask-without-tell deaths still leave orphan Optuna `RUNNING` trials (the worker doesn't call ask, so Phase 2's orchestrator owns this case — if Phase 2 dies between `ask()` and the enqueue commit, the orphan accumulates). Orphan RUNNING trials are operationally tolerated for MVP1 — TPE samples from `study.trials` filtered by `state == COMPLETE`, ignoring RUNNING. A periodic reaper is tracked separately as `infra_optuna_orphan_reaper`.

  This is a deliberate, narrow correctness contract. The spec accepts orphan RUNNING noise in exchange for not over-promising atomicity that Optuna's storage class doesn't actually provide; the Optuna-side reconciliation step (clause 1b) is what closes the dangerous tell-then-die window that an app-only idempotency check would miss.

## 12) Given/When/Then acceptance criteria

### AC-1a: Optuna schema exists after `make migrate`

- Given a fresh `make migrate` run on an empty database.
- When the operator queries `SELECT schema_name FROM information_schema.schemata`.
- Then both `public` and `optuna` schemas exist. (RelyLoop's tables — including `studies` and `trials` — are in `public.*`; the `optuna` schema is empty at this point because Optuna defers table creation.)

### AC-1b: Optuna tables auto-create in the isolated schema on first storage use

- Given AC-1a holds (`optuna` schema exists; no Optuna tables yet).
- When an `RDBStorage("postgresql://.../?options=-csearch_path=optuna")` is constructed/used for the first time (whether via `optuna.create_study(storage=...)`, `optuna.load_study(...)`, or direct `RDBStorage(...)` construction at worker boot — Optuna's exact creation trigger is an implementation detail this AC does not constrain).
- Then Optuna's internal tables (e.g., `optuna.studies`, `optuna.trials`, `optuna.trial_values`) are created in `optuna.*` and do NOT collide with RelyLoop's `public.studies` / `public.trials` tables. Verify by `\dn+` (schemas) plus `\dt optuna.*` (tables in the optuna schema only).

### AC-2: TPE sampler is the default

- Given a study created without an explicit sampler config.
- When the worker initializes the Optuna study.
- Then `study.sampler.__class__.__name__ == 'TPESampler'`.

### AC-3: pytrec_eval matches a hand-computed baseline

- Given a fixture: 5 queries × 10 docs/query, with hand-curated judgments and a known ranking.
- When `score(qrels, run, {'ndcg@10', 'map@10'})` is called (the helper translates to pytrec_eval's `ndcg_cut_10` / `map_cut_10` internally per FR-3).
- Then the returned `aggregate['ndcg@10']` matches the hand-computed baseline within 1e-6, and the returned `aggregate['map@10']` matches within 1e-6.
- Example shape (illustrative — exact values are pinned by the implementation's full fixture, not by this spec):
  - Input: `qrels = {"q1": {"d1": 3, "d2": 2}, ...}`, `run = {"q1": {"d2": 0.9, "d1": 0.7}, ...}`
  - Expected: `aggregate.ndcg@10 ≈ 0.789` placeholder; the implementor computes the precise value from the full 5-query fixture and pins it in the test.

### AC-4: `run_trial` writes a complete trial

- Given a seeded study with the local-es cluster, a 50-query set, a hand-built judgment list, and `objective.metric = 'ndcg'`, `objective.k = 10`.
- When the worker dequeues a `run_trial(study_id, trial_number=1)` job.
- Then within 5 seconds, a `trials` row exists with `status='complete'`, `params` populated, `metrics` containing `ndcg@10`, `primary_metric` denormalized to `metrics.ndcg@10`, and `duration_ms` non-null.

### AC-5: Adapter failure surfaces as `status='failed'`

- Given the cluster `local-es` has been stopped (`docker compose stop elasticsearch`).
- When a `run_trial` job runs against a study targeting `local-es`.
- Then a `trials` row is written with `status='failed'`, `error` containing "CLUSTER_UNREACHABLE" (or similar), `metrics={}`, and `study.tell()` was called so Optuna does not deadlock.

### AC-6a: Pruning auto-disables for small studies (default-pruner case)

- Given a study with `config.max_trials = 30` (below the 50-trial pruning threshold) AND the `pruner` key is **absent** from `config` (default-omitted).
- When the worker initializes the Optuna study.
- Then `study.pruner.__class__.__name__ == 'NopPruner'`.

### AC-6b: Explicit `median` overrides the auto-disable safeguard

- Given a study with `config.max_trials = 30` AND `config.pruner = 'median'` is **explicitly present** in the stored config.
- When the worker initializes the Optuna study.
- Then `study.pruner.__class__.__name__ == 'MedianPruner'` — the explicit operator choice forces pruning on regardless of the small-study heuristic.

(Together AC-6a + AC-6b verify FR-2's two-pronged contract: omitted key triggers the safeguard; explicit key honors operator intent.)

### AC-7: Search uses _msearch, not per-query _search

- Given a `run_trial` invocation with 50 queries.
- When the trial executes (cassette-replayed).
- Then exactly one HTTP call to `_msearch` is made; zero calls to `_search`.

### AC-8: Retry contract (idempotency + Optuna-side reconciliation)

- **AC-8a (app-row idempotency):** Given a successful first `run_trial(study_id, N)` invocation that wrote a terminal app row, when the same job is replayed, then the worker returns no-op (app row count remains 1; Optuna trial count remains 1).
- **AC-8b (Optuna-side reconciliation after tell-then-die):** Given a `run_trial(study_id, N)` invocation in which `study.tell()` succeeded but the app-row INSERT did not run (worker died via `os._exit(1)`), and Optuna therefore has trial `N` in terminal state but the app `trials` table has no row for `(study_id, N)`, when the same job is replayed, then the worker reconstructs the app row from `study.trials[N]` (no second `ask()`, no re-execution of search/score), resulting in exactly one app row + exactly one Optuna trial in terminal state.

## 13) Non-functional requirements

- **Performance:** A 50-query trial against a 10K-doc local-es index completes in <500ms p99 (adapter call ~200ms, pytrec_eval scoring <50ms, Optuna ask/tell <100ms, DB write <100ms).
- **Reliability:** Worker survives Postgres restart cleanly. Arq's per-job visibility-timeout (default 300s) re-makes the job eligible for retry if the worker dies before `tell()` completes. Per the §11 retry contract: the app `trials` table has at-most-one terminal row per `(study_id, optuna_trial_number)`; ask-without-tell deaths leave orphan Optuna RUNNING trials that are operationally tolerated for MVP1 (a periodic reaper is out of scope here — tracked separately as `infra_optuna_orphan_reaper`). Infra-level DB failures (e.g., connection lost) MUST re-raise so Arq retries with backoff; trial-level failures (adapter, render, score) MUST land as `status='failed'` rows and the job returns successfully.
- **Operability:** Every trial logs a single INFO record at completion with `study_id`, `trial_number`, `status`, `primary_metric`, `duration_ms`. Failures log at WARN with the exception trace.

## 14) Test strategy requirements

- **Unit tests** (`backend/tests/unit/eval/`):
  - `test_scoring.py` — pytrec_eval helper against a hand-curated qrels/run pair; assert known nDCG@10, MAP, P@10 values within 1e-6. Also asserts the user-facing → wire-name translation produces the expected pytrec_eval input dict.
  - `test_metric_validation.py` — exercises this feature's `SUPPORTED_METRICS` / `SUPPORTED_K_VALUES` frozensets in `backend/app/eval/scoring.py` and the `SamplerKind` / `PrunerKind` `Literal` types in `backend/app/eval/types.py`. Asserts that out-of-allowlist values are rejected at the helper-function boundary (`score(metrics={...})` raises `ValueError` on unknown metric tokens). **API-payload validation against `studies.config` / `studies.objective` is Phase 2's concern, not this feature's.**
- **Integration tests** (`backend/tests/integration/`):
  - `test_optuna_rdb.py` — `make migrate` creates only the `optuna` schema (no Optuna tables yet); first `create_study(storage=RDBStorage(...))` call lazily creates Optuna's internal tables in `optuna.*` and they don't collide with `public.*`; concurrent ask/tell calls from two workers don't deadlock.
  - `test_run_trial.py` — full `run_trial` invocation against a seeded study + cassette-replayed local-es (using the existing pytest-recording infrastructure already established in `infra_adapter_elastic`'s adapter tests); asserts AC-4.
  - `test_run_trial_adapter_failure.py` — `run_trial` against a stopped cluster produces a `failed` trial row (AC-5).
  - `test_run_trial_idempotent_retry.py` — re-running `run_trial(study_id, optuna_trial_number)` after a successful first invocation is a no-op; the existing terminal `trials` row is detected and the job returns immediately (verifies §11 retry contract clause 1).
  - `test_run_trial_partial_failure.py` — simulates worker death AT TWO distinct failure points using `os._exit(1)` injection (NOT a regular Python exception — those are caught by the trial-failure handler and produce `status='failed'` rows, which is a different code path than worker death). The two scenarios:
    1. **Death after ask(), before tell().** Inject `os._exit(1)` at a monkeypatched seam right after `ask()` returns. After the death: app `trials` has zero rows for `(study_id, optuna_trial_number)`; Optuna has one RUNNING trial. Re-execute the job; assert: exactly one terminal app row, Optuna has 1 RUNNING (orphan, tolerated) + 1 COMPLETE.
    2. **Death after tell(), before app-row insert.** Inject `os._exit(1)` immediately after `tell()` succeeds but before the app-row INSERT. After the death: app has zero rows; Optuna has one COMPLETE trial at `optuna_trial_number = N`. Re-execute the job; assert: the worker's idempotency check (per §11 clause 1b — Optuna-side reconciliation) detects the existing terminal Optuna trial via `study.trials[N]` and reconstructs the app row from the cached Optuna state without re-running search/score. End state: exactly one terminal app row, exactly one COMPLETE Optuna trial (no duplicates).
- **Contract tests** (`backend/tests/contract/`):
  - `test_trial_row_shape.py` — written `trials` row populates exactly the columns documented in the `Trial` ORM model from `backend/app/db/models/trial.py` (shipped in `feat_study_lifecycle` Phase 1); asserts `params` / `metrics` are JSON-serializable, `primary_metric` is denormalized correctly, `duration_ms` is non-null on success, `status` matches the DB CHECK allowlist. **No Pydantic Trial model is introduced by this feature** — the API-layer Pydantic shape arrives in Phase 2.
- **E2E tests:** N/A — no UI.
- **Benchmarks** (`backend/tests/benchmarks/`):
  - `test_scoring_perf.py` — pytrec_eval scoring completes in <100ms per query for a 50-query × top_k=10 fixture. (Benchmark dir is new for this feature; create alongside.)

## 15) Documentation update requirements

- `docs/01_architecture/optimization.md` already documents the patterns; update if implementation diverges from the spec.
- `docs/03_runbooks/`: add `optuna-debugging.md` — how to inspect Optuna's RDB tables, replay a trial, diagnose pruner false-positives.
- `docs/05_quality/testing.md`: extend the existing pytest-recording cassette guidance (already used in `infra_adapter_elastic`'s engine tests) with the `run_trial`-specific pattern (full job replay against a recorded `_msearch` cassette).
- `docs/02_product/mvp1-user-stories.md`: mark US-7 / US-8 as "implemented" when this feature ships.

## 16) Rollout and migration readiness

- **Feature flags:** None.
- **Migration/backfill:** No application-table migrations in this feature (the `optuna` schema initializer already shipped with `infra_foundation`). Optuna's own internal tables are created during the first `RDBStorage` construction or storage operation against an empty `optuna` schema — no Alembic step for them in either RelyLoop's chain or as a separate explicit invocation.
- **Operational readiness gates:**
  - `make migrate` creates the `optuna` schema cleanly on a fresh database (already verified by `infra_foundation`).
  - First `RDBStorage` construction/use lazily creates Optuna's internal tables in `optuna.*` (verified by AC-1b).
  - The benchmark in `backend/tests/benchmarks/test_scoring_perf.py` passes on the CI runner.
- **Release gate:** `feat_study_lifecycle` Phase 2's `start_study` orchestrator can dispatch `run_trial` without modification.

## 17) Traceability matrix

All test paths use `backend/tests/...` (consistent with the project layout — there is no top-level `tests/`).

| FR ID | AC IDs | Planned story IDs (TBD) | Test files | Docs to update |
|---|---|---|---|---|
| FR-1 (RDBStorage) | AC-1a, AC-1b | TBD | `backend/tests/integration/test_optuna_rdb.py` | `docs/01_architecture/optimization.md` |
| FR-2 (TPE + MedianPruner) | AC-2, AC-6a, AC-6b | TBD | `backend/tests/integration/test_optuna_rdb.py`, `backend/tests/unit/eval/test_metric_validation.py` | `docs/01_architecture/optimization.md` |
| FR-3 (pytrec_eval helper) | AC-3 | TBD | `backend/tests/unit/eval/test_scoring.py`, `backend/tests/benchmarks/test_scoring_perf.py` | `docs/01_architecture/optimization.md` |
| FR-4 (run_trial job) | AC-4, AC-5, AC-7, AC-8a, AC-8b | TBD | `backend/tests/integration/test_run_trial.py`, `backend/tests/integration/test_run_trial_adapter_failure.py`, `backend/tests/integration/test_run_trial_idempotent_retry.py`, `backend/tests/integration/test_run_trial_partial_failure.py` | `docs/03_runbooks/optuna-debugging.md` |
| FR-5 (trial metrics persisted) | AC-4 | TBD | `backend/tests/contract/test_trial_row_shape.py` | — |

## 18) Definition of feature done

- [ ] All ACs pass in CI: AC-1a, AC-1b, AC-2, AC-3, AC-4, AC-5, AC-6a, AC-6b, AC-7, AC-8a, AC-8b.
- [ ] All test layers green; ≥80% coverage on `backend/app/eval/scoring.py` and `backend/workers/trials.py`.
- [ ] Benchmark `backend/tests/benchmarks/test_scoring_perf.py` passes (<100ms/query).
- [ ] `docs/03_runbooks/optuna-debugging.md` merged.
- [ ] `feat_study_lifecycle` Phase 2 author confirms the `run_trial` interface meets the orchestrator's needs.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None — all resolved (see Decision log).

### Decision log

- 2026-05-09 — pytrec_eval everywhere (no engine-native `_rank_eval`) — per umbrella spec §14 + [`optimization.md`](../../../01_architecture/optimization.md).
- 2026-05-09 — Optuna co-tenants with app Postgres (separate schema) — per umbrella spec §13.
- 2026-05-09 — Multi-objective deferred to v2; CMA-ES deferred to MVP2 — per [`optimization.md` §"Reserved for later releases"](../../../01_architecture/optimization.md).
- 2026-05-09 — `studies.config.trial_timeout_s` default: **60s** (per `feat_study_lifecycle` decision-log).
- 2026-05-09 — Optuna RDB schema bootstrap: **invoke explicitly via `make migrate`**. Already implemented in `infra_foundation` Story 2.2 — the Makefile runs `alembic upgrade head` then `python -m backend.app.db.optuna_schema`, which idempotently issues `CREATE SCHEMA IF NOT EXISTS optuna`. Optuna's own tables auto-create lazily on the first `optuna.create_study(storage=RDBStorage(...))` call (Optuna's documented mechanism — there is no `RDBStorage.initialize()` method). Patched 2026-05-10: earlier draft incorrectly cited a `python -c "...RDBStorage(...).initialize()"` call that doesn't exist; the actual mechanism is the existing `python -m backend.app.db.optuna_schema` invocation.

### Review log

- **2026-05-10 — Review-and-patch pass against shipped upstream features.** Audit found:
  - File-path corrections: `backend/eval/...` → `backend/app/eval/...`; `backend/worker/...` → `backend/workers/...` (multiple §3, §FR-3, §FR-4, §8.4, §17, §18 references).
  - §8.4 enumerated-value source-of-truth relocated: `SamplerKind`/`PrunerKind`/`TrialStatus` Literals don't live on the ORM models (which use `Mapped[str]`); created at `backend/app/eval/types.py` for both this feature's worker and Phase 2 of `feat_study_lifecycle`'s API layer to import.
  - ERR@k dropped from FR-3 (not in pytrec_eval); deferred to MVP2 alongside the metric expansion. §3 Out of scope updated.
  - §FR-3 metric naming: added wire-name translation note (`ndcg@k` → `ndcg_cut_<k>`, `mrr` → `recip_rank`, etc.) so implementors don't pass user-facing names directly to pytrec_eval.
  - §2 Current state audit rewritten in present tense with PR # citations (`infra_foundation` #4, `infra_adapter_elastic` #16, `feat_study_lifecycle` Phase 1 #18).
  - §5 dependencies marked ✅ Done; Optuna ≥ 3.6 rationale corrected (`RDBStorage` is sync; async-friendliness is the caller's via `asyncio.to_thread`).
  - §13 NFR Postgres-restart wording made precise around Arq's visibility-timeout retry mechanism.
  - §AC-3 nDCG@10=0.789 reclassified as illustrative (not reproducible from the truncated example fixture).
  - Decision log entry 5 corrected to match the actual `python -m backend.app.db.optuna_schema` mechanism.
  - References to `feat_study_lifecycle` updated to distinguish Phase 1 (shipped) from Phase 2 (deferred — orchestrator + 12 endpoints + `start_study` job).
  - Status: Draft → **Approved**.
- **2026-05-10 — GPT-5.5 cross-model review, cycle 1.** Initial attempt returned 429 `insufficient_quota`; once quota was restored, cycle 1 raised 12 findings (3 High, 7 Medium, 2 Low). Adjudication: **10 accepted, 2 rejected with cited counter-evidence**.
  - Highs accepted: (1) FR-1 + §16 still cited `optuna.storages._rdb.alembic` despite the corrected decision-log entry — propagated the fix to FR-1 + §16. (3) §11 + §13 falsely claimed `Optuna.Study.ask()` is "idempotent on trial_number" — `ask()` does not accept a trial number arg and creates a new trial each call; rewrote both sections around the actual retry contract (worker checks for existing terminal `trials` row by `(study_id, optuna_trial_number)`; ask + execute + tell wrapped in a single Postgres transaction; orchestrator-vs-worker assignment of `optuna_trial_number` deferred to the impl plan). (10) §13 reliability claim depended on the false idempotency — relinked to the new contract.
  - Mediums accepted: (2) §AC-1 split into AC-1a (schema exists after make migrate) + AC-1b (Optuna tables auto-create on first create_study). (5) §AC-6 narrowed to the default-pruner case so it doesn't contradict FR-2's explicit-override sentence. (6) §FR-3 translation table made `map`/`map@k` distinction explicit (full-recall vs cut). (7) §8.4 prose split source-of-truth correctly: `types.py` for sampler/pruner/trial-status, `scoring.py` for metric set + k values. (8) §14 test names reworded to clarify scope is THIS feature's eval/ types and frozensets, not Phase 2's API-layer Pydantic validators.
  - Lows accepted: (11) §9 reworded — this feature consumes the pre-existing `optuna` schema initializer (shipped in `infra_foundation`), it does not "add" the schema. (12) Header `Consumed by:` updated to specify `feat_study_lifecycle` Phase 2.
  - **Highs rejected with cited counter-evidence:** (4) GPT-5.5 claimed no `clusters` table and no `adapter.render()` API. Rejected — `clusters` shipped in `0002_clusters_config_repos.py` from `infra_adapter_elastic` PR #16 (verified earlier this session via `\dt`); `render()` shipped in PR #16 Epic 2 per state.md ("Epic 2: ... `render` (Jinja → ES Query DSL)").
  - **Mediums rejected with cited counter-evidence:** (9) GPT-5.5 claimed cassette infra doesn't exist. Rejected — `pyproject.toml:50` adds `pytest-recording>=0.13`; cassette references already in `backend/tests/unit/adapters/test_elastic_schema.py:105` from PR #16.
  - **Cycle 2 trigger:** Findings 1, 3, 5, 6, 8 are major (changed FR text, AC text, or test contract). Re-running GPT-5.5 with the rejection log per the spec-gen skill's convergence protocol.
- **2026-05-10 — GPT-5.5 cross-model review, cycle 2.** 6 new findings (2 High, 4 Medium); zero repeats from cycle 1's rejection log. **All 6 accepted** — cycle 2 surfaced real defects in the cycle-1 patches (which is exactly what subsequent review cycles are for):
  - High (1) — **Cycle 1's shared-transaction claim was wrong.** I patched §11/§13 with "wrap ask → execute → tell + row INSERT in a single Postgres transaction so a worker death rolls back both the Optuna trial state and the partial app row." Cycle 2 correctly pointed out that Optuna's `RDBStorage` manages its own SQLAlchemy engine — it does NOT participate in the caller's app-DB transaction, so app-level rollback cannot undo Optuna-side state. Rewrote §11 + §13 around an honest narrower contract: app-table idempotency on `(study_id, optuna_trial_number)`; ask-without-tell deaths leave orphan Optuna RUNNING trials that MVP1 explicitly tolerates; a future periodic reaper is tracked separately as `infra_optuna_orphan_reaper`. This trades a small amount of operational noise for a contract the implementation can actually keep.
  - High (2) — **FR-5 denormalization key mismatch.** FR-5 said `metrics[study.objective.metric]` but `metrics` is keyed by user-facing names like `'ndcg@10'` while `objective.metric` is the base name `'ndcg'`. Defined `objective_metric_key(objective: dict) -> str` in `backend/app/eval/scoring.py` (cut-aware metrics → `f"{metric}@{k}"`; non-cut → `metric` alone; `map` is special-cased on whether `k` is set). Updated FR-5 to use this helper.
  - Medium (3) — AC-3 contradicted FR-3's `map` vs `map@k` distinction. Changed AC-3's call to `{'ndcg@10', 'map@10'}` to match the cut-MAP intent.
  - Medium (4) — FR-1 + AC-1b + §16 said Optuna creates tables "on first `create_study()`"; Optuna's actual trigger may be RDBStorage construction. Rephrased to "first `RDBStorage` construction or use" — neutral about Optuna's internal timing detail; only commits to the two guarantees we actually rely on (schema exists; tables land in `optuna.*`).
  - Medium (5) — `test_run_trial_idempotent_retry.py` only covered the easy case. Added `test_run_trial_partial_failure.py` to fault-inject between ask() and tell() and verify the contract that orphan Optuna RUNNING + idempotent app-table behavior actually holds.
  - Medium (6) — Cycle 1's narrowing of AC-6 left FR-2's explicit-override path uncovered. Split AC-6 into AC-6a (default-omitted → NopPruner) + AC-6b (explicit `pruner='median'` → MedianPruner regardless of max_trials). Added FR-2 data-contract clause: "Phase 2's API is required NOT to materialize defaults into the stored row" — key absence is the explicitness signal the worker reads.
  - Cycle 2 had **zero rejects** — all findings were legitimate corrections to cycle-1 patches. **Cycle 3 trigger:** Findings 1 and 2 are major (rewrote retry contract; introduced new helper function). Running cycle 3 with the cumulative cycle 1 + cycle 2 rejection log per the skill's convergence protocol.
- **2026-05-10 — GPT-5.5 cross-model review, cycle 3.** 6 new findings (2 High, 3 Medium, 1 Low); zero repeats from the cumulative rejection log. **All 6 accepted** — cycle 3 caught two more architectural issues that cycle-2's patches introduced:
  - High (1) — **Cycle 2's "tell() then INSERT" ordering created a NEW failure window** I had missed: worker dies between `tell()` succeeding and the app-row INSERT → Optuna has a terminal trial; app has no row; the cycle-2 idempotency check passes (no app row found) → next retry calls `ask()` again, creating a duplicate Optuna trial that, unlike RUNNING orphans, *is included in TPE sampling*. Fixed by adding clause 1b to §11: an Optuna-side reconciliation step that, on app-row-miss, loads `study.trials[optuna_trial_number]` and reconstructs the app row from the existing terminal Optuna state without re-executing.
  - High (2) — **`optuna_trial_number` semantic ambiguity.** Cycle-2's §11 said the value could be "pre-assigned by orchestrator OR derived in worker via `study.ask().number`" — but those aren't equivalent: worker-derived isn't knowable before the idempotency check runs, AND a pre-assigned number can't be passed to `ask()` (which doesn't accept that arg). Locked in **orchestrator pre-assignment** as the only valid contract: Phase 2 calls `study.ask()` itself before enqueue and passes the returned trial number to the worker; the worker uses `study.trials[N]` to load the in-flight Optuna trial without calling ask again.
  - Medium (3) — **FR-4 vs §11 internal contradiction.** Cycle 2 flipped §11 to "tell() then row INSERT" but FR-4 still said "row INSERT then tell()". Aligned FR-4 with the §11 ordering and added rationale tied to clause 1b's reconciliation requirement.
  - Medium (4) — **`objective.k` optionality undocumented.** §8.4 said `k ∈ {1, 3, 5, ...}` without saying when it can be omitted. Added per-metric conditional: required for ndcg/precision/recall; optional for map (presence = `map@k`, absence = full-recall MAP); ignored for mrr.
  - Medium (5) — **`test_run_trial_partial_failure.py` description was wrong.** Said "monkeypatch `adapter.search_batch` to raise" — but that's a normal trial-level failure path FR-4 requires to produce `status='failed'`, not a worker-death simulation. Reworded to use `os._exit(1)` injection at TWO failure points (after ask before tell; after tell before INSERT) covering both AC-8a and AC-8b.
  - Low (6) — **§17 traceability missing the new retry tests.** Added AC-8 (split into AC-8a app-row idempotency + AC-8b Optuna-side reconciliation), mapped both retry tests in the FR-4 row, added to §18 DoD checklist.
  - Cycle 3 had **zero rejects** — all findings were legitimate corrections to cycle-2 patches. **Convergence note:** the spec-gen skill's 3-cycle ceiling has been reached. Cycle 3's findings are all applied. Cycle 4 was NOT run (skill rule). Operator decision: ship at cycle-3 convergence; further architectural concerns (Optuna behaviors not empirically validated against the actual library version, edge-case interleavings of the orchestrator and worker) are deferred to the implementation plan + integration tests, where they can be validated against running code rather than spec prose.
