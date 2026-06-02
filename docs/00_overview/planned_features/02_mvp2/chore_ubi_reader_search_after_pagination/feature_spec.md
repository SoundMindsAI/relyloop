# Feature Specification — Exact full-traffic UBI aggregation via cursor pagination (`scan_all`)

**Date:** 2026-06-02
**Status:** Draft
**Owners:** RelyLoop maintainers (soundminds.ai)
**Related docs:**
- [`idea.md`](idea.md)
- [`implementation_plan.md`](implementation_plan.md)
- [`docs/01_architecture/adapters.md`](../../../../01_architecture/adapters.md) (SearchAdapter Protocol — Absolute Rule #4)
- [`docs/01_architecture/llm-orchestration.md`](../../../../01_architecture/llm-orchestration.md) (UBI → judgment generation context)
- [`docs/03_runbooks/judgment-generation-debugging.md`](../../../../03_runbooks/judgment-generation-debugging.md) (UBI window tuning)

---

## 1) Purpose

`UbiReader` derives CTR/dwell judgments from the `ubi_events` stream, but
each scan currently issues **one** `size`/`rows`-limited query clamped to
`ES_MAX_RESULT_WINDOW` (10000). On dense clusters that's a **sample** of
the first 10k matching events per (target, window), not the full traffic —
the corrected-CTR and dwell signals are biased toward whichever events the
engine returns first.

- **Problem:** `UbiReader._scan_ubi_events` (`backend/app/services/ubi_reader.py:450-523`) and `_scan_ubi_queries` (`:389-448`) each issue a single `search_batch` with `top_k = min(max_events, ES_MAX_RESULT_WINDOW)` = 10000 (`DEFAULT_MAX_EVENTS = ES_MAX_RESULT_WINDOW`, `:94-105`). A larger `size` makes ES/OpenSearch reject the query ("Result window is too large / all shards failed"), which the adapter swallows to `[]` and surfaces as a spurious `UBI_INSUFFICIENT_DATA` (the original rung-3 E2E failure mode). So the cap cannot simply be raised — exact aggregation requires real pagination.
- **Outcome:** A new engine-neutral `SearchAdapter.scan_all` cursor-scan lets `UbiReader` iterate the **entire** matching event/query stream for a window (subject to a caller ceiling), folding each page into the aggregation accumulators incrementally. ES + OpenSearch paginate via `search_after` (inside a Point-in-Time snapshot by default — snapshot-consistent under concurrent writes); Solr paginates via `cursorMark` (no PIT — snapshot-exact over a finalized window, best-effort under live writes; see D-2/A3). CTR/dwell ratings reflect full traffic, not a 10k sample.
- **Non-goal:** No change to `aggregate_features` math, no new judgment source, no UI, no migration, no change to `search_batch` / `list_documents` / the Optuna trial hot path, no new LLM call.

## 2) Current state audit

### Existing implementations

- **`UbiReader`** (`backend/app/services/ubi_reader.py`): `read_features` (`:239-354`) does probe → `_scan_ubi_queries` → `_scan_ubi_events` → `aggregate_features`. `read_user_query_map` (`:356-387`) re-scans `ubi_queries` for the worker's `query_id → user_query` join. Both private scanners issue exactly one `search_batch` call and clamp `top_k` to `ES_MAX_RESULT_WINDOW`.
  - `_scan_ubi_queries` (`:389-448`) builds an ES Query DSL `bool.filter` body (or, when `engine_type == "solr"`, a Solr request-param body via `_build_solr_ubi_body`, `:124-176`); requests `fl="query_id,user_query,application,timestamp"`; returns `_extract_query_hits` (`:526-563`).
  - `_scan_ubi_events` (`:450-523`) builds the analogous body filtered by window + `application` + `query_id IN <ids>`; returns raw `_source` dicts; `_extract_event` (`:566-640`) materializes `UbiEvent`s (nested + top-level field fallbacks).
  - Caps: `ES_MAX_RESULT_WINDOW = 10_000` (`:78-89`), `DEFAULT_MAX_QUERIES = 5000` (`:91-92`), `DEFAULT_MAX_EVENTS = ES_MAX_RESULT_WINDOW` (`:94-105`).
- **`SearchAdapter` Protocol** (`backend/app/adapters/protocol.py:171-304`): `engine_type: EngineType` (`EngineType = Literal["elasticsearch", "opensearch", "solr"]`, `:31`). Existing methods: `health_check`, `list_targets`, `get_schema`, `list_query_parsers`, `render`, `search_batch` (`:228-250`), `explain`, `get_document`, `list_documents` (`:281-304`).
- **Cursor precedent — `list_documents`** (the exact two-idiom abstraction this spec reuses):
  - Protocol return type `DocumentPage` (`:131-152`) carries `hits: list[AdapterDocumentHit]`, `total: int`, and an **additive** `next_cursor_token: str | None` (`:152`) — "when populated, the router prefers it over the trailing-hit `sort` for cursor encoding". `AdapterDocumentHit.sort: list[Any]` (`:128`) carries the engine-native per-hit sort value for ES `search_after` round-trips.
  - `ElasticAdapter.list_documents` (`backend/app/adapters/elastic.py:767-859`): `_search` + `match_all` + `sort: [{"_doc": "asc"}]` + `track_total_hits: true`; sets `search_after` from the prior page's trailing `sort`; **does not** open a PIT (notes PIT + `_shard_doc` as a fallback, `:789`). Returns each hit's `sort`.
  - `SolrAdapter.list_documents` (`backend/app/adapters/solr.py:1577-1690`): `cursorMark=*` first page → `nextCursorMark` continuation; terminal page detected when `nextCursorMark == request cursorMark` (sets `next_cursor_token=None`); secondary terminal guard on a short page (`< limit`). Sorts on the uniqueKey resolved via `_resolve_unique_key` (`:876`).
- **Protocol shape test** (`backend/tests/unit/adapters/test_protocol.py`): `_StubAdapter` enumerates every Protocol method (`:32-102`); `test_async_methods_are_coroutines` (`:116-134`) and the Solr branch (`:321-368`) iterate a hardcoded method-name list. **Both lists must gain `scan_all`.**
- **Adapter `_request` helpers:** `ElasticAdapter._request` (`elastic.py:129`) and `SolrAdapter._request` (`solr.py:367`) — single-retry + 401/403/5xx translation. Solr param values are validated by `_validate_solr_param_values` (`solr.py:173`); uniqueKey resolved + cached via `_resolve_unique_key` (`solr.py:876`).
- **Callers / ownership:** `UbiReader(adapter, ...)` is constructed in `backend/workers/judgments_ubi.py:375` (passing `settings.ubi_position_bias_prior`), `backend/app/services/agent_judgments_dispatch.py:501`, and `backend/app/services/ubi_readiness.py:182`. The adapter is **owned by the caller** (`aclose()` is the worker/dispatcher's responsibility via `acquire_adapter`); `scan_all` adds no lifecycle ownership to the reader.

### Navigation and link impact

N/A — no UI, no URLs, no routes.

| Source file | Current link target | New link target |
|---|---|---|
| N/A | N/A | N/A |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/unit/adapters/test_protocol.py` | `_StubAdapter` method set (`:32-102`) + two hardcoded method-name lists (`:124-134`, `:354-365`) | 1 stub + 2 lists | Add a `scan_all` method to `_StubAdapter` (async; returns one terminal page) and append `"scan_all"` to both async-coroutine method-name lists so the Protocol shape stays exhaustive. |
| `backend/tests/unit/services/test_ubi_reader.py` | Existing reader tests stub `adapter.search_batch` and assert a single-call scan | n existing | Update / add: the new paginated path calls `scan_all`, not `search_batch`. Tests must stub `scan_all` returning multiple pages and assert full aggregation across pages. Existing single-page expectations migrate to the multi-page contract. |
| `backend/tests/unit/services/test_ubi_reader_no_writes.py` | Mocks the httpx transport; asserts zero write-shaped requests | 1 | `scan_all` must remain read-only (`_search`/`_pit` open+close — `DELETE /_pit` is the only non-GET/POST and is part of the read contract; assert no `_bulk`/`_doc`/`_update`/index-`DELETE`). Confirm the no-writes invariant still holds with the new request shapes (PIT open is `POST /<index>/_pit`, PIT close is `DELETE /_pit` with a body — both read-side). |
| `backend/tests/unit/adapters/test_elastic_list_documents.py`, `test_solr_get_document_list_documents.py` | `MockTransport`-driven adapter tests | reference | Pattern source for the new `test_elastic_scan_all.py` + `test_solr_scan_all.py` (and an OpenSearch-branch case). No change to the existing files. |

### Existing behaviors affected by scope change

- **UBI event scan (`_scan_ubi_events`):** Current: one `search_batch`, ≤10k events. New: `scan_all` loop, full traffic up to a caller ceiling. Decision needed: no (D-1/D-2/D-3 locked in §19).
- **UBI query scan (`_scan_ubi_queries` / `read_user_query_map`):** Current: one `search_batch`, ≤5000 queries. New: `scan_all` loop. Same paginated path; the `read_user_query_map` re-scan reuses it. Decision needed: no.
- **`search_batch`:** unchanged. The Optuna trial hot path is untouched (D-1).

---

## 3) Scope

### In scope

- Add `SearchAdapter.scan_all(...)` to the Protocol (`backend/app/adapters/protocol.py`) + its page return type.
- Implement `scan_all` in `ElasticAdapter` (covers ES **and** OpenSearch — same class, `search_after` + PIT) and in `SolrAdapter` (`cursorMark`).
- Rewrite `UbiReader._scan_ubi_events` + `_scan_ubi_queries` to loop `scan_all` and aggregate incrementally; keep `read_features` / `read_user_query_map` signatures unchanged.
- Update `DEFAULT_MAX_EVENTS` / `DEFAULT_MAX_QUERIES` semantics (per-call clamp → total-scan ceiling, D-3) and add a `Settings`-backed default ceiling for the worker path.
- Tests: Protocol shape (`test_protocol.py`), adapter `scan_all` (ES, OpenSearch branch, Solr), reader multi-page aggregation, no-writes invariant.

### Out of scope

- `aggregate_features` math, position-bias correction, dwell logic (unchanged domain).
- `search_batch`, `list_documents`, `get_document`, the Optuna trial runner, the run_query endpoint.
- Any UI, any new endpoint, any new judgment source, any LLM call.
- Migration / schema change (Alembic head unchanged).
- Live Solr `UBIComponent` event capture (not shipped in stock Solr images — out of scope here; the demo synthesizes events, unchanged).

### API convention check

N/A — no HTTP API surface added or changed. The `scan_all` addition is an internal adapter-Protocol method, governed by [`docs/01_architecture/adapters.md`](../../../../01_architecture/adapters.md) (Absolute Rule #4), not by [`api-conventions.md`](../../../../01_architecture/api-conventions.md).

### Phase boundaries (if multi-phase)

Single-phase. No deferred phases, no `phase<N>_idea.md` tracking required.

## 4) Product principles and constraints

- **Adapter Protocol discipline (Absolute Rule #4).** All engine-specific **pagination mechanics** (`search_after`/PIT-open/PIT-close vs `cursorMark`, including the ES-vs-OpenSearch PIT endpoint difference) live ONLY in `backend/app/adapters/elastic.py` + `solr.py`. `UbiReader` consumes the unified `scan_all`/`close_scan` Protocol and never branches on `engine_type` for pagination mechanics. **Acknowledged exception (Review A4):** the reader retains its existing, pre-shipped `engine_type == "solr"` branch for **filter-body shape** only — the ES Query DSL `bool.filter` body vs the Solr request-param body (`_build_solr_ubi_body`) genuinely differ and the reader already owns this (it shipped with `feat_ubi_judgments`/`infra_adapter_solr`). This is a known, narrow deviation from the strict "engine code only in adapters" ideal, scoped to body construction, not pagination. Fully eliminating it (an adapter-side UBI query builder so the reader supplies engine-neutral criteria) is a larger refactor than this scaling chore and is recorded as a deferred option in §19 (D-4), not undertaken here.
- **Read-only contract preserved.** `scan_all` issues only read-side requests: **PIT-mode search `POST /_search`** (with a top-level `pit` object, no index in the URL — cycle-3 C3-2); **no-PIT fallback search `POST /<target>/_search`**; PIT open/close per engine — Elasticsearch `POST /<index>/_pit` + `DELETE /_pit`, **OpenSearch** `POST /<index>/_search/point_in_time` + `DELETE /_search/point_in_time` (D-5); Solr `GET /<collection>/select`. No `_bulk`/`_doc`/`_update`/`_create`/index-`DELETE`. The `test_ubi_reader_no_writes` invariant is extended to cover the new shapes, and its allowlist **MUST include both PIT endpoint families AND both search shapes** (`POST /_search` and `POST /<target>/_search`) (cycle-2 C2-2 / cycle-3 C3-2) so the OpenSearch close path is not misclassified as a destructive `DELETE` and the index-less PIT search is allowlisted.
- **Honor CLAUDE.md Absolute Rules.** No migration (#5 N/A). No secret added (#2 N/A — adapters reuse existing mounted credentials). No LLM call (#3/#8 N/A). No `/healthz` change (#6/#11 N/A). Conventional Commits + DCO sign-off (#7) apply. Engine code stays in adapters (#4 — central to this spec).
- **Honest-sample → honest-full.** The 10k clamp was a correct, honest sample for the demo + typical query sets. The ceiling (D-3) keeps a finite, operator-visible bound; the difference is the bound is now configurable and high, not a silent 10k floor.

### Anti-patterns

- **Do not** extend `search_batch` with pagination state (D-1). It is the multi-query `_msearch` hot path with a `query_id`-mapping contract tuned for the Optuna trial runner; overloading it couples two incompatible concerns.
- **Do not** branch on `engine_type` for pagination mechanics inside `UbiReader` — that's the adapter's job. The reader loops a generic cursor.
- **Do not** leak a PIT. Every ES/OpenSearch `scan_all` that opens a PIT MUST close it (`DELETE /_pit`) in a `finally`, even on mid-scan error. A leaked PIT pins shard resources.
- **Do not** raise the `size` per call above `ES_MAX_RESULT_WINDOW`. Pagination, not a bigger window, is the fix (raising `size` reproduces the original "all shards failed" bug).
- **Do not** remove the ceiling entirely (D-3). An unbounded scan on a pathological index is a footgun; keep a caller-supplied finite cap with a truncation log.
- **Do not** assume Solr has PIT. It does not; Solr uses `cursorMark`. Each adapter implements its own idiom behind the shared return shape.

## 5) Assumptions and dependencies

- **`feat_ubi_judgments` (shipped)** — owns `UbiReader`; this chore extends it. Status: implemented. Risk if missing: N/A (shipped).
- **`infra_adapter_solr` (shipped)** — `SolrAdapter` + the `list_documents`/`next_cursor_token` cursor precedent + `_resolve_unique_key`. Status: implemented. Risk if missing: the Solr `scan_all` branch would have no precedent to mirror.
- **`feat_index_document_browser` (shipped)** — `list_documents` + `AdapterDocumentHit.sort` + `DocumentPage.next_cursor_token`. Status: implemented. Why required: the cross-engine cursor abstraction `scan_all` mirrors.
- **ES/OpenSearch PIT API** — both support PIT but at **different endpoints** (D-5): Elasticsearch 8.11+/9.x uses `POST/DELETE /<index>/_pit`; OpenSearch 2.x/3.x uses `POST/DELETE /<index>/_search/point_in_time`. Status: external engine capability. Risk if unsupported: narrow fallback (D-7) — no-PIT `search_after` over a sortable tiebreaker (see D-8) + WARN.

## 6) Actors and roles

- Primary actor: system (the `generate_judgments_from_ubi` worker / dispatcher invoking `UbiReader.read_features`). No human actor.
- Role model: N/A — single-tenant install, no auth surface.
- Permission boundaries: the adapter uses the cluster's already-mounted credentials; no new permission surface.

### Authorization

N/A — single-tenant install, no auth surface. The adapter call inherits the cluster's existing auth headers.

### Audit events

N/A — pure read-path data aggregation. `scan_all` mutates no tenant-visible state (no DB write, no `audit_log` row). `audit_log` itself ships at MVP3 ([`data-model.md`](../../../../01_architecture/data-model.md)); even once it lands, a read-side scan emits nothing.

## 7) Functional requirements

### FR-1: `SearchAdapter.scan_all` + `close_scan` Protocol methods
- Requirement:
  - The Protocol **MUST** declare an async `scan_all(target, body, *, page_size, cursor=None, fl=None, request_id=None) -> ScanPage` (exact signature finalized in the plan; `body`/`fl` carry the engine-native filter the caller built, mirroring how `search_batch` accepts a `NativeQuery.body`).
  - The method **MUST** return a page object (`ScanPage`) carrying `hits: list[ScoredHit]` and an opaque `cursor: <token> | None` where `None` signals the terminal page. The caller passes the returned `cursor` back to fetch the next page.
  - The Protocol **MUST** also declare an async `close_scan(cursor, *, request_id=None) -> None` that releases any engine-side resource held by a **non-terminal** cursor (ES/OpenSearch: `DELETE` the open PIT; Solr: no-op — `cursorMark` holds no server resource). `close_scan` **MUST** be safe to call with a `None` cursor (no-op) and idempotent (closing an already-closed/terminal cursor is a no-op, never an error). This is the contract that lets a caller exit early (ceiling reached, exception) without leaking a PIT (Review A1/B2).
  - Both methods **MUST** be async (HTTP I/O). The Protocol shape test (`test_protocol.py`) **MUST** include `scan_all` **and** `close_scan` in both coroutine method-name lists and in `_StubAdapter`.
- Notes: Single-target, cursor-based — deliberately separate from the multi-query `search_batch` (D-1) and parallel to `list_documents` (D-2). `ScanPage` reuses `ScoredHit` (the reader only needs `source`); no new per-hit model unless the plan finds a need. The terminal page closes its own PIT automatically (FR-2); `close_scan` exists for the early-exit / error paths where the loop stops before `cursor is None`.

### FR-2: `ElasticAdapter.scan_all` — ES + OpenSearch via `search_after` (+ PIT)
- Requirement:
  - The adapter **MUST** paginate `ubi_events`/`ubi_queries` with `search_after` over a stable total-order sort key, defaulting to a Point-in-Time snapshot for consistency across pages on a live append-heavy index.
  - On the **first** page it **MUST** open a PIT, then `POST /_search` with `{pit:{id,keep_alive}, sort:[{timestamp:asc},{_shard_doc:asc}], size:page_size, ...body}`. Continuation pages set `search_after` to the prior page's trailing hit `sort`.
  - **The PIT id can change between searches (cycle-5 C5-1).** Every PIT search **response** may return an updated `pit_id`; the adapter **MUST** use the **most-recently-returned** id (not just the open-PIT id) in the next continuation request's `pit.id` and in the eventual `close_scan`/terminal `DELETE`. The cursor token the adapter returns **MUST** therefore carry the latest id, not the original. Closing a stale id would leak the live PIT.
  - **Every PIT search request — including continuations — MUST re-send `pit.keep_alive` (cycle-5 C5-2).** Omitting it on continuation pages lets the PIT expire mid-scan on a long full-traffic scan even while pages progress. Each `POST /_search` body carries `pit: {id: <latest_pit_id>, keep_alive: <ttl>}`.
  - **PIT endpoint differs by engine (Review A2):** Elasticsearch opens with `POST /<target>/_pit?keep_alive=<ttl>` and closes with `DELETE /_pit` (body `{"id": <pit_id>}`). OpenSearch opens with `POST /<target>/_search/point_in_time?keep_alive=<ttl>` and closes with `DELETE /_search/point_in_time` (body `{"pit_id": [<pit_id>]}`). The adapter **MUST** select the correct path/body internally by `self.engine_type` — this is an **adapter-internal** branch (Rule #4 keeps it inside `ElasticAdapter`); the public `scan_all`/`close_scan` Protocol stays engine-neutral. (D-5 amended accordingly.)
  - On the **terminal** page (fewer than `page_size` hits) it **MUST** close the PIT and return `cursor=None`. It **MUST** also close the PIT in a `finally` on any mid-scan error, and `close_scan(cursor)` (FR-1) **MUST** close the PIT encoded in a non-terminal cursor handed to it by an early-exiting caller.
  - **PIT-unsupported fallback is narrow (Review A4-related):** the adapter **MUST** fall back (logging a WARN with no secret) ONLY for responses that signal PIT-unsupported — specifically `405 Method Not Allowed`, `501 Not Implemented`, or `400` whose error body indicates an unknown/unsupported PIT action. It **MUST NOT** swallow `401`/`403` (→ `TargetsForbiddenError`/auth) or `404 index_not_found` (→ `TargetNotFoundError`) as a fallback — those propagate via the normal error envelope.
  - **The fallback sort key MUST NOT assume `_id` is sortable (cycle-2 C2-3 / D-8).** Modern Elasticsearch (9.x) disables `_id` fielddata by default (`indices.id_field_data.enabled` off) — a `sort: [{_id: asc}]` returns HTTP 400, the exact reason `ElasticAdapter.list_documents` already sorts on `_doc` (`elastic.py:783-789`). Without a PIT there is **no shard-stable total order** available cheaply (`_doc` is not stable across pages without a PIT). Therefore the no-PIT fallback **MUST** paginate `search_after` over `[{timestamp:asc}, {<tiebreaker>:asc}]` where `<tiebreaker>` is a doc_values-enabled unique field IF one is configured (per a `Settings.ubi_no_pit_tiebreaker_field`, default unset); when no such field is configured, the adapter **MUST NOT** attempt an unsafe `_id` sort — it falls back to the **single 10k-capped `search_batch` query** (the original honest-sample behavior) and logs a WARN stating the scan was sampled, not full. This preserves correctness over completeness when neither PIT nor a sortable tiebreaker is available.
  - **The no-PIT paginated fallback is best-effort under live writes (cycle-4 C4-1).** A configured doc_values tiebreaker gives a deterministic `search_after` order, but **without a PIT the scan is not snapshot-consistent** — exactly like Solr's `cursorMark` (A3). It is exact only over a finalized/static window; under concurrent writes to `[since, until)`, docs indexed mid-scan with a sort key before the current cursor can be missed. The PIT-unavailable WARN **MUST** state that snapshot consistency is lost and the scan is best-effort unless the window is finalized. (PIT-mode ES/OpenSearch remains fully snapshot-consistent.)
  - The same class serves `engine_type` `elasticsearch` **and** `opensearch` (one `scan_all`/`close_scan` implementation; the only engine branch is the PIT path/body above — both engines support PIT, just at different endpoints). Same error-translation envelope as `search_batch`/`list_documents` (401/403 → auth, 404 index_not_found → `TargetNotFoundError`, 5xx/connection → `ClusterUnreachableError`).
- Notes: `_shard_doc` is a PIT-only tiebreaker guaranteeing total order (per the `list_documents` D-26 note); both ES and OpenSearch support it under a PIT. Without PIT, the tiebreaker is a configured doc_values unique field (`Settings.ubi_no_pit_tiebreaker_field`), NOT `_id` (D-8) — and if none is configured the adapter returns a single sampled page instead of paginating (so there is no cross-page total-order requirement in that branch). The cursor token the adapter returns encodes the `pit_id` + trailing `sort` + a `no_pit` flag so `UbiReader` stays cursor-agnostic and `close_scan` knows whether/what to release. **PIT search request shape (cycle-3 C3-2):** under a PIT the search is `POST /_search` with a top-level `pit` object and **no index in the URL** (the PIT binds the target); the index appears in the URL only in the no-PIT fallback (`POST /<target>/_search`) and in PIT open (`POST /<target>/_pit` ES / `POST /<target>/_search/point_in_time` OpenSearch).

### FR-3: `SolrAdapter.scan_all` — `cursorMark`
- Requirement:
  - The adapter **MUST** paginate via Solr `cursorMark`: first page `cursorMark=*`; continuation pages `cursorMark=<prior nextCursorMark>`; `sort` **MUST** include the uniqueKey (resolved via `_resolve_unique_key`) for total ordering (Solr requires the sort to be deterministic for cursor paging).
  - The terminal page is detected exactly as `list_documents` does: `nextCursorMark == request cursorMark` (sets `cursor=None`), with the short-page secondary guard (`len(hits) < page_size`).
  - The request body **MUST** pass through `_validate_solr_param_values` (Solr request-param scalars/lists only — the caller supplies a Solr-shaped filter body, NOT an ES Query DSL body; D-4).
  - `close_scan(cursor)` for Solr **MUST** be a no-op — `cursorMark` holds no server-side resource (FR-1).
  - Same error envelope as `SolrAdapter.list_documents` (404 → `TargetNotFoundError`, 401/403/5xx/connection → `ClusterUnreachableError`).
- Notes: **Solr has no PIT (Review A3).** `cursorMark` deep-paging guarantees no-skip / no-duplicate **only** for documents that existed and whose sort-key value was stable for the duration of the scan. Under concurrent commits to `ubi_events` during a multi-page scan, newly-indexed docs may or may not appear depending on their uniqueKey ordering relative to the current `cursorMark` — so the Solr scan is **best-effort full-traffic, not a snapshot**, and is **exact only when the scanned window is finalized** (i.e. `until` is in the past and no further events land in `[since, until)`). UBI windows for judgment generation are normally historical/closed, so this holds in practice. The runbook (§15) and §11 document this; §9 scopes the "no skip / no double-count" invariant to ES/OpenSearch-PIT + Solr-over-a-finalized-window.

### FR-4: `UbiReader` paginates + aggregates incrementally
- Requirement:
  - `_scan_ubi_events` and `_scan_ubi_queries` **MUST** loop `scan_all` (passing the existing per-engine filter body they already build) until `cursor is None`, folding each page into the accumulators — events bucketed by `(query_id, doc_id)`; queries into the `_extract_query_hits` list — rather than collecting all rows then aggregating.
  - The reader **MUST** enforce the ceiling **exactly** (cycle-4 C4-2): the running count **MUST NOT** overshoot `max_events`/`max_queries` by up to a page when the ceiling is not a multiple of `page_size`. The reader achieves this by requesting `page_size = min(configured_page_size, remaining_budget)` on each `scan_all` call and/or slicing the final processed page to `remaining_budget` hits before folding. The `ubi_reader_scan_truncated` WARN reports the **exact** scanned count (== ceiling), not a page-rounded count.
  - The reader **MUST** stop and log a structured `ubi_reader_scan_truncated` WARN when the running count reaches the caller ceiling (`max_events`/`max_queries`, D-3), so an operator sees a truncated full scan vs a silent 10k cap.
  - **The reader MUST call `adapter.close_scan(cursor)` in a `finally` whenever its `scan_all` loop exits while holding a non-terminal cursor** — i.e. on ceiling truncation OR on a mid-scan exception (Review A1/B2). Exiting via the terminal page (`cursor is None`) needs no explicit close (the adapter already closed the PIT, FR-2). This guarantees no PIT leak on early exit.
  - `read_features` and `read_user_query_map` public signatures **MUST** be unchanged for callers (the `max_events`/`max_queries` kwargs keep their names; their default semantics shift to ceilings per FR-5). Callers in the worker/dispatcher/readiness service are unaffected.
  - The reader **MUST NOT** branch on `engine_type` for pagination mechanics; only the existing filter-body-shape branch (ES DSL vs Solr params, D-4) is retained.
- Notes: The `_probe_enabled` 404 → `UbiNotEnabledError` flow and the empty-window `{}` fallbacks are unchanged.

### FR-5: Default scan ceiling sourced from `Settings`, applied at every caller path
- Requirement:
  - `DEFAULT_MAX_EVENTS` / `DEFAULT_MAX_QUERIES` **MUST** become total-scan ceilings (not per-call `size` clamps).
  - The default ceiling **MUST** be operator-configurable via `Settings` (e.g. `ubi_max_events_scan` / `ubi_max_queries_scan`, defaulting to a high finite value) and **MUST** apply uniformly across **all three** `UbiReader` construction sites — `judgments_ubi.py:375`, `agent_judgments_dispatch.py:501`, and `ubi_readiness.py:182` — not just the worker (Review B1). To prevent divergence, the ceiling default **MUST** be resolved inside `UbiReader` (constructor reads `get_settings()`-derived ceilings, or accepts them as constructor args with the `read_features`/`read_user_query_map` `max_events`/`max_queries` kwargs overriding per-call) rather than each caller passing its own — a caller that forgets the kwarg inherits the shared `Settings` ceiling, never an accidental 10k.
  - The per-page `page_size` passed to `scan_all` **MUST** stay `<= ES_MAX_RESULT_WINDOW` (10000) so each individual page is a valid window-sized request on every engine.
- Notes: This is the "raise the ceiling, keep a bound" decision (D-3). Page size and total ceiling are distinct knobs. Centralizing the default in `UbiReader` (D-6) is the mechanism that keeps worker/dispatcher/readiness consistent.

### FR-6: Read-only invariant preserved
- Requirement:
  - `scan_all` (all engines) **MUST** issue only read-side requests. The `test_ubi_reader_no_writes` invariant **MUST** be extended to cover the new request shapes and assert no `_bulk`/`_doc`/`_update`/`_create`/index-`DELETE` request escapes. PIT open (`POST /_pit`) and PIT close (`DELETE /_pit`) are part of the read contract and **MUST** be explicitly allowlisted in the assertion.
- Notes: `DELETE /_pit` is the one non-GET/non-`_search`/non-`select` request; the test must distinguish it from a destructive index `DELETE`.

### FR-7: Large `query_id` sets MUST NOT produce an oversized event-scan filter
- Requirement:
  - Raising `max_queries` to the new high ceiling (FR-5) means `_scan_ubi_events` can be handed thousands-to-tens-of-thousands of `query_id`s for its `query_id IN <ids>` filter. The reader **MUST NOT** emit a single filter that exceeds engine limits (cycle-4 C4-3): Solr `/select` is a `GET` whose URL length is bounded (the `{!terms f=query_id}<id>,<id>,...` `fq` lives in the URL/query-string — a multi-thousand-id list overflows typical 8–32 KB header limits); Elasticsearch `terms` queries are bounded by `index.max_terms_count` (default 65536) and a very large `terms` list also bloats the request body.
  - The reader **MUST** chunk the event scan by `query_id` batches sized within a safe per-engine bound (e.g. `Settings.ubi_query_id_batch_size`, default conservative such that the Solr GET URL stays under the limit), running one `scan_all` loop per batch and **merging** the per-batch accumulators into the single `(query_id, doc_id)` event map. (Solr `POST /select` with body params is an acceptable alternative to GET-URL chunking IF the existing `SolrAdapter` request path supports it; otherwise chunking is the mechanism.)
  - The chunking **MUST** respect the overall `max_events` ceiling (FR-4) across batches — the ceiling is global, not per-batch.
- Notes: This protects the promised full-traffic path on **dense** windows (the whole point of the feature) from breaking on the *query* dimension once the *event* dimension is unbounded. The plan finalizes the batch-size default + whether Solr switches to `POST /select`.

## 8) API and data contract baseline

### 7.1 Endpoint surface

N/A — no HTTP endpoints added or changed. `scan_all` is an internal adapter-Protocol method.

### 7.2 Contract rules

N/A — no API contract. The internal Protocol contract is governed by `adapters.md` (Absolute Rule #4): engine-specific code stays in the adapter modules; the `scan_all` return shape (`ScanPage`) is engine-neutral.

### 7.3 Response examples

N/A — no API response. (The internal `ScanPage` shape is specified in FR-1 and finalized in the plan.)

### 7.4 Enumerated value contracts

N/A — no filters, status badges, sort keys, or dropdowns sent over the wire. The `EngineType` Literal (`protocol.py:31`) is unchanged.

### 7.5 Error code catalog

No **new** error codes. `scan_all` reuses the adapter error classes (`TargetNotFoundError`, `TargetsForbiddenError`, `ClusterUnreachableError`) already translated by callers; `UbiReader` continues to map probe 404 → `UbiNotEnabledError` and reachability failures → `CLUSTER_UNREACHABLE` upstream.

## 9) Data model and state transitions

### New/changed entities

N/A — no schema change, no migration. Alembic head unchanged. The only new "type" is the internal `ScanPage` Pydantic/dataclass return shape (adapter layer, not a DB entity).

### Required invariants

- **Read-only:** no write-shaped request escapes `scan_all` (FR-6).
- **No PIT leak:** every opened PIT is closed (`finally`), even on error (FR-2).
- **Total order:** when paginating, the sort key is a strict total order on every engine — `[timestamp,_shard_doc]` (ES/OpenSearch under PIT) / `[timestamp, <configured doc_values tiebreaker>]` (ES/OpenSearch no-PIT, only when a tiebreaker is configured) / uniqueKey-terminated Solr — so no event is skipped or double-counted across pages. In the ES/OpenSearch no-PIT **no-tiebreaker-configured** branch the adapter does NOT paginate (it returns a single sampled 10k page, D-8), so the cross-page total-order invariant does not apply there. The adapter never sorts on `_id` (D-8 — ES 9 rejects it). **Snapshot-consistency scope (Review A3 / cycle-4 C4-1):** no-skip / no-double-count is guaranteed under concurrent writes **only for ES/OpenSearch under a PIT**. The Solr `cursorMark` path AND the ES/OpenSearch no-PIT fallback path are guaranteed exact only when the scanned window `[since, until)` is finalized (historical, no further writes) — the normal UBI judgment-generation case; under live writes both no-PIT paths are best-effort.
- **Bounded:** every scan terminates at `cursor is None` or at the caller ceiling, whichever comes first (FR-4/FR-5).
- **Protocol exhaustiveness:** `test_protocol.py` lists `scan_all` in both coroutine method-name lists + `_StubAdapter` (FR-1).

### State transitions

N/A — no entity state machine. The cursor lifecycle (open → continue* → terminal/close) is request-scoped and not persisted.

### Idempotency/replay behavior

A repeated `read_features` for the same window re-scans and re-aggregates deterministically (same window + same index state → same result). PIT snapshots make a single multi-page scan internally consistent even under concurrent writes; two separate scans over a changing index may legitimately differ (different traffic).

## 10) Security, privacy, and compliance

- Threats: none introduced. `scan_all` reads the same `ubi_events`/`ubi_queries` data the reader already reads, over the same authenticated adapter client. No new external surface, no new secret.
- Controls: read-only invariant (FR-6); PIT close in `finally` (no resource leak); WARN logs never include credentials (Absolute Rule #10) — a PIT-fallback WARN logs the endpoint/engine, not the key.
- Secrets/key handling: unchanged — adapters reuse mounted credentials via `resolve_credentials`.
- Auditability: N/A (read path; no state mutation).
- Data retention/deletion/export impact: none — reads do not retain or export beyond the in-memory aggregation already performed.

## 11) UX flows and edge cases

### Information architecture

N/A — no UI.

### Tooltips and contextual help

N/A — no UI element.

| Element | Tooltip / help text | Trigger | Placement |
|---------|-------------------|---------|-----------|
| N/A | N/A | N/A | N/A |

### Primary flows

1. **Full-traffic event aggregation (ES/OpenSearch):** worker → `read_features` → `_scan_ubi_events` → `scan_all` opens PIT → loops `search_after` pages, folding each into `events_by_pair` → terminal page closes PIT → `aggregate_features` over the full set.
2. **Full-traffic event aggregation (Solr):** same, but `scan_all` loops `cursorMark` (no PIT) → terminal when `nextCursorMark` stabilizes.
3. **Query scan / `read_user_query_map`:** `_scan_ubi_queries` loops `scan_all` over `ubi_queries` identically; the user-query map is built from the full query set.

### Edge/error flows

- **Empty window:** first `scan_all` page returns zero hits, `cursor=None`; reader returns `{}` exactly as today (existing `ubi_reader_empty_features` log).
- **Ceiling hit:** running count reaches `max_events`/`max_queries` → reader stops, logs `ubi_reader_scan_truncated` (count + ceiling), aggregates what it has.
- **PIT unsupported (ES/OpenSearch):** PIT open returns `405`/`501`/`400-unsupported-pit` only → adapter falls back per FR-2 (see D-7) + WARN; scan completes. `401`/`403` → `TargetsForbiddenError`/auth and `404 index_not_found` → `TargetNotFoundError` do **NOT** trigger fallback — they propagate via the normal error envelope (Review A4 / cycle-2 C2-1).
- **Mid-scan engine error:** `scan_all` raises `ClusterUnreachableError`; adapter closes any open PIT in `finally`; the error propagates so the worker records a failed generation (unchanged upstream handling).
- **Solr terminal-page string normalization:** the `nextCursorMark == cursorMark` check plus the short-page secondary guard prevent an extra empty loop (mirrors `list_documents`).
- **Concurrent writes during scan:** PIT snapshot (ES/OpenSearch) prevents skip/double-count within a scan. Solr (no PIT) is exact only over a finalized window; under live writes to `[since, until)` the Solr `cursorMark` scan is best-effort (newly-indexed docs may be included or excluded depending on uniqueKey ordering relative to the current mark). UBI windows are normally historical, so this is acceptable; the runbook calls it out (Review A3).

## 12) Given/When/Then acceptance criteria

### AC-1: `scan_all` is in the Protocol and the shape test
- Given the `SearchAdapter` Protocol and `test_protocol.py`
- When the suite runs
- Then `scan_all` is an async coroutine on `_StubAdapter`, the ES stub, and the SolrAdapter branch, and appears in both `iscoroutinefunction` method-name lists
- Example values: `assert inspect.iscoroutinefunction(stub.scan_all)`; `"scan_all"` present in both lists.

### AC-2: ES/OpenSearch `scan_all` paginates the full stream via PIT + `search_after`
- Given a `MockTransport` ES adapter returning 3 pages of `page_size` hits then a short terminal page
- When `scan_all` is looped from `cursor=None` until it returns `cursor=None`
- Then a PIT is opened on page 1 (`POST /<target>/_pit`), each continuation page sends `search_after` = prior trailing `sort` AND `pit: {id: <latest>, keep_alive: <ttl>}`, the PIT is closed (`DELETE /_pit`) on the terminal page using the latest id, and all hits across pages are returned with none dropped or duplicated
- Example values: 3×10 + 1×4 hits → 34 unique hits; exactly one `_pit` open + one `_pit` close.

### AC-2b: PIT id rotation is propagated (cycle-5 C5-1/C5-2)
- Given a `MockTransport` ES adapter whose page-1 search response returns `pit_id=A2`, page-2 returns `pit_id=A3` (id rotates each search)
- When `scan_all` is looped
- Then the page-2 request body's `pit.id == A2`, the page-3 request body's `pit.id == A3`, every continuation `POST /_search` body includes `pit.keep_alive`, and the terminal/`close_scan` `DELETE /_pit` closes `A3` (the latest), not the original open id

### AC-3: ES PIT-unavailable fallback
- Given a `MockTransport` where the PIT-open endpoint returns 405/501/400-unsupported AND a `Settings.ubi_no_pit_tiebreaker_field` is configured (doc_values unique field)
- When `scan_all` runs
- Then the adapter falls back to no-PIT `search_after` over `[timestamp, <tiebreaker>]`, logs a WARN (no credential), and still returns all hits across pages

### AC-3b: ES PIT-unavailable AND no tiebreaker → sampled fallback (no unsafe `_id` sort)
- Given the PIT-open endpoint returns 405/501/400-unsupported AND no `ubi_no_pit_tiebreaker_field` is configured
- When `scan_all` runs
- Then the adapter does NOT issue a `sort: [{_id: asc}]` query (which ES 9 rejects); it falls back to a single 10k-capped `search_batch` query and logs a WARN that the scan was sampled, not full (cycle-2 C2-3 / D-8)

### AC-4: Solr `scan_all` paginates via `cursorMark`
- Given a `MockTransport` Solr adapter returning pages until `nextCursorMark` stabilizes
- When `scan_all` is looped
- Then page 1 sends `cursorMark=*`, continuations send the prior `nextCursorMark`, `sort` includes the uniqueKey, and the loop terminates with `cursor=None` on the stable page — all hits returned, none dropped
- Example values: uniqueKey `id`; terminal when echoed `nextCursorMark` equals the request `cursorMark`.

### AC-5: `UbiReader` aggregates across pages, full traffic
- Given a stubbed adapter whose `scan_all` returns 25,000 events across pages (above the old 10k clamp)
- When `read_features` runs
- Then `aggregate_features` sees events from **all** pages (not just the first 10k), and the result reflects the full set
- Example values: 25,000 events over `(q1,d1)`,`(q1,d2)` → counts equal the full per-pair totals, not capped.

### AC-6: Ceiling truncation is logged, not silent
- Given `max_events=10_000` and a stream of 50,000 events
- When `read_features` runs
- Then the reader stops at 10,000 scanned, logs `ubi_reader_scan_truncated` (scanned=10000, ceiling=10000), and aggregates the 10k it has
- Example values: structured log `event_type="ubi_reader_scan_truncated"` present; no exception.

### AC-7: Read-only invariant holds for `scan_all`
- Given the `test_ubi_reader_no_writes` httpx-transport mock extended to the paginated path
- When `read_features` runs against ES (with PIT) and Solr
- Then only read-side requests are observed — PIT-mode `POST /_search` (no index in URL), no-PIT fallback `POST /<target>/_search`, ES `POST /<target>/_pit` + `DELETE /_pit`, OpenSearch `POST /<target>/_search/point_in_time` + `DELETE /_search/point_in_time`, Solr `GET .../select` — and zero `_bulk`/`_doc`/`_update`/`_create`/index-`DELETE` requests escape

### AC-8: PIT is never leaked on mid-scan error
- Given a `MockTransport` ES adapter that 503s on page 2
- When `scan_all` raises `ClusterUnreachableError`
- Then a `DELETE /_pit` for the opened PIT was still issued (closed in `finally`) before the error propagated

### AC-9: PIT is closed when `UbiReader` stops at the ceiling (early exit)
- Given a stubbed/`MockTransport` ES adapter returning non-terminal pages and `max_events` reached before `cursor is None`
- When `read_features` stops at the ceiling
- Then the reader called `adapter.close_scan(cursor)` (→ `DELETE /_pit`) in its `finally` before returning, and `ubi_reader_scan_truncated` was logged (no PIT leak on truncation — Review A1/B2)

### AC-10: OpenSearch PIT uses the OpenSearch endpoint
- Given an `ElasticAdapter` with `engine_type == "opensearch"` and a `MockTransport`
- When `scan_all` opens/closes a PIT
- Then it issues `POST /<target>/_search/point_in_time` (open) and `DELETE /_search/point_in_time` (close) — NOT the Elasticsearch `_pit` paths (Review A2)

### AC-11: PIT fallback is narrow (no auth/404 swallow)
- Given a `MockTransport` where `POST` to the PIT endpoint returns `401`/`403` (or `404 index_not_found`)
- When `scan_all` runs
- Then the adapter does NOT fall back to no-PIT; it raises `TargetsForbiddenError`/auth (or `TargetNotFoundError`) via the normal envelope. Fallback fires only for `405`/`501`/`400-unsupported-pit` (AC-3).

### AC-12: Settings ceiling applies to every caller path
- Given `Settings.ubi_max_events_scan` configured and a `UbiReader` constructed without an explicit `max_events` kwarg (as the dispatcher/readiness paths do)
- When `read_features` runs against a stream above the ceiling
- Then the scan truncates at the `Settings` ceiling (not a hardcoded 10k), proving the centralized default reaches all construction sites (Review B1)

### AC-13: Ceiling is enforced exactly, even when not page-aligned
- Given `max_events = 15_001`, `page_size = 10_000`, and a stream of ≥ 20,000 events
- When `read_features` runs
- Then exactly 15,001 events are aggregated (not 20,000 from rounding up to the 2nd full page), `ubi_reader_scan_truncated` logs `scanned=15001`, and the second `scan_all` call requested `page_size = min(10000, 5001) = 5001` (cycle-4 C4-2)

### AC-14: Large `query_id` set is chunked, no oversized filter
- Given `ubi_queries` returns 30,000 query_ids and `ubi_query_id_batch_size` configured (e.g. 1024)
- When `_scan_ubi_events` runs against Solr and ES
- Then the event scan is issued in `ceil(30000/batch)` chunks, no single Solr `/select` URL exceeds the URL-length bound and no single ES `terms` list exceeds `index.max_terms_count`, and the per-batch accumulators merge into one `(query_id, doc_id)` map (cycle-4 C4-3)

## 13) Non-functional requirements

- Performance: more requests per scan on dense clusters (N pages instead of 1), but each page is a bounded `page_size` request; total work is proportional to actual traffic in the window. The Optuna hot path (`search_batch`) is untouched, so trial latency is unaffected. UBI judgment generation is an async worker job, not a request-time path — added latency is acceptable.
- Reliability: PIT snapshot improves correctness under concurrent writes; PIT-close-in-`finally` prevents resource leaks; the ceiling prevents runaway scans.
- Operability: `ubi_reader_scan_truncated` + the PIT-fallback WARN give operators visibility into truncation and PIT availability. Page count is implicit in request logs.
- Accessibility/usability: N/A (no UI).

## 14) Test strategy requirements (spec-level)

- Unit tests (`backend/tests/unit/`):
  - `adapters/test_protocol.py` — add `scan_all` **and** `close_scan` to `_StubAdapter` + both method-name lists (AC-1).
  - `adapters/test_elastic_scan_all.py` (new) — ES PIT open/continue/close happy path (AC-2), **PIT id rotation + keep_alive on every continuation** (AC-2b), PIT-unavailable fallback for 405/501/400-unsupported (AC-3), no-tiebreaker sampled fallback (AC-3b), **narrow-fallback negative cases** 401/403/404 do NOT fall back (AC-11), an OpenSearch-`engine_type` case asserting the `_search/point_in_time` endpoints (AC-10), mid-scan error closes PIT (AC-8), `close_scan` closes a non-terminal PIT using the latest id (AC-9 adapter half). `MockTransport`-driven (pattern: `test_elastic_list_documents.py`).
  - `adapters/test_solr_scan_all.py` (new) — `cursorMark` open/continue/terminal (AC-4), uniqueKey in sort, `_validate_solr_param_values` pass, `close_scan` is a no-op. (pattern: `test_solr_get_document_list_documents.py`).
  - `services/test_ubi_reader.py` — multi-page aggregation (AC-5), ceiling truncation log + `close_scan` called on early exit (AC-6, AC-9 reader half), `Settings`-ceiling reaches a no-explicit-kwarg construction (AC-12), **exact (non-page-aligned) ceiling enforcement** (AC-13), **large `query_id`-set chunking** with a merged accumulator + no-oversized-filter assertion (AC-14); migrate existing single-call expectations to the `scan_all` loop.
  - `services/test_ubi_reader_no_writes.py` — extend the invariant to the paginated path incl. PIT open/close allowlist (AC-7).
- Integration tests (`backend/tests/integration/`): the existing UBI integration test (`test_generate_judgments_from_ubi.py`) must still pass with the paginated reader (DB-backed, adapter stubbed/mocked at the HTTP boundary). No new hermetic integration test required.
  - **Real-engine cross-engine correctness (Review B3):** `MockTransport` unit tests verify request *construction* but not real ES/OpenSearch PIT or Solr `cursorMark` semantics. Per CLAUDE.md "Common Pitfalls" (CI must be hermetic; no managed-cloud lane), real-engine paginated scans are covered in the **rung-3 E2E lane** (real ES + Solr), not the hermetic `pr.yml` job — the same lane that originally surfaced the 10k-cap bug. The plan must add (or extend) a rung-3 scenario exercising a >10k-event paginated scan on at least ES and Solr; this is the load-bearing real-behavior check the mocks cannot provide. (OpenSearch PIT real-engine coverage is desirable but gated on an OpenSearch rung-3 fixture; tracked, not blocking.)
- Contract tests (`backend/tests/contract/`): N/A — no API contract.
- E2E tests (`ui/tests/e2e/`): N/A — no UI.

## 15) Documentation update requirements

- `docs/01_architecture/adapters.md`: add `scan_all` to the SearchAdapter method table + a short note on the two-idiom pagination (ES/OpenSearch `search_after`+PIT vs Solr `cursorMark`), mirroring the existing `list_documents` entry.
- `docs/03_runbooks/judgment-generation-debugging.md`: note that UBI scans are now full-traffic (paginated) with an operator ceiling (`ubi_max_events_scan`/`ubi_max_queries_scan`); how to read `ubi_reader_scan_truncated`; the PIT-fallback WARN meaning; and the **Solr-best-effort-under-live-writes** caveat (run UBI generation over a finalized/historical window for exactness — A3).
- `docs/02_product`: none.
- `docs/04_security/llm-data-flow.md`: confirm unchanged (same data read; just more pages) — a one-line note that pagination does not change what leaves the cluster.
- `docs/05_quality`: none.
- `state.md`: add the merge one-liner to "Last 5 merges" + full entry to `state_history.md` at finalization (per CLAUDE.md). No Alembic-head change.

## 16) Rollout and migration readiness

- Feature flags / staged rollout: none — ships in one PR. The ceiling default (`Settings`) lets operators tune scan volume without code change.
- Migration/backfill expectations: none — no schema change.
- Operational readiness gates: `pr.yml` CI green (lint, mypy, unit/integration/contract, 80% coverage). The hermetic CI **merge gate** verifies request *construction* via `MockTransport` adapter unit tests + the reader multi-page tests (no managed-cloud lane per CLAUDE.md "Common Pitfalls").
- **Real-engine validation (non-blocking, post-merge — cycle-2 C2-4):** the rung-3 ES + Solr >10k paginated scenario (§14/§18) runs in the rung-3 E2E lane, **not** the `pr.yml` merge gate. It is a required deliverable of this feature (added/extended in the plan) but executed as post-merge real-engine validation, consistent with hermetic CI. §14 and §18 are the source of truth for the scenario; §16 classifies it as non-blocking-for-merge / required-as-validation.
- Release gate (merge): `make test-unit` + `make lint` + `make typecheck` + `make test-contract` green; coverage ≥ 80%. Real-engine rung-3 scenario green before the feature is considered fully validated.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1 | Story 1.1 | `adapters/test_protocol.py` | `adapters.md` |
| FR-2 | AC-2, AC-2b, AC-3, AC-3b, AC-8, AC-10, AC-11 | Story 2.1 | `adapters/test_elastic_scan_all.py` | `adapters.md` |
| FR-3 | AC-4 | Story 2.2 | `adapters/test_solr_scan_all.py` | `adapters.md` |
| FR-4 | AC-5, AC-6, AC-9, AC-13 | Story 3.1 | `services/test_ubi_reader.py` | `judgment-generation-debugging.md` |
| FR-5 | AC-6, AC-12 | Story 3.1, 3.2 | `services/test_ubi_reader.py` | `judgment-generation-debugging.md` |
| FR-6 | AC-7 | Story 2.1, 2.2, 3.1 | `services/test_ubi_reader_no_writes.py` | `llm-data-flow.md` (confirm) |
| FR-7 | AC-14 | Story 3.1 | `services/test_ubi_reader.py` | `judgment-generation-debugging.md` |

## 18) Definition of feature done

This feature is complete when:

- [ ] `SearchAdapter.scan_all` **and `close_scan`** are declared in `protocol.py` + the `ScanPage` return shape; `test_protocol.py` lists both exhaustively.
- [ ] `ElasticAdapter.scan_all`/`close_scan` (ES + OpenSearch) implement PIT + `search_after` with `finally`-close, the ES-vs-OpenSearch PIT endpoint branch, latest-PIT-id propagation + `keep_alive` on every continuation (AC-2b), and the narrow PIT-unsupported fallback (405/501/400-unsupported only).
- [ ] `SolrAdapter.scan_all` implements `cursorMark` with uniqueKey-terminated sort + terminal detection; `close_scan` is a no-op.
- [ ] `UbiReader._scan_ubi_events` + `_scan_ubi_queries` loop `scan_all`, aggregate incrementally, and call `close_scan` in `finally` on early exit; `read_features`/`read_user_query_map` signatures unchanged.
- [ ] `DEFAULT_MAX_EVENTS`/`DEFAULT_MAX_QUERIES` are total-scan ceilings; the default is `Settings`-backed and centralized in `UbiReader` so worker/dispatcher/readiness all inherit it; `page_size <= ES_MAX_RESULT_WINDOW`.
- [ ] Ceiling enforced exactly (no page-rounding overshoot, AC-13); large `query_id` sets chunked so no oversized Solr URL / ES `terms` filter is emitted (FR-7, AC-14).
- [ ] AC-1..AC-14 (incl. AC-2b, AC-3b) pass in CI; the rung-3 real-engine paginated scenario (ES + Solr) is added/extended.
- [ ] `test_ubi_reader_no_writes` extended; no write-shaped request escapes.
- [ ] `make lint` + `make typecheck` + `make test-unit` + `make test-contract` clean; coverage ≥ 80%.
- [ ] `adapters.md` + `judgment-generation-debugging.md` updated; `llm-data-flow.md` confirmed unchanged-by-design.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

- None blocking. One implementation-time choice deferred to the plan: the exact `ScanPage`/cursor token encoding (a Pydantic model vs a small dataclass; how the ES `pit_id`+`sort` and Solr `nextCursorMark` are packed into one opaque `cursor`). Recommended default: a single `ScanPage(hits: list[ScoredHit], cursor: <opaque str|object> | None)` where the cursor is engine-internal and round-tripped verbatim by the caller (the caller never inspects it). This keeps `UbiReader` cursor-agnostic.

### Decision log

- 2026-06-02 — **D-1: New `scan_all` method, not an extended `search_batch`.** `search_batch` is the multi-query `_msearch` hot path with a `query_id`-mapping + `strict_errors`/`timeout` contract tuned for the Optuna trial runner. A dedicated single-target cursor method mirrors the `list_documents` precedent (also separate, also cursor-based, also abstracting `search_after` vs `cursorMark`). Rationale: overloading `search_batch` couples two incompatible contracts and risks the hot path.
- 2026-06-02 — **D-2: ES/OpenSearch use `search_after` with PIT as the consistency default; Solr uses `cursorMark` (best-effort under live writes).** Both ES and OpenSearch support PIT (at different endpoints — see D-5); a long multi-page scan over a live append-heavy `ubi_events` index needs snapshot consistency to avoid skip/double-count, so PIT is the default (with `_shard_doc` tiebreaker). `list_documents` skips PIT because a single browse page tolerates churn; a full scan does not. PIT-unsupported (narrowed to 405/501/400-unsupported by D-7) falls back per D-8 — no-PIT `search_after` over a configured doc_values tiebreaker, or a sampled 10k single query when none is configured (never an unsafe `_id` sort). **Solr has no PIT** and uses the documented `cursorMark` deep-paging idiom — which is exact only over a finalized window; under concurrent writes the Solr scan is best-effort (Review A3). UBI windows are normally historical, so this is acceptable; documented in the runbook.
- 2026-06-02 — **D-3: Raise the ceiling, don't remove it.** `DEFAULT_MAX_EVENTS`/`DEFAULT_MAX_QUERIES` become total-scan ceilings (`Settings`-backed default, high but finite) rather than per-call `size` clamps. The reader logs `ubi_reader_scan_truncated` when the ceiling is hit. Rationale: an unbounded scan on a pathological index is a footgun; a visible bound preserves the honest-sample property while lifting the silent 10k floor.
- 2026-06-02 — **D-4: The caller (reader) still builds the engine-shaped filter body; `scan_all` only owns pagination.** `UbiReader` already branches `engine_type == "solr"` to build a Solr request-param body vs an ES Query DSL body (the filter shape genuinely differs and the reader already owns it — pre-shipped). `scan_all` accepts that body and adds only the pagination/sort/PIT scaffolding. Rationale: minimizes the new Protocol surface and reuses the reader's existing, tested filter builders. **Acknowledged Rule #4 deviation (Review A4):** this is a narrow, pre-existing exception scoped to body construction, not pagination. The clean alternative — an adapter-side UBI query builder so the reader supplies engine-neutral criteria — is a larger refactor than this scaling chore and is recorded here as a **deferred option**, not undertaken now.
- 2026-06-02 — **D-5 (amended): One `ElasticAdapter.scan_all`/`close_scan` serves ES and OpenSearch, with one adapter-internal PIT-endpoint branch.** Both are the same adapter class. The original D-5 ("no per-engine branch") was **wrong** — ES PIT is `POST/DELETE /<index>/_pit`; OpenSearch PIT is `POST/DELETE /<index>/_search/point_in_time` (Review A2). The fix: a single `scan_all` with an internal `self.engine_type` branch ONLY for the PIT path/body. The branch stays inside `ElasticAdapter` (Rule #4); the public Protocol is engine-neutral.
- 2026-06-02 — **D-6: Centralize the scan ceiling default in `UbiReader`.** All three construction sites (worker, dispatcher, readiness) inherit a `Settings`-backed ceiling resolved inside `UbiReader`, so a caller that omits the kwarg never silently falls back to 10k (Review B1). Per-call `max_events`/`max_queries` kwargs still override.
- 2026-06-02 — **D-7: `scan_all` cursor lifecycle is explicit via `close_scan`; the reader closes on early exit.** Page-at-a-time `scan_all` cannot self-close a PIT when the caller stops before the terminal page (ceiling/error). Added `SearchAdapter.close_scan(cursor)` (ES/OpenSearch: `DELETE` the PIT; Solr: no-op); `UbiReader` calls it in `finally` whenever it exits holding a non-terminal cursor (Review A1/B2). PIT-unsupported fallback is narrowed to 405/501/400-unsupported so 401/403/404 keep the normal error envelope (Review A4-fallback).
- 2026-06-02 — **D-8: No-PIT fallback never sorts on `_id`.** ES 9 disables `_id` fielddata by default, so `sort: [{_id: asc}]` returns HTTP 400 (the reason `list_documents` sorts on `_doc`). Without a PIT, `_doc` is not a stable cross-page total order either. So the no-PIT fallback paginates over `[timestamp, <doc_values tiebreaker>]` when a `Settings.ubi_no_pit_tiebreaker_field` is configured; when none is configured it falls back to the original single 10k-capped query + a "sampled, not full" WARN. Rationale (cycle-2 C2-3): correctness-over-completeness — a wrong total order would skip/duplicate events, which is worse than an honest sample.

### Review log

**Cross-model review: GPT-5.5 (`gpt-5.5`), 2 cycles.**

- **Cycle 1 (2026-06-02):** 8 findings (3 High, 5 Medium). Adjudication:
  - **A1 (High) — PIT leak on early-exit/ceiling truncation:** ACCEPTED. Added `SearchAdapter.close_scan` (FR-1, D-7), reader `finally`-close on early exit (FR-4), AC-9.
  - **A2 (High) — ES vs OpenSearch PIT endpoints differ:** ACCEPTED. Added adapter-internal PIT-endpoint branch (FR-2, D-5 amended), AC-10.
  - **A3 (High) — Solr `cursorMark` is not a snapshot:** ACCEPTED. Downgraded Solr to best-effort-under-live-writes / exact-over-finalized-window in Purpose, §9, §11, FR-3, D-2; runbook caveat in §15.
  - **A4 (Medium) — PIT-fallback too broad (would swallow auth/404):** ACCEPTED. Narrowed fallback to 405/501/400-unsupported (FR-2, D-7), AC-11.
  - **A4-Rule#4 (Medium) — reader engine-branch contradicts "engine code only in adapters":** ACCEPTED as clarification. Reframed §4 + D-4 as an acknowledged, narrow, pre-existing exception with the clean refactor recorded as a deferred option (not a denial of the contradiction).
  - **B1 (Medium) — ceiling only required on worker, not dispatcher/readiness:** ACCEPTED. Centralized the default in `UbiReader` (FR-5, D-6), AC-12.
  - **B2 (Medium) — no test for early-termination PIT close:** ACCEPTED. AC-9 + reader/adapter test tasks in §14.
  - **B3 (Medium) — MockTransport can't verify real cursor/PIT behavior:** ACCEPTED (as scoped real-engine coverage). Added a rung-3 real-engine paginated scenario requirement (ES + Solr) in §14; kept hermetic CI mock-only per CLAUDE.md "no managed-cloud CI lane" — OpenSearch real-engine coverage tracked, non-blocking.
  - Findings rejected: none.
- **Cycle 2 (2026-06-02):** re-review of the patched spec. 4 new Medium findings, all internal-consistency / correctness gaps from the cycle-1 patches. All ACCEPTED:
  - **C2-1 — §11 still said "any 4xx → fallback":** fixed §11 to match the narrowed FR-2/AC-11 (405/501/400-unsupported only; 401/403/404 propagate).
  - **C2-2 — §4/§5 still listed ES `_pit` for OpenSearch:** fixed both to split the ES vs OpenSearch PIT endpoints (D-5); no-writes allowlist must cover both families.
  - **C2-3 — `_id` not sortable by default in ES 9:** added D-8 + AC-3b — no-PIT fallback uses a configured doc_values tiebreaker or a sampled 10k single query, never an unsafe `_id` sort.
  - **C2-4 — §16 release gate contradicted §14/§18 on the rung-3 lane:** fixed §16 to classify the rung-3 ES+Solr paginated scenario as required-validation / non-blocking-for-merge, consistent with hermetic CI.
  - Findings rejected: none.
- **Cycle 3 (2026-06-02):** 2 new Medium findings, both stale references the cycle-2 patches missed. Both ACCEPTED:
  - **C3-1 — FR-2 Notes + §9 still cited `_id` as the no-PIT tiebreaker:** fixed both to point at the configured doc_values tiebreaker / sampled-fallback (D-8) and to state the no-tiebreaker branch returns a single sampled page (no cross-page total order needed there).
  - **C3-2 — PIT search must be `POST /_search` (no index in URL), not `POST /<index>/_search`:** a PIT binds the target, so the index is omitted from the search URL. Fixed §4 + AC-7 to distinguish PIT-mode `POST /_search` from no-PIT fallback `POST /<target>/_search`; allowlist covers both.
  - Findings rejected: none.
- **Cycle 4 (2026-06-02):** 3 new Medium findings (deeper-layer issues exposed as the contract firmed up). All ACCEPTED:
  - **C4-1 — ES/OpenSearch no-PIT fallback also best-effort under live writes (not just Solr):** amended FR-2/§9/§11 + D-8 to scope snapshot-consistency to PIT-mode only; both no-PIT paths (Solr cursorMark + ES no-PIT) are exact only over a finalized window.
  - **C4-2 — ceiling can overshoot by up to one page when not page-aligned:** added exact-enforcement requirement to FR-4 (`page_size=min(configured, remaining)` + final-page slice) + AC-13 (non-aligned `max_events=15001`).
  - **C4-3 — large `query_id IN` filter can exceed Solr GET-URL / ES `terms` limits:** added FR-7 (chunk the event scan by `query_id` batches, merge accumulators, respect the global `max_events` ceiling) + AC-14.
  - Findings rejected: none.
- **Cycle 5 (2026-06-02):** 2 new findings (1 High, 1 Medium) on PIT-protocol details. Both ACCEPTED:
  - **C5-1 (High) — PIT id can rotate between searches; must propagate the latest id into the next request + close:** amended FR-2 (cursor carries the latest id; close uses it) + AC-2/AC-2b. Closing a stale id would leak the live PIT.
  - **C5-2 (Medium) — every continuation `POST /_search` must re-send `pit.keep_alive`:** amended FR-2 + AC-2b so the PIT cannot expire mid-scan on long scans.
  - Findings rejected: none.
- **Cycle 6 (2026-06-02):** re-review with the full cycles-1–5 rejection/resolution log in the system prompt — returned an empty `findings` set (**0 High/Medium findings**) across repeated calls. Converged after 5 substantive cycles (16 findings total: 4 High, 12 Medium; all ACCEPTED, none rejected, none deferred). Spec finalized.
