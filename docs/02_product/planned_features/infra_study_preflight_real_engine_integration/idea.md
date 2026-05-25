# Real-engine integration test fixture for the study-preflight overlap probe

**Date:** 2026-05-22
**Status:** Idea — surfaced during [`feat_study_preflight_overlap_probe`](../../../00_overview/implemented_features/2026_05_22_feat_study_preflight_overlap_probe/feature_spec.md) phase-gate review (PR #193, squash-merged as `ca835e0` on 2026-05-22). Feature shipped; this idea covers the deferred test-infra investment.
**Priority:** P2 — current coverage is sufficient (AC-10 + AC-11 exercise the real adapter call path end-to-end via captured `NativeQuery` body shape); this would add value-add real-engine assertions but no new bug class is uncovered.

**Origin:** GPT-5.5 phase-gate code review on [`feat_study_preflight_overlap_probe`](../../../00_overview/implemented_features/2026_05_22_feat_study_preflight_overlap_probe/feature_spec.md) (PR #193, squash `ca835e0`, merged 2026-05-22) flagged that integration cases AC-1 through AC-4b were implemented as monkeypatches of `backend.app.api.v1.studies.probe_judgment_overlap` instead of real-engine end-to-end runs against the ES service container. The decision to monkeypatch was deliberate: the existing `_seed_minimum_for_post_studies()` fixture ([`backend/tests/integration/test_studies_api.py:61`](../../../../backend/tests/integration/test_studies_api.py#L61)) seeds a stub `base_url="http://stub:9200"` cluster with no method to bulk-index documents with specific doc IDs into that cluster's index. Adding the real-engine path requires net-new fixture infrastructure.

## Problem

`feat_study_preflight_overlap_probe`'s integration tests (AC-1 through AC-4b in [`backend/tests/integration/test_studies_api.py`](../../../../backend/tests/integration/test_studies_api.py)) use `monkeypatch.setattr("backend.app.api.v1.studies.probe_judgment_overlap", ...)` to inject `OverlapProbeResult` fakes. This validates the handler's threshold logic (the `min(MIN_OVERLAP, max(judged_doc_count, 1))` formula and the 422 envelope shape) but does NOT exercise:

1. The real `probe_judgment_overlap()` against seeded `queries` + `judgments` rows hitting the new repo helpers (`find_first_judged_query`, `list_doc_ids_for_list_and_query`).
2. The actual `NativeQuery` ids-query body against a real ES `_search` round-trip with real seeded index documents.
3. The probe → ES → ScoredHit decode chain end-to-end.

The dict-key unpacking + adapter-call-shape locking IS covered by AC-10 + AC-11 (both monkeypatch `ElasticAdapter.search_batch` to capture the call args), so the real adapter Protocol invocation IS verified. The remaining gap is "do `find_first_judged_query` + `list_doc_ids_for_list_and_query` produce the expected results against real DB rows in the full POST /studies flow."

## Why deferred

- Current coverage is meaningful: 4 unit tests exercise `probe_judgment_overlap` with mocked repo + adapter; AC-10 + AC-11 lock the real adapter-call shape and dict-key unpacking via captured kwargs.
- Adding real-engine tests requires a new fixture that bulk-indexes documents into the cluster's test ES index with specific doc IDs (to control overlap counts deterministically). The existing fixture's stub cluster has no live ES counterpart.
- Risk of false-positive flake from CI ES timing > value of the assertion in steady state.

## Proposed capabilities

If a future test-infra investment makes this cheap:

1. Add a `_seed_es_docs_for_overlap_probe(cluster_id, target, doc_ids)` fixture helper that bulk-indexes the given doc IDs into the cluster's `target` index. The `SearchAdapter` Protocol ([`backend/app/adapters/protocol.py`](../../../../backend/app/adapters/protocol.py)) intentionally does not expose `bulk_index` — it's a query-time abstraction, not a write-time one. The fixture needs another path. **Decision to lock at spec time (recommended default — see Decisions to lock below):** use a dedicated test-only helper that imports the underlying httpx client / `elasticsearch-py` client directly from inside the fixture module, bypassing the Protocol. Do NOT add a `bulk_index` method to the `SearchAdapter` Protocol just for test fixtures — that pollutes the Protocol's product surface with non-product responsibilities and forces both `ElasticAdapter` and any future `FusionAdapter` to implement a write method they don't need.
2. Replace AC-1 through AC-4b's monkeypatch-based assertions with calls through the real probe, seeding judgments + matching/non-matching index docs to control the overlap count.
3. Keep AC-10 + AC-11 (adapter-call-shape locks) as-is — they catch a different class of bug (Protocol-shape drift).

## Decisions to lock at spec time

- **D-1 (bulk-index mechanism):** the test fixture uses a dedicated test-only client (httpx or `elasticsearch-py`) initialized from the cluster's `base_url` + credentials inside the fixture module. Do NOT extend the `SearchAdapter` Protocol. **Why:** the Protocol's role is engine-agnostic *query-time* search; bulk-indexing is a test-time concern that doesn't generalize across `ElasticAdapter` + future `FusionAdapter` (Fusion's bulk-index surface differs significantly and would never share an interface with ES's `_bulk`). Locking this at spec time prevents the spec from re-litigating Protocol-vs-fixture-helper.
- **D-2 (CI engine):** the test fixture indexes against the ES service container only (matching the established pattern of the existing `acquire_adapter` real-engine tests). OpenSearch coverage at the `search_batch` layer is satisfied via the adapter Protocol contract tests per [`feat_study_preflight_overlap_probe/feature_spec.md` Decision Log entry 2026-05-22](../../../00_overview/implemented_features/2026_05_22_feat_study_preflight_overlap_probe/feature_spec.md). **Why:** running both ES + OpenSearch in CI for this fixture would double the runtime without exercising any code path the Protocol contract doesn't already cover.

## Coordinates with

- [`chore_studies_post_arq_spy_fixture`](../chore_studies_post_arq_spy_fixture/idea.md) (also deferred from the same phase-gate review) — the Arq spy fixture and the ES bulk-index fixture are independent investments; either can land first.
