# Pipeline Status — Home-page first-run demo nudge

## Idea
- Status: Complete
- File: [`idea.md`](idea.md)

## Spec
- Status: Approved (auto-mode, no user gate)
- Date: 2026-05-21
- File: [`feature_spec.md`](feature_spec.md)
- Cross-model review: GPT-5.5 — 3 cycles, all findings accepted + applied; cycle 1 (8 findings: 1 High / 3 Medium / 4 Low), cycle 2 (4 findings: 1 High / 2 Medium / 1 Low), cycle 3 (1 Medium). One additional Opus-internal verification pass clean.
- Phases: 2 total (Phase 1 covered by this spec; Phase 2 tracked in [`phase2_idea.md`](phase2_idea.md))

## Plan
- Status: Approved (auto-mode, no user gate)
- Date: 2026-05-21
- File: [`implementation_plan.md`](implementation_plan.md)
- Cross-model review: GPT-5.5 — 3 cycles, all findings accepted + applied; cycle 1 (7 findings: 0 High / 4 Medium / 3 Low), cycle 2 (3 findings: 0 High / 2 Medium / 1 Low), cycle 3 (1 finding: 0 High / 1 Medium / 0 Low). One Medium correction reflected back into [`feature_spec.md`](feature_spec.md) FR-2 (queryKey contract relaxed to allow the existing `useClusters` hook).
- Stories: 12 across 4 epics (1 in Epic 1, 4 in Epic 2, 4 in Epic 3, 3 in Epic 4)
- Phases covered: Phase 1 (banner + badges + CI guard). Phase 2 (reseed endpoint + UI) remains deferred per [`phase2_idea.md`](phase2_idea.md).

## Implementation
- Status: Complete
- Date: 2026-05-22
- PR: #188 (squash `21325432`)
- CI: green (5/5 jobs: backend lint+typecheck+pytest+coverage, backend unit fast lane, frontend lint+typecheck+vitest+build, docker buildx, operator-path smoke)
- Stories completed: 12 (1 in Epic 1, 4 in Epic 2, 4 in Epic 3, 3 in Epic 4)
- Cross-model review: Gemini Code Assist 3 Medium (2 accepted in `cb0bdc4` — `useClusters({ enabled })` + parity-guard regex broadening; 1 rejected with counter-evidence — `useMemo` would save nothing given React's render model + early-return). Final GPT-5.5: 0 High / 0 Medium / 2 Low (1 fixed in `2cdc44a` — banner-comment accuracy; 1 deferred to this finalization step).
- Phase 2 (reseed endpoint + UI): split out at finalization to a new planned folder [`feat_home_demo_reseed_endpoint`](../feat_home_demo_reseed_endpoint/idea.md) so it surfaces in `/pipeline --status`.

## Done
- Date: 2026-05-22
- Tag: none (feature ships as part of MVP1; no separate release)
- Implemented-features path: `docs/00_overview/implemented_features/2026_05_22_feat_home_first_run_demo_nudge/`
