# Rank-ordered FTS results (`ORDER BY ts_rank DESC`)

**Date:** 2026-05-16
**Status:** Idea — deferred from `feat_data_table_primitive` (MVP1) per spec §16.
**Priority:** Backlog — explicitly held for MVP2 (folder name suffix). Re-evaluate when MVP2 work begins; the tsvector + GIN indexes are already on disk so the actual implementation is small.
**Origin:** [`feat_data_table_primitive/feature_spec.md` §16 lines 896–900](../../../implemented_features/2026_05_16_feat_data_table_primitive/feature_spec.md). The 6 Postgres `tsvector` columns + GIN indexes already exist (migrations `0008`–`0013`); the `plainto_tsquery('english', :q)` predicate is wired into 6 list endpoints. Only the ORDER BY and the cursor encoding need to change.
**Depends on:** `feat_data_table_primitive` (PR open on `feat/data-table-primitive`). Cursor pagination is already keyset-based on `(created_at, id)`.

## Problem

`feat_data_table_primitive` shipped filter-only FTS — `?q=foo` matches rows where `search_vector @@ plainto_tsquery('english', 'foo')` is true but orders results by `created_at DESC, id DESC` (the default cursor key). For long query strings or short result sets the ordering is fine. For ambiguous queries it isn't — a user searching `clusters?q=prod` against 50 clusters whose names share the token "prod" gets the newest matches first, not the most relevant.

True rank-ordered FTS would `ORDER BY ts_rank(search_vector, plainto_tsquery('english', :q)) DESC, created_at DESC, id DESC` — but the existing keyset cursor only encodes `(created_at, id)`. A cursor predicate that pages forward on `(ts_rank, created_at, id)` either needs the cursor to encode the float `ts_rank` (brittle across pages because floats don't have a stable lexicographic key) or needs offset/limit pagination (banned by `api-conventions.md` §"Anti-patterns").

## Proposed capabilities

### Rank-ordered FTS ordering when `?q=` is present

- Each of the 6 search-enabled list endpoints (`clusters`, `studies`, `query_sets`, `query_templates`, `judgment_lists`, `conversations`) gains a conditional ORDER BY: when `?q=` is set, sort by `ts_rank DESC` then the existing `(created_at, id)` tiebreaker; otherwise unchanged.
- The frontend's `<DataTable>` toolbar gains a "Sort by relevance" indicator when `?q=` is active so users know the column-header sort is overridden.

### Cursor encoding that survives float-sort boundaries

Two reasonable approaches; the spec write-up should pick one after a `/preflight` against Postgres semantics:

1. **Rank-bucketed cursor.** Encode `(rank_bucket: int, created_at, id)` where `rank_bucket = floor(ts_rank * 1e6)`. Page boundaries are integer-comparable so the keyset predicate is exact; the bucket size is conservative enough that two rows with rank differing by ~1e-6 still page in a deterministic order via the `(created_at, id)` tiebreaker.
2. **Materialized rank column.** Add a `last_search_score REAL` column populated by the API on every `?q=` request (per-request, not stored long-term). Cursor encodes `(last_search_score, created_at, id)`. Heavier write surface but predictable.

The MVP1 cursor format is opaque base64-JSON, so either approach is a backend-only change — clients never construct cursors.

### Backward-compat: cursor invalidation on sort change

The existing `?sort=` surface already drops the cursor when sort changes. The same rule needs to extend to `?q=` changes — going from `?q=foo` to `?q=bar` invalidates any in-flight cursor because the rank ordering changes.

## Scope signals

- **Backend:** ~150–250 LOC across 6 list-endpoint handlers + the shared cursor encoder/decoder helpers + 1 new repo function (`select_with_rank` or similar). Touches `backend/app/api/v1/<resource>.py` × 6, `backend/app/services/cursor.py`, possibly a new test helper.
- **Frontend:** small — the `<DataTable>` toolbar adds a "Sort by relevance" pill when `q` is active; the rest of the URL contract is unchanged.
- **Migration:** none if approach (1) chosen; one schema migration if approach (2) chosen (add `last_search_score` to 6 tables — though as a NULLable transient field this is borderline-not-needed).
- **Config:** none.
- **Audit events:** none (FTS reads, not mutations).

## Why deferred

Cursor encoding for `ts_rank` ordering is non-trivial — the spec §16 calls it out explicitly:

> True rank-ordered FTS (`ORDER BY ts_rank DESC`) would require either encoding `ts_rank` into the opaque cursor (custom serialization across 6 endpoints + brittle floating-point key boundaries) or replacing keyset cursor pagination with offset/limit (banned by api-conventions.md "Anti-patterns").

The simpler MVP1 design (filter-only) is correct and useful as-is. Rank ordering becomes valuable when:

- Result sets routinely exceed 50 rows per query (MVP1's typical alpha install is well under that).
- The operator persona shifts from "I know what I'm looking for, narrow my list" to "I'm exploring, surface the best matches first" — which is more an MVP3+ multi-tenant scale concern than an MVP1 single-tenant workflow.

When ClickHouse or a search-side ranking surface lands at MVP2, the rank-ordering question can be revisited with a real perf budget (the current MVP1 backend doesn't even surface `ts_rank` in any UI hook).

## Relationship to other work

- **Builds on** `feat_data_table_primitive` — every required piece of plumbing (the 6 `search_vector` columns, the `plainto_tsquery` predicate, the 6 endpoint surfaces, the `<DataTable>` search input) already exists. This idea is purely a backend ordering change plus a small frontend indicator.
- **Does not conflict with** any other planned feature. The `?sort=` surface remains the explicit override — when both `?q=` and `?sort=` are present, the user-supplied sort wins.
