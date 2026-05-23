# Feature Specification — Auto-Followup Studies

**Date:** 2026-05-23
**Status:** Draft
**Owners:** Eric Starr (product + engineering)
**Related docs:**
- [`idea.md`](idea.md) — origin + preflight-refreshed brief
- [`implementation_plan.md`](implementation_plan.md) (forthcoming)
- [`docs/01_architecture/optimization.md`](../../../01_architecture/optimization.md)
- [`docs/01_architecture/agent-tools.md`](../../../01_architecture/agent-tools.md) — `propose_search_space` tool wire shape
- [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) — DataTable / form-dropdown discipline
- Substrate column (already present): [`backend/app/db/models/study.py:72-77`](../../../../backend/app/db/models/study.py#L72) (`parent_study_id` self-FK, `baseline_metric` placeholder)
- Substrate primitive (already shipped): [`backend/app/agent/tools/studies/propose_search_space.py`](../../../../backend/app/agent/tools/studies/propose_search_space.py) (PR #175, 2026-05-21)
- Coordinated dep (idea-stage): [`feat_study_baseline_trial`](../feat_study_baseline_trial/idea.md) — when it ships, the gate switches from §FR-2a to §FR-2b (see Decision log D-3).

---

## 1) Purpose

RelyLoop's within-study optimizer compounds aggressively (hundreds of trials, TPE-narrowed), but its **across-study** loop is fully manual: an operator must read the digest, decide to chain a follow-up, and re-enter the create-study wizard with the prior winner's params copied across. The agent does not observe study completion — there is no background scheduler that wakes on the `completed` transition (verified: [`backend/app/agent/orchestrator.py:160`](../../../../backend/app/agent/orchestrator.py#L160) `run_turn` is only invoked from `send_user_message`).

- **Problem:** Each study is one-shot. The 2026-05-21 Karpathy-loop audit named this the single largest gap between RelyLoop today and an overnight-compounding loop — and it is the only "❌" cell in the audit's scorecard that maps to a feature-sized fix rather than a multi-quarter rewrite.
- **Outcome:** A relevance engineer can opt into auto-chaining on a per-study basis by setting `studies.config.auto_followup_depth` in the create-study wizard (or the `create_study` agent tool). When set, each completed study in the chain — provided its winner clears a lift gate and the daily LLM budget hasn't been exhausted — programmatically constructs the next study using `propose_search_space(prior_study_id=...)` and queues it via the existing `start_study` worker, decrementing the depth counter. Every chain member still produces a manual-review proposal; **no PR is opened autonomously**. Cancelling a parent cancels its in-flight child (default; confirm modal exposes the alternative).
- **Non-goal:** Auto-opening PRs on chain members, cross-template chains, multi-objective chains, search-space *widening* on stagnation. These are real follow-ups but each needs separate design — captured in §3 Out of scope with redirects.

## 2) Current state audit

### Existing implementations

- [`backend/app/db/models/study.py:72-77`](../../../../backend/app/db/models/study.py#L72) — `parent_study_id String(36) NULL ForeignKey("studies.id")` and `baseline_metric Float NULL` both already declared. The column docstring at line 75 reads `"Self-FK for fork lineage (MVP2 surface)"` — this feature *is* the MVP2 fork surface the column was added for. **No schema migration for column creation.** The FK uses Postgres default `ON DELETE NO ACTION` (no clause supplied at [`migrations/versions/0003_study_lifecycle_schema.py:183-187`](../../../../migrations/versions/0003_study_lifecycle_schema.py#L183)); D-1 below locks this as-is.
- [`backend/app/api/v1/schemas.py:619-649`](../../../../backend/app/api/v1/schemas.py#L619) — `StudyDetail` response already serializes `parent_study_id` (line 635) and `baseline_metric` (line 636). **No API response-shape migration.** Frontend code that wants to render chain lineage already has the field on the GET payload.
- [`backend/app/api/v1/schemas.py:556-586`](../../../../backend/app/api/v1/schemas.py#L556) — `StudyConfigSpec` is the wire shape for `studies.config`; this feature adds one optional field (`auto_followup_depth: int | None`) + one model_validator (depth-range check).
- [`backend/workers/digest.py`](../../../../backend/workers/digest.py) — runs after each study completes; persists digest narrative + parameter-importance + pending proposal; daily-budget peek at lines 554–578. The trigger for `enqueue_followup_study` lands inside this worker, *after* the pending-proposal insert (so a chain run still produces a reviewable proposal at every depth) and *after* the budget-peek block (so we reuse the in-scope `redis_client` for the second budget read).
- [`backend/workers/orchestrator.py:93-305`](../../../../backend/workers/orchestrator.py#L93) — `start_study(ctx, study_id)` consumes the queued row produced by `POST /api/v1/studies` (or by this feature's new worker function). The orchestrator's 5-consecutive-failures circuit breaker (docstring at [`:70`](../../../../backend/workers/orchestrator.py#L70), implementation at [`:212-225`](../../../../backend/workers/orchestrator.py#L212)) and 20-zero-metric "no signal" termination (at [`:243-244`](../../../../backend/workers/orchestrator.py#L243)) both transition `status → failed`; FR-7 reads `parent.status` to short-circuit the chain on either of those.
- [`backend/app/agent/tools/studies/propose_search_space.py`](../../../../backend/app/agent/tools/studies/propose_search_space.py) — `propose_search_space_impl` accepts `prior_study_id: UUID | None` and narrows numeric bounds via `winner ± |winner| × bracket` (default `bracket=0.5`). The chain worker calls the **domain function** behind this tool, not the agent-orchestrated tool, to avoid coupling the worker to chat-agent context (see Anti-patterns).
- [`backend/app/db/repo/study.py`](../../../../backend/app/db/repo/study.py) — `create_study(db, **fields)` at line 47, `get_study(db, study_id)` at line 61, `list_studies(...)` at line 67. This feature adds `list_children_of_study(db, parent_id) -> list[Study]` (single new repo function) for the UI chain panel.
- [`backend/app/services/study_state.py:172-192`](../../../../backend/app/services/study_state.py#L172) — `cancel_study(db, study_id)` is the canonical cancel-transition entry. FR-8's cascade wraps this: a new service `cancel_study_with_chain_cascade(db, study_id, *, cascade: bool)` calls `cancel_study(parent)` then loops over in-flight children. Direct ORM `UPDATE status` is blocked by the SQLAlchemy event-listener guards at [`:296-345`](../../../../backend/app/services/study_state.py#L296).
- [`backend/workers/all.py:55-93`](../../../../backend/workers/all.py#L55) — `WorkerSettings` registers Arq job functions. `enqueue_followup_study` is a one-shot job (NOT a cron), registered in the `functions=` list at line ~210.
- [`ui/src/app/studies/[id]/page.tsx`](../../../../ui/src/app/studies/%5Bid%5D/page.tsx) — study detail page (4.6 KB). FR-10 adds an "Auto-followup chain" panel between the existing trials summary and parameter-importance sections.
- [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) — canonical contextual-help source. This feature adds 4 new keys (`auto_followup_depth`, `auto_followup_chain`, `lift_gate`, `auto_followup_budget_skip`) per the §11 tooltip inventory.

### Navigation and link impact

No URL/route changes — the chain panel mounts on the existing `/studies/[id]` page; the wizard adds a Step-4-adjacent field on the existing `/studies/new` page. No redirects.

| Source file | Current link target | New link target |
|---|---|---|
| N/A | N/A | N/A |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/contract/test_studies_api.py` | StudyDetail response shape assertions | 1 file | **Extend** existing `auto_followup_depth_round_trips_through_config` contract test (new): assert `POST /studies` with `config.auto_followup_depth=3` round-trips through `GET /studies/{id}` unchanged. |
| `backend/tests/unit/api/test_study_config_validation.py` | `StudyConfigSpec` validator assertions | 1 file | **Extend**: cover the new `auto_followup_depth ∈ {None} ∪ [0,5]` validator (`0` is the worker-internal terminal value per FR-1; D-12). |
| `backend/tests/integration/test_studies_api.py` | `POST /studies` integration | 1 file | **Extend**: parent → completion → child enqueued (with FR-2a gate-passing fixture). |
| `backend/tests/unit/domain/test_study_state.py` | `cancel_study` unit tests | 1 file | **Extend**: cascade-cancel test (mock children list, assert each child's `cancel_study` called). |
| `ui/src/__tests__/components/studies/study-detail.test.tsx` | Study detail render | 1 file | **Extend**: when `parent_study_id` is set, "Parent" chip renders + links; when `auto_followup_depth > 0` in config, depth counter renders. |
| `ui/tests/e2e/studies.spec.ts` | Studies E2E | 1 file | **Extend**: opt-in field appears in wizard, chain panel renders on completed study, confirm-modal opens on cancel-with-children. |

### Existing behaviors affected by scope change

- **Digest worker completion path** (`backend/workers/digest.py`). Current: persists narrative + parameter-importance + pending proposal, then returns. New: after pending-proposal insert, evaluates the chain trigger; if all gates pass, enqueues `enqueue_followup_study(study_id)` (a separate Arq job — never inline, to keep the digest worker's transaction scope tight). **Decision needed: no** — the trigger is additive and conditional on `config.auto_followup_depth is not None` (per D-12, includes the worker-set terminal `0` so the depth-0 leaf's own enqueue can fire `auto_followup_depth_exhausted`); default behavior (no opt-in, i.e., field omitted or `None`) is unchanged.
- **`services.study_state.cancel_study`**. Current: transitions a single study `running → cancelled` (or `queued → cancelled`). New: a wrapping service `cancel_study_with_chain_cascade(db, study_id, *, cascade: bool = True)` calls the inner `cancel_study` then iterates in-flight children. Existing direct callers of `cancel_study` keep their behavior (no cascade). The `POST /api/v1/studies/{id}/cancel` endpoint at [`backend/app/api/v1/studies.py:459-475`](../../../../backend/app/api/v1/studies.py#L459) reads the new `?cascade=true|false` query param (default `true`) and dispatches accordingly. **Decision needed: no** — locked in §FR-8 + D-6.
- **Create-study wizard's Step 4** (`ui/src/app/studies/new/...`). Current: numeric fields for `max_trials` / `time_budget_min` / `parallelism` / `trial_timeout_s`. New: adjacent "Auto-followup chain" toggle group with depth selector (0, 1, 2, 3, 4, 5) where 0 = off. **Decision needed: no** — values + labels locked in §7.4.
- **Study detail page**. Current: trials summary, parameter importance, digest narrative. New: an "Auto-followup chain" panel that renders only when `parent_study_id IS NOT NULL` OR `config.auto_followup_depth > 0` OR `list_children_of_study(id)` is non-empty. **Decision needed: no** — locked in §FR-10.

---

## 3) Scope

### In scope

- **Pydantic** — One new optional field on `StudyConfigSpec` (`auto_followup_depth: int | None = None`) + one new model_validator (range check).
- **Domain** — `backend/app/domain/study/auto_followup.py` (new): pure function `evaluate_chain_gate(parent_study, parent_trials, ...) -> ChainGateOutcome` returning `enqueue | skip_no_lift | skip_parent_failed | skip_depth_exhausted` plus the structlog telemetry payload. Pure, unit-testable without fixtures.
- **Worker** — `backend/workers/auto_followup.py` (new): `enqueue_followup_study(ctx, parent_study_id)` Arq job. Loads parent + best trial + first-decile trials; runs `evaluate_chain_gate`; if `enqueue`, peeks daily budget; if under threshold, calls the **domain function** `propose_search_space.narrow_around_winner(...)` (refactored out of the agent-tool wrapper — see FR-4 / D-2), builds a `CreateStudyRequest`, persists via `repo.create_study`, and enqueues `start_study`.
- **Digest worker** — Adds one block at the end of `generate_digest` after the pending-proposal insert (per [`backend/workers/digest.py`](../../../../backend/workers/digest.py)) that enqueues `enqueue_followup_study(study_id)` when **`config.auto_followup_depth is not None`** AND `status == 'completed'`. Note: this includes `auto_followup_depth == 0` so the depth-0 leaf's own enqueue can fire `auto_followup_depth_exhausted` (per FR-1 note + AC-5). The gate evaluation happens *inside* `enqueue_followup_study`, not in the digest worker, so the digest path stays tight. Enqueue uses `_job_id=f"enqueue_followup_study:{study_id}"` so Arq's deterministic-job-id machinery dedupes duplicate deliveries at the queue level (per [`backend/workers/all.py:156-160`](../../../../backend/workers/all.py#L156) `generate_judgments_llm` precedent).
- **Service** — `backend/app/services/study_state.cancel_study_with_chain_cascade(...)` (new wrapper).
- **Repo** — One new function: `backend/app/db/repo/study.list_children_of_study(db, parent_id) -> list[Study]` (filters `parent_study_id == parent_id AND deleted_at IS NULL`, orders `created_at ASC`).
- **API** — One new sub-resource endpoint (`GET /api/v1/studies/{id}/children`, per FR-10) + extension of `POST /api/v1/studies/{id}/cancel` with optional `?cascade=true|false` query param (default `true`).
- **Frontend** — Study-detail page chain panel; create-study wizard depth selector (0–5, where 0 sentinel = off); cancel-with-children confirm modal; 4 new glossary entries.
- **Telemetry** — 8 structlog events (see FR-9 for the authoritative catalog): `auto_followup_enqueued`, `auto_followup_skipped_no_lift`, `auto_followup_skipped_budget`, `auto_followup_skipped_parent_failed`, `auto_followup_skipped_parent_missing`, `auto_followup_depth_exhausted`, `auto_followup_enqueued_duplicate_dropped`, `auto_followup_cancelled_with_parent`.
- **Tests** — Unit (4 files), integration (3 files), contract (1 file), E2E (1 spec extension). See §14.

### Out of scope

- **Auto-PR opening.** Every chain member generates a digest + pending proposal; the operator opens each PR manually. Captured as a future-feature stub: `feat_auto_followup_pr_open` (idea file written only if telemetry shows ≥90% operator approval rate on chain-member proposals after MVP1 ships).
- **Search-space widening on stagnation.** When 3 consecutive chain members produce no lift, the deterministic move is to widen rather than narrow — but that requires a `widen_around_winner` heuristic that doesn't exist. Captured as `feat_search_space_stagnation_widening` (will write later if operators ask).
- **Cross-template chains.** `propose_search_space(prior_study_id=...)` only narrows when `parent.template_id == child.template_id`. Cross-template chains would need a `swap_template` heuristic that maps prior winners' params onto a new template's `declared_params`. Composes with `feat_digest_executable_followups` which already needs that primitive.
- **Multi-objective chains.** Single-objective only in MVP1 per umbrella spec §13.
- **`ON DELETE SET NULL` migration.** Locked at NO ACTION (D-1) — studies are soft-deleted via `deleted_at` per CLAUDE.md "Database conventions"; the FK strictness is theoretical.
- **`feat_study_baseline_trial` integration.** When that feature ships and populates `studies.baseline_metric`, the gate switches from §FR-2a (lift-over-first-decile) to §FR-2b (lift-over-baseline). The switch is a single-line change in `evaluate_chain_gate`; no API/schema impact. Captured in D-3 and tracked in the [`feat_study_baseline_trial`](../feat_study_baseline_trial/idea.md) idea file as the consumer.
- **Modifying `propose_search_space` agent tool.** The tool's wire shape is unchanged. This feature uses the underlying domain function (`narrow_around_winner`) that the tool already wraps, refactoring out the small domain function from the existing tool body so both surfaces (agent tool + worker) call the same code (D-2).

### API convention check

This feature adds **one new sub-resource endpoint** (`GET /api/v1/studies/{study_id}/children`, per FR-10) and extends one existing endpoint (`POST /api/v1/studies/{id}/cancel`) with an optional query parameter. RelyLoop API conventions per [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md):

- **Endpoint prefix:** `/api/v1/<resource>` — verified at [`backend/app/api/v1/studies.py:459`](../../../../backend/app/api/v1/studies.py#L459).
- **Router namespace:** `backend/app/api/v1/studies.py` (router touches: the new `GET /studies/{id}/children` endpoint + the `?cascade=` param on the existing cancel handler).
- **Non-auth error envelope:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` per `backend/app/api/errors.py`. The existing 400 / 404 / 409 paths on cancel are unchanged; one new error code (`AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE`, 422) lands on `POST /studies` when `StudyConfigSpec` validation fails.
- **Auth error shape:** N/A — RelyLoop is single-tenant, no auth through MVP3.

### Phase boundaries

**Single-phase delivery.** Tier A (opt-in field + trigger + worker) and Tier B (budget gate + failure halting + UI panel + cancellation cascade + telemetry) ship together. Splitting them would put an autonomous worker in production without the operator-trust surfaces — the cascade modal, the chain panel, and the telemetry events are what make the trigger safe to ship. There is no `phase2_idea.md` required for this feature.

## 4) Product principles and constraints

- **Opt-in by default.** `auto_followup_depth` defaults to `None` (off). Zero existing studies are affected; zero existing tests change behavior; zero operators have to do anything to retain MVP1 single-shot semantics.
- **Bounded.** Hard validator cap at depth `5`. With the Standard preset's `max_trials=200` (per `chore_study_default_stop_conditions`), depth=5 = 1,000 trials per chain — meaningful overnight compounding, but capped so a single mis-clicked toggle cannot 10× the daily LLM budget.
- **Lift-gated.** A chain only continues when the winner *meaningfully* beats a baseline. Until `feat_study_baseline_trial` ships, the baseline is the parent's first-decile trials (§FR-2a, lock D-3); after, it's the per-study baseline trial (§FR-2b). Without lift, the chain ends.
- **Budget-aware.** Every chain enqueue peeks `peek_daily_total()` and short-circuits at ≥80% of `OPENAI_DAILY_BUDGET_USD`. The follow-up *study* runs deterministically (Optuna + ir_measures, no LLM), but the digest at its completion will need budget, so we gate at enqueue time, not at digest time.
- **No autonomous merge.** Every chain member produces a manual-review proposal. Production config never changes without an operator clicking through.
- **Cancellation is a hard stop.** Cancelling a parent cancels its in-flight child by default. Operators retain control even on a multi-hour overnight run.
- **Telemetry per skip reason.** Every "I didn't enqueue" branch emits a distinct structlog event so operators can grep the log to understand why a chain ended. No silent failures.
- **CLAUDE.md Absolute Rule #4 (adapter Protocol):** not engaged — no new engine adapter calls.
- **CLAUDE.md Absolute Rule #5 (migrations):** trivial — no new column. Conditional ALTER only if D-1 is overturned; locked NO ACTION ⇒ no migration.

### Anti-patterns

- **Do not** evaluate `evaluate_chain_gate` inside the digest worker's transaction. The gate evaluation needs the parent's full completed-trial list (for the first-decile computation); loading that inside `generate_digest` would balloon the digest transaction. The pattern is: digest persists → enqueue one-shot `enqueue_followup_study` job → that job loads what it needs in its own session. Mirrors the existing `digest worker → open_pr` boundary at [`backend/workers/digest.py`](../../../../backend/workers/digest.py) (cycle-1 F5).
- **Do not** call the `propose_search_space` *agent tool* (the one in `backend/app/agent/tools/studies/propose_search_space.py`) from `enqueue_followup_study`. Agent tools are dispatched with chat-agent context (`ctx.conversation_id`, etc.) that doesn't apply here. Refactor the small narrowing-math function out into `backend/app/domain/study/search_space_narrow.py` (or extend the existing `backend/app/domain/study/search_space_defaults.py` with `narrow_around_winner`); both the agent tool and this worker call the domain function (D-2).
- **Do not** add a new column to `studies` for the chain trigger or depth counter. The depth lives inside the existing `config` JSONB; the parent-child relationship lives on the existing `parent_study_id` self-FK. Adding a column would create a second source of truth for "is this study part of a chain?" and the two would drift.
- **Do not** mutate `study.status` directly when cascading the cancel. Route every child cancel through `services.study_state.cancel_study` so the SQLAlchemy event-listener guards (see [`backend/app/services/study_state.py:296-345`](../../../../backend/app/services/study_state.py#L296)) fire — bypassing them via a raw `UPDATE` raises `StudyStateProtectionError`, and rightly so.
- **Do not** open a PR automatically on a chain-member proposal. Locked out of scope; the trust gradient must be earned by operator behavior before we wire that path.
- **Do not** inline a chain into the orchestrator's `start_study`. Keeping the chain trigger in the *digest* worker (not the orchestrator) means a child only enqueues *after* the parent's results are persisted and reviewable. Inlining into `start_study` would create the child in the same transaction as the parent's completion, complicating rollback semantics.
- **Do not** invent dropdown values for the wizard depth selector outside `[0, 1, 2, 3, 4, 5]` (per CLAUDE.md "Enumerated Value Contract Discipline" and §7.4 below). The backend allowlist is `int | None` with `0 ≤ n ≤ 5` (per FR-1 + D-12); the frontend's wizard-`0` is a UX sentinel that maps to `null` at submit time (NOT to wire-`0`), so the source-of-truth comment in the wizard component must spell this out explicitly. Wire-`0` is reserved for the worker's decrement path.

## 5) Assumptions and dependencies

- **`feat_agent_propose_search_space` shipped (PR #175, 2026-05-21).**
  - Why required: provides the narrowing primitive the worker re-uses.
  - Status: implemented.
  - Risk if missing: cannot ship this feature. Not at risk.
- **`chore_study_default_stop_conditions` shipped (PR #215, 2026-05-23).**
  - Why required: makes every study in the chain have a known finite stop condition, bounding chain resource footprint.
  - Status: implemented.
  - Risk if missing: chain depth × `max_trials=∞` is catastrophic. Not at risk.
- **`peek_daily_total()` and `OPENAI_DAILY_BUDGET_USD`** wired into `backend/app/llm/budget_gate.py`.
  - Why required: budget short-circuit at enqueue time (FR-6).
  - Status: implemented (used in digest worker since 2026-05-13).
  - Risk if missing: chains can blow through daily budget. Not at risk.
- **`feat_study_baseline_trial`** (idea-stage, not yet shipped).
  - Why required: populates `studies.baseline_metric` so the gate can compare against a true production-config baseline (FR-2b).
  - Status: idea (priority P2 in MVP1 backlog).
  - Risk if missing: chain gate uses the parent's first-decile trials as an implicit baseline (FR-2a). Operators still get a meaningful gate; they just don't get a *production-baseline* comparison. **Hardness: soft.** Spec ships with FR-2a; when `feat_study_baseline_trial` lands, a single-line change in `evaluate_chain_gate` switches to FR-2b. See D-3.

## 6) Actors and roles

- Primary actor: **Relevance Engineer** (per CLAUDE.md persona list). Opts in by setting `auto_followup_depth` in the create-study wizard or via the `create_study` agent tool.
- System actors: **digest worker** (trigger), **`enqueue_followup_study` worker** (chain builder), **orchestrator** (`start_study` consumer).
- Role model: N/A — single-tenant install, no auth surface through MVP3.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP2. At that point, the 8 structlog events introduced in §FR-9 (authoritative catalog per D-10) become canonical audit events; the metadata payload (parent_study_id, depth, lift, etc.) is already shaped to drop into `audit_log.metadata_json` without secrets. Tracked in CLAUDE.md "Activates at MVP2."

## 7) Functional requirements

### FR-1: Opt-in field on `StudyConfigSpec`

- Requirement:
  - The system **MUST** accept an optional `auto_followup_depth: int | None = None` field on the wire shape `StudyConfigSpec` ([`backend/app/api/v1/schemas.py:556`](../../../../backend/app/api/v1/schemas.py#L556)).
  - The system **MUST** validate the field via a Pydantic `model_validator(mode='after')`: if `auto_followup_depth is not None`, then `0 <= auto_followup_depth <= 5`. Out-of-range values raise `ValidationError` → 422 `AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE`. `0` is a valid terminal-state value (see note below).
  - The system **MUST** preserve the value through the existing `config.model_dump(exclude_none=True, exclude_unset=True)` flow at study-create time (Story 3.3 contract) — `auto_followup_depth` is stored inside the `studies.config` JSONB row when set, omitted when `None`.
  - The system **MUST** return the field unchanged in `GET /api/v1/studies/{id}` (already covered — `StudyDetail.config: dict[str, Any]` round-trips the entire JSONB).
- Notes: No new column. The depth lives inside the existing JSONB. CLAUDE.md "Database conventions" already favors JSONB for "flexible structured fields (settings, params, metrics, payloads)." **Why `0` is valid:** the worker decrements `parent.depth - 1` when building a child (FR-3, FR-5). A depth-3 parent creates 3 follow-ups (depths 2 → 1 → 0). The depth-0 leaf is persisted so its own `enqueue_followup_study` invocation can emit the `auto_followup_depth_exhausted` telemetry event (FR-9, AC-5). Operators **never** opt into `0` via the wizard (the wizard's "Off" sentinel maps to `None`, not `0` — see FR-11); the wire-level allowance exists for the worker's decrement-and-persist path, and for the agent tool to set it if an LLM constructs an exotic chain shape. The spec intentionally does not bifurcate operator-facing vs worker-facing validators — one validator, one allowlist.

### FR-2: Lift-gate evaluation

- Requirement (FR-2a, **active on ship**):
  - The system **MUST** evaluate the chain gate via `evaluate_chain_gate(parent_study, parent_complete_trials, ...) -> ChainGateOutcome` (pure domain function at `backend/app/domain/study/auto_followup.py`).
  - The gate **MUST** return `enqueue` only when ALL of: (a) `parent.status == 'completed'`, (b) `parent.best_metric is not None`, (c) `config.auto_followup_depth > 0`, (d) the **lift-over-first-decile** comparison passes: let `first_decile = sorted(complete_trials, key=lambda t: t.created_at)[:max(1, len(complete_trials) // 10)]`, then `parent.best_metric > max(t.primary_metric for t in first_decile if t.primary_metric is not None) + epsilon` where `epsilon = 0.005`. If the parent has fewer than 10 complete trials, `first_decile` is the first trial alone.
  - The gate **MUST** return `skip_no_lift` when (a)/(b)/(c) pass but (d) fails — log `auto_followup_skipped_no_lift` with `parent_study_id`, `best_metric`, `first_decile_max`, `epsilon`.
- Requirement (FR-2b, **inactive on ship; activated by `feat_study_baseline_trial`**):
  - When `studies.baseline_metric IS NOT NULL` on the parent, the gate **MUST** instead compare `parent.best_metric > parent.baseline_metric + epsilon`. The first-decile branch is the fallback when `baseline_metric IS NULL`.
  - This requirement is **NOT** implemented in this PR. It is a guarded one-line change in `evaluate_chain_gate` whose test coverage is added when `feat_study_baseline_trial` ships. See D-3.
- Notes: `epsilon = 0.005` is the half-percent absolute lift. For metrics like nDCG@10 (range [0, 1]), this is a meaningful operator-perceptible improvement. For metrics on different scales, the spec assumes the same `epsilon` — operators with non-normalized metrics opt out by setting `auto_followup_depth = None`. A future feature could make `epsilon` per-objective; out of scope for MVP1.

### FR-3: `enqueue_followup_study` worker function

- Requirement:
  - The system **MUST** expose a new Arq job function `enqueue_followup_study(ctx, parent_study_id: str)` at `backend/workers/auto_followup.py`, registered in `backend/workers/all.py:functions`.
  - The function **MUST** load the parent study via `repo.get_study(db, parent_study_id)`. On `None`, log `auto_followup_skipped_parent_missing` (defensive — race with hard delete; should not fire in normal operation since hard delete doesn't exist in MVP1) and return.
  - **The function MUST then call the layer-2 idempotency backstop:** `existing_children = await repo.list_children_of_study(db, parent_study_id)`; if `existing_children` is non-empty, log `auto_followup_enqueued_duplicate_dropped` with `parent_study_id` and `existing_child_ids=[c.id for c in existing_children]` and return. This is the canonical implementation of §9 layer-2 + FR-9 event #7 + AC-13 (D-11). Layer-1 (Arq `_job_id`-keyed dedup at enqueue time, configured by the digest worker) handles the common dual-delivery case; this in-worker check covers the long-tail `_job_id` key-expiry path.
  - The function **MUST** load `parent_complete_trials` via `repo.list_trials_for_study(db, parent_study_id)` (existing repo function at [`backend/app/db/repo/trial.py:79`](../../../../backend/app/db/repo/trial.py#L79); no `status=` kwarg) and filter in-Python to `trial.status == 'complete'`. (Adding a `status=` kwarg to the repo is out of scope for this feature — the filter is a 2-line list comprehension.)
  - The function **MUST** call `evaluate_chain_gate(parent, parent_complete_trials)` and dispatch on the returned `ChainGateOutcome`:
    - `enqueue` → proceed to budget check + child build.
    - `skip_no_lift` → log `auto_followup_skipped_no_lift` and return.
    - `skip_parent_failed` → log `auto_followup_skipped_parent_failed` and return.
    - `skip_depth_exhausted` → log `auto_followup_depth_exhausted` and return.
  - The function **MUST** call `peek_daily_total(redis_client)` (from [`backend/app/llm/budget_gate.py`](../../../../backend/app/llm/budget_gate.py)) and compare against `0.8 * settings.openai_daily_budget_usd`. On `peek_total + estimated_max_call_cost(settings.openai_model) > 0.8 * budget` (with `estimated_max_call_cost` from [`backend/app/llm/cost_model.py:86`](../../../../backend/app/llm/cost_model.py#L86)), log `auto_followup_skipped_budget` with `peek_total`, `budget`, `threshold_pct=80` and return.
  - The function **MUST** call `narrow_around_winner(template_id=parent.template_id, prior_winning_params=best_trial.params, bracket=0.5)` (domain function — see D-2) to produce the child `search_space`.
  - The function **MUST** build a child via `repo.create_study(db, name=f"{parent.name} (chain depth {parent_depth - 1})", cluster_id=parent.cluster_id, target=parent.target, template_id=parent.template_id, query_set_id=parent.query_set_id, judgment_list_id=parent.judgment_list_id, search_space=child_search_space, objective=parent.objective, config=child_config, parent_study_id=parent.id, status='queued', optuna_study_name=<new uuid>)` where `child_config = {**parent.config, 'auto_followup_depth': parent.config['auto_followup_depth'] - 1}`.
  - The function **MUST** enqueue `start_study(child.id)` via the shared `ctx['arq_pool']`.
  - The function **MUST** log `auto_followup_enqueued` with `parent_study_id`, `child_study_id`, `remaining_depth`, `lift`, `epsilon`.
- Notes: All five "skip" branches and the one "enqueue" branch each have a distinct structlog event_type so operators can grep one log to understand chain behavior across a night.

### FR-4: Domain function `narrow_around_winner`

- Requirement:
  - The system **MUST** expose a pure domain function `narrow_around_winner(template_id: str, prior_winning_params: dict[str, Any], bracket: float = 0.5) -> SearchSpace` at `backend/app/domain/study/search_space_defaults.py` (extending the existing module).
  - The function **MUST** produce byte-identical output to what the existing `propose_search_space` agent tool produces for the same inputs (verified by the parity test in §14).
  - The existing agent tool [`backend/app/agent/tools/studies/propose_search_space.py`](../../../../backend/app/agent/tools/studies/propose_search_space.py) **MUST** be refactored to call this domain function, removing the duplicate narrowing math from the tool body.
- Notes: This refactor + extraction is required regardless — D-2 forbids the worker from calling the agent tool directly. The byte-identical-output requirement guards against drift.

### FR-5: Strict config inheritance

- Requirement:
  - The child study's `config` **MUST** be `{**parent.config, 'auto_followup_depth': parent.config['auto_followup_depth'] - 1}` (per FR-3). Every other key (`max_trials`, `time_budget_min`, `parallelism`, `trial_timeout_s`, `sampler`, `pruner`, `seed`, `secondary_metrics`) propagates verbatim.
  - The child's `name` **MUST** be `f"{parent.name} (chain depth {remaining})"` where `remaining = parent.config['auto_followup_depth'] - 1`.
  - The child's `cluster_id`, `target`, `template_id`, `query_set_id`, `judgment_list_id`, `objective` **MUST** be inherited verbatim from the parent.
- Notes: D-4 locks this. Alternative (reset to `Settings.studies_default_*`) was rejected — operator chose the parent's config for a reason; chaining with different parallelism would surprise.

### FR-6: Daily budget gate at enqueue time

- Requirement:
  - The system **MUST** call `peek_daily_total(redis_client)` inside `enqueue_followup_study` before building the child.
  - The system **MUST** short-circuit when `peek_total + estimated_max_call_cost(settings.openai_model) > 0.8 * settings.openai_daily_budget_usd`. Log `auto_followup_skipped_budget`.
  - The system **MUST** use the existing `backend/app/llm/budget_gate.peek_daily_total` (no new budget tracking — reuses the digest-worker substrate).
- Notes: D-5 locks 80%. Headroom for the digest LLM call at chain-member completion + any in-flight chat-agent activity.

### FR-7: Failure-aware halting

- Requirement:
  - The system **MUST** return `skip_parent_failed` from `evaluate_chain_gate` when `parent.status == 'failed'` (covers both 5-consecutive-failures and 20-zero-metric terminations — both transition to `failed`).
  - The system **MUST** return `skip_parent_failed` when `parent.status == 'cancelled'` (defensive — should not fire because the digest worker doesn't run on cancelled studies, but the worker re-checks).
- Notes: Re-checking is a deliberate redundancy. The digest-worker triggers `enqueue_followup_study` only on `completed`, but a race between cancellation and digest enqueue is theoretically possible; explicit gate in the worker is the canonical authority.

### FR-8: Cancellation cascade

- Requirement:
  - The system **MUST** add `services.study_state.cancel_study_with_chain_cascade(db, study_id, *, cascade: bool = True) -> Study`.
  - When `cascade is True`, the function **MUST** call `cancel_study(study_id)` then iterate `repo.list_children_of_study(db, study_id)` filtered by `status IN ('queued', 'running')`, calling `cancel_study(child.id)` for each. Each child cancel emits its own `study_state_transition` log + a `auto_followup_cancelled_with_parent` log carrying `parent_study_id` and `child_study_id`.
  - When `cascade is False`, the function **MUST** call only `cancel_study(study_id)` (parent only).
  - The system **MUST** extend `POST /api/v1/studies/{id}/cancel` with optional query parameter `?cascade=<bool>` (default `true`) that selects which path. Invalid `?cascade=` values raise `400 INVALID_CASCADE_PARAM` (FastAPI's automatic query-param parsing already returns 422 for non-bool; we override to 400 with the standard error envelope for symmetry with the existing endpoint's error catalog).
  - The cascade **MUST** propagate transitively — if a cancelled child has children (depth > 1 chain in flight), each grandchild is also cancelled. Implementation: depth-first recursive traversal via `list_children_of_study`.
  - The frontend cancel-button modal **MUST** default the cascade radio to "Cancel parent + in-flight children" (per D-6) when the parent has at least one `status IN ('queued', 'running')` child OR when `parent.config.get('auto_followup_depth', 0) > 0` and `parent.status == 'running'` (anticipated child).
- Notes: D-6 locks the default. The radio is exposed even when no children are in-flight so the operator can see the choice and feel in control; selecting "Cancel parent only" with no children is a no-op for the cascade path.

### FR-9: Telemetry events (authoritative catalog — 8 events)

- Requirement:
  - The system **MUST** emit each of these structlog events at `INFO` level via the existing `logger = structlog.get_logger(__name__)` pattern (see [`backend/workers/digest.py:77`](../../../../backend/workers/digest.py#L77)):
    1. `auto_followup_enqueued` — `parent_study_id`, `child_study_id`, `remaining_depth`, `lift`, `epsilon`.
    2. `auto_followup_skipped_no_lift` — `parent_study_id`, `best_metric`, `first_decile_max`, `epsilon`.
    3. `auto_followup_skipped_budget` — `parent_study_id`, `peek_total`, `budget`, `threshold_pct=80`.
    4. `auto_followup_skipped_parent_failed` — `parent_study_id`, `parent_status`, `parent_failed_reason`. **Defensive-only:** the digest worker doesn't run on failed studies (verified at [`backend/workers/orchestrator.py:452`](../../../../backend/workers/orchestrator.py#L452) — digest enqueue is gated through the `completed` transition only), so this event fires only if `enqueue_followup_study` is manually invoked on a failed study (e.g., operator triggers via shell).
    5. `auto_followup_skipped_parent_missing` — `parent_study_id`. Defensive — fires if the parent row was hard-deleted between digest commit and the followup worker's load. MVP1 has no hard-delete tooling, so this never fires in normal operation.
    6. `auto_followup_depth_exhausted` — `parent_study_id`, `auto_followup_depth=0`. Fires on the depth-0 leaf's own enqueue invocation (per FR-1 + AC-5).
    7. `auto_followup_enqueued_duplicate_dropped` — `parent_study_id`, `existing_child_ids`. Defensive backstop — fires if Arq's `_job_id` dedup misses (rare; the `_job_id=f"enqueue_followup_study:{study_id}"` machinery should drop dupes at the queue level — see FR-3 and §9). The worker re-checks `list_children_of_study` after acquiring its DB session as a safety net.
    8. `auto_followup_cancelled_with_parent` — `parent_study_id`, `child_study_id`.
  - Every event **MUST** carry `event_type=<event_name>` per the existing structlog convention (so `jq 'select(.event_type=="auto_followup_skipped_budget")'` works).
  - Events **MUST NOT** include any secrets or PII (no API keys, no user identifiers — N/A in MVP1 anyway).
- Notes: This is the operator's primary debugging surface until MVP2's `audit_log` lands. The 3 defensive events (4, 5, 7) are gated for the canary paths and should be alerted on at MVP2.

### FR-10: UI — Study-detail chain panel

- Requirement:
  - The system **MUST** render an "Auto-followup chain" panel on `/studies/[id]` when ANY of: (a) `study.parent_study_id IS NOT NULL`, (b) `study.config.auto_followup_depth > 0`, (c) `list_children_of_study(study.id)` is non-empty.
  - The panel **MUST** display:
    - **Parent link** (if `parent_study_id`): "Parent: <link to parent study>".
    - **Remaining depth** (if `config.auto_followup_depth > 0`): "Auto-chain: {remaining} of {original} — next follow-up will narrow around current winner." `original` = `study.config.auto_followup_depth + (chain position from root)`. For MVP1, we display `auto_followup_depth` as remaining and skip the "of {original}" suffix because computing original requires walking the chain to root; lock to "Remaining auto-follow-ups: N" (simpler, no DB walk).
    - **Children list** (if non-empty): table with columns `Child name`, `Status`, `Best metric`, `Created`. Each row links to the child's detail page.
  - The panel **MUST** consume the **existing** `GET /api/v1/studies/{id}` payload (which already returns `parent_study_id` + `baseline_metric` + `config`) PLUS a single new `GET /api/v1/studies/{id}/children` endpoint that wraps `list_children_of_study`. Response shape: `{ "data": list[StudySummary], "next_cursor": null }` (no pagination for v1 — depth ≤ 5, so direct children of any one parent are at most 1 by construction).
  - **`list_children_of_study` returns DIRECT children only** (`WHERE parent_study_id = ?`, not transitive descendants). The chain panel renders the parent link (1 hop up) + direct children list (1 hop down). To see deeper lineage, the operator navigates to a child's detail page; that page shows the same panel with the next hop. This is the deliberate trade-off — keeps the endpoint O(1)-shaped and avoids materializing a full chain tree on every page load. A transitive `list_descendants_of_study` is a future feature if operators ask for a single-page chain view.
- Notes: The children endpoint is purposefully separate from the detail endpoint to keep `StudyDetail` from ballooning. List view shape matches existing `StudyListResponse` (`StudySummary[]`). The chain depth-5 ceiling guarantees at most 5 sequential navigations to walk a full chain.

### FR-11: UI — Create-study wizard depth selector

- Requirement:
  - The system **MUST** add a depth selector to the create-study wizard's existing Step-4 stop-conditions section (where `max_trials` / `time_budget_min` already live).
  - The selector **MUST** be a `<select>` with options `[0, 1, 2, 3, 4, 5]` labeled `["Off", "1 follow-up", "2 follow-ups", "3 follow-ups", "4 follow-ups", "5 follow-ups"]`.
  - The wizard **MUST** map `0` → omit `auto_followup_depth` from the submitted `config` (so `auto_followup_depth` stays at its default `None`), and `1..5` → set `config.auto_followup_depth = <value>`.
  - The selector **MUST** include a top-of-file source-of-truth comment per CLAUDE.md "Enumerated Value Contract Discipline" naming the backend allowlist and the `0`-sentinel convention.
  - The selector **MUST** carry an inline tooltip (per §11) explaining the lift gate + budget gate.
- Notes: The `0`-sentinel is a UX choice — "Off" is more discoverable in a numeric selector than a separate boolean toggle. The mapping is documented at the call site so future drift cannot silently invert the meaning.

### FR-12: ON DELETE policy locked to NO ACTION

- Requirement:
  - The system **MUST NOT** add an ALTER migration to change `studies.parent_study_id`'s FK behavior from the default `NO ACTION`.
  - Operators relying on hard-delete tooling (no such tool exists in MVP1) **MUST** soft-delete via `deleted_at` instead, per CLAUDE.md "Database conventions."
- Notes: D-1 locks this. Adding the ALTER later is a one-PR, ~15-LOC change if hard-delete tooling lands.

## 8) API and data contract baseline

### 8.1 Endpoint surface

This feature adds **one new sub-resource endpoint** and extends one existing endpoint:

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `GET` | `/api/v1/studies/{study_id}/children` | List in-flight + completed child studies of a parent (for the chain panel) | `404 STUDY_NOT_FOUND` |
| `POST` | `/api/v1/studies/{study_id}/cancel?cascade=<bool>` | Cancel parent study; `cascade=true` (default) also cancels in-flight children | `404 STUDY_NOT_FOUND`, `409 INVALID_STATE_TRANSITION`, `400 INVALID_CASCADE_PARAM` |

The `POST /api/v1/studies` body shape gains one optional field nested in `config.auto_followup_depth` (FR-1); no path or method change.

### 8.2 Contract rules

- Error body **MUST** include machine-readable `error_code` per the project envelope (verified against `backend/app/api/errors.py`).
- The `?cascade=` query param **MUST** parse case-insensitively (`"true"`, `"True"`, `"TRUE"` all → `True`). Invalid values map to `400 INVALID_CASCADE_PARAM` rather than FastAPI's default `422`.
- The children endpoint **MUST** return `200 { "data": [], "next_cursor": null }` for a study with no children — never `404`.

### 8.3 Response examples

**`GET /api/v1/studies/{id}/children` — success (no children):**
```json
{
  "data": [],
  "next_cursor": null
}
```

**`GET /api/v1/studies/{id}/children` — success (one direct child):**

Per FR-10, `list_children_of_study` returns DIRECT children only. A depth-N chain produces a single direct child per parent (the next chain member); grandchildren are reached by navigating into that child's detail page and reading ITS children. This example shows the root parent's response — one direct child:

```json
{
  "data": [
    {
      "id": "01923b8e-9c0a-7000-8000-000000000001",
      "name": "My study (chain depth 2)",
      "cluster_id": "01923b8e-9c0a-7000-8000-aaaaaaaaaaaa",
      "status": "running",
      "best_metric": null,
      "created_at": "2026-05-23T22:00:00Z",
      "completed_at": null
    }
  ],
  "next_cursor": null
}
```

**`GET /api/v1/studies/{id}/children` — 404 unknown study:**
```json
{
  "detail": {
    "error_code": "STUDY_NOT_FOUND",
    "message": "study 01923b8e-9c0a-7000-8000-000000000099 not found",
    "retryable": false
  }
}
```

**`POST /api/v1/studies/{id}/cancel?cascade=true` — 200 success:**
```json
{
  "id": "01923b8e-9c0a-7000-8000-000000000000",
  "status": "cancelled",
  "completed_at": "2026-05-23T22:45:00Z",
  ...
}
```
(Full `StudyDetail` shape per [`backend/app/api/v1/schemas.py:619`](../../../../backend/app/api/v1/schemas.py#L619). The cascade itself is observable via the children endpoint immediately after.)

**`POST /api/v1/studies/{id}/cancel?cascade=invalid` — 400:**
```json
{
  "detail": {
    "error_code": "INVALID_CASCADE_PARAM",
    "message": "?cascade= must be one of: true, false (case-insensitive)",
    "retryable": false
  }
}
```

**`POST /api/v1/studies` — 422 out-of-range depth:**
```json
{
  "detail": {
    "error_code": "AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE",
    "message": "config.auto_followup_depth must be between 0 and 5 inclusive when set; got 6",
    "retryable": false
  }
}
```

### 8.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `config.auto_followup_depth` (POST body) | `None`, `0`, `1`, `2`, `3`, `4`, `5` (`0` is internal-only — wizard never sends it; see FR-1 note) | `backend/app/api/v1/schemas.py:StudyConfigSpec._validate_auto_followup_depth` (model_validator added by FR-1) | `ui/src/components/studies/create-study-wizard/step-4-stop-conditions.tsx` (`AUTO_FOLLOWUP_DEPTH_WIZARD_VALUES = [0, 1, 2, 3, 4, 5] as const` where wizard-`0` is the off-sentinel that maps to `undefined` on the wire — distinct from the backend-allowed wire-`0` which only the worker sets) |
| `?cascade=` (cancel query) | `true`, `false` (case-insensitive at parse time; normalized to lowercase bool) | `backend/app/api/v1/studies.py:cancel_study` (custom dependency that parses Literal-style) | `ui/src/app/studies/[id]/page.tsx` cancel modal — radio: `"true"` ↔ "Cancel parent + in-flight children", `"false"` ↔ "Cancel parent only" |
| Chain-panel render conditions (UI-side only — no wire flow) | `parent_study_id IS NOT NULL` OR `config.auto_followup_depth > 0` OR `children.length > 0` | N/A (composed in `ui/src/components/studies/auto-followup-chain-panel.tsx`) | Component prop sourced from `GET /studies/{id}` + `GET /studies/{id}/children` |

### 8.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| `AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE` | 422 | `config.auto_followup_depth` was set but not in `[0, 5]`. (`0` is internal terminal state; wizard never sends it — see FR-1 note.) |
| `INVALID_CASCADE_PARAM` | 400 | `?cascade=` query param on cancel was not parseable as a boolean. |

Existing error codes reused: `STUDY_NOT_FOUND` (404), `INVALID_STATE_TRANSITION` (409).

## 9) Data model and state transitions

### New / changed entities

**No new tables. No new columns on existing tables.** The feature is purely additive to existing surfaces:

- `studies.parent_study_id` — **already exists** ([`backend/app/db/models/study.py:72-75`](../../../../backend/app/db/models/study.py#L72)). This feature *uses* the column for the first time; it does not declare it.
- `studies.config` JSONB — **already exists**. This feature adds one optional key (`auto_followup_depth`) inside the JSONB; no migration.
- `studies.baseline_metric` — **already exists** ([`backend/app/db/models/study.py:76`](../../../../backend/app/db/models/study.py#L76)). This feature reads it (FR-2b path), does not write it. Writing is `feat_study_baseline_trial`'s job.

### Required invariants

- `studies.config.auto_followup_depth IS NULL` OR `0 <= studies.config.auto_followup_depth <= 5` (per FR-1 + D-12; `0` is the worker-internal terminal-state value). Enforced at API write via `StudyConfigSpec` validator (FR-1) for API-originated writes; enforced at the worker level by the FR-3 decrement path (`parent_depth - 1` produces `0..N-1` from `1..N` parents, all within range) for auto-created child studies. NOT enforced at DB level — JSONB does not support partial CHECK constraints in a portable way; the two write paths (API + worker decrement) are the canonical sources.
- `studies.parent_study_id IS NULL` OR `studies.parent_study_id REFERENCES studies(id)` (NO ACTION on delete) — already enforced by the existing FK.
- A child's `cluster_id`, `target`, `template_id`, `query_set_id`, `judgment_list_id`, `objective` **MUST** equal its parent's values. Enforced by `enqueue_followup_study` at child-creation time; not enforced at DB level (no constraint can express "match parent values across 6 columns"). A future invariant write-path audit at MVP2 may add a service-level assertion.
- A chain's combined depth **MUST NOT** exceed the original `auto_followup_depth`. Enforced by the `parent_depth - 1` decrement in FR-3; `depth = 0` short-circuits via `skip_depth_exhausted` (FR-7).

### State transitions

This feature does not add a new study status. It adds two new transition *triggers* for existing statuses:

- `running → completed` (parent) — **may** enqueue `enqueue_followup_study` (gate-dependent). Existing transition, new side effect.
- `running → cancelled` (parent, via cascade) — **may** cancel in-flight `running` and `queued` children (cascade-dependent). Existing transition, new transitive trigger.

State diagram unchanged at the per-study level. The new dimension is chain-level: a chain is "alive" iff any member is `queued` or `running`; "ended" otherwise (every member terminal).

### Idempotency / replay behavior

- `enqueue_followup_study(parent_study_id)` idempotency is **two-layered**:
  1. **Primary (queue-level):** the digest worker enqueues with `_job_id=f"enqueue_followup_study:{study_id}"`, so Arq's deterministic-job-id machinery drops duplicates at the Redis queue level before any worker code runs. This is the canonical RelyLoop pattern (precedent: [`backend/workers/all.py:156-160`](../../../../backend/workers/all.py#L156) for `generate_judgments_llm`). Race window: zero — Arq's `_job_id` check is atomic against Redis.
  2. **Defensive backstop (worker-level):** at the start of `enqueue_followup_study`, after acquiring the DB session, re-check `repo.list_children_of_study(db, parent_id)`. If non-empty, log `auto_followup_enqueued_duplicate_dropped` (FR-9 event #7) with `existing_child_ids` and return. This catches the case where (a) a job ran successfully, (b) Arq cleaned up the job_id key after expiry, (c) a fresh delivery arrives later (e.g., a manual re-trigger or a cron sweep). **Race window:** technically yes — two concurrent worker invocations with the same parent_id can both see `[]` and both create. Mitigation: layer 1 makes this near-impossible. A future hardening (deferred — captured as `chore_auto_followup_parent_advisory_lock`) is a Postgres advisory lock keyed on `parent_study_id` for `SELECT FOR UPDATE`-style serialization. **For MVP1, the two-layer scheme is sufficient — there is no autonomous re-triggering path; layer 1 covers the only known duplicate-delivery vector (worker restart between Redis ack and DB commit).**
- Cancellation cascade is idempotent: cancelling an already-cancelled child is a no-op (the `_ensure_legal` check at [`backend/app/services/study_state.py:180`](../../../../backend/app/services/study_state.py#L180) rejects `cancelled → cancelled` transitions via `InvalidStateTransition`; the cascade catches that exception and continues to the next child).

## 10) Security, privacy, and compliance

- **Threats:**
  1. Operator mis-sets `auto_followup_depth=5` and walks away — runs unbounded LLM cost overnight. **Mitigation:** Daily budget gate at 80% (FR-6). Depth cap at 5 (FR-1). Wizard tooltip explains both gates (§11).
  2. Bug in lift gate fires `enqueue` when it should `skip_no_lift` — chains run forever on noise. **Mitigation:** Lift gate is a pure unit-testable domain function (FR-2). Depth cap caps damage at 5 chains. Telemetry events allow grep-the-log diagnosis.
  3. Bug in cancellation cascade misses a child — operator cancels parent, child keeps running, surprises operator. **Mitigation:** Integration test (§14) covers depth-3 cascade. Cascade is recursive on `list_children_of_study`. Worker is idempotent.
  4. Chain produces a flood of pending proposals operator can't review. **Mitigation:** Out of scope (auto-PR-opening explicitly deferred); operator faces N proposals where N ≤ depth+1 = 6 — readable, not a flood.
- **Controls:** No new authn/authz (single-tenant MVP1). No new secrets. No new external API calls (all chain work is internal to RelyLoop).
- **Secrets/key handling:** N/A — feature does not introduce new credentials.
- **Auditability:** Telemetry events (FR-9) cover every enqueue / skip / cascade. At MVP2, these graduate to `audit_log` rows (per CLAUDE.md "Activates at MVP2"). For MVP1, structlog + Compose `make logs` are the audit surface.
- **Data retention / deletion / export impact:** No new data classes. Chain studies are subject to the same soft-delete / retention policy as standalone studies (per `studies.deleted_at`).

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:**
  - **Create-study wizard** — depth selector lives in the existing Step-4 stop-conditions section, adjacent to `max_trials` / `time_budget_min`. No new step; no nav change.
  - **Study detail page** — chain panel is a new section between the existing trials-summary card and the parameter-importance panel. Always at the same vertical position; visible only when the render conditions in FR-10 are met.
  - **Cancel modal** — replaces the existing 1-question cancel modal with a 2-question modal when cascade applies (radio: cascade vs. parent-only).
- **Labeling taxonomy:**
  - "Auto-followup chain" (panel title; matches the spec name; `auto_followup_chain` glossary key).
  - "Off / 1 follow-up / 2 follow-ups / 3 follow-ups / 4 follow-ups / 5 follow-ups" (wizard selector options; matches the depth values 0–5).
  - "Parent: {study name}" (chain panel; if `parent_study_id`).
  - "Remaining auto-follow-ups: N" (chain panel; if `config.auto_followup_depth > 0`).
  - "Cancel parent + in-flight children" / "Cancel parent only" (cancel-modal radio).
- **Content hierarchy:**
  - Chain panel: parent link (top) → remaining-depth line → children table (bottom). Always visible when render conditions met.
  - Cancel modal: question first, radio options second, action buttons last (standard modal pattern from existing `chore_cluster_delete_ui`).
- **Progressive disclosure:** Chain panel is invisible by default (no chain ⇒ no panel). When visible, all content is shown — no further reveal needed.
- **Relationship to existing pages:** Chain panel **extends** the existing study-detail page. Wizard depth selector **extends** Step 4. Cancel modal **extends** the existing cancel modal.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement | Glossary key |
|---|---|---|---|---|
| Wizard "Auto-followup chain" selector | "Run up to N follow-up studies after this one completes. Each follow-up narrows the search space around the winner. Halts on no lift, exhausted budget, or failed parent." | hover on info icon | right | `auto_followup_depth` (new) |
| Chain panel title | "RelyLoop ran follow-up studies automatically based on this study's winner. Each follow-up narrowed the search bounds; the chain ends when there's no further lift." | hover on info icon | right | `auto_followup_chain` (new) |
| Lift-gate explainer (in tooltip on `auto_followup_chain`) | "A follow-up only enqueues when the parent's winner beat the first-decile baseline by at least 0.5%. Smaller lifts are likely noise." | hover on info icon | inline | `lift_gate` (new) |
| Cancel modal radio | "Cancel just the parent; in-flight children keep running. Or cancel the whole chain at once." | hover on radio label | right | N/A (modal-local; no glossary key needed) |
| Wizard depth-gate (when daily budget low) | "Daily LLM budget is at {N}% — chains may be skipped." | inline below selector | inline | `auto_followup_budget_skip` (new) |

Per CLAUDE.md "Tooltips and contextual help": every entry above cites a glossary key (4 new keys to add in the implementation plan) or is explicitly modal-local. The implementation plan adds these 4 keys to `ui/src/lib/glossary.ts` in Story 4.x.

### Primary flows

1. **Opt into chain (operator creates a chained study, depth=3 means 3 follow-ups after the original).**
   - Operator opens create-study wizard.
   - In Step 4, operator selects "3 follow-ups" from the depth dropdown.
   - Operator submits; `POST /studies` round-trips `config.auto_followup_depth=3` on the original study (study A).
   - Study A runs to completion → digest persists → `enqueue_followup_study(A)` fires → gate passes → child B enqueued with `config.auto_followup_depth=2`.
   - B runs → digest → `enqueue_followup_study(B)` → gate passes → child C enqueued with `config.auto_followup_depth=1`.
   - C runs → digest → `enqueue_followup_study(C)` → gate passes → child D enqueued with `config.auto_followup_depth=0` (the persisted terminal state per FR-1 + D-12).
   - D runs → digest → `enqueue_followup_study(D)` → gate returns `skip_depth_exhausted` (because `D.config.auto_followup_depth == 0`) → `auto_followup_depth_exhausted` logged → no further child.
   - Operator wakes up to 4 chain-member proposals in `/proposals` (one per study A/B/C/D), reviews and merges manually.

2. **Chain stops mid-run on no lift.**
   - Operator starts a depth-5 chain.
   - Chain members 1 and 2 produce lift; chain member 3's winner does not beat the first-decile baseline by `epsilon`.
   - `auto_followup_skipped_no_lift` logged; no further chain members enqueued.
   - Operator sees 3 chain-member proposals in `/proposals` + the original parent's proposal — 4 total.

3. **Operator cancels a running chain.**
   - Operator opens parent study's detail page.
   - Cancel button → modal opens with radio defaulting to "Cancel parent + in-flight children" (per D-6).
   - Operator confirms.
   - `POST /studies/{parent_id}/cancel?cascade=true` fires.
   - Parent transitions to `cancelled`. Each in-flight `queued` / `running` child also transitions to `cancelled` via the cascade service.
   - `auto_followup_cancelled_with_parent` logged per child.

### Edge / error flows

- **Daily budget at 80% when chain member completes** → `auto_followup_skipped_budget` logged; chain ends silently. Operator can grep the log to understand. Future feature could surface this as a banner on the chain panel.
- **Parent study fails (5-consecutive-failures or 20-zero-metric)** → **no digest is enqueued by the orchestrator (verified at `backend/workers/orchestrator.py:452` — digest enqueue only fires from the `_stop` → `complete_study` path).** Consequently, `enqueue_followup_study` is never invoked, and no chain-halt telemetry fires in the normal failed-parent path (per AC-6 and FR-9 event #4's defensive-only annotation). Chain panel shows "Chain halted: parent failed" by reading `study.status` and `study.failed_reason` on the existing study-detail payload — no chain-specific event is needed.
- **Worker restarts between digest commit and `enqueue_followup_study` dispatch** → on restart, the digest is already persisted (idempotent); `enqueue_followup_study` is called from the digest worker only once per parent (the digest worker is idempotent — re-running it short-circuits via the existing `digest already persisted` check at [`backend/workers/digest.py:467`](../../../../backend/workers/digest.py#L467)). Defensive idempotency in `enqueue_followup_study` (per §9 idempotency notes) covers the corner case of dual delivery.
- **Operator opens `GET /studies/{id}/children` while a cascade is in flight** → returns the current state. Reads are atomic per row; the cascade is a sequence of single-row writes, so a read may see a partial cascade. Acceptable for the chain-panel use case (operator refreshes; eventually consistent).

## 12) Given/When/Then acceptance criteria

### AC-1: Opt-in field round-trips through the API

- Given a study creation request with `config.auto_followup_depth=3`.
- When the operator POSTs `/api/v1/studies`.
- Then the response includes `config.auto_followup_depth=3` AND a subsequent `GET /api/v1/studies/{id}` returns the same value.
- Example values:
  - Request body: `{ "name": "test", "cluster_id": "...", "target": "products", "template_id": "...", "query_set_id": "...", "judgment_list_id": "...", "search_space": {...}, "objective": {"metric": "ndcg", "k": 10, "direction": "maximize"}, "config": {"max_trials": 50, "auto_followup_depth": 3} }`.
  - Expected: 201 with `config.auto_followup_depth=3` in the returned `StudyDetail`.

### AC-2: Depth-out-of-range returns 422

- Given `config.auto_followup_depth=6` (or `-1`).
- When the operator POSTs `/api/v1/studies`.
- Then the response is `422 AUTO_FOLLOWUP_DEPTH_OUT_OF_RANGE` with the canonical error envelope.
- Note: `0` is **valid** (worker-set terminal-state value per FR-1); only values outside `[0, 5]` (or non-`None` non-integers) trigger 422.

### AC-3: Lift gate enqueues child when winner beats first-decile

- Given a depth-2 parent study completes with `best_metric=0.42` and the first-decile of trials has a max `primary_metric=0.30`.
- When `enqueue_followup_study(parent_id)` runs.
- Then a child study is created with `config.auto_followup_depth=1` and inherited cluster/target/template/query_set/judgment_list/objective; `auto_followup_enqueued` is logged with `lift=0.12, epsilon=0.005`.

### AC-4: Lift gate skips when winner is within epsilon of first-decile

- Given a depth-2 parent study completes with `best_metric=0.302` and first-decile max `0.30`.
- When `enqueue_followup_study(parent_id)` runs.
- Then no child is created; `auto_followup_skipped_no_lift` is logged with `best_metric=0.302, first_decile_max=0.30, epsilon=0.005`.

### AC-5: Depth-exhausted halts chain

- Given a depth-1 parent completes successfully (lift passes).
- When `enqueue_followup_study(parent_id)` runs.
- Then a depth-0 child is created and **its own** `enqueue_followup_study` runs.
- And the depth-0 invocation logs `auto_followup_depth_exhausted` and creates no further child.

### AC-6: Parent-failed halts chain

- Given a depth-3 parent study transitions to `failed` via the 5-consecutive-failures circuit breaker.
- When the parent terminates.
- Then **no digest is enqueued** (verified at [`backend/workers/orchestrator.py:452`](../../../../backend/workers/orchestrator.py#L452) — digest enqueue is in `_stop()` after the `complete_study` transition, never on the `fail_study` path). Consequently, `enqueue_followup_study` is never invoked, and no chain member is created. **No telemetry fires in the normal failed-study flow.** The `auto_followup_skipped_parent_failed` event (FR-9 event #4) is a defensive backstop that fires only if `enqueue_followup_study` is manually invoked on a failed study (e.g., operator triggers via shell or a future feature that re-tries digest on failed studies).
- Acceptance test: integration test seeds a study with `status='failed'`, asserts no child row appears within 2s of seeding (negative test).

### AC-7: Budget-exhausted halts chain

- Given `peek_daily_total()` returns `0.85 * settings.openai_daily_budget_usd`.
- When `enqueue_followup_study(parent_id)` runs (gate passes).
- Then no child is created; `auto_followup_skipped_budget` is logged with `peek_total=85.0, budget=100.0, threshold_pct=80`.

### AC-8: Cancellation cascade hits all in-flight children

- Given a depth-3 chain where parent is `running`, child-1 is `running`, child-2 is `queued`.
- When operator POSTs `/api/v1/studies/{parent_id}/cancel?cascade=true`.
- Then parent transitions to `cancelled`, child-1 transitions to `cancelled`, child-2 transitions to `cancelled`; each emits `study_state_transition` + `auto_followup_cancelled_with_parent`.

### AC-9: Cancellation without cascade leaves children alone

- Given the same chain as AC-8.
- When operator POSTs `/api/v1/studies/{parent_id}/cancel?cascade=false`.
- Then parent transitions to `cancelled`; child-1 and child-2 keep their current status.

### AC-10: Chain panel renders all three sub-elements

- Given a study with `parent_study_id=P`, `config.auto_followup_depth=2`, and one child `C`.
- When operator visits `/studies/{id}`.
- Then the chain panel shows: a "Parent: P" link, "Remaining auto-follow-ups: 2", and a children table with one row for C.

### AC-11: Cancel modal default radio respects D-6

- Given a `running` study with `config.auto_followup_depth=3` (anticipated child OR active child).
- When operator clicks Cancel.
- Then the modal opens with the "Cancel parent + in-flight children" radio pre-selected.

### AC-12: Children endpoint returns empty list (not 404) for childless study

- Given a study with no children.
- When operator GETs `/api/v1/studies/{id}/children`.
- Then response is `200 { "data": [], "next_cursor": null }`.

### AC-13: Idempotent enqueue drops duplicate Arq deliveries

- Given a parent's `enqueue_followup_study` has already produced one child.
- When `enqueue_followup_study` is delivered a second time for the same parent (test simulates by directly invoking the worker function twice via the Arq job's underlying coroutine, bypassing `_job_id` queue-level dedup — exercises the layer-2 backstop).
- Then no second child is created; `auto_followup_enqueued_duplicate_dropped` is logged with `existing_child_ids` matching the first child.
- Note: queue-level dedup (`_job_id`) is the primary defense (verified separately in integration test: `enqueue_job` called twice for same parent → second call returns `None` per Arq's `_job_id` contract). AC-13 exercises the worker-level backstop.

## 13) Non-functional requirements

- **Performance:**
  - `enqueue_followup_study` p99 wall-clock < 500 ms (one parent load + one trial list + one budget peek + one create + one enqueue; all bounded queries).
  - `GET /studies/{id}/children` p99 < 100 ms (single indexed query on `parent_study_id`).
  - `cancel_study_with_chain_cascade` p99 < 2 s for depth-5 chain (5 sequential `cancel_study` calls; each ~200 ms).
- **Reliability:**
  - `enqueue_followup_study` is idempotent against duplicate Arq deliveries (FR/§9).
  - Cancellation cascade is idempotent (re-cancelling cancelled child is no-op).
- **Operability:**
  - 8 distinct structlog event_types (FR-9 authoritative catalog). Grep-friendly per existing convention.
  - No new metrics or alerts in MVP1 (no metrics infra). MVP2 brings Langfuse + SigNoz; the events catalog should map cleanly to span attributes.
- **Accessibility:**
  - Chain panel uses standard shadcn/ui Card primitive; inherits accessibility.
  - Cancel modal radio: keyboard navigable; labels associated via `<Label htmlFor=>`; radio group has accessible name.
  - Wizard depth selector: native `<select>` (no custom widget); inherits keyboard + screen-reader accessibility.

## 14) Test strategy requirements (spec-level)

### Unit (`backend/tests/unit/`)

- `backend/tests/unit/api/test_study_config_validation.py` — extend with cases for `auto_followup_depth ∈ {None, 0, 1, 5}` (valid — `0` is the worker-persisted terminal value per FR-1) and `{-1, 6, 5.5}` (invalid → ValidationError). **Note:** Pydantic v2 with default `model_config` coerces numeric strings (`'3'`) to int — so `'3'` is **valid** (parses to 3) and is NOT an invalid case. If we want stricter parsing, the spec would need to add `model_config = ConfigDict(strict=True)` to `StudyConfigSpec`, which is a wider change with cascading test impact across all other `int` fields in the model; out of scope for v1. Document this in the validator's docstring.
- `backend/tests/unit/domain/test_auto_followup.py` — NEW. Pure-function tests of `evaluate_chain_gate`:
  - Lift > epsilon → `enqueue`.
  - Lift ≤ epsilon → `skip_no_lift`.
  - `parent.status == 'failed'` → `skip_parent_failed`.
  - `config.auto_followup_depth == 0` → `skip_depth_exhausted`.
  - `len(complete_trials) < 10` → first-decile = first trial alone (boundary).
  - `len(complete_trials) == 0` → defensive skip (should not happen but tested).
- `backend/tests/unit/domain/test_search_space_narrow.py` — NEW (covers FR-4's extracted domain function). Parity test: existing agent-tool fixture → asserts byte-identical output after refactor.
- `backend/tests/unit/services/test_study_state.py` — extend with `cancel_study_with_chain_cascade` tests (mock `list_children_of_study`; assert each child's `cancel_study` called).

### Integration (`backend/tests/integration/`)

- `backend/tests/integration/test_auto_followup.py` — NEW. DB-backed (no engine needed):
  - Parent completes + lift-passing fixture → child row appears in DB with correct config + parent_study_id.
  - Budget peek > 80% → no child enqueued (mock `peek_daily_total`).
  - Parent `status='failed'` → no child enqueued.
  - Depth-3 chain: parent (depth=3) → child-1 (depth=2) → child-2 (depth=1) → child-3 (depth=0) → child-3's own enqueue logs `auto_followup_depth_exhausted` (stub `start_study` so child rows persist but don't run).
  - **Layer-2 idempotency:** re-invoke `enqueue_followup_study` worker function directly twice for same parent (bypasses Arq) → second invocation logs `auto_followup_enqueued_duplicate_dropped` and creates no second child.
  - **Layer-1 idempotency (Arq `_job_id` queue-level dedup):** call `arq_pool.enqueue_job("enqueue_followup_study", parent_id, _job_id=f"enqueue_followup_study:{parent_id}")` twice in rapid succession; assert second call returns `None` per Arq's `_job_id` contract — verifies the queue-level dedup path that the digest worker depends on.
- `backend/tests/integration/test_studies_api.py` — extend with cascade cases:
  - `POST /studies/{id}/cancel?cascade=true` → parent + children cancelled.
  - `POST /studies/{id}/cancel?cascade=false` → only parent cancelled.
  - `POST /studies/{id}/cancel?cascade=invalid` → 400 INVALID_CASCADE_PARAM.
- `backend/tests/integration/test_study_children_endpoint.py` — NEW. `GET /studies/{id}/children` returns empty / single / multiple.

### Contract (`backend/tests/contract/`)

- `backend/tests/contract/test_studies_api.py` — extend:
  - `config.auto_followup_depth` round-trips through POST → GET.
  - `GET /studies/{id}/children` response matches `StudyListResponse` shape.
  - 422 envelope for out-of-range depth matches the canonical error shape.
  - 400 envelope for invalid cascade matches the canonical error shape.

### E2E (`ui/tests/e2e/`)

- `ui/tests/e2e/auto-followup.spec.ts` — NEW. Real-backend (no `page.route()` mocking):
  - Wizard: select depth=2, submit, assert `config.auto_followup_depth=2` via API helper.
  - Detail page: navigate to a chain parent (seeded via API helper), assert chain panel renders with parent link + remaining-depth + children table.
  - Cancel modal: click Cancel on a chain parent, assert modal opens with "Cancel parent + in-flight children" radio pre-selected.

Per CLAUDE.md "E2E Testing Rules": no `page.route()` mocking. Tests use the real backend at `localhost:8000` and the seed-helper pattern established by `infra_e2e_seed_completed_study`.

## 15) Documentation update requirements

- `docs/01_architecture/optimization.md` — add a §"Auto-followup chains" subsection describing the chain trigger, gate, depth decrement, and budget short-circuit. Cross-link to the spec.
- `docs/01_architecture/ui-architecture.md` — extend §"Routes (MVP1)" entry for `/studies/[id]` to mention the chain panel render conditions. Add the 4 new glossary keys to the "Tooltips and contextual help" inventory.
- `docs/02_product/mvp1-user-stories.md` — add Story F.X "Operator chains studies overnight" under the studies-feature group.
- `docs/03_runbooks/` — NEW `docs/03_runbooks/auto-followup-debugging.md`: how to grep telemetry events for chain behavior; how to manually break a runaway chain; how to verify the budget peek is reading the right Redis key.
- `state.md` — update active-priorities + Alembic head note (no migration → Alembic head unchanged, but reference the merged PR).
- `CLAUDE.md` — add `auto_followup_*` event names to a future telemetry-catalog entry (when MVP2's `audit_log` lands; defer for now).

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. The opt-in is `auto_followup_depth = None` by default — every existing study is unaffected. No phased rollout needed.
- **Migration:** None. Existing column (`parent_study_id`) is re-used; new field (`auto_followup_depth`) lives in JSONB.
- **Operational readiness gates:**
  - All 13 acceptance criteria pass in CI.
  - Telemetry event names verified by grep (operator can find each event type).
  - Runbook merged (`docs/03_runbooks/auto-followup-debugging.md`).
- **Release gate:** Standard PR-gate per CLAUDE.md (lint + typecheck + tests + 80% coverage + CI green + Gemini review adjudicated + final GPT-5.5 review clean).

## 17) Traceability matrix

| FR ID | Acceptance Criteria | Planned stories (placeholder; impl-plan-gen will assign IDs) | Test files / suites | Docs to update |
|---|---|---|---|---|
| FR-1 (opt-in field) | AC-1, AC-2 | Story 1.x (StudyConfigSpec validator + JSONB round-trip) | `test_study_config_validation.py`, `test_studies_api.py` (contract) | `optimization.md` |
| FR-2 (lift gate) | AC-3, AC-4 | Story 2.x (`evaluate_chain_gate` domain function) | `test_auto_followup.py` (unit + integration) | `optimization.md`, `auto-followup-debugging.md` |
| FR-3 (worker) | AC-3, AC-5 | Story 2.x + 3.x (`enqueue_followup_study` Arq job) | `test_auto_followup.py` (integration) | `auto-followup-debugging.md` |
| FR-4 (domain narrow function) | AC-3 | Story 2.x (extract from agent tool) | `test_search_space_narrow.py` (parity) | (none — internal refactor) |
| FR-5 (config inheritance) | AC-3 | Story 3.x (`enqueue_followup_study` child build) | `test_auto_followup.py` (integration) | (covered in FR-3 docs) |
| FR-6 (budget gate) | AC-7 | Story 3.x | `test_auto_followup.py` (integration) | `auto-followup-debugging.md` |
| FR-7 (failure halting) | AC-6 | Story 2.x (gate function) | `test_auto_followup.py` (unit) | `auto-followup-debugging.md` |
| FR-8 (cascade cancel) | AC-8, AC-9, AC-11 | Story 5.x (service + endpoint) | `test_study_state.py`, `test_studies_api.py` (integration) | `optimization.md` |
| FR-9 (telemetry) | All ACs (events are observable side effects) | Story 3.x + 5.x (event emission) | All integration tests assert specific events | `auto-followup-debugging.md` |
| FR-10 (chain panel) | AC-10 | Story 6.x (children endpoint + panel component) | `study-detail.test.tsx`, `auto-followup.spec.ts` | `ui-architecture.md` |
| FR-11 (wizard selector) | AC-1, AC-11 | Story 7.x (Step 4 extension + 4 glossary keys) | `auto-followup.spec.ts` (E2E) | `ui-architecture.md` |
| FR-12 (ON DELETE locked) | (no AC — negative requirement) | (no story — decision-only) | (no test — covered by absence of migration) | (none) |

## 18) Definition of feature done

This feature is complete when:

- [ ] All 13 acceptance criteria (AC-1 through AC-13) pass in CI.
- [ ] All test layers (unit / integration / contract / E2E) are green.
- [ ] Documentation updates listed in §15 are merged.
- [ ] Operational gates from §16 are satisfied (runbook merged, telemetry verified).
- [ ] No open questions remain in §19 (all locked at spec time).

## 19) Open questions and decision log

### Open questions

**None.** All 6 idea-stage Open questions are locked in the Decision log below.

### Decision log

- **2026-05-23 — D-1 — ON DELETE on `studies.parent_study_id`: keep Postgres default NO ACTION.** Recommended default from preflight idea §1a. Rationale: studies are soft-deleted via `deleted_at` per CLAUDE.md "Database conventions"; the FK strictness is theoretical. No migration. Re-evaluate when hard-delete tooling lands.
- **2026-05-23 — D-2 — Worker calls the domain function, not the agent tool.** The narrowing math (`narrow_around_winner`) is extracted from `propose_search_space` (the agent tool) into `backend/app/domain/study/search_space_defaults.py`. Both surfaces (worker + agent tool) call the domain function. Rationale: agent tools require chat-agent context; the worker has none. Refactor lands in the same PR as the worker.
- **2026-05-23 — D-3 — Gate is lift-over-first-decile (FR-2a) until `feat_study_baseline_trial` ships.** Recommended default from preflight idea §3a. Rationale: `studies.baseline_metric` is currently always NULL. The first-decile-of-trials baseline is a valid implicit reference; switches to lift-over-baseline (FR-2b) via a one-line change when the dependency ships. Captured in `feat_study_baseline_trial`'s idea file as the consumer that will flip the path.
- **2026-05-23 — D-4 — Strict config inheritance from parent to child** (FR-5). Recommended default from preflight idea §4a. Rationale: operator set parent's config for a reason; changing parallelism or trial timeout for the child would surprise. Alternative (reset-to-default) rejected.
- **2026-05-23 — D-5 — Budget threshold at 80% of `OPENAI_DAILY_BUDGET_USD`.** Recommended default from preflight idea §5a. Rationale: leaves 20% headroom for the chain member's digest call + any in-flight chat-agent activity.
- **2026-05-23 — D-6 — Cancel modal default radio: "Cancel parent + in-flight children".** Recommended default from preflight idea §6. Rationale: consistent with cancel being the explicit user action; surprises an operator less than a cascade that doesn't happen.
- **2026-05-23 — D-7 — Depth cap at 5 (Pydantic validator).** Recommended default from preflight idea §2. Rationale: depth=5 × `max_trials=200` (Standard preset default from `chore_study_default_stop_conditions`) = 1,000 trials per chain — meaningful overnight compounding without 10× budget surprise.
- **2026-05-23 — D-8 — Children endpoint is separate from `StudyDetail`.** Avoids ballooning `StudyDetail` to include child arrays. Trade-off: 2 API calls instead of 1 for the chain panel. Worth it — keeps the detail-page shape lean and the children fetch cancellable independently.
- **2026-05-23 — D-9 — `?cascade=` query param defaults to `true` on cancel.** Backwards-compatibility note: any existing operator-tooling that POSTs `/cancel` without `?cascade=` gets the new cascade behavior. Caller inventory (verified 2026-05-23):
  - **Frontend** — [`ui/src/lib/api/studies.ts:117`](../../../../ui/src/lib/api/studies.ts#L117) POSTs `/api/v1/studies/{id}/cancel` with empty body. After this feature, this call resolves to `cascade=true` by default. The new modal flow from FR-11 wraps this call — when the modal is in use, the call passes the operator-selected `?cascade=<radio_value>`. For standalone studies (no chain), the cascade is a no-op (`list_children_of_study` returns `[]`); no observable behavior change. **Action:** update [`ui/src/lib/api/studies.ts`](../../../../ui/src/lib/api/studies.ts) to accept an optional `cascade?: boolean` arg; default `true` to match server default.
  - **Agent tool** — [`backend/app/agent/tools/studies/cancel_study.py:34`](../../../../backend/app/agent/tools/studies/cancel_study.py#L34) calls `study_state.cancel_study(ctx.db, str(args.study_id))` DIRECTLY (no HTTP, no `cancel_study_with_chain_cascade`). The agent tool is unaffected by the cascade default — it never cascades in v1. Rationale: an LLM-initiated cancel should be the most conservative path (cancel only what was named). Adding cascade to the agent tool is a future feature if operators want it.
  - **No other callers.** Grep `/api/v1/studies/.+/cancel` across the repo returned only the two above + tests.
  This is the right default for parent studies with children; for standalone studies (no chain), the cascade has no children to find and is effectively a no-op. No existing automation should break.
- **2026-05-23 — D-10 — FR-9 authoritative catalog finalized at 8 events** (after cycle-2 GPT-5.5 review). The 8 events include the 6 core paths plus 2 defensive backstops: `auto_followup_skipped_parent_missing` (hard-delete race, MVP1-impossible) and `auto_followup_enqueued_duplicate_dropped` (Arq `_job_id` layer-2 backstop). The discrepancy between earlier "6 events" + "7 events" mentions in §3 + §13 was reconciled in this cycle.
- **2026-05-23 — D-11 — Two-layer idempotency (Arq `_job_id` + worker backstop)** locked over the cycle-2-flagged race in the original single-layer check-then-create design. Layer 1 (Arq `_job_id`) closes the only realistic duplicate-delivery vector for MVP1 (worker restart between Redis ack and DB commit). Layer 2 (worker-level `list_children_of_study` re-check) catches the longer-tail case of `_job_id` key expiry. A Postgres advisory lock for full serialization is deferred as `chore_auto_followup_parent_advisory_lock` (a future hardening; not needed for MVP1's lack of autonomous re-triggering).
- **2026-05-23 — D-12 — Digest trigger fires when `auto_followup_depth is not None` (including 0)** so depth-0 leaves emit `auto_followup_depth_exhausted` from their own `enqueue_followup_study` invocation. Initially the spec gated the trigger at `> 0`, which would have made AC-5 impossible to satisfy (cycle-2 GPT-5.5 finding #1).
- **2026-05-23 — D-13 — `list_children_of_study` returns direct children only** (not transitive descendants). Chain panel walks lineage one hop per navigation. A `list_descendants_of_study` for single-page chain view is deferred as a future feature if operators ask. Reconciles the cycle-2 finding that the example showed depth-2 + depth-1 under a single parent (inconsistent with direct-child semantics).
