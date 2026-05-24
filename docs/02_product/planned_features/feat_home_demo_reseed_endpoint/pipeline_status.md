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
- Status: Not started

## Implementation
- Status: Not started
