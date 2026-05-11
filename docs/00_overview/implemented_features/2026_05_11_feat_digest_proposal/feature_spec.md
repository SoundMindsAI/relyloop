# Feature Specification — feat_digest_proposal

**Date:** 2026-05-11 (rewritten after Phase 2 of `feat_study_lifecycle` + `feat_llm_judgments` shipped; original 2026-05-09 draft preserved in git history)
**Status:** Approved (review-and-patched 2026-05-11; ready for `/pipeline` → `impl-plan-gen`)
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

State as of 2026-05-11 (after `feat_study_lifecycle` Phase 2 PR #25 + `feat_llm_judgments` PR #35 + the PR #39 spec-drift sweep merged):

- `studies`, `trials`, `judgment_lists`, `judgments`, `proposals` all exist with full MVP1 shapes (created by `feat_study_lifecycle` + `feat_llm_judgments`). Alembic head is `0004_judgments`.
- **The orchestrator already inserts a `proposals` row with `status='pending'` INSIDE the same transaction as `complete_study`** (`backend/workers/orchestrator.py:346-356`, the C3-F1 atomicity fix from Phase 2's GPT-5.5 review). This row carries the durable handoff; the Arq enqueue of `generate_digest` is a fast-path accelerator only. **Consequence: when the digest worker runs, a pending proposal row ALREADY EXISTS for the study.** This feature POPULATES that row (`config_diff`, `metric_delta`) rather than INSERTing a new one.
- A stub at `backend/workers/digest_stub.py` is currently registered as `generate_digest` in `backend/workers/all.py:164`. The stub idempotently confirms the pending proposal exists (defensive INSERT if missing). This feature REPLACES the stub with the full implementation under the same Arq job name (`generate_digest`) so the orchestrator's enqueue at `orchestrator.py:370` continues to fire correctly.
- `digests` table doesn't exist; this feature creates it via migration `0005_digests`.
- This feature does NOT migrate `proposals` — full MVP1 shape (including `pr_url` / `pr_state` / `pr_merged_at` / `pr_open_error` / `rejected_reason`) is owned by `feat_study_lifecycle` per [`data-model.md`](../../../01_architecture/data-model.md). This feature only UPDATEs existing pending rows + INSERTs new rows for the manual-proposal endpoint.
- LLM hot-path infrastructure shipped by `feat_llm_judgments` is REUSABLE here: `backend/app/llm/capability_check.py:read_capability_result`, `backend/app/llm/budget_gate.py:{peek_daily_total,record_cost}`, `backend/app/llm/cost_model.py:{known_models,estimated_max_call_cost}`, `backend/app/llm/prompt_loader.py:SandboxedEnvironment` pattern (autoescape=True). The digest worker mirrors the judgments worker's pre-call peek → call → post-call record cost ordering.
- The Optuna RDB study is loaded via `backend/app/eval/optuna_runtime.py:get_or_create_study()` (the same helper `backend/workers/trials.py` uses) — not by calling `optuna.load_study(...)` directly.

## 3) Scope

### In scope

- Migration `0005_digests` creating the `digests` table per [`data-model.md`](../../../01_architecture/data-model.md): `(id, study_id UNIQUE, narrative TEXT, parameter_importance JSONB, recommended_config JSONB, suggested_followups TEXT[], generated_by TEXT, generated_at)`. Round-trip downgrade required (CLAUDE.md Absolute Rule #5).
- This feature does NOT migrate `proposals` — owned by `feat_study_lifecycle` per [`data-model.md` §"MVP1 table inventory + migration ownership"](../../../01_architecture/data-model.md). This feature POPULATEs existing pending proposal rows + INSERTs new rows for the manual-proposal endpoint.
- Worker job: `generate_digest(ctx, study_id)` at `backend/workers/digest.py`, replacing the current stub at `backend/workers/digest_stub.py` (registered under the same Arq job name `generate_digest` so `backend/workers/orchestrator.py:370` and `backend/workers/all.py:164` keep working). The worker:
  - Loads the study + best trial + top-10 trials + `baseline_metric`
  - Locates the pre-existing `proposals` row for `study_id` (`status='pending'`, created by the orchestrator's `_stop` in `backend/workers/orchestrator.py:346-356`). If missing — defensive INSERT mirroring `digest_stub.py:67-87`.
  - Loads the Optuna study via `backend/app/eval/optuna_runtime.py:get_or_create_study()` and calls `optuna.importance.get_param_importances(study)` for the `{param: importance_score}` map.
  - Composes the LLM prompt from `prompts/digest_narrative.system.md` + `prompts/digest_narrative.user.jinja` (loaded via a `DigestPromptBundle` modeled on `backend/app/llm/prompt_loader.py:JudgmentPromptBundle` — `SandboxedEnvironment(autoescape=True)`).
  - Reads `Settings.openai_model` for the model pin (no hardcoding per CLAUDE.md Rule #8); reads `Settings.openai_base_url`. Uses `backend/app/llm/capability_check.py:read_capability_result()` to gate on `structured_output == "ok"` AND `cap.model == settings.openai_model` (cycle-8 C8-F2 pattern from `feat_llm_judgments`).
  - Pre-call: `backend/app/llm/budget_gate.py:peek_daily_total()`; post-call: `record_cost()` via the `_safe_record_cost` helper pattern (catch Redis flaps so a paid call isn't dropped).
  - INSERTs the `digests` row.
  - UPDATEs the pre-existing pending `proposals` row with the computed `config_diff` and `metric_delta`. The status remains `pending` (the `pending → pr_opened` transition is owned by `feat_github_pr_worker`).
- **Boot-time scan: `WorkerSettings.on_startup` extension.** Scan `proposals WHERE status='pending' AND config_diff = {}` (or a similar "not-yet-populated" sentinel) and enqueue `generate_digest` for each `study_id`. Covers studies completed while the worker was down. Mirrors the existing `list_running_study_ids` / `list_queued_study_ids` / `list_generating_judgment_list_ids` sweep pattern in `backend/workers/all.py:on_startup`.
- API endpoints (router at `backend/app/api/v1/proposals.py`, registered in `backend/app/main.py` alongside the existing v1 routers):
  - `GET /api/v1/studies/{id}/digest` — returns the digest for a completed study (404 `DIGEST_NOT_READY` if the digest hasn't been written yet).
  - `POST /api/v1/proposals` — manual proposal creation from a chat-agent flow that didn't go through a study (`cluster_id`, `template_id`, `config_diff`). Reserved interface; the agent uses it for hand-crafted tweaks.
  - `GET /api/v1/proposals` (paginated, status filter) + `GET /api/v1/proposals/{id}`.
  - `POST /api/v1/proposals/{id}/reject` — sets `status='rejected'` with optional `reason`.

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

- **Dependency: `feat_study_lifecycle` Phase 2 (PR #25, merged 2026-05-11)** — the orchestrator's `_stop` at `backend/workers/orchestrator.py:346-356` INSERTs a pending `proposals` row in the same transaction as `complete_study` (the C3-F1 durable-handoff design). It then best-effort enqueues `generate_digest(study_id)` at `orchestrator.py:370`. This feature consumes the pending row by populating `config_diff` + `metric_delta`.
- **Dependency: `feat_llm_judgments` (PR #35, merged 2026-05-11)** — `judgment_lists` table content (the digest prompt references the judgment-list name + rubric) AND the LLM hot-path infrastructure: `capability_check.read_capability_result`, `budget_gate.{peek_daily_total, record_cost}`, `cost_model.{known_models, estimated_max_call_cost}`, `prompt_loader` patterns. The digest worker mirrors the judgments worker's preflight order (api_key → capability → pricing → budget peek → call → record).
- **Dependency: `infra_optuna_eval`** — `optuna.importance.get_param_importances` requires the Optuna study row to exist. Load via `backend/app/eval/optuna_runtime.py:get_or_create_study()` (the same helper `backend/workers/trials.py` already uses) — not via raw `optuna.load_study(...)`.
- **OpenAI API key** required at digest time (returns `OPENAI_NOT_CONFIGURED` per the same pattern as `feat_llm_judgments`).

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (reads digest via UI, decides to open PR).

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP2. When MVP2 ships, this feature's `digest.generated` and `proposal.created` will emit audit events; `proposal.rejected` will emit when the user rejects.

## 7) Functional requirements

### FR-1: Schema
- The system **MUST** create the `digests` table via migration `0005_digests` per [`data-model.md`](../../../01_architecture/data-model.md) (MVP1 shape: no `tenant_id`, no `created_by`). Round-trip downgrade (CLAUDE.md Absolute Rule #5).
- The system **MUST NOT** migrate `proposals` — that table's full MVP1 shape is owned by `feat_study_lifecycle` per [`data-model.md` §"MVP1 table inventory + migration ownership"](../../../01_architecture/data-model.md). This feature populates / inserts proposal rows (via FR-2 worker + FR-4 manual endpoint).

### FR-2: Digest worker
- The system **MUST** ship `generate_digest(ctx, study_id)` as an Arq job at `backend/workers/digest.py`. This **REPLACES** the current stub at `backend/workers/digest_stub.py`. The Arq registration name (`generate_digest`) is preserved so the orchestrator's `enqueue_job` at `backend/workers/orchestrator.py:370` and the `WorkerSettings.functions` entry at `backend/workers/all.py:164` keep firing without orchestrator-side changes. The plan **MUST** delete the stub file and update the import in `backend/workers/all.py`.
- The job **MUST** preflight in this order (mirrors the `feat_llm_judgments` worker's preflight contract, including the cycle-2 / cycle-8 fixes from PR #35):
  1. **Load + bail.** Fetch the study row; if missing or `status != 'completed'`, log + return. (Defense-in-depth — the orchestrator only enqueues on `completed`, but the worker is idempotent.)
  2. **OpenAI key check.** If `Settings.openai_api_key` is empty, flip the pending proposal's owning digest path to a deferred state and return. (Specifically: do NOT INSERT a `digests` row, do NOT modify the pending proposal, log WARN with `OPENAI_NOT_CONFIGURED`. Operator retries via runbook after populating the key.)
  3. **Capability check.** Read the cache via `backend/app/llm/capability_check.py:read_capability_result()`. If cap is None, `cap.structured_output != 'ok'`, or `cap.model != Settings.openai_model`: log WARN, fall back to the narrative-only path (no `recommended_config`, no `suggested_followups`). `parameter_importance` is computed from Optuna independently and is unaffected.
  4. **Model-pricing check.** If `Settings.openai_model not in backend/app/llm/cost_model.py:known_models()`: log WARN with `UNKNOWN_MODEL_PRICING`, return without writing. Operator pins a known model or extends the pricing dict.
  5. **Daily-budget peek.** `backend/app/llm/budget_gate.py:peek_daily_total()`; if `current + estimated_max_call_cost(model) > Settings.openai_daily_budget_usd` and the budget is enabled, log WARN with `OPENAI_BUDGET_EXCEEDED`, return without writing. Operator retries after rollover.
- After preflight, the job **MUST**:
  - Locate the pending proposal: `SELECT * FROM proposals WHERE study_id = :sid AND status='pending'` (created by the orchestrator's `_stop`). If missing, defensive INSERT mirroring `digest_stub.py:67-87`.
  - Load the top-10 trials by `primary_metric DESC` and the best trial via `backend/app/db/repo/trial.py`. The baseline metric is `studies.baseline_metric` (populated by the orchestrator before the first Optuna trial per the `feat_study_lifecycle` Decision Log of 2026-05-09 option (c) — confirmed at `backend/app/db/models/study.py:76`).
  - Load the Optuna study via `backend/app/eval/optuna_runtime.py:get_or_create_study()`. Call `optuna.importance.get_param_importances(study)` for the `{param: importance_score}` map.
  - Render the user prompt via the `DigestPromptBundle` loader (modeled on `backend/app/llm/prompt_loader.py:load_judgment_prompts`). Inputs: study name, cluster name, target, query-set name + count, judgment-list name + rubric summary, baseline + achieved metrics, top-10 trial params + metrics, parameter-importance map.
  - Call `openai.AsyncOpenAI(api_key=Settings.openai_api_key, base_url=Settings.openai_base_url).chat.completions.create(model=Settings.openai_model, ...)` with the structured-output schema from FR-5. `max_completion_tokens=2000` (matches `cost_model._OUTPUT_TOKEN_CEILING`; honest budget gate per the `feat_llm_judgments` cycle-5 C5-F1 pattern).
  - Post-call: `_safe_record_cost(redis, result.cost_usd)` mirroring `backend/workers/judgments.py:_safe_record_cost` (catches Redis flaps so a paid call isn't dropped).
  - INSERT the `digests` row.
  - UPDATE the pre-existing pending `proposals` row with the populated `config_diff` + `metric_delta`. Status remains `pending` (the `pending → pr_opened` transition is owned by `feat_github_pr_worker`). The repo helper `update_proposal_for_digest` is added by FR-6.
- **Zero-successful-trials case.** If `study.best_metric IS NULL`: persist a `digests` row with `narrative = "No successful trials in this study. Diagnose using the worker logs."`, `parameter_importance = {}`, `recommended_config = {}`, `suggested_followups = []`, and **delete the pending proposal row** (it's pointing at a non-existent best trial). Notes: covers US-16's failure mode. The runbook documents the manual re-run path.
- Notes: covers US-16, US-17.

### FR-2b: Boot-time scan (post-Phase-2 dependency)
- `backend/workers/all.py:on_startup` **MUST** be extended to scan for pending proposals that have NOT yet been digested and re-enqueue `generate_digest` for each. Detection: `SELECT study_id FROM proposals WHERE status='pending' AND id NOT IN (SELECT proposal_id FROM digests WHERE proposal_id IS NOT NULL)` — or equivalently, scan via a "not-yet-populated" sentinel like `config_diff = '{}'::jsonb` (deferred to the plan-gen step). Without this scan, studies completed while the worker was down would never get their digest narratives.
- The enqueue **MUST** use a deterministic `_job_id=f"generate_digest:{study_id}"` to dedup against an already-in-flight job from the API enqueue path (mirrors the `feat_llm_judgments` cycle-4 C4-F1 fix).

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
- The system **MUST** load `prompts/digest_narrative.system.md` and `prompts/digest_narrative.user.jinja` at first use via a `DigestPromptBundle` modeled on `backend/app/llm/prompt_loader.py:load_judgment_prompts()` (lru_cache, `SandboxedEnvironment(autoescape=True)` per the `feat_llm_judgments` cycle-5 C5-F2 contract).
- The user prompt **MUST** include: study name, cluster name, target, query-set name + query count, judgment-list name + rubric summary, baseline metric value, achieved metric value, top-10 trials (params + primary metric), parameter-importance map, **the deterministically-computed `recommended_config` (worker-filtered best-trial params)**, and **`dropped_template_params`** (best-trial param keys no longer declared on the current template — empty list when there is no drift). Doc IDs and doc bodies are **NEVER** included (the digest is study-summary data, not retrieval content — see §10).
- **`recommended_config` is NOT generated by the LLM.** The worker computes it deterministically as `{p: v for p, v in best_trial.params.items() if p in template.declared_params}` and passes it to the prompt as INPUT. The LLM's role is to describe the recommendation in `narrative` and to suggest follow-ups. This guarantees AC-1 cannot be violated by a hallucinated config and gives the template-drift case a deterministic outcome (per implementation-plan cycle-1 F5/F9 / cycle-2 F1/F2).
- The structured-output JSON schema (`response_format={"type":"json_schema","json_schema":{...,"strict":true}}`) **MUST** declare: `narrative: str`, `suggested_followups: list[str]` with **`maxItems: 5`** wired into the schema (not just a prose comment — matches the `feat_llm_judgments` `RATING_RESPONSE_SCHEMA` strict-output pattern). `recommended_config` is **NOT** in the schema — see preceding bullet.

### FR-6: Repository functions
- The system **MUST** extend `backend/app/db/repo/proposal.py` with:
  - `update_proposal_for_digest(db, proposal_id, *, config_diff, metric_delta)` — UPDATE the existing pending row's `config_diff` + `metric_delta`. Caller commits.
  - `list_proposals_paginated(db, *, cursor, limit, status?, cluster_id?)` — cursor-paginated list for FR-4's `GET /api/v1/proposals`.
  - `count_proposals(db, *, status?, cluster_id?)` — `X-Total-Count` header for the list endpoint.
  - `reject_proposal(db, proposal_id, *, reason)` — transition `pending → rejected`, set `rejected_reason`. Caller commits. Raises a service-layer `InvalidStateTransition` if the row is not `pending`.
  - `list_pending_proposals_for_boot_scan(db) -> list[str]` — FR-2b boot-time scan query (study IDs to enqueue).
- The system **MUST** add a new repo `backend/app/db/repo/digest.py` with:
  - `create_digest(db, **fields)` — caller commits.
  - `get_digest_for_study(db, study_id) -> Digest | None` — FR-3 fetch endpoint.

## 8) API and data contract baseline

### 8.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `GET` | `/api/v1/studies/{id}/digest` | Fetch digest | `STUDY_NOT_FOUND`, `DIGEST_NOT_READY` |
| `POST` | `/api/v1/proposals` | Manually create a proposal | `VALIDATION_ERROR`, `CLUSTER_NOT_FOUND`, `TEMPLATE_NOT_FOUND` |
| `GET` | `/api/v1/proposals` | List proposals (cursor + `X-Total-Count`) | `VALIDATION_ERROR` (bad `?status`) |
| `GET` | `/api/v1/proposals/{id}` | Detail | `PROPOSAL_NOT_FOUND` |
| `POST` | `/api/v1/proposals/{id}/reject` | Reject a pending proposal | `PROPOSAL_NOT_FOUND`, `INVALID_STATE_TRANSITION` |

### 8.4 Enumerated value contracts

Per CLAUDE.md "Enumerated Value Contract Discipline" — every wire value must cite its backend source of truth so frontend option lists don't drift.

| Field | Accepted values | Backend source of truth |
|---|---|---|
| `proposals.status` | `pending`, `pr_opened`, `pr_merged`, `rejected` | `backend/app/db/models/proposal.py` CHECK `proposals_status_check` (already shipped by `feat_study_lifecycle` Phase 1) |
| `proposals.pr_state` | `open`, `closed`, `merged`, `null` | `backend/app/db/models/proposal.py` CHECK `proposals_pr_state_check` (already shipped) |
| `?status` (proposals filter) | `pending`, `pr_opened`, `pr_merged`, `rejected` | `backend/app/api/v1/proposals.py` (this feature creates it; typed as `Literal[...]` so out-of-range filters surface as 422 VALIDATION_ERROR per the existing studies pattern at `backend/app/api/v1/studies.py:?status=StudyStatusWire`) |

### 8.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| `DIGEST_NOT_READY` | 404 | Digest hasn't been written yet (worker lag or `OPENAI_NOT_CONFIGURED` deferral). `retryable: true` |
| `STUDY_NOT_FOUND` | 404 | Referenced `study_id` doesn't exist |
| `PROPOSAL_NOT_FOUND` | 404 | Proposal ID not found |
| `CLUSTER_NOT_FOUND`, `TEMPLATE_NOT_FOUND` | 404 | Manual-proposal FK targets missing |
| `INVALID_STATE_TRANSITION` | 409 | Reject attempted on non-pending proposal (`retryable: false`) |
| `INVALID_STUDY_STATE` | 409 | Internal — digest worker received non-completed study (defense-in-depth) |
| `VALIDATION_ERROR` | 422 | Pydantic body validation OR out-of-range `?status` filter value |

**Worker-side terminal reasons** (logged at WARN; not endpoint-visible because the digest path is async via Arq): `OPENAI_NOT_CONFIGURED`, `LLM_PROVIDER_INCAPABLE` (capability cache miss or model mismatch), `UNKNOWN_MODEL_PRICING`, `OPENAI_BUDGET_EXCEEDED`. These mirror the codes used by the `feat_llm_judgments` worker per its §8.5. The operator-facing surfacing happens via `GET /api/v1/studies/{id}/digest` returning `DIGEST_NOT_READY` until the worker re-runs after the operator fixes the underlying condition.

## 9) Data model and state transitions

`digests`: append-only (no UPDATE / DELETE outside cascade).
`proposals.status`: `pending → pr_opened → pr_merged | rejected`. The `pr_opened` transition is owned by `feat_github_pr_worker`. This feature owns `pending → rejected`.

## 10) Security, privacy, and compliance

- **Threats:**
  1. The digest narrative could include sensitive doc content from the trials' top-K hits. **Mitigation:** the prompt sends study-summary data only — params + metrics + parameter-importance scores. **Never** doc IDs, doc bodies, or query text. (Smaller surface than `feat_llm_judgments`, whose worker by necessity sends doc bodies. The existing security doc at [`docs/04_security/llm-data-flow.md`](../../../04_security/llm-data-flow.md) is extended in §15 to document the digest path alongside.)
  2. Cost runaway — many studies completing simultaneously fire many digest LLM calls. **Mitigation:** daily budget gate via the same `backend/app/llm/budget_gate.py` peek/record pattern used by `feat_llm_judgments`. The pre-call peek refuses to fire when the projected total would breach `Settings.openai_daily_budget_usd`.
- **Auditability:** N/A — `audit_log` is MVP2. When MVP2 ships, this feature's `digest.generated` and `proposal.created` will emit audit events; `proposal.rejected` will emit when the user rejects.

## 11) UX flows and edge cases

This feature has no UI surface; UI is owned by `feat_studies_ui` (digest panel on study detail page) and `feat_proposals_ui` (proposals list + detail).

### Edge/error flows

- **Study completed with zero successful trials.** Per FR-2, digest row is created with the failure narrative; no proposal row.
- **OpenAI fails during digest generation.** Worker retries 3× with backoff; on final failure, no digest row is created. The orchestrator's enqueue of `generate_digest` includes Arq's default retry policy; after exhaustion the failure is logged at WARN. The user must retry manually (via runbook escape hatch).
- **Best trial's params include a parameter that no longer exists in the template.** The narrative may mention it; the recommended_config will include only currently-declared params. Mismatch is flagged in `digests.suggested_followups` (e.g., `"baseline trial used 'tie_breaker' which is no longer in the template"`).

## 12) Given/When/Then acceptance criteria

### AC-1: Digest generated on study completion (populates pre-existing pending proposal)

- Given a completed study with `best_metric=0.762` (vs. `baseline_metric=0.612`) AND an orchestrator-inserted pending `proposals` row with empty `config_diff` (`{}`) + null `metric_delta` (as inserted by `backend/workers/orchestrator.py:346-356`).
- When the orchestrator's enqueue at `backend/workers/orchestrator.py:370` fires `generate_digest(study_id)`.
- Then within 30s a `digests` row exists with non-null `narrative` (>200 chars), `parameter_importance` containing entries for every continuous param in the study's search space, `recommended_config` **matching the best trial's params filtered to currently-declared template params** (deterministically computed by the worker — NOT generated by the LLM, per FR-5), and `suggested_followups` (1–5 items). The pre-existing pending `proposals` row is UPDATED in place — `id` unchanged, `status` still `pending`, but now `config_diff = {param: {from, to}}` (one entry per `recommended_config` key) and `metric_delta = {ndcg@10: {baseline: 0.612, achieved: 0.762, delta_pct: 24.5}}`. **No second `proposals` row is created.**

### AC-2: Failed-study digest replaces artifact, deletes pending proposal

- Given a study where `best_metric IS NULL` (zero successful trials) AND the orchestrator-inserted pending `proposals` row exists.
- When `generate_digest` runs.
- Then a `digests` row exists with `narrative = "No successful trials in this study. Diagnose using the worker logs."`, `parameter_importance = {}`, `recommended_config = {}`, `suggested_followups = []`. The orchestrator's pending `proposals` row is DELETED (since `best_trial_id` is NULL, the proposal points at nothing). No second proposal is inserted.

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
- Then total tokens used <8000 (input ~5000, output ~3000); cost <$0.05 per digest at `gpt-4o-2024-08-06` rates (logged at INFO). `max_completion_tokens=2000` is passed on the OpenAI call so the daily budget gate is a true upper bound.

### AC-9: Boot-time scan picks up worker-down studies

- Given a study completed (orchestrator inserted the pending `proposals` row, then the worker crashed before the digest enqueue could be drained).
- When the worker restarts and `WorkerSettings.on_startup` runs.
- Then `list_pending_proposals_for_boot_scan` returns the orphaned study; `generate_digest(study_id)` is re-enqueued with `_job_id="generate_digest:{study_id}"`; the digest lands on the next worker tick and the pending proposal is populated as in AC-1.

### AC-10: OpenAI-not-configured defers, doesn't fail

- Given a study completed (pending proposal exists) AND `Settings.openai_api_key` is empty.
- When `generate_digest` runs.
- Then the worker logs `event_type='digest_openai_not_configured'` at WARN, does NOT write a `digests` row, does NOT modify the pending proposal, and returns. A subsequent `GET /api/v1/studies/{id}/digest` returns 404 `DIGEST_NOT_READY` (`retryable: true`). After the operator populates the key and the worker re-runs (boot scan or runbook re-enqueue), the digest lands.

### AC-11: Capability fallback degrades, doesn't fail

- Given a study completed AND `read_capability_result()` returns `cap.structured_output='fail'` (or `cap.model != Settings.openai_model`, or cache miss).
- When `generate_digest` runs.
- Then the worker logs `event_type='digest_capability_fail'` at WARN, calls OpenAI with a narrative-only prompt (no `response_format`), persists the `digests` row with `recommended_config={}` + `suggested_followups=[]` + a non-empty `narrative` + non-empty `parameter_importance` (computed from Optuna independently). The pending proposal stays in `status='pending'` with empty `config_diff`. Operator can fix the upstream + re-run via runbook for a full digest.

## 13) Non-functional requirements

- **Performance:** Digest generation completes in <30s p99 (Optuna importance compute <1s, OpenAI call ~10–20s, DB writes <500ms).
- **Cost:** <$0.05 per digest at `gpt-4o-2024-08-06` rates (logged at INFO). Daily budget gate alignment: same `backend/app/llm/budget_gate.py:peek_daily_total` → call → `record_cost` ordering as the `feat_llm_judgments` worker. `_safe_record_cost` wrapper catches Redis flaps so a paid digest call isn't dropped (cycle-2 C2-F3 pattern from `feat_llm_judgments`).
- **Reliability:** Digest job retries via the OpenAI SDK's built-in retry on `RateLimitError` / `APITimeoutError` / `APIConnectionError` / 5xx — same retry list as `backend/app/llm/openai_judge.py:rate_query_batch` (cycle-6 C6-F2 addition). A final failure is logged + the pending proposal stays in `status='pending'` for the boot-time scan or operator-triggered re-enqueue.
- **Operability:** Every digest invocation logs `study_id`, `tokens_used`, `cost_usd`, `duration_ms`, `proposal_id`, `model` at INFO. Worker-side terminal reasons surface via structured-log `event_type` markers (`digest_openai_not_configured`, `digest_budget_exceeded`, `digest_unknown_pricing`, `digest_capability_fail`, `digest_complete`, `digest_zero_trials`).

## 14) Test strategy requirements

- **Unit tests** (`backend/tests/unit/`):
  - `workers/test_digest_prompt.py` — prompt rendering with canonical inputs + autoescape test for adversarial study names (parallels `backend/tests/unit/workers/test_judgment_prompt_render.py`).
  - `workers/test_digest_failure_path.py` — zero-successful-trials case produces the failure narrative + deletes the pending proposal.
- **Integration tests** (`backend/tests/integration/`):
  - `test_digest_generate.py` — end-to-end against a seeded completed study + mocked OpenAI; asserts AC-1 (UPDATE pending proposal, no second row created).
  - `test_digest_zero_trials.py` — AC-2 (pending proposal deleted).
  - `test_digest_not_ready.py` — AC-4 (`GET /studies/{id}/digest` 404 path).
  - `test_digest_boot_scan.py` — AC-9 (on_startup re-enqueues orphan pending proposals).
  - `test_digest_openai_deferral.py` — AC-10 (no key → no digest row, no proposal mutation).
  - `test_digest_capability_fallback.py` — AC-11 (narrative-only fallback when structured_output not ok).
  - `test_proposal_reject.py` — AC-5.
  - `test_proposal_manual.py` — AC-6.
  - `test_proposals_api.py` — `GET /api/v1/proposals` pagination + X-Total-Count + status filter.
- **Contract tests** (`backend/tests/contract/`):
  - `test_digest_proposal_api_contract.py` — OpenAPI parity for all 5 endpoints + static error-code grep over the §8.5 catalog (mirrors `backend/tests/contract/test_judgments_api_contract.py`).
- **Benchmarks**:
  - `test_digest_token_budget.py` — assert AC-8 (cost <$0.05).

## 15) Documentation update requirements

- `docs/01_architecture/data-model.md` already documents the schemas; update if implementation diverges.
- `docs/03_runbooks/`: add `digest-debugging.md` — re-enqueue a digest, inspect parameter_importance, manually flag a proposal as rejected, the runbook escape hatch for `OPENAI_NOT_CONFIGURED` / `OPENAI_BUDGET_EXCEEDED` deferred digests.
- `docs/04_security/llm-data-flow.md` — extend with the digest path: data sent (study summary + params + metrics only — no doc IDs, no doc bodies, no query text). Smaller surface than judgments; one section addition.
- `docs/02_product/mvp1-user-stories.md`: mark US-16 / US-17 inline with "(Implemented — `feat_digest_proposal`)" per the PR #39 sweep pattern.

## 16) Rollout and migration readiness

- **Feature flags:** None.
- **Migration/backfill:** Adds `digests` and `proposals` tables.
- **Operational readiness gates:** Tutorial study produces an informative digest in under 30s.
- **Release gate:** `feat_github_pr_worker` author confirms the proposal interface (status, pr_url, pr_state columns) supports their flow.

## 17) Traceability matrix

| FR ID | AC IDs | Stories (TBD) | Test files | Docs |
|---|---|---|---|---|
| FR-1 (schema) | AC-1, AC-2, AC-6 | TBD | `tests/integration/test_digest_generate.py` | data-model.md |
| FR-2 (worker) | AC-1, AC-2, AC-7, AC-8, AC-10, AC-11 | TBD | `tests/integration/test_digest_generate.py`, `test_digest_zero_trials.py`, `test_digest_openai_deferral.py`, `test_digest_capability_fallback.py` | runbook |
| FR-2b (boot scan) | AC-9 | TBD | `tests/integration/test_digest_boot_scan.py` | runbook |
| FR-3 (digest fetch) | AC-3, AC-4 | TBD | `tests/integration/test_digest_not_ready.py` | — |
| FR-4 (proposal CRUD) | AC-5, AC-6 | TBD | `tests/integration/test_proposal_reject.py`, `test_proposal_manual.py`, `test_proposals_api.py` | — |
| FR-5 (digest prompt) | AC-1 | TBD | `tests/unit/workers/test_digest_prompt.py` | runbook |
| FR-6 (repo) | AC-1, AC-2, AC-5, AC-9 | TBD | covered by integration tests via the routes that call the repo helpers | — |

## 18) Definition of feature done

- [ ] AC-1 through AC-8 pass.
- [ ] All test layers green; ≥80% coverage on `backend/workers/digest.py`, `backend/app/api/v1/proposals.py`, `backend/app/db/repo/proposal.py`, `backend/app/db/repo/digest.py`.
- [ ] Tutorial study produces a useful digest under 30s for under $0.05.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None — all resolved (see Decision log).

### Decision log

- 2026-05-09 — One digest per study (UNIQUE) — per umbrella spec §9.
- 2026-05-09 — Top-10 trials in prompt (not full table) — token-budget discipline.
- 2026-05-09 — Failed studies get a digest row with placeholder narrative + no proposal — fail-loud-but-cheap principle.
- 2026-05-09 — `baseline_metric` source: **option (c)** — `feat_study_lifecycle`'s orchestrator runs a single non-Optuna trial with template defaults BEFORE Optuna starts; result lands in `studies.baseline_metric` (column added per [`data-model.md`](../../../01_architecture/data-model.md)). **Confirmed shipped:** `backend/app/db/models/study.py:76`.
- 2026-05-09 — `proposals` schema is owned by `feat_study_lifecycle` (full MVP1 shape, all columns including `pr_url`/`pr_state`/`pr_open_error`). This feature INSERTs rows only. **Superseded 2026-05-11:** Phase 2's C3-F1 atomicity fix now has the orchestrator INSERT the pending proposal row in the same transaction as `complete_study`. This feature UPDATEs that row rather than inserting a new one. The manual-proposal endpoint (FR-4) still inserts.
- 2026-05-09 — Digest re-generation: **manual escape hatch via runbook for MVP1** (`DELETE FROM digests WHERE study_id = ...` + re-enqueue); add a `POST /studies/{id}/digest/regenerate` endpoint at MVP2 if real demand emerges.
- 2026-05-09 — `GET /api/v1/proposals/{id}` response shape locked in FR-4: includes inline `study_summary` (when applicable) and inline `digest` (when applicable) so the UI doesn't need fan-out queries. Consumed by `feat_proposals_ui`.
- 2026-05-11 — Worker contract inverted from CREATE-proposal to POPULATE-existing-pending-proposal (FR-2). Driven by `feat_study_lifecycle` Phase 2's C3-F1 durable handoff design (`orchestrator.py:346-356`). The current `digest_stub.py` is replaced under the same Arq job name `generate_digest`.
- 2026-05-11 — Boot-time scan added (FR-2b). state.md called this requirement out at line 166. Required because the orchestrator's enqueue is best-effort; the pending proposal row is the durable handoff.
- 2026-05-11 — LLM infrastructure reuse locked in: `backend/app/llm/{capability_check,budget_gate,cost_model,prompt_loader}.py` shipped by `feat_llm_judgments` (PR #35) are consumed verbatim. The preflight order (api_key → capability+model → pricing → budget peek) mirrors `feat_llm_judgments` cycle-2/cycle-4/cycle-5/cycle-8 GPT-5.5 review findings.
- 2026-05-11 — Path drifts corrected: `backend/worker/` → `backend/workers/`; `backend/api/proposals.py` → `backend/app/api/v1/proposals.py`; `backend/db/models/` → `backend/app/db/models/` throughout.
- 2026-05-11 — `Settings.openai_model` is the authoritative model pin (CLAUDE.md Rule #8). Verbatim model IDs in §13 are illustrative only.
- 2026-05-11 — **`recommended_config` is deterministic, not LLM-generated** (FR-5 + AC-1). Patched in response to the implementation-plan cycle-1 F5/F9 + cycle-2 F1 GPT-5.5 review findings. The LLM hallucinating a config that doesn't match the best trial would silently violate AC-1; computing `recommended_config = {p: v for p, v in best_trial.params.items() if p in template.declared_params}` removes that failure mode and gives the template-drift case (best trial used a param no longer declared) a deterministic outcome — dropped keys are surfaced in `digests.suggested_followups`. The LLM's contract narrows to `{narrative, suggested_followups}`.
