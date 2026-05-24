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
- Status: Not started

## Implementation
- Status: Not started

## Branch
- `bug/demo-clusters-unreachable-in-healthz`
