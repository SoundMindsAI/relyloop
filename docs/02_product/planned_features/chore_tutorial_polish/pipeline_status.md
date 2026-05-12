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
- Status: Not started
