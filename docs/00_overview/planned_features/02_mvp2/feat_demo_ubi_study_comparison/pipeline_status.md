# Pipeline Status — feat_demo_ubi_study_comparison

## Idea
- Status: Complete
- File: [idea.md](./idea.md) (preflight-audited 2026-05-29)

## Spec
- Status: Approved (autonomous-mode auto-advance)
- Date: 2026-05-29
- File: [feature_spec.md](./feature_spec.md)
- Cross-model review: GPT-5.5 — 3 cycles run; converged with 1 rejection (A1 — endpoint already exists per cited counter-evidence) + 1 deliberately-deferred meta-note (A5 — docstring confirms claim); all other findings accepted and patched. Cycle 3 was last; reached the spec-gen 3-cycle cap.
- Phases: 2 total, 1 covered by this spec; [phase2_idea.md](./phase2_idea.md) tracks the deferred side-by-side study-comparison view.

## Plan
- Status: Approved (autonomous-mode auto-advance)
- Date: 2026-05-29
- File: [implementation_plan.md](./implementation_plan.md)
- Cross-model review: GPT-5.5 — 3 cycles run; cycle 1 surfaced 11 findings (all accepted); cycle 2 surfaced 6 findings (5 accepted + 1 rejected with counter-evidence from `judgment_list.py:51`); cycle 3 surfaced 3 findings (all accepted). Reached the impl-plan-gen 3-cycle cap.
- Stories: 14 total across 4 epics (Epic 1: pure-domain generator + canonical mapping + writer = 3 stories; Epic 2: SCENARIOS catalog + reseed wiring + CLI parity = 5 stories; Epic 3: frontend chip + helper = 2 stories; Epic 4: fast-lane + heavy-lane + E2E + docs = 4 stories).
- Phases covered: Phase 1 only. Phase 2 tracked at [phase2_idea.md](./phase2_idea.md).

## Implementation
- Status: Not started
