# Pipeline Status — Cluster base_url SSRF guard (hostname-aware)

**Release:** mvp2

## Idea
- Status: Complete
- File: idea.md

## Spec
- Status: Approved
- Date: 2026-06-09
- File: feature_spec.md
- Cross-model review: Opus self-review (GPT-5.5 unreachable in the Claude Code remote sandbox)
- Phases: 2 total (Phase 1 covered by this spec; Phase 2 = connect-time IP pinning, tracked in phase2_idea.md)

## Plan
- Status: Approved
- Date: 2026-06-09
- File: implementation_plan.md
- Cross-model review: Opus self-review (GPT-5.5 unreachable in the Claude Code remote sandbox)
- Stories: 3 (Epic 1: classifier / orchestrator+wiring / docs)
- Phases covered: Phase 1 (Phase 2 connect-time IP pinning deferred → phase2_idea.md)

## Implementation
- Status: Complete — Phase 1 (PR #510, squash-merged `3cb28c7`, 2026-06-09)
- CI: all `pr.yml` jobs green (smoke skipped — opt-in/off)
- Stories: 3/3 complete (classifier / orchestrator+wiring / docs)
- Review: Opus self-review (GPT-5.5 unreachable) + Gemini Code Assist 2 Medium findings accepted (bounded DNS timeout, malformed-port 422)
- **Folder retained in `planned_features/` — Phase 2 (connect-time IP pinning, `phase2_idea.md`) is still pending**, so it is NOT moved to `implemented_features/` per the impl-execute deferred-phase rule.
