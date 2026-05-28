# Pipeline Status — bug_demo_clusters_unreachable_in_healthz

## Idea
- Status: Complete (preflight-audited + patched 2026-05-24)
- File: idea.md
- Priority: P2 (`/healthz` observability gap; decoupled from the unrelated banner E2E failure)

## Spec
- Status: Approved
- Date: 2026-05-24
- File: feature_spec.md
- Cross-model review: GPT-5.5 — 3 cycles (cap reached; 18 findings cycle-1+2+3, all accepted)
- Phases: 1 (single-phase bug fix)
- Key decisions (§19 D-1 through D-10):
  - D-1: Option A (fire-and-forget startup warmup)
  - D-2: NO ClusterAggregateHealth response-shape change (Option B rejected)
  - D-3: NO periodic re-warmup cron — only POST-bypassing out-of-band inserts hit the lazy-warm path
  - D-7: FR-7 added — plug the `get_or_probe_health` CredentialsMissing cache-write gap (cycle-1 catch)
  - D-8: Drop `cache_hits`/`probed` counters from FR-5 (cycle-1 — `get_or_probe_health` exposes no source distinction)
  - D-9: Add Redis-ping-WARN at warmup start (cycle-2 lock of Q1)
  - D-10: Split shutdown tests across `test_main_lifespan.py` + `test_cluster_health_warmup.py` (cycle-2 catch)

## Plan
- Status: Approved
- Date: 2026-05-24
- File: implementation_plan.md
- Cross-model review: GPT-5.5 — 3 cycles to cap (11 findings: 6 cycle 1 + 3 cycle 2 + 2 cycle 3; all 11 accepted)
- Stories: 4 (Story 1.1 FR-7 cache-write fix · Story 1.2 warmup service module · Story 1.3 lifespan wiring · Story 1.4 architecture doc)
- Test coverage: 12 new unit cases (2 in test_cluster_service.py · 7 in test_cluster_health_warmup.py · 3 in test_main_lifespan.py) + 3 integration cases
- Phases covered: single phase (no deferred phases)
- Notable cycle catches:
  - Cycle 1 A1 (High): structlog `event` field — first positional arg IS the event field; corrected to use stable identifier as the message
  - Cycle 1 B4 (High): AC-10 missing `await db.commit()` — `repo.create_cluster` only flushes; caller commits
  - Cycle 2 A1: `repo.create_cluster` line range corrected (28-32 → 39-45)
  - Cycle 2 B1: lifespan tests need fakes for Redis/arq/session_factory or they hang on real I/O
  - Cycle 2 B2: shutdown test uses explicit cancel-seen Event instead of weak "no warning" check
  - Cycle 3: bounded polling for both operator-path verification AND AC-8 in-process capture pattern

## Implementation
- Status: Complete
- Date: 2026-05-25
- PR: [#236](https://github.com/SoundMindsAI/relyloop/pull/236) (squash-merged as `70b2ae46`, admin-merged)
- CI in-scope jobs: all green (backend lint+typecheck+tests+coverage, frontend lint+typecheck+tests+build, docker buildx, fast-lane unit)
- CI smoke gate: pre-existing failure from the dashboard banner E2E (same as PR #228 / PR #232 / PR #234); admin-merge precedent applies. Decoupled from this `/healthz` bug per spec §19 D-6.
- Stories completed: 4/4 (1.1 FR-7 cache-write fix · 1.2 warmup service module · 1.3 lifespan wiring · 1.4 data-model.md doc) + integration tests added in phase-gate-fix commit `d3a63bf6`.
- Tests: 16 new/updated cases — 3 in test_cluster_service.py (AC-3 + AC-11) + 7 in test_cluster_health_warmup.py unit + 4 in test_main_lifespan.py incl env-var-gate (AC-1 + AC-7 + env-var test) + 3 contract assertions extended in test_cluster_health_warmup.py integration (AC-8/AC-9/AC-10, skip outside CI service containers)
- Phase-gate review: GPT-5.5 — 1 Medium finding (missing integration test file) accepted + shipped in commit `d3a63bf6`
- Final cross-model review: GPT-5.5 — 4 findings (3 Medium + 1 Low) all accepted; biggest was refactor to per-page session lifecycle (commit `7716a04e`) for bounded memory + cleaner asyncpg pool behavior
- Gemini Code Assist: clean review, zero line-level findings
- CI rounds: 3 fix iterations after PR open — (1) per-page refactor, (2) env-var gate `RELYLOOP_DISABLE_STARTUP_WARMUP` to avoid asyncio interleaving with the latent webhook merge-handler row-lock race, (3) explicit `monkeypatch.delenv` for unit test isolation
- Tangential bug captured: [`bug_webhook_concurrent_merge_race_timing_sensitive`](../../planned_features/02_mvp2/bug_webhook_concurrent_merge_race_timing_sensitive/idea.md) — real production-correctness bug in webhook merge-handler row-lock; deterministically reproducible by adding any second lifespan task; P2 next-ticket candidate

## Branch
- `bug/demo-clusters-unreachable-in-healthz` (deleted post-merge by `gh pr merge --delete-branch`)
