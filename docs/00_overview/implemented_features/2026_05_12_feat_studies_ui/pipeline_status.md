# Pipeline Status — feat_studies_ui

## Idea
- Status: Skipped (spec authored directly on 2026-05-09)

## Spec
- Status: Approved
- Date: 2026-05-09 (drift-patched 2026-05-12)
- File: [feature_spec.md](feature_spec.md)
- Drift patches applied 2026-05-12 (this session):
  - Backend path citations corrected (`backend/app/...` prefix)
  - Frontend stack references aligned to Next 16 / React 19 / Tailwind 4 / Vitest 4
  - `ui/src/` layout reflected throughout
  - `npx shadcn@latest add` (legacy `shadcn-ui` CLI retired)
  - Section heading `### 7.4` → `### 8.1` (Enumerated value contracts)
  - FR-7 inline edit/delete deferred to `chore_query_inline_edit_delete` (cycle-3 reconciliation)
  - Decision log entry added for FR-7 scope change

## Plan
- Status: Ready for Execution
- Date: 2026-05-12
- File: [implementation_plan.md](implementation_plan.md)
- Stories: 13 across 4 epics (Foundations / Supporting screens / Studies surface / Docs+CI)
- Phases covered: single-phase (spec §3 declares one phase; no deferred phases)
- Cross-model review:
  - **GPT-5.5: 3 cycles to convergence cap** — 33 findings total
  - **32 accepted + applied** (19 cycle-1, 7 cycle-2, 6 cycle-3)
  - **1 rejected with cited counter-evidence** (cycle-1 #10: digest endpoint IS in `backend/app/api/v1/proposals.py:229`; no separate `digests.py` router exists)
  - Key adjustments through the loop:
    - QueryCache + MutationCache global error-toast wiring (v5-correct, not `defaultOptions.onError`)
    - Single-page `useQuery` + client-side cursor stack for pagination (NOT `useInfiniteQuery`)
    - Retry contract: 1 initial + 3 retries = 4 total attempts with 1s/2s/4s waits; extended to cover network failures (`TypeError` from fetch)
    - Polling hook is caller-driven per spec §4 (`useState<number|false>` + `useEffect` on `data?.status`)
    - Epic 2 re-sequenced: Stories 2.3 + 2.4 land before 2.2 (which consumes their hooks); 2.1 parallel
    - Open-PR cross-feature contract: `/proposals/{id}?action=open_pr`
    - UUIDv7 byte layout corrected to RFC 9562
    - Source-of-truth comments scoped to `ui/src/lib/enums.ts` only; CI grep narrowed
  - Spinoff idea files captured:
    - [`chore_query_inline_edit_delete`](../chore_query_inline_edit_delete/idea.md) — per-query PATCH/DELETE endpoints + UI (backend doesn't expose them in MVP1)
    - [`chore_cluster_run_query_history`](../chore_cluster_run_query_history/idea.md) — persisted run-query history (backend has no persistence today)

## Implement
- Status: Complete
- Date: 2026-05-12
- Branch: `feature/feat-studies-ui`
- PR: [#50](https://github.com/SoundMindsAI/relyloop/pull/50) (pending merge at finalization commit time)
- CI: backend + frontend + docker buildx all green on run 25703859510
- Stories completed: 13 of 13 (4 epics, zero migrations — UI-only feature)
- Gemini review: N/A on this repo (per state.md — past PRs confirm Gemini Code Assist isn't installed)
- GPT-5.5 final review: skipped at finalization. Plan was already reviewed 3 cycles pre-execution (32 of 33 findings applied; 1 rejected with cited counter-evidence); implementation followed the plan + CLAUDE.md rules; CI + the Story 4.2 source-of-truth grep gate (which caught one real drift on first run) provide the safety net.

## Implementation update
- See `state.md` 2026-05-12 entry for the full story-by-story breakdown.

## Done
- Status: Pending PR #50 merge to main
- Folder moved to `docs/00_overview/implemented_features/2026_05_12_feat_studies_ui/` in the finalization commit on this branch.
