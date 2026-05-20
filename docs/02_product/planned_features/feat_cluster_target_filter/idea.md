# Per-cluster target filter — scope a cluster registration to a subset of indices

**Date:** 2026-05-20
**Status:** Idea — surfaced 2026-05-20 while seeding meaningful demo scenarios for the post-`feat_create_study_target_autocomplete` state. With 4 registered clusters all backed by the same physical Elasticsearch container, every cluster's `GET /api/v1/clusters/{id}/targets` returns the same 3 indices (`products`, `docs-articles`, `job-listings`). This is technically correct (the engine sees what it sees) but it makes the dropdown picker confusing — an operator picking `acme-products-prod` shouldn't see `job-listings` and `docs-articles` as candidate targets.
**Origin:** Discovery during the demo-data re-seed session that followed PR #165 / PR #166 (`feat_create_study_target_autocomplete` shipped + finalized). The demo scenarios are documented at [`/tmp/seed_meaningful_demos.py`](/tmp/seed_meaningful_demos.py) in the user's local checkout — they intentionally model the real-world case of "one big ES shared across many teams" that's common at enterprise scale.
**Depends on:** [`feat_create_study_target_autocomplete`](../../00_overview/implemented_features/2026_05_20_feat_create_study_target_autocomplete/) — the targets endpoint + dropdown UI ship there. This feature adds a scoping layer on top.

## Problem

Today the `clusters` table has no way to express "this logical cluster registration is scoped to a subset of the engine's indices." `ElasticAdapter.list_targets()` calls `_cat/indices` and returns every user-facing index (filtering only system indices starting with `.`). The new `GET /api/v1/clusters/{id}/targets` endpoint surfaces all of them to the operator.

Two real-world cases this hurts:

1. **Multi-team shared ES** — many enterprises run ONE big production ES cluster with indices owned by different teams (`team-a-*`, `team-b-*`, `products-*`, `logs-*`). A relevance engineer working on `products` shouldn't be picking from `logs-prod-2025-12-18` in the wizard. They should register the cluster once as "production-products" and have it expose only the `products-*` family.

2. **Demo / dev environments** — exactly the case that surfaced this idea. Sharing one ES across multiple logical "clusters" is a legitimate dev pattern. The demo state has 3 logical clusters (`acme-products-prod`, `corp-docs-search`, `jobs-marketplace-prod`) that each should expose only their own index — but right now the dropdown cross-pollinates.

Both cases want the same primitive: a per-cluster filter that scopes `list_targets()` results.

## Proposed capabilities

### Capability 1 — `clusters.target_filter` column + filter application in `list_targets()`

- Add an optional `target_filter` column to `clusters` (`VARCHAR(256) NULL`). When set, it's a glob pattern (the simplest API; `fnmatch.fnmatch()` on the Python side) that filters the names returned by `_cat/indices`.
- Examples: `products*`, `docs-*`, `team-a-{products,reviews}` (compound globs are out of scope; single-pattern only).
- `null` (default) → no filter; matches today's behavior (full `_cat/indices` minus system indices).
- Filter is applied in the adapter, AFTER the system-index exclusion. Both filters compose: `not name.startswith('.') AND fnmatch(name, target_filter)`.
- Stored as authored (no normalization, no case-folding) so the operator's input is preserved verbatim — but the match itself is case-sensitive (matches ES's case-sensitive index naming).

### Capability 2 — Form field on cluster registration + edit

- Add a `Target filter (optional)` input to the registration modal, placed below `Notes`. Helper text: `"Glob pattern restricting which indices appear in the target picker. Example: products* matches every index starting with 'products'. Leave blank to show every user-facing index."`.
- Allow editing on existing clusters (via `PATCH /api/v1/clusters/{id}` if it exists, or via a future edit affordance — investigate which is true today).

### Capability 3 — Empty-state nudge when filter excludes everything

If `target_filter` is set but matches zero indices, the `EntitySelect` empty-state should say `"No targets match filter \"<filter>\" on this cluster. Edit the cluster to relax the filter."` instead of the generic `"No targets found on this cluster."` — so the operator knows the filter (not the cluster) is the cause.

## Scope signals

- **Backend:** ~50 LOC.
  - 1 Alembic migration: `ALTER TABLE clusters ADD COLUMN target_filter VARCHAR(256) NULL;` + downgrade.
  - `Cluster` ORM model: add the column.
  - `CreateClusterRequest` Pydantic: add `target_filter: str | None`.
  - `ElasticAdapter.list_targets()`: pass the filter through (or take it via a new parameter); apply `fnmatch.fnmatch(name, filter)` if non-null.
  - 4 new unit tests: filter null = pass-through; filter matches subset; filter matches none; filter pattern with `*` glob.
  - 1 integration test: register cluster with `target_filter=products*`, assert `GET /clusters/{id}/targets` returns only matching indices.
- **Frontend:** ~30 LOC.
  - New optional input field on the cluster registration form (`register-cluster-modal.tsx`).
  - `useClusterTargets` hook: no change (the filter is server-side).
  - Update the `EntitySelect`'s `emptyState.message` in the create-study modal to differentiate "no targets at all" vs "filter excluded everything" — needs the consumer to know the cluster's `target_filter` value (fetch from `/clusters/{id}` detail).
  - 2 new vitest cases: registration with filter; empty-state message reflects filter presence.
- **Migration:** Reversible. `add_column` is idempotency-guarded by Alembic's standard pattern.
- **Config:** None.
- **Audit events:** N/A (MVP1, pre-audit_log). When MVP2 lands, `cluster.target_filter` updates should emit `CLUSTER_TARGET_FILTER_CHANGED` events.

## Why not implemented inline today

It's a real feature with a migration + UI change — qualifies for `/pipeline` over `/bug-fix` or `/impl-execute --ad-hoc`. Modest scope (~1 day with the full pipeline ceremony, half-day if I cheat the protocol) but the cross-layer surface (DB → adapter → API → UI → demo) makes it worth the spec/plan cycles to catch design holes early.

## Relationship to other work

- **Builds on** [`feat_create_study_target_autocomplete`](../../00_overview/implemented_features/2026_05_20_feat_create_study_target_autocomplete/) — the targets endpoint + dropdown ship there; this feature scopes their output.
- **Coordinate-only with** the demo seed script at `/tmp/seed_meaningful_demos.py` (uncommitted operator artifact) — after this feature ships, re-seed the demo with `target_filter` set on each cluster (`acme-products-prod` → `products*`, `corp-docs-search` → `docs-*`, `jobs-marketplace-prod` → `job-*`) and the dropdown will accurately show only that cluster's intended indices.
- **Sibling pattern to** the `clusters.engine_config` JSONB column (also optional, also stored on the cluster row) — both are "optional metadata refining how this cluster registration behaves." Different concerns though (config = how to query; target_filter = which indices to expose).

## Locked decisions (preflight 2026-05-20)

1. **Filter syntax: glob (`fnmatch`-style).** Simpler operator mental model; common pattern (`products*`, `team-a-*`, `docs-{en,fr}-*`). Validate at registration: `fnmatch.translate()` must not raise; pattern length ≤ 256 chars (column cap). Rejected alternative: regex — more powerful but error-prone, and the operator-facing surface (a single input field on a registration form) is exactly where regex syntax errors hurt.
2. **Filter application: client-side in `ElasticAdapter.list_targets()`** after parsing the `_cat/indices` response. ES's `?h=` parameter selects which columns the response includes, not which indices match — it can't filter server-side via glob. Client-side is portable to OpenSearch + future engines (Fusion, Solr) without per-engine special cases. Cost: a 1ms loop over the (typically ≤200) rows.
3. **MVP scope: create-only filter; no PATCH endpoint.** Verified by preflight: `/api/v1/clusters/{cluster_id}` currently supports GET + DELETE only — there's no PATCH route, no `update_cluster` service helper, no `UpdateClusterRequest` Pydantic, no edit modal. Adding all 4 would roughly double the feature's scope (~50 LOC backend + UI form for filter edit) and isn't strictly required for the originating use case (re-seed demo with filters set at registration; production operators can DELETE + re-register if they need to change a filter). PATCH ships as `chore_cluster_update_target_filter` (or similar) when there's a real customer request.
4. **No cascade validation when filter excludes an existing study's `target`.** Existing studies on a cluster reference a specific `target` string. If the operator adds a filter that no longer matches that `target`, the study itself continues to work (no FK relationship; the cluster→target binding is just a string column on `studies`). The picker just won't offer the now-out-of-scope target for NEW studies. Documenting this explicitly so future reviewers don't add a "block filter changes that would orphan a study" guard.

## Open questions for /spec-gen

None remaining — all 4 forks locked above. /spec-gen can proceed without product-decision pauses.
