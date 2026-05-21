# Orchestrator: abort the study after N consecutive trials with primary_metric == 0.0

**Date:** 2026-05-21
**Status:** Idea — defense-in-depth tier behind the create-time fail-fast guards
**Priority:** P1 — third tier of fail-fast (mid-flight). Mirrors the existing 5-consecutive-failures lifecycle guard; ~50 LOC. Catches everything the two create-time guards miss.
**Origin:** Same operator session as [`feat_study_target_judgment_mismatch_guard`](../feat_study_target_judgment_mismatch_guard/idea.md). Even with the two create-time guards (`target` mismatch + judgment-overlap preflight), there's a residual class of "study cannot produce signal" pathologies the orchestrator could catch mid-flight — for the same per-trial cost as the existing "5 consecutive failures → fail study" guard.
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

Mirror the existing `feat_study_lifecycle` "5 consecutive trial failures → fail study" pattern. Implementation lives in [`backend/app/workers/orchestrator.py`](../../../../backend/app/workers/orchestrator.py) (or wherever the `start_study` Arq job coordinates trial enqueue + status transitions).

Threshold: **20 consecutive trials** with `primary_metric == 0.0` AND `status == 'complete'` (not `failed` — that's a separate guard) → transition the study to `failed` with `failed_reason = "no signal: 20 consecutive trials scored 0.0 — judgment overlap likely lost mid-study"`.

20 is the proposed floor because:
- Default `max_trials = 100`; 20 is 20% of that — small enough waste to recover gracefully, large enough not to spook on a legitimate early-low TPE exploration.
- Optuna's TPE warm-up uses 10 random samples by default. 20 gives 10 random + 10 informed; if BOTH classes score 0, the search space genuinely can't produce signal.
- Configurable via a `Settings.study_zero_streak_abort_threshold: int = 20`.

The guard runs in the orchestrator's tick loop between trial enqueues — same surface as the existing failure-streak guard. No new DB queries: the orchestrator already polls trial state to advance the lifecycle.

### Error code + UI surface

New error code `STUDY_NO_SIGNAL` in the canonical error list. Surfaces in `study.failed_reason` so:

- The studies-list filter chip "Failed" includes the no-signal cases (already there — `feat_studies_ui` handles `status='failed'` generically).
- The study detail page's StudyHeader badge shows "Failed: no signal" with a tooltip linking to the new FAQ entry (when [`chore_guides_faq`](../chore_guides_faq/idea.md) lands).

### Tests

- Integration: seed a study where the orchestrator deterministically receives 20 consecutive trials with primary_metric=0.0 → study transitions to `failed` with `STUDY_NO_SIGNAL`.
- Integration: seed a study with 19 zeros + 1 non-zero → study continues running (boundary).
- Integration: 5 failed trials interleaved with 5 zero-metric trials don't trigger the abort (the failure-streak guard counts independently).

## Scope signals

- **Backend:** orchestrator change (~30 LOC). New error code + 1 new `study.failed_reason` text. Settings field for the threshold (~5 LOC). Tests: 3 integration.
- **Frontend:** optional — the existing failed-study UI surface handles this case generically. A targeted "no signal" tooltip is nice-to-have.
- **Migration:** none.
- **Config:** new `STUDY_ZERO_STREAK_ABORT_THRESHOLD: int = 20` Settings field.
- **Audit events:** N/A in MVP1 (audit_log activates at MVP2).
- **Estimated size:** small-to-medium — ~50 LOC + ~100 LOC of tests. 60 minutes.

## Why this lives behind the two create-time guards

The create-time guards are deterministic and cheap. This one is mid-flight, costs N trials of wasted budget before triggering, and has a tuning surface (threshold). It's the right tool for "everything the create-time guards missed" — not the front-line check.

If only one of these three ships, it should be the [target-mismatch guard](../feat_study_target_judgment_mismatch_guard/idea.md). If only two ship, add the [preflight overlap probe](../feat_study_preflight_overlap_probe/idea.md). This one is the third leg for hardening the long tail.

## Relationship to other work

- **Pattern precedent:** `feat_study_lifecycle` "5 consecutive failures → fail study" guard at [`backend/app/services/study_state.py`](../../../../backend/app/services/study_state.py) — same loop position, same terminal-transition mechanic, same `failed_reason` shape.
- **Composes with:** the FR-7 graceful-degradation contract in `feat_pr_metric_confidence` — when a study is aborted with `STUDY_NO_SIGNAL`, the ConfidencePanel still renders the partial shape (best_trial_id may or may not be set depending on whether trial 0 was a non-zero outlier).
- **Surface alignment:** if [`chore_guides_faq`](../chore_guides_faq/idea.md) ships, this error becomes one of the canonical FAQ entries ("my study failed with STUDY_NO_SIGNAL — what now?").
