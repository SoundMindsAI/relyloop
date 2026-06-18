# Engine version selection at install time

**Date:** 2026-06-17
**Status:** Idea — ready for `/pipeline`. Spun out of the shipped [`feat_selective_engine_startup_and_demo`](../../../implemented_features/2026_06_17_feat_selective_engine_startup_and_demo/feature_spec.md) at finalization (it shipped engine *selection*; this folder is engine *version* selection). **Not deferred** — the operator confirmed (2026-06-17) that version selection is a core requirement, not polish: RelyLoop must not assume every customer runs the latest engine version.
**Priority:** P1 — high-value, ready now. The core (capabilities A+B+C: image-tag env vars, curated matrix, install.sh flags) lets an operator evaluate RelyLoop against the engine version their production cluster actually runs, instead of being forced onto the hardcoded latest. Capability D (version display in the reset modal) is the one optional nice-to-have within the feature and can be dropped at spec time without losing the core value. (Dashboard `_extract_priority` at [`scripts/build_mvp1_dashboard.py:299`](../../../../../scripts/build_mvp1_dashboard.py#L299) recognizes `P0`/`P1`/`P2`/`Backlog` — `P1` is honored verbatim.)
**Origin:** Deferred from [`feat_selective_engine_startup_and_demo`'s feature_spec.md](../../../implemented_features/2026_06_17_feat_selective_engine_startup_and_demo/feature_spec.md) §3 "Phase boundaries" (Phase 2 row). The user's original ask included "the latest of the last 2 major releases for the engines selected" — the shipped feature provided engine *selection* without version selection, so the larger lift (curated version matrix + ES/OS version-report path) lands as a follow-on with its own review surface.
**Depends on:** [`feat_selective_engine_startup_and_demo`](../../../implemented_features/2026_06_17_feat_selective_engine_startup_and_demo/feature_spec.md) — **shipped** (PR #548, 2026-06-17). This work reuses the `RELYLOOP_ENGINES` env var + the `EngineTypeWire` literal + the `GET /api/v1/_test/demo/engines` endpoint it added.

## Problem

Phase 1 ships engine *selection* — operator picks which engines start at install time. Engine *versions* stay hardcoded in [`docker-compose.yml`](../../../../../docker-compose.yml) at `elasticsearch:9.4.1`, `opensearchproject/opensearch:3.6.0`, `solr:10.0`. To run RelyLoop against a different ES version (e.g. an older 8.x cluster the operator is migrating from, or a newer 9.5 they're evaluating), they have to edit the Compose file by hand. The user's original ask was for "the latest of the last 2 major releases" to be offered as a built-in choice.

## Proposed capabilities

### A. Per-engine image tag env vars

- Add `ES_IMAGE_TAG`, `OS_IMAGE_TAG`, `SOLR_IMAGE_TAG` env vars in [`docker-compose.yml`](../../../../../docker-compose.yml) with the current pins as defaults. Verified current pins at [`docker-compose.yml:340`](../../../../../docker-compose.yml#L340) (`elasticsearch:9.4.1`), [`docker-compose.yml:368`](../../../../../docker-compose.yml#L368) (`opensearchproject/opensearch:3.6.0`), [`docker-compose.yml:407`](../../../../../docker-compose.yml#L407) (`solr:10.0`):
  ```yaml
  elasticsearch:
    image: ${BASE_REGISTRY:-}elasticsearch:${ES_IMAGE_TAG:-9.4.1}
  ```
- Default unset → current behavior preserved.
- `.env.example` documents the env vars and the offered version matrix (D below).

### B. Curated engine version matrix

- New backend constant `ENGINE_VERSION_MATRIX` in a new file [`backend/app/core/engine_versions.py`](../../../../../backend/app/core/engine_versions.py) (decision locked at preflight — `backend/app/services/demo_seeding.py` was the original alternative, but the matrix is consumed by BOTH `demo_seeding.py` (for image-tag-aware reseed) and `backend/app/api/v1/_test.py`'s `GET /api/v1/_test/demo/engines` capability endpoint (for the version field in D below); a shared home in `core/` avoids an import-direction cycle). Listing maintainer-curated valid tags per engine, e.g.:
  ```python
  ENGINE_VERSION_MATRIX: Final = {
      "elasticsearch": ("9.4.1", "8.15.3"),  # latest patch of each supported major
      "opensearch":    ("3.6.0", "2.18.0"),
      "solr":          ("10.0",  "9.7"),
  }
  ```
- **Matrix bound locked at preflight: one entry per *supported major* in the adapter compatibility window — NOT a fixed "last 2" count.** Today that yields exactly 2 entries per engine because the documented window is ES 8.11+/9.x ([`adapters.md:147`](../../../../01_architecture/adapters.md#L147)), OpenSearch 2.x/3.x ([`adapters.md:148`](../../../../01_architecture/adapters.md#L148)), and Solr 9.x/10.x ([`adapters.md:232`](../../../../01_architecture/adapters.md#L232), runtime-enforced by `SOLR_MIN_VERSION` at [`solr.py:80`](../../../../../backend/app/adapters/solr.py#L80)). Tying the matrix to the supported-major window — not an arbitrary number — keeps it self-bounding: a row drops when the adapter drops a major, and a row is added when a new major is supported. Do NOT offer:
  - **A major outside the window** (e.g. ES 7.x) — that's an untested compatibility claim; on Solr the version-floor check at [`solr.py:585`](../../../../../backend/app/adapters/solr.py#L585) would abort the probe outright.
  - **Multiple minors within one major** (9.4.1 *and* 9.3.2 *and* …) — the adapter behaves identically across minors, so extra minor rows are pure maintenance cost (each is a manual update per D-5) for zero operator value.
- Mirror in `ui/src/lib/enums.ts` as `ENGINE_VERSION_MATRIX` const with the source-of-truth comment (per CLAUDE.md "Enumerated Value Contract Discipline").
- Manual maintainer update on each upstream major release (deferred-fork D-5 locked: no runtime Docker Hub discovery — see the shipped feature's [feature_spec.md](../../../implemented_features/2026_06_17_feat_selective_engine_startup_and_demo/feature_spec.md) D-5 rationale). The smoke job pins to the latest-major tag, so each offered version stays a *tested* compatibility claim.

### C. install.sh non-interactive version flags

- `RELYLOOP_ES_VERSION`, `RELYLOOP_OS_VERSION`, `RELYLOOP_SOLR_VERSION` env vars accepted by `scripts/install.sh`.
- Validate each value against `ENGINE_VERSION_MATRIX` for its engine; reject unknown values with `Unknown <engine> version 'X'. Allowed: <matrix values>.` BEFORE any `docker compose` invocation (same pre-validation discipline as Phase 1's `RELYLOOP_ENGINES`).
- Translate validated values into `ES_IMAGE_TAG` / `OS_IMAGE_TAG` / `SOLR_IMAGE_TAG` exports for the Compose invocation.

### D. ES/OS version-report path

- Today Solr has [`probe_capabilities()`](../../../../../backend/app/adapters/solr.py#L470) returning a structured version; ES/OS only have the binary-reachable probe at [`is_engine_reachable`](../../../../../backend/app/services/demo_seeding.py#L467) (returns `bool`).
- **Decision locked at preflight:** add a SIBLING `is_engine_reachable_with_version` in `backend/app/services/demo_seeding.py` returning `(reachable: bool, version: str | None)`, rather than changing `is_engine_reachable`'s return type. Rationale: `is_engine_reachable` is called from `snapshot_engine_reachability` (slug→bool map, used by the orchestrator's scenario filter) and `demo_engines()` (the `_test` capability endpoint, which DOES want the version) — only the second caller needs the version, and changing the signature of the first would ripple through the orchestrator filter for no operator value. The sibling preserves a stable `bool`-returning probe for hot paths while adding the richer call site exactly where it's used.
- ES/OS parse: GET `/` → JSON body → `version.number` field (already the same shape `is_engine_reachable` validates today as the `"version" in body` reachability check at [`demo_seeding.py:496`](../../../../../backend/app/services/demo_seeding.py#L496)). Solr reuses the existing `probe_capabilities()` structured version.
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

- **Backend:** ~150–250 LOC. New `ENGINE_VERSION_MATRIX` constant in `backend/app/core/engine_versions.py` (locked above). New sibling `is_engine_reachable_with_version` in `demo_seeding.py` (locked above). Extend `DemoEngineStatus` Pydantic model at [`backend/app/api/v1/_test.py:812`](../../../../../backend/app/api/v1/_test.py#L812) with `version: str | None = None` (the default keeps existing payloads back-compat; the field is `None` until the new probe stamps it).
- **Frontend:** ~50–100 LOC. New `ENGINE_VERSION_MATRIX` mirror in `ui/src/lib/enums.ts` (Phase 2 may not need a frontend version-select; the version display is informational). Reset modal renders version label.
- **Infra / Compose:** `image:` lines change to interpolate `${X_IMAGE_TAG:-default}`. `.env.example` documents new env vars.
- **CI:** the smoke job pins to known-good versions; verify image tag interpolation works in CI.
- **Migration:** None.
- **Audit events:** N/A (still pre-MVP3 audit_log; `_test` namespace excluded).

## Why this is core, not deferred

This folder originally carried a "Why deferred" note inherited from the Phase 1 shipping split. That rationale was retired on 2026-06-17 after the operator confirmed version selection is a core requirement. For the record, why each original deferral bullet does not hold:

- *"Version selection is polish."* — It isn't. RelyLoop hardcodes `elasticsearch:9.4.1` / `opensearch:3.6.0` / `solr:10.0` in [`docker-compose.yml`](../../../../../docker-compose.yml). An operator running, say, ES 8.15 in production cannot evaluate RelyLoop against their real cluster version without hand-editing Compose. That's an evaluation/adoption gap, not polish.
- *"ES/OS have no version-report logic, so it's unjustified."* — That argument only applies to capability **D** (displaying the detected version in the reset modal). The core value is capabilities **A + B + C** (image-tag env vars + curated matrix + install.sh flags), none of which need version-report logic. D stays an optional in-feature nice-to-have; the core ships regardless.
- *"Defer until we see if engine selection is used."* — Conflates two unrelated needs: *which engines start* (Phase 1) vs. *which version of an engine* (this work). Usage of one does not predict demand for the other. The matrix-maintenance cost it worried about is one row update per major release per engine — a few times a year.

**Scope guidance for /spec-gen:** treat A+B+C as the must-ship core and D as a droppable stretch goal if the ES/OS version-report parsing turns out to be more than the ~1-line `version.number` read estimated above.

## Relationship to other work

- **Hard dependency on Phase 1.** Phase 2 reuses the `RELYLOOP_ENGINES` env var, the `EngineTypeWire` literal, and the `GET /api/v1/_test/demo/engines` endpoint shape.
- Builds on the Solr capability-probe pattern from [`infra_adapter_solr`](../../../implemented_features/2026_05_31_infra_adapter_solr/) — extends the version-report concept to ES/OS.
- Compose engine-service edits coordinate with the corp-network install series (`chore_corp_install_dx_improvements` and siblings) — coordinate `.env.example` edits.
