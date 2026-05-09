# Feature Specification — feat_digest_proposal

**Date:** 2026-05-09
**Status:** Draft
**Owners:** TBD
**Related docs:**
- [docs/02_product/mvp1-user-stories.md](../../mvp1-user-stories.md) — covers US-16, US-17
- [docs/01_architecture/llm-orchestration.md](../../../01_architecture/llm-orchestration.md) — OpenAI digest call pattern
- [docs/01_architecture/data-model.md](../../../01_architecture/data-model.md) — `digests`, `proposals` tables
- [docs/01_architecture/optimization.md](../../../01_architecture/optimization.md) — `optuna.importance` consumed
- Depends on: [`feat_study_lifecycle`](../feat_study_lifecycle/feature_spec.md), [`feat_llm_judgments`](../feat_llm_judgments/feature_spec.md)
- Consumed by: [`feat_github_pr_worker`](../feat_github_pr_worker/feature_spec.md), [`feat_studies_ui`](../feat_studies_ui/feature_spec.md), [`feat_proposals_ui`](../feat_proposals_ui/feature_spec.md)

---

## 1) Purpose

- **Problem:** A study completes with thousands of trials; a relevance engineer needs a 60-second answer to "what won, by how much, and what should I ship?" Without a structured digest, the engineer has to read the full trial table to find insights.
- **Outcome:** When a study transitions to `completed`, the digest worker generates: a narrative summary (LLM-authored), a parameter-importance map (computed by `optuna.importance`), and a recommended config. The result is persisted as a `digests` row + a `proposals` row (status=`pending`) so the engineer can review and decide to open a PR with one click.
- **Non-goal:** No PR creation (that's `feat_github_pr_worker`). No multi-objective Pareto-front analysis (v2). No A/B-test design recommendations (MVP3+). No human-in-the-loop interrupt before digest generation (digest is a write-only artifact; no review-before-creation).

## 2) Current state audit

After dependencies ship:
- `studies`, `trials`, `judgment_lists`, `proposals` all exist with full MVP1 shapes (created by `feat_study_lifecycle`).
- The orchestrator (per `feat_study_lifecycle` FR-4) enqueues a digest job on study completion. This feature implements the consumer of that enqueue.
- `digests` table doesn't exist; this feature creates it.
- This feature does NOT extend `proposals` — full MVP1 shape (including `pr_url`/`pr_state`/`pr_merged_at`/`pr_open_error`/`rejected_reason`) is created by `feat_study_lifecycle` per [`data-model.md`](../../../01_architecture/data-model.md). This feature only INSERTs proposal rows.

## 3) Scope

### In scope

- Migration creating `digests` table per [`data-model.md`](../../../01_architecture/data-model.md): `(id, study_id UNIQUE, narrative TEXT, parameter_importance JSONB, recommended_config JSONB, suggested_followups TEXT[], generated_by TEXT, generated_at)`.
- This feature does NOT migrate `proposals` — owned by `feat_study_lifecycle` per [`data-model.md` §"MVP1 table inventory + migration ownership"](../../../01_architecture/data-model.md). This feature INSERTs proposal rows only.
- Worker job: `generate_digest(study_id)` in `backend/worker/digest.py`:
  - Loads the study + best trial + top-10 trials + baseline_metric
  - Calls `optuna.importance.get_param_importances(study)` to get a `{param: importance_score}` map
  - Composes the LLM prompt (loaded from `prompts/digest_narrative.system.md` + `prompts/digest_narrative.user.jinja`) with: study context, top-10 trials params + metrics, parameter-importance map, baseline vs achieved metric, query-set + judgment-list summaries
  - Calls OpenAI (`gpt-4o-2024-08-06`) for the narrative + recommended_config + suggested_followups via structured-output completion
  - Persists `digests` row
  - Creates a `proposals` row with `study_id`, `study_trial_id = study.best_trial_id`, `cluster_id`, `template_id`, `config_diff = {param: {from, to}}`, `metric_delta = {primary: {baseline, achieved, delta_pct}}`, `status='pending'`
- API endpoints:
  - `GET /api/v1/studies/{id}/digest` — returns the digest for a completed study (404 `DIGEST_NOT_READY` if study isn't completed yet or digest hasn't been written)
  - `POST /api/v1/proposals` — manual proposal creation from a chat-agent flow that didn't go through a study (cluster_id, template_id, config_diff). Reserved interface; the agent uses it to support hand-crafted tweaks.
  - `GET /api/v1/proposals` (paginated, status filter) + `GET /api/v1/proposals/{id}`
  - `POST /api/v1/proposals/{id}/reject` — sets `status='rejected'` with optional `reason`

### Out of scope

- PR creation — `feat_github_pr_worker`.
- UI for digest display + proposal review — `feat_studies_ui` + `feat_proposals_ui`.
- Multi-objective digest (Pareto-front analysis) — v2.
- LLM-authored A/B-test design recommendations — MVP3+.
- Human-in-the-loop interrupts before digest creation — GA v1 (with LangGraph).

### API convention check

Per [`api-conventions.md`](../../../01_architecture/api-conventions.md). All endpoints under `/api/v1/`. Cursor pagination on list endpoints.

### Phase boundaries

Single-phase. The MVP1 deliverable: "study completes → digest generated within 30s → narrative is informative, recommended_config is correct, parameter_importance chart data is computable from `digest.parameter_importance` JSON."

## 4) Product principles and constraints

- **Digest is write-only.** A study has zero or one digest (UNIQUE on `study_id`). Re-running a digest requires recreating the study (or admin escape hatch via direct DB delete + re-enqueue — runbook documents).
- **Proposal is the apply-path artifact.** Even if the engineer never opens a PR, the proposal row is the durable record of "this is what we recommended." Status defaults to `pending`.
- **Digest reads only completed studies.** The `generate_digest` job rejects studies in `running` / `cancelled` / `failed` states (the orchestrator only enqueues digest on `completed`, but defense-in-depth).
- **`parameter_importance` is data, not narrative.** The frontend renders it as a bar chart (Recharts per `feat_studies_ui`); the narrative may reference it but doesn't replace it.
- **Cost discipline.** A digest is one LLM call (`gpt-4o-2024-08-06`); typical cost <$0.05 per study. The daily OpenAI budget gate per [`llm-orchestration.md`](../../../01_architecture/llm-orchestration.md) applies.

### Anti-patterns

- **Do not** generate a digest for a study with `best_metric IS NULL` (zero successful trials). Persist a `digests` row with `narrative = "No successful trials. Diagnose with the worker logs."` and skip the LLM call. Save the cost.
- **Do not** include the full trials table in the LLM prompt. Top-10 trials only (the model doesn't need 1000 rows).
- **Do not** include OpenAI's response verbatim without validating against the structured-output schema. Use `client.chat.completions.create(response_format=...)` or `with_structured_output` (when MVP4 brings LangChain).
- **Do not** create multiple proposals per study automatically. One proposal per digest. Manual proposals via `POST /api/v1/proposals` are a separate flow.

## 5) Assumptions and dependencies

- **Dependency: `feat_study_lifecycle`** — enqueues the digest job on study completion. The hand-off interface is `await arq.enqueue_job('generate_digest', study_id)` in the orchestrator's `complete_study` service function.
- **Dependency: `feat_llm_judgments`** — `judgment_lists` table content (the digest prompt references the judgment-list name + rubric).
- **Dependency: `infra_optuna_eval`** — `optuna.importance.get_param_importances` requires the Optuna study row to exist; the digest worker reads it via `optuna.load_study(study_name=str(study_id), storage=...)`.
- **OpenAI API key** required at digest time (returns `OPENAI_NOT_CONFIGURED` per the same pattern as `feat_llm_judgments`).

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (reads digest via UI, decides to open PR).

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP2. When MVP2 ships, this feature's `digest.generated` and `proposal.created` will emit audit events; `proposal.rejected` will emit when the user rejects.

## 7) Functional requirements

### FR-1: Schema
- The system **MUST** create `digests` and `proposals` tables per [`data-model.md`](../../../01_architecture/data-model.md). MVP1 shapes (no `tenant_id`, no `created_by`).

### FR-2: Digest worker
- The system **MUST** define `generate_digest(ctx, study_id)` as an Arq job in `backend/worker/digest.py`.
- The job **MUST** verify `studies.status = 'completed'` (raise `INVALID_STUDY_STATE` otherwise; the orchestrator should never trigger this, but defense-in-depth).
- The job **MUST** load the top-10 trials by `primary_metric DESC`, the best trial, the baseline (defined as the metric of trial #0 — the first trial, which uses Optuna's seed defaults; alternative: explicit `studies.baseline_metric` populated by the orchestrator before the first trial).
- The job **MUST** call `optuna.importance.get_param_importances(study)` and store the result in `digests.parameter_importance`.
- The job **MUST** read the capability cache (per `infra_foundation` FR-7). If `structured_output == "ok"` for the configured `OPENAI_BASE_URL`, call with `response_format={type: "json_schema", ...}` for narrative + recommended_config + suggested_followups. If `structured_output != "ok"`, fall back to a simpler narrative-only prompt (no recommended_config or suggested_followups) and log at WARN that the digest is degraded. The digest row's `parameter_importance` is computed from Optuna independently and is unaffected by this fallback.
- The job **MUST** persist a `digests` row.
- The job **MUST** create a corresponding `proposals` row with status=`pending` referencing the study, best trial, cluster, template, and the metric_delta + config_diff.
- If the study has zero successful trials (`best_metric IS NULL`): persist a `digests` row with `narrative = "No successful trials in this study. Diagnose using the worker logs."`, `parameter_importance = {}`, `recommended_config = {}`, `suggested_followups = []`, and DO NOT create a proposal row. Notes: covers US-16's failure mode.
- Notes: covers US-16, US-17.

### FR-3: Digest fetch endpoint
- `GET /api/v1/studies/{id}/digest` returns the digest body if it exists.
- Returns 404 `DIGEST_NOT_READY` if the study is not `completed` OR if the digest row hasn't been written yet (the orchestrator's enqueue may have lag).

### FR-4: Proposal CRUD
- `POST /api/v1/proposals` accepts `{cluster_id, template_id, config_diff, metric_delta?}` for manual proposals (`study_id` NULL, `study_trial_id` NULL).
- `GET /api/v1/proposals?status=&cluster_id=&cursor=&limit=` paginated, filterable. Each item is a `ProposalSummary`:
  ```json
  {
    "id": "uuid",
    "study_id": "uuid|null",
    "cluster": {"id": "uuid", "name": "products-prod-es", "engine_type": "elasticsearch"},
    "template": {"id": "uuid", "name": "product_search", "version": 3},
    "status": "pending|pr_opened|pr_merged|rejected",
    "pr_state": "open|closed|merged|null",
    "pr_url": "string|null",
    "metric_delta": {"primary": {"baseline": 0.612, "achieved": 0.762, "delta_pct": 24.5}} | null,
    "created_at": "iso8601"
  }
  ```
- `GET /api/v1/proposals/{id}` returns the full `ProposalDetail` shape:
  ```json
  {
    "id": "uuid",
    "study_id": "uuid|null",
    "study_summary": null | {
      "id": "uuid",
      "name": "string",
      "status": "completed",
      "best_metric": 0.762,
      "best_trial_id": "uuid",
      "query_set": {"id": "uuid", "name": "qs_modelnums", "query_count": 50},
      "judgment_list": {"id": "uuid", "name": "tutorial-v1", "status": "complete"}
    },
    "study_trial_id": "uuid|null",
    "cluster": {"id": "uuid", "name": "string", "engine_type": "elasticsearch", "environment": "prod"},
    "template": {"id": "uuid", "name": "string", "version": 3, "engine_type": "elasticsearch"},
    "config_diff": {"field_boosts.title": {"from": 2.5, "to": 4.7}, "tie_breaker": {"from": 0.1, "to": 0.34}},
    "metric_delta": {"ndcg@10": {"baseline": 0.612, "achieved": 0.762, "delta_pct": 24.5}} | null,
    "status": "pending|pr_opened|pr_merged|rejected",
    "pr_url": "string|null",
    "pr_state": "open|closed|merged|null",
    "pr_merged_at": "iso8601|null",
    "pr_open_error": "string|null",
    "rejected_reason": "string|null",
    "digest": null | {
      "id": "uuid",
      "narrative": "markdown string",
      "parameter_importance": {"field_boosts.title": 0.42, "tie_breaker": 0.21, ...},
      "recommended_config": {...},
      "suggested_followups": ["string", ...],
      "generated_at": "iso8601"
    },
    "created_at": "iso8601"
  }
  ```
  `study_summary` is non-null when `study_id` is non-null. `digest` is non-null when an associated `digests` row exists for the study (one-to-one). Inlining the `digest` object on the proposal-detail response avoids a fan-out query from the UI.
- `POST /api/v1/proposals/{id}/reject` accepts `{reason?}`; transitions `pending → rejected`. Returns 409 if already in a terminal state.

### FR-5: Digest prompt
- The system **MUST** load `prompts/digest_narrative.system.md` and `prompts/digest_narrative.user.jinja` at startup.
- The user prompt **MUST** include: study name, cluster name, target, query set name + query count, judgment list name + rubric summary, baseline metric value, achieved metric value, top-10 trials (params + primary metric), parameter importance map.
- The structured-output schema (`response_format` Pydantic model) **MUST** declare: `narrative: str`, `recommended_config: dict[str, Any]`, `suggested_followups: list[str]` (max 5).

## 8) API and data contract baseline

### 7.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `GET` | `/api/v1/studies/{id}/digest` | Fetch digest | `STUDY_NOT_FOUND`, `DIGEST_NOT_READY` |
| `POST` | `/api/v1/proposals` | Manually create a proposal | `VALIDATION_ERROR`, `CLUSTER_NOT_FOUND`, `TEMPLATE_NOT_FOUND` |
| `GET` | `/api/v1/proposals` | List proposals | (none) |
| `GET` | `/api/v1/proposals/{id}` | Detail | `PROPOSAL_NOT_FOUND` |
| `POST` | `/api/v1/proposals/{id}/reject` | Reject a pending proposal | `PROPOSAL_NOT_FOUND`, `INVALID_STATE_TRANSITION` |

### 7.4 Enumerated value contracts

| Field | Accepted values | Backend source of truth |
|---|---|---|
| `proposals.status` | `pending`, `pr_opened`, `pr_merged`, `rejected` | `backend/db/models/proposal.py` |
| `?status` (proposals filter) | same | `backend/api/proposals.py` |

### 7.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| `DIGEST_NOT_READY` | 404 | Digest not generated yet (study not completed or worker lag) |
| `PROPOSAL_NOT_FOUND` | 404 | Proposal ID not found |
| `INVALID_STATE_TRANSITION` | 409 | Reject attempted on non-pending proposal |
| `INVALID_STUDY_STATE` | 409 | Internal — digest worker received non-completed study |

## 9) Data model and state transitions

`digests`: append-only (no UPDATE / DELETE outside cascade).
`proposals.status`: `pending → pr_opened → pr_merged | rejected`. The `pr_opened` transition is owned by `feat_github_pr_worker`. This feature owns `pending → rejected`.

## 10) Security, privacy, and compliance

- **Threats:**
  1. The digest narrative could include sensitive doc content from the trials' top-K hits. **Mitigation:** the prompt does NOT include doc content — only doc IDs and scores. Doc content stays at the cluster.
  2. Cost runaway — many studies completing simultaneously fire many digest LLM calls. **Mitigation:** daily budget gate per [`llm-orchestration.md`](../../../01_architecture/llm-orchestration.md); digest jobs check budget before calling.
- **Auditability:** N/A — `audit_log` is MVP2.

## 11) UX flows and edge cases

This feature has no UI surface; UI is owned by `feat_studies_ui` (digest panel on study detail page) and `feat_proposals_ui` (proposals list + detail).

### Edge/error flows

- **Study completed with zero successful trials.** Per FR-2, digest row is created with the failure narrative; no proposal row.
- **OpenAI fails during digest generation.** Worker retries 3× with backoff; on final failure, no digest row is created. The orchestrator's enqueue of `generate_digest` includes Arq's default retry policy; after exhaustion the failure is logged at WARN. The user must retry manually (via runbook escape hatch).
- **Best trial's params include a parameter that no longer exists in the template.** The narrative may mention it; the recommended_config will include only currently-declared params. Mismatch is flagged in `digests.suggested_followups` (e.g., `"baseline trial used 'tie_breaker' which is no longer in the template"`).

## 12) Given/When/Then acceptance criteria

### AC-1: Digest generated on study completion

- Given a completed study with `best_metric=0.762` (vs. `baseline_metric=0.612`).
- When the orchestrator enqueues `generate_digest(study_id)` via `complete_study`.
- Then within 30s a `digests` row exists with non-null `narrative` (>200 chars), `parameter_importance` containing entries for every continuous param in the study's search space, `recommended_config` matching the best trial's params, and `suggested_followups` (1–5 items). A corresponding `proposals` row exists with `status='pending'`, `study_id=<study>`, `study_trial_id=<best_trial>`, `metric_delta = {ndcg: {baseline: 0.612, achieved: 0.762, delta_pct: 24.5}}`, `config_diff = {param: {from, to}}`.

### AC-2: Failed-study digest creates artifact, no proposal

- Given a study where `best_metric IS NULL` (zero successful trials).
- When `generate_digest` runs.
- Then a `digests` row exists with `narrative = "No successful trials in this study. Diagnose using the worker logs."`, `parameter_importance = {}`. NO `proposals` row is created.

### AC-3: Digest fetch via API

- Given a study with a digest.
- When the operator hits `GET /api/v1/studies/{id}/digest`.
- Then the response is HTTP 200 with the digest body.

### AC-4: Digest fetch on running study

- Given a study with `status='running'`.
- When the operator hits `GET /api/v1/studies/{id}/digest`.
- Then the response is HTTP 404 with `error_code: DIGEST_NOT_READY`.

### AC-5: Reject a proposal

- Given a proposal with `status='pending'`.
- When the operator POSTs `/api/v1/proposals/{id}/reject` with `{reason: "metric delta too small to justify churn"}`.
- Then the response is HTTP 200; the proposal row is updated to `status='rejected', rejected_reason='metric delta too small to justify churn'`.
- A second POST to `/reject` returns HTTP 409 `INVALID_STATE_TRANSITION`.

### AC-6: Manual proposal creation

- Given a cluster + template + a hand-crafted `config_diff`.
- When the operator POSTs to `/api/v1/proposals` with `{cluster_id, template_id, config_diff: {field_boosts.title: {from: 2.0, to: 4.0}}}`.
- Then the response is HTTP 201 with the created proposal (`status='pending'`, `study_id=NULL`).

### AC-7: parameter_importance shape

- Given a study with continuous params `field_boosts.title`, `field_boosts.body`, `tie_breaker`, `fuzziness` and 100 trials.
- When the digest is generated.
- Then `digests.parameter_importance` is a JSON object with all 4 param keys, values floats summing to ~1.0 (within float-rounding tolerance of `optuna.importance` semantics).

### AC-8: Cost stays under budget

- Given a digest generation against a typical study (top-10 trials × 4 params).
- When the LLM call completes.
- Then total tokens used <8000 (input ~5000, output ~3000); cost <$0.05 per digest at `gpt-4o-2024-08-06` rates (logged at INFO).

## 13) Non-functional requirements

- **Performance:** Digest generation completes in <30s p99 (Optuna importance compute <1s, OpenAI call ~10–20s, DB writes <500ms).
- **Cost:** <$0.05 per digest.
- **Reliability:** Digest job retries 3× on OpenAI rate-limit; a final failure is logged but does NOT auto-retry indefinitely.
- **Operability:** Every digest invocation logs `study_id`, `tokens_used`, `cost_usd`, `duration_ms`, `proposal_id` (if created) at INFO.

## 14) Test strategy requirements

- **Unit tests** (`backend/tests/unit/`):
  - `worker/test_digest_prompt.py` — prompt rendering with canonical inputs.
  - `worker/test_digest_failure_path.py` — zero-successful-trials case produces the failure narrative.
- **Integration tests** (`backend/tests/integration/`):
  - `test_digest_generate.py` — end-to-end against a seeded completed study + OpenAI cassette; asserts AC-1.
  - `test_digest_zero_trials.py` — AC-2.
  - `test_digest_not_ready.py` — AC-4.
  - `test_proposal_reject.py` — AC-5.
  - `test_proposal_manual.py` — AC-6.
- **Contract tests** (`backend/tests/contract/`):
  - `test_digest_proposal_api_contract.py` — OpenAPI parity.
- **Benchmarks**:
  - `test_digest_token_budget.py` — assert AC-8 (cost <$0.05).

## 15) Documentation update requirements

- `docs/01_architecture/data-model.md` already documents the schemas; update if implementation diverges.
- `docs/03_runbooks/`: add `digest-debugging.md` — re-enqueue a digest, inspect parameter_importance, manually flag a proposal as rejected.
- `docs/02_product/mvp1-user-stories.md`: mark US-16 / US-17 as "implemented".

## 16) Rollout and migration readiness

- **Feature flags:** None.
- **Migration/backfill:** Adds `digests` and `proposals` tables.
- **Operational readiness gates:** Tutorial study produces an informative digest in under 30s.
- **Release gate:** `feat_github_pr_worker` author confirms the proposal interface (status, pr_url, pr_state columns) supports their flow.

## 17) Traceability matrix

| FR ID | AC IDs | Stories (TBD) | Test files | Docs |
|---|---|---|---|---|
| FR-1 (schema) | AC-1, AC-2, AC-6 | TBD | `tests/integration/test_digest_generate.py` | data-model.md |
| FR-2 (worker) | AC-1, AC-2, AC-7, AC-8 | TBD | `tests/integration/test_digest_generate.py`, `tests/integration/test_digest_zero_trials.py` | runbook |
| FR-3 (digest fetch) | AC-3, AC-4 | TBD | `tests/integration/test_digest_not_ready.py` | — |
| FR-4 (proposal CRUD) | AC-5, AC-6 | TBD | `tests/integration/test_proposal_reject.py`, `tests/integration/test_proposal_manual.py` | — |
| FR-5 (digest prompt) | AC-1 | TBD | `tests/unit/worker/test_digest_prompt.py` | runbook |

## 18) Definition of feature done

- [ ] AC-1 through AC-8 pass.
- [ ] All test layers green; ≥80% coverage on `backend/worker/digest.py`, `backend/api/proposals.py`.
- [ ] Tutorial study produces a useful digest under 30s for under $0.05.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None — all resolved (see Decision log).

### Decision log

- 2026-05-09 — One digest per study (UNIQUE) — per umbrella spec §9.
- 2026-05-09 — Top-10 trials in prompt (not full table) — token-budget discipline.
- 2026-05-09 — Failed studies get a digest row with placeholder narrative + no proposal — fail-loud-but-cheap principle.
- 2026-05-09 — `baseline_metric` source: **option (c)** — `feat_study_lifecycle`'s orchestrator runs a single non-Optuna trial with template defaults BEFORE Optuna starts; result lands in `studies.baseline_metric` (column added per [`data-model.md`](../../../01_architecture/data-model.md)).
- 2026-05-09 — `proposals` schema is owned by `feat_study_lifecycle` (full MVP1 shape, all columns including `pr_url`/`pr_state`/`pr_open_error`). This feature INSERTs rows only.
- 2026-05-09 — Digest re-generation: **manual escape hatch via runbook for MVP1** (`DELETE FROM digests WHERE study_id = ...` + re-enqueue); add a `POST /studies/{id}/digest/regenerate` endpoint at MVP2 if real demand emerges.
- 2026-05-09 — `GET /api/v1/proposals/{id}` response shape locked in FR-4: includes inline `study_summary` (when applicable) and inline `digest` (when applicable) so the UI doesn't need fan-out queries. Consumed by `feat_proposals_ui`.
