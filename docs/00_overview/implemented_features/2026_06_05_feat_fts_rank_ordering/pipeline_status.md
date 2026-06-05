# Pipeline Status — Rank-ordered FTS results

## Idea
- Status: Complete
- File: idea.md

## Spec
- Status: Approved (self-reviewed)
- Date: 2026-06-05
- File: feature_spec.md
- Cross-model review: GPT-5.5 UNAVAILABLE in this env (no key, egress 403) → Opus self-review substituted per operator decision (2026-06-05). 3 self-review passes, 0 unresolved findings.
- Phases: 1 total (single-phase)

## Plan
- Status: Approved (self-reviewed)
- Date: 2026-06-05
- File: implementation_plan.md
- Cross-model review: Opus self-review substituted for GPT-5.5 (same reason). 3 passes, 0 unresolved findings.
- Stories: 4 total across 2 epics (1.1 helpers, 1.2 repos, 1.3 routers, 2.1 frontend; tests woven through)
- Phases covered: 1 of 1

## Implementation
- Status: Complete (PR #472, squash-merged `f970c05`, 2026-06-05)
- Release: mvp2
- Note: Backend + small frontend, no migration. `?q=` without `?sort=` now orders the 6 searchable endpoints by relevance (`floor(ts_rank*1e6) DESC, id DESC`) via the rank-bucketed 2-tuple cursor (reuses the `parsed=None` keyset; no new sort helpers). Cross-model: GPT-5.5 unreachable → Opus self-review substituted (operator decision). Gemini 6 findings all accepted (stale datetime cursor on rank path → 422 guard). 10 unit (keyset oracle) + 11-case DB integration matrix + 4 vitest pill. All 19 CI checks green.
