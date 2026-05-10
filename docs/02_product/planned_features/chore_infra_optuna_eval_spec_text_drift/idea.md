# Idea — `chore_infra_optuna_eval_spec_text_drift`

**Date:** 2026-05-10
**Origin:** Surfaced during GPT-5.5 cycle-3 cross-model review of `infra_optuna_eval`'s implementation plan (cycle-3 finding A2). Cited in [`infra_optuna_eval/implementation_plan.md`](../infra_optuna_eval/implementation_plan.md) Story 3.1 task 6's "Note on spec §11 vs §14 wording".

## Problem

The `infra_optuna_eval` feature spec at [`feature_spec.md`](../infra_optuna_eval/feature_spec.md) has internal drift between §11 and §14 about the partial-failure retry contract:

- **§11 "Trial-number assignment"** (review-and-patched in cycle 3 of spec review): "The worker therefore does NOT call `ask()`; it loads the in-flight trial via `study.trials[optuna_trial_number]`." This is the **controlling contract** — explicitly locked in across three review cycles.
- **§14 "Test strategy requirements", `test_run_trial_partial_failure.py` case 1:** "Death after `ask()`, before `tell()`. ... Re-execute the job; assert: exactly one terminal app row, Optuna has 1 RUNNING (orphan, tolerated) + 1 COMPLETE." The "1 RUNNING orphan" outcome can only arise if the worker calls `ask()` itself — which §11 forbids.

The contradiction was first surfaced by GPT-5.5 cycle 2 (finding B4) for the implementation plan, and re-surfaced in cycle 3 (finding A2) once we'd locked the plan to §11's contract.

## Why deferred

Out of scope for the `infra_optuna_eval` implementation. The plan implements tests per §11 (the architecturally correct contract — without an orphan accumulation in the within-worker death scenario) and explicitly documents the §11-controls-over-§14 decision. Patching the spec is a one-paragraph rewrite of §14's case 1 description, but it's a separate concern from shipping the runtime.

## What to do

Patch [`feature_spec.md`](../infra_optuna_eval/feature_spec.md) §14 `test_run_trial_partial_failure.py` case 1 to:

> 1. **Death after orchestrator-allocated trial is loaded, before `tell()`.** Inject `os._exit(1)` at the worker's `INFRA_OPTUNA_EVAL_FAULT=after_trial_load_before_execute` seam. After the death: app `trials` has zero rows for `(study_id, optuna_trial_number)`; Optuna has one RUNNING trial. Re-execute the job; assert: exactly one terminal app row (COMPLETE), exactly one COMPLETE Optuna trial for `optuna_trial_number`. **No orphan accumulates** in this scenario because the worker doesn't call `ask()` — the second invocation completes the same trial number. Orphan-RUNNING trials only arise from a separate failure mode (orchestrator dies between its own `ask()` and the enqueue commit) tracked as `infra_optuna_orphan_reaper`.

The rest of §14 is consistent with §11 already; only this one sub-bullet needs the rewrite.

## Acceptance criteria

- [ ] §14 case 1 wording matches §11's worker-does-not-call-ask contract.
- [ ] No claim in §14 of "1 RUNNING orphan" outcome for a within-worker death.
- [ ] Status: spec moves to Approved-with-patch (or keep Approved if minor — operator's call).

## Dependencies

None. Pure documentation patch. Could land alongside the `infra_optuna_eval` PR or in a follow-up.

## Estimated scope

~10 lines of spec text. One PR.
