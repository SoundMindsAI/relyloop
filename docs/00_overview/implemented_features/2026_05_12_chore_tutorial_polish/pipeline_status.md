# Pipeline Status — chore_tutorial_polish

## Idea
- Status: Skipped (spec authored directly from umbrella spec §27 + the design-partner brief; no separate idea.md)

## Spec
- Status: Approved
- Date: 2026-05-12
- File: feature_spec.md
- Cross-model review: 1 spec-gen Review & Patch cycle (5 Major + 11 Minor findings adjudicated)
- Phases: single-phase
- Last revision: cycle-2 + cycle-3 sweeps during /pipeline --auto plan stage (pre-baked judgments cut from scope, seed-order corrected, AC renumbered)

## Plan
- Status: Approved
- Date: 2026-05-12
- File: implementation_plan.md
- Cross-model review: GPT-5.5 — 3 cycles (cycle-1: 13 findings → 12 accepted + 1 rejected with cited counter-evidence; cycle-2: 6 findings → all accepted; cycle-3: 7 findings → all accepted, mostly residual cleanup)
- Stories: 13 total across 4 epics
  - Epic 1 (1 story): samples/ bootstrap
  - Epic 2 (3 stories): seed_es.py + ui Dockerfile + ui Compose service
  - Epic 3 (2 stories): smoke pytest + smoke CI job
  - Epic 4 (7 stories): tutorial + README + release-checklist + deployment.md + US flips + demo + tag/release
- Phases covered: single-phase

## Implementation
- Status: Complete (PR #64 merged 2026-05-12 as `bb95e3f`)
- Stories shipped: 11 of 13 (Story 1.1, 2.1, 2.2, 2.3, 3.1, 3.2, 4.1, 4.2, 4.3, 4.4, 4.5)
- Manual blocking steps remaining (per release-checklist.md): Story 4.6 (demo recording) + Story 4.7 (`v0.1.0` Git tag + GitHub Release). Both unblock now that PR #64 is merged.
- CI gates green on merge commit: backend, frontend, docker buildx, smoke (operator-path tutorial flow).
- Pre-existing platform bugs surfaced + captured: [`bug_judgment_template_default_params_contract`](../bug_judgment_template_default_params_contract/idea.md), [`bug_worker_optuna_init_race`](../bug_worker_optuna_init_race/idea.md).
