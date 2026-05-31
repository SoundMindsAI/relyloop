# Idea — CI gate for generated-artifact freshness (types.ts + public/docs)

**Date:** 2026-05-31
**Status:** Idea — tangential discovery during `feat_overnight_autopilot` (Story 2.1 + 4.1, PR forthcoming)
**Type:** `infra_`
**Priority:** P2 — silent drift, no current runtime impact, but it pollutes feature PRs with large unrelated diffs and risks shipping stale types.

## Origin

While implementing `feat_overnight_autopilot`:
- Running `pnpm types:gen` (Story 2.1) to surface the two new chain schemas regenerated **~818 lines** of `ui/src/lib/types.ts` — the committed generated file had drifted from the live backend OpenAPI (accumulated `_SourceBreakdown.click` UBI bucket, Solr schemas, etc. from previously-merged features). Two judgment test fixtures had to gain `click: 0` just to typecheck.
- Running `node scripts/copy-docs.mjs` (Story 4.1, the `prebuild`/`predev` sync) revealed `ui/public/docs/tutorial-first-study.md` was missing the "Path C — Solr" section that had been merged into the source `docs/08_guides/tutorial-first-study.md` — the tracked public copy had never been re-synced + committed when Solr shipped.

Both are **tracked generated artifacts** (`ui/src/lib/types.ts` header literally says "GENERATED FILE — do not edit"; `ui/public/docs/*` is a one-direction copy of `docs/08_guides/*`) with **no CI freshness gate**, so they drift silently between the feature that should have regenerated them and the next feature that happens to run the generator.

## Problem

- `ui/src/lib/types.ts` — regenerated from `http://localhost:8000/openapi.json` via `pnpm types:gen` (`ui/scripts/gen-types.mjs`). Nothing fails CI when a backend schema change lands without a matching regen. The drift surfaces as an unrelated 800-line diff in whatever frontend PR next touches types.
- `ui/public/docs/*` — synced from `docs/08_guides/*` via `ui/scripts/copy-docs.mjs` (`prebuild`/`predev` hooks). A guide edit that isn't followed by a committed sync leaves the tracked public copy stale; the drift only corrects when someone runs a local build and notices the dirty working tree.

## Proposed capability

A CI job (or pre-commit hook) that regenerates both artifacts and fails if the working tree is dirty afterward:

```bash
# requires a running backend for types:gen — gate behind the existing service-container API
cd ui && pnpm types:gen && node scripts/copy-docs.mjs
git diff --exit-code ui/src/lib/types.ts ui/public/docs/   # non-zero = stale artifact committed
```

For `types:gen` the gate needs the API up (CI already has a service-container Postgres; would need the API container too, or a cached `openapi.json` snapshot checked into the repo to diff against). `copy-docs` is pure-filesystem and can run anywhere — that half is cheap and could ship first.

## Scope signals

- **Backend:** none.
- **Frontend / CI:** moderate — a new `pr.yml` step (or two: cheap copy-docs check now, types:gen check when an API service container is wired into the frontend job).
- **Migration / config:** none.
- **Audit events:** N/A.

## Why deferred (not fixed inline)

Out of scope for `feat_overnight_autopilot` — this is a CI/tooling subsystem change unrelated to the chain-summary feature, and the `types:gen` half needs an API service container in the frontend CI job (an infra decision, not a one-liner). The feature PR corrected the drift as a side effect; this idea prevents recurrence.

## Relationship to other work

- The `types.ts` drift forced cross-feature fixture edits in `feat_overnight_autopilot` PR (the `click: 0` additions) — see that PR's description.
- Pairs with the broader "hermetic CI" posture in `infra_ci_smoke_makeup` (shipped) — both are about CI catching integration-boundary drift that unit tests miss.
