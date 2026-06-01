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
- `ui/public/docs/*` — synced from `docs/08_guides/*` via `ui/scripts/copy-docs.mjs` (`prebuild`/`predev` hooks). The script's `DOCS` array currently syncs **three** guides (`tutorial-first-study.md`, `quick-tour.md`, `workflows-overview.md`) plus a generated `README.md` — verified at [`ui/scripts/copy-docs.mjs:30-34`](../../../../../ui/scripts/copy-docs.mjs). A guide edit that isn't followed by a committed sync leaves the tracked public copy stale; the drift only corrects when someone runs a local build and notices the dirty working tree.
- **Precedent (verified, shipped):** the `license-inventory` CI job (`pr.yml`) already implements this exact "regenerate + fail-if-stale" pattern — it runs `uv run python scripts/gen_license_inventory.py --check` to regenerate `docs/04_security/license-inventory.md` and fails the gate when the committed copy drifts, with a documented local-fix command. This idea applies the same posture to `types.ts` + `ui/public/docs/`. The gate verb (`--check` subcommand vs `git diff --exit-code`) is a spec-time decision (see Open questions).

## Proposed capability

A CI job (or pre-commit hook) that regenerates both artifacts and fails if the working tree is dirty afterward:

```bash
# requires a running backend for types:gen — gate behind the existing service-container API
cd ui && pnpm types:gen && node scripts/copy-docs.mjs
git diff --exit-code ui/src/lib/types.ts ui/public/docs/   # non-zero = stale artifact committed
```

For `types:gen` the gate needs a live `/openapi.json` (`gen-types.mjs` hits `http://localhost:8000/openapi.json` — verified at [`ui/scripts/gen-types.mjs:24`](../../../../../ui/scripts/gen-types.mjs)). The **backend** `pr.yml` job already has a service-container Postgres + ES + OpenSearch, but the **frontend / static-checks-frontend** jobs run service-free (`pnpm install · lint · tsc · vitest · next build`) — they have no API to hit. No cached `openapi.json` snapshot exists in the repo today (verified: `find . -name openapi.json` returns nothing outside `node_modules`). So the `types:gen` half needs an infra decision (option A: stand up the API in a job that already has Postgres; option B: export `openapi.json` from the FastAPI app **without** a running server via `app.openapi()` and diff a committed snapshot). `copy-docs` is pure-filesystem and can run anywhere — that half is cheap and could ship first.

> **Note on `gen-types.mjs`'s self-documented stance:** the generator's own banner says *"CI does NOT regenerate this file — the committed version is the source of truth for the PR"* ([`ui/scripts/gen-types.mjs`](../../../../../ui/scripts/gen-types.mjs)). This idea **changes** that posture for the freshness check (CI regenerates only to *compare*, never to commit). If the gate ships, update that banner comment so it doesn't contradict the new CI behavior.

> **`paths-ignore` interaction (design fork):** `pr.yml`'s `pull_request` trigger carries `paths-ignore: ['docs/**']` (verified at `.github/workflows/pr.yml:48-49`). The `copy-docs` source is `docs/08_guides/*.md`, so a PR that edits **only** a guide may not trigger `pr.yml` at all — meaning a pure-docs guide edit could merge without the copy-docs gate ever running. The gate must either (a) live in a job/path-filter that does fire on `docs/08_guides/**` changes, or (b) accept that the gate catches the drift on the *next* code PR rather than the guide PR itself. This must be resolved at spec time (see Open questions).

## Scope signals

- **Backend:** none.
- **Frontend / CI:** moderate — a new `pr.yml` step (or two: cheap copy-docs check now, types:gen check when an API service container is wired into the frontend job).
- **Migration / config:** none.
- **Audit events:** N/A.

## Why deferred (not fixed inline)

Out of scope for `feat_overnight_autopilot` — this is a CI/tooling subsystem change unrelated to the chain-summary feature, and the `types:gen` half needs an API service container in the frontend CI job (an infra decision, not a one-liner). The feature PR corrected the drift as a side effect; this idea prevents recurrence.

## Open questions for /spec-gen (recommended defaults)

1. **Gate mechanism — `--check` subcommand vs raw `git diff --exit-code`?** *Recommended default:* match the shipped `license-inventory` precedent — regenerate then `git diff --exit-code <artifact paths>` in a CI step with a documented local-fix command in the step comment. (A `--check` flag would mean adding flags to two separate JS generators; the `git diff` approach is generator-agnostic and already proven.)
2. **`types:gen` — live API container vs offline `openapi.json` export?** *Recommended default:* **offline export.** Add a tiny backend entrypoint that calls `app.openapi()` and writes the schema to stdout/file (no Uvicorn, no DB needed for schema generation since FastAPI builds the schema from route signatures), point `gen-types.mjs` at a committed `openapi.json` snapshot, and gate on both the snapshot's freshness and the generated `types.ts`. This keeps the frontend CI job service-free. *Fork to confirm at spec time:* `backend/app/main.py` calls `get_settings()` at **module import time** (line 195, for CORS origins), so naively importing `app` to call `app.openapi()` will trigger settings load — which reads `*_FILE`-mounted secrets and can raise `SettingsError` in a bare CI step. The offline export must either (a) provide minimal dummy secret files in the CI step, or (b) build the OpenAPI schema from the route table without importing the CORS-configured `app` singleton. Verify the cleanest path in the spec.
3. **`paths-ignore: docs/**` interaction.** *Recommended default:* ship the `copy-docs` freshness check in a job that does NOT carry the `docs/**` path-ignore (e.g. its own small job triggered on `docs/08_guides/**` + `ui/public/docs/**`), OR accept best-effort "catch on next code PR" for v1 and note the gap. Lock at spec time.
4. **Phasing — ship `copy-docs` half first?** *Recommended default:* yes. The `copy-docs` check is pure-filesystem (no API, no service container) and can ship as a standalone cheap CI step immediately; the `types:gen` half follows once the offline-export decision (Q2) is settled. Spec may scope this as two phases or one.

## Relationship to other work

- The `types.ts` drift forced cross-feature fixture edits in `feat_overnight_autopilot` PR (the `click: 0` additions) — see that PR's description.
- Pairs with the broader "hermetic CI" posture in `infra_ci_smoke_makeup` (shipped) — both are about CI catching integration-boundary drift that unit tests miss.
- **Closest precedent:** the shipped `license-inventory` CI job (`chore_oss_public_launch_punchlist`, 2026-05-30) — `scripts/gen_license_inventory.py --check` regenerates `docs/04_security/license-inventory.md` and fails CI on drift. This idea is the same regenerate-and-compare pattern applied to two more tracked generated artifacts.
- **`chore_ci_gitignore_paths_ignore_gap`** (shipped 2026-05-13, in `implemented_features/`) — already touched the `pr.yml` `paths-ignore` filter and the docs-only-PR CI-trigger question. Read its design before proposing any path-filter edit in Q3, so this gate's job placement is consistent with that prior decision rather than conflicting with it.
