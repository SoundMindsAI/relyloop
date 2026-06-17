# Phase 2 — Engine version selection at install time

**Date:** 2026-06-17
**Status:** Idea — deferred phase of [`feat_selective_engine_startup_and_demo`](feature_spec.md)
**Priority:** P3 — polish on top of Phase 1's engine selection; not blocking; depends on Phase 1 shipping first
**Origin:** Deferred from [`feature_spec.md`](feature_spec.md) §3 "Phase boundaries" (Phase 2 row). The user's original ask in [`idea.md`](idea.md) included "the latest of the last 2 major releases for the engines selected" — Phase 1 ships engine selection without version selection so the larger lift (curated version matrix + ES/OS version-report path) lands as a follow-on PR with its own review surface.
**Depends on:** Phase 1 (`feat_selective_engine_startup_and_demo` — engine selection at install + reset modal) merged first. Phase 2 reuses the `RELYLOOP_ENGINES` env var + the `EngineTypeWire` literal.

## Problem

Phase 1 ships engine *selection* — operator picks which engines start at install time. Engine *versions* stay hardcoded in [`docker-compose.yml`](../../../../../docker-compose.yml) at `elasticsearch:9.4.1`, `opensearchproject/opensearch:3.6.0`, `solr:10.0`. To run RelyLoop against a different ES version (e.g. an older 8.x cluster the operator is migrating from, or a newer 9.5 they're evaluating), they have to edit the Compose file by hand. The user's original ask was for "the latest of the last 2 major releases" to be offered as a built-in choice.

## Proposed capabilities

### A. Per-engine image tag env vars

- Add `ES_IMAGE_TAG`, `OS_IMAGE_TAG`, `SOLR_IMAGE_TAG` env vars in [`docker-compose.yml`](../../../../../docker-compose.yml) with the current pins as defaults:
  ```yaml
  elasticsearch:
    image: ${BASE_REGISTRY:-}elasticsearch:${ES_IMAGE_TAG:-9.4.1}
  ```
- Default unset → current behavior preserved.
- `.env.example` documents the env vars and the offered version matrix (D below).

### B. Curated engine version matrix

- New backend constant `ENGINE_VERSION_MATRIX` (location: `backend/app/services/demo_seeding.py` or a new `backend/app/core/engine_versions.py`) listing maintainer-curated valid tags per engine, e.g.:
  ```python
  ENGINE_VERSION_MATRIX: Final = {
      "elasticsearch": ("9.4.1", "8.15.3"),  # latest of last two majors
      "opensearch":    ("3.6.0", "2.18.0"),
      "solr":          ("10.0",  "9.7"),
  }
  ```
- Mirror in `ui/src/lib/enums.ts` as `ENGINE_VERSION_MATRIX` const with the source-of-truth comment (per CLAUDE.md "Enumerated Value Contract Discipline").
- Manual maintainer update on each upstream release (deferred-fork D-5 locked: no runtime Docker Hub discovery — see [`feature_spec.md`](feature_spec.md) D-5 rationale).

### C. install.sh non-interactive version flags

- `RELYLOOP_ES_VERSION`, `RELYLOOP_OS_VERSION`, `RELYLOOP_SOLR_VERSION` env vars accepted by `scripts/install.sh`.
- Validate each value against `ENGINE_VERSION_MATRIX` for its engine; reject unknown values with `Unknown <engine> version 'X'. Allowed: <matrix values>.` BEFORE any `docker compose` invocation (same pre-validation discipline as Phase 1's `RELYLOOP_ENGINES`).
- Translate validated values into `ES_IMAGE_TAG` / `OS_IMAGE_TAG` / `SOLR_IMAGE_TAG` exports for the Compose invocation.

### D. ES/OS version-report path

- Today Solr has `probe_capabilities()` returning a structured version; ES/OS only have the binary-reachable probe.
- Extend `is_engine_reachable` (or add a sibling `is_engine_reachable_with_version`) to return `(reachable: bool, version: str | None)` for ES/OS by parsing the `version.number` field from their root response.
- Update the Phase 1 `GET /api/v1/_test/demo/engines` capability endpoint to include the version field:
  ```json
  {"engine_type": "elasticsearch", "reachable": true, "version": "9.4.1"}
  ```
- Reset modal renders the version inline next to each engine checkbox label (read-only, no select — version changes still require re-running install).

### E. Updated docs

- [`docs/03_runbooks/local-dev.md`](../../../../03_runbooks/local-dev.md) — "Selecting an engine version" subsection.
- [`docs/01_architecture/deployment.md`](../../../../01_architecture/deployment.md) — engine version matrix block.
- README / maintainer docs — process for adding a new version row to the matrix on each upstream release.

## Scope signals

- **Backend:** ~150–250 LOC. New `ENGINE_VERSION_MATRIX` constant. Extend `is_engine_reachable` to surface ES/OS versions. Extend `DemoEngineStatus` Pydantic model with `version: str | None`.
- **Frontend:** ~50–100 LOC. New `ENGINE_VERSION_MATRIX` mirror in `ui/src/lib/enums.ts` (Phase 2 may not need a frontend version-select; the version display is informational). Reset modal renders version label.
- **Infra / Compose:** `image:` lines change to interpolate `${X_IMAGE_TAG:-default}`. `.env.example` documents new env vars.
- **CI:** the smoke job pins to known-good versions; verify image tag interpolation works in CI.
- **Migration:** None.
- **Audit events:** N/A (still pre-MVP3 audit_log; `_test` namespace excluded).

## Why deferred

- Engine selection (Phase 1) is the larger user-value win; version selection is polish.
- ES/OS have no version-report logic today; adding it solely to populate a read-only modal display would be unjustified — the install-time version picker is the justification.
- The version-matrix maintenance discipline (D-5 in Phase 1's spec) is a real ongoing cost; deferring lets the team observe whether Phase 1's engine selection is heavily used before paying that cost.

## Relationship to other work

- **Hard dependency on Phase 1.** Phase 2 reuses the `RELYLOOP_ENGINES` env var, the `EngineTypeWire` literal, and the `GET /api/v1/_test/demo/engines` endpoint shape.
- Builds on the Solr capability-probe pattern from [`infra_adapter_solr`](../../../implemented_features/2026_05_31_infra_adapter_solr/) — extends the version-report concept to ES/OS.
- Compose engine-service edits coordinate with the corp-network install series (`chore_corp_install_dx_improvements` and siblings) — coordinate `.env.example` edits.
