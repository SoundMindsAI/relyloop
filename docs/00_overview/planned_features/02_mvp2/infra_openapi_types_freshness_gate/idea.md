# infra_openapi_types_freshness_gate — offline OpenAPI export + `types.ts` freshness gate

**Date:** 2026-06-01
**Status:** Idea — Phase 2 of [`infra_generated_artifact_freshness_gate`](../infra_generated_artifact_freshness_gate/feature_spec.md), extracted to its own folder
**Type:** `infra_`
**Priority:** P2 (same as parent)

## Origin

Defined as Phase 2 in [`infra_generated_artifact_freshness_gate/feature_spec.md`](../infra_generated_artifact_freshness_gate/feature_spec.md) §3 "Phase boundaries". Phase 1 (the `copy-docs` freshness gate — FR-1, FR-3, FR-9) ships first because it is pure-filesystem and zero-infra. This work carries the OpenAPI-export + `types.ts` half, which has a real import-cleanliness investigation and a banner-determinism fix.

> The parent's [`implementation_plan.md`](../infra_generated_artifact_freshness_gate/implementation_plan.md) covers both phases (Epic 1 = Phase 1, Epic 2 = Phase 2). This standalone folder is the discoverable idea-stage record of the Phase 2 half if Phase 1 ships alone; if both phases ship in one pass, this folder is retired at finalization.

## Deferred functional requirements (from the spec)

- **FR-2** — `types.ts` freshness gate: regenerate `ui/src/lib/types.ts` from the committed `ui/openapi.json` snapshot using the locked absolute-path source form (`OPENAPI_URL="$PWD/ui/openapi.json" pnpm --dir ui types:gen`), fail on `git status --porcelain` drift.
- **FR-4** — offline, deterministic OpenAPI export: a backend entrypoint that emits the canonical schema with **no** running server / live DB / ES / OpenSearch. Requires an **import-graph spike** (the parent spec's main open question) to prove no live clients are constructed at schema-build time and to pick path (a) `*_FILE` dummy stand-ins vs path (b) `get_openapi()` from a side-effect-clean route table. Canonical serialization locked: `json.dumps(schema, sort_keys=True, separators=(",",":"), ensure_ascii=False)` + trailing newline + atomic write + clean stdout.
- **FR-5** — banner determinism + stance reconciliation in `gen-types.mjs`: make the banner source-invariant (no interpolated `OPENAPI_URL`), drop the false "CI does NOT regenerate" line, and switch the invocation from `npx` to the lockfile-pinned `openapi-typescript` binary.
- **FR-6** — determinism verification (also applies to Phase 1, but the `types.ts`/snapshot determinism is the harder half).
- **FR-7** — `ui/openapi.json` snapshot freshness gate (needs the backend `uv` toolchain).
- **FR-8** (Phase 2 half) — the canonical chained local-fix command spanning exporter + `types:gen`.

Acceptance criteria: AC-4, AC-5, AC-6, AC-7, AC-8, AC-9 (types/snapshot half), AC-10.

## Why deferred

Phase 1 is zero-dependency and immediately catches the recurring guide-sync drift. Phase 2 requires:
1. The import-graph spike (does the schema builder import cleanly without triggering `backend/app/main.py:195`'s module-level `get_settings()`, and is route-table assembly side-effect-free?).
2. The `gen-types.mjs` banner-determinism + `npx`→pinned-binary edits.
3. Committing a new `ui/openapi.json` snapshot artifact.

These are larger surface + carry the only real open question in the spec.

## Dependencies on Phase 1

Soft. Phase 2 reuses Phase 1's gate-step pattern (regenerate + `git status --porcelain` + canonical fix-command text + the `scripts/` guard + negative-test harness). Phase 2 can ship independently but is cheaper after Phase 1 establishes the pattern.

## Open question carried forward

- **FR-4 import path (a) vs (b)** — resolve in the Phase 2 plan's first story (the spike). Recommended default: try path (b) `get_openapi()` against a side-effect-clean router assembly; fall back to path (a) `*_FILE` dummy stand-ins. See spec §19.
