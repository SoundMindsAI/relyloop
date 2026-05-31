# Pipeline Status — feat_demo_ubi_study_comparison

**Release:** mvp2

## Idea
- Status: Complete
- File: [idea.md](./idea.md) (preflight-audited 2026-05-29)

## Spec
- Status: Approved (autonomous-mode auto-advance)
- Date: 2026-05-29
- File: [feature_spec.md](./feature_spec.md)
- Cross-model review: GPT-5.5 — 3 cycles run; converged with 1 rejection (A1 — endpoint already exists per cited counter-evidence) + 1 deliberately-deferred meta-note (A5 — docstring confirms claim); all other findings accepted and patched. Cycle 3 was last; reached the spec-gen 3-cycle cap.
- Phases: 2 total, 1 covered by this spec; Phase 2 (deferred side-by-side study-comparison view) split out to [`feat_ubi_llm_study_comparison`](../../planned_features/02_mvp2/feat_ubi_llm_study_comparison/idea.md) at finalization.

## Plan
- Status: Approved (autonomous-mode auto-advance)
- Date: 2026-05-29
- File: [implementation_plan.md](./implementation_plan.md)
- Cross-model review: GPT-5.5 — 3 cycles run; cycle 1 surfaced 11 findings (all accepted); cycle 2 surfaced 6 findings (5 accepted + 1 rejected with counter-evidence from `judgment_list.py:51`); cycle 3 surfaced 3 findings (all accepted). Reached the impl-plan-gen 3-cycle cap.
- Stories: 14 total across 4 epics (Epic 1: pure-domain generator + canonical mapping + writer = 3 stories; Epic 2: SCENARIOS catalog + reseed wiring + CLI parity = 5 stories; Epic 3: frontend chip + helper = 2 stories; Epic 4: fast-lane + heavy-lane + E2E + docs = 4 stories).
- Phases covered: Phase 1 only. Phase 2 split out to [`feat_ubi_llm_study_comparison`](../../planned_features/02_mvp2/feat_ubi_llm_study_comparison/idea.md) at finalization.

## Implementation
- Status: Complete
- Date: 2026-05-30
- PR: [#320](https://github.com/SoundMindsAI/relyloop/pull/320) (squash-merged 2026-05-30; merge commit `853a5053`)
- CI: green (pr.yml backend fast-lane + DCO + secrets-defense; heavy jobs skipped under the active `SKIP_HEAVY_CI=true` repo variable)
- Stories: 14/14 complete across 4 epics
- Cross-model review: Gemini Code Assist (4 findings, all accepted + fixed in `b5b38dfb`) + GPT-5.5 final (6 findings — 5 accepted + fixed in `6e55c32e`, 1 rejected as spec-vs-code drift with cited counter-evidence). Adjudication tables posted on PR #320.
- Phase 2 (side-by-side UBI-vs-LLM study comparison view) split out to [`feat_ubi_llm_study_comparison`](../feat_ubi_llm_study_comparison/idea.md) at finalization.
