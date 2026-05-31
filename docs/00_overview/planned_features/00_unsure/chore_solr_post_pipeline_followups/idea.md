# chore_solr_post_pipeline_followups

**Date:** 2026-05-30
**Status:** Idea — tangential observations from `infra_adapter_solr` end-to-end
**Origin:** `/impl-execute` mid-flight sweep during `infra_adapter_solr` Stories
A1–A13.

## Problem

The 13-story `infra_adapter_solr` execution surfaced several follow-on items
that fit neither the original spec nor any sister feature folder. None block
the MVP2 Solr release — they're operator-experience or test-infra cleanups
worth tracking so they don't evaporate.

## Proposed capabilities

1. **`make up` end-to-end verification** for the new Solr Compose service.
   The skill's mandatory operator-path verification was deferred to the
   operator per the mid-flight checkpoint. Items to verify on the first
   `make up` after merge:
   - `bootstrap-security.sh` generates `security.json` on a clean
     `./data/solr` and Solr boots green within the healthcheck window.
   - `/healthz` reports `subsystems.solr = "reachable"` + Solr version
     `10.0.x` when the SOLR_HOST env var is set.
   - `make seed-solr` creates the products + ubi_queries + ubi_events
     collections and bulk-indexes `samples/products.json`.
   - `make seed-clusters` registers `local-solr` alongside ES / OpenSearch
     without auth errors.

2. **Live-Solr integration tests** that were scaffolded in the spec but
   deferred to the operator-stack restart:
   - `backend/tests/integration/test_compose_solr_up.py` — Compose smoke.
   - `backend/tests/integration/test_solr_live_healthz.py` — `/healthz`
     subsystems.solr probe against running Solr.
   - `backend/tests/integration/test_solr_live_search.py` — `search_batch`
     round-trip + per-query error isolation.
   - `backend/tests/integration/test_solr_live_explain.py` — `debugQuery`
     parses + Lucene-escaped doc IDs work.
   - `backend/tests/integration/test_solr_live_document_browser.py` —
     `get_document` + `list_documents` + 101-doc/limit-25 no-gap test.
   - `backend/tests/integration/test_solr_live_reprobe.py` — `/reprobe`
     concurrent serialization + atomic rollback on probe failure.
   - `backend/tests/integration/test_solr_live_ltr_rescore.py` — LTR model
     upload + rescore round-trip.
   - `backend/tests/integration/test_solr_live_ubi_reader.py` — UbiReader
     against Solr's `solr.UBIComponent`.

3. **Frontend `types.ts` regen** — the openapi-generated types were
   manually patched (7 `engine_type` unions + 2 `auth_kind` unions widened
   for Solr). After the operator restarts the api container, run
   `cd ui && pnpm types:gen` so the regenerated file replaces the manual
   patch with the canonical openapi output. The patches should be
   bit-for-bit equivalent.

4. **Guide 01 Playwright screenshot regen** — `docs/08_guides/...`
   Guide 01 "Register your first cluster" needs new screenshots covering
   the Solr engine pick + per-engine auth filtering. `pnpm capture-guides`
   drives this against the running stack.

5. **`ui/tests/e2e/solr-study-end-to-end.spec.ts`** — real-backend
   Playwright spec running the full Karpathy loop against live Compose
   Solr (no `page.route()` mocking). Mirrors `signup_flow.spec.ts` pattern
   per CLAUDE.md E2E Testing Rules.

6. **`explain` `{!term}` parser (GPT-5.5 review F4, deferred Low).**
   `explain()` pins the doc via `fq=<uniqueKey>:<lucene-escaped doc_id>`.
   That's correct for the normal `string` uniqueKey, but switching to the
   `{!term f=<uniqueKey>}<doc_id>` parser would be analysis-independent
   (matters only if a uniqueKey is mapped to a text field — unlikely for
   IDs) and would drop the Lucene-escape dependency entirely. Deferred
   because it churns the explain escape-assertion unit tests for a Low
   finding that's correct in the common case. When picked up: also strip
   `fl` from the explain request (harmless today; debug.explain ignores it).

7. **Pre-flight LTR-model validator on study create** — the
   render-time pre-flight catches the common case (a trial would actually
   hit the missing model), but study create currently accepts a
   `rerank_model.id` that's not in `engine_config.ltr_models`. The
   pre-flight should run earlier (in the studies POST handler) so the
   operator sees the 400 LTR_MODEL_NOT_FOUND before submitting a study
   that's guaranteed to fail at trial time.

## Why deferred

Items 1–5 explicitly require the operator's Compose stack to be restarted
with the new Solr service — they're not bugs in the implementation, just
post-merge operator hygiene + infra-paid-for-by-running-Solr verification.

Item 6 is a defense-in-depth nice-to-have; the render-time check covers the
trial-run hot path. Pre-flight at study create requires cluster.engine_config
lookup across the studies POST handler, which adds a coupling point that's
worth designing carefully rather than rushing.

## Deferred Gemini perf-hardening findings (PR #336, non-blocking)

8. **Bound the probe's per-target uniqueKey fetch (Gemini Gm2).**
   `probe_capabilities` loops over targets sequentially issuing
   `/<target>/schema/uniquekey`. For a cluster with many collections this is
   N sequential round-trips. Wrap in `asyncio.gather` with a bounded
   semaphore. Registration-time only; demo clusters have 1-3 collections so
   no urgency.

9. **Explicit concurrency cap in `search_batch` (Gemini Gm3).**
   `asyncio.gather` over all queries has no semaphore. httpx's default pool
   already caps concurrent sockets, so this is tuning rather than a leak;
   add a bounded semaphore if a large query set saturates the pool.

10. **Validate non-int `rows` in `_build_select_request` (Gemini Gm5).**
    A template/operator passing a non-int `rows` string currently lets Solr
    400 (translated to `INVALID_QUERY_DSL`). Pre-validating would give a
    clearer message. Low value; safe degradation today.

## Scope signals

- 1: operator action only (no code).
- 2: `backend/tests/integration/` — ~8 new files; mirrors existing patterns.
- 3: 1 file regen + diff verification.
- 4: 2 new screenshot assets + 1 modified Playwright spec.
- 5: 1 new Playwright spec (~150 LOC, mirrors `signup_flow.spec.ts`).
- 6: 1 service-layer validator + 1 router translation + 2 tests.
