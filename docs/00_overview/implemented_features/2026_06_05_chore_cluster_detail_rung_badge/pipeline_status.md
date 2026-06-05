# Pipeline Status — chore_cluster_detail_rung_badge

## Idea
- Status: Complete (preflight-audited 2026-06-01)
- File: idea.md

## Spec
- Status: Approved
- Date: 2026-06-01
- File: feature_spec.md
- Cross-model review: GPT-5.5 cycles 1, 2, 3 — 8 findings total, all 8 accepted and patched (D-10 through D-17). Cycle 3 stop rule: max-3-cycle cap reached; all cycle-3 findings were Medium and have been addressed.
- Phases: 1 total, 1 covered by spec (single-phase chore; no deferred phase).

## Plan
- Status: Approved
- Date: 2026-06-01
- File: implementation_plan.md
- Cross-model review: GPT-5.5 cycles 1, 2, 3 — 15 findings total (10 cycle-1 + 2 cycle-2 + 3 cycle-3), all 15 accepted and patched. Cycle-3 stop rule: max-3-cycle cap reached; all cycle-3 findings were Medium and have been addressed.
- Stories: 8 stories across 1 epic (Story 8 → 1 → 2 → 3 → 4 → 5 → 6 → 7 sequence).
- Phases covered: single phase (no deferred phase).

## Implementation
- Status: Complete (PR #464, squash-merged `3e03ce7`, 2026-06-05)
- Release: mvp2
- Note: Frontend-only, no migration. New `ClusterDetailUbiReadinessCard` mounted on `/clusters/[id]` between the action bar and indices card; query-set picker + debounced target input + auto-seed (single query set + target_filter) → `<UbiRungBadge>` via `useUbiReadiness`. Synthetic-UBI `<DemoBadge>` relocated out of `ClusterDetailSummary` into the new card. Story 8 added `placeholderData: keepPreviousData` to the shared `useUbiReadiness` hook. Dual leak gate + 404/503 fallback caption + inline retry. Tests: 13-case vitest (MSW network mocking + real QueryClient for the AC-8 placeholderData assertion; AC-9 no-inline-rung-literal static guard), summary regression, one gated real-backend Playwright spec, demo-ubi surface #3 re-anchored. Gemini: 2 medium findings accepted + fixed (`b0063dd`). All 19 CI checks green.
