# Pipeline Status — Selective Engine Provisioning (Startup + Reset-to-Demo)

**Release:** mvp2

## Idea
- Status: Complete (preflight-patched 2026-06-17)
- File: [idea.md](idea.md)

## Spec
- Status: Approved (Draft → Approved on draft completion)
- Date: 2026-06-17
- File: [feature_spec.md](feature_spec.md)
- Cross-model review: Opus self-review (GPT-5.5 unreachable in Claude Code remote sandbox per CLAUDE.md "Environment-aware fallback")
- Phases: 3 total (Phase 1 covered by spec; Phase 2 + 3 deferred)
- Deferred-phase tracking:
  - Phase 2: [phase2_idea.md](phase2_idea.md) — engine version selection at install time
  - Phase 3: [phase3_idea.md](phase3_idea.md) — SSE migration for reseed status streaming (defer-until-incident)

## Plan
- Status: Approved
- Date: 2026-06-17
- File: [implementation_plan.md](implementation_plan.md)
- Cross-model review: Opus self-review (GPT-5.5 unreachable)
- Stories: 6 total across 3 epics (Epic 1: install-time engine selection — Stories 1.1/1.2; Epic 2: reset-to-demo backend engine filter — Stories 2.1/2.2; Epic 3: reset-to-demo modal UI — Stories 3.1/3.2)
- Phases covered: Phase 1 only (Phase 2 + 3 tracked in [phase2_idea.md](phase2_idea.md) and [phase3_idea.md](phase3_idea.md))

## Implementation
- Status: Complete (Phase 1) — PR #548 squash-merged `9bf20ab2` on 2026-06-17
- Branch: `feat_selective_engine_startup_and_demo` (merged)
- PR: [#548](https://github.com/SoundMindsAI/relyloop/pull/548)
- CI: all 19 checks green on the merged head (`smoke` SKIPPED — opt-in/off by default)
- Gemini Code Assist: 2 findings (1 High + 1 Medium) — both accepted + fixed; adjudication summary posted on the PR
- Cross-model review: Opus self-review (GPT-5.5 unreachable); Gemini was the live cross-family code-stage gate
- Stories shipped: 6/6 (Epic 1: 1.1/1.2; Epic 2: 2.1/2.2; Epic 3: 3.1/3.2)

## Done
- Status: Phase 1 merged to `main` 2026-06-17 (squash `9bf20ab2`, PR #548). No remote staging in MVP1/2 — local-only.
- **Folder NOT archived to `implemented_features/`** — Phase 2 (engine version selection) + Phase 3 (SSE migration) deferred trackers remain in this folder. Per impl-execute Step 8.6, a multi-phase feature stays in `planned_features/02_mvp2/` until every deferred phase ships. Archive when phase2 + phase3 are both done (or explicitly closed).
