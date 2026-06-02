# Idea — three contract-test allowlists are out of date with recently-shipped MVP2 features

**Date:** 2026-05-31
**Status:** Idea — tangential discovery during `feat_study_convergence_indicator` pre-push gate
**Type:** `bug_`
**Priority:** P2 — three failing contract tests on a clean tree (no local changes). Doesn't block local dev, but every subsequent PR's local `pytest backend/tests/contract/` is going to see these failures and have to triage them inline.

## Origin

Reproduced live during `feat_study_convergence_indicator` pre-push gate (commit `265a946f`). Running `pytest backend/tests/contract/` on a clean working tree produced:

```
FAILED backend/tests/contract/test_enum_source_of_truth_helpers.py::test_resolve_engine_type_wire
FAILED backend/tests/contract/test_health_contract.py::TestHealthOpenAPISchema::test_response_schema_matches_documented_keys
FAILED backend/tests/contract/test_openapi_surface.py::test_openapi_has_no_orphan_endpoints
```

Each one was confirmed pre-existing via `git stash` (no working-tree changes) on `feat/study-convergence-indicator`. They are NOT introduced by this feature.

## Problem

Three separate contract-test allowlists were not updated as features shipped through MVP2. Each is a "hand-maintained canonical list of valid values" that drifts when a feature adds new entries to the underlying source-of-truth but doesn't touch the test allowlist:

1. **`test_resolve_engine_type_wire`** ([`backend/tests/contract/test_enum_source_of_truth_helpers.py:100`](../../../../../backend/tests/contract/test_enum_source_of_truth_helpers.py#L100)) — asserts the resolver returns `{"elasticsearch", "opensearch"}`. Should be `{"elasticsearch", "opensearch", "solr"}` after `infra_adapter_solr` shipped (2026-05-31, PR #336).

2. **`TestHealthOpenAPISchema::test_response_schema_matches_documented_keys`** ([`backend/tests/contract/test_health_contract.py:161`](../../../../../backend/tests/contract/test_health_contract.py#L161)) — asserts `/healthz` `subsystems` keys are `{"db", "elasticsearch", "opensearch", "redis", ...}`. Should include `"solr"` after `infra_adapter_solr` Story A12.

3. **`test_openapi_has_no_orphan_endpoints`** ([`backend/tests/contract/test_openapi_surface.py:217`](../../../../../backend/tests/contract/test_openapi_surface.py#L217)) — asserts every endpoint in the OpenAPI surface appears in a hand-maintained `EXPECTED_ENDPOINTS` set. Missing 5 endpoints from three features:
   - `GET /api/v1/clusters/{cluster_id}/ubi-readiness` (`feat_ubi_judgments`, PR #317)
   - `POST /api/v1/judgments/generate-from-ubi` (`feat_ubi_judgments`)
   - `GET /api/v1/studies/{study_id}/chain` (`feat_overnight_autopilot`, PR #343)
   - `POST /api/v1/clusters/test-connection` (`infra_adapter_solr`, Story A8)
   - `POST /api/v1/clusters/{cluster_id}/reprobe` (`infra_adapter_solr`, Story A8)

All three failures are the same shape: a feature added an entry to its source-of-truth (e.g., extending the `engine_type` CHECK constraint, adding a new endpoint to a router) but the matching contract-test allowlist wasn't updated in the same PR.

## Proposed fix

**Single-PR, scoped to the three test files:**

1. **`test_resolve_engine_type_wire`** — change `{"elasticsearch", "opensearch"}` → `{"elasticsearch", "opensearch", "solr"}`.
2. **`TestHealthOpenAPISchema::test_response_schema_matches_documented_keys`** — extend the expected `subsystems` set with `"solr"`.
3. **`test_openapi_has_no_orphan_endpoints`** — add the 5 missing `(method, path)` tuples to `EXPECTED_ENDPOINTS`. Group them with the existing comment that says which feature/PR each came from for traceability.

No production-code change. ~10 LOC across 3 files. Each fix has a clear blame trail to the originating feature; the test allowlists should have been updated as part of those features' implementation plans.

## Why this happened

The hand-maintained allowlists are a defensive contract pattern (they catch silently-orphaned endpoints + drift in enum surfaces) but they're not auto-derived. Each feature's pre-push gate should have surfaced the failure, but the failures landed across at least three different feature PRs without being addressed — suggesting:

- Either the pre-push gate was waived (`SKIP_HEAVY_CI=true` per state.md — but local `make test-contract` would also have failed),
- OR the contributors saw the failures and assumed "pre-existing" without filing the idea,
- OR the failures are masked when running the test container in isolation (`make test-worktree`) but not on the operator's host.

Worth investigating once the fix lands — there may be a CI configuration gap that lets these allowlist drifts slip through.

## Scope signals

- **Backend tests:** 3 file edits, ~10 LOC total.
- **Frontend / migration / config:** none.
- **Audit events:** N/A (test-only change).

## Relationship to other work

- Originating PRs: `feat_ubi_judgments` (PR #317), `feat_overnight_autopilot` (PR #343), `infra_adapter_solr` (PR #336). All shipped between 2026-05-29 and 2026-05-31.
- Sibling `chore_solr_post_pipeline_followups` (in this bucket) tracks other Solr-related follow-ons but does NOT mention these three contract test failures — they belong in this dedicated bug file.
- After this lands, consider adding a CLAUDE.md note under "Common Pitfalls" reminding contributors that a new endpoint or a new enum value must be paired with an `EXPECTED_ENDPOINTS` / wire-allowlist update in the same PR.
