# chore_ubi_reader_search_after_pagination — exact full-traffic UBI aggregation

**Date:** 2026-05-29 (preflight-refreshed 2026-06-02)
**Status:** Idea — deferred from `feat_ubi_judgments` (found during the rung-3 E2E); preflighted + forks locked 2026-06-02
**Origin:** The rung-3 E2E against a real Elasticsearch surfaced that `UbiReader` issued a single `search_batch` with `size=50000`, which exceeds the engine's default `index.max_result_window` (10000) → "all shards failed" → swallowed → spurious `UBI_INSUFFICIENT_DATA`. Fixed by capping the per-scan size at `ES_MAX_RESULT_WINDOW` (10000) — see `backend/app/services/ubi_reader.py:78-105` (`ES_MAX_RESULT_WINDOW`, `DEFAULT_MAX_EVENTS`, `DEFAULT_MAX_QUERIES`). This idea tracks the proper fix for exact full-traffic aggregation.
**Depends on:** `feat_ubi_judgments` shipped (judgment generation) **and** `infra_adapter_solr` shipped (third engine — see capability note below). Both shipped.
**Priority:** P2

## Problem

`UbiReader._scan_ubi_events` (`backend/app/services/ubi_reader.py:450-523`)
and `_scan_ubi_queries` (`:389-448`) each issue ONE `search_batch`
(a `size`/`rows`-limited query) per (target, window). To stay under the
engine result-window they clamp to `min(max_events, ES_MAX_RESULT_WINDOW)`
= 10000 rows (`DEFAULT_MAX_EVENTS = ES_MAX_RESULT_WINDOW`, `:94-105`;
`DEFAULT_MAX_QUERIES = 5000`, `:91-92`). For a dense cluster (millions of
events/month), that's a **sample**, not the full traffic — CTR/dwell
ratings are derived from the first 10k matching events rather than all of
them. The module docstring + `DEFAULT_MAX_EVENTS` docstring already point
at this folder as the tracked scale upgrade.

**Three engines, two pagination idioms.** `_scan_ubi_events` already
branches on `self._adapter.engine_type == "solr"` to emit Solr request
params (`_build_solr_ubi_body`, `:124-176`) vs an ES/OpenSearch Query DSL
body. The full-traffic fix must therefore work on all three shipped
engines (`elasticsearch`, `opensearch`, `solr` — see
`EngineType` Literal in `backend/app/adapters/protocol.py:31`):
ES + OpenSearch paginate with `search_after` over a stable sort key
(optionally inside a Point-in-Time snapshot — both support `/<index>/_pit`);
**Solr has no PIT and uses `cursorMark`** instead. There is already a
working precedent for exactly this two-idiom split in the Protocol:
`SearchAdapter.list_documents` (`protocol.py:281-304`) returns a
`DocumentPage` carrying both a per-hit `sort` value (ES `search_after`
continuation) **and** an additive `next_cursor_token` (Solr
`nextCursorMark`) — see `ElasticAdapter.list_documents`
(`elastic.py:767-859`) and `SolrAdapter.list_documents`
(`solr.py:1577-1690`).

## Proposed capability (forks locked — see Decisions)

Add a unified, engine-neutral **cursor-scan** to the adapter Protocol so
`UbiReader` can iterate the FULL event stream for a window without the 10k
cap, accumulating into `aggregate_features` incrementally:

1. New Protocol method `scan_all(...)` on `SearchAdapter` (NOT an extension
   of `search_batch` — see Decision D-1). It yields successive pages of
   `ScoredHit`s plus an opaque continuation cursor; the adapter hides the
   ES/OpenSearch `search_after`(+PIT) vs Solr `cursorMark` difference
   behind one return shape, exactly as `list_documents` already does.
2. `UbiReader._scan_ubi_events` / `_scan_ubi_queries` loop `scan_all`
   until the cursor terminates, folding each page into the event/query
   accumulators rather than materializing all rows then aggregating.
3. The 10k clamp becomes a safety ceiling (`max_events`/`max_queries` cap
   the total scanned, default raised or made unbounded — see Decision
   D-3), not a per-call `size` limit.

## Decisions locked (2026-06-02 preflight)

- **D-1 — New `scan_all` Protocol method, not an extended `search_batch`.**
  `search_batch` is the multi-query `_msearch` hot path (Optuna trial
  runner issues N queries in one call; its `query_id` → hits mapping shape
  and `strict_errors`/`timeout` semantics are tuned for that). Bolting
  stateful pagination onto it would overload one method with two
  incompatible contracts. A dedicated single-target `scan_all` mirrors the
  precedent already set by `list_documents` (also a separate method, also
  cursor-based, also abstracting ES `search_after` vs Solr `cursorMark`).
- **D-2 — ES/OpenSearch use `search_after`; PIT is the default for snapshot
  consistency but degrades gracefully.** Both ES and OpenSearch expose
  `/<index>/_pit`. `list_documents` today skips PIT (sorts on `_doc`
  without a snapshot) and notes PIT as a "fallback if shard churn becomes a
  problem". For UBI full-traffic aggregation the scan can span many pages
  over a live, append-heavy `ubi_events` index, so a PIT snapshot is the
  correct default (avoids double-counting / skipping on concurrent writes).
  The sort key is `[timestamp asc, _shard_doc asc]` (the `_shard_doc`
  tiebreaker is PIT-only and guarantees a total order). If `_pit` is
  unavailable/denied, the adapter falls back to `search_after` over
  `[timestamp asc, _id asc]` without a PIT and logs a WARN. Solr uses
  `cursorMark=*` → `nextCursorMark` over a `sort` that includes the
  uniqueKey for total ordering (same shape as `SolrAdapter.list_documents`).
- **D-3 — Default cap raised, not removed.** Unbounded scans on a
  pathological index are a footgun. Keep `max_events`/`max_queries` as
  caller-supplied ceilings (the worker passes a high but finite default
  from `Settings`, e.g. `ubi_max_events_scan`), and the reader stops +
  logs when the ceiling is hit so the operator sees "scan truncated at N".
  This preserves the honest-sample property while lifting the 10k floor.

## Scope signals

- Backend: `SearchAdapter` Protocol (+ `scan_all` + Protocol shape tests in
  `test_protocol.py`) + `ElasticAdapter.scan_all` (ES + OpenSearch:
  `search_after`/PIT) + `SolrAdapter.scan_all` (`cursorMark`) +
  `UbiReader` (incremental aggregation across pages). ~200-300 LOC +
  adapter unit tests (ES, OpenSearch-branch, Solr) + reader unit tests.
- Frontend: none.
- Migration: none. (Alembic head unchanged.)

## Relationship to other work

- `feat_ubi_judgments` (shipped) owns `UbiReader`; this chore extends it.
- `infra_adapter_solr` (shipped) added the Solr branch + the
  `list_documents`/`next_cursor_token` cursor precedent this design reuses.
- `feat_index_document_browser` (shipped) introduced `list_documents` +
  `AdapterDocumentHit.sort` + `DocumentPage.next_cursor_token` — the exact
  cross-engine cursor abstraction `scan_all` mirrors.
