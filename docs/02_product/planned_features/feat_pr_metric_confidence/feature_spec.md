# Feature Specification — PR Metric Confidence

**Date:** 2026-05-21
**Status:** Draft (pending GPT-5.5 cross-model review)
**Owners:** soundminds.ai
**Related docs:**
- Input brief: [`idea.md`](idea.md)
- Sibling shipped: [`feat_digest_proposal`](../../../00_overview/implemented_features/2026_05_11_feat_digest_proposal/feature_spec.md), [`feat_github_pr_worker`](../../../00_overview/implemented_features/2026_05_12_feat_github_pr_worker/feature_spec.md), [`feat_studies_ui`](../../../00_overview/implemented_features/2026_05_12_feat_studies_ui/feature_spec.md), [`feat_llm_judgments`](../../../00_overview/implemented_features/2026_05_11_feat_llm_judgments/feature_spec.md)
- Architecture: [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md), [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md), [`docs/01_architecture/optimization.md`](../../../01_architecture/optimization.md), [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md), [`docs/01_architecture/llm-orchestration.md`](../../../01_architecture/llm-orchestration.md)

---

## 1) Purpose

- **Problem:** RelyLoop's value-delivery surface is the Pull Request opened against the operator's central search-config repo. Today the PR body carries two scalar point estimates (`baseline → achieved` for the primary metric) — no confidence band, no per-query breakdown, no runner-up gap, no convergence signal. An approver opening the PR cannot tell whether a +0.13 NDCG lift is a robust plateau (10 trials within 0.005 of the winner) or a sharp peak that 50% probability won't reproduce. The per-query metric data that `pytrec_eval` already computes inside `score()` is dropped on the floor at the persistence boundary — every trial, on every study.
- **Outcome:** Approvers reading a study-backed PR see a "## Confidence" section directly between the existing "## Metric delta" and "## Config diff" sections. The section carries: (a) a bootstrap-based 95% CI on the headline metric, (b) a per-query histogram (improved / unchanged / regressed counts), (c) up to 5 named regressor queries with their `query_text` and metric deltas, (d) a runner-up gap classification (robust plateau vs sharp peak), (e) a late-trial noise floor (1σ over the last 20% of complete trials), and (f) a convergence call-out (early-and-held / late-rising / noisy). The same data renders as a `<ConfidencePanel>` on `/studies/[id]` so operators inspect confidence before opening the PR. The digest narrative LLM prompt gains structured `<confidence>` and `<per_query_outcomes>` XML blocks so the narrative opens with a confidence-framed sentence ("NDCG@10 +0.13 (95% CI 0.78–0.89, N=20 queries) — robust plateau, 2 named regressors").
- **Non-goal:** This feature does NOT add a baseline-trial run to the orchestrator (the `studies.baseline_metric` column exists but is never populated by current production code — see §2 audit). Per-query delta uses **runner-up #2** as the comparison reference in MVP1; a separate deferred Phase 2 adds true baseline-trial computation. This feature also does NOT add holdout-set discipline, Wilcoxon paired tests, or multiple-comparison correction — those are explicit out-of-scope per §3 and the input brief.

## 2) Current state audit

### Existing implementations

| File / component | What it does | Differences from expectation |
|---|---|---|
| [`backend/workers/git_pr.py:488-528`](../../../../backend/workers/git_pr.py#L488) `_render_pr_body_study_backed` | Renders the PR body markdown — sections: `## Metric delta`, `## Config diff`, `## Suggested follow-ups`, `## Parameter importance` | Verified against codebase. No `## Confidence` section exists today. The new section inserts between `## Metric delta` and `## Config diff`. |
| [`backend/app/eval/scoring.py:153-194`](../../../../backend/app/eval/scoring.py#L153) `score()` | Returns `ScoreResult` typed as `{"aggregate": {metric: mean_value}, "per_query": {qid: {metric_name: float}}}` | Verified. The `per_query` dict is computed by `pytrec_eval.RelevanceEvaluator.evaluate()` and reduced to the mean for `aggregate`. |
| [`backend/workers/trials.py:433-446`](../../../../backend/workers/trials.py#L433) `run_trial` worker | Persists `trials.metrics = scored["aggregate"]` via `repo.create_trial(...)` after pytrec_eval runs | Verified. `scored["per_query"]` is discarded at this line — never persisted to the database. This is the central gap the feature closes. |
| [`backend/app/db/models/trial.py`](../../../../backend/app/db/models/trial.py) `Trial` ORM | Columns: `id`, `study_id` (FK CASCADE), `optuna_trial_number`, `params` JSONB, `primary_metric` Float (denormalized for `(study_id, primary_metric DESC NULLS LAST)` index), `metrics` JSONB (not-null), `duration_ms`, `status` (CHECK `complete\|failed\|pruned`), `error`, `started_at`, `ended_at` | Verified. Adding `per_query_metrics JSONB NULL` is the only schema change required for Tier B. |
| [`backend/app/db/models/study.py:76`](../../../../backend/app/db/models/study.py#L76) `studies.baseline_metric` | Float, nullable, **never written in production code** — the docstring says "populated by the orchestrator (Phase 2)" but `grep -rn "baseline_metric *=" backend/workers/ backend/app/services/` confirms zero write sites; only test fixtures and the digest worker's read path reference it | **Material finding.** Phase 2's orchestrator work (running a non-Optuna baseline trial) was deferred and never landed. `study.baseline_metric` is always `None` in production. The MVP1 PR body shows `baseline=None → achieved=X` with no `delta_pct`. This means **per-query "regression vs baseline" cannot be computed without first implementing baseline-trial persistence**. The spec resolves this by comparing winner vs **runner-up #2 per-query**, not winner vs baseline. Per-query baseline comparison is deferred to a Phase 2 follow-up tracked in [`phase2_idea.md`](phase2_idea.md). |
| [`backend/workers/digest.py:296-308`](../../../../backend/workers/digest.py#L296) `_compute_metric_delta` | Builds `{primary_metric_key: {baseline, achieved, delta_pct}}` for the proposal's `metric_delta` JSONB column; reads `study.baseline_metric` (always None) and `study.best_metric` | Verified. In MVP1 the wire shape is `{"baseline": null, "achieved": 0.84, "delta_pct": null}`. PR body renders this as `ndcg@10: None → 0.84` — an existing UX gap. This feature improves the situation by adding the confidence band (computed without a baseline). True baseline numbers are unlocked by Phase 2. |
| [`backend/app/db/models/digest.py`](../../../../backend/app/db/models/digest.py) `Digest` ORM | Columns: `id`, `study_id` (UNIQUE FK), `narrative` Text, `parameter_importance` JSONB, `recommended_config` JSONB, `suggested_followups` ARRAY(Text), `generated_by`, `generated_at` | Verified. No schema change to `digests` — the new `confidence` data lives on `StudyDetail` (computed at-read-time from trials), NOT on `digests`. Rationale: the per-query data on trials is the source of truth; recomputing on read is O(N_trials) which is sub-millisecond for MVP1 study sizes (≤1000 trials × ≤100 queries = 100K floats = <500KB JSONB). |
| [`prompts/digest_narrative.user.jinja`](../../../../prompts/digest_narrative.user.jinja) | Jinja2 template with XML blocks `<study>`, `<baseline_vs_achieved>`, `<top_trials>`, `<parameter_importance>`, `<recommended_config>`, `<dropped_template_params>`, `<degraded_mode>` | Verified. New blocks `<confidence>` and `<per_query_outcomes>` slot in after `<baseline_vs_achieved>` (before `<top_trials>`). |
| [`prompts/digest_narrative.system.md`](../../../../prompts/digest_narrative.system.md) | System prompt; line 29-30 says "`narrative` — a markdown string (~200–600 words). Open with the headline metric delta. Then explain *why* …" | Verified. The "Open with the headline metric delta" sentence is mid-bullet inside the `narrative` field instruction; the spec edits it precisely (see FR-6). |
| [`backend/app/api/v1/schemas.py:613-637`](../../../../backend/app/api/v1/schemas.py#L613) `StudyDetail` Pydantic | 17 fields including `baseline_metric`, `best_metric`, `best_trial_id`, `trials_summary` (TrialsSummaryShape) | Verified. The spec adds one optional field: `confidence: ConfidenceShape \| None`. Old clients ignoring the field continue to work — Pydantic on the wire is permissive. |
| [`backend/app/api/v1/studies.py:118-142`](../../../../backend/app/api/v1/studies.py#L118) `_detail()` | Builds `StudyDetail` from a `Study` ORM row | Verified. Spec adds a call to a new domain helper `compute_study_confidence(db, study)` that returns `ConfidenceShape \| None` and is invoked from `_detail()`. |
| [`ui/src/app/studies/[id]/page.tsx`](../../../../ui/src/app/studies/[id]/page.tsx) | 114 lines — header card + trials table; no digest/confidence panels rendered | Verified clean canvas. The new `<ConfidencePanel>` mounts between the header card and the trials table (above the digest panel when it renders for completed studies). |

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| (none) | (no URLs change) | — |

Confidence data lives within the existing `/studies/[id]` route — no new pages, no redirects, no removed routes.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/integration/test_studies_api.py` | Asserts on `StudyDetail` shape from `GET /api/v1/studies/{id}` | ≥1 | Add assertion that `confidence` key is present (may be `null`). Existing assertions on other fields remain unchanged. |
| `backend/tests/contract/test_studies_openapi.py` (or equivalent OpenAPI shape lock) | Asserts the OpenAPI schema for the `StudyDetail` response | 1 | Verify the new `confidence` field appears in the schema with the correct type. |
| `backend/tests/integration/test_digest_zero_trials.py` + `test_digest_zero_trials_with_openai_unconfigured.py` | Digest worker with `best_metric=None` | 2 | No code change required; assert that `confidence` is `None` on the resulting StudyDetail (degraded path). |
| `backend/tests/unit/workers/test_digest_prompt_render.py` | Renders `digest_narrative.user.jinja` with sample inputs | 1 | Extend the fixture with `confidence` + `per_query_outcomes` keys. Add a new test that the rendered prompt contains `<confidence>` block when data is non-None and omits it when None. |
| `backend/tests/integration/test_proposals_api.py` (if exists for `_render_pr_body_study_backed`) | PR body output | TBD | Add cases that assert `## Confidence` section presence/absence + named regressor inclusion. |
| `ui/src/__tests__/components/studies/` | Existing study-detail component tests | TBD | Add new `confidence-panel.test.tsx` (component test against TanStack `useStudy` mock returning `confidence` payload). |
| `ui/tests/e2e/studies.spec.ts` | Existing real-backend Playwright spec | 1 | Add 1-2 assertions that the ConfidencePanel renders when a seeded completed study has `per_query_metrics` populated. |

Total: ~6 existing test files modified, 2 new test files added.

### Existing behaviors affected by scope change

- **PR body section ordering.** Current: `Metric delta → Config diff → Suggested follow-ups → Parameter importance`. New: `Metric delta → **Confidence** → Config diff → Suggested follow-ups → Parameter importance`. Decision needed: **no** — insertion is additive, ordering is unambiguous.
- **`trials.metrics` JSONB shape.** Currently `{ndcg@10: 0.84, map: 0.62, ...}` (aggregate). The new column `trials.per_query_metrics` is a sibling, NOT a replacement. No change to existing column's shape. Decision needed: **no**.
- **Digest narrative LLM prompt.** Current opening guidance: "Open with the headline metric delta." New: "Open with the headline metric delta + a one-sentence confidence framing (CI, per-query outcome counts, worst-regressed query name when any)." Decision needed: **no** — spec locks the exact replacement string in FR-6.
- **Run-trial worker latency.** Adding `per_query_metrics` write is a single dict copy (≤100 queries × 5 metrics = ~500 floats) — sub-millisecond per trial. No measurable impact. Decision needed: **no**.
- **`StudyDetail` API response size.** Adds an optional `confidence` field — when present, +~2-5 KB for a typical 20-query study. No change to the list endpoint's `StudySummary`. Decision needed: **no**.

---

## 3) Scope

### In scope

- **One Alembic migration** `0015_trials_per_query_metrics`: adds `trials.per_query_metrics JSONB NULL`. Reversible downgrade. No backfill — old trials stay `NULL` and analytics gracefully no-show their per-query surfaces.
- **One-line worker change** in `backend/workers/trials.py` to persist `per_query_metrics=scored["per_query"]` alongside `metrics=scored["aggregate"]`.
- **New domain module** `backend/app/domain/study/confidence.py` with pure-Python helpers (bootstrap CI, runner-up gap classification, late-trial noise floor, convergence regime detection, per-query outcome classification, top regressors).
- **New Pydantic shape** `ConfidenceShape` exposed as an optional field on `StudyDetail` (`backend/app/api/v1/schemas.py`).
- **Read-side enrichment** in `backend/app/api/v1/studies.py::_detail()` that invokes `compute_study_confidence(db, study)` and attaches the result to the response.
- **PR-body section** `## Confidence` inserted into `_render_pr_body_study_backed()` in `backend/workers/git_pr.py`. Section renders whenever `confidence is not None` (i.e., the winner trial row exists). Each sub-block (CI line, per-query block, regressor list, runner-up gap, late-trial 1σ, convergence) is gated on its specific sub-field being non-null — so old studies (winner has `per_query_metrics IS NULL`) get the section with the aggregate signals but no per-query content; running studies (`best_trial_id IS NULL`) get no section at all.
- **Digest narrative prompt update**: `prompts/digest_narrative.user.jinja` gains `<confidence>` + `<per_query_outcomes>` XML blocks; `prompts/digest_narrative.system.md` opening guidance edited per FR-6.
- **Study-detail UI**: new `<ConfidencePanel>` React component at `ui/src/components/studies/confidence-panel.tsx`, mounted from `ui/src/app/studies/[id]/page.tsx` between the header card and the trials table.
- **Test coverage** at unit (domain helpers), integration (DB-backed StudyDetail enrichment + digest worker prompt rendering), contract (OpenAPI shape lock for `ConfidenceShape`), and E2E (Playwright real-backend renders the panel) layers.

### Out of scope

- **Baseline-trial computation in the orchestrator.** Implementing the deferred Phase 2 work (run a single non-Optuna trial before Optuna starts, persist its per-query metrics on the study row, populate `study.baseline_metric` and `study.baseline_trial_id`). Tracked in [`phase2_idea.md`](phase2_idea.md). This feature treats the comparison reference as **runner-up #2 per-query** in MVP1; Phase 2 swaps in baseline comparison.
- **Holdout-set discipline (80/20 split).** Per input brief §"Out of scope for v1": MVP1 judgment-set sizes are too small for a meaningful split, and enterprise relevance engineers often optimize on a curated set. Revisit at MVP4 when multi-tenant judgments routinely exceed 100 queries.
- **Wilcoxon signed-rank paired test.** Theoretically correct but for typical 10–20 query studies the test rarely returns significant even when the lift is real. Defer until operators ask for it.
- **Multiple-comparison correction across the 1000-trial budget.** Most-correct statistical concern but the hardest to surface for non-statisticians. Defer; revisit if approver feedback flags inflated metrics.
- **Sparkline / chart rendering for convergence trajectory.** Phase 1 renders convergence as a textual call-out only ("Best metric found at trial 387 of 1000; held thereafter"). A future enhancement can add a Recharts line chart.
- **Confidence on rejected proposals.** The "## Confidence" section appears in study-backed proposal PR bodies only. Manually-authored proposals (`proposal.study_id IS NULL`) skip the section.
- **Per-query metrics for old studies.** No backfill — `trials.per_query_metrics IS NULL` for trials predating the migration. The `confidence` field on `StudyDetail` returns `null` (degraded path) for those studies.

### API convention check

Verified against [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md):

- **Endpoint prefix convention:** `/api/v1/<resource>`. No new endpoints — this feature extends the existing `GET /api/v1/studies/{id}` response shape with an optional `confidence` field.
- **Router namespace:** [`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py) — existing router file gets one new domain-helper call inside `_detail()`.
- **HTTP methods for CRUD:** N/A (this feature is read-only at the API layer; the write side is the `run_trial` worker which is not a router-mediated path).
- **Non-auth error envelope shape:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` per `api-conventions.md`. No new error codes — `compute_study_confidence` returns `None` on any degraded path rather than raising.
- **Auth error shape:** N/A in MVP1–MVP3 (single-tenant, no auth surface).

### Phase boundaries

- **Phase 1 (this spec — MVP1, ships immediately):** Per-query persistence + read-side enrichment + PR body section + digest narrative prompt + ConfidencePanel. Comparison reference for regressors is **runner-up #2 per-query**.
- **Phase 2 (deferred — tracked in [`phase2_idea.md`](phase2_idea.md)):** Orchestrator runs a non-Optuna baseline trial first; `studies.baseline_trial_id` (new column, denormalized FK) points to that trial; per-query regressor comparison switches to **baseline** when available, with `runner_up` as the fallback when `studies.baseline_trial_id IS NULL`. Phase 2 is purely additive on top of Phase 1 — no migration to undo, no API contract break.

## 4) Product principles and constraints

- **Approver trust is the value-delivery surface.** Every signal in the "## Confidence" section must answer a concrete approver question ("is this fragile?", "is the lift bigger than noise?", "does it break specific queries?"). Cosmetic statistics with no actionable meaning are out.
- **Graceful degradation over hard failure.** Any missing input (study has no trials, no per_query_metrics, no runner-up, no completed trials in the late-trial window) produces a null-or-suppressed surface, NEVER an error envelope or LLM degraded-mode trigger. The API ships an optional `confidence` field so old clients keep working.
- **Source of truth is the trial row.** `trials.per_query_metrics` is computed deterministically from `pytrec_eval` and never overwritten. Analytics recompute on read.
- **No `digests` schema change.** The digest worker is downstream of the trials data; per-query analytics belong on the trial side. The digest narrative reads pre-computed confidence and injects it into the LLM prompt.
- **Floating LLM model names forbidden** (CLAUDE.md Absolute Rule #8). The digest worker already reads `Settings.openai_model` for the narrative LLM call — no new LLM call in this feature.
- **Conventional Commits.** All commits on this branch follow the `feat(pr-metric-confidence): ...` / `infra(migrate): ...` etc. format (CLAUDE.md Absolute Rule #7).
- **`/healthz` performance budget.** N/A — this feature touches no health probes.
- **scipy + numpy availability.** Verified — `.venv/lib/python3.13/site-packages/{scipy,numpy}` are installed via pytrec_eval transitive dep. Bootstrap CI uses `numpy.random.choice` + `numpy.percentile` (no scipy.stats dependency to keep the lift surface minimal and avoid optional-dep import-time risk).

### Anti-patterns

- **Do not** compute `confidence` from the `digests.parameter_importance` field — that's Optuna's parameter-importance, not metric-confidence. The two are unrelated; mixing them produces nonsense.
- **Do not** add a `digests.confidence` JSONB column. The trial row carries the canonical per-query data; recomputing on `StudyDetail` read is correct because (a) study sizes are bounded (≤1000 trials), (b) keeps the source-of-truth single, (c) avoids a migration on `digests` and a write-path retrofit.
- **Do not** cache the confidence computation at the API layer. The data is small (~500KB worst case) and the study-detail endpoint is not on a hot path; caching adds complexity without measurable benefit.
- **Do not** compare winner against the simple mean of all trials per-query (would dilute the regressor signal when the winner is a clear leader). Use **runner-up #2 per-query** explicitly — see FR-3 for rationale.
- **Do not** use scipy.stats.bootstrap. Numpy-only bootstrap is ~5 lines, faster for our sample sizes, and avoids dragging scipy's optional bias-correction machinery into the runtime path. Numpy is already a transitive dep via pytrec_eval; scipy is not required.
- **Do not** add multi-tenant filtering. RelyLoop is single-tenant through MVP3 (CLAUDE.md activates-at-MVP4 rule).
- **Do not** persist confidence to `digests` even partially (e.g., "just the regressor names"). The digest worker can read the per-query data from trials at digest-generation time; persisting it twice introduces drift.
- **Do not** wrap the bootstrap loop in `try`/`except Exception:` — if numpy raises, the underlying data is wrong and we want the trace to surface. Suppress to `None` only on documented degraded paths (N(queries) < 5; no per_query_metrics; no winner trial).
- **Do not** raise an error code if `compute_study_confidence` returns None. The `null` value on the wire is the contract.

## 5) Assumptions and dependencies

- **Dependency: `feat_digest_proposal`** (PR #41, merged 2026-05-11). Required for the digest narrative prompt update path. Status: implemented. Risk if missing: feature still ships (the PR body and StudyDetail enrichment are independent of the digest), but the LLM narrative wouldn't pick up the confidence framing.
- **Dependency: `feat_github_pr_worker`** (PR #45, merged 2026-05-12). Required for `_render_pr_body_study_backed` to exist as the modification point. Status: implemented. Risk if missing: N/A — already shipped.
- **Dependency: `feat_studies_ui`** (PR #50, merged 2026-05-12). Required for `/studies/[id]` route to host the `<ConfidencePanel>`. Status: implemented. Risk if missing: N/A.
- **Dependency: `feat_llm_judgments`** (PR #35, merged 2026-05-11). Provides the judgment data that `pytrec_eval` consumes; without per-query judgments there's no per-query metrics. Status: implemented. Risk if missing: per_query_metrics would be empty dicts (still safe — analytics gracefully no-show).
- **Dependency: numpy 1.x** (transitive via `pytrec-eval>=0.5` in `pyproject.toml`). Required for bootstrap resampling. Verified present at `.venv/lib/python3.13/site-packages/numpy/__init__.py`. Risk if missing: feature can't ship — but numpy is already required by pytrec_eval which already ships.
- **Dependency: Alembic head at `0014_clusters_target_filter`** (current as of 2026-05-21). Required so the new `0015_trials_per_query_metrics` migration applies cleanly. Status: confirmed via [`state.md`](../../../../state.md). Risk if missing: migration round-trip fails — but `0014` is already merged.
- **No new external services.** No new OpenAI calls (the existing digest worker's LLM call is the only LLM hop). No new GitHub API calls. No new ES/OS adapter calls.

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (per umbrella spec §6). Reads the ConfidencePanel before opening a PR; reads the "## Confidence" section in the PR body to decide whether to merge.
- **Secondary actor:** Approver (subset of relevance engineers with merge rights on the central search-config repo). Reads the "## Confidence" section in the PR body as the primary input to their merge decision.
- **Tertiary actor:** Viewer (PMs, exec stakeholders, read-only). Sees the ConfidencePanel on /studies/[id] but does not act on it directly in MVP1.
- **Role model:** N/A — RelyLoop MVP1 is single-tenant + no auth (per [`docs/01_architecture/tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md)).
- **Permission boundaries:** No tool-side enforcement in MVP1. Approval is delegated to the operator's central search-config repo's branch protection rules.

### Authorization

N/A — single-tenant install, no auth surface (MVP1).

### Audit events

N/A — `audit_log` lands at MVP2 per [`docs/01_architecture/data-model.md` §"Forthcoming: audit_log"](../../../01_architecture/data-model.md). This feature touches no tenant-visible state mutations beyond the existing `run_trial` worker INSERT (which is internal-system, never tenant-direct). At MVP2 when `audit_log` ships, the `run_trial` worker's `INSERT INTO trials` already gets covered by whatever audit-log integration the MVP2 epic adds for the workers layer — no per-feature instrumentation needed here.

## 7) Functional requirements

### FR-1: Persist per-query metrics on every successful trial

- Requirement:
  - The system **MUST** add a nullable JSONB column `trials.per_query_metrics` via Alembic migration `0015_trials_per_query_metrics`. The migration has a working `downgrade()` and round-trips cleanly (`alembic upgrade head && alembic downgrade -1 && alembic upgrade head`).
  - The `run_trial` worker at [`backend/workers/trials.py:433-446`](../../../../backend/workers/trials.py#L433) **MUST** persist `per_query_metrics=scored["per_query"]` as part of `repo.create_trial(...)` whenever `status='complete'`.
  - The worker **MUST NOT** write `per_query_metrics` on the `status='failed'` path at [`trials.py:500`](../../../../backend/workers/trials.py#L500) (where `metrics={}` is the current behavior) — `per_query_metrics` stays `NULL` for failed trials.
  - Old trials predating the migration **MUST** retain `per_query_metrics IS NULL` (no backfill).
- Notes: The shape mirrors `ScoreResult.per_query` from [`scoring.py:47`](../../../../backend/app/eval/scoring.py#L47) — `{qid: {metric_name: float}}`. `metric_name` keys are the **user-facing names produced by `score()`'s wire→user remap loop at [`scoring.py:180-185`](../../../../backend/app/eval/scoring.py#L180): exactly `ndcg`, `map`, `precision`, `recall`, `mrr`** (NOT the pytrec_eval wire-name forms like `ndcg_cut.10`, NOT the abbreviated `p`). The threshold-table lookup in FR-4a uses these same five names so wire/threshold/UI/test keys are byte-equal.

### FR-2: Compute confidence signals from persisted trial data

- Requirement:
  - The system **MUST** provide an async domain function `async def compute_study_confidence(db: AsyncSession, study: Study) -> ConfidenceShape | None` in `backend/app/domain/study/confidence.py`. Callers (`_detail()`, digest worker, PR worker — see FR-5d) MUST `await` the call.
  - The function **MUST** return `None` when any of: (a) `study.best_trial_id IS NULL`, (b) the winner trial **row** is missing (cascade-delete race per [`digest.py:615-625`](../../../../backend/workers/digest.py#L615)), (c) `len(complete_trials) < 1`. NOTE: A winner row that exists but has `per_query_metrics IS NULL` does NOT trigger whole-object `None` — instead the function returns a **partial** `ConfidenceShape` per FR-7 (aggregate signals like `runner_up_gap`, `late_trial_stddev`, and `convergence` still compute from `primary_metric` + `optuna_trial_number`).
  - The function **MUST** fetch data via four small queries (NOT by loading all trials with `per_query_metrics` into memory):
    1. The **winner trial row** (`SELECT ... FROM trials WHERE id = study.best_trial_id`) — includes its `per_query_metrics`.
    2. The **runner-up trial row** (`SELECT ... FROM trials WHERE study_id = ? AND status = 'complete' AND id != ? ORDER BY primary_metric DESC NULLS LAST LIMIT 1` — uses the existing `trials_study_metric` index) — includes its `per_query_metrics`.
    3. A **trial summary list** (`SELECT primary_metric, optuna_trial_number FROM trials WHERE study_id = ? AND status = 'complete' ORDER BY optuna_trial_number ASC`) — projects ONLY the two columns needed for `runner_up_gap.classification`, `late_trial_stddev`, and `convergence`. No `per_query_metrics` payload in this query.
    4. A **regressor query-text fetch** (`SELECT id, query_text FROM queries WHERE id = ANY(:regressor_qids)`) — issued AFTER step 1+2 have produced the candidate regressor `query_id` list (at most 5 ids). Skipped entirely when no regressors are produced.
  - Total wire load is bounded at ~30KB regardless of trial count (two `per_query_metrics` rows ≤ ~5KB each, the summary list at N×(8+8) bytes ≈ 16KB for 1000 trials, plus ≤ 5 query rows).
  - When data is sufficient, the function **MUST** populate every sub-field independently; partial population is the contract. Specifically:
    - `headline` is always populated when `study.best_metric IS NOT NULL`.
    - `ci_95` is populated when the winner has ≥5 per-query datapoints; suppressed (`None`) below 5.
    - `runner_up_gap` is populated when there are ≥2 complete trials; suppressed below 2.
    - `late_trial_stddev` is populated when `len(complete_trials) ≥ 10`; suppressed below 10 (sample too small).
    - `convergence` is populated when there are ≥3 complete trials; suppressed below 3.
    - `per_query_outcomes` is populated when there are ≥2 complete trials AND BOTH the winner trial AND the runner-up #2 trial (the comparison reference locked in FR-3) have `per_query_metrics IS NOT NULL`; suppressed when any of those three conditions fails. This is stricter than "any other complete trial" — the comparison MUST be against the runner-up specifically, per FR-3 + the four-query data-loading contract above.
- Notes: Computation is O(N_queries) for the per-query analytics (only the winner and runner-up rows carry `per_query_metrics`); O(N_trials) for the summary-list pass (two-column projection only). No caching; results recomputed on every `GET /api/v1/studies/{id}` call. The four-query read pattern above is the canonical implementation contract — the function is forbidden from issuing a "give me every complete trial's per_query_metrics" query.

### FR-3: Define winner-vs-comparison reference for per-query deltas

- Requirement:
  - In MVP1 (this spec, Phase 1), the comparison reference for per-query deltas **MUST** be the **runner-up #2 trial** — defined as the complete trial with the second-highest `primary_metric` (sorted descending, `NULLS LAST`).
  - When fewer than 2 complete trials exist OR the runner-up has `per_query_metrics IS NULL`, the per-query comparison **MUST** be suppressed (`per_query_outcomes = None`). The aggregate `runner_up_gap` still computes if the runner-up has a `primary_metric` value (see FR-7) — only the per-query side is suppressed.
  - The wire shape **MUST** include a `comparison_against` field whose value **in MVP1 Phase 1 is unconditionally `"runner_up"`**. The `"baseline"` value is reserved for Phase 2 and MUST NOT be emitted by Phase 1 code (no conditional `if study.baseline_trial_id ...` branching in Phase 1 — that column doesn't exist).
- Notes: Runner-up is chosen over "mean of all trials" because the latter dilutes the regressor signal when the winner is a clear leader (the winner is far ahead per-query on most queries, so deltas vs mean are universally positive and obscure the actual regressors). Comparing against runner-up #2 surfaces only queries where the winner sacrifices accuracy that some other tried config achieved. Phase 2 (tracked in [`phase2_idea.md`](phase2_idea.md)) adds `studies.baseline_trial_id` AND switches the conditional in `compute_study_confidence` to emit `"baseline"` when that column is non-null — both changes in one Phase 2 migration + code update.

### FR-4: Lock thresholds and methods for each confidence signal

- Requirement:
  - **Bootstrap CI:** percentile method, N=1000 resamples, 95% interval. Implemented with `numpy.random.default_rng(seed=42).choice(per_query_values, size=(1000, len(per_query_values)), replace=True).mean(axis=1)` → `numpy.percentile(means, [2.5, 97.5])`. The seed is fixed for determinism (an approver re-reading the PR sees identical numbers; reproducibility wins over per-call randomness for this surface).
  - **Runner-up gap classification:** "robust_plateau" when the top-`min(10, num_complete_trials)` trials by `primary_metric` are all within 0.005 of the winner; "sharp_peak" otherwise. The 0.005 threshold is locked. When `num_complete_trials < 2` the classification is suppressed (`runner_up_gap = None` per FR-2's threshold list); for 2 ≤ N < 10 the rule degrades gracefully — e.g., 3 trials with values [0.84, 0.838, 0.836] all within 0.005 → `robust_plateau`.
  - **Late-trial noise floor:** computed as `numpy.std(primary_metric for trial in last_n_complete_trials, ddof=1)` (sample stddev). `last_n_complete_trials = trials sorted by optuna_trial_number ascending, take the last max(5, int(len(complete)*0.2)) entries`. Suppressed (returned as `None`) when `len(complete) < 10`.
  - **Convergence regime:** "early_held" when the winner's `optuna_trial_number ≤ 0.5 * max_optuna_trial_number` AND **at least one trial in the last 25% of trial numbers has `primary_metric` within 0.005 of the winner** (i.e., late exploration found similar plateau configs — the optimizer "held" the region); "late_rising" when the winner's `optuna_trial_number ≥ 0.9 * max_optuna_trial_number`; "noisy" otherwise. Note: "no improvement after the winner" is tautological because the winner is by-definition the global best, so the rule uses "late trial within 0.005 of winner" as the observable signal that the optimizer found multiple near-equivalents.
  - **Regressor threshold (per-metric):** absolute delta cutoff. Locked in FR-4a's metric-threshold table.

#### FR-4a — Regressor threshold table (locked, enumerated)

For "is this query regressed?" the comparison is `winner.per_query_metrics[qid][metric] - runner_up.per_query_metrics[qid][metric]`. A query is "regressed" when this delta is **less than the negative of the threshold** for the active metric:

| Metric | Threshold (absolute delta) |
|---|---|
| `ndcg` | 0.01 |
| `precision` | 0.01 |
| `recall` | 0.01 |
| `map` | 0.02 |
| `mrr` | 0.02 |

A query is "improved" when delta > +threshold; "unchanged" when |delta| ≤ threshold. The metric used for the threshold lookup is `study.objective['metric']` (always one of the wire-enum values in [`ui/src/lib/enums.ts`](../../../../ui/src/lib/enums.ts) and [`backend/app/api/v1/schemas.py:521`](../../../../backend/app/api/v1/schemas.py#L521) `_K_REQUIRED_METRICS` family).

### FR-5: Surface confidence in three places

- Requirement:
  - **(5a) `StudyDetail` API response.** The system **MUST** add `confidence: ConfidenceShape | None` to the [`StudyDetail`](../../../../backend/app/api/v1/schemas.py#L613) Pydantic model. The field **MUST** be populated via `compute_study_confidence(db, row)` in [`_detail()`](../../../../backend/app/api/v1/studies.py#L118). When the function returns `None`, the JSON wire value is `null`.
  - **(5b) PR body `## Confidence` section.** The system **MUST** insert a new section between `## Metric delta` and `## Config diff` in [`_render_pr_body_study_backed`](../../../../backend/workers/git_pr.py#L488). The section renders the headline + CI line, the per-query outcome counts (when available), the named regressor block (when any), the runner-up gap classification, the late-trial noise floor, and the convergence call-out. If `confidence is None`, the entire section is omitted.
  - **(5c) `<ConfidencePanel>` on `/studies/[id]`.** The system **MUST** add a new component at [`ui/src/components/studies/confidence-panel.tsx`](../../../../ui/src/components/studies/confidence-panel.tsx) mounted from [`ui/src/app/studies/[id]/page.tsx`](../../../../ui/src/app/studies/[id]/page.tsx) between the study header card and the existing trials table. The panel renders headline + CI band (when `ci_95` non-null), per-query outcome chips (when `per_query_outcomes` non-null), the named regressor table (when `per_query_outcomes.regressed > 0`; up to 5 rows), the runner-up gap label (when `runner_up_gap` non-null), the late-trial 1σ value (when `late_trial_stddev` non-null), and the convergence call-out (when `convergence` non-null). If the entire `confidence` field is `null`, the panel renders nothing. There is NO "view full per-query breakdown" disclosure in Phase 1 — the inline 5-row regressor table is the only per-query surface (consistent with the bounded payload from FR-2 query 4).
  - **(5d) PR worker data plumbing.** The system **MUST** modify the PR-opening worker code path (the `open_pr` Arq job and any other call site that invokes `_render_pr_body_study_backed`) so that BEFORE rendering it (a) loads the Study row via `repo.get_study(db, proposal.study_id)`, (b) `await`s `compute_study_confidence(db, study)`, (c) passes the resulting `ConfidenceShape | None` into `_render_pr_body_study_backed(..., confidence=...)` as a new keyword argument. The renderer reads `confidence` and emits the `## Confidence` section per FR-5b. An integration test against the real PR worker path (NOT just the pure renderer) covers AC-11 end-to-end.
- Notes: All four surfaces (StudyDetail, PR body, ConfidencePanel, digest prompt) consume the same source-of-truth `ConfidenceShape` Pydantic model. There is no UI-only or PR-body-only data — every signal is computable from the same domain helper. The PR worker re-runs the computation rather than reading `StudyDetail` JSON to keep the worker independent of the HTTP layer.

### FR-6: Update the digest narrative LLM prompt

- Requirement:
  - The system **MUST** add two new XML blocks to [`prompts/digest_narrative.user.jinja`](../../../../prompts/digest_narrative.user.jinja), inserted after the existing `</baseline_vs_achieved>` block:

    ```jinja2
    {% if confidence %}<confidence>
    {% if confidence.ci_95 %}ci_low: {{ confidence.ci_95.low }}
    ci_high: {{ confidence.ci_95.high }}
    {% endif %}n_queries: {{ confidence.headline.n_queries }}
    {% if confidence.runner_up_gap %}runner_up_gap: {{ confidence.runner_up_gap.value }} ({{ confidence.runner_up_gap.classification or 'unclassified' }})
    {% endif %}{% if confidence.late_trial_stddev %}late_trial_stddev: {{ confidence.late_trial_stddev.value }}
    {% endif %}{% if confidence.convergence %}convergence: {{ confidence.convergence.regime }} (best at trial {{ confidence.convergence.best_at_trial }} of {{ confidence.convergence.total_trials }})
    {% endif %}</confidence>

    {% endif %}{% if confidence and confidence.per_query_outcomes %}<per_query_outcomes>
    improved: {{ confidence.per_query_outcomes.improved }}
    unchanged: {{ confidence.per_query_outcomes.unchanged }}
    regressed: {{ confidence.per_query_outcomes.regressed }}
    comparison_against: {{ confidence.per_query_outcomes.comparison_against }}
    {% for r in confidence.per_query_outcomes.top_regressors %}- {{ r.query_text }}: {{ r.winner_score }} → {{ r.comparison_score }} ({{ r.delta }})
    {% endfor %}</per_query_outcomes>

    {% endif %}
    ```

    The template consumes the same nested `ConfidenceShape` exposed on `StudyDetail` (§8.3) — no flat DTO adapter. The digest worker passes the `confidence` dict directly into `render_digest_user_prompt(...)`'s new `confidence: dict | None` kwarg; the jinja `{% if %}` guards handle every degraded combination from FR-7.
  - The system **MUST** edit [`prompts/digest_narrative.system.md`](../../../../prompts/digest_narrative.system.md) line 29-30 from:
    > `narrative` — a markdown string (~200–600 words). Open with the headline metric delta. Then explain *why* the recommendation works…

    to:
    > `narrative` — a markdown string (~200–600 words). Open with the headline metric delta, immediately followed by a one-sentence confidence framing that mentions the CI band (when `<confidence>` is present), the per-query outcome counts (when `<per_query_outcomes>` is present), and the worst-regressed query by name (when `<per_query_outcomes>` has regressors). Then explain *why* the recommendation works…
  - The system prompt's XML-block list (lines 13-25) **MUST** be extended to document blocks 8 (`<confidence>`) and 9 (`<per_query_outcomes>`) and their conditional-inclusion semantics.
  - The system **MUST** update [`backend/app/llm/digest_prompt.py:67`](../../../../backend/app/llm/digest_prompt.py#L67) `render_digest_user_prompt` to accept ONE new optional kwarg `confidence: dict | None = None` (a single object — `per_query_outcomes` is nested INSIDE `confidence` per the `ConfidenceShape` contract in §8.3, not a sibling). The digest worker `backend/workers/digest.py` awaits `compute_study_confidence(db, study)` and passes the result via `ConfidenceShape.model_dump()` into the prompt-render call.
- Notes: The system prompt edit is precise — the existing string `"Open with the headline metric delta."` is replaced by the longer string. The prompt rendering is exercised by [`backend/tests/unit/workers/test_digest_prompt_render.py`](../../../../backend/tests/unit/workers/test_digest_prompt_render.py) which adds new fixtures for the with/without-confidence paths.

### FR-7: Graceful degradation paths

- Requirement:
  - When `study.best_trial_id IS NULL` (study not yet complete): the API returns `confidence: null` (the **entire** ConfidenceShape is None). The PR body section is omitted. The ConfidencePanel renders nothing. The digest worker passes `confidence=None` so both jinja blocks are skipped.
  - When the winner trial has `per_query_metrics IS NULL` (e.g., trial predates the `0015` migration): `ci_95`, `headline.n_queries`, and `per_query_outcomes` are all `null`. The rest of `ConfidenceShape` (`runner_up_gap`, `late_trial_stddev`, `convergence`) **still computes** because those signals depend only on `primary_metric` + `optuna_trial_number`, not on per-query data. Headline `value` is still populated from `study.best_metric`.
  - When fewer than 5 queries have per-query data on the winner: `ci_95 = null` only; per-query outcomes still compute if the runner-up also has per-query data (no minimum-query gate on outcomes).
  - When fewer than 10 complete trials: `late_trial_stddev = null` only.
  - When fewer than 3 complete trials: `convergence = null` only.
  - When fewer than 2 complete trials: `runner_up_gap = null` AND `per_query_outcomes = null`.
  - When ≥ 2 complete trials but the runner-up has `per_query_metrics IS NULL`: `runner_up_gap` still computes (uses only `primary_metric`); `per_query_outcomes = null` only.
  - When numpy raises (should never happen with valid float inputs): the exception propagates and `_detail()` returns 500 — this is a programming error, not a degraded path. (No bare `except Exception:`.)
- Notes: Each degraded sub-field is independent. Tests cover each combination explicitly (see §14).

## 8) API and data contract baseline

### 8.1 Endpoint surface

This feature does NOT add new endpoints. It extends one existing endpoint's response shape.

| Method | Path | Purpose | Change |
|---|---|---|---|
| `GET` | `/api/v1/studies/{study_id}` | Read study detail | **MODIFIED**: adds optional `confidence` field to the response (`ConfidenceShape \| None`). |

### 8.2 Contract rules

- Existing `StudyDetail` shape per [`schemas.py:613`](../../../../backend/app/api/v1/schemas.py#L613) is preserved.
- The new `confidence` field is `Optional[ConfidenceShape]` with default `None`.
- Old clients that don't deserialize `confidence` continue to work.
- The OpenAPI schema is shape-locked via the existing `studies` contract test family (precedent: `test_clusters_target_filter_openapi.py`).

### 8.3 Response examples

**Success — completed study with full confidence data:**

```json
{
  "id": "01931e4a-...",
  "name": "tune-product-title-boost-baseline",
  "cluster_id": "01931...",
  "target": "products",
  "template_id": "01931...",
  "query_set_id": "01931...",
  "judgment_list_id": "01931...",
  "search_space": {"params": {"title_boost": {"type": "float", "low": 0.5, "high": 10.0, "log": true}}},
  "objective": {"metric": "ndcg", "k": 10, "direction": "maximize"},
  "config": {"max_trials": 1000, "sampler": "tpe", "pruner": "median"},
  "status": "completed",
  "failed_reason": null,
  "optuna_study_name": "01931e4a-...",
  "parent_study_id": null,
  "baseline_metric": null,
  "best_metric": 0.840,
  "best_trial_id": "01931...",
  "created_at": "2026-05-21T07:23:52Z",
  "started_at": "2026-05-21T07:23:52Z",
  "completed_at": "2026-05-21T07:25:13Z",
  "trials_summary": {"total": 1000, "complete": 998, "failed": 2, "pruned": 0, "best_primary_metric": 0.840},
  "confidence": {
    "headline": {"metric": "ndcg", "value": 0.840, "k": 10, "n_queries": 20},
    "ci_95": {"low": 0.782, "high": 0.891, "method": "bootstrap_n1000", "n_samples": 20},
    "runner_up_gap": {"value": 0.005, "classification": "robust_plateau", "top10_within": 0.005, "runner_up_metric": 0.835},
    "late_trial_stddev": {"value": 0.018, "window_size": 200, "min_window_required": 10},
    "convergence": {"best_at_trial": 387, "total_trials": 1000, "regime": "early_held"},
    "per_query_outcomes": {
      "improved": 14,
      "unchanged": 4,
      "regressed": 2,
      "comparison_against": "runner_up",
      "top_regressors": [
        {"query_id": "01931...", "query_text": "shipping policy", "winner_score": 0.41, "comparison_score": 0.92, "delta": -0.51},
        {"query_id": "01931...", "query_text": "wireless headphones", "winner_score": 0.71, "comparison_score": 0.85, "delta": -0.14}
      ]
    }
  }
}
```

**Success — completed study with partial confidence data (degraded — trials predate migration, so per_query_metrics is NULL but aggregate signals still compute):**

```json
{
  "id": "01931...",
  "name": "tune-product-title-boost-baseline-7ce587",
  "...": "...",
  "best_metric": 0.81,
  "best_trial_id": "01931...",
  "confidence": {
    "headline": {"metric": "ndcg", "value": 0.81, "k": 10, "n_queries": null},
    "ci_95": null,
    "runner_up_gap": {"value": 0.05, "classification": "sharp_peak", "top10_within": 0.04, "runner_up_metric": 0.76},
    "late_trial_stddev": {"value": 0.022, "window_size": 50, "min_window_required": 10},
    "convergence": {"best_at_trial": 412, "total_trials": 1000, "regime": "early_held"},
    "per_query_outcomes": null
  }
}
```

**Success — study in `running` state (no best_trial_id yet):**

```json
{
  "id": "01931...",
  "name": "tune-product-title-boost-baseline",
  "status": "running",
  "best_trial_id": null,
  "...": "...",
  "confidence": null
}
```

**Non-auth failure example — study not found (existing envelope; unchanged):**

```json
{
  "detail": {
    "error_code": "STUDY_NOT_FOUND",
    "message": "study 01931xxx not found",
    "retryable": false
  }
}
```

HTTP 404. No new error codes.

**Auth failure example:** N/A in MVP1–3 (no auth surface).

### 8.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `confidence.convergence.regime` | `early_held`, `late_rising`, `noisy` | New `ConfidenceShape` Pydantic `Literal[...]` in [`backend/app/api/v1/schemas.py`](../../../../backend/app/api/v1/schemas.py); domain helper at `backend/app/domain/study/confidence.py::classify_convergence_regime()` | `<ConfidencePanel>` regime badge (`ui/src/components/studies/confidence-panel.tsx`); add wire-value alias in [`ui/src/lib/enums.ts`](../../../../ui/src/lib/enums.ts) `CONVERGENCE_REGIME_VALUES` |
| `confidence.runner_up_gap.classification` | `robust_plateau`, `sharp_peak` | New `Literal[...]` in `ConfidenceShape`; domain helper `classify_runner_up_gap()` | `<ConfidencePanel>` runner-up gap label |
| `confidence.per_query_outcomes.comparison_against` | `runner_up` (MVP1 — the only emitted value in Phase 1) | New `Literal["runner_up", "baseline"]` in `ConfidenceShape`; in MVP1 Phase 1 the helper unconditionally emits `"runner_up"` (the `"baseline"` value is reserved for Phase 2 and Phase 1 code MUST NOT branch on `study.baseline_trial_id` — that column does not exist yet) | `<ConfidencePanel>` "vs runner-up" label; PR body wording |
| `confidence.ci_95.method` | `bootstrap_n1000` (only value in MVP1; future MVP2 may add `wilson` or others) | New `Literal[...]` in `ConfidenceShape`; constant in `confidence.py` | Documentation in tooltip only; no user-visible select |
| `confidence.headline.metric` | `ndcg`, `map`, `precision`, `recall`, `mrr` | [`backend/app/api/v1/schemas.py:214`](../../../../backend/app/api/v1/schemas.py#L214) `ObjectiveMetric = Literal["ndcg", "map", "precision", "recall", "mrr"]` (canonical wire-enum source) | Read from existing `OBJECTIVE_METRIC_VALUES` in [`ui/src/lib/enums.ts:68`](../../../../ui/src/lib/enums.ts#L68) — no new array. |

**Rules:**
- The 3 new `Literal[...]` value sets above MUST be added to `ui/src/lib/enums.ts` as `CONVERGENCE_REGIME_VALUES`, `RUNNER_UP_CLASSIFICATION_VALUES`, `COMPARISON_AGAINST_VALUES`, with source-of-truth comments per the project's enumerated-value-contract discipline (see CLAUDE.md §"Enumerated Value Contract Discipline").
- `confidence.ci_95.method` is internal; the frontend treats it as opaque (only the `bootstrap_n1000` value exists in MVP1).
- All other fields in `ConfidenceShape` (counts, scalars, query_ids, query_texts) are free-form data, not enumerated.

### 8.5 Error code catalog

No new error codes introduced.

## 9) Data model and state transitions

### New / modified entities

**Modified table: `trials`**

- Add `per_query_metrics` (`JSONB`, **nullable**, no default) — per-query pytrec_eval scores for this trial. Shape: `{query_id: {metric_name: float}}` matching `ScoreResult.per_query` from [`scoring.py:47`](../../../../backend/app/eval/scoring.py#L47). NULL for trials predating the migration AND for trials with `status='failed'` (worker writes NULL on failure paths). No index — the column is read O(1) via `WHERE id = ?` lookups on the winner / runner-up trial rows.

**No other table changes.** The new `ConfidenceShape` Pydantic model is API-layer only and not persisted (recomputed on read).

> **RELYLOOP MVP1–MVP3 reminder:** no `tenant_id` column added; this feature stays single-tenant.

### Required invariants

- **INV-1:** `trials.per_query_metrics IS NULL OR jsonb_typeof(trials.per_query_metrics) = 'object'`. Enforced by a **DB-level CHECK constraint** added in the same migration (`CHECK (per_query_metrics IS NULL OR jsonb_typeof(per_query_metrics) = 'object')`, named `trials_per_query_metrics_object_check`). DB enforcement is the right layer because the write path is the Arq `run_trial` worker — not a Pydantic-validated HTTP request — so application-level Pydantic guards would not fire.
- **INV-2:** When `trials.status = 'failed'`, `trials.per_query_metrics IS NULL`. Enforced by the worker write path (FR-1 explicitly states the failed-path skip — `repo.create_trial(...)` is called with `per_query_metrics=None` on the failure branch). Verified by integration test covering AC-2.
- **INV-3:** When `trials.status = 'complete'` AND the trial was created post-migration AND `pytrec_eval` returned non-empty `per_query`, `trials.per_query_metrics IS NOT NULL`. Application-level invariant — verified by integration test that runs a real trial and asserts persistence (AC-1).
- **INV-4:** `compute_study_confidence(db, study)` returns `None` OR a valid `ConfidenceShape` — never raises (except for un-recoverable programming errors like ImportError). Application-level invariant — verified by unit tests covering every degraded-path branch.

### State transitions

No new state machines. The existing `trials.status ∈ {complete, failed, pruned}` and `studies.status ∈ {queued, running, completed, cancelled, failed}` are unchanged.

### Idempotency / replay behavior

- The `run_trial` worker's INSERT is already idempotent on `(study_id, optuna_trial_number)` per [`infra_optuna_eval/feature_spec.md` §11](../../../00_overview/implemented_features/2026_05_10_infra_optuna_eval/feature_spec.md). Adding `per_query_metrics` to the same INSERT doesn't change idempotency semantics.
- `compute_study_confidence` is pure and deterministic given a fixed seed (numpy RNG seed = 42 per FR-4). Re-reading the same study returns identical confidence values, byte-for-byte.

## 10) Security, privacy, and compliance

- **Threats:**
  - **T1:** Information leak via query_text in the PR body's named-regressor block. If a tenant's query_set contains sensitive terms (e.g., proprietary product codes), those terms now appear in the public PR body the operator's central config repo receives. Mitigation: the PR body has *always* been visible to whoever can see the config repo; this feature does not change the trust boundary (config repo write access = read access to study metadata). Operator-side mitigation: scope the config repo's read-access to the same audience already trusted with judgment data.
  - **T2:** DoS via very-large `per_query_metrics` payloads. A judgment list with 10,000 queries × 5 metrics × 1000 trials = 50M floats = ~400MB JSONB. Mitigation: judgment lists are operator-curated; max sizes are bounded by the operator's own discipline (MVP1 has no per-tenant quota gate — single-tenant + no auth). At MVP4 when multi-tenant lands, the per-tenant judgment-set cap (TBD per MVP4 epic) caps this naturally.
  - **T3:** Bootstrap CI determinism failure. If the numpy seed isn't fixed, an approver re-reading the PR sees different CI numbers each time — undermines trust. Mitigation: FR-4 locks `seed=42`. Tested via the integration test that asserts byte-identical CI values across two consecutive reads.
- **Controls:** No new controls. Reuses the existing `pytrec_eval` data path (no new external service, no new credentials, no new secret).
- **Secrets / key handling:** N/A — no new secrets.
- **Auditability:** N/A in MVP1 (no `audit_log` yet). At MVP2, the `run_trial` worker's INSERT (which now writes `per_query_metrics`) gets audit-log coverage as part of the MVP2 epic's worker integration — no per-feature work needed here.
- **Data retention / deletion / export impact:** `trials.per_query_metrics` cascade-deletes with `trials` cascade-deletes with `studies`. No additional retention surface.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** The ConfidencePanel renders inside the existing `/studies/[id]` route — no new page or tab. Position: between the existing study header card and the existing trials table. The panel collapses to nothing when `confidence === null` so old / running studies keep the current visual rhythm.
- **Labeling taxonomy:**
  - Section heading: **"Confidence"** (capitalized, sentence case to match "Trials" elsewhere on the page).
  - CI band label: **"95% CI"** (industry standard, no expansion).
  - Per-query outcome chips: **"Improved"**, **"Unchanged"**, **"Regressed"** — green / grey / red badges using existing badge variants from the project's design system.
  - Runner-up gap classification: **"Robust plateau"** / **"Sharp peak"** — green / amber.
  - Convergence: **"Early-and-held"** / **"Late-rising"** / **"Noisy"** — green / amber / amber.
  - Comparison label: **"vs runner-up"** in MVP1; **"vs baseline"** when Phase 2 ships and `comparison_against === 'baseline'`.
- **Content hierarchy:** Top to bottom — (1) headline + CI band (primary, always-visible when `confidence` is non-null; CI line itself only renders when `ci_95` is non-null); (2) per-query outcome chips row (when `per_query_outcomes` non-null); (3) named regressors table (only when `per_query_outcomes.regressed > 0`, capped at 5 rows); (4) runner-up gap + late-trial 1σ + convergence (3 secondary callouts in a single row, each rendered only when their sub-field is non-null).
- **Progressive disclosure:** The 4-section panel renders ~150-200px tall by default. The named regressors table (up to 5 rows with `query_text`, `winner_score`, `comparison_score`, `delta`) renders inline only when `per_query_outcomes.regressed > 0`. No "View per-query breakdown" disclosure in Phase 1 — that would require fetching `query_text` for every compared query (potentially 100s of rows), which violates the bounded-payload promise of FR-2 query 4. Operators who want the full per-query view can drill into the winner trial's metrics via a future enhancement.
- **Relationship to existing pages:** Sits between the existing header card and trials table on `/studies/[id]`. The existing digest panel (when present, for completed studies with digests) renders below the trials table — unchanged.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---|---|---|---|
| "95% CI" label | "Bootstrap 95% confidence interval on the headline metric, computed from per-query scores via 1000 resamples with replacement." | hover | top |
| "Improved/Unchanged/Regressed" chips | "Queries where the winner's per-query metric differs from the runner-up's by more than the threshold (NDCG/P/R: 0.01; MAP/MRR: 0.02)." | hover | top |
| "Robust plateau" / "Sharp peak" label | "Robust: the top min(10, complete trials) are all within 0.005 of the winner — many near-equivalent configs. Sharp: at least one trial in that top set is farther than 0.005 below the winner — winner is isolated." | hover | top |
| "Late-trial 1σ" label | "Standard deviation of the primary metric over the last 20% of completed trials — the empirical noise floor." | hover | top |
| "Convergence: Early-and-held" / "Late-rising" / "Noisy" | "Early-and-held: best found in the first half AND at least one trial in the last 25% finished within 0.005 of the winner (plateau held). Late-rising: best found in the last 10% — more trials may help. Noisy: neither — no clear convergence pattern." | hover | top |
| "vs runner-up" / "vs baseline" label | "Reference for per-query comparison. Runner-up: the second-best trial. Baseline: a no-tuning trial run before Optuna starts (when available)." | hover | top |

Tooltip implementation reuses the existing [`InfoTooltip`](../../../../ui/src/components/common/info-tooltip.tsx) / [`HelpPopover`](../../../../ui/src/components/common/help-popover.tsx) primitives from `feat_contextual_help` — no new tooltip component required. Glossary entries (in [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts)) added for `confidence.ci_95`, `confidence.runner_up_gap`, `confidence.late_trial_stddev`, `confidence.convergence_regime`, `confidence.per_query_outcomes`, `confidence.comparison_against`.

### Primary flows

1. **Approver opens a study-backed PR in their config repo.** The PR body now has a `## Confidence` section between `## Metric delta` and `## Config diff`. They read: "NDCG@10 +0.13 (95% CI 0.78–0.89, N=20 queries). 14 improved · 4 unchanged · 2 regressed (vs runner-up). Queries that regressed: `shipping policy` (0.92 → 0.41), `wireless headphones` (0.85 → 0.71). Runner-up gap 0.005 (robust plateau). Late-trial 1σ = 0.018. Convergence: early-and-held (best at trial 387 of 1000)." They decide to merge or reject based on whether the named regressors are operator-important queries.
2. **Relevance engineer inspects a completed study on `/studies/[id]`.** ConfidencePanel renders above the trials table with the headline + CI band + outcome chips + (when regressors exist) the named regressors table showing up to 5 (query_text, winner_score, comparison_score, delta) rows. They identify which queries the winner sacrificed from the inline list, decide whether to broaden the search space and rerun. (A full per-query breakdown disclosure is explicitly out of scope for Phase 1 — see §3 Out of scope.)
3. **Relevance engineer creates a new study and opens its detail page while it's still running.** Status is "running", `best_trial_id` is null, ConfidencePanel renders nothing (clean visual; no empty-state shell). The trials table polls every 3s as usual.

### Edge / error flows

- **Old study (pre-`0015_trials_per_query_metrics` migration), completed.** Winner trial's `per_query_metrics IS NULL`. `compute_study_confidence` returns a **partial** `ConfidenceShape` with `ci_95`, `headline.n_queries`, and `per_query_outcomes` all null but aggregate signals (`runner_up_gap`, `late_trial_stddev`, `convergence`) populated — see AC-3. The PR body's `## Confidence` section shows only the aggregate signals; the digest narrative's `<confidence>` block similarly renders only non-null fields. No error envelope, no LLM degraded mode, no operator-visible failure.
- **Study with only 1 complete trial (others all failed).** Winner exists; runner-up doesn't. `runner_up_gap = None`, `per_query_outcomes = None`. CI band still computes (winner has per_query data). Headline + CI render; the rest is suppressed.
- **Study with 5 queries (small judgment list).** CI band reports `n_samples: 5` — at the lower bound. Late-trial 1σ requires ≥10 complete trials independently. Per-query outcomes work normally (the threshold is 2 trials, not 5 queries).
- **Study with 4 queries.** CI band suppressed (n < 5). Other fields proceed independently.
- **Study with `best_metric IS NULL` (zero-trials AC-2 path — see [`feat_digest_proposal`](../../../00_overview/implemented_features/2026_05_11_feat_digest_proposal/feature_spec.md)).** `confidence = None`.
- **OpenAI capability check failed (digest worker in degraded mode).** `<degraded_mode>` XML block fires per the existing prompt logic. The new `<confidence>` and `<per_query_outcomes>` blocks STILL render in degraded mode — they're plain data, not LLM-derived. The narrative LLM may not be called; if not, the data still exists in the PR body section (which is built independently from the LLM narrative).
- **Worker race: `study.best_trial_id` points at a deleted row.** Already handled by the existing `digest_best_trial_missing` defensive log at [`digest.py:615-625`](../../../../backend/workers/digest.py#L615). Our new code uses the same `repo.get_trial(db, trial_id)` (or equivalent) and on `None` returns `confidence = None` rather than raising. The existing log event continues to fire from the digest worker; we don't add a new log.

## 12) Given/When/Then acceptance criteria

### AC-1: Per-query metrics persist on every successful trial

- Given a study with `template_id` declaring `title_boost: 'float'`, a query set of 5 queries, and a judgment list with judgments for those queries
- When the orchestrator runs 5 Optuna trials and all 5 complete successfully
- Then `SELECT per_query_metrics FROM trials WHERE study_id = ?` returns 5 non-NULL JSONB rows, each shaped `{qid: {<user-facing-metric>: float, ...}}` where the keys are the user-facing metric tokens emitted by `backend.app.eval.scoring.score()` — i.e., the @-suffixed form for cutoff-aware metrics (`ndcg@10`, `map@10`, `precision@10`, `recall@10`) and bare names for cutoff-free metrics (`mrr`, plain `map`). Base names are constrained to `MetricCatalog` (`ndcg`, `map`, `precision`, `recall`, `mrr`).
- Example values:
  - Input: `study_id="01931..."`, `max_trials=5`, `objective={metric: "ndcg", k: 10}`, judgment list with `query_ids=["q1","q2","q3","q4","q5"]`
  - Expected: 5 rows, each with `per_query_metrics["q1"]["ndcg@10"]` populated as a float between 0.0 and 1.0

### AC-2: Failed trial does not write per_query_metrics

- Given a study where one trial's adapter call fails (simulated network error)
- When `run_trial` writes the failed trial row
- Then `SELECT per_query_metrics, status FROM trials WHERE id = ?` returns `(NULL, 'failed')`

### AC-3: Old studies degrade to a partial ConfidenceShape (aggregate-only)

- Given a completed study whose trials predate the `0015_trials_per_query_metrics` migration (all rows have `per_query_metrics IS NULL`) AND `study.best_trial_id` points at an existing winner trial row
- When `GET /api/v1/studies/{id}` is called
- Then the response body has `confidence != null` BUT with `confidence.ci_95 == null`, `confidence.per_query_outcomes == null`, and `confidence.headline.n_queries == null`
- And the aggregate sub-fields are populated: `confidence.headline.value` from `study.best_metric`, `confidence.runner_up_gap` (when ≥2 complete trials), `confidence.late_trial_stddev` (when ≥10 complete trials), `confidence.convergence` (when ≥3 complete trials)
- And the PR body contains a `## Confidence` section showing only the aggregate signals (no CI line, no per-query block)
- And the ConfidencePanel renders the aggregate signals (no CI band, no per-query chips, no regressor table)
- Counter-example: when `study.best_trial_id` resolves to a deleted row (or `best_trial_id IS NULL` because the study never completed), `confidence == null` (whole-object), the PR body has no `## Confidence` section, and the panel renders nothing — see AC-3a.

### AC-3a: Missing winner trial row → confidence is whole-object null

- Given a study where `best_trial_id IS NULL` (still running) OR `best_trial_id` points at a row that has been deleted
- When `GET /api/v1/studies/{id}` is called
- Then `confidence == null`
- And the PR body has no `## Confidence` section
- And the ConfidencePanel renders nothing

### AC-4: Bootstrap CI computed and reproducible

- Given a completed study with 20 queries and 100 complete trials, all with `per_query_metrics`
- When `GET /api/v1/studies/{id}` is called twice in succession
- Then both responses have identical `confidence.ci_95.low` and `confidence.ci_95.high` values (byte-equal — proves the seed=42 lock)
- And `confidence.ci_95.low < confidence.headline.value < confidence.ci_95.high`
- Example: headline=0.84, ci_95={low: 0.78, high: 0.89}

### AC-5: Runner-up gap classification

- Given a completed study whose top 10 trials by `primary_metric` are all within 0.005 of the winner (e.g., 0.840, 0.838, 0.836, ..., 0.835)
- When `GET /api/v1/studies/{id}` is called
- Then `confidence.runner_up_gap.classification == "robust_plateau"`
- And when the top 10 are NOT all within 0.005 (e.g., winner 0.840, second-best 0.760), `classification == "sharp_peak"`

### AC-6: Late-trial noise floor

- Given a completed study with 50 complete trials whose `primary_metric` values are known
- When `GET /api/v1/studies/{id}` is called
- Then `confidence.late_trial_stddev.value` equals `numpy.std(primary_metric[-10:], ddof=1)` where `window_size = max(5, int(50*0.2)) = 10`
- And `confidence.late_trial_stddev.window_size == 10`

### AC-7: Late-trial noise floor suppressed for small studies

- Given a completed study with 9 complete trials
- When `GET /api/v1/studies/{id}` is called
- Then `confidence.late_trial_stddev` is `null` (below 10-trial minimum)

### AC-8: Convergence regime — early-and-held

- Given a completed study where the winner's `optuna_trial_number = 200` out of `max_optuna_trial_number = 1000`, AND at least one trial with `optuna_trial_number > 750` has `primary_metric` within 0.005 of the winner (proving the late exploration found similar plateau configs)
- When `GET /api/v1/studies/{id}` is called
- Then `confidence.convergence.regime == "early_held"`
- And `confidence.convergence.best_at_trial == 200`
- And `confidence.convergence.total_trials == 1000`
- Counter-example for `noisy`: same study but no late trial within 0.005 of the winner → `regime == "noisy"`. Counter-example for `late_rising`: winner's `optuna_trial_number = 950` → `regime == "late_rising"`.

### AC-9: Convergence regime — late-rising

- Given a completed study where the winner's `optuna_trial_number = 950` out of `max_optuna_trial_number = 1000`
- When `GET /api/v1/studies/{id}` is called
- Then `confidence.convergence.regime == "late_rising"`

### AC-10: Per-query regressor naming with thresholded comparison

- Given a completed study with `objective={metric: "ndcg", k: 10}`, winner trial `per_query_metrics` keyed by user-facing token (`ndcg@10`), and runner-up #2 with per_query, where for `query_id="qA"` the winner's `per_query_metrics[qA]["ndcg@10"] == 0.41` and the runner-up's is `0.92` (delta=-0.51, below the -0.01 threshold for NDCG)
- And for `query_id="qB"` the winner's `ndcg@10` is `0.85` and the runner-up's is `0.85` (delta=0, within ±0.01 unchanged window)
- When `GET /api/v1/studies/{id}` is called
- Then `confidence.per_query_outcomes.top_regressors` contains a row for `query_id="qA"` with `query_text` joined from the queries table, `winner_score=0.41`, `comparison_score=0.92`, `delta=-0.51`
- And `confidence.per_query_outcomes.regressed == 1`
- And `confidence.per_query_outcomes.unchanged` includes `qB` in its count

### AC-11: PR body renders the Confidence section between Metric delta and Config diff

- Given a completed study with full confidence data and a study-backed proposal in `pending` status
- When `_render_pr_body_study_backed(...)` is called (e.g., by `POST /api/v1/proposals/{id}/open_pr` worker job)
- Then the rendered markdown body contains, in order: `# RelyLoop proposal`, `## Metric delta`, `## Confidence`, `## Config diff`, `## Suggested follow-ups`, `## Parameter importance`
- And the `## Confidence` section contains "95% CI", an "Queries:" line with improved/unchanged/regressed counts, and a "Queries that regressed:" sub-section listing up to 5 query_texts with their deltas

### AC-12: PR body omits the Confidence section when confidence=null

- Given a study-backed proposal whose study has `confidence == null` whole-object — e.g., `best_trial_id IS NULL` (still running, never completed) OR `best_trial_id` points to a deleted/missing trial row (cascade-delete race, see AC-3a)
- When `_render_pr_body_study_backed(...)` is called
- Then the rendered markdown body does NOT contain `## Confidence`
- And the section ordering becomes `Metric delta → Config diff → Suggested follow-ups → Parameter importance` (the existing pre-feature behavior)
- Counter-example: old studies with existing winner row but `per_query_metrics IS NULL` produce a partial `ConfidenceShape` (NOT whole-object null), so the PR body DOES contain `## Confidence` showing only aggregate signals — see AC-3.

### AC-13: ConfidencePanel renders against real backend

- Given the operator runs `make up`, seeds a completed study with `per_query_metrics`, and opens `/studies/[seeded_id]` in a browser
- When the page loads
- Then the ConfidencePanel renders between the study header card and the trials table
- And the panel contains the headline + CI band, the per-query outcome chips, the runner-up gap label, the late-trial 1σ, and the convergence call-out
- And the inline named-regressors table renders up to 5 rows when `per_query_outcomes.regressed > 0` (each row showing `query_text`, `winner_score`, `comparison_score`, `delta`)
- And there is NO "View per-query breakdown" disclosure (Phase 1 out of scope per §3)

### AC-14: Digest narrative LLM prompt includes confidence blocks

- Given a completed study with full confidence data and a triggered digest generation
- When the digest worker renders `digest_narrative.user.jinja` with the new `confidence` kwarg (a single dict — the serialized `ConfidenceShape.model_dump()` with `per_query_outcomes` nested inside per FR-6)
- Then the rendered prompt contains a `<confidence>` block with `ci_low`, `ci_high`, `n_queries`, `runner_up_gap`, `late_trial_stddev`, `convergence` fields (resolved from nested paths `confidence.ci_95.low`, `confidence.ci_95.high`, `confidence.headline.n_queries`, etc.)
- And contains a `<per_query_outcomes>` block (rendered from `confidence.per_query_outcomes`, NOT from a sibling kwarg) with `improved`, `unchanged`, `regressed`, `comparison_against` and a list of `top_regressors`
- And the rendered system prompt has the updated "Open with the headline metric delta, immediately followed by a one-sentence confidence framing…" line

### AC-15: Bootstrap CI suppressed when N(queries) < 5

- Given a completed study whose query set has 4 queries
- When `GET /api/v1/studies/{id}` is called
- Then `confidence.ci_95 == null`
- And the rest of the `confidence` object is populated normally (`headline`, `runner_up_gap`, etc., as data allows)

### AC-16: Per-query outcomes suppressed when no runner-up has per_query_metrics

- Given a completed study with only 1 complete trial (others failed)
- When `GET /api/v1/studies/{id}` is called
- Then `confidence.per_query_outcomes == null` AND `confidence.runner_up_gap == null`
- And `confidence.headline` and `confidence.ci_95` are populated normally (winner alone is enough)

### AC-17: Alembic migration round-trips cleanly

- Given the local Alembic head at `0014_clusters_target_filter` with seeded demo data
- When `alembic upgrade head` runs (applies `0015_trials_per_query_metrics`), then `alembic downgrade -1`, then `alembic upgrade head` again
- Then no errors are raised
- And after the downgrade, `trials.per_query_metrics` does NOT exist as a column
- And after the second upgrade, the column exists again with `IS NULL` for every row (preserved by being nullable)

## 13) Non-functional requirements

- **Performance:**
  - `GET /api/v1/studies/{id}` p95 latency increase from the new `compute_study_confidence` call: **< 100ms** for studies up to 1000 trials × 100 queries. The three-query read pattern (FR-2) keeps payload at ~30KB regardless of trial count. Bottleneck is the bootstrap loop (1000 resamples × N_queries numpy operations) which is ~5ms for N=100 queries. The wire load + DB roundtrip dominates the budget; the actual compute is ≪10ms. Measured by adding a perf assertion to the integration test (skip-by-default for CI, opt-in via env flag).
  - The `run_trial` worker latency increase from persisting `per_query_metrics`: **< 1ms** (single dict copy into the existing INSERT). No measurable hot-path impact.
- **Reliability:**
  - `compute_study_confidence` returns `None` on every degraded path; never raises (except for unrecoverable programming errors). Verified by unit tests covering each FR-7 degraded path.
  - PR-body rendering never raises on `confidence=None`; tested via AC-12 contract.
- **Operability:**
  - No new metrics, logs, or alerts. The existing `digest_best_trial_missing` log already covers the only race we share with the digest worker.
  - The runbook entry [`docs/03_runbooks/local-dev.md`](../../../../docs/03_runbooks/local-dev.md) doesn't need an update (no new operator action). A glossary update lands per FR-6.
- **Accessibility / usability:**
  - ConfidencePanel meets the existing WCAG 2.1 AA pattern used by the studies-detail page. Color-only signals (green/amber/red badges) are paired with text labels per the project's chip-discipline (`feat_contextual_help` precedent).
  - Tooltips trigger on hover AND keyboard focus (per `InfoTooltip` primitive's existing behavior).

## 14) Test strategy requirements (spec-level)

- **Unit tests (`backend/tests/unit/`):**
  - `backend/tests/unit/domain/study/test_confidence.py` — 20+ cases covering `bootstrap_ci` (deterministic seed, N>=5 / N<5 paths), `classify_runner_up_gap` (robust_plateau / sharp_peak), `compute_late_trial_stddev` (window size, ≥10 / <10 path), `classify_convergence_regime` (early_held / late_rising / noisy), `classify_query_outcomes` (improved/unchanged/regressed counts per FR-4a threshold table), `top_regressors` (sorted by absolute delta, capped at 5, query_text join), `compute_study_confidence` orchestrator function (every degraded path from FR-7).
  - `backend/tests/unit/workers/test_digest_prompt_render.py` (existing file extended) — 4+ new cases for prompt rendering with confidence / without confidence / with per_query_outcomes / partial population.
- **Integration tests (`backend/tests/integration/`):**
  - `backend/tests/integration/test_studies_api_confidence.py` (new file) — 8+ cases covering AC-3, AC-4, AC-5, AC-7, AC-10, AC-15, AC-16, with seeded studies via the existing `_digest_helpers.py` patterns extended to populate `per_query_metrics`.
  - `backend/tests/integration/test_trials_per_query_metrics_migration.py` (new file) — round-trip migration test (AC-17) following the pattern at `test_clusters_target_filter_migration.py`.
  - `backend/tests/integration/test_run_trial_per_query_persistence.py` (new file or extension of existing trials worker tests) — verify AC-1 + AC-2 by running a real trial against a stubbed adapter (the existing `infra_optuna_eval` integration-test scaffold).
- **Contract tests (`backend/tests/contract/`):**
  - Extend the existing `studies` OpenAPI shape-lock contract test (precedent: cluster target_filter contract test) to include the `confidence` field with its `ConfidenceShape` sub-shape.
  - Add a PR-body section contract test in the `git_pr` test family (or new file `test_pr_body_confidence_section.py`) covering AC-11 + AC-12.
- **E2E tests (`ui/tests/e2e/`):**
  - Extend `ui/tests/e2e/studies.spec.ts` with 2 new real-backend cases:
    - **AC-13** ConfidencePanel renders for a seeded completed study with full per-query data (uses an extended `_digest_helpers.py`-equivalent helper on the Playwright side OR uses an extended seedAcmeProductsChain pattern with per_query_metrics).
    - ConfidencePanel correctly omits itself for a study with `confidence=null`.
  - The Playwright spec MUST NOT use `page.route()` mocking — real backend per CLAUDE.md E2E policy. The seed helper either inserts a synthetic Trial row with hand-crafted `per_query_metrics` JSONB or runs a real `run_trial` invocation.

Total estimated new test count: ~35 cases across unit (20+), integration (10+), contract (3+), E2E (2).

## 15) Documentation update requirements

- **`docs/01_architecture/data-model.md`:** Add `trials.per_query_metrics` to the per-table column reference for `trials`. Note nullable + post-`0015` semantics. The `studies.baseline_metric` row already exists; add a forward-ref to Phase 2 that explains baseline_trial_id will be added at that time.
- **`docs/01_architecture/api-conventions.md`:** No update required (no convention change).
- **`docs/01_architecture/optimization.md`:** Add a brief "Confidence signals" subsection noting that the `score()` function's `per_query` dict is now persisted on `trials.per_query_metrics` (was previously discarded). Point at the new domain module.
- **`docs/02_product`:** No update required at the umbrella level. This spec is the planning artifact.
- **`docs/03_runbooks/local-dev.md`:** No update required (no new operator action).
- **`docs/04_security`:** No update required (no new security surface).
- **`docs/05_quality/testing.md`:** No update required (existing test-layer convention covers the new test files).
- **`docs/08_guides`:** No new walkthrough guide. The existing guide 06 ("Create and monitor a study") may benefit from a short addendum mentioning the ConfidencePanel — captured as a follow-up idea, NOT in-scope here.
- **`state.md`:** Update after PR merge with the new Alembic head (`0015_trials_per_query_metrics`) and feature ship status.
- **`CLAUDE.md`:** No update required (no new convention; the data-model.md update covers the new column reference).

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. RelyLoop is single-tenant + local-only through MVP3. The feature ships in a single PR.
- **Migration / backfill expectations:**
  - Migration `0015_trials_per_query_metrics` adds one nullable JSONB column. **No backfill.** Old trials retain `per_query_metrics IS NULL` and degrade gracefully via FR-7. New trials write the column on every successful trial.
  - Round-trip verified (`alembic upgrade head && alembic downgrade -1 && alembic upgrade head`) before merge per CLAUDE.md Absolute Rule #5.
  - Idempotency-guarded: the `add_column` and `drop_column` operations are inside `upgrade()` / `downgrade()` respectively; no conditional skip needed because the column doesn't exist pre-migration.
  - Revision ID length: `0015_trials_per_query_metrics` = 30 characters — under the 32-char `alembic_version` limit.
- **Operational readiness gates:**
  - `pre-commit run --all-files` passes locally.
  - `make test` (unit + integration + contract) passes locally with the new tests.
  - `cd ui && pnpm test` (vitest) passes.
  - `pnpm playwright test` passes locally with the 2 new E2E cases.
  - CI green on PR (lint + typecheck + tests + Docker build).
- **Release gate:** Merge to main triggers no staging deploy in MVP1 (no remote staging). Local stack rebuild via `make up` after pulling main picks up the migration; operators run `make migrate` to apply `0015` to their existing dev DBs.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks (TBD by `/impl-plan-gen`) | Test files / suites | Docs to update |
|---|---|---|---|---|
| FR-1 (per_query persistence) | AC-1, AC-2, AC-17 | Migration story; worker-change story | `tests/integration/test_trials_per_query_metrics_migration.py`, `tests/integration/test_run_trial_per_query_persistence.py` | `data-model.md`, `state.md` |
| FR-2 (compute helper) | AC-3, AC-4, AC-5, AC-7, AC-15, AC-16 | Domain-module story | `tests/unit/domain/study/test_confidence.py`, `tests/integration/test_studies_api_confidence.py` | `optimization.md` |
| FR-3 (winner-vs-runner-up) | AC-10, AC-16 | Domain-module story; folded into FR-2 | `tests/unit/domain/study/test_confidence.py` (top_regressors cases) | — |
| FR-4 + FR-4a (thresholds + methods) | AC-4, AC-5, AC-6, AC-8, AC-9, AC-10 | Domain-module story | `tests/unit/domain/study/test_confidence.py` (every threshold path) | — |
| FR-5a (StudyDetail enrichment) | AC-3, AC-4, AC-16 | API-extension story | `tests/integration/test_studies_api_confidence.py`, `tests/contract/test_studies_openapi.py` | — |
| FR-5b (PR body section) | AC-11, AC-12 | PR-renderer story | `tests/contract/test_pr_body_confidence_section.py` | — |
| FR-5c (ConfidencePanel UI) | AC-13 | Frontend story | `ui/tests/e2e/studies.spec.ts` + `ui/src/__tests__/components/studies/confidence-panel.test.tsx` | — |
| FR-6 (digest narrative prompt) | AC-14 | Prompt-update story | `tests/unit/workers/test_digest_prompt_render.py` extended | `optimization.md` |
| FR-7 (degraded paths) | AC-3, AC-7, AC-15, AC-16 | Folded into FR-2 | `tests/unit/domain/study/test_confidence.py` (every degraded branch) | — |

## 18) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-1 through AC-17) pass in CI.
- [ ] All test layers (unit / integration / contract / E2E) are green.
- [ ] Migration `0015_trials_per_query_metrics` is applied to the local stack and verified round-trip.
- [ ] The runbook entry doc-updates (per §15) are merged.
- [ ] Rollout gates from §16 are satisfied (CI green + local smoke).
- [ ] No open questions remain in §19.
- [ ] `phase2_idea.md` exists in the feature directory documenting the deferred baseline-trial work.

## 19) Open questions and decision log

### Open questions

None remaining after preflight + spec-gen. The seven open questions surfaced during preflight have all been resolved by locked decisions below.

### Decision log

- **2026-05-21 — D1 — API surface for ConfidencePanel data.** Locked: enrich `StudyDetail` with an optional `confidence: ConfidenceShape | None` field (Option A from preflight). Rejected: separate endpoint `GET /api/v1/studies/{id}/confidence` (premature surface area), client-side computation (would require sending all `trials.per_query_metrics` over the wire — wasteful and couples the frontend to schema). Rationale: matches how `digest` is already inlined into `StudyDetail`'s sibling fields; old clients ignore the field; single source of truth.

- **2026-05-21 — D2 — Regressor threshold semantics.** Locked: absolute delta with per-metric table — NDCG/precision/recall = 0.01, MAP/MRR = 0.02 (FR-4a). Rejected: relative-delta (ill-defined when comparison_score=0), per-tenant overrides (deferred until MVP4 + auth). Rationale: matches the calibration-kappa tier-threshold precedent and is large enough to filter noise on judgment lists with ≤20 queries.

- **2026-05-21 — D3 — Late-trial window definition.** Locked: `max(5, int(len(complete_trials)*0.2))` trials, with a minimum of 10 complete trials required to compute the noise floor at all (FR-7). Rejected: fixed window of 50 (too aggressive for small studies), last-by-time-rather-than-trial-number (Optuna trial number IS time-ordered by construction). Rationale: a 10-trial minimum is enough for a meaningful sample stddev; below that the value misleads more than it informs.

- **2026-05-21 — D4 — Bootstrap CI parameters.** Locked: percentile method, N=1000 resamples, 95% CI, suppressed when N(queries) < 5 (FR-4). RNG seed = 42 fixed for determinism (FR-4, AC-4). Rejected: bias-corrected percentile (BCa) method (small-sample bias correction is fragile under N<20; percentile is the textbook default for relevance-engineer-facing UI). Rationale: textbook 1000-resample percentile is the established default; fixed seed ensures approvers see stable numbers on PR re-reads.

- **2026-05-21 — D5 — Wide-plateau threshold.** Locked: "robust_plateau" when top-10 complete trials are ALL within 0.005 of the winner; "sharp_peak" otherwise (FR-4). Rejected: relative threshold (e.g., 0.5 * (winner − baseline)) because `baseline` is always None in MVP1 (see §2 audit). Rationale: 0.005 is below typical late-trial noise (1σ ~ 0.018 in our test data) so it's a tight definition of "plateau", and the test is unambiguously well-defined without baseline data.

- **2026-05-21 — D6 — Convergence-trial classification thresholds.** Locked: "early_held" when winner's optuna_trial_number ≤ 50% of max AND at least one trial in the last 25% of trial numbers has `primary_metric` within 0.005 of the winner (the observable "plateau held" signal — the original "no improvement after" framing was tautological because the winner is by definition the global best); "late_rising" when winner's optuna_trial_number ≥ 90% of max; "noisy" otherwise (FR-4). Rejected: more granular regimes (4+ buckets) because the UX value diminishes — 3 buckets answer "do I trust this winner?" cleanly. Rejected: "no improvement after" framing — tautological (GPT-5.5 cycle 1 F7). Rationale: 50/90 thresholds match the project's recurring "first half / last 10%" framings in the optimization docs; the within-0.005 late-window probe is the observable signal that the optimizer's late budget found near-equivalent configs.

- **2026-05-21 — D7 — Confidence-framing wording in digest narrative.** Locked: exact replacement string in FR-6 ("Open with the headline metric delta, immediately followed by a one-sentence confidence framing that mentions the CI band (when `<confidence>` is present), the per-query outcome counts (when `<per_query_outcomes>` is present), and the worst-regressed query by name (when `<per_query_outcomes>` has regressors). Then explain *why*…"). Rejected: free-form LLM prompt that just receives the data without a wording instruction (would produce inconsistent narrative openings across studies). Rationale: the exact replacement is short, observable in `system.md`, and testable via the `test_digest_prompt_render` unit test.

- **2026-05-21 — D8 — Baseline-trial computation deferred to Phase 2.** Locked: this feature ships per-query analytics against runner-up #2 (FR-3). The orchestrator's deferred "non-Optuna baseline trial" work moves to a separate Phase 2 spec tracked in `phase2_idea.md`. Phase 2 adds `studies.baseline_trial_id` (column), modifies the orchestrator to run a baseline trial first, and switches `confidence.per_query_outcomes.comparison_against` to "baseline" when available. Phase 2 is purely additive — no migration to undo, no API contract break. Rationale: the orchestrator change is a meaningful surface (new code path, new failure modes, new tests) that deserves its own spec cycle; bundling it here would inflate scope without proportional product value.

- **2026-05-21 — D9 — No new `digests` schema column.** Locked: `confidence` data is computed at-read-time from `trials.per_query_metrics` on every `GET /api/v1/studies/{id}` call (FR-2). Rejected: persist `confidence` to a new `digests.confidence JSONB` column. Rationale: keeps source-of-truth single (the trial rows); avoids a migration on `digests`; avoids retrofitting the digest worker's write path; recompute cost is sub-millisecond for MVP1 sizes.

- **2026-05-21 — D10 — Numpy-only bootstrap, no scipy.** Locked: implement bootstrap with `numpy.random.default_rng(42).choice + numpy.percentile` (FR-4). Rejected: `scipy.stats.bootstrap`. Rationale: numpy is already a transitive dep via pytrec_eval; scipy is also installed but adding it as a direct runtime dependency expands the package surface for no measurable benefit — `scipy.stats.bootstrap`'s bias-correction machinery is overkill for 1000-sample percentile bootstraps on N≤100 query datasets.
