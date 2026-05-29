# chore_ubi_reader_search_after_pagination — exact full-traffic UBI aggregation

**Date:** 2026-05-29
**Status:** Idea — deferred from `feat_ubi_judgments` (found during the rung-3 E2E)
**Origin:** The rung-3 E2E against a real Elasticsearch surfaced that `UbiReader` issued a single `search_batch` with `size=50000`, which exceeds the engine's default `index.max_result_window` (10000) → "all shards failed" → swallowed → spurious `UBI_INSUFFICIENT_DATA`. Fixed by capping the per-scan size at 10000 (a representative sample). This idea tracks the proper fix for exact full-traffic aggregation.
**Depends on:** `feat_ubi_judgments` shipped
**Priority:** P2

## Problem

`UbiReader._scan_ubi_events` / `_scan_ubi_queries` each issue ONE
`search_batch` (a `size`-limited query). To stay under the engine
result-window they now cap at 10000 rows per (target, window). For a
dense cluster (millions of events/month), that's a **sample**, not the
full traffic — CTR/dwell ratings are derived from the first 10k matching
events rather than all of them. The module docstring + `DEFAULT_MAX_EVENTS`
document this.

## Proposed capability

Add `search_after` (point-in-time) pagination to the reader so it can
aggregate the FULL event stream for a window without the 10k cap:

1. Open a PIT on `ubi_events`, scan with `search_after` over a stable
   sort key (e.g. `[timestamp, _shard_doc]`), accumulating into
   `aggregate_features` incrementally.
2. Same for `ubi_queries` if a query set ever exceeds 5000 queries.

This needs either a new adapter method (`scan` / `search_after`) or an
extension to `search_batch` — which touches the `SearchAdapter` Protocol
(Absolute Rule #4 territory), so it's a deliberate, scoped change rather
than an inline tweak. The MVP sample is correct + honest for the demo +
typical query sets; this is the scale upgrade.

## Scope signals

- Backend: `SearchAdapter` Protocol + `ElasticAdapter` (new scan method) +
  `UbiReader` (incremental aggregation). ~200-300 LOC + adapter tests.
- Frontend: none.
- Migration: none.
