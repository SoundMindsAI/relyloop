# Implementation Plan — Engine Version Selection at Install Time

**Date:** 2026-06-17
**Status:** Draft
**Primary spec:** [feature_spec.md](feature_spec.md)
**Cross-model review:** Opus self-review (GPT-5.5 unreachable in Claude Code remote sandbox per CLAUDE.md "Environment-aware fallback"; Gemini Code Assist remains the cross-family gate at the code/PR stage).
**Policy source(s):** [`CLAUDE.md`](../../../../../CLAUDE.md) (Absolute Rules #2, #4, #5); [`docs/01_architecture/adapters.md`](../../../../01_architecture/adapters.md) (engine compatibility window); [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md) (error envelope, dev-only `_test` namespace).

---

## 0) Planning principles

- **Spec traceability first:** every story maps to FR IDs and at least one AC.
- **Epic gates are hard stops:** no story in epic N+1 starts until epic N's gate is green.
- **Fail-loud tests:** DoD entries cite explicit status/shape/error/exit-code assertions.
- **Mirror the parent feature's patterns:** the shipped [`feat_selective_engine_startup_and_demo`](../../../implemented_features/2026_06_17_feat_selective_engine_startup_and_demo/feature_spec.md) is the closest analog (same `_test` namespace, same sourceable-bash-helper pattern, same `EngineTypeWire` source-of-truth discipline). Where Phase 1 did engine selection, this does engine *version* selection — story shapes, file locations, and CI guards mirror Phase 1.
- **Back-compat by construction:** default unset → today's behavior. Every story's DoD has at least one assertion proving the default-unset path is byte-identical.

## 1) Scope traceability (FR → epic/story)

| FR ID | Spec section | Epic / Story | Notes |
|---|---|---|---|
| FR-1 | §7 FR-1 | Epic 1 / Story 1.1 | Three `image:` line edits in `docker-compose.yml`. |
| FR-2 | §7 FR-2 | Epic 1 / Story 1.2 | New `backend/app/core/engine_versions.py`. |
| FR-3 | §7 FR-3 | Epic 1 / Story 1.3 | New `scripts/lib/relyloop_engine_versions.sh` + install.sh integration. |
| FR-4 | §7 FR-4 | Epic 1 / Story 1.3 | Pre-validation discipline — same story as the helper (it IS the validator). |
| FR-5 | §7 FR-5 | Epic 3 / Story 3.1 | Frontend mirror in `ui/src/lib/enums.ts`. |
| FR-6 | §7 FR-6 | Epic 2 / Story 2.1 | Sibling `is_engine_reachable_with_version` in `demo_seeding.py`. |
| FR-7 | §7 FR-7 | Epic 2 / Story 2.2 | `DemoEngineStatus.version` field. |
| FR-8 | §7 FR-8 | Epic 2 / Story 2.2 | Capability endpoint wired through. |
| FR-9 | §7 FR-9 | Epic 3 / Story 3.2 | Reset modal version annotation. |
| FR-10 | §7 FR-10 | Epic 1 / Story 1.4 | `.env.example` documentation block. |
| FR-11 | §7 FR-11 | Epic 1 / Story 1.5 | CI guard for matrix-Compose-default sync. |
| FR-12 | §7 FR-12 | Epic 4 / Story 4.1 | Docs: `local-dev.md`, `deployment.md`, `adapters.md` cross-link, `CONTRIBUTING.md`, inline maintainer-process comment. |

**Phase coverage:** Single-phase per spec §3. All 12 FRs implemented in this plan. No deferred phases → **no `phase2_idea.md` to file.** If capability D's parse logic exceeds ~10 LOC per engine during Story 2.1 implementation, the `/impl-execute` Step 8.6 deferred-work mechanism splits it at that time (standard escape valve — does not require pre-allocation here).

## 2) Delivery structure

**Epic → Story → Tasks → DoD** (preferred for product-facing work).

### Conventions

- **Bash helpers** live in `scripts/lib/` and are sourced (not exec'd) from `scripts/install.sh`. Pattern: [`scripts/lib/relyloop_engines.sh`](../../../../../scripts/lib/relyloop_engines.sh) (Phase 1).
- **Bash unit tests** live in `scripts/ci/test_*.sh` and are invoked from `.github/workflows/pr.yml`. Pattern: [`scripts/ci/test_parse_relyloop_engines.sh`](../../../../../scripts/ci/test_parse_relyloop_engines.sh) (Phase 1, 17 cases).
- **Backend Python** follows MVP1 conventions: `core/` for pure constants + types (no DB, no I/O), `services/` for orchestration (async, takes `db: AsyncSession`). New constant goes in `backend/app/core/` per spec §4 anti-patterns (avoids import-direction cycle with the `_test.py` capability endpoint).
- **Frontend `enums.ts` mirrors** use `as const` + a `// Values must match <backend/path>` source-of-truth comment per CLAUDE.md "Enumerated Value Contract Discipline". Pattern: [`ui/src/lib/enums.ts:42-44`](../../../../../ui/src/lib/enums.ts#L42-L44) (`ENGINE_TYPE_VALUES`).
- **Vitest component tests** live alongside the component in `__tests__/`. Pattern: [`ui/src/components/dashboard/__tests__/`](../../../../../ui/src/components/dashboard/__tests__/).
- **CI freshness gates** (`scripts/ci/verify_*.sh`) re-generate the artifact and fail on `git status --porcelain` drift. Extended in Stories 1.5 + 3.1.
- **No migration** — Alembic head stays `0023_proposals_superseded_status`. Skip migration verification (Section 3.5).

### AI Agent Execution Protocol (applies to every story)

1. Read the spec section the story cites BEFORE writing code.
2. Read the analogous Phase 1 file/test BEFORE writing the new one.
3. Run the story's DoD assertions locally before marking the story complete.
4. Run `make fmt && make lint && make typecheck && make test-unit` after each backend story.
5. Run `cd ui && pnpm lint && pnpm typecheck && pnpm test` after each frontend story.
6. Run `bash scripts/regen-generated-artifacts.sh` after Story 2.2 (OpenAPI snapshot includes the new `version` field).
7. Push at the end of each epic (not after each story) — keeps the commit series readable.

---

## Epic 1 — Install-time infrastructure (Compose, matrix, install.sh, .env, CI guard)

**Outcome:** `RELYLOOP_ES_VERSION=8.15.3 make up` boots Elasticsearch 8.15.3; unknown versions are rejected BEFORE any `docker compose pull`; default unset preserves today's behavior; the matrix-Compose-default sync invariant is enforced by CI.

### Story 1.1 — Compose engine services accept image-tag env vars

**Outcome:** The three engine services interpolate `${X_IMAGE_TAG:-<latest-major-default>}` instead of hardcoding the tag. Default unset → byte-identical Compose config to today.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`docker-compose.yml`](../../../../../docker-compose.yml) | Line 340: `image: ${BASE_REGISTRY:-}elasticsearch:9.4.1` → `image: ${BASE_REGISTRY:-}elasticsearch:${ES_IMAGE_TAG:-9.4.1}`. Line 368: `image: ${BASE_REGISTRY:-}opensearchproject/opensearch:3.6.0` → `image: ${BASE_REGISTRY:-}opensearchproject/opensearch:${OS_IMAGE_TAG:-3.6.0}`. Line 407: `image: ${BASE_REGISTRY:-}solr:10.0` → `image: ${BASE_REGISTRY:-}solr:${SOLR_IMAGE_TAG:-10.0}`. No other field changes — `profiles:`, `environment:`, `ports:`, `healthcheck:` all stay identical. |

**Endpoints**

N/A.

**Key interfaces**

```yaml
# docker-compose.yml — three image: lines, same pattern per engine:
image: ${BASE_REGISTRY:-}elasticsearch:${ES_IMAGE_TAG:-9.4.1}
image: ${BASE_REGISTRY:-}opensearchproject/opensearch:${OS_IMAGE_TAG:-3.6.0}
image: ${BASE_REGISTRY:-}solr:${SOLR_IMAGE_TAG:-10.0}
```

**Pydantic schemas**

N/A.

**Tasks**

1. Edit [`docker-compose.yml:340`](../../../../../docker-compose.yml#L340) — replace the literal tag with `${ES_IMAGE_TAG:-9.4.1}`. Add a comment above the `image:` line: `# Image tag interpolation — see feat_engine_version_selection FR-1.`
2. Same edit at [`docker-compose.yml:368`](../../../../../docker-compose.yml#L368) (`${OS_IMAGE_TAG:-3.6.0}`).
3. Same edit at [`docker-compose.yml:407`](../../../../../docker-compose.yml#L407) (`${SOLR_IMAGE_TAG:-10.0}`).
4. Verify byte-identical default behavior: `unset ES_IMAGE_TAG OS_IMAGE_TAG SOLR_IMAGE_TAG; docker compose config | grep -E 'image:.*(elasticsearch|opensearch|solr):' | sort` produces the same output as before the edit. Capture the before/after in the PR body for review.
5. Verify env-var override: `ES_IMAGE_TAG=8.15.3 docker compose config | grep 'image:.*elasticsearch:'` reports `elasticsearch:8.15.3`. (Manual smoke; the CI guard in Story 1.5 backstops this.)

**Definition of Done**

- [ ] `docker-compose.yml` lines 340/368/407 contain `${X_IMAGE_TAG:-<default>}` interpolation. [FR-1]
- [ ] `docker compose config` with no env vars set produces byte-identical output to the pre-PR baseline (verified manually; before/after diff posted in the PR body). [AC-1]
- [ ] `ES_IMAGE_TAG=8.15.3 docker compose config` reports `elasticsearch:8.15.3` (manual smoke).
- [ ] The `[0]` element of each `ENGINE_VERSION_MATRIX` tuple (Story 1.2) matches the corresponding `:-` default in this file. (Cross-checked by Story 1.5's CI guard.) [AC-4]

### Story 1.2 — `ENGINE_VERSION_MATRIX` constant + matrix-key sync unit test

**Outcome:** A new pure-Python constant exports the maintainer-curated valid tags per engine; a unit test enforces the matrix keys stay aligned with `EngineTypeWire`.

**New files**

| File | Purpose |
|---|---|
| [`backend/app/core/engine_versions.py`](../../../../../backend/app/core/engine_versions.py) | Defines `ENGINE_VERSION_MATRIX: Final[dict[str, tuple[str, ...]]]`. Top-of-file comment documents the maintainer release-update process (per FR-2). Module is pure constants — no DB, no I/O, no async. |
| [`backend/tests/unit/core/test_engine_versions_matrix.py`](../../../../../backend/tests/unit/core/test_engine_versions_matrix.py) | Asserts `set(ENGINE_VERSION_MATRIX.keys()) == set(get_args(EngineTypeWire))`. Asserts every tuple is non-empty (the `[0]` access in the Compose-default-sync check would IndexError otherwise). Asserts every value is a str (no tuples of ints or None). |

**Modified files**

None.

**Endpoints**

N/A.

**Key interfaces**

```python
# backend/app/core/engine_versions.py
"""Curated engine image-tag matrix for install-time version selection.

Each entry lists the latest-patch tag for one supported major in the
adapter compatibility window (docs/01_architecture/adapters.md). When
upstream releases a new latest patch for a supported major, update the
corresponding tuple entry, bump the Compose `:-` default in
`docker-compose.yml` if the major changed, and verify the smoke job
passes against the new tag.

The matrix bound is the supported-major window, NOT a fixed "last N"
count. Today the window is ES 8.x+9.x, OpenSearch 2.x+3.x, Solr 9.x+10.x
yielding 2 entries per engine; when the adapter window changes the
matrix changes in lockstep.
"""

from typing import Final

ENGINE_VERSION_MATRIX: Final[dict[str, tuple[str, ...]]] = {
    "elasticsearch": ("9.4.1", "8.15.3"),  # latest patch of each supported major
    "opensearch":    ("3.6.0", "2.18.0"),
    "solr":          ("10.0",  "9.7"),
}
```

**Pydantic schemas**

N/A.

**Tasks**

1. Create [`backend/app/core/engine_versions.py`](../../../../../backend/app/core/engine_versions.py) with the constant + top-of-file maintainer-release-update comment block per FR-2. Use the exact key strings `"elasticsearch"`, `"opensearch"`, `"solr"` (verbatim match with `EngineTypeWire`).
2. Create [`backend/tests/unit/core/__init__.py`](../../../../../backend/tests/unit/core/__init__.py) if `backend/tests/unit/core/` does not exist yet (verify by `ls backend/tests/unit/core/`). The directory is a pytest collection point; `__init__.py` is empty.
3. Create [`backend/tests/unit/core/test_engine_versions_matrix.py`](../../../../../backend/tests/unit/core/test_engine_versions_matrix.py) with three tests:
   - `test_matrix_keys_match_engine_type_wire` — asserts `set(ENGINE_VERSION_MATRIX.keys()) == set(get_args(EngineTypeWire))`. Imports `EngineTypeWire` from `backend.app.api.v1.schemas`.
   - `test_matrix_values_are_nonempty_string_tuples` — asserts each value is `tuple[str, ...]` with `len > 0` (the `[0]` access in Story 1.5's CI guard would IndexError on an empty tuple).
   - `test_matrix_values_are_strings` — asserts every element of every tuple is `isinstance(str)`.
4. Run `make test-unit` and confirm the three new tests pass.

**Definition of Done**

- [ ] `backend/app/core/engine_versions.py` exists with the documented matrix + maintainer-release-update comment. [FR-2]
- [ ] `from backend.app.core.engine_versions import ENGINE_VERSION_MATRIX` resolves at import time (no module-load side effect).
- [ ] `ENGINE_VERSION_MATRIX["elasticsearch"][0] == "9.4.1"`, `…["opensearch"][0] == "3.6.0"`, `…["solr"][0] == "10.0"` (matches the Compose `:-` defaults from Story 1.1).
- [ ] Unit test `test_matrix_keys_match_engine_type_wire` passes. [AC-10]
- [ ] Unit tests `test_matrix_values_are_nonempty_string_tuples` + `test_matrix_values_are_strings` pass (regression backstop for Story 1.5).

### Story 1.3 — install.sh helper for `RELYLOOP_ES_VERSION` / `RELYLOOP_OS_VERSION` / `RELYLOOP_SOLR_VERSION`

**Outcome:** Operators set `RELYLOOP_ES_VERSION=8.15.3` in `.env` (or shell), `install.sh` validates it against `ENGINE_VERSION_MATRIX` BEFORE any `docker compose` call, exports `ES_IMAGE_TAG=8.15.3` on success, exits 1 with a clear stderr message on unknown values.

**New files**

| File | Purpose |
|---|---|
| [`scripts/lib/relyloop_engine_versions.sh`](../../../../../scripts/lib/relyloop_engine_versions.sh) | Defines `parse_relyloop_engine_versions`. Sourced (not exec'd) from `install.sh`. Reads `$RELYLOOP_ES_VERSION` / `$RELYLOOP_OS_VERSION` / `$RELYLOOP_SOLR_VERSION` independently. For each set non-empty var, reads the matrix values from a sourceable bash data file (Task 1) and validates. Exports `ES_IMAGE_TAG` / `OS_IMAGE_TAG` / `SOLR_IMAGE_TAG` on success. Returns 1 on unknown — bubbles to `exit 1` under `install.sh`'s `set -e`. |
| [`scripts/lib/relyloop_engine_versions_matrix.sh`](../../../../../scripts/lib/relyloop_engine_versions_matrix.sh) | A pure-bash mirror of `ENGINE_VERSION_MATRIX` — three space-separated string lists declared as bash variables. The Python constant is the source of truth; this file is generated/checked by Story 1.5's CI guard so backend and bash never drift. (Bash 3.2 on macOS does not have associative arrays, hence three variables instead of one map.) |
| [`scripts/ci/test_parse_relyloop_engine_versions.sh`](../../../../../scripts/ci/test_parse_relyloop_engine_versions.sh) | Bash unit test for `parse_relyloop_engine_versions`. Mirrors `scripts/ci/test_parse_relyloop_engines.sh`. ~12 cases: unset → no export; each engine's valid values → matching `*_IMAGE_TAG` export; whitespace tolerance; unknown value → rc=1 + stderr; multiple vars set independently; empty string treated as unset (matches Phase 1 convention). |

**Modified files**

| File | Change |
|---|---|
| [`scripts/install.sh`](../../../../../scripts/install.sh) | After the existing `parse_relyloop_engines` invocation at [line 118](../../../../../scripts/install.sh#L118), source `scripts/lib/relyloop_engine_versions.sh` and call `parse_relyloop_engine_versions`. Add a comment block above mirroring lines 96-117's documentation style. Position: BEFORE `docker compose config --quiet` at line 121 (the engine selection is resolved first → version selection second → then Compose validates the final composition). |
| [`.github/workflows/pr.yml`](../../../../../.github/workflows/pr.yml) | At the same job that invokes `scripts/ci/test_parse_relyloop_engines.sh` (find it via `grep -n test_parse_relyloop_engines pr.yml`), add a sibling step invoking `scripts/ci/test_parse_relyloop_engine_versions.sh`. |

**Endpoints**

N/A.

**Key interfaces**

```bash
# scripts/lib/relyloop_engine_versions.sh — new helper
parse_relyloop_engine_versions() {
  # Sources the matrix data:
  source "${REPO_ROOT}/scripts/lib/relyloop_engine_versions_matrix.sh"
  # Now $ES_VERSIONS = "9.4.1 8.15.3"; $OS_VERSIONS = "3.6.0 2.18.0"; $SOLR_VERSIONS = "10.0 9.7"

  _validate_one() {
    local var_name="$1"   # e.g. "RELYLOOP_ES_VERSION"
    local input="${!var_name:-}"   # bash indirect read
    [[ -z "$input" ]] && return 0  # unset / empty → no export, Compose default applies
    local engine_label="$2"        # e.g. "elasticsearch" (for error message)
    local allowed_list="$3"        # e.g. "$ES_VERSIONS"
    local export_var="$4"          # e.g. "ES_IMAGE_TAG"
    for v in $allowed_list; do
      if [[ "$input" == "$v" ]]; then
        export "$export_var"="$input"
        echo "RelyLoop: pinning $engine_label to $input"
        return 0
      fi
    done
    echo "Unknown $engine_label version '$input'. Allowed: ${allowed_list// /, }." >&2
    return 1
  }

  _validate_one RELYLOOP_ES_VERSION   elasticsearch "$ES_VERSIONS"   ES_IMAGE_TAG   || return 1
  _validate_one RELYLOOP_OS_VERSION   opensearch    "$OS_VERSIONS"   OS_IMAGE_TAG   || return 1
  _validate_one RELYLOOP_SOLR_VERSION solr          "$SOLR_VERSIONS" SOLR_IMAGE_TAG || return 1
}
```

```bash
# scripts/lib/relyloop_engine_versions_matrix.sh — generated from the Python source
# Source of truth: backend/app/core/engine_versions.py ENGINE_VERSION_MATRIX
# Drift guarded by scripts/ci/verify_engine_version_matrix_parity.sh (Story 1.5).
ES_VERSIONS="9.4.1 8.15.3"
OS_VERSIONS="3.6.0 2.18.0"
SOLR_VERSIONS="10.0 9.7"
```

**Pydantic schemas**

N/A.

**Tasks**

1. Create [`scripts/lib/relyloop_engine_versions_matrix.sh`](../../../../../scripts/lib/relyloop_engine_versions_matrix.sh) with the three `*_VERSIONS` variables, values matching `ENGINE_VERSION_MATRIX` from Story 1.2 verbatim. Include the source-of-truth comment at top.
2. Create [`scripts/lib/relyloop_engine_versions.sh`](../../../../../scripts/lib/relyloop_engine_versions.sh) with the `parse_relyloop_engine_versions` function. Follow the style of [`scripts/lib/relyloop_engines.sh`](../../../../../scripts/lib/relyloop_engines.sh) — SPDX header, top-of-file rationale comment, `# shellcheck source=…` directive on the matrix source line, the bash-3.2-safe `${arr[@]+"${arr[@]}"}` form per CLAUDE.md "Working in sibling worktrees" footnote.
3. Edit [`scripts/install.sh`](../../../../../scripts/install.sh) — after line 118 (existing `parse_relyloop_engines`), add a new comment block (mirror lines 96-117) + `source "${REPO_ROOT}/scripts/lib/relyloop_engine_versions.sh"` + `parse_relyloop_engine_versions`. Verify with shellcheck that the new section parses cleanly.
4. Create [`scripts/ci/test_parse_relyloop_engine_versions.sh`](../../../../../scripts/ci/test_parse_relyloop_engine_versions.sh) by copying the structure of [`scripts/ci/test_parse_relyloop_engines.sh`](../../../../../scripts/ci/test_parse_relyloop_engines.sh). Replace the per-case logic to exercise the new helper. Required cases (assert via the same `expect_ok` / `expect_fail` shape as Phase 1):
   - **unset_all** — all three vars unset → all three `*_IMAGE_TAG` vars stay unset → rc=0.
   - **es_valid_latest** — `RELYLOOP_ES_VERSION=9.4.1` → `ES_IMAGE_TAG=9.4.1` exported → rc=0.
   - **es_valid_older_major** — `RELYLOOP_ES_VERSION=8.15.3` → `ES_IMAGE_TAG=8.15.3` exported → rc=0.
   - **os_valid_latest** / **os_valid_older_major** — same pattern for OS (`3.6.0`, `2.18.0`).
   - **solr_valid_latest** / **solr_valid_older_major** — same pattern for Solr (`10.0`, `9.7`).
   - **es_unknown** — `RELYLOOP_ES_VERSION=9.9.9` → rc=1, stderr contains `Unknown elasticsearch version '9.9.9'. Allowed: 9.4.1, 8.15.3.`, `ES_IMAGE_TAG` NOT exported.
   - **os_unknown** / **solr_unknown** — same pattern.
   - **mixed_one_unknown** — `RELYLOOP_ES_VERSION=9.4.1 RELYLOOP_OS_VERSION=2.0.0` → rc=1 (first failure short-circuits per the helper's `|| return 1` chain), stderr contains the OS error message. Document the short-circuit explicitly in the helper's top-of-file rationale.
   - **empty_string_treated_as_unset** — `RELYLOOP_ES_VERSION=""` → no export, rc=0. (Matches Phase 1 convention.)
   - **all_three_valid** — all three vars set to valid latest values → all three `*_IMAGE_TAG` exports → rc=0.
5. Edit [`.github/workflows/pr.yml`](../../../../../.github/workflows/pr.yml) — find the existing step invoking `scripts/ci/test_parse_relyloop_engines.sh` (grep target: `grep -n test_parse_relyloop_engines pr.yml`) and add an adjacent step running the new test script.
6. Run all tests locally: `bash scripts/ci/test_parse_relyloop_engine_versions.sh` and confirm 0 failures.

**Definition of Done**

- [ ] `scripts/lib/relyloop_engine_versions.sh` exists; defines `parse_relyloop_engine_versions`; sourceable without side effects; passes shellcheck. [FR-3]
- [ ] `scripts/lib/relyloop_engine_versions_matrix.sh` exists; values match `ENGINE_VERSION_MATRIX` from Story 1.2 verbatim. [FR-3]
- [ ] `scripts/install.sh` sources the new helper and calls `parse_relyloop_engine_versions` AFTER `parse_relyloop_engines` and BEFORE `docker compose config --quiet`. [FR-4]
- [ ] `RELYLOOP_ES_VERSION=8.15.3 bash scripts/install.sh` (with `RELYLOOP_SKIP_BUILD=1` to keep the test bounded) → `ES_IMAGE_TAG=8.15.3` propagates into the Compose environment (manual smoke; verified by `docker compose config | grep elasticsearch:`). [AC-2]
- [ ] `RELYLOOP_ES_VERSION=9.9.9 bash scripts/install.sh` → exits 1 before any `docker compose pull` / `docker compose up`; stderr contains the documented error message. [AC-3]
- [ ] `scripts/ci/test_parse_relyloop_engine_versions.sh` passes locally (12 cases listed above, 0 failures).
- [ ] `pr.yml` runs `scripts/ci/test_parse_relyloop_engine_versions.sh` in the same job as `test_parse_relyloop_engines.sh`.

### Story 1.4 — `.env.example` documentation block

**Outcome:** Operators discover the new env vars + matrix values + back-compat-by-default behavior from `.env.example`.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`.env.example`](../../../../../.env.example) | After the existing "Selective engine startup" block ([line 147](../../../../../.env.example#L147)), add a new "Selecting an engine version" block. Comment style mirrors the existing block (long-form rationale + commented-out examples). Documents the three env vars, the allowed-values pointer (`backend/app/core/engine_versions.py`), the matrix values, the back-compat default, and the matrix-Compose-default sync invariant. |

**Endpoints / Key interfaces / Pydantic schemas**

N/A.

**Tasks**

1. Read [`.env.example:109-147`](../../../../../.env.example#L109-L147) (the existing "Selective engine startup" block) end-to-end so the new block matches its tone.
2. Append a new block immediately after line 147 with the following structure:
   ```dotenv
   # --- Selecting an engine version ----------------------------------------
   #
   # Pin one or more engines to a specific supported version at install time.
   # Useful when evaluating RelyLoop against the version your production
   # cluster runs (e.g. an ES 8.x cluster being migrated from). Default
   # unset → the matrix's latest-major default applies, identical to
   # today's behavior.
   #
   # Allowed values per engine, see backend/app/core/engine_versions.py
   # ENGINE_VERSION_MATRIX:
   #   elasticsearch: 9.4.1, 8.15.3
   #   opensearch:    3.6.0, 2.18.0
   #   solr:          10.0,  9.7
   #
   # Matrix bound is the adapter compatibility window per
   # docs/01_architecture/adapters.md (ES 8.x+9.x, OpenSearch 2.x+3.x,
   # Solr 9.x+10.x). Out-of-window tags are rejected at install.sh BEFORE
   # any `docker compose pull`.
   #
   # Examples:
   #   RELYLOOP_ES_VERSION=8.15.3   # ES 8.x evaluator path
   #   RELYLOOP_OS_VERSION=2.18.0   # OpenSearch 2.x evaluator path
   #   RELYLOOP_SOLR_VERSION=9.7    # Solr 9.x evaluator path
   #
   # The matrix's first entry per engine is the Compose default — keep
   # the matrix and the docker-compose.yml `${X_IMAGE_TAG:-<default>}`
   # literals in sync. CI guard at scripts/ci/verify_engine_version_matrix_parity.sh
   # enforces this on every PR.
   # RELYLOOP_ES_VERSION=8.15.3
   # RELYLOOP_OS_VERSION=2.18.0
   # RELYLOOP_SOLR_VERSION=9.7
   ```
3. Run the existing `.env.example` filename CI guard locally (`bash scripts/ci/check-no-env-files.sh` against the modified tree) to confirm the file naming convention is intact.

**Definition of Done**

- [ ] `.env.example` contains a "Selecting an engine version" block immediately after the existing "Selective engine startup" block. [FR-10, AC-14]
- [ ] The block lists all three env vars with matrix-allowed values per engine.
- [ ] The block names `backend/app/core/engine_versions.py` as the source of truth.
- [ ] The block states the back-compat default behavior.
- [ ] `.env*` filename CI guard green on the modified tree.

### Story 1.5 — CI guard for matrix-Compose-default sync + matrix-bash-mirror parity

**Outcome:** Two CI guards run on every PR. Guard 1 fails if `ENGINE_VERSION_MATRIX[<engine>][0]` drifts from `docker-compose.yml`'s `${X_IMAGE_TAG:-<default>}` literal. Guard 2 fails if the bash mirror `scripts/lib/relyloop_engine_versions_matrix.sh` drifts from the Python source.

**New files**

| File | Purpose |
|---|---|
| [`scripts/ci/verify_engine_version_matrix_parity.sh`](../../../../../scripts/ci/verify_engine_version_matrix_parity.sh) | Two-part guard: (a) parse `ENGINE_VERSION_MATRIX` from `backend/app/core/engine_versions.py` via a small Python one-liner (`python3 -c 'from backend.app.core.engine_versions import *; …'`); compare `[0]` element of each tuple to the `${X_IMAGE_TAG:-<default>}` literal grepped from `docker-compose.yml`; exit 1 on drift. (b) parse the bash mirror values; compare to the Python values; exit 1 on drift. Output the drifted pair on failure for fast diagnosis. |
| [`scripts/ci/test_verify_engine_version_matrix_parity.sh`](../../../../../scripts/ci/test_verify_engine_version_matrix_parity.sh) | Tests the guard itself. Three cases: (a) clean tree → guard exits 0; (b) injected Compose-default drift → guard exits 1 with the named pair; (c) injected bash-mirror drift → guard exits 1 with the named pair. Uses temp-dir scratch copies of the relevant files; never mutates the real tree. |

**Modified files**

| File | Change |
|---|---|
| [`.github/workflows/pr.yml`](../../../../../.github/workflows/pr.yml) | Add a new job step in the same job that runs `verify_install_builds_all_services.sh` (find via `grep -n verify_install_builds_all_services pr.yml`). The step invokes `bash scripts/ci/verify_engine_version_matrix_parity.sh`. Add a second adjacent step running `bash scripts/ci/test_verify_engine_version_matrix_parity.sh` so the guard itself is regression-tested on every PR. |

**Endpoints / Key interfaces / Pydantic schemas**

N/A.

**Tasks**

1. Write `scripts/ci/verify_engine_version_matrix_parity.sh`. Approximate shape:
   ```bash
   #!/usr/bin/env bash
   set -euo pipefail
   REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

   # Part (a): matrix[0] ↔ docker-compose.yml `:-` default sync.
   python3 -c '
   from backend.app.core.engine_versions import ENGINE_VERSION_MATRIX
   for engine, versions in ENGINE_VERSION_MATRIX.items():
       print(f"{engine} {versions[0]}")
   ' | while read -r engine default; do
     # Map engine name → Compose image-line pattern + var name.
     case "$engine" in
       elasticsearch) pattern='elasticsearch:\${ES_IMAGE_TAG:-' ;;
       opensearch)    pattern='opensearchproject/opensearch:\${OS_IMAGE_TAG:-' ;;
       solr)          pattern='solr:\${SOLR_IMAGE_TAG:-' ;;
       *) echo "Unknown engine '$engine' in matrix" >&2; exit 1 ;;
     esac
     # Look for `${ES_IMAGE_TAG:-9.4.1}` (or equivalent) in docker-compose.yml.
     if ! grep -qE "${pattern}${default}\}" docker-compose.yml; then
       echo "MATRIX-COMPOSE DRIFT: $engine matrix[0]='$default' but docker-compose.yml does not contain '${pattern}${default}}'." >&2
       exit 1
     fi
   done

   # Part (b): bash mirror ↔ Python source sync.
   # Parse the bash file's three variables; compare to the Python matrix.
   # Implementation: source the bash file in a subshell so its variables don't leak, dump them, then compare.
   ( set +u
     source "${REPO_ROOT}/scripts/lib/relyloop_engine_versions_matrix.sh"
     printf 'elasticsearch %s\n' "$ES_VERSIONS"
     printf 'opensearch %s\n' "$OS_VERSIONS"
     printf 'solr %s\n' "$SOLR_VERSIONS"
   ) | python3 -c '
   import sys
   from backend.app.core.engine_versions import ENGINE_VERSION_MATRIX
   for line in sys.stdin:
       engine, *versions = line.strip().split()
       python_vals = list(ENGINE_VERSION_MATRIX[engine])
       if versions != python_vals:
           print(f"BASH-MIRROR DRIFT: {engine} bash={versions} python={python_vals}", file=sys.stderr)
           sys.exit(1)
   '
   echo "OK — matrix-Compose defaults and bash mirror in sync."
   ```
2. Write `scripts/ci/test_verify_engine_version_matrix_parity.sh`. Pattern: copy the verify script + the three input files (`docker-compose.yml`, `scripts/lib/relyloop_engine_versions_matrix.sh`, `backend/app/core/engine_versions.py`) to `mktemp -d` working trees, mutate one of them per case, run the guard, assert rc + stderr. Mirror the structure of [`scripts/ci/test_verify_openapi_snapshot_fresh.sh`](../../../../../scripts/ci/test_verify_openapi_snapshot_fresh.sh) for the mktemp scaffolding.
3. Add the two `pr.yml` steps. Verify by re-reading the workflow diff that they run on every PR (not gated by `SMOKE_TEST` or similar).
4. Test locally: clean tree → both guards rc=0. Inject a one-character drift in `engine_versions.py` → guard a exits 1. Revert. Inject a drift in `relyloop_engine_versions_matrix.sh` → guard b exits 1. Revert.

**Definition of Done**

- [ ] `scripts/ci/verify_engine_version_matrix_parity.sh` exists and is executable (`chmod +x`). [FR-11]
- [ ] Guard exits 0 against a clean tree.
- [ ] Guard exits 1 with a named drift message when `ENGINE_VERSION_MATRIX[<engine>][0]` is mutated without bumping the Compose `:-` default. [AC-4]
- [ ] Guard exits 1 with a named drift message when the bash mirror diverges from the Python source.
- [ ] `scripts/ci/test_verify_engine_version_matrix_parity.sh` exists and passes locally.
- [ ] `pr.yml` runs both scripts on every PR (no `SMOKE_TEST` gate).

### Epic 1 gate

- [ ] Stories 1.1 through 1.5 complete.
- [ ] AC-1, AC-2, AC-3, AC-4, AC-10, AC-14 satisfied.
- [ ] `make test-unit` green (no regressions; 3 new tests from Story 1.2 + the bash unit test suite from Story 1.3 + Story 1.5).
- [ ] `make lint && make typecheck` green.
- [ ] Manual smoke: `RELYLOOP_ES_VERSION=8.15.3 make up` boots ES 8.15.3 (verified via `docker compose config` output AND running container's `/` reports `version.number == "8.15.3"`).

---

## Epic 2 — Backend capability extension (sibling probe + endpoint field)

**Outcome:** A new `is_engine_reachable_with_version` sibling probe returns `(reachable, version)` without modifying the existing `is_engine_reachable`. The `_test/demo/engines` capability endpoint returns the version field. The OpenAPI snapshot is regenerated.

### Story 2.1 — `is_engine_reachable_with_version` sibling probe

**Outcome:** A new function alongside `is_engine_reachable` returns `(reachable: bool, version: str | None)`. ES/OS parse the same GET `/` body as the existing reachability check; Solr delegates to `probe_capabilities()`. The existing function is not modified.

**New files**

| File | Purpose |
|---|---|
| [`backend/tests/unit/services/test_is_engine_reachable_with_version.py`](../../../../../backend/tests/unit/services/test_is_engine_reachable_with_version.py) | Unit tests for the new sibling. Mocks `httpx.AsyncClient` (or uses `pytest-httpx`'s `httpx_mock`) and `SolrAdapter.probe_capabilities`. Cases listed under Tasks → DoD below. |

**Modified files**

| File | Change |
|---|---|
| [`backend/app/services/demo_seeding.py`](../../../../../backend/app/services/demo_seeding.py) | Add a new async function `is_engine_reachable_with_version` immediately after the existing `is_engine_reachable` (after line 506). New function has its own docstring referencing the `is_engine_reachable` totality contract. Existing function is NOT touched. |

**Endpoints**

N/A.

**Key interfaces**

```python
# backend/app/services/demo_seeding.py — new sibling function
async def is_engine_reachable_with_version(
    engine_base_url: str,
    engine_type: _EngineType,
    *,
    timeout_s: float = 2.0,
) -> tuple[bool, str | None]:
    """Return (reachable, version) for an engine. Total — no exception propagates.

    Sibling of `is_engine_reachable`; same probe paths and totality contract,
    but additionally parses the engine's reported version number.

    - ES/OS: GET `/` -> validates `version.number` is a str, returns it.
    - Solr: delegates to a one-shot `SolrAdapter.probe_capabilities()`.

    Any failure (timeout, non-200, malformed body, missing field) returns
    (False, None) — except: a reachable engine with a malformed/missing
    `version.number` returns (True, None) so the operator can still see
    that the engine answered (even if RelyLoop can't tell what it is).
    The WARN log shape mirrors `is_engine_reachable`'s existing
    `demo_reseed_engine_probe_failed` extra dict.
    """
```

**Pydantic schemas**

N/A.

**Tasks**

1. Read [`backend/app/services/demo_seeding.py:467-506`](../../../../../backend/app/services/demo_seeding.py#L467-L506) so the new function matches the existing function's docstring + WARN-log shape + httpx timeout pattern exactly.
2. Add the new function immediately after `is_engine_reachable`. The probe body for ES/OS:
   ```python
   try:
       async with httpx.AsyncClient(timeout=timeout_s) as client:
           response = await client.get(f"{engine_base_url}/")
           if response.status_code != 200:
               return False, None
           body = response.json()
           # ES/OS reachability check (same as is_engine_reachable's "version" in body).
           if "version" not in body:
               return False, None
           version_block = body.get("version")
           if not isinstance(version_block, dict):
               return True, None  # reachable but malformed shape
           number = version_block.get("number")
           if not isinstance(number, str):
               return True, None  # reachable but version.number missing or wrong type
           return True, number
   except Exception as exc:  # noqa: BLE001 — total
       logger.warning(
           "demo_reseed_engine_probe_failed",
           extra={
               "engine_type": engine_type,
               "engine_base": engine_base_url,
               "error_type": type(exc).__name__,
               "probe": "is_engine_reachable_with_version",
           },
       )
       return False, None
   ```
   The `"probe": "is_engine_reachable_with_version"` log field disambiguates this WARN from the existing `is_engine_reachable` WARN — useful when an operator greps for probe failures and wants to know which probe failed.
3. For Solr, delegate to `SolrAdapter.probe_capabilities()`:
   ```python
   if engine_type == "solr":
       try:
           from backend.app.adapters.solr import SolrAdapter
           adapter = SolrAdapter(base_url=engine_base_url, ...)  # minimal stub — see existing adapter init
           result = await asyncio.wait_for(adapter.probe_capabilities(), timeout=timeout_s)
           return True, result.version  # ProbeResult.version is str
       except Exception:
           # Any failure (including unsupported version raising) is "unreachable".
           return False, None
   ```
   Note: the existing `is_engine_reachable` for Solr uses GET `/solr/admin/info/system` directly without instantiating an adapter. Read [`solr.py`](../../../../../backend/app/adapters/solr.py)'s adapter init signature first; if instantiation requires fields we don't have at this call site (e.g. `auth_config`), fall back to direct GET against `/solr/admin/info/system` and parse `lucene.solr-spec-version` (the Solr response shape). The capability-probe delegation is the preferred path but is NOT a hard requirement — the spec's FR-6 says "delegate" but if instantiation is too heavy, direct GET is acceptable (document the choice in the function's docstring).
4. Create [`backend/tests/unit/services/test_is_engine_reachable_with_version.py`](../../../../../backend/tests/unit/services/test_is_engine_reachable_with_version.py). Required cases (target ≥8):
   - **es_happy_path** — mock GET `/` returns 200 + `{"name": "node-1", "version": {"number": "9.4.1"}}` → returns `(True, "9.4.1")`, no WARN log.
   - **os_happy_path** — same shape for opensearch → `(True, "3.6.0")`.
   - **solr_happy_path** — mock `probe_capabilities()` returns `ProbeResult(version="10.0.0", …)` → `(True, "10.0.0")`. (If Story 2.1 task 3 falls back to direct GET, mock the GET response instead.)
   - **reachable_but_version_missing** — 200 with body `{"name": "node-1"}` (no `version` field) → `(False, None)` (matches `is_engine_reachable`'s strictness: no version field = not a real engine).
   - **reachable_but_version_block_not_dict** — 200 with `{"version": "string-not-dict"}` → `(True, None)` + WARN. (Reachable but malformed — operator sees the engine answered.)
   - **reachable_but_version_number_missing** — 200 with `{"version": {"build_flavor": "default"}}` → `(True, None)` + WARN. [AC-7]
   - **reachable_but_version_number_not_str** — 200 with `{"version": {"number": 9.4}}` (numeric) → `(True, None)` + WARN.
   - **http_500** — non-200 response → `(False, None)` + WARN.
   - **timeout** — `httpx.TimeoutException` → `(False, None)` + WARN.
   - **connection_refused** — `httpx.ConnectError` → `(False, None)` + WARN.
   - **solr_probe_unreachable** — `SolrAdapter.probe_capabilities()` raises → `(False, None)`.
   The WARN-shape assertion uses `caplog` (or the project's `structlog_capture` fixture if it exists per the parent plan).
5. Confirm `is_engine_reachable` is untouched: `git diff backend/app/services/demo_seeding.py` shows ONLY the new function added — no changes to the existing function's signature, body, or docstring. [AC-11]
6. Run the existing reachability tests at [`backend/tests/unit/services/test_demo_seeding_engine_reachability.py`](../../../../../backend/tests/unit/services/test_demo_seeding_engine_reachability.py) — they MUST pass without modification.

**Definition of Done**

- [ ] `is_engine_reachable_with_version` defined in `demo_seeding.py` immediately after the existing function. [FR-6]
- [ ] Function signature: `async def is_engine_reachable_with_version(engine_base_url: str, engine_type: _EngineType, *, timeout_s: float = 2.0) -> tuple[bool, str | None]`.
- [ ] Existing `is_engine_reachable` is byte-identical (verified by `git diff`). [AC-11]
- [ ] Existing tests at `test_demo_seeding_engine_reachability.py` pass without modification. [AC-11]
- [ ] All 10+ cases in `test_is_engine_reachable_with_version.py` pass. [AC-7]
- [ ] `make test-unit` green; `make typecheck` green (the tuple return type is correctly annotated).

### Story 2.2 — `DemoEngineStatus.version` field + capability endpoint integration

**Outcome:** `GET /api/v1/_test/demo/engines` returns the `version` field on every row. The OpenAPI snapshot includes the field. The frontend `DemoEngineStatus` type regenerates with the field.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`backend/app/api/v1/_test.py`](../../../../../backend/app/api/v1/_test.py) | At line 812, extend `DemoEngineStatus` with `version: str | None = None`. At line 858-878 (the `demo_engines` handler), replace the `asyncio.gather(*(is_engine_reachable(url, et) …))` call with `is_engine_reachable_with_version(url, et)` and construct each row with the version. |
| [`backend/tests/integration/test_demo_engines_capability.py`](../../../../../backend/tests/integration/test_demo_engines_capability.py) | Extend with two new cases: (a) all three engines reachable → all three rows have non-null `version`; (b) one engine unreachable (mocked) → that row has `version: null` + the others still have populated versions. |
| [`backend/tests/contract/test_openapi_surface.py`](../../../../../backend/tests/contract/test_openapi_surface.py) | At line 397, extend `test_demo_engines_response_shape` to assert `version` is in `row_props` AND its OpenAPI shape is string-or-null (`anyOf: [{type: string}, {type: null}]` OR the equivalent `type: string` + `nullable: true` depending on the FastAPI version's emission style — check what the regenerated snapshot produces). |
| [`ui/openapi.json`](../../../../../ui/openapi.json) | Regenerated via `bash scripts/regen-generated-artifacts.sh`. Will include the new `version` field on `DemoEngineStatus`. NOT a hand-edit. |
| [`ui/src/lib/types.ts`](../../../../../ui/src/lib/types.ts) | Regenerated from `ui/openapi.json` via `pnpm types:gen` (part of `regen-generated-artifacts.sh`). NOT a hand-edit. |
| [`ui/src/lib/api/demo-engines.ts`](../../../../../ui/src/lib/api/demo-engines.ts) | At line 38, extend the `DemoEngineStatus` interface with `version: string | null;`. This is the hand-maintained mirror of the regenerated OpenAPI type used by the React Query hook — keep it in sync with the generated `types.ts`. (If the existing `DemoEngineStatus` interface in `demo-engines.ts` is already generated from `types.ts`, this step is unnecessary; verify by reading the file.) |

**Endpoints**

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `GET` | `/api/v1/_test/demo/engines` | (existing endpoint, response extended) Returns `{engines: [{engine_type, reachable, version: str|null}, …]}`. Always 200. Gated by `_require_development_env`. | (none — total handler) |

**Key interfaces**

```python
# backend/app/api/v1/_test.py — extended Pydantic model
class DemoEngineStatus(BaseModel):
    """Per-engine reachability + version snapshot for the reset-modal checkbox group."""

    model_config = ConfigDict(extra="forbid")

    engine_type: EngineTypeWire
    reachable: bool
    version: str | None = None  # NEW — engine's self-reported version.number (ES/OS) or probe_capabilities().version (Solr). None when unreachable or version probe failed.
```

```python
# backend/app/api/v1/_test.py — handler now calls the sibling probe
async def demo_engines() -> DemoEnginesResponse:
    resolved = [(et, _resolve_engine_base_url(url)) for et, url in _DEMO_ENGINE_PROBE_URLS]
    results = await asyncio.gather(
        *(is_engine_reachable_with_version(url, et) for et, url in resolved)
    )
    return DemoEnginesResponse(
        engines=[
            DemoEngineStatus(engine_type=et, reachable=ok, version=ver)
            for (et, _), (ok, ver) in zip(resolved, results, strict=True)
        ]
    )
```

**Pydantic schemas**

Already covered above. `DemoEnginesResponse` is unchanged (its `engines` field is `list[DemoEngineStatus]`, which transitively includes the new `version`).

**Tasks**

1. Read [`backend/app/api/v1/_test.py:812-878`](../../../../../backend/app/api/v1/_test.py#L812-L878) end-to-end before editing.
2. Extend `DemoEngineStatus` at line 812 with `version: str | None = None`. Update the docstring to mention the new field.
3. Replace the handler body at line 866-878 to call `is_engine_reachable_with_version` and construct each `DemoEngineStatus` with the version. Import the new function at the top of the file alongside the existing `is_engine_reachable` import.
4. Read [`backend/tests/integration/test_demo_engines_capability.py`](../../../../../backend/tests/integration/test_demo_engines_capability.py) to understand the existing test fixtures (engine mocking pattern, dev-env override, etc.).
5. Add two new test cases to `test_demo_engines_capability.py`:
   - **test_all_engines_reachable_returns_version** — mock all three probes to return `(True, "<version>")`; assert each row has the expected version string.
   - **test_unreachable_engine_returns_null_version** — mock OS probe to return `(False, None)`; assert the OS row has `reachable=False` and `version=None`; assert the ES + Solr rows still have non-null versions.
6. Extend [`backend/tests/contract/test_openapi_surface.py:397-428`](../../../../../backend/tests/contract/test_openapi_surface.py#L397-L428). After line 415 (the existing `engine_type` / `reachable` assertion), add:
   ```python
   assert "version" in row_props, "DemoEngineStatus.version missing from OpenAPI schema"
   version_prop = row_props["version"]
   # FastAPI emits Optional[str] as anyOf:[{type:'string'}, {type:'null'}] OR
   # as nullable:true depending on its OpenAPI version setting. Tolerate both shapes:
   is_nullable_string = (
       (version_prop.get("type") == "string" and version_prop.get("nullable") is True)
       or any(
           t.get("type") in ("string", "null") for t in version_prop.get("anyOf", [])
       )
   )
   assert is_nullable_string, f"DemoEngineStatus.version is not nullable-string: {version_prop!r}"
   ```
7. Run `bash scripts/regen-generated-artifacts.sh` to regenerate `ui/openapi.json` + `ui/src/lib/types.ts`. Confirm the diff includes the new `version` field on `DemoEngineStatus`.
8. If [`ui/src/lib/api/demo-engines.ts:38`](../../../../../ui/src/lib/api/demo-engines.ts#L38) maintains a hand-maintained `DemoEngineStatus` interface (not auto-generated), extend it with `version: string | null;`. Read the file first to determine whether it's generated or hand-maintained.
9. Run the freshness gate locally: `bash scripts/ci/verify_openapi_snapshot_fresh.sh` — must pass after step 7.
10. Run the contract + integration tests: `make test-contract && make test-integration` — must pass.

**Definition of Done**

- [ ] `DemoEngineStatus.version` field added with `str | None = None` default. [FR-7]
- [ ] `demo_engines` handler calls `is_engine_reachable_with_version`, NOT `is_engine_reachable`. [FR-8]
- [ ] `DemoEnginesResponse` shape includes the `version` field on every row (verified by integration tests). [AC-5, AC-6]
- [ ] Integration test asserts `version` is populated when reachable, null when unreachable. [AC-5, AC-6]
- [ ] Integration test asserts `version` is null when reachable-but-version-malformed (uses the case from Story 2.1's `reachable_but_version_number_missing`). [AC-7]
- [ ] Contract test `test_demo_engines_response_shape` asserts `version` is present + nullable-string. [AC-15]
- [ ] `ui/openapi.json` regenerated; includes `version` field on `DemoEngineStatus`. [AC-12]
- [ ] `ui/src/lib/types.ts` regenerated (via `pnpm types:gen`); contains `version?: string | null` (or equivalent) on the generated `DemoEngineStatus` type.
- [ ] `verify_openapi_snapshot_fresh.sh` passes on the modified tree. [AC-12]
- [ ] Existing reset modal still renders (the Phase 1 React Query hook tolerates the new optional field per `extra="forbid"` semantics — verified by `cd ui && pnpm test` against the existing modal tests).

### Epic 2 gate

- [ ] Stories 2.1 + 2.2 complete.
- [ ] AC-5, AC-6, AC-7, AC-11, AC-12, AC-15 satisfied.
- [ ] `make test-unit && make test-integration && make test-contract` green.
- [ ] `cd ui && pnpm typecheck && pnpm test` green (the existing modal tests must still pass — the type extension is back-compat).
- [ ] `bash scripts/regen-generated-artifacts.sh` produces no further diffs (idempotent).

---

## Epic 3 — Frontend (matrix mirror + reset modal version annotation)

**Outcome:** The frontend has a typed mirror of `ENGINE_VERSION_MATRIX` for future use; the reset-to-demo modal renders the detected version inline next to each engine checkbox label.

### Story 3.1 — Frontend `ENGINE_VERSION_MATRIX` mirror in `enums.ts`

**Outcome:** `ui/src/lib/enums.ts` exports `ENGINE_VERSION_MATRIX` as `as const` with a source-of-truth comment; CI guards (`verify_enum_source_of_truth.sh` or a new sibling) enforce backend-frontend parity.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`ui/src/lib/enums.ts`](../../../../../ui/src/lib/enums.ts) | After line 44 (the existing `EngineType` export), add a new exported `ENGINE_VERSION_MATRIX` const with the same values as the backend. Pattern mirrors `ENGINE_TYPE_VALUES` exactly — `as const` + a `// Values must match backend/app/core/engine_versions.py ENGINE_VERSION_MATRIX` source-of-truth comment. |
| [`scripts/ci/verify_enum_source_of_truth.sh`](../../../../../scripts/ci/verify_enum_source_of_truth.sh) | Extend to scan for the new mirror. Add a case that parses `ENGINE_VERSION_MATRIX` from both files and compares. (Read the existing script's structure first — if it's pattern-based and already handles `as const` constants generically, no change is needed; if it's specific to `Literal[…]`/`as const` arrays, add a new case for dict-shaped mirrors. The decision is captured in Task 3.) |

**Endpoints / Key interfaces / Pydantic schemas**

N/A.

**Tasks**

1. Read [`ui/src/lib/enums.ts:42-44`](../../../../../ui/src/lib/enums.ts#L42-L44) to confirm the pattern.
2. Add the new mirror immediately after line 44:
   ```typescript
   // Values must match backend/app/core/engine_versions.py ENGINE_VERSION_MATRIX.
   // Matrix bound: one entry per supported major in the adapter compatibility
   // window (docs/01_architecture/adapters.md). When upstream releases a new
   // latest patch for a supported major, update the corresponding tuple AND
   // the Compose `${X_IMAGE_TAG:-<default>}` literal in docker-compose.yml in
   // the same PR. Drift guarded by scripts/ci/verify_engine_version_matrix_parity.sh.
   export const ENGINE_VERSION_MATRIX = {
     elasticsearch: ['9.4.1', '8.15.3'],
     opensearch:    ['3.6.0', '2.18.0'],
     solr:          ['10.0',  '9.7'],
   } as const;
   export type EngineVersion = (typeof ENGINE_VERSION_MATRIX)[EngineType][number];
   ```
3. Read [`scripts/ci/verify_enum_source_of_truth.sh`](../../../../../scripts/ci/verify_enum_source_of_truth.sh) end-to-end. Determine whether it's pattern-generic (in which case the new mirror is auto-covered) or per-symbol (in which case add a new case). Document the determination in the PR body.
   - **If pattern-generic** (it iterates over all `as const` exports in `enums.ts` and matches them to backend symbols): verify the new mirror is picked up by running `bash scripts/ci/verify_enum_source_of_truth.sh` locally — it should pass against the synced state.
   - **If per-symbol**: add a new check for `ENGINE_VERSION_MATRIX` that compares the TS const to the Python dict. Use `python3 -c 'from backend.app.core.engine_versions import ENGINE_VERSION_MATRIX; …'` + a node/ts-node one-liner (or just regex-extract the `as const` object literal from `enums.ts`) and diff.
4. Confirm the existing Story 1.5 guard (`verify_engine_version_matrix_parity.sh`) ALREADY catches the bash-mirror drift; this story's guard covers the *frontend* mirror, not the bash mirror. Two distinct sync points: (Python ↔ Compose default), (Python ↔ bash mirror), (Python ↔ frontend mirror).

**Definition of Done**

- [ ] `ui/src/lib/enums.ts` exports `ENGINE_VERSION_MATRIX` with values verbatim matching the backend constant. [FR-5]
- [ ] Source-of-truth comment present and names `backend/app/core/engine_versions.py ENGINE_VERSION_MATRIX`.
- [ ] `verify_enum_source_of_truth.sh` (or sibling) passes against the synced state.
- [ ] Mutating a value in the frontend mirror without a backend change causes the guard to fail (verified locally — revert after). [AC-13]
- [ ] Mutating a value in the backend without a frontend change causes the guard to fail (verified locally — revert after). [AC-13]
- [ ] `cd ui && pnpm typecheck` green (the new `as const` constant and `EngineVersion` type compile).

### Story 3.2 — Reset modal renders version annotation

**Outcome:** When the capability response includes a non-null `version`, the modal renders the engine label as `Elasticsearch — 9.4.1` (em-dash + muted text). When `version` is null, the label renders as today (`Elasticsearch`). The interactive checkbox semantics are unchanged.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/dashboard/reset-demo-state-button.tsx`](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx) | In the engine-checkbox-group block (search for `data-testid="reset-demo-state-engines"` — verified at the spec's audit table to be around line 267), modify each engine label rendering to conditionally append the version annotation. Use the existing capability data (`enginesQuery.data`) — no new fetch. |
| [`ui/src/components/dashboard/__tests__/reset-demo-state-button.test.tsx`](../../../../../ui/src/components/dashboard/__tests__/reset-demo-state-button.test.tsx) | Add three new test cases for the version annotation rendering. (If the test file does not exist yet, create it following the vitest pattern of sibling tests in `ui/src/components/dashboard/__tests__/`.) |

**Endpoints / Key interfaces / Pydantic schemas**

N/A.

**Tasks**

1. Read [`ui/src/components/dashboard/reset-demo-state-button.tsx`](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx) end-to-end (~460 LOC). Locate the checkbox-group block (`data-testid="reset-demo-state-engines"` around line 267) and the existing engine-label rendering inside the per-engine map.
2. The capability response shape (`enginesQuery.data.engines[i].version`) is now `string | null`. Extract a helper:
   ```typescript
   function renderEngineLabel(engine: DemoEngineStatus): React.ReactNode {
     const label = ENGINE_DISPLAY_LABELS[engine.engine_type];  // existing const at line 37 — 'Elasticsearch' | 'OpenSearch' | 'Apache Solr'
     if (engine.version == null) return label;
     return (
       <>
         {label}
         <span className="text-muted-foreground text-xs ml-1">— {engine.version}</span>
       </>
     );
   }
   ```
   Apply inside the existing `.map((e) => …)` for the checkbox rendering. Keep all existing prop/state logic untouched — no new state, no new hook.
3. Add three vitest cases to `reset-demo-state-button.test.tsx`:
   - **renders_version_annotation_when_present** — mocks `useDemoEnginesCapability` to return `{data: {engines: [{engine_type: 'elasticsearch', reachable: true, version: '9.4.1'}, …]}}`; opens the modal; asserts the DOM contains `Elasticsearch — 9.4.1` (text via `screen.getByText` with a regex or composite text matcher).
   - **omits_version_annotation_when_null** — mocks the same hook to return `version: null` for one engine; asserts the engine's label renders as plain `Elasticsearch` (no em-dash, no version string).
   - **omits_version_annotation_during_capability_load** — mocks the hook to return `{data: null, isLoading: true}`; opens the modal; asserts NO version annotation is rendered for any engine (matches today's pre-load behavior).
4. Run `cd ui && pnpm test reset-demo-state-button` — all old + new tests pass.

**Definition of Done**

- [ ] `reset-demo-state-button.tsx` renders `<engine label> — <version>` (em-dash + muted text) when the capability response includes a non-null `version`. [FR-9, AC-8]
- [ ] When `version` is null, label renders as today (engine label only, no annotation). [AC-9]
- [ ] Pre-load state (`enginesQuery.data == null`) renders no version annotations (existing behavior preserved).
- [ ] No new state variable, no new hook, no new API call introduced — the change is rendering-only.
- [ ] All three new vitest cases pass; all existing modal tests still pass. [AC-8, AC-9]
- [ ] `cd ui && pnpm lint && pnpm typecheck` green.

### Epic 3 gate

- [ ] Stories 3.1 + 3.2 complete.
- [ ] AC-8, AC-9, AC-13 satisfied.
- [ ] `cd ui && pnpm test` green (vitest, including new cases).
- [ ] Manual smoke: open the reset modal in a running stack; observe the engine labels render `Elasticsearch — 9.4.1` / `OpenSearch — 3.6.0` / `Apache Solr — <version>` (operator confirms in PR body screenshot or note).

---

## Epic 4 — Documentation

**Outcome:** Operators discover the new env vars from `local-dev.md`; the matrix is documented in `deployment.md`; the adapter doc cross-links to the matrix; the maintainer release-update process is named in `CONTRIBUTING.md`.

### Story 4.1 — Docs: local-dev + deployment + adapters cross-link + CONTRIBUTING

**Outcome:** All five doc surfaces named in spec §15 are updated.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| [`docs/03_runbooks/local-dev.md`](../../../../03_runbooks/local-dev.md) | After the existing "Selecting a subset of engines" section ([line 108](../../../../03_runbooks/local-dev.md#L108)), add a new "Selecting an engine version" subsection. Mirror the existing section's structure: 3-line intro, copy-pasteable `echo … >> .env` example, link to the matrix file, "DX hazard" note about Compose's `${X:-default}` fallback. |
| [`docs/01_architecture/deployment.md`](../../../../01_architecture/deployment.md) | Add an "Engine version matrix" block in the engine-services section. List the three engines, their supported majors per `adapters.md`, current matrix values, and a one-paragraph maintainer-release-update note. Cross-link to `backend/app/core/engine_versions.py`. |
| [`docs/01_architecture/adapters.md`](../../../../01_architecture/adapters.md) | Add a one-line cross-link in each engine's compatibility section: "See [`deployment.md` §Engine version matrix](deployment.md) for the curated install-time version matrix." |
| [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md) | Add a one-line pointer in the maintainer section (or a new "Engine version matrix" subsection): "When upstream releases a new latest patch for a supported major, update the matrix at `backend/app/core/engine_versions.py` per the in-file comment block; the CI guard at `scripts/ci/verify_engine_version_matrix_parity.sh` enforces sync with the Compose defaults and the bash mirror." |

**Endpoints / Key interfaces / Pydantic schemas**

N/A.

**Tasks**

1. Read [`docs/03_runbooks/local-dev.md:108-130`](../../../../03_runbooks/local-dev.md#L108-L130) (the existing "Selecting a subset of engines" section) end-to-end so the new section matches its tone.
2. Add the "Selecting an engine version" subsection. Reference structure:
   ```markdown
   ## Selecting an engine version

   By default `make up` boots each engine at the matrix's latest-major default
   tag (`elasticsearch:9.4.1` / `opensearchproject/opensearch:3.6.0` /
   `solr:10.0`). To pin an engine to a different supported version — e.g. an
   older ES 8.x when evaluating against a cluster you're migrating from —
   set the corresponding `RELYLOOP_*_VERSION` env var to a value listed
   in [`backend/app/core/engine_versions.py`](../../../backend/app/core/engine_versions.py) `ENGINE_VERSION_MATRIX`:

   ```bash
   echo "RELYLOOP_ES_VERSION=8.15.3" >> .env   # ES 8.x evaluator path
   make up
   ```

   Allowed values per engine (current matrix):

   | Engine | Supported majors | Allowed values |
   |---|---|---|
   | Elasticsearch | 8.x, 9.x | `9.4.1`, `8.15.3` |
   | OpenSearch | 2.x, 3.x | `3.6.0`, `2.18.0` |
   | Solr | 9.x, 10.x | `10.0`, `9.7` |

   Unknown values are rejected at `install.sh` BEFORE any `docker compose pull`:

   ```
   Unknown elasticsearch version '9.5.0'. Allowed: 9.4.1, 8.15.3.
   ```

   **DX hazard: don't run `docker compose up -d` directly.** `make up` reads
   `RELYLOOP_*_VERSION` and translates them into `*_IMAGE_TAG` exports for
   Compose's `${X_IMAGE_TAG:-<default>}` substitution. Running `docker compose up -d`
   directly skips the validation and won't honor the `RELYLOOP_*_VERSION` vars
   — you'd need to set `ES_IMAGE_TAG` / `OS_IMAGE_TAG` / `SOLR_IMAGE_TAG` explicitly.
   Same DX hazard pattern as the "Selecting a subset of engines" section above.
   ```
3. Read the existing engine-services section of [`docs/01_architecture/deployment.md`](../../../../01_architecture/deployment.md). Add a new "Engine version matrix" block following it. Reference structure:
   ```markdown
   ### Engine version matrix

   RelyLoop ships a maintainer-curated `ENGINE_VERSION_MATRIX` at
   [`backend/app/core/engine_versions.py`](../../../backend/app/core/engine_versions.py)
   listing the supported install-time engine versions. The matrix bound is the
   adapter compatibility window documented in [`adapters.md`](adapters.md):
   one entry per supported major per engine (latest patch). Operators select
   a version via `RELYLOOP_ES_VERSION` / `RELYLOOP_OS_VERSION` / `RELYLOOP_SOLR_VERSION`
   at install time — see the
   [runbook](../03_runbooks/local-dev.md) for usage.

   | Engine | Supported majors (adapters.md) | Matrix values | Compose default |
   |---|---|---|---|
   | Elasticsearch | 8.11+, 9.x | `9.4.1`, `8.15.3` | `9.4.1` |
   | OpenSearch | 2.x, 3.x | `3.6.0`, `2.18.0` | `3.6.0` |
   | Solr | 9.x, 10.x | `10.0`, `9.7` | `10.0` |

   **Maintainer release-update process.** When upstream releases a new latest
   patch for a supported major, update the matrix at `engine_versions.py`,
   bump the Compose `${X_IMAGE_TAG:-<default>}` literal in `docker-compose.yml`
   if the major changed, regenerate the bash mirror at
   `scripts/lib/relyloop_engine_versions_matrix.sh`, and verify the smoke job
   passes against the new tag. The CI guard at
   `scripts/ci/verify_engine_version_matrix_parity.sh` enforces sync between
   the three places on every PR.
   ```
4. Add the cross-links in [`docs/01_architecture/adapters.md`](../../../../01_architecture/adapters.md) near each engine's compatibility section. Verify by `grep -n 'See \[`deployment.md`' adapters.md` shows three matches (one per engine).
5. Edit [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md). If there's an existing "Maintainer" or "Release management" section, add the pointer there. Otherwise add a new "Engine version matrix" subsection near the bottom (post-release-notes section).
6. Run `make pre-commit` to confirm the docs pass the markdown / link-check hooks.

**Definition of Done**

- [ ] `docs/03_runbooks/local-dev.md` has a "Selecting an engine version" subsection immediately after "Selecting a subset of engines". [FR-12]
- [ ] `docs/01_architecture/deployment.md` has an "Engine version matrix" block listing the supported majors, values, and Compose defaults. [FR-12]
- [ ] `docs/01_architecture/adapters.md` cross-links to the deployment.md block for each engine. [FR-12]
- [ ] `CONTRIBUTING.md` names the maintainer release-update process and the CI guard. [FR-12]
- [ ] `make pre-commit` passes on the modified tree (markdown/link checks).
- [ ] `state.md` updated to note this work shipped (handled at finalization, not in this story; called out here for awareness).

### Epic 4 gate

- [ ] Story 4.1 complete.
- [ ] All five doc files updated.
- [ ] Pre-commit hooks green.

---

## UI Guidance

(Required because Story 3.2 has frontend scope.)

### Reference: current component structure

[`ui/src/components/dashboard/reset-demo-state-button.tsx`](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx) is ~460 LOC, structured as:

- Lines 1-50: imports + type imports including `useDemoEnginesCapability` (capability hook) and `DemoEngineStatus`.
- Lines 32-41: human-friendly engine label constants (`ENGINE_DISPLAY_LABELS` const at line 37, mapping `'elasticsearch'` → `'Elasticsearch'` etc.).
- Lines 60-150: component body — state hooks (open dialog, user selection set), `useDemoEnginesCapability` query, effects for default selection from capability data.
- Lines 200-260: dialog wrapper + content layout.
- Lines 262-300: the engine checkbox group (`data-testid="reset-demo-state-engines"`) — the insertion target for this work.
- Lines 300-460: confirm/cancel buttons, partial-completion footer, loading/error states.

### Insertion point

Inside the existing `.map((e) => …)` in the checkbox group (around line 280-295). Each iteration renders:
- The `<input type="checkbox">` with the existing handlers (untouched).
- A `<label>` whose text is currently `ENGINE_LABELS[e.engine_type]`. **This is the only line that changes** — replace the bare label text with the new `renderEngineLabel(e)` helper.

### Analogous markup patterns

Pattern for muted-text inline annotation: search for `text-muted-foreground` in `ui/src/components/dashboard/` to find existing in-file usage of muted secondary text. Existing analog: the partial-completion footer in the same file renders subdued reason text in `text-muted-foreground text-xs` — the exact classes this work reuses.

Exact JSX inside the `.map` body — copy-paste (verify the actual `htmlFor`/`id` convention against the existing component before applying; the existing rendering uses the standard shadcn `<Label>` + `<Checkbox>` composition):

```tsx
<label htmlFor={`reset-engine-${e.engine_type}`} className="cursor-pointer">
  {ENGINE_DISPLAY_LABELS[e.engine_type]}
  {e.version != null && (
    <span className="text-muted-foreground text-xs ml-1">— {e.version}</span>
  )}
</label>
```

### Layout and structure

- Each row stays a single line: `[checkbox] [Label] — [version]`.
- The version annotation is inline next to the label, NOT on a new line.
- Disabled rows (unreachable engines) keep their existing visual treatment; the version annotation is absent for them (because `version == null`) — no extra disabled styling needed for the annotation.
- Mobile layout: the label + version annotation wrap together; if the row's width is constrained, the version annotation wraps as part of the label text. No special breakpoint logic.

### Confirmation/modal dialog pattern

N/A — no new dialog. Existing modal from Phase 1 is the host; this work modifies the in-modal checkbox list.

### Visual consistency table

| New UI element | Tailwind classes / pattern source | Notes |
|---|---|---|
| Version annotation `<span>` | `text-muted-foreground text-xs ml-1` | Matches the existing partial-completion footer's muted-text style in the same file. |
| Em-dash separator (`—`) | Literal Unicode em-dash inside the `<span>` | NOT a `<Separator>` component — the annotation is inline text. |

### Component composition

Inline. The `renderEngineLabel` helper is defined at module scope inside `reset-demo-state-button.tsx` (NOT extracted to a sibling file) because it's tightly coupled to the modal's existing `DemoEngineStatus` type and `ENGINE_LABELS` const, and it's only ever called from one render site.

### Interaction behavior table

| User action | Frontend behavior | API call |
|---|---|---|
| Operator opens reset modal | `useDemoEnginesCapability` fires (Phase 1, unchanged); on data return, each engine row's label renders with version annotation if `version != null`. | `GET /api/v1/_test/demo/engines` (Phase 1, unchanged endpoint — extended response in Story 2.2). |
| Operator clicks an engine checkbox | Existing `toggleEngine` handler (unchanged); the version annotation is purely decorative — clicking the annotation toggles the checkbox (it's inside the `<label>`). | None. |
| Capability response fails / times out | Existing pre-load state renders; engine labels show without annotation (the existing error/fallback rendering is untouched). | None. |

### Handler function patterns

No new handlers. The version annotation is a render-time computation only — no state, no event, no effect.

### Information architecture placement

No navigation change. The modal stays where it is (home dashboard `/` → "Reset to demo state" button). The version annotation is informational; it does NOT add a new entry point or change discoverability.

### Tooltips and contextual help

The spec §11 tooltip inventory says no in-app tooltips are required for this feature (the version IS the info). The relevant glossary keys remain `engine.elasticsearch`, `engine.opensearch`, `engine.solr` (existing).

| Element | Tooltip / help text | Trigger | Placement | Glossary key | Source-of-truth comment | Markup pattern |
|---|---|---|---|---|---|---|
| Version annotation `<span>` | (none — the version string IS self-explanatory) | N/A | N/A | N/A | N/A | (no tooltip JSX) |

### Legacy behavior parity

N/A — no component is deleted or replaced; the change is a 1-line modification to the existing label rendering. The Story 3.2 task list lists the exact line that changes, no behaviors to preserve.

### Client-side persistence

N/A — no `localStorage` / `sessionStorage` involvement.

---

## 3) Testing workstream

### 3.1 Unit tests

| Test file | Owning story | Cases | Spec ACs |
|---|---|---|---|
| `backend/tests/unit/core/test_engine_versions_matrix.py` (new) | Story 1.2 | 3: matrix-key sync, nonempty tuples, str values | AC-10 |
| `backend/tests/unit/services/test_is_engine_reachable_with_version.py` (new) | Story 2.1 | 10+: happy paths per engine, malformed shapes, HTTP errors, timeouts | AC-7, AC-11 |
| `backend/tests/unit/services/test_demo_seeding_engine_reachability.py` (existing — unchanged) | Story 2.1 | Existing cases pass without modification | AC-11 |

### 3.2 Integration tests

| Test file | Owning story | Cases | Spec ACs |
|---|---|---|---|
| `backend/tests/integration/test_demo_engines_capability.py` (extend) | Story 2.2 | 2 new: all-reachable-with-version, one-unreachable-null-version | AC-5, AC-6 |

### 3.3 Contract tests

| Test file | Owning story | Cases | Spec ACs |
|---|---|---|---|
| `backend/tests/contract/test_openapi_surface.py` (extend `test_demo_engines_response_shape`) | Story 2.2 | 1 new assertion: `version` field present + nullable-string | AC-12, AC-15 |

### 3.4 E2E tests

No new E2E test files. Rationale:
- The reset modal's version annotation is a render-only change, fully covered by the vitest component tests in Story 3.2.
- The capability endpoint is dev-only (`_require_development_env`) — the existing Playwright E2E suite already exercises the reset flow via `demo-ubi.spec.ts` (CI-excluded from smoke per state.md's note, but available locally).
- An E2E case asserting the version annotation in the modal would duplicate the vitest coverage in Story 3.2 with no additional confidence.

### 3.5 Migration verification

**N/A — no migration.** Alembic head stays `0023_proposals_superseded_status`.

### 3.6 CI gates

| Gate | Story | Behavior |
|---|---|---|
| `verify_engine_version_matrix_parity.sh` (new) | Story 1.5 | Fails on matrix-Compose-default drift OR Python-bash mirror drift. |
| `test_verify_engine_version_matrix_parity.sh` (new) | Story 1.5 | Self-test for the guard. |
| `test_parse_relyloop_engine_versions.sh` (new) | Story 1.3 | 12 bash unit-test cases. |
| `verify_enum_source_of_truth.sh` (extend) | Story 3.1 | Catches frontend mirror drift. |
| `verify_openapi_snapshot_fresh.sh` (existing) | Story 2.2 | Fails if `ui/openapi.json` is stale. |
| `verify_types_fresh.sh` (existing) | Story 2.2 | Fails if `ui/src/lib/types.ts` is stale. |
| `verify_install_builds_all_services.sh` (existing) | All | Existing CI guard — verifies the install path still resolves all services. |

### 3.5 Existing test impact audit

| Existing test | Impact | Action |
|---|---|---|
| `backend/tests/unit/services/test_demo_seeding_engine_reachability.py` | Existing `is_engine_reachable` is unchanged. | No modification. Tests must continue to pass. |
| `backend/tests/integration/test_demo_engines_capability.py` | Existing cases — adapted to include `version` field in their response assertions. Extended with 2 new cases. | Light modification — assertions gain a `version` field check; new cases added. |
| `backend/tests/contract/test_openapi_surface.py` | `test_demo_engines_response_shape` is extended with the version-field assertion. | Single-test extension. |
| `ui/src/components/dashboard/__tests__/` (existing modal tests, if present) | Modal renders one new annotation; existing checkbox/Confirm logic unchanged. | Verify existing tests still pass; new cases added in Story 3.2. |
| `scripts/ci/test_parse_relyloop_engines.sh` (existing Phase 1 bash test) | Helper unchanged. | No modification. |

---

## 4) Documentation update workstream

### 4.0 Core context files

| File | Change | Story |
|---|---|---|
| `state.md` | At finalization: add this feature to the "Last 5 merges" one-liner; refresh "Active feature" if it was set. | Finalization (post-merge), not Story 4.1. |
| `state_history.md` | Append the full merge narrative (newest-first). | Finalization. |
| `CLAUDE.md` | No new rules — the matrix and helper patterns reuse existing conventions (Enumerated Value Contract Discipline, `_FILE` secrets discipline N/A here). | No change. |

### 4.1 Architecture docs (`docs/01_architecture`)

| File | Change | Story |
|---|---|---|
| `deployment.md` | "Engine version matrix" block. | Story 4.1 |
| `adapters.md` | Cross-links from each engine's compatibility section. | Story 4.1 |

### 4.2 Product docs (`docs/02_product`)

No change.

### 4.3 Runbooks (`docs/03_runbooks`)

| File | Change | Story |
|---|---|---|
| `local-dev.md` | "Selecting an engine version" subsection. | Story 4.1 |

### 4.4 Security docs (`docs/04_security`)

No change — no new secret, no new data flow.

### 4.5 Quality docs (`docs/05_quality`)

No change — the new CI guards are documented inline in their scripts.

### Other

| File | Change | Story |
|---|---|---|
| `CONTRIBUTING.md` | Maintainer release-update pointer. | Story 4.1 |
| `.env.example` | "Selecting an engine version" block. | Story 1.4 |
| `backend/app/core/engine_versions.py` | Top-of-file maintainer-process comment. | Story 1.2 |

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

None planned. This feature is purely additive: no existing function signature changes, no existing endpoint shape changes (only an additive optional field), no existing migration changes.

### 5.2 Planned refactor tasks

None.

### 5.3 Refactor guardrails

- `is_engine_reachable`'s signature MUST remain `(url, engine_type) -> bool` (Story 2.1 DoD). The sibling function is additive only.
- The new `ENGINE_VERSION_MATRIX` constant uses the canonical engine-name keys (`elasticsearch` / `opensearch` / `solr`) from `EngineTypeWire`. No new local enum.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

- **Hard dependency on Phase 1 (shipped).** Reuses `RELYLOOP_ENGINES`, `EngineTypeWire`, `DemoEngineStatus`, `DemoEnginesResponse`, `GET /api/v1/_test/demo/engines`, the `parse_relyloop_engines` helper pattern, the reset-modal capability-fetch hook. All shipped via PR #548.
- **Adapter compatibility window** — bound by `docs/01_architecture/adapters.md`. If the adapter docs change, the matrix changes in lockstep.
- **Docker Hub image availability** — the matrix's listed tags must actually exist on Docker Hub. If a tag is yanked upstream, the smoke job will fail to pull and the regression surfaces immediately.

### Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Matrix drifts from Compose `:-` defaults | Medium (maintainer forgets to bump both) | Story 1.5 CI guard fails the PR on drift. |
| Python ↔ bash mirror drifts | Medium (two files to update) | Story 1.5 CI guard covers this too. |
| Backend ↔ frontend matrix drifts | Medium | Story 3.1 extends `verify_enum_source_of_truth.sh`. |
| ES/OS root-response shape changes upstream (`version.number` moves) | Low | The probe returns `(True, None)` when the field is missing — graceful degradation. Story 2.1 has explicit test cases for this. |
| Operator sets `RELYLOOP_ES_VERSION` to a matrix-valid tag that Docker Hub then yanks | Low | install.sh's validation passes; `docker pull` fails with a clear registry error. Surfaced to operator immediately. |
| Smoke job (when enabled) breaks because the matrix's latest-major tag is no longer pullable | Low | Same as above — smoke fails immediately; maintainer pins to the next stable patch. |
| Capability endpoint slowdown from the version-aware probe | Low | The version parse is an extra dict lookup in the SAME HTTP response body — no additional round-trip. Spec §13 documents this. |

### Failure mode catalog

| Failure | Symptom | Diagnosis | Recovery |
|---|---|---|---|
| Matrix value mistyped in `engine_versions.py` (e.g. `"9.4..1"`) | Story 1.2 unit test passes (value is a str), Story 1.5 CI guard fails: `MATRIX-COMPOSE DRIFT: elasticsearch matrix[0]='9.4..1' but docker-compose.yml does not contain …` | Read the guard's stderr — it names the drifted pair. | Fix the typo; re-push. |
| Bash mirror value mistyped | Story 1.5 CI guard fails: `BASH-MIRROR DRIFT: elasticsearch bash=['9.4.1', '8.15.2'] python=['9.4.1', '8.15.3']` | Read the guard's stderr — it names the divergence. | Fix the mirror; re-push. |
| install.sh helper accepts an unknown value silently | Story 1.3 bash test case `es_unknown` fails | Read the test's stderr — it expected rc=1 and the documented error message. | Fix the helper's allowlist comparison. |
| ES probe response shape unexpected | Story 2.1 test case `reachable_but_version_block_not_dict` exercises this — returns `(True, None)` with a WARN log | Operator sees the modal labels render without versions; checks the API logs. | Capture the actual response shape in a bug report; revisit the probe's parsing logic. |
| Frontend modal renders raw "undefined" instead of omitting the annotation | Story 3.2 vitest cases catch this | Check the conditional rendering in `renderEngineLabel` — must guard `engine.version != null`, NOT `engine.version` (the latter would match an empty string and the former matches null/undefined). | Fix the condition; re-run vitest. |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1 (infra) sequentially** — Stories 1.1 → 1.2 → 1.3 → 1.4 → 1.5. Story 1.5's CI guard depends on Stories 1.1 and 1.2 (it cross-checks them). Story 1.3 depends on Story 1.2 (the bash mirror must match the Python matrix).
2. **Epic 2 (backend) sequentially** — Story 2.1 → Story 2.2. Story 2.2 calls the function from Story 2.1.
3. **Epic 3 (frontend) parallel where possible** — Story 3.1 can land before or after Story 2.2 (it doesn't depend on the backend endpoint shape). Story 3.2 depends on Story 2.2 (it consumes the new `version` field on the response).
4. **Epic 4 (docs) at the end** — the doc tables cite the matrix values + the CI guards, which must exist first.

### Parallelization opportunities

- Stories 1.2 + 1.3 can be written in parallel by different agents (the Python constant and the bash helper are independent); the integration point is Story 1.5's CI guard which lands after both.
- Story 3.1 is independent of Epic 2 and can land in parallel with Epic 2.
- Story 4.1 (docs) is independent of Epic 2 and Epic 3's implementation and can be drafted as soon as Story 1.5 is complete (the matrix values are stable by then).

For an `/impl-execute --all` run by a single agent, the sequential order above is the safe choice: each story's DoD references files from earlier stories, and each epic gate is a hard stop.

---

## 8) Rollout and cutover plan

- **Feature flags / staged rollout:** None. Purely additive — default unset → today's behavior.
- **Migration/backfill:** None. Alembic head unchanged.
- **Image-tag changes are immediate** — operators who set `RELYLOOP_ES_VERSION=8.15.3` on their next `make up` get the new tag. No reseed required (the engine container is replaced; the persistent `./data/elasticsearch` volume stays unless the operator did `make reset`). Upgrade safety is the operator's call against the engine vendor's documented upgrade path — out of scope per spec §3.
- **Operational readiness gates:** Story 1.5's CI guards + Story 2.1's totality contract are the regression guards. Both fire on every PR.
- **Release gate:** Standard `pr.yml` checks green. Smoke job stays OFF by default per state.md.

---

## 9) Execution tracker

### Current sprint

- [ ] Story 1.1 — Compose engine services accept image-tag env vars
- [ ] Story 1.2 — `ENGINE_VERSION_MATRIX` constant + matrix-key sync unit test
- [ ] Story 1.3 — install.sh helper for `RELYLOOP_*_VERSION`
- [ ] Story 1.4 — `.env.example` documentation block
- [ ] Story 1.5 — CI guard for matrix-Compose-default sync
- [ ] Epic 1 gate
- [ ] Story 2.1 — `is_engine_reachable_with_version` sibling probe
- [ ] Story 2.2 — `DemoEngineStatus.version` field + capability endpoint
- [ ] Epic 2 gate
- [ ] Story 3.1 — Frontend `ENGINE_VERSION_MATRIX` mirror
- [ ] Story 3.2 — Reset modal version annotation
- [ ] Epic 3 gate
- [ ] Story 4.1 — Docs
- [ ] Epic 4 gate
- [ ] Final cross-model review (Gemini Code Assist at PR stage; GPT-5.5 final review if reachable, else Opus self-review per CLAUDE.md fallback)
- [ ] Merge

### Blocked items

None.

### Done this sprint

(Populated as stories complete.)

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

For each story, before marking complete, the agent must verify:

| Gate | Story 1.1 | Story 1.2 | Story 1.3 | Story 1.4 | Story 1.5 | Story 2.1 | Story 2.2 | Story 3.1 | Story 3.2 | Story 4.1 |
|---|---|---|---|---|---|---|---|---|---|---|
| New files exist at the documented paths | N/A | ✓ | ✓ | N/A | ✓ | ✓ | N/A | N/A | N/A | N/A |
| Modified files compile (`make lint && make typecheck`) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | N/A |
| Unit tests pass (`make test-unit`) | N/A | ✓ | (bash test) | N/A | ✓ | ✓ | ✓ | N/A | (vitest) | N/A |
| Integration tests pass (`make test-integration`) | N/A | N/A | N/A | N/A | N/A | N/A | ✓ | N/A | N/A | N/A |
| Contract tests pass (`make test-contract`) | N/A | N/A | N/A | N/A | N/A | N/A | ✓ | N/A | N/A | N/A |
| Vitest passes (`cd ui && pnpm test`) | N/A | N/A | N/A | N/A | N/A | N/A | ✓ | ✓ | ✓ | N/A |
| OpenAPI snapshot fresh | N/A | N/A | N/A | N/A | N/A | N/A | ✓ | N/A | N/A | N/A |
| Enum source-of-truth gate passes | N/A | N/A | N/A | N/A | N/A | N/A | N/A | ✓ | N/A | N/A |
| Matrix parity gate passes | N/A | ✓ | ✓ | N/A | ✓ | N/A | N/A | ✓ | N/A | N/A |
| Manual smoke verified | N/A | N/A | ✓ | N/A | N/A | N/A | N/A | N/A | ✓ | N/A |
| Docs pre-commit passes | N/A | N/A | N/A | ✓ | N/A | N/A | N/A | N/A | N/A | ✓ |

---

## 11) Plan consistency review (required before execution)

| Check | Status | Notes |
|---|---|---|
| Every FR has a row in §1 traceability table | ✓ | FR-1 through FR-12 listed. |
| Every FR is assigned to at least one story | ✓ | 12 FRs across 10 stories. |
| Every endpoint in spec §8.1 appears in exactly one story's endpoint table | ✓ | One endpoint (`GET /api/v1/_test/demo/engines`) appears in Story 2.2's table. |
| Every error code in spec §8.5 appears in a contract test task | N/A | Spec §8.5 lists no new API error codes (bash exit-code only). Story 1.3 covers the bash exit-code path. |
| Every AC has at least one DoD reference | ✓ | AC-1 through AC-15 cited across the DoDs. AC-1 (Story 1.1 + Epic 1 gate manual smoke), AC-2 (1.1, 1.3), AC-3 (1.3), AC-4 (1.1, 1.5), AC-5 (2.2), AC-6 (2.2), AC-7 (2.1, 2.2), AC-8 (3.2), AC-9 (3.2), AC-10 (1.2), AC-11 (2.1), AC-12 (2.2), AC-13 (3.1), AC-14 (1.4), AC-15 (2.2). |
| Test files in §3 are each assigned to exactly one owning story | ✓ | One column per test file; no orphans. |
| Epic gate arithmetic matches actual story count | ✓ | Epic 1 gate covers 5 stories; Epic 2 covers 2; Epic 3 covers 2; Epic 4 covers 1. Plan total: 10 stories. |
| All open questions from spec §19 resolved | ✓ | Spec §19 reports no open questions — three forks locked at preflight. |
| Frontend UI Guidance section complete | ✓ | Story 3.2 is the only frontend story; UI Guidance section above covers insertion point, analogous markup, layout, interaction table, handler patterns, info architecture, tooltips (N/A justified), legacy-behavior-parity (N/A justified — no delete), client-side persistence (N/A). |
| Enumerated value contracts verified | ✓ | Spec §8.4 lists every contract; the values match `ENGINE_VERSION_MATRIX` in `backend/app/core/engine_versions.py` (Story 1.2). Story 3.1 mirrors in frontend with source-of-truth comment. |
| Audit-event coverage | N/A | No state-mutating endpoint added. Spec §6 audit events are N/A; capability endpoint is read-only, install.sh is pre-API. |
| Alembic head verified | ✓ | `0023_proposals_superseded_status` (from `ls migrations/versions/ | sort | tail -1`). No migration in this plan. |
| Modified file existence verified | ✓ | All modified files exist (verified during spec drafting): `docker-compose.yml`, `scripts/install.sh`, `.env.example`, `.github/workflows/pr.yml`, `backend/app/services/demo_seeding.py`, `backend/app/api/v1/_test.py`, `backend/tests/integration/test_demo_engines_capability.py`, `backend/tests/contract/test_openapi_surface.py`, `ui/openapi.json`, `ui/src/lib/types.ts`, `ui/src/lib/api/demo-engines.ts`, `ui/src/lib/enums.ts`, `ui/src/components/dashboard/reset-demo-state-button.tsx`, `scripts/ci/verify_enum_source_of_truth.sh`, `docs/03_runbooks/local-dev.md`, `docs/01_architecture/deployment.md`, `docs/01_architecture/adapters.md`, `CONTRIBUTING.md`. |
| Migration verification N/A | ✓ | No migration. |
| Deferred phases tracked | ✓ | Single-phase per spec §3. No deferred phases → no `phase2_idea.md`. |

---

## 12) Definition of plan done

This plan is ready for execution (`/impl-execute --all`) when:

- [x] All 12 FRs from the spec map to at least one story in §1.
- [x] All 15 ACs are referenced in at least one story's DoD.
- [x] Single endpoint surface (`GET /api/v1/_test/demo/engines`) appears in exactly one endpoint table.
- [x] All modified files verified to exist.
- [x] Alembic head verified (no migration in this plan).
- [x] UI Guidance section complete with copy-pasteable JSX.
- [x] §11 Plan consistency review all green.
- [x] No deferred phases without tracking artifacts (single-phase, none deferred).
- [x] Cross-model review completed (Opus self-review per CLAUDE.md fallback; Gemini Code Assist remains the live cross-family gate at the PR stage).
