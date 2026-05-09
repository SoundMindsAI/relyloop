# Feature Specification — feat_llm_judgments

**Date:** 2026-05-09
**Status:** Draft
**Owners:** TBD
**Related docs:**
- [docs/02_product/mvp1-user-stories.md](../../mvp1-user-stories.md) — covers US-13, US-14, US-15
- [docs/01_architecture/llm-orchestration.md](../../../01_architecture/llm-orchestration.md) — OpenAI SDK + function calling pattern
- [docs/01_architecture/data-model.md](../../../01_architecture/data-model.md) — `judgment_lists`, `judgments` tables
- [docs/01_architecture/optimization.md](../../../01_architecture/optimization.md) — pytrec_eval consumes judgments
- Depends on: [`infra_foundation`](../infra_foundation/feature_spec.md), [`infra_adapter_elastic`](../infra_adapter_elastic/feature_spec.md), [`feat_study_lifecycle`](../feat_study_lifecycle/feature_spec.md)

---

## 1) Purpose

- **Problem:** Studies need ground-truth judgments to score trials. Hand-labeling 50–500 (query, doc) pairs is slow and gates the loop. An LLM-as-judge pipeline generates an initial judgment list in minutes, with a calibration check + override UI to let the relevance team correct mistakes.
- **Outcome:** A relevance engineer selects a query set + cluster + target + rubric and the system runs the current template to fetch top-K hits per query, asks OpenAI to rate each (query, doc) on a 0–3 scale with rationale, and persists the result as a `judgment_lists` row + `judgments` rows. The team then reviews via the override flow and computes Cohen's kappa against a 30–50-pair human sample.
- **Non-goal:** No click-derived judgments (Fusion Signals → judgment converter is v1.5+). No multi-LLM provider abstraction (MVP4). No judgment list versioning beyond "regenerating with a different rubric creates a new list" (immutable). No agent-tool wrapping at the chat layer (that's `feat_chat_agent`'s job to expose `generate_judgments_llm`).

## 2) Current state audit

After dependencies ship:
- `query_sets`, `queries`, `clusters` tables exist (per `feat_study_lifecycle` + `infra_adapter_elastic`).
- `judgment_lists` exists with the **full MVP1 shape** per [`data-model.md`](../../../01_architecture/data-model.md) — created by `feat_study_lifecycle` (the previously-described "stub" approach was changed during the schema-locking pass per the data-model.md §"MVP1 table inventory + migration ownership"). This feature creates ONLY the `judgments` child table and writes rows + status updates into the existing `judgment_lists`.
- `openai` Python SDK is installed (per `infra_foundation`) but no LLM calls are made yet.
- No `prompts/` directory exists yet — this feature creates `prompts/judgment_generation.system.md` + `prompts/judgment_generation.user.jinja` + `prompts/judgment_generation.rubric_v1.md` per [`llm-orchestration.md` §"Prompt directory layout"](../../../01_architecture/llm-orchestration.md).

## 3) Scope

### In scope

- Migration creating `judgments` table per [`data-model.md`](../../../01_architecture/data-model.md): `(judgment_list_id, query_id, doc_id, rating, source, rater_ref, confidence, notes, created_at)` with `UNIQUE (judgment_list_id, query_id, doc_id)`.
- This feature does NOT migrate `judgment_lists` — the full MVP1 shape (including `cluster_id`, `target`, `current_template_id`, `status`, `failed_reason`, `calibration`) is created by `feat_study_lifecycle`.
- API endpoints:
  - `POST /api/v1/judgments/generate` — async; creates `judgment_lists` row with `status='generating'` + persists `cluster_id`/`target`/`current_template_id` so the worker can reconstruct context; enqueues `generate_judgments_llm(judgment_list_id)` Arq job; returns `{judgment_list_id, status: 'generating'}`
  - `POST /api/v1/judgment-lists/import` — **import path for pre-baked judgments** (used by the tutorial's no-OpenAI first-run flow per `chore_tutorial_polish`). Accepts `{name, description?, query_set_id, cluster_id, target, rubric, judgments: [{query_id, doc_id, rating, notes?}]}`. Creates `judgment_lists` row with `status='complete'`, `current_template_id=NULL` (imports aren't tied to a template), and bulk-inserts the `judgments` rows with `source='human'`, `rater_ref='import'`. Returns the created list.
  - `GET /api/v1/judgment-lists` (paginated) + `GET /api/v1/judgment-lists/{id}` (returns list + counts by source + calibration if present)
  - `GET /api/v1/judgment-lists/{id}/judgments` (paginated, filterable by `source`)
  - `PATCH /api/v1/judgment-lists/{id}/judgments/{judgment_id}` — override a single rating (creates a new judgment row with `source='human'` and the same `(query_id, doc_id)` — UNIQUE constraint enforced via UPSERT)
  - `POST /api/v1/judgment-lists/{id}/calibration` — accepts a list of human-labeled (query_id, doc_id, rating) tuples; computes Cohen's kappa vs. the LLM ratings and writes to `judgment_lists.calibration` JSONB
- Worker job: `generate_judgments_llm(query_set_id, cluster_id, target, current_template_id, rubric_text)` in `backend/worker/judgments.py`:
  - For each query in the query set: render the current template with default params, call `adapter.search_batch` for top-K (default 50) hits, ask OpenAI to rate each (query, doc) pair on a 0–3 scale with rationale (one batched call per query — `n_queries` total LLM calls)
  - Persist judgments with `source='llm'`, `rater_ref='openai:gpt-4o-2024-08-06'`
  - Stamp the parent `judgment_lists` row with `status='complete'` (or `failed` with error)
- Prompts in `prompts/judgment_generation.*` per [`llm-orchestration.md` §"Prompt directory layout"](../../../01_architecture/llm-orchestration.md). Default rubric (`rubric_v1.md`) is a 0–3 scale: 0=irrelevant, 1=marginally relevant, 2=relevant, 3=highly relevant — generic e-commerce-ish wording suitable for the tutorial.
- Cohen's kappa helper in `backend/eval/calibration.py` (also computes weighted kappa and per-rating-class agreement breakdown).

### Out of scope

- Click-derived judgments (Fusion Signals integration) — v1.5+.
- Multi-LLM provider abstraction — MVP4.
- Judgment list versioning beyond "new rubric → new list" — MVP2 if needed.
- Hidden ground-truth holdout for double-blind eval — MVP2.
- Agent-tool exposure (`generate_judgments_llm` as a chat tool) — `feat_chat_agent`.
- UI for judgment review — `feat_studies_ui` (the review surface lives at `/judgments/{id}` in the Next.js app).

### API convention check

Per [`api-conventions.md`](../../../01_architecture/api-conventions.md). All endpoints under `/api/v1/`. Cursor pagination on list endpoints. Structured error envelope.

### Phase boundaries

Single-phase. The MVP1 deliverable is "create a judgment list via API for the tutorial 50-query set, watch it complete in under 5 minutes for under $1 of OpenAI cost, then run a study against it that achieves a meaningful nDCG@10 lift over baseline."

## 4) Product principles and constraints

- **One LLM call per query, not per (query, doc).** Batching all top-K docs into a single rating call per query trades latency for cost — 50 calls (one per query) at ~$0.01 each = $0.50 for a 50-query × 50-doc judgment set, vs. $25 for per-doc. The model returns a JSON array of `{doc_id, rating, rationale}`.
- **Re-running with a changed rubric creates a new judgment list.** Old list is preserved (immutable). Studies that referenced the old list keep their results stable.
- **Human overrides shadow LLM ratings.** The `judgments` UNIQUE constraint on `(judgment_list_id, query_id, doc_id)` means a human override REPLACES the LLM rating for that pair. The original LLM rating is lost from the active list (recoverable via git/DB backup if needed; per project preference, no DEPRECATED-style preservation).
- **Calibration is advisory, not gating.** A judgment list with poor calibration kappa (<0.6) is flagged with a UI warning but still usable. The relevance team makes the call.
- **Cost guardrail.** Per [`llm-orchestration.md` §"Cost & error handling"](../../../01_architecture/llm-orchestration.md), the daily OpenAI budget gate applies. Generation jobs check the budget before starting and refuse with `OPENAI_BUDGET_EXCEEDED` if exceeded.

### Anti-patterns

- **Do not** issue per-(query, doc) LLM calls. Batch per query.
- **Do not** stream judgment generation. The job is a worker async task; the API returns the `job_id` immediately and the UI polls `/api/v1/judgment-lists/{id}` for status.
- **Do not** allow rubric edits in place. A new rubric → a new judgment list.
- **Do not** use floating model tags (`gpt-4o`). Pin the version (`openai:gpt-4o-2024-08-06`) per [`llm-orchestration.md`](../../../01_architecture/llm-orchestration.md).

## 5) Assumptions and dependencies

- **Dependency: `infra_foundation`** — Postgres, Arq, settings; `OPENAI_API_KEY_FILE` mounted (per [`deployment.md`](../../../01_architecture/deployment.md)).
- **Dependency: `infra_adapter_elastic`** — `clusters` rows exist; `SearchAdapter.search_batch` works for fetching top-K candidates per query.
- **Dependency: `feat_study_lifecycle`** — `query_sets`, `queries`, `query_templates` tables; stub `judgment_lists` table this feature extends.
- **OpenAI API key** is required at generation time (the API logs a warning at startup if missing per `infra_foundation` FR-3; `POST /api/v1/judgments/generate` returns `OPENAI_NOT_CONFIGURED` if missing).

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (kicks off generation, reviews + overrides ratings, supplies human-labeled samples for calibration).

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP2. When MVP2 ships, this feature's `judgment_list.generated`, `judgment_list.calibrated`, and `judgment.overridden` mutations will emit audit events.

## 7) Functional requirements

### FR-1: judgments schema
- The system **MUST** create the `judgments` table per [`data-model.md`](../../../01_architecture/data-model.md) with `UNIQUE (judgment_list_id, query_id, doc_id)`.
- The system **MUST NOT** extend `judgment_lists` (full MVP1 shape owned by `feat_study_lifecycle`). This feature only writes rows + status/calibration updates.

### FR-2: Generate-judgments worker job
- The system **MUST** define `generate_judgments_llm(ctx, judgment_list_id)` as an Arq job in `backend/worker/judgments.py`.
- The job **MUST** load the `judgment_lists` row to get `cluster_id`, `target`, `current_template_id`, `query_set_id`, `rubric` — these are persisted on the row by the `POST /generate` endpoint so the worker is fully self-contained on a `judgment_list_id`.
- The job **MUST** for each query in the set: render the current template (default params), `adapter.search_batch(target, [query], top_k=50)`, batched LLM call asking for ratings + rationales for all returned docs, persist `judgments` rows with `source='llm'` and `rater_ref='openai:gpt-4o-2024-08-06'`, `notes` populated with the rationale.
- The job **MUST** mark the parent `judgment_lists.status = 'complete'` on success or `'failed'` with an error reason on infra-level failure.
- The job **MUST** check the daily OpenAI budget before each LLM call; if exceeded, partial results persist + the list status becomes `failed` with reason `OPENAI_BUDGET_EXCEEDED`.
- Notes: covers US-13.

### FR-3: Generate endpoint
- `POST /api/v1/judgments/generate` accepts `{name, description?, query_set_id, cluster_id, target, current_template_id, rubric}` and:
  - Creates a `judgment_lists` row with `status='generating'`, persisting `cluster_id`/`target`/`current_template_id`/`query_set_id`/`rubric` on the row
  - Enqueues `generate_judgments_llm(judgment_list_id)` (the worker is fully self-contained on `judgment_list_id`)
  - Returns HTTP 202 with `{judgment_list_id, status: 'generating'}`
- The endpoint **MUST** validate `OPENAI_API_KEY_FILE` is configured at request time (returns `OPENAI_NOT_CONFIGURED` if not).
- The endpoint **MUST** read the capability cache (per `infra_foundation` FR-7) and refuse with `LLM_PROVIDER_INCAPABLE` (HTTP 503, `retryable: false`) if `structured_output != "ok"` for the configured `OPENAI_BASE_URL`. Judgment generation requires structured output and will not work against a model that can't deliver it. (The error message names the capability that's missing so the operator knows which model to upgrade.)

### FR-3c: Starter rubric content for `prompts/judgment_generation.rubric_v1.md`

Ships as a placeholder; Product replaces with the final tailored content (per §19 open question) before this feature merges. The starter is generic-enough to demo against any e-commerce-shaped dataset (including the Amazon ESCI subset shipped by `chore_tutorial_polish`):

```markdown
# Relevance Rubric v1

Rate each (query, document) pair on a 0–3 scale based on how well the document satisfies the user's intent expressed by the query.

**3 — Highly relevant.** This document is exactly what the user wants. They would click through, find the information / product they're looking for, and consider the search successful. Examples: searching "wireless noise-canceling headphones" and getting Sony WH-1000XM5; searching "running shoes for flat feet" and getting a model explicitly designed for flat feet.

**2 — Relevant.** This document substantially addresses the query but isn't the perfect match. The user would consider it useful but might keep looking. Examples: searching "wireless noise-canceling headphones" and getting wireless headphones without active noise cancellation; searching "running shoes for flat feet" and getting general running shoes that don't specifically address flat feet.

**1 — Marginally related.** This document is in the same general category as the query but doesn't address the user's specific intent. The user would skip it. Examples: searching "wireless noise-canceling headphones" and getting wired earbuds; searching "running shoes for flat feet" and getting hiking boots.

**0 — Irrelevant.** This document has nothing meaningful to do with the query. Examples: searching "wireless noise-canceling headphones" and getting a kitchen appliance; searching "running shoes for flat feet" and getting a book about feet anatomy.

When in doubt between two ratings, choose the lower one — relevance ratings should be conservative.
```

The actual prompt sent to OpenAI **MUST** include this rubric in full as part of the system prompt.

### FR-3b: Import endpoint (tutorial path; no OpenAI required)
- `POST /api/v1/judgment-lists/import` accepts `{name, description?, query_set_id, cluster_id, target, rubric, judgments: [{query_id, doc_id, rating, notes?}]}` and:
  - Creates a `judgment_lists` row with `status='complete'`, `current_template_id=NULL`
  - Bulk-inserts every supplied judgment with `source='human'` (semantically: imported = curated by a human, even if the original generator was an LLM offline), `rater_ref='import'`
  - Returns HTTP 201 with the created list including `judgment_count`
- The endpoint **MUST** validate every `query_id` exists in the supplied `query_set_id` (returns `QUERY_NOT_IN_SET` for any invalid).
- Notes: this is the path `chore_tutorial_polish` uses to ship `samples/judgments.json` for a no-OpenAI first run.

### FR-4: Override endpoint
- `PATCH /api/v1/judgment-lists/{id}/judgments/{judgment_id}` accepts `{rating: int, notes?: str}` and:
  - UPSERTs a new `judgments` row with `source='human'`, `rater_ref='operator'`, `notes` as supplied (the `(judgment_list_id, query_id, doc_id)` UNIQUE means the LLM row is replaced, not duplicated)
- The endpoint **MUST** reject ratings outside 0..3 with `INVALID_RATING`.
- Notes: covers US-14.

### FR-5: Calibration endpoint
- `POST /api/v1/judgment-lists/{id}/calibration` accepts `{human_samples: [{query_id, doc_id, rating}]}` (30–50 typical) and:
  - For each sample, fetches the LLM rating from `judgments`
  - Computes Cohen's kappa, weighted kappa (linear weights), per-rating-class agreement breakdown via `backend/eval/calibration.py`
  - Persists to `judgment_lists.calibration` JSONB (overwrites prior calibration)
  - Returns HTTP 200 with the computed metrics
- Notes: covers US-15.

### FR-6: List + detail + paginated judgments
- `GET /api/v1/judgment-lists?cursor=&limit=` paginated.
- `GET /api/v1/judgment-lists/{id}` returns the list with `judgment_count`, `source_breakdown {llm: N, human: M}`, and `calibration` (if present).
- `GET /api/v1/judgment-lists/{id}/judgments?source=&cursor=&limit=` paginated; filterable by source.

## 8) API and data contract baseline

### 7.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/judgments/generate` | Kick off LLM generation (async) | `OPENAI_NOT_CONFIGURED`, `OPENAI_BUDGET_EXCEEDED`, `QUERY_SET_NOT_FOUND`, `CLUSTER_NOT_FOUND`, `TEMPLATE_NOT_FOUND`, `JUDGMENT_LIST_NAME_TAKEN` |
| `GET` | `/api/v1/judgment-lists` | List judgment lists | (none) |
| `GET` | `/api/v1/judgment-lists/{id}` | Detail with counts + calibration | `JUDGMENT_LIST_NOT_FOUND` |
| `GET` | `/api/v1/judgment-lists/{id}/judgments` | Paginated judgment rows | `JUDGMENT_LIST_NOT_FOUND` |
| `PATCH` | `/api/v1/judgment-lists/{id}/judgments/{judgment_id}` | Human override | `JUDGMENT_LIST_NOT_FOUND`, `JUDGMENT_NOT_FOUND`, `INVALID_RATING` |
| `POST` | `/api/v1/judgment-lists/{id}/calibration` | Compute kappa from human samples | `JUDGMENT_LIST_NOT_FOUND`, `INSUFFICIENT_SAMPLES` |

### 7.4 Enumerated value contracts

| Field | Accepted values | Backend source of truth |
|---|---|---|
| `judgment_lists.status` | `generating`, `complete`, `failed` | `backend/db/models/judgment_list.py` |
| `judgments.source` | `llm`, `human`, `click` | `backend/db/models/judgment.py` (`click` reserved for v1.5+) |
| `judgments.rating` | `0`, `1`, `2`, `3` | `backend/db/models/judgment.py` (CHECK constraint) |
| `?source` (filter on judgments list) | `llm`, `human` | `backend/api/judgments.py` |

### 7.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| `OPENAI_NOT_CONFIGURED` | 503 | `OPENAI_API_KEY_FILE` is missing/empty |
| `OPENAI_BUDGET_EXCEEDED` | 503 | Daily budget exceeded; `retryable: true` after 24h |
| `LLM_PROVIDER_INCAPABLE` | 503 | The configured `OPENAI_BASE_URL` doesn't support a required capability (e.g., structured output for judgments). `retryable: false`. Operator must reconfigure to a capable model/provider. |
| `JUDGMENT_LIST_NOT_FOUND` | 404 | List ID not found |
| `JUDGMENT_LIST_NAME_TAKEN` | 409 | Name already in use |
| `JUDGMENT_NOT_FOUND` | 404 | Judgment row not found within the list |
| `INVALID_RATING` | 400 | Rating not in 0..3 |
| `INSUFFICIENT_SAMPLES` | 400 | Calibration needs ≥10 human samples to compute meaningful kappa |
| `QUERY_SET_NOT_FOUND`, `CLUSTER_NOT_FOUND`, `TEMPLATE_NOT_FOUND` | 404 | Referenced entity missing |

## 9) Data model and state transitions

This feature extends `judgment_lists` (stub created by `feat_study_lifecycle`) and creates `judgments`. Schemas per [`data-model.md`](../../../01_architecture/data-model.md).

### State transitions

`judgment_lists.status`: `generating → complete | failed`. No transitions after terminal state.

`judgments`: append-only via UPSERT. Human overrides REPLACE LLM rows for the same `(query_id, doc_id)` (UNIQUE constraint).

## 10) Security, privacy, and compliance

- **Threats:**
  1. A user uploads a query set with malicious queries that exfiltrate via the LLM rationale (prompt injection). **Mitigation:** the OpenAI prompt template uses delimited query/doc fields (XML-style); rationale field is stored verbatim but never executed/rendered as HTML.
  2. A user generates judgments against a sensitive cluster (PII in doc content). **Mitigation:** the operator is responsible — the tool processes whatever the cluster returns. Documented in `docs/04_security/llm-data-flow.md` (added by this feature).
  3. Cost runaway via crafted query sets with thousands of queries. **Mitigation:** the daily budget gate; plus the API rejects query sets with >10K queries with `VALIDATION_ERROR` at generation time.
- **Secrets handling:** `OPENAI_API_KEY_FILE` only.
- **Auditability:** N/A — `audit_log` is MVP2.

## 11) UX flows and edge cases

This feature has no UI surface; the review/override UI is owned by `feat_studies_ui`. The API supports both UI and chat-agent consumers.

### Edge/error flows

- **OpenAI rate-limit during generation.** The worker retries with exponential backoff per [`llm-orchestration.md`](../../../01_architecture/llm-orchestration.md). After 3 failed attempts on the same query, the query is marked `failed` in the worker log; partial results persist; the list completes with `status='complete'` and `judgment_count` < expected.
- **Cluster goes unreachable mid-generation.** The current query fails; the worker continues with the next query (does not abort the whole list). Operator sees partial results.
- **Override before generation completes.** The list is `generating`; PATCH returns 409 `LIST_NOT_READY` (added to the catalog at FR-4). User must wait.
- **Calibration with all-identical ratings** (e.g., human and LLM both rated everything 3). Cohen's kappa is undefined; the response includes `kappa: null` with `warning: 'no rating variance'`.

## 12) Given/When/Then acceptance criteria

### AC-1: Generate the tutorial judgment list

- Given the tutorial query set (50 queries), `local-es` cluster with seeded products index, and a basic e-commerce template.
- When the operator POSTs `{name: 'tutorial-v1', query_set_id, cluster_id, target: 'products', current_template_id, rubric: <rubric_v1 contents>}` to `/api/v1/judgments/generate`.
- Then the response is HTTP 202 with `{judgment_list_id, status: 'generating'}`. Within 5 minutes (50 queries × ~5s each, single-worker), polling shows `status: 'complete'`, `judgment_count` ≈ 50 × 50 = 2500, `source_breakdown.llm = 2500`. Total OpenAI cost as logged: <$1.
- Example values:
  - Polling: `curl -s /api/v1/judgment-lists/{id} | jq .status` → eventually returns `"complete"`

### AC-2: Override a single rating

- Given a complete judgment list with an LLM-rated row `(query_id=q1, doc_id=d1, rating=2, source=llm)`.
- When the operator PATCHes `/api/v1/judgment-lists/{id}/judgments/{judgment_id}` with `{rating: 0, notes: "obviously irrelevant"}`.
- Then the underlying row is REPLACED (UNIQUE constraint UPSERT) with `rating=0, source=human, rater_ref='operator', notes="obviously irrelevant"`. Subsequent `GET` reflects the new rating; `source_breakdown.llm` decreases by 1, `source_breakdown.human` increases by 1.

### AC-3: Compute calibration

- Given a complete judgment list and 30 human-labeled samples uploaded.
- When the operator POSTs to `/api/v1/judgment-lists/{id}/calibration`.
- Then the response is HTTP 200 with `{cohens_kappa: 0.72, weighted_kappa: 0.78, per_class: {0: 0.85, 1: 0.65, 2: 0.70, 3: 0.80}, n_samples: 30}` (example; actual numbers depend on data). The `judgment_lists.calibration` JSONB is updated.

### AC-4: Cost guardrail

- Given `OPENAI_DAILY_BUDGET_USD=0.10` (very low for the test).
- When a judgment generation job runs that would exceed the budget after the third query.
- Then the worker stops at the third query, the list status transitions to `failed` with reason `OPENAI_BUDGET_EXCEEDED`, partial judgments (3 queries × ~50 docs = ~150 rows) are persisted with `source='llm'`.

### AC-5: Reject generation when OpenAI key missing

- Given `./secrets/openai_key` is empty (placeholder per `infra_foundation` FR-3).
- When `POST /api/v1/judgments/generate` is called.
- Then the response is HTTP 503 with `error_code: OPENAI_NOT_CONFIGURED`. No row is created.

### AC-6: Single LLM call per query (not per doc)

- Given a generation job over a 5-query × 10-doc setup.
- When the worker runs (cassette-replayed).
- Then exactly 5 calls to OpenAI's `chat.completions.create` are made; not 50.

### AC-7: Re-generation creates a new list

- Given an existing judgment list `tutorial-v1`.
- When the operator POSTs another `/judgments/generate` with the SAME `query_set_id` but a different `rubric` and `name='tutorial-v2'`.
- Then a NEW `judgment_lists` row is created with the new rubric; `tutorial-v1` is unchanged. Studies referencing `tutorial-v1` continue to use those judgments.

## 13) Non-functional requirements

- **Performance:** `POST /api/v1/judgments/generate` returns in <100ms (single INSERT + Arq enqueue). Generation throughput target: 50 queries × ~50 docs in <5 min on a single worker (≈5-6s per query).
- **Cost:** <$1 OpenAI cost for the tutorial 50-query set at `gpt-4o-2024-08-06`.
- **Reliability:** Per-query failures don't abort the job; partial results persist.
- **Operability:** Every LLM call logs `judgment_list_id`, `query_id`, `tokens_used`, `cost_usd`, `duration_ms` at INFO.

## 14) Test strategy requirements

- **Unit tests** (`backend/tests/unit/`):
  - `eval/test_calibration.py` — Cohen's kappa + weighted kappa against hand-computed baselines (sklearn-equivalent expected values).
  - `worker/test_judgment_prompt_render.py` — Jinja2 prompt rendering produces expected output for canonical (query, [docs], rubric) inputs.
- **Integration tests** (`backend/tests/integration/`):
  - `test_judgment_generate.py` — full generation against cassette-replayed local-es + recorded OpenAI cassette; asserts AC-1 (smaller scale: 5 queries × 5 docs).
  - `test_judgment_override.py` — AC-2.
  - `test_calibration_endpoint.py` — AC-3.
  - `test_budget_guardrail.py` — AC-4.
  - `test_openai_not_configured.py` — AC-5.
- **Contract tests** (`backend/tests/contract/`):
  - `test_judgments_api_contract.py` — OpenAPI shape parity.
- **E2E tests:** N/A (UI in `feat_studies_ui`).

## 15) Documentation update requirements

- `docs/01_architecture/llm-orchestration.md` already documents the patterns; update if implementation diverges.
- `docs/04_security/`: add `llm-data-flow.md` — what data goes to OpenAI, retention model, ZDR enrollment guidance.
- `docs/03_runbooks/`: add `judgment-generation-debugging.md` — replay a cassette, compute kappa from CSV, override in bulk.
- `docs/02_product/mvp1-user-stories.md`: mark US-13 / US-14 / US-15 as "implemented".

## 16) Rollout and migration readiness

- **Feature flags:** None.
- **Migration/backfill:** Adds columns to stub `judgment_lists`; creates `judgments` table.
- **Operational readiness gates:** Tutorial generation completes in <5 min for <$1.
- **Release gate:** `feat_studies_ui` review-and-override UI can call this API without modification.

## 17) Traceability matrix

| FR ID | AC IDs | Stories (TBD) | Test files | Docs |
|---|---|---|---|---|
| FR-1 (schema) | AC-2, AC-7 | TBD | `tests/integration/test_judgment_generate.py` | data-model.md |
| FR-2 (worker) | AC-1, AC-4, AC-6 | TBD | `tests/integration/test_judgment_generate.py`, `tests/integration/test_budget_guardrail.py` | runbook |
| FR-3 (generate endpoint) | AC-1, AC-5 | TBD | `tests/integration/test_judgment_generate.py`, `tests/integration/test_openai_not_configured.py` | runbook |
| FR-4 (override) | AC-2 | TBD | `tests/integration/test_judgment_override.py` | runbook |
| FR-5 (calibration) | AC-3 | TBD | `tests/integration/test_calibration_endpoint.py`, `tests/unit/eval/test_calibration.py` | runbook |
| FR-6 (list + paginated) | AC-1, AC-2 | TBD | `tests/integration/test_judgment_generate.py` | — |

## 18) Definition of feature done

- [ ] AC-1 through AC-7 pass.
- [ ] All test layers green; ≥80% coverage on `backend/worker/judgments.py`, `backend/eval/calibration.py`, `backend/api/judgments.py`.
- [ ] Tutorial generation completes in <5 min for <$1 (recorded as a benchmark assertion).
- [ ] `docs/04_security/llm-data-flow.md` merged.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

1. **Final rubric content** for `prompts/judgment_generation.rubric_v1.md` — the spec ships with the **starter rubric below** (per FR-3c) as a placeholder. Product to replace with the final ~200-word rubric tailored to the Amazon ESCI tutorial dataset before this feature ships. The starter is enough to unblock plan generation and writing the worker; the final rubric content is a copy edit. — Owner: **User** — Due: before this feature merges to main (NOT before plan generation).

### Decision log

- 2026-05-09 — Batched LLM call per query (not per doc) — cost optimization confirmed by umbrella spec §14 lines 740 + project constraint of <$1 tutorial cost.
- 2026-05-09 — Human overrides REPLACE LLM rows (UPSERT via UNIQUE) — per project preference: no DEPRECATED-style preservation.
- 2026-05-09 — Re-generating with new rubric creates a new list (immutable) — per umbrella spec §14 lines 743.
- 2026-05-09 — `top_k` per query at generation: **hard-coded 50 in MVP1**; add knob in MVP2 if needed.
- 2026-05-09 — Cassette recording for OpenAI tests: **`pytest-recording` cassettes** (more realistic than respx mocking; matches the cassette pattern already used for ES/OpenSearch tests).
- 2026-05-09 — `judgment_lists` table is owned by `feat_study_lifecycle` (full MVP1 shape including `cluster_id`, `target`, `current_template_id`, `status`, `failed_reason`, `calibration`); this feature creates only `judgments` and writes rows.
- 2026-05-09 — Added `POST /api/v1/judgment-lists/import` endpoint (FR-3b) for the tutorial's no-OpenAI first-run path per `chore_tutorial_polish`.
