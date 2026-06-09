# Pipeline Status — Typed normalizer pipeline (Phase 2 of query-normalization-tuning)

**Release:** mvp2

> **SHIPPED 2026-06-09 (PR #509).** The design-ahead gate cleared: Phase 1 (`feat_query_normalization_tuning`) merged, and Q-1 (include `expand_contractions_custom` inert — 6 steps) + Q-2 (JS parity via frontend vitest fixture) were locked.

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
- Status: **Complete** (PR #509, squash-merged `7a24849`, 2026-06-09)
- CI: all 19 `pr.yml` checks green (smoke skipped — opt-in/off); coverage 81.64% ≥ 80%
- Stories: 8/8 complete across 5 epics (Story 0 gate confirmed passing; Epic 1 domain ×4; Epic 2 PR body ×1; Epic 3 frontend ×2; Epic 4 docs ×1)
- Migration: none (Alembic head stays 0023)
- Cross-model review: Opus self-review (GPT-5.5 unreachable in the Claude Code remote sandbox); Gemini Code Assist — 2 Medium findings, both accepted (`7047190`: strip_punctuation snippets use the runtime's regex)
- Q-1 locked: include `expand_contractions_custom` inert (6 steps). Q-2 locked: JS parity via frontend vitest fixture.
