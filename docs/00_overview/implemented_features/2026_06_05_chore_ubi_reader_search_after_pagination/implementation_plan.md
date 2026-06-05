# Implementation Plan — Exact full-traffic UBI aggregation via cursor pagination (`scan_all`)

**Date:** 2026-06-02
**Status:** Complete (PR #474, squash-merged `d9afbce` 2026-06-05)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** CLAUDE.md (Absolute Rule #4 — engine code only in adapters; Conventional Commits + DCO sign-off; read-only UBI contract; no migration)

---

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs (FR-1..FR-7).
- Adapter Protocol discipline (Rule #4): all pagination mechanics (`search_after`/PIT, `cursorMark`) live ONLY in `elastic.py` + `solr.py`. The reader loops a generic cursor.
- Reuse the shipped precedent: `list_documents` (`elastic.py:767-859`, `solr.py:1577-1690`) already abstracts ES `search_after` vs Solr `cursorMark` behind one return shape — `scan_all` mirrors it.
- Read-only invariant is load-bearing: no write-shaped request escapes `scan_all`; PIT open/close are read-side and explicitly allowlisted.
- No migration, no UI, no new LLM call, no `search_batch` change.
- Correctness over completeness: when neither PIT nor a sortable tiebreaker exists, fall back to the honest 10k sample (never an unsafe `_id` sort).

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic/Phase | Notes |
|---|---|---|
| FR-1 | Epic 1 / Story 1.1 | `scan_all` + `close_scan` Protocol methods + `ScanPage` shape + `test_protocol.py` |
| FR-2 | Epic 2 / Story 2.1 | `ElasticAdapter.scan_all`/`close_scan` — ES + OpenSearch PIT + `search_after`, latest-id propagation, narrow fallback, no-`_id`-sort |
| FR-3 | Epic 2 / Story 2.2 | `SolrAdapter.scan_all`/`close_scan` — `cursorMark` |
| FR-4 | Epic 3 / Story 3.1 | `UbiReader` paginated incremental aggregation + exact ceiling + early-exit `close_scan` |
| FR-5 | Epic 3 / Story 3.1, 3.2 | `Settings`-backed centralized ceiling across all 3 caller paths |
| FR-6 | Epic 2 + 3 / Stories 2.1, 2.2, 3.1 | read-only invariant extended to the paginated path |
| FR-7 | Epic 3 / Story 3.1 | `query_id` chunking so no oversized Solr URL / ES `terms` filter |

No deferred phases — the spec is single-phase. No `phase<N>_idea.md` tracking required.

## 2) Delivery structure

**Structure:** Epic → Story → Tasks → DoD. Three epics: (1) Protocol surface, (2) adapter implementations, (3) reader + settings + chunking. Backend + tests only.

### Conventions (project-specific)

```
- All pagination mechanics live in backend/app/adapters/{elastic,solr}.py (Rule #4).
- scan_all/close_scan are async (httpx); render/list_query_parsers stay sync.
- ScanPage reuses ScoredHit; no new per-hit model unless a need surfaces.
- ES PIT: open POST /<index>/_pit?keep_alive=<ttl>; close DELETE /_pit body {"id": <pit_id>}.
  OpenSearch PIT: open POST /<index>/_search/point_in_time?keep_alive=<ttl>;
  close DELETE /_search/point_in_time body {"pit_id": [<pit_id>]}.
- PIT-mode search is POST /_search (NO index in URL — the PIT binds the target).
- PIT mode injects a deterministic total-order sort [{timestamp:asc},{_shard_doc:asc}];
  the adapter reads the LAST hit's raw `sort` array and packs it into the opaque cursor
  for the next page's search_after (ScoredHit does NOT expose `sort` — the reader never
  needs it; the adapter holds it inside the cursor).
- Pagination keys are ADAPTER-OWNED, never caller-overridable (P3-A1 / P4-A2): the merge
  is {**body, <pagination keys>} (body FIRST, pagination keys overwrite) AND the adapter
  strips any caller pagination key leaking from the inherited body — ES: `from`,
  `search_after`, `size`, `sort`, **`pit`** (then sets `pit`/`sort`/`size`/`search_after`
  in PIT mode; in the no-PIT fallback the stripped `pit` guarantees no stray caller PIT
  leaks into `POST /<target>/_search` — P5-A1);
  Solr: `start`, `rows`, `cursorMark`, `sort` (then sets `rows`/`cursorMark`/`sort`).
  Solr `start` is especially load-bearing: it is INVALID combined with `cursorMark` and
  would error or skip/duplicate rows — it MUST be stripped.
- Cleanup is BEST-EFFORT on BOTH the exception path AND the normal terminal close
  (P3-A2 / P4-A3): close_scan / terminal PIT-DELETE failures are caught + logged (no
  secret); on the exception path the PRIMARY exception is re-raised; on the terminal
  path the completed ScanPage(hits, cursor=None) is still returned — a close failure
  never masks the original error and never masks a successful final page.
- Every PIT search request carries pit:{id:<latest>, keep_alive:<ttl>}; the latest
  PIT id from each response replaces the prior one in the cursor + close.
- PIT response field names differ by engine (P2-A2): ES open-PIT response returns
  {"id": <pit_id>}; OpenSearch open-PIT returns {"pit_id": <pit_id>}. PIT-mode
  _search responses echo the (possibly rotated) PIT id under "pit_id" (ES) — the
  adapter reads the engine-correct field, retaining the prior id if the response
  omits it. Tests assert these exact response field names per engine.
- No-PIT fallback never sorts on _id (ES 9 rejects it). Use a configured
  Settings.ubi_no_pit_tiebreaker_field, else a single sampled 10k query + WARN.
- Ceiling is enforced exactly: page_size = min(configured_page_size, remaining_budget)
  and/or slice the final page.
- Large query_id sets are chunked so no single Solr request or ES terms list exceeds
  engine limits. Solr `scan_all` uses POST /<target>/select (form/body params) — NOT a
  GET URL — so a multi-thousand-id {!terms} fq does not overflow URL/header limits
  (P1-B1). A batch is split whenever EITHER Settings.ubi_query_id_batch_size (id count)
  OR Settings.ubi_query_id_batch_max_bytes (encoded byte length, the HARD limit) would be
  exceeded (P2-B1). ES terms list stays under index.max_terms_count (default 65536) per chunk.
- Tests: asyncio_mode="auto" (no decorator). MockTransport for adapter HTTP shapes.
- Commit with `git commit -s` (DCO) + Conventional Commits `chore:` prefix.
```

### AI Agent Execution Protocol

0. Load context: read `architecture.md` + `state.md` + `docs/01_architecture/adapters.md`.
1. Read story scope (outcome + modified files + DoD).
2. Implement the change behind the adapter Protocol (Rule #4).
3. Add/update tests at the right layer (Protocol → `test_protocol.py`; adapter → `test_*_scan_all.py`; reader → `test_ubi_reader.py` + `test_ubi_reader_no_writes.py`).
4. Run `make test-unit` (targeted), `make lint`, `make typecheck`.
5. No frontend, no migration, no docs-beyond-state.md until finalization.
6. Attach evidence (commands run + pass/fail) at finalization.

---

## Epic 1 — Protocol surface (`scan_all` + `close_scan` + `ScanPage`)

**Epic gate (hard stop):** `SearchAdapter.scan_all` + `close_scan` declared in `protocol.py`; `ScanPage` return shape defined; `test_protocol.py` lists both methods exhaustively (stub + both coroutine lists + Solr branch); `make test-unit` for `test_protocol.py` + `make typecheck` clean.

### Story 1.1 — Add `scan_all` / `close_scan` to the SearchAdapter Protocol
**Outcome:** The Protocol declares the cursor-scan surface; the shape test enforces it across the stub, ES adapter, and Solr adapter; `ScanPage` carries `hits` + an opaque `cursor`.

**New files**

None. (`ScanPage` lives in `protocol.py` alongside `ScoredHit`/`DocumentPage`.)

**Modified files**

| File | Change |
|---|---|
| `backend/app/adapters/protocol.py` | Add `class ScanPage(BaseModel)` with `hits: list[ScoredHit]` and `cursor: <opaque token> \| None` (the cursor is an engine-internal token round-tripped verbatim by the caller — spec §19 open-question default). Add to the `SearchAdapter` Protocol: `async def scan_all(self, target, body, *, page_size, cursor=None, fl=None, request_id=None) -> ScanPage` and `async def close_scan(self, cursor, *, request_id=None) -> None`. Docstrings cite the two-idiom abstraction (ES `search_after`+PIT / Solr `cursorMark`) and the `close_scan` early-exit contract. |
| `backend/tests/unit/adapters/test_protocol.py` | Add `scan_all` + `close_scan` to `_StubAdapter` (async; `scan_all` returns a terminal `ScanPage(hits=[], cursor=None)`, `close_scan` returns `None`). Append `"scan_all"` + `"close_scan"` to BOTH `iscoroutinefunction` method-name lists (the stub list `:124-134` and the SolrAdapter branch `:354-365`). Add `ScanPage` validity tests (valid empty, valid with hits, cursor None vs token). |

**Endpoints**

N/A — internal Protocol method, no HTTP surface.

**Key interfaces**

```python
# backend/app/adapters/protocol.py
class ScanPage(BaseModel):
    """One page of a full-stream scan (scan_all). `cursor=None` == terminal page.

    The cursor is an opaque, engine-internal continuation token (ES: encodes the
    latest pit_id + trailing sort + a no_pit flag; Solr: the nextCursorMark). The
    caller round-trips it verbatim and never inspects it; it stays engine-agnostic.
    """
    hits: list[ScoredHit]
    cursor: object | None = None  # opaque; final encoding chosen by the adapters

class SearchAdapter(Protocol):
    ...
    async def scan_all(
        self, target: str, body: dict[str, Any], *,
        page_size: int, cursor: object | None = None,
        fl: list[str] | None = None, request_id: str | None = None,
    ) -> ScanPage: ...

    async def close_scan(self, cursor: object | None, *, request_id: str | None = None) -> None:
        """Release any engine-side resource held by a NON-terminal cursor (ES/OS:
        DELETE the latest PIT; Solr: no-op). Safe with cursor=None; idempotent."""
        ...
```

**Tasks**
1. Define `ScanPage` in `protocol.py`.
2. Add `scan_all` + `close_scan` to the `SearchAdapter` Protocol with docstrings.
3. Extend `_StubAdapter` + both coroutine method-name lists + `ScanPage` validity tests in `test_protocol.py`.

**Definition of Done (DoD)**
- `protocol.py` declares `scan_all`, `close_scan`, `ScanPage` (FR-1).
- `test_protocol.py` asserts both methods are coroutines on stub + Solr branch (AC-1).
- `make test-unit` (`test_protocol.py`) + `make typecheck` clean.

---

## Epic 2 — Adapter implementations (ES/OpenSearch + Solr)

**Epic gate (hard stop):** `ElasticAdapter` + `SolrAdapter` implement `scan_all`/`close_scan`; ES PIT id-rotation + keep_alive + narrow fallback + no-`_id`-sort all covered; Solr `cursorMark` + no-op close covered; read-only invariant holds for both; `make test-unit` (the two new adapter test files) + `make lint` + `make typecheck` clean.

### Story 2.1 — `ElasticAdapter.scan_all` / `close_scan` (ES + OpenSearch)
**Outcome:** ES + OpenSearch paginate `ubi_events`/`ubi_queries` over the full stream via `search_after` inside a PIT (with id rotation + keep_alive renewal), close the PIT on terminal/early-exit/error, branch the PIT endpoint by `engine_type`, narrow the PIT-unsupported fallback, and never sort on `_id`.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/adapters/test_elastic_scan_all.py` | `MockTransport`-driven ES + OpenSearch `scan_all`/`close_scan` tests (pattern: `test_elastic_list_documents.py`). |

**Modified files**

| File | Change |
|---|---|
| `backend/app/adapters/elastic.py` | Implement `scan_all` + `close_scan`. PIT-mode: open PIT (engine-branched endpoint + `?keep_alive`), loop `POST /_search` (index-less) with `{pit:{id:<latest>,keep_alive}, sort:[{timestamp:asc},{_shard_doc:asc}], size:page_size, search_after?, ...body}`, **read the last hit's raw `sort` array** and pack it (+ latest `pit_id` + `no_pit` flag) into the returned opaque cursor, terminate on a short page (close PIT, `cursor=None`), close PIT in `finally` on error. `close_scan(cursor)` DELETEs the latest PIT with the engine-correct **body**: ES `DELETE /_pit` body `{"id": <pit_id>}`; OpenSearch `DELETE /_search/point_in_time` body `{"pit_id": [<pit_id>]}`. Narrow fallback (405/501/400-unsupported → no-PIT path; never 401/403/404). No-`_id`-sort: no-PIT path uses `[timestamp, <Settings.ubi_no_pit_tiebreaker_field>]` if configured, else single sampled `search_batch` query + WARN. Reuse `_request` for error translation. |

**Endpoints**

N/A (adapter-internal engine calls only). Engine requests — open vs close split (P4-A1): ES open `POST /<index>/_pit`, close `DELETE /_pit` (unindexed, body `{"id":...}`); OpenSearch open `POST /<index>/_search/point_in_time`, close `DELETE /_search/point_in_time` (unindexed, body `{"pit_id":[...]}`); PIT-mode search `POST /_search` (index-less); no-PIT fallback `POST /<target>/_search`. The no-writes allowlist permits only the unindexed PIT-close paths.

**Key interfaces**

```python
# backend/app/adapters/elastic.py (sketch)
_PIT_PATHS = {  # adapter-internal engine branch (Rule #4 stays inside the adapter)
    "elasticsearch": ("/{idx}/_pit", "/_pit"),
    "opensearch":    ("/{idx}/_search/point_in_time", "/_search/point_in_time"),
}

async def scan_all(self, target, body, *, page_size, cursor=None, fl=None, request_id=None) -> ScanPage:
    # cursor is None on first page → open PIT (or no-PIT fallback / sampled).
    # cursor carries {pit_id, search_after, no_pit} → continuation.
    # Each response's pit_id (when present) replaces cursor.pit_id.
    # keep_alive sent on EVERY PIT search body.
    ...

async def close_scan(self, cursor, *, request_id=None) -> None:
    # No-op if cursor is None or cursor.no_pit. Else DELETE the latest pit_id.
    ...
```

**Tasks**
1. Implement `scan_all` PIT happy path: open → loop with `search_after` + latest-id + keep_alive → terminal close (**best-effort**: a terminal-close failure is logged but still returns `ScanPage(cursor=None)` with the final page — P4-A3).
2. Implement `close_scan` (DELETE latest PIT; no-op for None / no-PIT cursors); call it from `scan_all`'s `finally` on error **best-effort** — catch+log a close failure and re-raise the primary exception so cleanup never masks the original error (P3-A2). Pagination keys (`pit`/`sort`/`size`/`search_after`) are adapter-owned and overwrite anything in the caller `body`; strip caller `from`/`search_after`/`size`/`sort`/**`pit`** before BOTH PIT and no-PIT request construction (so no stray caller `pit` leaks into the no-PIT fallback — P3-A1/P5-A1).
3. Engine-branch the PIT open/close endpoint by `self.engine_type` (ES `_pit` vs OpenSearch `_search/point_in_time`) AND the PIT-id response field (ES open → `id`; OpenSearch open → `pit_id`; `_search` echo → engine-correct field, retain prior id if omitted). Add MockTransport tests with the exact per-engine response bodies asserting the rotated id is used in the next request + close (P2-A2).
4. Narrow PIT-unsupported fallback (405/501/400-unsupported only); 401/403/404 propagate via `_request`'s normal translation.
5. No-`_id`-sort: configured-tiebreaker no-PIT pagination, else single sampled query + WARN.
6. Capture the last hit's raw `sort` array into the cursor each page (the `search_after` continuation value); inject `[{timestamp:asc},{_shard_doc:asc}]` as the PIT sort.
7. Write `test_elastic_scan_all.py`: AC-2 (open/continue/close + assert exact `sort`/`search_after` across pages), AC-2b (id rotation + keep_alive on every continuation), AC-3 (fallback w/ tiebreaker), AC-3b (sampled fallback, no `_id` sort), AC-8 (mid-scan error closes PIT), AC-10 (OpenSearch endpoints **+ close-request body shape**), AC-11 (401/403/404 do NOT fall back), `close_scan` closes latest id with the correct body (AC-9 adapter half), **pagination-key precedence** (input `body` with stray `sort`/`size`/`from`/`search_after`/`pit` → PIT sort/page size still win, stray keys stripped, and the no-PIT fallback request emits NO `pit` — P3-A1/P5-A1), **best-effort cleanup** (page-error-plus-close-error → original exception preserved, P3-A2; terminal-close-error → final page still returned, P4-A3). Assert the ES close body `{"id":...}` and OpenSearch close body `{"pit_id":[...]}`, not just the path.

**Definition of Done (DoD)**
- `ElasticAdapter.scan_all`/`close_scan` implement FR-2 fully (id rotation, keep_alive, engine-branched PIT endpoint, narrow fallback, no-`_id`-sort, `finally`-close).
- `test_elastic_scan_all.py` covers AC-2, AC-2b, AC-3, AC-3b, AC-8, AC-10, AC-11 + `close_scan`.
- `make test-unit` (`test_elastic_scan_all.py`) + `make lint` + `make typecheck` clean.

### Story 2.2 — `SolrAdapter.scan_all` / `close_scan` (`cursorMark`)
**Outcome:** Solr paginates the full stream via `cursorMark` over a uniqueKey-terminated sort, terminates exactly as `list_documents` does, validates request params, uses **POST** `/select` so a large `{!terms}` fq does not overflow the URL, and `close_scan` is a no-op.

**Correctness precondition (functional contract, not just runbook — P1-A3):** the Solr scan is snapshot-exact only when the window `[since, until)` is finalized (no further commits). Under concurrent writes it is best-effort. The story's docstring + the runbook state this; UBI judgment windows are normally historical.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/adapters/test_solr_scan_all.py` | `MockTransport`-driven Solr `scan_all` tests (pattern: `test_solr_get_document_list_documents.py`). |

**Modified files**

| File | Change |
|---|---|
| `backend/app/adapters/solr.py` | Implement `scan_all`: **POST** `/<target>/select` (form-encoded body params — NOT a GET URL, so a multi-thousand-id `{!terms f=query_id}` fq cannot overflow URL/header limits, P1-B1) with `cursorMark=*` first page → `nextCursorMark` continuation; `sort` includes the uniqueKey (`_resolve_unique_key`); body passes `_validate_solr_param_values`; terminal when `nextCursorMark == request cursorMark` (or short-page guard) → `cursor=None`. Implement `close_scan` as a no-op (cursorMark holds no server resource). |

**Endpoints**

N/A (adapter-internal). Engine request: Solr `POST /<collection>/select` (form-encoded body params — P1-B1; the large `{!terms}` fq lives in the body, never the URL).

**Key interfaces**

```python
# backend/app/adapters/solr.py (sketch)
async def scan_all(self, target, body, *, page_size, cursor=None, fl=None, request_id=None) -> ScanPage:
    unique_key = await self._resolve_unique_key(target, request_id=request_id)
    cursor_mark = cursor or "*"
    safe_body = {k: v for k, v in body.items()
                 if k not in ("start", "rows", "cursorMark", "sort")}  # strip caller paging (P4-A2)
    params = {**safe_body, "rows": str(page_size), "cursorMark": cursor_mark,
              "sort": f"... ,{unique_key} asc", "fl": ...}  # NO `start` with cursorMark
    _validate_solr_param_values(params)
    # ... POST /select (form body, not GET URL); next = nextCursorMark;
    # terminal if next == cursor_mark or short page.

async def close_scan(self, cursor, *, request_id=None) -> None:
    return  # cursorMark holds no server-side resource
```

**Tasks**
1. Implement `scan_all` `cursorMark` loop via **POST** `/<target>/select` (form body) with uniqueKey-terminated sort + `_validate_solr_param_values`. **Strip caller `start`/`rows`/`cursorMark`/`sort` from the inherited body** before setting adapter-owned values — `start` is invalid with `cursorMark` (P4-A2).
2. Terminal detection: `nextCursorMark == request cursorMark` + short-page secondary guard (mirror `list_documents`).
3. Implement `close_scan` no-op.
4. Write `test_solr_scan_all.py`: AC-4 (open/continue/terminal), uniqueKey-in-sort, param validation, **POST (not GET) with a large `{!terms}` fq in the body** (AC-14 Solr half), **stray-paging-key strip** (input `body={start,rows,cursorMark,sort}` → outgoing POST has no `start` and uses the adapter cursor/sort/rows, P4-A2), `close_scan` no-op.

**Definition of Done (DoD)**
- `SolrAdapter.scan_all`/`close_scan` implement FR-3.
- `test_solr_scan_all.py` covers AC-4 + uniqueKey + validation + no-op close.
- `make test-unit` (`test_solr_scan_all.py`) + `make lint` + `make typecheck` clean.

---

## Epic 3 — Reader pagination, settings ceiling, and `query_id` chunking

**Epic gate (hard stop):** `UbiReader._scan_ubi_events` + `_scan_ubi_queries` loop `scan_all` and aggregate incrementally; exact ceiling enforced; `close_scan` called on early exit; `Settings` ceiling centralized across all 3 caller paths; large `query_id` sets chunked; read-only invariant holds; `read_features`/`read_user_query_map` signatures unchanged; `make test-unit` + `make lint` + `make typecheck` + `make test-contract` clean; coverage ≥ 80%.

### Story 3.1 — `UbiReader` paginated incremental aggregation + exact ceiling + chunking
**Outcome:** The reader iterates the full event/query stream via `scan_all`, folds each page in, enforces the ceiling exactly, closes the cursor on early exit, and chunks large `query_id` sets so no oversized filter is emitted.

**New files**

None. (Tests extend the existing reader test files.)

**Modified files**

| File | Change |
|---|---|
| `backend/app/services/ubi_reader.py` | Rewrite `_scan_ubi_events` + `_scan_ubi_queries` to loop `adapter.scan_all` (passing the existing per-engine filter body they already build via `_build_solr_ubi_body` / ES DSL) until `cursor is None`, folding each page into the accumulators. Enforce the ceiling exactly: `page_size = min(configured_page_size, remaining_budget)` + slice final page. Call `adapter.close_scan(cursor)` in `finally` whenever the loop exits holding a non-terminal cursor (ceiling/exception). Chunk `_scan_ubi_events` by `query_id` batches (`Settings.ubi_query_id_batch_size`), merging per-batch accumulators, respecting the global `max_events` ceiling. Log `ubi_reader_scan_truncated` (exact count) on ceiling hit. Repurpose `DEFAULT_MAX_EVENTS`/`DEFAULT_MAX_QUERIES` as ceilings; keep `page_size <= ES_MAX_RESULT_WINDOW`. Public `read_features`/`read_user_query_map` signatures unchanged. |
| `backend/tests/unit/services/test_ubi_reader.py` | Add/migrate: multi-page aggregation (AC-5), ceiling truncation + `close_scan`-on-early-exit (AC-6, AC-9 reader half), exact non-page-aligned ceiling (AC-13), `Settings`-ceiling via no-kwarg construction (AC-12), large `query_id`-set chunking with merged accumulator + no-oversized-filter assertion (AC-14). Migrate existing single-`search_batch` expectations to the `scan_all` loop. |
| `backend/tests/unit/services/test_ubi_reader_no_writes.py` | Extend the httpx-transport invariant to the paginated path; allowlist both PIT endpoint families + both search shapes (`POST /_search`, `POST /<target>/_search`); assert zero `_bulk`/`_doc`/`_update`/`_create`/index-`DELETE` (AC-7). |

**Endpoints**

N/A — service layer, no HTTP surface.

**Key interfaces**

```python
# backend/app/services/ubi_reader.py (sketch — _scan_ubi_events)
async def _scan_ubi_events(self, *, target, since, until, query_ids, max_events, request_id):
    out: list[dict] = []
    remaining = max_events
    # _chunk bounds each batch by BOTH id-count (self._ubi_query_id_batch_size)
    # AND encoded byte-length (self._ubi_query_id_batch_max_bytes), where the
    # byte budget is measured on the FULLY-SERIALIZED filter fragment — i.e. the
    # wrapper + separators (Solr `{!terms f=query_id}a,b,c` / ES terms-list JSON),
    # NOT just the summed raw id lengths — so the request body/URL stays under
    # engine limits regardless of id length (P1-B1; Gemini PR #413 finding #3 —
    # accepted, serialization-overhead clarification).
    #
    # NOTE (Gemini PR #413 finding #2 — accepted, remedy adjusted): `UbiReader`
    # is deliberately decoupled from `Settings` (ctor takes only `adapter` +
    # injected values, mirroring `position_bias_prior` — see ubi_reader.py
    # docstring ~L189-190). So these two ceilings are resolved by the CALLER from
    # `Settings` and INJECTED via `__init__` (stored as `self._ubi_query_id_batch_size`
    # / `self._ubi_query_id_batch_max_bytes`); the sketch references the instance
    # attrs, never a module-level `settings` (which is out of scope here and would
    # NameError). Do NOT call `get_settings()` inside the reader — that breaks the
    # established decoupling. (`UBI_EVENTS_INDEX` below is correct as-is: it is a
    # module-level constant at ubi_reader.py:75, already used directly at L515 —
    # not an instance attr; Gemini finding #4 rejected as stale.)
    for batch in _chunk(query_ids, self._ubi_query_id_batch_size, self._ubi_query_id_batch_max_bytes):
        body = self._build_events_filter(target, since, until, batch)  # existing per-engine builder
        cursor = None
        try:
            while remaining > 0:
                page = await self._adapter.scan_all(
                    UBI_EVENTS_INDEX, body,
                    page_size=min(ES_MAX_RESULT_WINDOW, remaining),
                    cursor=cursor, fl=..., request_id=request_id,
                )
                cursor = page.cursor  # assign the LATEST cursor IMMEDIATELY after await,
                                      # BEFORE any folding — so a fold-time exception still
                                      # closes the rotated PIT in `finally` (P1-B2).
                take = page.hits[:remaining]
                out.extend(h.source for h in take if h.source is not None)
                remaining -= len(take)
                if cursor is None or len(take) < len(page.hits):
                    break  # terminal OR ceiling reached mid-page
        finally:
            # Best-effort cleanup (P3-A2): a close failure must not mask a
            # page/fold exception propagating out of the try.
            try:
                await self._adapter.close_scan(cursor, request_id=request_id)  # no-op if None
            except Exception:  # noqa: BLE001 — cleanup swallow + log
                logger.warning("ubi_reader_close_scan_failed", ...)
        if remaining <= 0:
            logger.warning("ubi_reader_scan_truncated", scanned=max_events, ceiling=max_events, ...)
            break
    return out
```

**Tasks**
1. Rewrite `_scan_ubi_events` + `_scan_ubi_queries` to loop `scan_all` with exact ceiling + `finally`-close. **Assign `cursor = page.cursor` immediately after the await, before folding** (P1-B2), so a fold-time exception still closes the rotated PIT.
2. Add `query_id` chunking to `_scan_ubi_events` — split a batch whenever EITHER `Settings.ubi_query_id_batch_size` (id count) OR `Settings.ubi_query_id_batch_max_bytes` (encoded byte length) would be exceeded (P1-B1/P2-B1); merge per-batch accumulators; respect the global `max_events` ceiling. AC-14 constructs ids that exceed the byte ceiling at a count below the id ceiling and asserts the reader still splits.
3. Repurpose `DEFAULT_MAX_EVENTS`/`DEFAULT_MAX_QUERIES` as ceilings; keep `page_size` clamp `<= ES_MAX_RESULT_WINDOW`.
4. Keep `read_features`/`read_user_query_map` signatures + empty-window `{}` fallbacks + `_probe_enabled` unchanged.
5. Extend `test_ubi_reader.py` (AC-5, AC-6, AC-9, AC-12, AC-13, AC-14) + a **fold-time-exception test** asserting `close_scan` is still called on the latest cursor (P1-B2) + migrate single-call expectations.
6. Extend `test_ubi_reader_no_writes.py` (AC-7) — allowlist PIT endpoints + both search shapes.

**Definition of Done (DoD)**
- `_scan_ubi_events`/`_scan_ubi_queries` loop `scan_all`, aggregate incrementally, enforce the exact ceiling, close on early exit, chunk large `query_id` sets (FR-4, FR-6, FR-7).
- `read_features`/`read_user_query_map` signatures unchanged; existing callers unaffected.
- `test_ubi_reader.py` covers AC-5, AC-6, AC-9, AC-12, AC-13, AC-14; `test_ubi_reader_no_writes.py` covers AC-7.
- `make test-unit` + `make test-contract` + `make lint` + `make typecheck` clean; coverage ≥ 80%.

### Story 3.2 — Centralized `Settings`-backed scan ceiling
**Outcome:** The scan ceiling default lives in `Settings` and is resolved inside `UbiReader` so the worker, dispatcher, and readiness service all inherit it — no construction site can silently fall back to 10k.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `backend/app/core/settings.py` | Add non-secret config fields: `ubi_max_events_scan: int` (high finite default), `ubi_max_queries_scan: int`, `ubi_query_id_batch_size: int` (id-count ceiling per batch), `ubi_query_id_batch_max_bytes: int` (encoded byte-length hard ceiling per batch — P2-B1), `ubi_no_pit_tiebreaker_field: str \| None = None`. Bare env vars are fine (non-secret config — Absolute Rule #2 applies only to secrets). |
| `backend/app/services/ubi_reader.py` | `UbiReader.__init__` accepts the four ceilings (`max_events`/`max_queries`/`ubi_query_id_batch_size`/`ubi_query_id_batch_max_bytes`) as **constructor args injected by the caller** (mirroring how `position_bias_prior` is already injected — the reader stays decoupled from `Settings` per its docstring ~L189-190; it does **not** import or call `get_settings()`). The caller (worker/service) resolves the defaults from `Settings` and passes them in; `read_features`/`read_user_query_map` `max_events`/`max_queries` kwargs then default to the injected ceiling, not a hardcoded constant. Per-call kwargs still override. (Gemini PR #413 finding #2 — accepted; remedy adjusted to injection rather than in-reader `get_settings()` to preserve the decoupling.) |
| `backend/tests/unit/services/test_ubi_reader.py` | AC-12: construct `UbiReader` without an explicit `max_events` kwarg (as dispatcher/readiness do) + a configured `Settings.ubi_max_events_scan`; assert the scan truncates at the `Settings` ceiling, not 10k. |

**Endpoints**

N/A.

**Key interfaces**

```python
# backend/app/core/settings.py
ubi_max_events_scan: int = 1_000_000      # high but finite ceiling (D-3)
ubi_max_queries_scan: int = 200_000
ubi_query_id_batch_size: int = 1024       # id-count ceiling per event-scan batch (FR-7)
ubi_query_id_batch_max_bytes: int = 32_768  # encoded byte ceiling per batch — HARD limit
                                            # (a batch is split whenever EITHER ceiling is hit;
                                            # keeps ES terms list + Solr POST body bounded) — P2-B1
ubi_no_pit_tiebreaker_field: str | None = None  # doc_values unique field for no-PIT fallback (D-8)
```

**Tasks**
1. Add the four `Settings` fields with documented defaults.
2. Resolve the ceiling default inside `UbiReader` (constructor reads settings); keep per-call override kwargs.
3. Verify all three construction sites (`judgments_ubi.py:375`, `agent_judgments_dispatch.py:501`, `ubi_readiness.py:182`) inherit the shared default with no code change beyond construction (they already pass the adapter; they need not pass the ceiling).
4. Add AC-12 test.

**Definition of Done (DoD)**
- The ceiling default is `Settings`-backed and centralized in `UbiReader`; all three callers inherit it (FR-5).
- AC-12 passes.
- `make test-unit` + `make lint` + `make typecheck` clean.

---

## UI Guidance (required for frontend-facing work)

N/A — no frontend scope. No legacy behavior parity table — no user-facing component is being deleted or migrated (the only behavior change is internal: a sampled scan becomes a full/ceilinged scan).

---

## 3) Testing workstream (required)

### 3.1 Unit tests
- Location: `backend/tests/unit/`
- Tasks:
  - [ ] `adapters/test_protocol.py` — `scan_all` + `close_scan` on stub + both coroutine lists + `ScanPage` validity (AC-1) — Story 1.1.
  - [ ] `adapters/test_elastic_scan_all.py` (new) — AC-2, AC-2b, AC-3, AC-3b, AC-8, AC-10, AC-11 + `close_scan` (AC-9 adapter half) — Story 2.1.
  - [ ] `adapters/test_solr_scan_all.py` (new) — AC-4 + uniqueKey + param validation + no-op close — Story 2.2.
  - [ ] `services/test_ubi_reader.py` — AC-5, AC-6, AC-9 (reader half), AC-12, AC-13, AC-14 — Stories 3.1, 3.2.
  - [ ] `services/test_ubi_reader_no_writes.py` — AC-7 (paginated read-only invariant incl. PIT endpoints + both search shapes) — Story 3.1.
- DoD:
  - [ ] Every AC (AC-1..AC-14) has at least one unit test; coverage ≥ 80%.

### 3.2 Integration tests
- The existing UBI integration test (`backend/tests/integration/test_generate_judgments_from_ubi.py`) MUST still pass with the paginated reader (DB-backed, adapter mocked at the HTTP boundary). No new hermetic integration test required — the adapter HTTP shapes are covered by the `MockTransport` unit tests and the reader logic by the reader unit tests.
- **Real-engine validation (non-blocking-for-merge, per spec §16):** extend the rung-3 E2E lane with a >10k-event paginated scan on real ES + Solr (the lane that originally surfaced the 10k-cap bug). OpenSearch real-engine coverage is desirable but gated on a fixture — tracked, not blocking. This is NOT a `pr.yml` gate (hermetic CI; no managed-cloud lane per CLAUDE.md "Common Pitfalls").

### 3.3 Contract tests
- N/A — no endpoint added or changed. (`make test-contract` is still run as a regression gate since the reader is on the judgment-generation path, but no new contract assertions are added.)

### 3.4 E2E tests
- N/A — no UI.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/unit/adapters/test_protocol.py` | `_StubAdapter` + 2 coroutine method-name lists | 1 stub + 2 lists | Add `scan_all` + `close_scan` (Story 1.1). Required: the shape test fails if the stub omits a Protocol method. |
| `backend/tests/unit/services/test_ubi_reader.py` | Existing tests stub `adapter.search_batch` single-call | n | Migrate to `scan_all` multi-page stubs (Story 3.1). Required: the reader no longer calls `search_batch` on the primary path. |
| `backend/tests/unit/services/test_ubi_reader_no_writes.py` | httpx-transport no-writes mock | 1 | Extend to the paginated path + PIT allowlist (Story 3.1). |
| `backend/tests/integration/test_generate_judgments_from_ubi.py` | DB-backed UBI generation | 1 | Must still pass; adapter mocked at HTTP boundary returns paginated pages. |

### 3.6 Migration verification
- N/A — no schema change. Alembic head unchanged.

### 3.7 CI gates
- [ ] `make test-unit`
- [ ] `make test-contract` (regression)
- [ ] `make lint`
- [ ] `make typecheck`
- [ ] coverage ≥ 80%
- (real-engine rung-3: post-merge validation, not a merge gate)

---

## 4) Documentation update workstream (required)

### 4.0 Core context files
- **`state.md`** — at finalization, prepend the merge one-liner to "Last 5 merges" (drop the 6th) and add the full entry to `state_history.md`. Alembic head unchanged.
- **`architecture.md`** — add a one-line note that `SearchAdapter` now offers a cursor-scan (`scan_all`/`close_scan`) abstracting ES/OpenSearch `search_after`+PIT vs Solr `cursorMark`, used by `UbiReader` for full-traffic aggregation. (No new service/layer.)
- **`CLAUDE.md`** — no change (no new convention beyond the adapter method; the new `Settings.ubi_*` fields are non-secret config and follow the existing pattern; no maturity-boundary crossing).

### 4.1–4.5 Topical docs (`docs/01`–`05`)
- **`docs/01_architecture/adapters.md`** — add `scan_all`/`close_scan` to the SearchAdapter method table + a short note on the two-idiom pagination (ES/OpenSearch `search_after`+PIT incl. ES-vs-OpenSearch PIT endpoints; Solr `cursorMark`) and the no-PIT/sampled fallback.
- **`docs/03_runbooks/judgment-generation-debugging.md`** — full-traffic scans + operator ceilings (`ubi_max_events_scan`/`ubi_max_queries_scan`/`ubi_query_id_batch_size`/`ubi_no_pit_tiebreaker_field`); reading `ubi_reader_scan_truncated`; PIT-fallback WARN meaning; the Solr / ES-no-PIT best-effort-under-live-writes caveat (run over a finalized window for exactness).
- **`docs/04_security/llm-data-flow.md`** — one-line confirmation: pagination does not change what leaves the cluster (same data, more pages).
- `docs/02_product`, `docs/05_quality` — none.

**Documentation DoD**
- [ ] `adapters.md` + `judgment-generation-debugging.md` updated; `architecture.md` one-liner added; `llm-data-flow.md` confirmed.
- [ ] `state.md` merge one-liner + `state_history.md` entry at finalization.

---

## 5) Lean refactor workstream (required)

### 5.1 Refactor goals
- Replace the single-`search_batch`, 10k-clamped scan in `_scan_ubi_events`/`_scan_ubi_queries` with a generic `scan_all` loop, reusing the shipped `list_documents` cursor precedent rather than inventing a new abstraction.

### 5.2 Planned refactor tasks
- [ ] Extract the per-engine filter-body builders the reader already has (`_build_solr_ubi_body` + the ES DSL block) into clearly-named helpers if the `scan_all` loop makes the existing inline blocks awkward — but only if it reduces duplication; do NOT expand scope into an adapter-side UBI query builder (that's the D-4 deferred option, explicitly out of scope).
- [ ] No dead-code branches introduced; the `search_batch` import stays (used by the sampled no-PIT fallback per D-8).

### 5.3 Refactor guardrails
- [ ] Behavioral parity proven by the reader tests (full aggregation == sum over pages; ceiling exact).
- [ ] Rule #4 preserved — no pagination `engine_type` branch in the reader (only the pre-existing filter-body branch, D-4).
- [ ] Lint/typecheck green; no new dependency.
- [ ] No product-scope expansion; no UI; no migration.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_ubi_judgments` (`UbiReader`) | Epic 3 | shipped | N/A |
| `infra_adapter_solr` (`SolrAdapter`, `_resolve_unique_key`, `list_documents` cursor precedent) | Epic 2 | shipped | N/A |
| `feat_index_document_browser` (`list_documents`, `DocumentPage.next_cursor_token`, `AdapterDocumentHit.sort`) | Epics 1-2 | shipped | N/A |
| ES/OpenSearch PIT API | Story 2.1 | external engine capability | D-7/D-8 fallback (narrow → no-PIT tiebreaker or sampled 10k) |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| PIT leak on early exit / error | M | M (pins shard resources) | `close_scan` in `finally` (FR-4); AC-8 + AC-9 tests. |
| Stale PIT id used after rotation | M | M (engine error / leak) | Latest-id propagation in cursor + close (FR-2/AC-2b). |
| Ceiling overshoot when not page-aligned | M | L (more work than asked) | Exact enforcement `page_size=min(...)` + slice (FR-4/AC-13). |
| Oversized `query_id` filter on dense windows | M | M (breaks the full-traffic path) | Chunking (FR-7/AC-14); conservative `ubi_query_id_batch_size` default. |
| Unsafe `_id` sort (ES 9 400) | M | M (no-PIT path 400s) | Never sort on `_id`; configured tiebreaker or sampled fallback (D-8/AC-3b). |
| Mocks don't catch real cursor/PIT semantics | M | M | rung-3 real-engine paginated scenario (ES + Solr), post-merge validation. |

### Failure mode catalog

| Failure mode | Trigger | Expected behavior | Recovery |
|---|---|---|---|
| PIT unsupported | engine returns 405/501/400-unsupported on PIT open | no-PIT fallback (tiebreaker or sampled) + WARN | Auto |
| PIT denied / index missing | 401/403/404 on PIT open | propagate via normal error envelope (no fallback) | Caller records failed generation |
| Mid-scan engine error | 5xx / connection on page N | `close_scan` in `finally` closes latest PIT; `ClusterUnreachableError` propagates | Caller records failed generation |
| Ceiling reached | scanned == `max_events`/`max_queries` | stop + `ubi_reader_scan_truncated` WARN (exact count); aggregate what's collected; `close_scan` non-terminal cursor | Auto |
| Empty window | first page 0 hits, `cursor=None` | return `{}` (existing `ubi_reader_empty_features`) | Auto |

## 7) Sequencing and parallelization

### Suggested sequence
1. Story 1.1 (Protocol surface) — unblocks everything.
2. Stories 2.1 + 2.2 (adapters) — depend on 1.1; independent of each other.
3. Stories 3.1 + 3.2 (reader + settings) — depend on 1.1 (Protocol) and at least one adapter; 3.2 is a small settings layer 3.1 consumes.

### Parallelization opportunities
- Stories 2.1 (`elastic.py`) and 2.2 (`solr.py`) touch disjoint files and can be done in parallel after 1.1.
- 3.1 and 3.2 both touch `ubi_reader.py`; do 3.2 (settings) first or fold into 3.1 to avoid a same-file conflict. Bundle all stories into one PR (one branch per session per CLAUDE.md).

## 8) Rollout and cutover plan

- Rollout stages: single PR, full. The `Settings.ubi_*` defaults let operators tune scan volume / batch size / tiebreaker without code change.
- Release gate (merge): `make test-unit` + `make test-contract` + `make lint` + `make typecheck` green; coverage ≥ 80%; `pr.yml` CI green.
- Post-merge validation: rung-3 real-engine paginated scenario (ES + Solr) green before the feature is considered fully validated.

## 9) Execution tracker

### Current sprint
- [x] Story 1.1 — `scan_all`/`close_scan`/`ScanPage` Protocol + shape test (commit `95432e5`)
- [x] Story 2.1 — `ElasticAdapter.scan_all`/`close_scan` (ES + OpenSearch) (commit `6b331c1`)
- [x] Story 2.2 — `SolrAdapter.scan_all`/`close_scan` (`cursorMark`) (commit `3ab7bc4`)
- [x] Story 3.2 — centralized `Settings` ceiling (folded into commit `6b331c1`; all 5 fields added alongside `ubi_no_pit_tiebreaker_field` consumer) + worker/dispatcher inject (commit `f6305bf`)
- [x] Story 3.1 — `UbiReader` paginated aggregation + exact ceiling + chunking + read-only invariant (commit `f6305bf`)

### Blocked items
- None.

### Done this sprint
- Story 1.1 (`95432e5`) — Protocol surface: `ScanPage`, `scan_all`, `close_scan`.
- Story 2.1 (`6b331c1`) — `ElasticAdapter.scan_all`/`close_scan` (PIT + search_after, narrow no-PIT fallback, best-effort cleanup, AC-2/2b/3/3b/8/10/11 covered) + 5 Settings ceiling fields (Story 3.2 folded forward).
- Story 2.2 (`3ab7bc4`) — `SolrAdapter.scan_all`/`close_scan` (POST /select form-body, cursorMark, AC-4 + AC-14 Solr half + P4-A2 covered). Resolves the Story-1.1 transient Protocol-shape failures on `SolrAdapter`.
- Story 3.1+3.2 (`f6305bf`) — `UbiReader` rewrite: page-by-page `scan_all` loop, exact ceiling via `page_size=min(ES_MAX_RESULT_WINDOW, remaining)` + final-page slice, query_id chunking by count AND byte length, best-effort `close_scan` in `finally`, P1-B2 cursor-before-fold ordering. Ceiling kwargs injected by worker + dispatcher from Settings. Tests: 33 reader unit + 5 no-writes (PIT allowlist), all green; backend unit suite 2465 passed.

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete:

- [ ] Modified files match story scope (adapter/Protocol/reader + their tests).
- [ ] No endpoint/schema/migration (N/A for this plan — confirm none introduced).
- [ ] Rule #4 preserved: no pagination `engine_type` branch outside the adapters.
- [ ] Read-only invariant holds (no write-shaped request escapes `scan_all`).
- [ ] Required ACs for the story have passing tests.
- [ ] Commands executed and passed:
    - [ ] `make test-unit`
    - [ ] `make lint`
    - [ ] `make typecheck`
    - [ ] `make test-contract` (Epic 3)
- [ ] `state.md` / `state_history.md` updated at finalization.

## 11) Plan consistency review (performed)

1. **Spec ↔ plan endpoint count:** Spec §8.1 = N/A (0 endpoints). Plan = 0 endpoints. Match. ✓
2. **Spec ↔ plan FR coverage:** FR-1→1.1; FR-2→2.1; FR-3→2.2; FR-4→3.1; FR-5→3.1/3.2; FR-6→2.1/2.2/3.1; FR-7→3.1. All 7 FRs assigned. ✓
3. **Spec ↔ plan AC coverage:** AC-1→1.1; AC-2/2b/3/3b/8/10/11→2.1; AC-4→2.2; AC-5/6/9/13/14→3.1; AC-7→3.1; AC-12→3.2. All 16 ACs (AC-1..AC-14 incl. AC-2b, AC-3b) assigned. ✓
4. **Story internal consistency:** No endpoint tables/schemas (N/A). File ownership: 1.1 owns `protocol.py`+`test_protocol.py`; 2.1 owns `elastic.py`+`test_elastic_scan_all.py`; 2.2 owns `solr.py`+`test_solr_scan_all.py`; 3.1+3.2 share `ubi_reader.py` (sequenced/folded to avoid conflict) + `test_ubi_reader.py`; 3.2 also owns `settings.py`. No file silently owned by two unrelated stories. ✓
5. **Test file count:** 2 new (`test_elastic_scan_all.py`, `test_solr_scan_all.py`) + 3 extended (`test_protocol.py`, `test_ubi_reader.py`, `test_ubi_reader_no_writes.py`) + 1 must-still-pass integration. Matches §3.1/§3.5. ✓
6. **Gate arithmetic:** 3 epic gates → 5 stories; each epic gate's claims map to its stories' DoD. ✓
7. **Open questions resolved:** Spec §19 has no blocking open questions; the `ScanPage`/cursor-encoding default (opaque, round-tripped) is locked in Story 1.1. ✓
8. **Plan ↔ codebase verification:**
   - `backend/app/adapters/protocol.py:171-304` — `SearchAdapter` Protocol + `ScoredHit`/`DocumentPage` present (read 2026-06-02). ✓
   - `backend/app/adapters/elastic.py:767-859` (`list_documents`, `search_after`, `_doc` sort, no PIT) + `:556-659` (`search_batch`) + `:129` (`_request`) confirmed. ✓
   - `backend/app/adapters/solr.py:1577-1690` (`list_documents`, `cursorMark`, terminal detection) + `:876` (`_resolve_unique_key`) + `:173` (`_validate_solr_param_values`) confirmed. ✓
   - `backend/app/services/ubi_reader.py:389-523` (`_scan_ubi_queries`/`_scan_ubi_events`, single `search_batch`, `ES_MAX_RESULT_WINDOW`/`DEFAULT_MAX_*` caps) + `:124-176` (`_build_solr_ubi_body`) confirmed. ✓
   - `UbiReader` construction sites: `judgments_ubi.py:375`, `agent_judgments_dispatch.py:501`, `ubi_readiness.py:182` confirmed. ✓
   - `test_protocol.py` `_StubAdapter` + coroutine lists (`:124-134`, `:354-365`) confirmed. ✓
9. **Infrastructure path verification:** No migration (Alembic head unchanged). Test dirs `backend/tests/unit/adapters/` + `services/` confirmed. No router registration. ✓
10. **Frontend data plumbing:** N/A — no frontend.
11. **Persistence scope:** N/A — read path; no new storage.
12. **Enumerated value contract audit:** N/A — no filters/badges/dropdowns; `EngineType` Literal unchanged.
13. **Admin control / ceiling:** N/A — pre-MVP4, no admin model. (Scan ceiling is operator config, not an admin surface.)
14. **Audit-event coverage:** N/A — read path, no state mutation; `audit_log` not yet shipped (MVP3).

No unresolved findings.

---

## 12) Definition of plan done

- [x] Every FR (FR-1..FR-7) mapped to stories/tasks/tests.
- [x] Every AC (AC-1..AC-14 incl. AC-2b, AC-3b) mapped to a story + test.
- [x] Each story includes Modified files, Tasks, DoD (Endpoints/Schemas N/A and marked so).
- [x] Test layers scoped (unit primary; integration must-still-pass + post-merge rung-3; contract regression; e2e N/A).
- [x] Documentation updates planned (`adapters.md`, runbook, `architecture.md` one-liner, `llm-data-flow.md` confirm; `state.md`/`state_history.md` at finalization).
- [x] Lean refactor scope + guardrails explicit (no D-4 scope creep).
- [x] Epic gates measurable.
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review (§11) performed, no unresolved findings.

## 13) Cross-model review log

**Cross-model review: GPT-5.5 (`gpt-5.5`).**

- **Cycle 1 (2026-06-02):** 5 findings (1 High, 4 Medium). All ACCEPTED:
  - **P1-B1 (High) — count-based chunking (1024 ids) still overflows a Solr GET URL:** 1024 UUID ids ≈ 38 KB > typical 8 KB URL limit. Fixed: Solr `scan_all` uses **POST `/select`** (form body), and chunking is additionally bounded by **encoded byte-length**, not just id count (Conventions + Story 2.2 + Story 3.1 task 2 + AC-14 asserts request size, not just count).
  - **P1-A1 (Medium) — PIT sort + `search_after` continuation under-specified; `ScoredHit` has no `sort`:** clarified the adapter injects `[{timestamp:asc},{_shard_doc:asc}]`, reads the last hit's raw `sort` into the opaque cursor (the reader never needs `sort`); tests assert exact `sort`/`search_after` across pages (Conventions + Story 2.1).
  - **P1-A2 (Medium) — PIT close request bodies not specified:** added exact wire shapes — ES `DELETE /_pit` body `{"id":...}`; OpenSearch `DELETE /_search/point_in_time` body `{"pit_id":[...]}` — and required tests assert the body, not just the path (Conventions + Story 2.1 + AC-10).
  - **P1-A3 (Medium) — Solr exactness precondition only in the runbook:** elevated to the Story 2.2 functional contract (snapshot-exact only over a finalized window; best-effort under live writes).
  - **P1-B2 (Medium) — reader assigns `cursor` after folding → fold-time exception leaks the rotated PIT:** fixed the loop to assign `cursor = page.cursor` immediately after the await, before folding; added a fold-time-exception test (Story 3.1 sketch + task 1/5).
  - Findings rejected: none.
- **Cycle 2 (2026-06-02):** 3 new Medium findings (consistency/specificity gaps from the cycle-1 patches). All ACCEPTED:
  - **P2-A1 — Story 2.2 Endpoints line still said GET /select:** fixed to POST /select (the Modified-files + tasks already said POST).
  - **P2-A2 — PIT response field differs by engine (ES open → `id`, OpenSearch → `pit_id`):** specified exact per-engine parsing in Conventions + Story 2.1 task 3; tests assert the exact response field names.
  - **P2-B1 — byte-length chunking had no defined threshold:** added `Settings.ubi_query_id_batch_max_bytes` (hard ceiling); a batch splits whenever EITHER ceiling is hit; AC-14 constructs over-byte ids below the count ceiling and asserts the split.
  - Findings rejected: none.
- **Cycle 3 (2026-06-02):** 2 new Medium findings (the two attempts each surfaced one). Both ACCEPTED:
  - **P3-A1 — caller `body` could override scan-critical keys via the `{...body}` merge:** made pagination keys (`pit`/`sort`/`size`/`search_after`) adapter-owned (body merged first, then overwritten) + strip caller `from`/`search_after`/`size`/`sort`; added a precedence test.
  - **P3-A2 — `finally` `close_scan` could mask the primary exception:** made cleanup best-effort (catch+log close failures, re-raise the primary) in both the adapter `finally` and the reader `finally`; added page-error-plus-close-error tests.
  - Findings rejected: none.
- **Cycle 4 (2026-06-02):** 3 new Medium findings (the two attempts surfaced P4-A2 in common + one each of P4-A1/P4-A3). All ACCEPTED:
  - **P4-A1 — Story 2.1 Endpoints row showed indexed `DELETE /<index>/_pit`:** fixed the row to split open (indexed) vs close (unindexed `DELETE /_pit` / `DELETE /_search/point_in_time`); no-writes allowlist permits only the unindexed close paths.
  - **P4-A2 — Solr `start` not stripped (invalid with `cursorMark`):** strip caller `start`/`rows`/`cursorMark`/`sort` from the inherited Solr body before setting adapter-owned values; added a stray-paging-key strip test.
  - **P4-A3 — terminal-close failure could mask a successful final page:** made the normal terminal PIT close best-effort too (log on failure, still return `ScanPage(cursor=None)`); added a terminal-close-error test.
  - Findings rejected: none.
- **Cycle 5 (2026-06-02):** 1 new Medium finding (two of three attempts surfaced the identical issue — convergent). ACCEPTED:
  - **P5-A1 — `pit` not in the ES strip list:** a stray caller `pit` in the inherited body could leak into the no-PIT fallback `POST /<target>/_search`. Added `pit` to the ES strip list (stripped before BOTH PIT and no-PIT construction) + a test asserting the no-PIT fallback emits no `pit`.
  - Findings rejected: none.
- **Cycle 6 (2026-06-02):** re-review with the cumulative resolution log — returned **0 High/Medium findings** (clean across attempts). Converged after 5 substantive cycles (14 findings total: 1 High, 13 Medium; all ACCEPTED, none rejected/deferred). Plan finalized.
