# Orchestrator: abort the study after N consecutive trials with primary_metric == 0.0

**Date:** 2026-05-21
**Status:** Idea — defense-in-depth tier behind the create-time fail-fast guards
**Priority:** P1 — third tier of fail-fast (mid-flight). Mirrors the existing 5-consecutive-failures lifecycle guard; ~50 LOC. Catches everything the two create-time guards miss.
**Origin:** Same operator session as [`feat_study_target_judgment_mismatch_guard`](../../../00_overview/implemented_features/2026_05_21_feat_study_target_judgment_mismatch_guard/feature_spec.md) (shipped 2026-05-21 as PR #184 — Tier 1 create-time guard). Even with that guard plus the still-planned [`feat_study_preflight_overlap_probe`](../feat_study_preflight_overlap_probe/idea.md) (Tier 2 create-time guard), there's a residual class of "study cannot produce signal" pathologies the orchestrator could catch mid-flight — for the same per-trial cost as the existing "5 consecutive failures → fail study" guard.
**Depends on:** None (composes with `feat_study_lifecycle`'s existing terminal-state guard).

## Problem

The two create-time guards close the bulk of the "all 1000 trials score 0" surface, but they don't cover every path:

- **Cluster degradation mid-study.** The target index loses documents (operator runs `DELETE` while a study is mid-flight), or the cluster falls into a degraded state where it returns empty results. Trials keep completing with status='complete', primary_metric=0.0.
- **Template breakage on an edge param value.** A template body that's valid for `boost ∈ [0.5, 10]` may silently degrade to a zero-result query at a specific param value Optuna keeps sampling. The two guards catch nothing because the template renders cleanly and ES returns 200 OK.
- **Cluster credentials silently downgraded.** Auth tokens expire mid-study, the adapter falls back to anonymous, the cluster returns empty results (no access).
- **The preflight probe was bypassed.** Probe ran when index was healthy; index degraded between create and orchestrator start. Possible during canary deployments.

In all of these the orchestrator burns budget on trials that cannot produce signal. The operator returns to find 1000 zero-metric trials and has to start over.

## Proposed capabilities

### Mid-flight orchestrator guard

Mirror the existing `feat_study_lifecycle` "5 consecutive trial failures → fail study" pattern. Implementation lives in [`backend/workers/orchestrator.py`](../../../../backend/workers/orchestrator.py) — specifically the `start_study` Arq job that coordinates trial enqueue + status transitions and already calls `_last_n_all_failed(db, study_id, n=_CONSECUTIVE_FAILURE_THRESHOLD)` (at line 188) on each tick. The new zero-streak check would mirror that pattern alongside `_last_n_all_failed`.

Threshold: **20 consecutive trials** with `primary_metric == 0.0` AND `status == 'complete'` (not `failed` — that's the existing separate guard) → transition the study to `failed` via `study_state.fail_study(db, study_id, failed_reason="no signal: 20 consecutive trials scored 0.0 — judgment overlap likely lost mid-study")`.

**Threshold rationale (locked at 20).**
- Optuna's TPE warm-up uses **10 random samples by default** (upstream Optuna default; the project uses bare `TPESampler(seed=seed)` in [`backend/app/eval/optuna_runtime.py:107`](../../../../backend/app/eval/optuna_runtime.py) so this applies). 20 gives 10 random + 10 informed; if BOTH classes score 0, the search space genuinely can't produce signal.
- For operator-supplied `max_trials` ≥ 100 (a common floor in the tutorial), aborting at 20 caps the wasted budget at 20% — small enough to recover gracefully, large enough not to spook on legitimate early-low TPE exploration. Note that [`StudyConfigSpec` at `backend/app/api/v1/schemas.py:569-582`](../../../../backend/app/api/v1/schemas.py) declares `max_trials: int | None = Field(default=None, ge=1, le=100_000)` with NO server-side default — the operator must specify either `max_trials` or `time_budget_min`. A sibling planned chore [`chore_study_default_stop_conditions`](../chore_study_default_stop_conditions/idea.md) may add a server-side default later, but this idea does NOT depend on it.

**Configurability (locked: module-level constant, mirrors precedent).** The existing 5-failures guard uses `_CONSECUTIVE_FAILURE_THRESHOLD = 5` as a module-level constant in `orchestrator.py:69` — not a `Settings` field. The new zero-streak threshold should mirror that precedent: a module-level constant (e.g., `_ZERO_STREAK_THRESHOLD = 20`) co-located with `_CONSECUTIVE_FAILURE_THRESHOLD`. Operator-tunable knobs in `Settings` are reserved for surfaces operators actually tune (`openai_daily_budget_usd`, etc.); orchestrator thresholds are project-internal tuning.

The guard runs in the orchestrator's tick loop between trial enqueues — same surface as the existing failure-streak guard. No new DB queries: the orchestrator already polls trial state via `aggregate_trials_summary` to advance the lifecycle.

### Operator surface (no new error code)

**Superseded by spec §3 / §4 / §7.5 / §19 decision log:** the original draft proposed a new `STUDY_NO_SIGNAL` error code in the canonical error list, but spec review rejected it — there is no HTTP 4xx/5xx envelope to attach the code to (the operator-facing surface is the existing `Study.failed_reason` string column, not a new error response). The stable contract is the exact `failed_reason` string `"no signal: 20 consecutive trials scored 0.0 — judgment overlap likely lost mid-study"` + the structlog tag `event_type="stop_condition_fired", reason="no_signal"`. No new error code, no new envelope. The original prose is preserved below in strikethrough for traceability; the implementation matches the spec, not this draft.

~~New error code `STUDY_NO_SIGNAL` in the canonical error list.~~ Surfaces in `study.failed_reason` so:

- The studies-list filter chip "Failed" includes the no-signal cases (already there — `feat_studies_ui` handles `status='failed'` generically).
- The study detail page's StudyHeader badge shows "Failed: no signal" with a tooltip linking to the new FAQ entry (when [`chore_guides_faq`](../chore_guides_faq/idea.md) lands).

### Tests

- Integration: seed a study where the orchestrator deterministically receives 20 consecutive trials with primary_metric=0.0 → study transitions to `failed` with the exact `failed_reason` string above ~~`STUDY_NO_SIGNAL`~~.
- Integration: seed a study with 19 zeros + 1 non-zero → study continues running (boundary).
- Integration: 5 failed trials interleaved with 5 zero-metric trials don't trigger the abort (the failure-streak guard counts independently).

## Scope signals

- **Backend:** orchestrator change (~30 LOC) — new `_last_n_all_zero` helper alongside `_last_n_all_failed`; new `_ZERO_STREAK_THRESHOLD = 20` module constant alongside `_CONSECUTIVE_FAILURE_THRESHOLD`; new failed_reason text (the `STUDY_NO_SIGNAL` error code originally proposed was dropped during spec review — see "Operator surface" above). Tests: 6 integration (5 named + 1 parameterized 8-subcase boundary matrix), as finalized in the implementation plan.
- **Frontend:** optional — the existing failed-study UI surface handles this case generically. [`StudyHeader` at `ui/src/components/studies/study-header.tsx:85-88`](../../../../ui/src/components/studies/study-header.tsx) already renders `study.failed_reason` to the operator, so this idea ships with no required frontend change. A targeted "no signal" tooltip is nice-to-have once [`chore_guides_faq`](../chore_guides_faq/idea.md) lands.
- **Migration:** none.
- **Config:** no `Settings` field (per the locked design — see Threshold rationale above).
- **Audit events:** N/A in MVP1 (audit_log activates at MVP2).
- **Estimated size:** small — ~30 LOC orchestrator + ~500 LOC of integration tests (after spec review expanded the test surface to 6 tests with 8-subcase boundary matrix). 45–60 minutes implementation; the test surface was the larger time investment.

## Why this lives behind the two create-time guards

The create-time guards are deterministic and cheap. This one is mid-flight, costs N trials of wasted budget before triggering, and has a tuning surface (threshold). It's the right tool for "everything the create-time guards missed" — not the front-line check.

If only one of these three ships, it should be the [target-mismatch guard](../../../00_overview/implemented_features/2026_05_21_feat_study_target_judgment_mismatch_guard/feature_spec.md) (already shipped 2026-05-21 as PR #184). If only two ship, add the [preflight overlap probe](../feat_study_preflight_overlap_probe/idea.md). This one is the third leg for hardening the long tail.

## Relationship to other work

- **Pattern precedent:** the existing "5 consecutive failures → fail study" guard at [`backend/workers/orchestrator.py:188-210`](../../../../backend/workers/orchestrator.py) (which calls into `study_state.fail_study` at [`backend/app/services/study_state.py`](../../../../backend/app/services/study_state.py)) — same loop position, same terminal-transition mechanic, same `failed_reason` shape. Threshold module constant `_CONSECUTIVE_FAILURE_THRESHOLD = 5` at orchestrator.py:69.
- **Tier 1 sibling (shipped):** [`feat_study_target_judgment_mismatch_guard`](../../../00_overview/implemented_features/2026_05_21_feat_study_target_judgment_mismatch_guard/feature_spec.md) — rejects judgment-list/study cluster + target mismatches at `POST /studies` time. PR #184, merged 2026-05-21.
- **Tier 2 sibling (planned):** [`feat_study_preflight_overlap_probe`](../feat_study_preflight_overlap_probe/idea.md) — defense-in-depth tier behind the target-mismatch guard.
- **Composes with:** the FR-7 graceful-degradation contract in [`feat_pr_metric_confidence`](../../../00_overview/implemented_features/2026_05_21_feat_pr_metric_confidence/feature_spec.md) (shipped 2026-05-21 as PR #180) — when a study is aborted with `STUDY_NO_SIGNAL`, the ConfidencePanel still renders the partial shape (`best_trial_id` may or may not be set depending on whether trial 0 was a non-zero outlier).
- **Coordinates with:** [`chore_study_default_stop_conditions`](../chore_study_default_stop_conditions/idea.md) — a P2 idea proposing server-side defaults for `max_trials` / `time_budget_min`. If that chore ships before this one, this idea's "20-trial floor" framing aligns more directly with the new default; the zero-streak threshold itself is unchanged either way.
- **Surface alignment:** if [`chore_guides_faq`](../chore_guides_faq/idea.md) ships, this error becomes one of the canonical FAQ entries ("my study failed with STUDY_NO_SIGNAL — what now?").
