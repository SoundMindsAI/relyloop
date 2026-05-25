# 4 demo Elasticsearch clusters report `unreachable` in `/healthz` despite ES + OS containers being healthy

**Date:** 2026-05-24 (preflight-refreshed 2026-05-24 post-PR-#234 merge)
**Status:** Idea — surfaced during PR #232 smoke-cascade unblock on 2026-05-24.
**Priority:** P2 — `/healthz` observability gap. Operators polling `/healthz` see `elasticsearch_clusters: {registered: 4, healthy: 0, unreachable: 4}` and reasonably conclude the demo stack is broken — but [`GET /api/v1/clusters`](../../../../backend/app/api/v1/clusters.py#L196) reports all 4 healthy when called. (Earlier framings of this idea blamed the dashboard banner E2E failure on `/healthz`; that conflation has been corrected — see "Decoupling from the banner E2E failure" below.)
**Origin:** Surfaced during PR #232 smoke investigation. `/healthz` returns:

```json
{
  "elasticsearch_clusters": {"registered": 4, "healthy": 0, "unreachable": 4}
}
```

…even though:
- The `elasticsearch` Docker Compose service is healthy.
- The `opensearch` Docker Compose service is healthy.
- The 4 demo clusters were just seeded by `scripts/seed_meaningful_demos.py` with `base_url=http://elasticsearch:9200` / `http://opensearch:9200` (the container-network hostnames that resolve via Docker DNS).
- The api container can hit `http://elasticsearch:9200/_cluster/health` directly (the basic `subsystems.elasticsearch: "reachable"` field returns OK).

## Root cause (locked after preflight code audit)

`probe_registered_clusters` at [`backend/app/api/probes.py:95-133`](../../../../backend/app/api/probes.py#L95-L133) is a **cache-only aggregate**: it reads `cluster:health:{cluster_id}` from Redis (30s TTL) and never live-probes. The cache-miss branch at line 124-126 explicitly counts ANY cluster without a cached entry as `unreachable`:

```python
cached = await read_cached_health(redis, c.id)
if cached is None or cached.status in ("red", "unreachable"):
    unreachable += 1
else:
    healthy += 1
```

This is **design intent** per CLAUDE.md Absolute Rule #11 — `/healthz` must stay under the 200ms per-probe budget, so it cannot live-probe N user clusters synchronously. The cache is populated lazily by `cluster_svc.get_or_probe_health` at [`backend/app/services/cluster.py:192-215`](../../../../backend/app/services/cluster.py#L192-L215), which fires on demand from `GET /api/v1/clusters` and `GET /api/v1/clusters/{id}`.

**So:** at smoke-test time, after `make up` + `make seed-clusters` + `make seed-demo`, NOTHING has yet exercised any `/api/v1/clusters*` endpoint. The cache is empty for all 4 demo cluster IDs. `/healthz` faithfully reports `unreachable: 4` per its cache-miss-equals-unreachable convention. It is **NOT** an auth, engine-type, endpoint, or registration failure.

### Hypotheses ruled out during preflight code audit

1. ~~**Auth mismatch.**~~ Even if `cluster_credentials.yaml` were missing entries, that surfaces inside `get_or_probe_health` (cluster.py:202-208 catches `CredentialsMissing` and writes `HealthStatus(status="unreachable", error=...)` to the cache) — but the cache would then have an entry. The observed symptom is cache MISS (empty), not cached-unreachable. So auth-resolution isn't the issue at `/healthz` time.
2. ~~**Engine-type mismatch.**~~ The aggregate at `probes.py:124` doesn't construct adapters at all; it only reads the Redis cache. Engine type can't matter here.
3. ~~**Health-check endpoint difference.**~~ Same reasoning as #2 — no probe runs inside `probe_registered_clusters`.
4. **Async timing / cache empty.** **CONFIRMED ROOT CAUSE** — Redis `cluster:health:*` cache is empty until the first `GET /api/v1/clusters` (or `/{id}`) call populates it. `/healthz` then reads zero entries and counts everything as `unreachable`.

## Why this matters

`/healthz` is the operator's single-pane diagnostic for "is the stack healthy?". When the cluster-aggregate sub-field reports `unreachable: 4` post-seed, the operator has to either tail logs or hit `/api/v1/clusters` separately to find out the clusters are actually fine. That defeats the value of a one-call health dashboard.

This is the same observability-gap class as [`bug_openai_capability_check_incapable_on_valid_key`](../../../00_overview/implemented_features/2026_05_24_bug_openai_capability_check_incapable_on_valid_key/idea.md) (PR #234, merged 2026-05-24) — `/healthz` correctly reports an internal state, but the state is misleading without context.

## Decoupling from the banner E2E failure

Earlier framings (and the original idea text) claimed this bug "blocks dashboard E2E tests" because `useClusters` allegedly filters by health. **That claim is wrong** and has been removed:

- [`backend/app/api/v1/clusters.py:196-259`](../../../../backend/app/api/v1/clusters.py#L196-L259) `list_clusters` returns ALL registered clusters with their health attached as a field; it does NOT filter by `health.status`.
- [`ui/src/components/dashboard/demo-data-banner.tsx:90-97`](../../../../ui/src/components/dashboard/demo-data-banner.tsx#L90-L97) only checks `!dismissed && !isError && data && presentDemos.length > 0`. Health is irrelevant to banner rendering.

The banner test failure observed during PR #234's CI run (`dashboard.spec.ts:57` + `dashboard-reseed.spec.ts:95`) IS a real bug, but it has a different root cause (likely globalTeardown-or-other-spec cleanup deleting demo cluster rows mid-suite — see the `cluster` 204 DELETE flood at the end of the smoke Playwright log). **That belongs in its own bug folder.** This idea stays scoped to the `/healthz` aggregate observability gap.

## Reproducing locally

```bash
make up                                         # auto-seeds (if first-run)
make seed-demo FORCE=1                          # explicit re-seed
# Immediately poll /healthz BEFORE hitting /api/v1/clusters — cache is empty:
curl -s http://127.0.0.1:8000/healthz | jq '.subsystems.elasticsearch_clusters'
# Expected: {"registered": 4, "healthy": 0, "unreachable": 4}

# Now warm the cache via the list endpoint (which calls get_or_probe_health for each cluster):
curl -s 'http://127.0.0.1:8000/api/v1/clusters?limit=200' | jq '.data[].name, .data[].health_check.status'
# Expected: 4 names + 4× "green" (or "yellow") health_check.status entries

# Within 30s (TTL), /healthz now reflects the warm cache:
curl -s http://127.0.0.1:8000/healthz | jq '.subsystems.elasticsearch_clusters'
# Expected: {"registered": 4, "healthy": 4, "unreachable": 0}
```

If step 1 shows `unreachable: 4` AND step 2 returns all clusters with `health_check.status in {"green","yellow"}` AND step 3 then shows `healthy: 4`, the cache-population race is confirmed and Hypotheses #1-3 are definitively ruled out.

## Suggested fix paths (forks for /spec-gen to pick from)

Three viable options. The right call is a product/operator-experience judgment, not a code-correctness call — all three solve the observability gap; they differ on cost vs. side-effects.

### Option A (recommended) — Fire-and-forget startup cluster-health warmup

Add a `run_cluster_health_warmup_background` task to `backend/app/main.py` startup that pages through all registered clusters and calls `cluster_svc.get_or_probe_health(redis, cluster)` once per row. Parallels the existing OpenAI capability check pattern at [`backend/app/llm/capability_check.py:404-431`](../../../../backend/app/llm/capability_check.py#L404-L431) (fire-and-forget, swallows all exceptions, never crashes the API process).

- **Pros:** zero new endpoints, zero schema change, zero `/healthz` budget impact (warmup runs out-of-band at startup). Within ~5s of boot, `/healthz` reports accurate aggregate.
- **Cons:** if the operator registers a NEW cluster post-startup, that cluster shows `unreachable` until something else probes it. Mitigation: also run a periodic warmup job (every 30s, matching the cache TTL) — but that adds an Arq cron and arguably exceeds the bug's scope.
- **Scope:** ~50 LOC + 2-3 unit tests. Fits comfortably in `/impl-execute --ad-hoc` mode.

### Option B — Add a third `unprobed` count to `ClusterAggregateHealth`

Distinguish cache-miss (`unprobed`) from cached-unreachable (`unreachable`) in the response shape:

```python
class ClusterAggregateHealth(BaseModel):
    registered: int
    healthy: int
    unreachable: int    # cached status in {"red", "unreachable"}
    unprobed: int       # NEW: cache miss
```

- **Pros:** truthfully communicates the actual internal state — `unprobed` literally means "we haven't measured yet." No background task, no extra Redis writes.
- **Cons:** breaking change to the `/healthz` response shape (new required field). Existing consumers (operator scripts, smoke gates) that count "non-healthy" rows must update. Operators still have to refresh `/healthz` to see clusters move from `unprobed → healthy`, just less alarmingly than `unreachable → healthy`.
- **Scope:** ~30 LOC backend + contract test + 1-line doc update. Also fits ad-hoc mode.

### Option C — Accept current behavior, document it

The current behavior IS correct under "cache is the source of truth and 30s stale is fine" semantics. Add a note to [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md) (or the `/healthz` doc) explaining that `elasticsearch_clusters.unreachable` includes "not-yet-probed since boot" and operators should call `GET /api/v1/clusters` to warm the cache.

- **Pros:** zero code change, zero risk.
- **Cons:** the operator experience stays poor — same false alarm next boot. Operator hates docs that explain why a tool is misleading instead of fixing it.
- **Scope:** doc-only.

**Recommended default for /spec-gen:** Option A. The 30-second warmup cron is the only contested piece (do we accept new-cluster-registered-post-boot showing `unreachable` until first request, or pay for a cron?); /spec-gen can lock that decision.

## Why deferred

Out of scope for PR #232 (`feat_digest_executable_followups_swap_template`). Captured here so the next infra-cleanup PR can investigate.

The dashboard E2E test failure that PR #232's smoke surfaced is now known to be **separate** from this `/healthz` bug (see "Decoupling from the banner E2E failure" above). Don't mark those tests `@pytest.mark.xfail` based on this idea — they need their own root-cause investigation, captured under a different bug folder.

## Open questions for /spec-gen

1. **Pick a fix path.** Option A vs Option B vs Option C from "Suggested fix paths" above. Recommended default: A (fire-and-forget startup warmup).
2. **If Option A: handle clusters registered post-startup.** Either (a) warm them lazily on first `/api/v1/clusters` call (status quo + accept brief `unreachable` window — 5 minutes per 30s TTL), or (b) add a 30s Arq cron that re-warms all clusters (extra infra). Recommended default: (a) — clusters registered post-boot are rare in MVP1.
3. **If Option B: handle the breaking response-shape change for existing consumers.** Audit existing `/healthz` consumers (smoke gate `_wait_healthy`, dashboard, operator scripts) for hardcoded `unreachable` field-name reads. Recommended default: phased — add `unprobed` as required-but-defaulted field and emit a deprecation note in `docs/01_architecture/api-conventions.md`.

## Relationship to other work

- **Sibling bug (shipped):** [`bug_openai_capability_check_incapable_on_valid_key`](../../../00_overview/implemented_features/2026_05_24_bug_openai_capability_check_incapable_on_valid_key/idea.md) — shipped 2026-05-24 as PR #234 squash `d69189db`. Resolved the OTHER half of the smoke-cascade. This bug is now the only remaining `/healthz`-side blocker for smoke gate cleanup.
- **PR #228** (`feat_home_demo_reseed_endpoint`, merged 2026-05-24) added the dashboard reseed button + introduced the `make seed-demo` flow but didn't catch this regression because PR #228 was admin-merged with smoke red.
- **PR #188** (`feat_home_first_run_demo_nudge`, merged 2026-05-22) added the original dashboard banner test — also admin-merged at the time per the same pattern. The banner test failure visible since 2026-05-22 is NOT this `/healthz` bug (banner doesn't read `/healthz`); it has a separate root cause that should be captured as `bug_dashboard_banner_e2e_demo_clusters_deleted_mid_suite/` (or similar) once investigated. Likely culprit per the preflight code reading: globalTeardown's cleanup registry (`ui/tests/e2e/global-teardown.ts:124-150`) is deleting cluster rows that an earlier spec registered for cleanup — verify by checking which spec's `appendForCleanup` calls land in the registry. **Not in scope here.**
