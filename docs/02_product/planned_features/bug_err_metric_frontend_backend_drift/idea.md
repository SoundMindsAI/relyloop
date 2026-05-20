# `err` metric is selectable in the wizard but unsupported by the scoring backend

**Date:** 2026-05-19
**Status:** Idea — surfaced during GPT-5.5 review of chore_create_study_wizard_polish PR #157
**Origin:** GPT-5.5 finding flagged that the frontend's `K_IGNORED = {mrr, err}` predicate treats `err` as a permitted ignored-k metric, but [`backend/app/eval/scoring.py:24`](../../../../backend/app/eval/scoring.py#L24) defines `SUPPORTED_METRICS = frozenset({"ndcg", "map", "precision", "recall", "mrr"})` — excluding `err` as "deferred to MVP2 (per spec §3)". A user who picks `err` on Step-5 will pass POST `/api/v1/studies` validation (because `ObjectiveMetric` Literal at `backend/app/api/v1/schemas.py` still lists `err`), then the trial worker will raise `ValueError("unknown objective.metric 'err'; allowed: ['map', 'mrr', 'ndcg', 'precision', 'recall']")` at scoring time. The wizard's new "ERR evaluates the full ranked list — no cutoff used." caption makes the option look first-class.
**Depends on:** none

## Problem

`OBJECTIVE_METRIC_VALUES` (frontend at `ui/src/lib/enums.ts:66`) and `ObjectiveMetric` Literal (backend at `backend/app/api/v1/schemas.py`) both contain `err`. But the scoring layer's `SUPPORTED_METRICS` frozenset excludes it — `err` was reserved as a placeholder for ERR@k support in MVP2 but never wired through. The result is a UX trap: the user picks `err`, the study POSTs successfully, and the first trial fails with a backend-side ValueError that won't surface in the UI as a clear "this metric isn't supported yet" message.

The chore_create_study_wizard_polish chore made this worse: the new tri-state k field captions `err` as `"ERR evaluates the full ranked list — no cutoff used."`, which positions it as a feature-complete K_IGNORED metric.

## Proposed capabilities

### Option A — Remove `err` from `OBJECTIVE_METRIC_VALUES` until scoring supports it

- Drop `err` from `ui/src/lib/enums.ts:66` `OBJECTIVE_METRIC_VALUES`.
- Drop `err` from `backend/app/api/v1/schemas.py` `ObjectiveMetric` Literal (Pydantic Literal also gates the wire).
- Update the glossary: remove the `study.metric.err` entry (covered by the existing `glossary.test.ts` parity check, which will catch the drop automatically once enums.ts is updated).
- Update `K_IGNORED` to `{ 'mrr' }` only.
- Migration is unnecessary — no DB rows reference the literal directly; existing studies that used `mrr` are unaffected.

### Option B — Wire `err` through scoring (deferred MVP2 plan)

- Add `err` to `SUPPORTED_METRICS` + the metric-token mapper in `scoring.py`.
- Pick the pytrec_eval token for ERR@k (or full-recall ERR).
- Add a parametrized test in `test_scoring_metric_tokens.py` exercising the ignored-k semantics.
- Likely 30-60 LOC backend + a few lines of glossary tightening.

Option A is the safer-by-default; Option B requires a product decision on ERR semantics that the spec hasn't made yet. Strong recommendation: **Option A** for short-term consistency, file Option B as a separate MVP2 follow-up.

## Scope signals

- **Backend:** Option A — 2 LOC (drop `err` from the Literal). Option B — ~30-60 LOC (mapper + tier classifier + tests).
- **Frontend:** Option A — 1 LOC enum trim + auto-cascading test updates. Option B — none (frontend already classifies `err` as K_IGNORED).
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A.

## Why deferred

Surfaced during PR #157's GPT-5.5 review, which is exactly the spot where adjudicating findings is supposed to file follow-ups rather than scope-creep the merging PR. The drift pre-existed `chore_create_study_wizard_polish` (it's a Story 1.2 / `OBJECTIVE_METRIC_VALUES` issue from the earlier `feat_study_lifecycle` Phase-2 PR), but the chore made the symptom more visible by surfacing a "no cutoff used" caption for the unsupported metric.

## Relationship to other work

- Surfaced from: [`chore_create_study_wizard_polish`](../chore_create_study_wizard_polish/) — pre-existing drift made more visible by the new Step-5 tri-state caption.
- Adjacent to: [`feat_study_lifecycle`](../../../00_overview/implemented_features/2026_05_10_feat_study_lifecycle/) which originally introduced both `OBJECTIVE_METRIC_VALUES` and `SUPPORTED_METRICS` without aligning them.
