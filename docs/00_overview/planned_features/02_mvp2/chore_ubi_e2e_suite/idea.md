# chore_ubi_e2e_suite — UBI Story 5.2 E2E suite

**Date:** 2026-05-29
**Status:** Idea — deferred from `feat_ubi_judgments` Story 5.2
**Origin:** feat_ubi_judgments PR (Story 5.2 was scoped in the implementation plan but deferred — needs a CI OpenSearch UBI plugin install + real-backend Playwright wiring that's heavier than a single PR can comfortably absorb on top of the 11-story UBI bundle)
**Depends on:** `feat_ubi_judgments` shipped + CI OpenSearch container with UBI plugin enabled
**Priority:** P2

## Problem

The implementation plan §3.4 scoped four E2E specs against the existing
OpenSearch service container:

- `ubi-onramp-rung-0.spec.ts`
- `ubi-onramp-rung-3.spec.ts`
- `ubi-hybrid-mode.spec.ts`
- `ubi-source-filter.spec.ts`

Plus a reusable `ui/tests/e2e/helpers/seed_ubi.ts` helper to write
`ubi_queries` + `ubi_events` directly to OpenSearch.

These specs need:

1. The existing OpenSearch service container to have the UBI plugin
   installed (not the default).
2. The seed helper to write valid UBI documents matching the worker's
   field-extraction expectations.
3. The standard real-backend Playwright pattern (no `page.route()`
   mocking).

Shipping all four specs in the main UBI PR would add ~400 LOC of E2E
infra + a Compose change to the OpenSearch service definition — both
out of proportion to the rest of the PR's review cost.

## Proposed capabilities

Ship as a focused E2E-only PR:

1. **Compose change** — add the OpenSearch UBI plugin to the existing
   service container (or a new `opensearch-ubi` profile).
2. **`seed_ubi.ts` helper** — `seedUbiQueries(...)` and `seedUbiEvents(...)`
   writing direct to the OS HTTP API.
3. **Four specs** — rung_0 nudge + dismiss, rung_3 happy-path UBI gen
   (poll list → assert source=click rows), rung_1 hybrid + sparse card
   + value-delta vs prior, source-filter click rendering.

## Scope signals

- Backend: zero changes.
- Frontend: zero changes.
- Test infra: 1 Compose change + 4 spec files + 1 helper file.

## Why deferred

The UBI feature works end-to-end without these specs (the unit + the
contract layer + the type system + the manual smoke covers the surface).
The E2E suite is value-add for regression protection, not load-bearing.
Shipping it as a separate PR keeps both PRs cleanly reviewable + avoids
mixing the OpenSearch UBI plugin install into the feature PR's diff.
