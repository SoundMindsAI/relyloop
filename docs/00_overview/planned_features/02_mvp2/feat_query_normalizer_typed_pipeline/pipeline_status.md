# Pipeline Status — Typed normalizer pipeline (Phase 2 of query-normalization-tuning)

> **DESIGN-AHEAD.** Implementation is GATED on Phase 1 (`feat_query_normalization_tuning`) merging to `main`. Phase 1 is currently UNMERGED (plan stage). Do NOT run `/impl-execute` until Phase 1 ships — see `feature_spec.md` §5 and the design-ahead banner.

## Idea
- Status: Complete
- File: idea.md
- Preflight: Audit & Patch applied 2026-06-01 (3 edits — cardinality-cap citation precision, ParamSpec union grounding, design-ahead/Phase-1-unmerged framing).

## Spec
- Status: Approved (design-ahead)
- Date: 2026-06-01
- File: feature_spec.md
- Cross-model review: GPT-5.5 passed (3 cycles — 5 + 5 + 3 findings, all accepted and fixed; converged at the 3-cycle max with all internal-consistency findings resolved)
- FRs: 9 · ACs: 13
- Phases: this IS Phase 2 of the parent feature; Capability D (operator-supplied dictionaries) is a recommended-out Phase 2.5, kept as a documented §19 D-5 note (no separate idea file created per the default).
- Open questions: Q-1 (ship `expand_contractions_custom` as inert reserved step vs omit — recommended: include inert) and Q-2 (JS-snippet test execution: backend Node subprocess vs frontend vitest fixture — recommended: frontend vitest fixture) remain as genuine forks with recommended defaults. Q-3 (duplicate-step error code) was locked to D-8 during review.

## Plan
- Status: Approved (design-ahead)
- Date: 2026-06-01
- File: implementation_plan.md
- Cross-model review: GPT-5.5 passed (3 cycles — 4 + 1 + 1 findings, all accepted and fixed; converged at the 3-cycle max with no open findings)
- Stories: 8 across 5 epics (Epic 0 precondition gate; Epic 1 domain ×4 stories incl. adapter-hook generalization; Epic 2 PR body ×1; Epic 3 frontend ×2; Epic 4 docs ×1)
- Phases covered: Phase 2 (Capabilities A+B+C). Capability D (Phase 2.5) deferred per spec D-5.
- Migration: none (Alembic head stays 0022).
- Execution gate: Story 0 asserts Phase 1 symbols exist and aborts otherwise. Open Questions Q-1 + Q-2 must be locked before `/impl-execute`.

## Implementation
- Status: Not started — BLOCKED on Phase 1 (`feat_query_normalization_tuning`) merge + Q-1/Q-2 lock.
