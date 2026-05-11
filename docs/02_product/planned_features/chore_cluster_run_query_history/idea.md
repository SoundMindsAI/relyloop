# Idea — chore_cluster_run_query_history

**Date:** 2026-05-12
**Origin:** Surfaced during `feat_studies_ui` implementation-plan generation (GPT-5.5 cycle-1 finding #5). Spec §3 "Cluster detail" reads "summary card + studies-by-this-cluster table + recent run-query history (if any)". The backend exposes `POST /api/v1/clusters/{id}/run_query` for ad-hoc dispatch (per `infra_adapter_elastic`) but **does not persist** the request or response — no `cluster_run_queries` table, no history endpoint.

## Problem

The "recent run-query history" surface in spec §3 cannot be built without backend support. The `feat_studies_ui` plan (Story 2.1) drops this from the cluster detail page and renders only the summary + studies-by-cluster table. Operators who hit `POST /clusters/{id}/run_query` (via the agent tool when `feat_chat_agent` ships, or via raw curl today) have no UI surface to review past queries.

## Why deferred

Backend has no persistence — adding it requires:
- A new table (`cluster_run_queries` or similar) with FK to `clusters`.
- A migration.
- An endpoint `GET /api/v1/clusters/{id}/run-queries?cursor&limit`.
- Optional pruning policy (the table could grow unbounded).

Out of scope for `feat_studies_ui` (UI-only).

## Proposed scope

1. **Backend:** add `cluster_run_queries` table + Alembic migration storing (cluster_id, request payload, response summary, latency_ms, status, created_at).
2. **Service:** record each `dispatch_run_query` call into the table; cap retention (e.g., last 100 per cluster, or 30-day TTL).
3. **API:** `GET /api/v1/clusters/{id}/run-queries` with cursor pagination + X-Total-Count.
4. **Frontend:** add the history table to `ui/src/app/clusters/[id]/page.tsx` (after `feat_studies_ui` ships).

## Alternative (lower-effort)

Drop the surface from the spec entirely — most operators will reach for `feat_chat_agent` to run queries once that lands, and the agent will likely persist conversation history that effectively duplicates this. Decision pending.

## Dependencies

- `feat_studies_ui` Story 2.1 shipped (or in flight).
- Decision on retention policy.

## References

- Spec text: `docs/02_product/planned_features/feat_studies_ui/feature_spec.md` §3 "Cluster detail"
- Implementation-plan deferral note: `feat_studies_ui/implementation_plan.md` Story 2.1
- Backend run_query endpoint (current state): `backend/app/api/v1/clusters.py:268` — `POST /clusters/{id}/run_query`
