# Index document browser — peek at the corpus a study scores against

**Date:** 2026-05-27
**Status:** Idea — surfaced during a live demo walkthrough of `tune-acme-products-rich-boosts`
**Priority:** P2
**Origin:** Operator on the study detail page asked "how can I find the data set?". The LinkedEntitiesRow surfaces cluster / query set / judgment list / template links, but there's no UI path to the *documents* the study scored against — operators have to drop to `curl http://localhost:9200/<index>/_search`.
**Depends on:** No other planned feature, but **NOT** "no codebase changes" — the [`SearchAdapter` Protocol](../../../../backend/app/adapters/protocol.py) exposes only `health_check / list_targets / get_schema / list_query_parsers / render / search_batch / explain` today. Cap 1 (paginated list) can route through existing `search_batch` with a `match_all` query + `search_after` cursor over a stable `_id` sort, but Cap 2 (fetch single doc by `_id`) requires extending the Protocol with a new `get_document(target, doc_id)` method (Absolute Rule #4 — engine-specific HTTP cannot live outside `backend/app/adapters/`). See D-1 below.

## Problem

A study scores trials by issuing queries against a specific index (the `target` field on `studies`) and ranking the returned documents against the judgment list. Operators reviewing a study's Confidence panel routinely want to answer questions like:

- "Why did `apple watch series 3` improve +0.222 — what docs are returning for that query?"
- "Is the 'face mask' regression because the corpus is missing the obvious match, or because the boost values pushed something else to the top?"
- "What does a sample doc in this index actually look like — what fields are indexed?"
- "How big is this corpus? Is the metric ceiling because of judgment sparsity, or because the corpus itself is tiny?"

Today the only answers come from raw `curl`s against the Elasticsearch / OpenSearch HTTP port. That's fine for engineers comfortable with the engine's query API, but it forces them out of the RelyLoop UI and breaks the demo narrative — especially with non-engineer stakeholders in the room. A simple read-only document browser closes the loop.

## Information architecture

The IA is the load-bearing UX choice. Without two independent entry points, the documents browser is a hidden surface reachable only via the `LinkedEntitiesRow` cross-link from a study — operators who aren't already looking at a study can't find it.

**Route hierarchy (V1 — three new pages, two modified):**

| Route | Status | Purpose |
|---|---|---|
| `/clusters/[id]` | **MODIFIED** — adds an "Indices" card between [`ClusterActionBar`](../../../../ui/src/components/clusters/cluster-action-bar.tsx) and [`StudiesByClusterTable`](../../../../ui/src/components/clusters/studies-by-cluster-table.tsx) | Top-down entry point (Cap A) |
| `/clusters/[id]/indices/[name]` | NEW | Index summary: header + `doc_count` + Schema table + nav cards (Cap B) |
| `/clusters/[id]/indices/[name]/documents` | NEW | Paginated `_id` list with `_source` preview (Cap 1) |
| `/clusters/[id]/indices/[name]/documents/[doc_id]` | NEW | Single-doc `_source` JSON view (Cap 2) |
| `/studies/[id]` | **MODIFIED** — `LinkedEntitiesRow` gains a 5th entry | Bottom-up entry point (Cap 3) |

**Why this shape:**

- **Two independent entry points.** Cluster detail (top-down: "I'm exploring this cluster, what's in it?") AND study detail (bottom-up: "I want to see what this study scored against"). One alone leaves operators stranded.
- **Index summary is a real page, not a redirect to `.../documents`.** The summary absorbs schema / field-type display (D-7), so the per-doc detail view stays focused on `_source` JSON instead of cluttering it with per-field type chips. The summary is also where future affordances naturally live ("studies targeting this index", "judgment lists referencing this index", and at MVP1.5+ "UBI signal volume" panels).
- **URL term `indices` vs wire term `target`.** Backend/adapter use `target` (`TargetInfo`, `studies.target`, `/clusters/{id}/targets`). UI users speak in "indices" for ES/OpenSearch. Frontend routes stay user-facing (`/indices/`); backend paths mirror the existing pattern (`/clusters/{id}/targets/{target}/documents`). Engine-aware relabeling (Fusion → "Collections") arrives if/when MVP3 calls for it — locked as D-6.
- **Forward-compatible with MVP1.5 UBI** (D-9). When [`feat_ubi_judgments`](../feat_ubi_judgments/idea.md) ships, `ubi_queries` and `ubi_events` join the Indices card. The card grows a `role` chip then — V1 ships without it (clean separation; one feature at a time).

## Proposed capabilities

### Cap A. Indices card on cluster detail (new entry point)

- Surface: a new "Indices" card on [`/clusters/[id]`](../../../../ui/src/app/clusters/[id]/page.tsx), inserted between [`ClusterActionBar`](../../../../ui/src/components/clusters/cluster-action-bar.tsx) and [`StudiesByClusterTable`](../../../../ui/src/components/clusters/studies-by-cluster-table.tsx).
- Data source: existing [`GET /api/v1/clusters/{cluster_id}/targets`](../../../../backend/app/api/v1/clusters.py) endpoint — no new endpoint, no new adapter method. Returns `TargetInfo(name, doc_count)`.
- Behavior: small table with columns `Name`, `Documents` (formatted with thousands separator), row click navigates to `/clusters/[id]/indices/[name]`. Sort by name ascending. No cursor (target lists are bounded — usually < 100 indices on operator clusters; bound check via the existing `target_filter` glob already applied server-side).
- Empty state: "No indices on this cluster" + link to the cluster registration runbook.
- Forbidden state (403 `TARGETS_FORBIDDEN`): "Cluster credentials don't allow listing indices" + a one-line "Register a key with `monitor` privilege" hint (mirrors the existing handling in [`create-study-modal`](../../../../ui/src/components/studies/create-study-modal.tsx) for the same error code).

### Cap B. Index summary page (new)

- Surface: new route `/clusters/[id]/indices/[name]`.
- Composition (no new backend endpoint — two existing endpoints compose into one page):
  - Page header: `name` + `doc_count` (from the cluster's `/targets` response, filtered client-side to the one row) + engine type chip (from `/clusters/[id]`).
  - Two prominent nav cards: **"Browse documents →"** (links to `.../documents`) and **"View studies targeting this index →"** (links to `/studies?target=<name>` — see Open Q below on whether that filter exists).
  - Schema table populated from existing [`GET /api/v1/clusters/{cluster_id}/schema?target=<name>`](../../../../backend/app/api/v1/clusters.py), returning `FieldSpec(name, type, analyzer, doc_count)` rows. Columns: `Field`, `Type`, `Analyzer`. Default sort by field name; the `doc_count` per-field (when present from the engine) hidden by default behind a column-visibility toggle.
- Why a real page (not a redirect to `.../documents`):
  - The schema introspection has no other home in the UI today — `GET /schema` is consumed only by the create-study modal's template validation. Surfacing it here is a quiet quality lift independent of the documents browser.
  - Operators evaluating relevance want a one-glance "is this index the shape I expected?" view before drilling into individual docs. Skipping the summary forces them to either guess from the doc-detail page or open the studies tab to inspect the template's declared params.
  - It's the natural landing zone for future affordances (UBI signal-volume mini-stats at MVP1.5; judgment-list coverage histograms at MVP2+) without revisiting the IA.

### Cap 1. List documents in an index

- Surface: a new route, candidate `/clusters/[id]/indices/[index]/documents` (read-only).
- Behavior: paginated list of `_id` + a configurable preview of `_source` fields. Page size 25 default, 100 max.
- Sort: V1 ships with `_id` ascending only (always works on every ES/OpenSearch index without keyword-field discovery). "Sort by any indexed `keyword` field" is a deferred follow-on (D-3) — it needs schema introspection + filtering FieldSpec entries to `type=='keyword'`.
- Corpus size for context (the "is the metric ceiling because of judgment sparsity, or because the corpus itself is tiny?" question): already exposed today via [`TargetInfo.doc_count`](../../../../backend/app/adapters/protocol.py) returned from `list_targets()` — surface it on the list page header without adding a new endpoint.
- Empty state: clear message + link back to the cluster page when the index is empty or doesn't exist.

### Cap 2. Inspect a single document

- Surface: drill-down `/clusters/[id]/indices/[index]/documents/[doc_id]`.
- Behavior: full `_source` rendered as pretty-printed JSON. Implementation note: `JSON.stringify(source, null, 2)` is sufficient — [`prettyPrintJinjaJson`](../../../../ui/src/lib/jinja-json-format.ts) is overkill for non-Jinja JSON (its sentinelling step is a no-op on pure JSON, and the function returns a discriminated `PrettyPrintResult` whose error path doesn't apply here).
- Mapping types live on Cap B's index summary page (D-7), **not** inline on this view. Keeps the JSON view focused; operators who need field types open the summary in a new tab via the breadcrumb. A small breadcrumb above the JSON renders the path `<cluster name> › <index name> › <doc_id>` with the index segment linking back to Cap B.

### Cap 3. Cross-link from study detail

- [`LinkedEntitiesRow`](../../../../ui/src/components/studies/linked-entities-row.tsx) on `/studies/[id]` extends from 4 entries (Cluster / Query set / Judgment list / Template) to 5 by appending an `Index` entry whose `name` is [`studies.target`](../../../../backend/app/db/models/study.py) and whose `href` is the new documents-list route. No new fetch — the field is already on `StudyDetail`.
- Bonus deferred (D-4): a "Run this study's template against the corpus" button on the documents list. The substrate already exists — [`POST /api/v1/clusters/{cluster_id}/run_query`](../../../../backend/app/api/v1/clusters.py) accepts arbitrary `query_dsl` + `top_k` + `timeout_s` and there is no UI consumer of it today. Worth its own small feature folder when it ships.

### Cap 4. (Stretch — deferred per D-4) Free-text search

- A search input that runs a simple `multi_match` against `_source` text fields. Not a study-grade query — just "let me find docs with 'apple watch' in the title" for demo and debug context. Same substrate as Cap 3's "Run template" bonus button (`run_query`), so the two are best bundled in a single follow-on.

## Scope signals

- **Backend:** two new read-only endpoints (mirror the existing nested-route pattern under `/clusters/{cluster_id}/...` — `/schema`, `/targets`, `/run_query` already live there; the documents endpoints nest under `/targets/{target}/`):
  - `GET /api/v1/clusters/{cluster_id}/targets/{target}/documents?cursor=&limit=` — list. Routes through `SearchAdapter.search_batch` with a `match_all` body + `sort: [{_id: 'asc'}]` + `search_after` derived from the opaque cursor (no new adapter method; thin call-site wrapper in the cluster service).
  - `GET /api/v1/clusters/{cluster_id}/targets/{target}/documents/{doc_id}` — detail. Routes through a NEW `SearchAdapter.get_document(target, doc_id, *, request_id) -> Document | None` method (D-1). ElasticAdapter implementation calls `GET /<index>/_doc/<doc_id>`; missing doc returns `None` → router translates to 404 `DOCUMENT_NOT_FOUND`.
  - Both endpoints inherit the existing error envelope (cluster missing → 404 `CLUSTER_NOT_FOUND`; index missing → 404 `TARGET_NOT_FOUND`; ACL denial → 403; cluster down → 503 `CLUSTER_UNREACHABLE`). Pagination follows [`api-conventions.md`](../../../01_architecture/api-conventions.md): opaque `?cursor=`, `?limit=` (default 25, max 100), `X-Total-Count` header from the engine's `hits.total.value`.
  - No new endpoints are needed for Cap A (Indices card) or Cap B (Index summary): they compose existing `/clusters/{id}/targets` + `/clusters/{id}/schema?target=` responses.
  - No new state, no mutations, no audit events (read-only — audit_log activates at MVP2 for mutations only per `data-model.md`).
- **Adapter Protocol:** ONE new method (`get_document`) added to [`SearchAdapter`](../../../../backend/app/adapters/protocol.py). [`ElasticAdapter`](../../../../backend/app/adapters/elastic.py) implements it; a stub on the future `LucidworksFusionAdapter` raises `NotImplementedError` until MVP3 (consistent with the existing "Fusion arrives at MVP3" precedent).
- **Frontend:** five surfaces touched:
  - MODIFIED [`ui/src/app/clusters/[id]/page.tsx`](../../../../ui/src/app/clusters/[id]/page.tsx) — adds the "Indices" card (Cap A) using the existing `DetailPageShell` + `Card` primitives.
  - NEW `ui/src/app/clusters/[id]/indices/[name]/page.tsx` — index summary (Cap B).
  - NEW `ui/src/app/clusters/[id]/indices/[name]/documents/page.tsx` — documents list (Cap 1), using the existing [`<DataTable>`](../../../../ui/src/components/common/data-table.tsx) primitive (cursor-aware out of the box per Story 2.5/2.7).
  - NEW `ui/src/app/clusters/[id]/indices/[name]/documents/[doc_id]/page.tsx` — single-doc detail (Cap 2).
  - MODIFIED [`ui/src/components/studies/linked-entities-row.tsx`](../../../../ui/src/components/studies/linked-entities-row.tsx) — adds a 5th entry (Cap 3).
  - One column-config file at `ui/src/components/clusters/documents-data-table.column-config.tsx` for Cap 1 — no `enum` or `fk-select` filter columns in V1, so no `sourceOfTruth` discipline triggers (a one-line "no enum filters" comment documents the intentional absence).
- **Migration:** none. No new tables.
- **Config:** none. The adapter Protocol + cluster credentials already cover it.
- **Audit events:** N/A — read-only surface.
- **Security:** the adapter respects per-cluster credentials. No additional auth surface needed in MVP1 (single-tenant). At MVP4 this surface inherits the same tenant scoping as `/clusters`.

## Why P2 (not P1)

- It's a *demo polish + operator convenience* feature, not a Karpathy-loop primitive. Operators have working access today via curl; the UX cost is felt during demos and onboarding, not during routine study work.
- The deeper version of this question — "why did query X improve / regress in this study?" — is partially answered by the Confidence panel's per-query outcomes tables (PR #282) and the trials table's per-trial params. The documents list adds another dimension but isn't the only signal.
- The engine adapter already has the read primitives; nothing else in the Karpathy loop is blocked on shipping this. It can land any time the team has bandwidth.

## Risks / unknowns

- **Doc-size unboundedness.** A 1000-doc corpus is trivial; a 10M-doc corpus is not. Cursor pagination via `search_after` over `_id` ascending has no upper bound (unlike `from/size` which caps at 10k); a hard server-side `limit ≤ 100` and a per-doc `_source` size cap (e.g. truncate any single field over 8 KiB on the list view) keep the response bounded.
- **Engine-specific quirks.** ES and OpenSearch share the same wire-level `_source` shape, but Fusion (MVP3) layers Solr semantics underneath. The Protocol does NOT currently have `fetch by id` or `scroll` primitives — see D-1 for the locked adapter extension; the Fusion stub raises `NotImplementedError` until MVP3 picks it up.
- **Cluster credentials.** Operator clusters with read-only API keys should work; clusters with no creds (anonymous local dev) should also work. Both already covered by the adapter; the new endpoints just thread the request through.
- **Cursor stability under concurrent writes.** `search_after` over `_id` is stable for append-only corpora; for operators with live indexing churn during the browse session, the same `_id` may appear on consecutive pages (rare). Acceptable for a read-only browse surface — flag in the UI as "consistency is point-in-time at page load."

## Decisions to lock for /spec-gen

- **D-1 — Adapter Protocol extension (locked).** Add `get_document(target: str, doc_id: str, *, request_id: str | None = None) -> Document | None` to `SearchAdapter`. ElasticAdapter implements via `GET /<index>/_doc/<doc_id>`. Fusion stub raises `NotImplementedError`. New Pydantic `Document(BaseModel)` mirrors `ScoredHit` minus `score` (`doc_id: str`, `source: dict[str, Any] | None`). Rationale: Absolute Rule #4 forbids engine-specific HTTP outside `backend/app/adapters/`; an ID-keyed lookup is too narrow to fake via `search_batch` + `ids` filter without leaking query-DSL construction into the router.
- **D-2 — Pagination strategy (locked).** Cursor-based via `search_after` over a stable `_id` ascending sort. Cursor is the opaque-base64 of the last hit's `sort` array (matches the `data_table_primitive` cursor-stack pattern at [`ui/src/components/common/data-table.tsx`](../../../../ui/src/components/common/data-table.tsx)). Default `limit=25`, max `limit=100`. Rejects `offset` / `from` per `api-conventions.md`.
- **D-3 — V1 sort surface (locked: minimal).** V1 ships `_id` ascending only. "Sort by any indexed `keyword` field" is a deferred follow-on; it needs `get_schema(target)` field-type filtering plus a sort-control UI (or list it as a separate sort-key picker pattern under `feat_data_table_primitive`).
- **D-4 — "Run template against corpus" + free-text search (deferred).** Cap 3's bonus button AND Cap 4 (free-text search) BOTH ride on the existing `POST /clusters/{id}/run_query` endpoint, which has zero UI consumers today. Capture as a follow-on sibling folder (`feat_cluster_query_playground` or similar) bundling: (a) a top-of-documents-list `multi_match` search box, (b) the "Run this study's template against the corpus" button on `/studies/[id]` that hydrates `run_query` with the study's `template_id` + `best_metric`-winning params. Not blocking for V1.
- **D-5 — `_source` field display (locked: full by default).** Detail view renders the full `_source` JSON. List view renders all `_source` fields by default with a `?fields=a,b,c` query-param narrowing knob (truncate any individual field value over 8 KiB to `<…truncated…>`). No persisted per-user field-selection state in V1.
- **D-6 — Cluster detail Indices card (locked: V1 includes it).** Without this, the documents browser is a hidden surface reachable only via the study-detail cross-link. The card is small (single existing `/targets` endpoint, no cursor). Frontend URL term is `indices` for user-facing clarity; backend wire term stays `target` to match `TargetInfo` / `studies.target` / the existing `/clusters/{id}/targets` endpoint. Engine-aware relabeling (Fusion → "Collections") is a future MVP3 concern. See Cap A.
- **D-7 — Index summary as a real page, not a redirect (locked).** `/clusters/[id]/indices/[name]` renders schema + counts + nav cards via existing endpoints (`/targets` filtered + `/schema?target=`). The Schema table absorbs the field-type/analyzer display that Cap 2 (per-doc detail) would otherwise have to host inline, which would clutter the JSON view. The summary is also the natural landing zone for future affordances (UBI signal-volume mini-stats; judgment-list coverage histograms) without revisiting the IA. See Cap B.
- **D-8 — Confidence panel → "View returned docs" affordance (deferred to D-4).** The natural improver/regressor → docs cross-link needs the trial's persisted query DSL + a query-playground surface — both deferred under D-4's future `feat_cluster_query_playground`. V1 ships without this cross-link; operators reach docs via Cap A (cluster context) or Cap 3 (study context). The deferred cross-link is the *highest-value* UX win the documents browser substrate enables — capture explicitly in the follow-on idea so it doesn't get lost.
- **D-9 — UBI index role classification (deferred to MVP1.5).** Once [`feat_ubi_judgments`](../feat_ubi_judgments/idea.md) ships, the Indices card needs to distinguish `tunable` indices from `ubi_signals` indices (`ubi_queries`, `ubi_events`) so operators don't accidentally try to tune the signal indices. Plan: extend `TargetInfo` with `role: Literal["tunable", "ubi_signals", "system"]` populated by an adapter-side classifier (small `frozenset` of UBI index name prefixes; CLAUDE.md enum discipline applies). V1 of this feature does NOT add the field — clean separation; MVP1.5 picks it up.

## Open questions for /spec-gen

- **`/studies?target=<name>` filter.** Cap B's "View studies targeting this index" nav card links to a filtered studies list. The studies list endpoint accepts cluster + status filters today; whether it accepts a `?target=` filter needs a quick grep — if absent, either (a) add it as a co-located ~5-LOC backend change, or (b) ship Cap B's nav card as a "feature pending" placeholder linking to `/studies?cluster_id=<id>` with a one-line note. Recommended default: **(a)** — the filter is a single SQL `WHERE target = ?` clause and Cap B is the only consumer that needs it.
- **Empty/forbidden state copy.** ACL-denied (403 `TARGETS_FORBIDDEN`) likely needs a different empty state than "index has zero docs" — operator's per-cluster API key may grant `list_targets` but not `_doc/_id` reads. Recommended default: surface both as the existing `EmptyState` component with a one-line distinction message (no design-shaped novelty here).
- **Test seed-data dependency.** E2E coverage needs at least one seeded index with ≥ 100 docs to exercise pagination. Recommended default: extend [`scripts/seed_meaningful_demos.py`](../../../../scripts/seed_meaningful_demos.py) (which already seeds `acme-products-rich`) to write 100 docs instead of the current count; or add a targeted `seed_browser_corpus()` helper. /spec-gen should pick.

## Relationship to other work

- **Extends** [`infra_adapter_elastic`](../../00_overview/implemented_features/2026_05_10_infra_adapter_elastic/) — adds ONE method (`get_document`) to the `SearchAdapter` Protocol (D-1) and threads listing through existing `search_batch`.
- **Complements** the Confidence panel improver/regressor tables ([PR #282](https://github.com/SoundMindsAI/relyloop/pull/282)) — those tell you *which* queries gained or lost; this would tell you *which docs* are returned for those queries.
- **Independent of** [`feat_studies_ui`](../../00_overview/implemented_features/2026_05_12_feat_studies_ui/) — the study detail page wouldn't change in any blocking way, just gains a cross-link via the existing [`LinkedEntitiesRow`](../../../../ui/src/components/studies/linked-entities-row.tsx) (extend from 4 entries to 5).
- **Coordinates with (not blocked by)** [`feat_ubi_judgments`](../feat_ubi_judgments/idea.md) (MVP1.5, P1) — that feature reads from `ubi_queries` and `ubi_events` indices in the same cluster. When UBI ships, the Indices card (Cap A) gains a `role` chip via D-9 so operators can tell signal indices from tunable indices at a glance. The documents browser itself (Cap 1/Cap 2) works unchanged on UBI indices and becomes a useful debugging surface ("which queries are users actually issuing?"). Out-of-scope for V1.
- **Substrate for a future sibling** `feat_cluster_query_playground` (D-4 — not yet captured as an idea folder) bundling Cap 3's "Run template against corpus" button + Cap 4's free-text search box. Both ride on the existing `POST /clusters/{id}/run_query` endpoint and would compose with this feature on the same detail page.
