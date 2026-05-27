# Index document browser — peek at the corpus a study scores against

**Date:** 2026-05-27
**Status:** Idea — surfaced during a live demo walkthrough of `tune-acme-products-rich-boosts`
**Priority:** P2
**Origin:** Operator on the study detail page asked "how can I find the data set?". The LinkedEntitiesRow surfaces cluster / query set / judgment list / template links, but there's no UI path to the *documents* the study scored against — operators have to drop to `curl http://localhost:9200/<index>/_search`.
**Depends on:** None. The engine adapter Protocol (`infra_adapter_elastic`) already has all the read primitives needed.

## Problem

A study scores trials by issuing queries against a specific index (the `target` field on `studies`) and ranking the returned documents against the judgment list. Operators reviewing a study's Confidence panel routinely want to answer questions like:

- "Why did `apple watch series 3` improve +0.222 — what docs are returning for that query?"
- "Is the 'face mask' regression because the corpus is missing the obvious match, or because the boost values pushed something else to the top?"
- "What does a sample doc in this index actually look like — what fields are indexed?"
- "How big is this corpus? Is the metric ceiling because of judgment sparsity, or because the corpus itself is tiny?"

Today the only answers come from raw `curl`s against the Elasticsearch / OpenSearch HTTP port. That's fine for engineers comfortable with the engine's query API, but it forces them out of the RelyLoop UI and breaks the demo narrative — especially with non-engineer stakeholders in the room. A simple read-only document browser closes the loop.

## Proposed capabilities

### Cap 1. List documents in an index

- Surface: a new route, candidate `/clusters/[id]/indices/[index]/documents` (read-only).
- Behavior: paginated list of `_id` + a configurable preview of `_source` fields. Page size 25 default, 100 max.
- Sort: by `_id` ascending by default; allow sort by any indexed field with a `keyword`-typed mapping.
- Empty state: clear message + link back to the cluster page when the index is empty or doesn't exist.

### Cap 2. Inspect a single document

- Surface: drill-down `/clusters/[id]/indices/[index]/documents/[doc_id]`.
- Behavior: full `_source` rendered as pretty-printed JSON (reuse the `prettyPrintJinjaJson` shipped in PR #282 — same idea, but feed it pure JSON without the Jinja-aware bits).
- Show the doc's mapping types alongside each field for context (e.g. `title (text)` / `price (float)` / `brand (keyword)`).

### Cap 3. Cross-link from study detail

- LinkedEntitiesRow on `/studies/[id]` gains a 5th item: `Index: acme-products-rich` linking to the documents list.
- Bonus when feasible: a "Run this study's template against the corpus" button on the documents list — renders the Jinja template with a free-text `query_text` input + the study's `best_metric`-winning param values, executes against the index, shows the top-K hits. This is "preview what a query looks like with the proposed config" — closes the loop from `Confidence → improver row → see the actual returned docs`.

### Cap 4. (Stretch) Free-text search

- A search input that runs a simple `match_all` / `multi_match` against `_source` keyword fields. Not a study-grade query — just "let me find docs with 'apple watch' in the title" for demo and debug context.

## Scope signals

- **Backend:** new read-only endpoints. Two candidates:
  - `GET /api/v1/clusters/{id}/indices/{index}/documents?cursor=&limit=&sort=`
  - `GET /api/v1/clusters/{id}/indices/{index}/documents/{doc_id}`
  - Both delegate to the engine adapter's existing read path. No new state, no mutations, no audit events (read-only).
- **Frontend:** new App Router routes, TanStack Query hooks, reuse `<DataTable>` primitive for the listing.
- **Migration:** none. No new tables.
- **Config:** none. The adapter Protocol + cluster credentials already cover it.
- **Audit events:** N/A — read-only surface.
- **Security:** the adapter respects per-cluster credentials. No additional auth surface needed in MVP1 (single-tenant). At MVP4 this surface inherits the same tenant scoping as `/clusters`.

## Why P2 (not P1)

- It's a *demo polish + operator convenience* feature, not a Karpathy-loop primitive. Operators have working access today via curl; the UX cost is felt during demos and onboarding, not during routine study work.
- The deeper version of this question — "why did query X improve / regress in this study?" — is partially answered by the Confidence panel's per-query outcomes tables (PR #282) and the trials table's per-trial params. The documents list adds another dimension but isn't the only signal.
- The engine adapter already has the read primitives; nothing else in the Karpathy loop is blocked on shipping this. It can land any time the team has bandwidth.

## Risks / unknowns

- **Doc-size unboundedness.** A 1000-doc corpus is trivial; a 10M-doc corpus is not. Pagination + a hard `size` cap on `_source` previews keep the surface bounded.
- **Engine-specific quirks.** ES and OpenSearch share the same wire-level `_source` shape, but Fusion (MVP3) layers Solr semantics underneath. The endpoint should consume the engine adapter Protocol's existing "fetch by id" / "scroll" primitives rather than hand-rolling per-engine HTTP.
- **Cluster credentials.** Operator clusters with read-only API keys should work; clusters with no creds (anonymous local dev) should also work. Both already covered by the adapter; the new endpoints just thread the request through.

## Relationship to other work

- **Extends** [`infra_adapter_elastic`](../../00_overview/implemented_features/2026_05_10_infra_adapter_elastic/) — uses its read primitives, doesn't change them.
- **Complements** the Confidence panel improver/regressor tables ([PR #282](https://github.com/SoundMindsAI/relyloop/pull/282)) — those tell you *which* queries gained or lost; this would tell you *which docs* are returned for those queries.
- **Independent of** [`feat_studies_ui`](../../00_overview/implemented_features/2026_05_12_feat_studies_ui/) — the study detail page wouldn't change in any blocking way, just gains a cross-link.
