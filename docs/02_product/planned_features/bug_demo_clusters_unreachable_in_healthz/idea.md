# 4 demo Elasticsearch clusters report `unreachable` in `/healthz` despite ES + OS containers being healthy

**Date:** 2026-05-24
**Status:** Idea — surfaced during PR #232 smoke-cascade unblock on 2026-05-24.
**Priority:** P2 — blocks dashboard E2E tests (`dashboard.spec.ts` + `dashboard-reseed.spec.ts`) from passing in smoke. The banner-conditional logic short-circuits if `useClusters` returns no demo clusters, so the banner doesn't render and the test fails with `getByTestId('demo-data-banner') element(s) not found`.
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

## Hypothesis

The per-cluster health probe at `/api/v1/clusters/{id}` (or wherever `elasticsearch_clusters.healthy` is computed in `/healthz`) is using a different reachability test from the `subsystems.elasticsearch` top-level field. Possibilities:

1. **Auth mismatch.** The demo clusters in `scripts/seed_meaningful_demos.py` are registered with `auth_kind=es_basic` and `credentials_ref=...` pointing at a credentials file that may not exist or may have wrong creds. The probe attempts auth → fails → reports unreachable. (The top-level `subsystems.elasticsearch` probe is anonymous, so it succeeds.)
2. **Engine-type mismatch.** Demo cluster for news is registered against OpenSearch but probed with ES adapter code (or vice versa) → wrong client → fails.
3. **Health-check endpoint difference.** Per-cluster probes hit `/_cluster/health` or `/_cat/health`; the cluster may require a different endpoint for auth-aware health checks.
4. **Async timing.** The per-cluster health check runs on a background timer and the snapshot at health-check time is stale (last result was before clusters were re-seeded by `make seed-demo FORCE=1` after TRUNCATE+reseed).

## Why this matters

The dashboard banner test (`ui/tests/e2e/dashboard.spec.ts:47`) navigates to `/`, expects `getByTestId('demo-data-banner')` to be visible, and asserts `acme-products-prod` in the body. The banner only renders when `useClusters({sort, limit, enabled}).data.data` includes a cluster matching `isDemoClusterName`. If the front-end fetches `/api/v1/clusters` and the API filters out "unreachable" clusters from that list (OR if the `useClusters` query is otherwise blocked), the banner returns null. **Need to verify whether `/api/v1/clusters` returns ALL registered clusters or only healthy ones** — that's the next investigation step.

## Reproducing locally

```bash
make up                                         # auto-seeds the 4 demos (since stack is empty)
make seed-demo FORCE=1                          # explicit re-seed
curl -s http://127.0.0.1:8000/healthz | jq '.elasticsearch_clusters'
curl -s http://127.0.0.1:8000/api/v1/clusters?limit=200 | jq '.data[].name, .data[].health_check'
```

If the 4 demo cluster names are present in `/api/v1/clusters` AND their `health_check.status` is `"unreachable"` (or similar non-OK value), reproduce confirmed.

## Suggested fix path

1. **Identify which probe code path is failing.** Grep for `elasticsearch_clusters` in `backend/app/api/health.py` and `backend/app/services/cluster_health.py` (or wherever per-cluster health snapshots live). Add a one-shot debug log emitting the URL + headers + response body for the per-cluster probe.
2. **Check the `credentials_ref` resolution.** The demos register clusters with `credentials_ref="local-es"` etc.; the api container must have a `./secrets/cluster_credentials.yaml` with matching keys. Smoke job's `Pre-generate secrets` step writes this file — verify the demo cluster names match.
3. **If auth mismatch is the cause**: either fix the demo seed script to use credentials that match the smoke's `cluster_credentials.yaml`, or relax the probe to fall back to anonymous when auth fails (the local ES container has security disabled per `docs/01_architecture/deployment.md`).

## Why deferred

Out of scope for PR #232 (`feat_digest_executable_followups_swap_template`). Capturing here so the next infra-cleanup PR can investigate. The dashboard E2E tests should be marked `@pytest.mark.xfail` or moved out of the smoke playwright run until this is resolved — but those changes are themselves their own PR.

## Relationship to other work

- **Sibling bug:** [`bug_openai_capability_check_incapable_on_valid_key`](../bug_openai_capability_check_incapable_on_valid_key/idea.md) — together these two are the remaining smoke-gate blockers as of 2026-05-24.
- **PR #228** (`feat_home_demo_reseed_endpoint`, merged 2026-05-24) added the dashboard reseed button + introduced the `make seed-demo` flow but didn't catch this regression because PR #228 was admin-merged with smoke red.
- **PR #188** (`feat_home_first_run_demo_nudge`, merged 2026-05-22) added the original dashboard banner test — also admin-merged at the time per the same pattern. So the test has been failing for everyone since 2026-05-22.
