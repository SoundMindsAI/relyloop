# Study Default Stop Conditions — recommended `max_trials` defaults driven by search-space dimensionality, with `time_budget_min` as a safety net

**Date:** 2026-05-21 (revised after empirical measurement)
**Status:** Idea — surfaced during the 2026-05-21 Karpathy-loop audit; recommendation grounded in measured per-trial cost from the local dev DB.
**Priority:** P2 — sensible-defaults tweak. No felt cost today (operators pick their own values); landing this saves a few minutes per study setup. Worth the next quiet-friction sweep.
**Origin:** Standalone audit at `~/.claude/plans/compressed-sparking-hamming.md`. Verified live via grep of [`backend/app/api/v1/schemas.py:550-580`](../../../../backend/app/api/v1/schemas.py) + [`ui/src/components/studies/create-study-modal.tsx:98-100`](../../../../ui/src/components/studies/create-study-modal.tsx); recommendation calibrated against `SELECT percentile_cont` on `trials.duration_ms` from the seeded dev DB (data section below).
**Depends on:** None. Pure decision-support change at the create-study surfaces; no schema migration, no service-layer behavior change.

## Problem

The server-side `StudyConfigSpec` validator at [`backend/app/api/v1/schemas.py:572-580`](../../../../backend/app/api/v1/schemas.py) correctly **requires** at least one of `max_trials` or `time_budget_min` — studies cannot be created with no stop condition. The system is safe. What it is not is **opinionated** about what good values are. Operators pick numbers by intuition, the LLM agent picks numbers with no project guidance, and the result is studies that either stop before TPE warms up or burn budget past the point of diminishing returns.

Two surfaces today:

1. **The create-study wizard** ([`ui/src/components/studies/create-study-modal.tsx:98-100`](../../../../ui/src/components/studies/create-study-modal.tsx)) declares both fields as optional empty inputs. It pre-fills `parallelism: 4` at [line 136](../../../../ui/src/components/studies/create-study-modal.tsx#L136) but leaves both stop-condition inputs blank.
2. **The `create_study` agent tool** ([`backend/app/agent/tools/studies/create_study.py`](../../../../backend/app/agent/tools/studies/create_study.py)) reuses `CreateStudyRequest` verbatim. The LLM picks a value with no recommended range from the system prompt or glossary.

## The measurement that drives the recommendation

Real per-trial cost on the dev stack as of 2026-05-21, across 5 seeded demo studies × 2 trials each (`SELECT … FROM trials WHERE status='complete'`):

| Metric | Value | Notes |
|---|---|---|
| `n_complete_trials` | 10 | small sample but tightly clustered |
| `avg(duration_ms)` | 949 ms | |
| `p50(duration_ms)` | 1,100 ms | |
| `p95(duration_ms)` | 1,200 ms | |
| `max(duration_ms)` | 1,200 ms | |
| Query set size for those studies | **5 queries each** | seed data |
| Cluster | local Docker ES 9.4 + OS 2.18 | |
| Trial timeout configured | 60s (default) | **50× larger than the p95 actual** |
| Parallelism configured | 4 (default) | |

Four of the five studies hit ~1.15s per trial against the seeded ES/OS clusters; one study (`tune-product-title-boost-baseline-7ce587`) hit ~144ms, likely cache-warmed or hitting a smaller index.

**Cost scaling estimate** (linear-ish in query-set size; `_msearch` parallelizes server-side but ES overhead doesn't vanish):

| Query-set size | Expected per-trial cost | Source |
|---|---|---|
| 5 queries (seed) | ~1.1s | measured |
| 50 queries (tutorial) | ~3–5s | extrapolated |
| 200 queries (production) | ~10–30s | extrapolated; managed cloud could push higher with network latency |

**What this means for wall-clock budgeting:** with `parallelism=4`, even at the pessimistic 30s-per-trial number, **an 8-hour overnight run completes ~3,840 trials** — well past TPE's diminishing returns for any low-dimensional search space RelyLoop typically optimizes. Trials are so cheap that the wall-clock budget is essentially never the binding constraint. The binding constraint is **trial count driven by search-space dimensionality**.

| TPE convergence behavior | Trial-count range |
|---|---|
| Warmup phase (TPE samples randomly) | 1–10 |
| MedianPruner becomes active per [`optuna_runtime.py:116-157`](../../../../backend/app/eval/optuna_runtime.py) | ≥50 |
| 1–2 param search space — typical convergence | ~50 |
| 3–5 param search space — typical convergence | ~200 |
| 6–10 param search space — typical convergence | ~500–1000 |
| 10+ param search space — typical convergence | 1000–2000 |

Past those numbers TPE keeps sampling but the marginal lift drops fast.

## Proposed capabilities

Tiered. Tier A is the wizard pre-fill + glossary copy. Tier B is the preset selector keyed off search-space dimensionality. Both are calibrated against the measured per-trial cost above.

### Tier A — wizard pre-fill + recommended-default copy

- **Pre-fill `max_trials = 200`** on Step 5 of the wizard. Justification: 200 covers the TPE convergence sweet spot for 3–5 param search spaces (the most common shape, given the template's `declared_params` typically lands here per [`backend/app/db/models/query_template.py:34-35`](../../../../backend/app/db/models/query_template.py)). At the measured ~1.1s/trial cost with parallelism=4, a 200-trial study completes in **<1 minute** on the dev stack; at the pessimistic 30s/trial estimate for 200-query production sets, it completes in **~25 minutes**. Both are reasonable interactive sessions. Operators with smaller (1–2 param) or larger (6+ param) search spaces can edit downward / upward; the preset selector (Tier B) makes this one-click.
- **Leave `time_budget_min` empty** — `max_trials` is the primary cap; `time_budget_min` is only useful as a safety net for managed clusters where per-trial cost might unexpectedly balloon. Operators who want a wall-clock cap can opt in.
- **Glossary updates** in [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) for the existing `study.max_trials` + `study.time_budget_min` keys. New copy for `study.max_trials`:
  > "Total trials to run before stopping. Sized by your search-space dimensionality: 50 for 1–2 params, 200 for 3–5 params (typical), 500–1000 for 6+ params. TPE's diminishing returns kick in past these. With default parallelism=4 and a ~1s/trial cost on a small query set, 200 trials completes in under a minute; on a managed cluster with a large query set it's more like 25 minutes."

  New copy for `study.time_budget_min`:
  > "Wall-clock safety cap, in minutes. Optional. Trials in RelyLoop are typically cheap (subsecond against local stacks, seconds against managed clusters), so the binding stop is almost always `max_trials`. Set this only if you want a hard ceiling on a slow cluster."
- **System prompt entry** in [`prompts/orchestrator.system.md`](../../../../prompts/orchestrator.system.md) — add to the Studies tools section: "When the user does not specify a stop condition, propose `max_trials=200` for typical 3–5 param search spaces. Scale down to 50 for 1–2 params, up to 500–1000 for 6+ params. Use `time_budget_min` only as a safety cap on slow clusters; trials are usually cheap."

### Tier B — dimensionality-keyed preset selector on Step 5

Replace the empty-input pattern with a radio above the numeric fields:

- **Focused (50 trials)** — 1–2 param search space. TPE warmup completes; MedianPruner doesn't activate (small studies skip pruning per [`optuna_runtime.py:116-157`](../../../../backend/app/eval/optuna_runtime.py)). Estimated wall-clock: ~15s on dev (5-query set), ~1 min on a managed cluster (50-query set).
- **Standard (200 trials)** — 3–5 param search space, the typical case. **Default.** Estimated wall-clock: ~1 min on dev, ~4 min on a 50-query set, ~25 min on a 200-query set with cloud latency.
- **Deep (1000 trials)** — 6+ param search space. Estimated wall-clock: ~5 min on dev, ~20 min on a 50-query set, ~2 hours on a 200-query set with cloud latency. Sets `time_budget_min=480` (8 hours) as a safety cap that almost certainly won't fire but exists as a circuit breaker.
- **Custom** — leaves the existing fields manually editable.

The preset writes `max_trials` (+ optionally `time_budget_min` for Deep). Other config fields (`parallelism`, `trial_timeout_s`) inherit the existing settings defaults; the preset does not touch them — those are cluster-shape concerns, not "how long should this run" concerns.

Frontend-only state; no new wire-value enum, no new backend logic.

### Out of scope

- **Adaptive parallelism** based on observed trial latency — interesting but real product surface; defer.
- **A separate "Karpathy mode" preset that combines `Deep` + auto-chained follow-ups** — belongs to [`feat_auto_followup_studies`](../feat_auto_followup_studies/idea.md), not here.
- **Backend-side Pydantic default changes** — rejected. The existing validator (force-explicit at the API layer) is the right safety net; only the wizard and the system prompt should opinion-set, so legacy callers aren't surprised.

## Scope signals

- **Backend:** ~5 LOC in [`prompts/orchestrator.system.md`](../../../../prompts/orchestrator.system.md).
- **Frontend:** Tier A: ~20 LOC (form default + 2 glossary entries + 1 vitest case). Tier B: ~150 LOC (preset radio + 4 vitest cases).
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A.
- **Tests:** Tier A: 1 vitest case asserting the `max_trials` field renders with `200` by default. Tier B: 4 cases (3 presets write the expected field bundle + 1 Custom mode preserves manual edits).

## Calibration note for future revisions

The recommended-default numbers in this idea (50 / 200 / 1000 trials; 8h time-budget safety cap) are calibrated against:

- Measured per-trial p95 of **1,200 ms** on the local dev stack (5-query seed sets, ES 9.4 + OS 2.18, default parallelism=4)
- Linear-ish scaling assumption for larger query sets
- Standard TPE convergence behavior for low-dimensional search spaces

If RelyLoop's actual production query sets prove dramatically larger or slower than these estimates, the preset wall-clock numbers in the glossary copy need updating. The trial-count recommendations (50 / 200 / 1000) are driven by TPE convergence, not wall-clock, and shouldn't change with cluster cost. Re-run the `percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) FROM trials WHERE status='complete'` query against any cluster's real workload to update the cited cost.

## Why not implemented inline today

Tier A alone is ≤30 LOC and touches the wizard + the system prompt — borderline drive-by per [`CLAUDE.md`](../../../../CLAUDE.md). The reason it's captured as an idea file rather than landed inline:

1. **Product call on the recommended-default number.** "200" is grounded in TPE convergence + measured per-trial cost, but other defensible numbers exist (100, 250, 500). The decision is a one-way change once shipped to every new study; worth deliberate scrutiny.
2. **Tier B is the more interesting unit.** A dimensionality-keyed preset selector is the real UX addition; pairing it with the default tweak (Tier A) in one PR gives reviewers the full picture.
3. **The glossary copy is operator-facing documentation.** Wall-clock estimates in user-visible help text need spec-shaped review for accuracy. The numbers cited here are calibrated against the dev stack; production operators will read them and form expectations.

## Open questions for /spec-gen

These need spec-time decisions — recommended defaults are surfaced so /spec-gen doesn't start from zero.

1. **Tier scope: ship Tier A + Tier B together, or Tier A first?** Recommended: **ship both as one unit** (per the idea's own "Tier B is the more interesting unit" framing). Tier A alone is operator-invisible polish (a different number in a pre-filled field); Tier B is the actual UX addition. Splitting would mean two PRs for what is conceptually one change. **Locked: Tier A + Tier B in one PR.**
2. **Default `max_trials` number: 200, or different?** Recommended: **200**, as calibrated from TPE convergence behavior for 3–5 param search spaces (the typical shape per `query_template.declared_params` cardinality). 100/250/500 are defensible alternatives the operator could pick. /spec-gen should confirm the number; if changed, update the glossary copy + system prompt entry accordingly.
3. **Preset names: Focused/Standard/Deep/Custom.** Recommended: as proposed. Alternative naming surveyed during /spec-gen — "Fast/Default/Thorough/Custom" reads more like file-size presets; "Quick/Recommended/Long/Custom" inverts the framing toward duration rather than search-space-fit. The idea's "dimensionality-keyed" rationale should drive the names (search-space-fit framing wins).
4. **Where the preset selector lives in Step 5.** Recommended: above the numeric `max_trials` + `time_budget_min` fields, with Standard selected by default. Selecting a preset fills the numeric fields (which remain editable in Custom mode). /spec-gen should specify the form-state transitions: does switching preset reset the numeric field, or only set it when blank?
5. **Glossary copy cluster-shape ranges (Tier A bullet 3).** The cited cost ranges ("under a minute on dev, ~25 minutes on a managed cluster") are dev-stack-calibrated. Production operators reading these form expectations. /spec-gen should decide whether to keep the wall-clock estimates (concrete but potentially mis-calibrating) or replace them with relative framings ("fast on local dev, minutes-to-tens-of-minutes on managed clusters"). Locked vote: keep concrete numbers and add a one-line caveat that they're measured against the dev stack.

## Relationship to other work

- **Substrate for [`feat_auto_followup_studies`](../feat_auto_followup_studies/idea.md)** — that feature relies on every study in a chain having a known finite stop condition so chained follow-ups inherit a sensible budget. "Standard preset = 200 trials × depth=3 = ~3 min total compounding on dev" is a concrete story; without sane defaults the chain has no predictable footprint.
- **Aligned with [`feat_pr_metric_confidence`](../../../00_overview/implemented_features/2026_05_21_feat_pr_metric_confidence/feature_spec.md)** (shipped 2026-05-21, PR #180) — convergence-trajectory analytics in the PR body are most meaningful when the operator knows the study had room to converge. 200-trial studies give those analytics meaningful signal; 50-trial studies often don't.
- **Composes with [`feat_create_study_search_space_builder`](../../../00_overview/implemented_features/2026_05_20_feat_create_study_search_space_builder/)** (shipped 2026-05-20) — the search-space builder counts declared params in real time; that count could feed the preset selector directly ("you have 4 params declared — Standard preset is recommended"). Composable enhancement, not required.
