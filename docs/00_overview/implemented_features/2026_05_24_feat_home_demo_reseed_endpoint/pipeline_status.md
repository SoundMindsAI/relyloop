# Pipeline Status — feat_home_demo_reseed_endpoint

## Idea
- Status: Complete
- File: idea.md
- /idea-preflight applied 2026-05-23 (commit e5282741): symbol-name fix, ES/OS index-cleanup step added, D1/D2/D3 locked, Q1/Q2/Q3 deferred to spec.

## Spec
- Status: Approved
- Date: 2026-05-23
- File: feature_spec.md
- Cross-model review: GPT-5.5 (model `gpt-5.5`) — **14 cycles to convergence.** Cycle 14 returned empty findings; all prior cycles' High-severity findings were accepted and patched. Key design pivots driven by cross-model review:
  - Cycle 1: TRUNCATE-commits-before-self-call + session-level advisory lock + cleanup-re-wipes invariant (4 findings accepted).
  - Cycle 2-3: Removed outer `asyncio.wait_for` and `SEED_TIMEOUT` entirely; reseed runs to natural Python-level completion; per-call `httpx` ceiling only.
  - Cycle 4-5: Stale-text cleanup + dual-client design (`api_client` vs `engine_client`).
  - Cycle 6: Advisory-lock connection-pinning (dedicated `AsyncConnection`, not relying on `AsyncSession` affinity).
  - Cycle 7: In-container engine base-URL resolver (`_resolve_engine_base_url` translates CLI's `localhost:9200/9201` → Compose DNS `elasticsearch/opensearch:9200/9201`).
  - Cycle 8-13: Tightened the `httpx.ReadTimeout` recovery contract to require `docker compose restart api` before retry (naive retry races abandoned handler's late commit); aligned toast/UX wording.
- Phases: single-phase delivery (no Phase 2 deferred).

## Plan
- Status: Approved
- Date: 2026-05-23
- File: implementation_plan.md
- Cross-model review: GPT-5.5 ran 14 cycles. Each cycle introduced 1-2 net-new findings that were accepted and patched (the plan has a hard architecture — dual httpx clients, session-level advisory lock on dedicated pinned `AsyncConnection`, no outer `asyncio.wait_for` (per-call HTTP ceiling only), `httpx.ReadTimeout` restart-then-retry recovery, in-process uvicorn integration-test topology with thread-safe AC-12 synchronization, AC-5 monkeypatched mid-loop engine failure, AC-13 explicit `demo_reseed_api_call_started` logs, AC-16 classid/objid `pg_locks` derivation). Pattern converged with diminishing findings (4 → 2 → 3 → 2 → 4 → 3 → 2 → 1 → 2 → 3 → 2 → 2 → 1 → 2). Plan ships with documented residuals on (a) `httpx.ReadTimeout` server-side late-commit recovery requires `docker compose restart api` (deliberate; alternative is server-side fencing primitives out of scope for MVP1), (b) AC-5 uses monkeypatched engine failure not container-stop (spec amended cycle 13 to allow either). All 16 ACs assigned to stories.
- Stories: 8 stories across 3 epics
  - Epic 1 (backend): Story 1.0 (Settings field), Story 1.1 (service module), Story 1.2 (route handler)
  - Epic 2 (frontend): Story 2.1 (dashboard button + dialog + vitest)
  - Epic 3 (tests + docs): Story 3.1 (contract tests), Story 3.2 (integration tests), Story 3.3 (Playwright E2E), Story 3.4 (runbook + api-conventions)
- Phases covered: single-phase delivery (no deferred phases per spec §3 Phase boundaries).

## Implementation
- Status: Complete (PR #228, merged 2026-05-24 as squash commit `ad6ff826`)
- Adjudicated 2 Gemini Code Assist comments (both Medium, both accepted) + 5 GPT-5.5 final-review findings (1 High + 2 Medium accepted, 1 Medium rejected as stale, 1 Low deferred).
