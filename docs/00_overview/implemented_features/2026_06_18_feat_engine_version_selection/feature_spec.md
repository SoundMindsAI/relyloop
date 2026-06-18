# Feature Specification — Engine Version Selection at Install Time

**Date:** 2026-06-17
**Status:** Draft
**Owners:** Product: relevance engineer (operator persona). Engineering: maintainer.
**Cross-model review:** Opus self-review (GPT-5.5 unreachable in Claude Code remote sandbox per CLAUDE.md "Environment-aware fallback"; Gemini Code Assist remains the cross-family gate at the code/PR stage).
**Related docs:**
- [idea.md](idea.md) — origin brief (preflighted 2026-06-17; priority reset from `Backlog` to `P1` per operator confirmation)
- Parent shipped feature: [`feat_selective_engine_startup_and_demo` feature_spec.md](../../../implemented_features/2026_06_17_feat_selective_engine_startup_and_demo/feature_spec.md) (PR #548, merged 2026-06-17) — provides `RELYLOOP_ENGINES`, `COMPOSE_PROFILES`, `GET /api/v1/_test/demo/engines`, `DemoEngineStatus`, the reset-modal checkbox group, the `parse_relyloop_engines` helper this work mirrors
- [docs/01_architecture/adapters.md](../../../../01_architecture/adapters.md) — engine compatibility window (ES 8.11+/9.x, OpenSearch 2.x/3.x, Solr 9.x/10.x) — the supported-major window is the bound for the curated matrix
- [docs/01_architecture/deployment.md](../../../../01_architecture/deployment.md) — Compose engine services + `RELYLOOP_ENGINES` integration
- [docs/03_runbooks/local-dev.md](../../../../03_runbooks/local-dev.md) — `make up` quickstart + "Selecting a subset of engines"
- [docs/01_architecture/api-conventions.md](../../../../01_architecture/api-conventions.md) — error envelope, routing

---

## 1) Purpose

**Problem.** RelyLoop hardcodes one image tag per engine in [`docker-compose.yml`](../../../../../docker-compose.yml) — `elasticsearch:9.4.1` at [line 340](../../../../../docker-compose.yml#L340), `opensearchproject/opensearch:3.6.0` at [line 368](../../../../../docker-compose.yml#L368), `solr:10.0` at [line 407](../../../../../docker-compose.yml#L407). Only `BASE_REGISTRY`, `ES_HEAP_SIZE`, and `SOLR_HEAP_SIZE` are env-parameterized today; the image tags themselves are not. An operator who wants to evaluate RelyLoop against a different ES version — e.g. an 8.x cluster they're migrating from, or a 9.5 patch they're piloting — must hand-edit Compose. That's an evaluation/adoption gap, not polish: RelyLoop should not assume every customer runs the latest tag.

**Outcome.** `RELYLOOP_ES_VERSION=8.15.3 make up` boots Elasticsearch 8.15.3 instead of 9.4.1. The same pattern works for `RELYLOOP_OS_VERSION` and `RELYLOOP_SOLR_VERSION`. Allowed values are a maintainer-curated `ENGINE_VERSION_MATRIX` — one entry per *supported major* in the adapter compatibility window, which today yields exactly 2 entries per engine. Unknown values are rejected at install.sh *before* any `docker compose` call (mirroring Phase 1's `RELYLOOP_ENGINES` discipline). The reset-to-demo modal renders the *detected* version inline next to each engine label, read-only, so the operator can see at a glance which version is running. Default unset → today's behavior preserved exactly (the latest-major pins remain the Compose defaults).

**Non-goal.** Switching engine versions from the browser. Engine versions are a Compose / install-time concern; the API container has no Docker socket and no authority to pull images or restart engine services. Per-minor version selection within a single major is also out of scope — the adapter behaves identically across minors, so offering 9.4.1 *and* 9.3.2 *and* 9.2.x would be pure maintenance cost (a row update per minor per engine) for zero operator value. The matrix offers one *latest patch* per supported major.

## 2) Current state audit

### Existing implementations

| File / artifact | What it does today | API / interface | Notes |
|---|---|---|---|
| [docker-compose.yml:330-339](../../../../../docker-compose.yml#L330-L339) | `elasticsearch` service, `profiles: ["es"]`, hardcoded `image: ${BASE_REGISTRY:-}elasticsearch:9.4.1`. | Compose | Image tag is the literal `9.4.1` — no env-var interpolation. `BASE_REGISTRY` is the only existing prefix knob. |
| [docker-compose.yml:364-379](../../../../../docker-compose.yml#L364-L379) | `opensearch` service, `profiles: ["os"]`, hardcoded `image: ${BASE_REGISTRY:-}opensearchproject/opensearch:3.6.0`. | Compose | Same pattern as ES — image tag literal. |
| [docker-compose.yml:403-418](../../../../../docker-compose.yml#L403-L418) | `solr` service, `profiles: ["solr"]`, hardcoded `image: ${BASE_REGISTRY:-}solr:10.0`. | Compose | Same pattern. |
| [scripts/install.sh:96-118](../../../../../scripts/install.sh#L96-L118) | Sources `scripts/lib/relyloop_engines.sh` and calls `parse_relyloop_engines` to translate `RELYLOOP_ENGINES` → `COMPOSE_PROFILES` BEFORE any `docker compose` call. Exits 1 on unknown engine. | Bash, sourced helper | The pre-validation discipline this work mirrors. Unknown values rejected before any image pull. |
| [scripts/lib/relyloop_engines.sh](../../../../../scripts/lib/relyloop_engines.sh) | `parse_relyloop_engines()` function — reads `$RELYLOOP_ENGINES`, validates against allowlist `{es, os, solr}`, deduplicates, exports `COMPOSE_PROFILES`. | Bash function | Pattern this spec extends with three sibling parsers, one per engine. |
| [scripts/ci/test_parse_relyloop_engines.sh](../../../../../scripts/ci/test_parse_relyloop_engines.sh) | 17-case unit test for the parser. Sourced from `pr.yml`'s `parse-relyloop-engines` lane. | Bash test | Test pattern this work mirrors for the new version parsers. |
| [backend/app/services/demo_seeding.py:467-506](../../../../../backend/app/services/demo_seeding.py#L467-L506) | `is_engine_reachable(url, engine_type) -> bool` — 2s-timeout GET probe. ES/OS validate `"version" in body`; Solr checks `responseHeader.status == 0` and `lucene` in body. | async function | Already reads the same `version` JSON the new sibling probe will parse — line 496 is the existing `"version" in body` check this work extends to read `body["version"]["number"]`. |
| [backend/app/api/v1/_test.py:812-826](../../../../../backend/app/api/v1/_test.py#L812-L826) | `DemoEngineStatus` Pydantic model (`engine_type`, `reachable`). `DemoEnginesResponse` wraps `engines: list[DemoEngineStatus]`. | Pydantic, `extra="forbid"` | Adding `version: str | None = None` is a back-compat extension — `extra="forbid"` rejects unknown fields *on input*, not on output emission, and existing consumers ignoring an unrecognized field is the standard JSON-API back-compat path. |
| [backend/app/api/v1/_test.py:842-878](../../../../../backend/app/api/v1/_test.py#L842-L878) | `GET /api/v1/_test/demo/engines` — probes ES/OS/Solr concurrently via `asyncio.gather`, returns 200 with per-engine reachability. Always returns 200 (unreachable engines surface as `reachable=false`, not as errors). | FastAPI route, `_require_development_env` gate | Same handler this work extends to include the version field. |
| [backend/app/adapters/solr.py:80](../../../../../backend/app/adapters/solr.py#L80) | `SOLR_MIN_VERSION` constant; runtime-enforced at [`solr.py:585`](../../../../../backend/app/adapters/solr.py#L585) — aborts probe below the floor. | Constant + version comparator | The supported-major window is enforced for Solr; ES/OS have no equivalent runtime floor. The curated matrix is the *only* validation gate for ES/OS, so its bound must match the documented adapter window. |
| [backend/app/adapters/solr.py:470](../../../../../backend/app/adapters/solr.py#L470) | `probe_capabilities()` — returns `ProbeResult` with a structured version field. | async method | Solr already has the version-report this work adds for ES/OS. The new sibling probe delegates to Solr's existing probe rather than re-parsing. |
| [backend/app/api/v1/schemas.py:315](../../../../../backend/app/api/v1/schemas.py#L315) | `EngineTypeWire = Literal["elasticsearch", "opensearch", "solr"]` — the canonical backend allowlist. | Pydantic Literal | The matrix keys are the *display* engine names (`elasticsearch` / `opensearch` / `solr`) — same as `EngineTypeWire`. |
| [ui/src/lib/enums.ts:42-44](../../../../../ui/src/lib/enums.ts#L42-L44) | `ENGINE_TYPE_VALUES = ['elasticsearch', 'opensearch', 'solr'] as const` — frontend mirror of `EngineTypeWire`, with the source-of-truth comment. | TS `as const` array | Pattern the new `ENGINE_VERSION_MATRIX` mirror follows: top-level `as const` + a `// Values must match backend/app/core/engine_versions.py ENGINE_VERSION_MATRIX` comment. |
| [ui/src/components/dashboard/reset-demo-state-button.tsx](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx) | Reset-to-demo modal. Calls `useDemoEnginesCapability` to fetch reachability and renders a checkbox per engine. Component already wired to the capability response shape. | React component | Adds a small `<span>` next to each engine label rendering the detected `version` when present. Pre-load and "version unavailable" states reuse the existing skeleton/null patterns. |
| [.env.example:109-147](../../../../../.env.example#L109-L147) | Existing "Selective engine startup" section documents `RELYLOOP_ENGINES`. | dotenv | New "Selecting an engine version" section follows in the same comment-block style. |
| [.github/workflows/pr.yml:439](../../../../../.github/workflows/pr.yml#L439), [:455](../../../../../.github/workflows/pr.yml#L455) | Backend lane declares engine images as SHA-pinned **service containers** (`elasticsearch:9.4.1@sha256:…`, `opensearchproject/opensearch:3.6.0@sha256:…`). | GHA service container | NOT affected by Compose changes. The backend lane is decoupled from `docker-compose.yml`'s image-tag interpolation (same decoupling as Phase 1). |
| [.github/workflows/pr.yml:887-894](../../../../../.github/workflows/pr.yml#L887-L894) | Smoke job sets `COMPOSE_PROFILES: "es,os,solr"` and calls `make up`. | GHA job | When `SMOKE_TEST` is enabled, this exercises the Compose path with the default image tags. New `*_IMAGE_TAG` env vars are NOT explicitly set in CI — the Compose `${X:-default}` fallback kicks in, so CI continues to test the matrix's latest-major default tags by default. |

### Navigation and link impact

No URL routes change. The reset-to-demo modal stays where it is ([`ui/src/components/dashboard/reset-demo-state-button.tsx`](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx) rendered inside [`start-here-checklist.tsx`](../../../../../ui/src/components/dashboard/start-here-checklist.tsx) on the home dashboard `/`). The `GET /api/v1/_test/demo/engines` endpoint stays at the same path with the same `_require_development_env` gate.

| Source file | Current link target | New link target |
|---|---|---|
| `(none)` | — | — |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [backend/tests/contract/test_openapi_surface.py:397-428](../../../../../backend/tests/contract/test_openapi_surface.py#L397-L428) | `test_demo_engines_response_shape` — asserts `DemoEngineStatus` has `engine_type` + `reachable` fields. | 1 | Extend to also assert `version` field exists (optional, string-or-null). |
| [backend/tests/integration/test_demo_engines_capability.py](../../../../../backend/tests/integration/test_demo_engines_capability.py) | Integration test for the capability endpoint. | 1 | Add a case asserting `version` field is populated when an engine is reachable (mocked httpx response) and `null` when unreachable. |
| [backend/tests/unit/services/test_demo_seeding_engine_reachability.py](../../../../../backend/tests/unit/services/test_demo_seeding_engine_reachability.py) | Unit tests for `is_engine_reachable`. | 1 | New companion test file `test_is_engine_reachable_with_version.py` for the sibling probe — does NOT modify the existing tests (the sibling is a new function). |
| [scripts/ci/test_parse_relyloop_engines.sh](../../../../../scripts/ci/test_parse_relyloop_engines.sh) | Existing `RELYLOOP_ENGINES` parser tests. | 17 cases | Unchanged. New companion file `scripts/ci/test_parse_relyloop_versions.sh` for the three new version parsers. |
| [ui/src/components/dashboard/__tests__/reset-demo-state-button.test.tsx](../../../../../ui/src/components/dashboard/__tests__/reset-demo-state-button.test.tsx) (if exists) | vitest component test for the reset modal. | TBD | Add render assertions: version label rendered when capability response includes `version`; falls back to `<engine label>` only when `version` is null. |

### Existing behaviors affected by scope change

- **`DemoEngineStatus` JSON shape:** Current: `{"engine_type": "elasticsearch", "reachable": true}`. New: `{"engine_type": "elasticsearch", "reachable": true, "version": "9.4.1"}` when the engine is reachable, `"version": null` when not. **Decision needed: no** — this is a purely additive optional field with `None` default, no consumer breaks.
- **`is_engine_reachable`'s signature:** Current: `(url, engine_type) -> bool`. New: unchanged. The sibling `is_engine_reachable_with_version` is a new function alongside, NOT a replacement. **Decision needed: no** — locked at preflight.
- **Default `make up` behavior:** Current: all three engines at the latest-major pins. New: identical when no `RELYLOOP_*_VERSION` env vars are set, because Compose's `${ES_IMAGE_TAG:-9.4.1}` form resolves to the current literal when the var is unset. **Decision needed: no** — back-compat by construction.
- **CI smoke job image versions:** Current: pulled from `docker-compose.yml`'s hardcoded tags. New: same (the smoke job does not set `*_IMAGE_TAG` env vars, so the Compose default kicks in). The smoke job continues to validate the matrix's latest-major default tags on every PR with `SMOKE_TEST=true`. **Decision needed: no** — same image bytes, validated by the same job.

---

## 3) Scope

### In scope

- **Capability A — Compose image-tag env vars.** Three engine services accept `ES_IMAGE_TAG` / `OS_IMAGE_TAG` / `SOLR_IMAGE_TAG` env vars with the current pinned tags as `${X:-default}` defaults.
- **Capability B — Curated matrix.** New `backend/app/core/engine_versions.py` exposes `ENGINE_VERSION_MATRIX: Final[dict[str, tuple[str, ...]]]` with one entry per *supported major* in the adapter compatibility window. Frontend mirror in `ui/src/lib/enums.ts` with a `// Values must match …` source-of-truth comment.
- **Capability C — install.sh non-interactive flags.** `RELYLOOP_ES_VERSION` / `RELYLOOP_OS_VERSION` / `RELYLOOP_SOLR_VERSION` env vars. Validated against `ENGINE_VERSION_MATRIX` BEFORE any `docker compose` call; unknown values exit 1 with `Unknown <engine> version 'X'. Allowed: <matrix values>.`. Validated values exported as `ES_IMAGE_TAG` / `OS_IMAGE_TAG` / `SOLR_IMAGE_TAG`.
- **Capability D — ES/OS version-report path.** New sibling `is_engine_reachable_with_version` in `backend/app/services/demo_seeding.py` returning `tuple[bool, str | None]`. ES/OS parse `body["version"]["number"]`; Solr delegates to `probe_capabilities()`. `DemoEngineStatus` gains `version: str | None = None`. `GET /api/v1/_test/demo/engines` returns the version field. Reset modal renders the version label inline next to each engine checkbox.
- **Capability E — Docs.** `docs/03_runbooks/local-dev.md` gains a "Selecting an engine version" subsection (mirroring the existing "Selecting a subset of engines"). `docs/01_architecture/deployment.md` gains an engine-version-matrix block. Maintainer release-update process (one row per upstream major release) documented inline near the matrix constant + in `CONTRIBUTING.md`.

### Out of scope

- **Per-minor version selection within a single major.** The adapter behaves identically across minor versions, so offering 9.4.1 *and* 9.3.2 within the same major is pure maintenance cost. The matrix offers one *latest patch* per supported major.
- **Versions outside the adapter compatibility window.** ES 7.x is documented as out-of-window at [`docs/01_architecture/adapters.md:147`](../../../../01_architecture/adapters.md#L147) (ES 8.11+/9.x); Solr 8.x is below `SOLR_MIN_VERSION` ([`solr.py:80`](../../../../../backend/app/adapters/solr.py#L80)). Offering them would ship an untested compatibility claim.
- **Runtime Docker Hub discovery.** The matrix is a maintainer-curated constant. No background job queries Docker Hub for new tags. Locked by Phase 1 deferred-fork D-5 (no runtime discovery — manual maintainer update on each upstream major release).
- **Per-trial / per-cluster version override.** A study cannot run against ES 8.x for trial 1 and ES 9.x for trial 2 — the cluster identity is fixed at study creation and the version reflects the running container, not a per-trial selection.
- **Browser-driven version switching.** The reset modal *displays* the running version (read-only); it does NOT offer a `<select>` to change it. Version changes still require re-running `make up`.
- **In-place upgrade tooling.** Changing `RELYLOOP_ES_VERSION` and re-running `make up` against a populated `./data/elasticsearch` volume may or may not be safe per engine's own upgrade rules — that's the operator's call against the engine vendor's documented upgrade path. The docs link to engine vendor upgrade pages.
- **GHA backend-lane image-tag selection.** The backend lane uses SHA-pinned service containers ([`pr.yml:439`](../../../../../.github/workflows/pr.yml#L439), [:455](../../../../../.github/workflows/pr.yml#L455)) decoupled from `docker-compose.yml`. Migrating the lane to consume the matrix is a separate concern (and would degrade reproducibility — SHA pins guarantee identical bytes; tag-only pins do not).

### API convention check

- **Endpoint prefix:** `/api/v1/_test/demo/engines` — already exists per Phase 1. This work extends the response shape, does NOT add new endpoints. The `_test` namespace is gated by `_require_development_env` ([`_test.py:847`](../../../../../backend/app/api/v1/_test.py#L847)) and produces 404 outside development.
- **Router namespace:** `backend/app/api/v1/_test.py` (the dev-only `_test` router).
- **HTTP methods for CRUD:** N/A — only GET on the capability endpoint.
- **Non-auth error envelope shape:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` per [`api-conventions.md`](../../../../01_architecture/api-conventions.md). Verified at [api-conventions.md:41](../../../../01_architecture/api-conventions.md#L41). `VALIDATION_ERROR` at 422 is the canonical Pydantic validation code per [api-conventions.md:66](../../../../01_architecture/api-conventions.md#L66).
- **Auth error shape:** N/A in MVP1–MVP3 (no auth surface).

### Phase boundaries

**Single phase.** All five capabilities ship in one PR. Rationale:
- Capability A (Compose env vars) is mechanically trivial (three `image:` line edits).
- Capability B (matrix constant + frontend mirror) is a single file + one `enums.ts` extension.
- Capability C (install.sh parsers) follows the exact pattern Phase 1 established for `RELYLOOP_ENGINES`.
- Capability D (ES/OS version probe) is estimated at ~1 line per engine to extract `body["version"]["number"]`. Solr delegates to `probe_capabilities()` (no new code).
- Capability E (docs) is two new subsections, no template changes.

If capability D's parse logic turns out to exceed ~10 LOC per engine during implementation (e.g., older OS releases nest the version under a different path), the impl-execute deferred-work step (Step 8.6) kicks in and splits D into its own follow-up via `phase2_idea.md`. This is the standard mechanism and does NOT require pre-allocating a `phase2_idea.md` here. **Single-phase spec, no `phase2_idea.md` to file.**

## 4) Product principles and constraints

- **Default unset → today's behavior preserved exactly.** A bare `make up` from a fresh clone with no `.env` boots the matrix's latest-major default tags — bit-for-bit identical to today's behavior.
- **The matrix is the contract.** Every value in `ENGINE_VERSION_MATRIX` is a *tested* compatibility claim — the smoke job (when `SMOKE_TEST=true`) validates the latest-major default on every PR. Adding a row means committing to test it.
- **Validate before pull.** Unknown values exit 1 from `install.sh` BEFORE any `docker compose pull` / `docker compose up` is invoked. No partial-failure state.
- **One entry per supported major.** The matrix bound is the documented adapter compatibility window (ES 8.x+9.x, OpenSearch 2.x+3.x, Solr 9.x+10.x). Not "last 2" — the window. When the adapter drops a major, the matrix row drops with it; when a new major is supported, a row is added.
- **`_FILE`-mounted secrets discipline preserved.** No image-tag value is a secret. The env vars are bare strings per the documented `.env`-for-non-secret-overrides pattern (CLAUDE.md Absolute Rule #2).
- **No runtime Docker Hub discovery.** Locked by Phase 1 D-5.
- **Version *display* is read-only.** The reset modal shows the detected version; it does NOT offer a `<select>` to change it.
- **Back-compat by construction.** `DemoEngineStatus.version` defaults to `None`; existing consumers that ignore unrecognized fields keep working.

### Anti-patterns

- **Do not** invent a "next 2" or "last 2 releases" count semantic. The matrix bound is the supported-major window per the adapter docs — anchor the implementation to the adapter window, not to a magic count.
- **Do not** offer image tags outside the adapter compatibility window (e.g. ES 7.x, OpenSearch 1.x, Solr 8.x). The Solr version-floor check at [`solr.py:585`](../../../../../backend/app/adapters/solr.py#L585) would abort the probe outright; ES/OS have no runtime floor but the cluster's behavior is not validated and the smoke job does not test it.
- **Do not** modify `is_engine_reachable`'s `bool` return type. Add a sibling `is_engine_reachable_with_version` returning `tuple[bool, str | None]`. The existing `bool` probe is called from `snapshot_engine_reachability` (slug→bool map for the orchestrator's scenario filter) where only the boolean is needed; widening the type there would ripple through the orchestrator for no operator value.
- **Do not** put the matrix in `backend/app/services/demo_seeding.py`. The matrix is consumed by BOTH `demo_seeding.py` and `backend/app/api/v1/_test.py`'s capability endpoint; a `core/` home avoids an import-direction cycle. (Locked at preflight.)
- **Do not** validate version values in `docker-compose.yml`'s YAML — Compose's `${X:-default}` substitution does NOT enforce an allowlist; an arbitrary `ES_IMAGE_TAG=foo` would be passed through to `docker pull` and surface as a registry error. Pre-validation must run in `install.sh` against the matrix BEFORE `docker compose pull/up`.
- **Do not** add a runtime Docker Hub query to discover new tags. Locked by Phase 1 D-5.
- **Do not** add per-minor versions within a single major. The adapter behaves identically across minors; extra rows are pure maintenance cost.
- **Do not** offer a `<select>` to change the version in the reset modal. Version changes require re-running `make up` — display only.

## 5) Assumptions and dependencies

- **Hard dependency on Phase 1 (shipped).** This work reuses `RELYLOOP_ENGINES`, `EngineTypeWire`, `DemoEngineStatus`, `DemoEnginesResponse`, `GET /api/v1/_test/demo/engines`, and the `parse_relyloop_engines` helper pattern. All shipped via PR #548 on 2026-06-17.
- **Adapter compatibility window is authoritative.** The matrix's bound is `docs/01_architecture/adapters.md` — ES 8.11+/9.x, OpenSearch 2.x/3.x, Solr 9.x/10.x. If the adapter window changes (a major is added or dropped), the matrix changes in lockstep.
- **Engine vendor upstream releases are out of our control.** The maintainer release-update process documents the manual step required when a new major's latest patch is published.
- **Docker Hub registry availability.** The corp-network install series shipped (PR #517-#525) covers the corp-proxy / TLS-interception case for the *default* image tags. Changing `*_IMAGE_TAG` does not introduce new registry-access risk because the image source is unchanged (same `${BASE_REGISTRY:-}` prefix).
- **No new secret.** No `_FILE`-mounted secret added. Bare env vars are appropriate for non-secret Compose substitutions per CLAUDE.md Absolute Rule #2.

## 6) Actors and roles

- Primary actor(s): **operator** (installs RelyLoop locally; chooses an engine version at install time). Also reads the version display in the reset modal during evaluation.
- Role model: **N/A — single-tenant install, no auth surface** (per [`docs/01_architecture/tech-stack.md`](../../../../01_architecture/tech-stack.md)).
- Permission boundaries: `_require_development_env` ([`_test.py:847`](../../../../../backend/app/api/v1/_test.py#L847)) gates the capability endpoint; same as Phase 1.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` table arrives at MVP2 per [`docs/01_architecture/data-model.md` §"Forthcoming: audit_log"](../../../../01_architecture/data-model.md). The endpoints in scope are reads (capability endpoint) and install-time bash (not API mutations). No state-mutating endpoint is added.

## 7) Functional requirements

### FR-1: Compose engine services accept image-tag env vars

- Requirement:
  - The `elasticsearch` service in `docker-compose.yml` **MUST** interpolate `image: ${BASE_REGISTRY:-}elasticsearch:${ES_IMAGE_TAG:-9.4.1}` — the trailing `:-9.4.1` literal MUST match the matrix's `elasticsearch[0]` value (the latest patch of the latest supported major).
  - The `opensearch` service **MUST** interpolate `image: ${BASE_REGISTRY:-}opensearchproject/opensearch:${OS_IMAGE_TAG:-3.6.0}` — trailing default matches `opensearch[0]`.
  - The `solr` service **MUST** interpolate `image: ${BASE_REGISTRY:-}solr:${SOLR_IMAGE_TAG:-10.0}` — trailing default matches `solr[0]`.
  - When all three env vars are unset, `docker compose config` **MUST** emit the same image references as before this work (back-compat by construction).
- Notes: The matrix's `[0]` element is the canonical "latest major's latest patch" — both the Compose default AND the smoke-job pin. A maintainer-update PR that bumps the matrix MUST also bump the Compose `:-` defaults in the same PR (enforced by the `verify_install_builds_all_services.sh` regression test, extended in FR-11).

### FR-2: Curated engine-version matrix constant

- Requirement:
  - A new file `backend/app/core/engine_versions.py` **MUST** export `ENGINE_VERSION_MATRIX: Final[dict[str, tuple[str, ...]]]`.
  - The dict keys **MUST** be the three `EngineTypeWire` values verbatim: `"elasticsearch"`, `"opensearch"`, `"solr"`.
  - Each value **MUST** be a tuple of latest-patch tags, one per supported major in the adapter compatibility window:
    - `"elasticsearch": ("9.4.1", "8.15.3")` — corresponds to ES 9.x + 8.x supported per [`adapters.md:147`](../../../../01_architecture/adapters.md#L147).
    - `"opensearch": ("3.6.0", "2.18.0")` — corresponds to OS 3.x + 2.x per [`adapters.md:148`](../../../../01_architecture/adapters.md#L148).
    - `"solr": ("10.0", "9.7")` — corresponds to Solr 10.x + 9.x per [`adapters.md:232`](../../../../01_architecture/adapters.md#L232).
  - The tuple's first element **MUST** match the corresponding Compose `${X_IMAGE_TAG:-<default>}` default.
  - The module **MUST** carry a top-of-file comment block documenting the maintainer release-update process: "When upstream releases a new latest patch for a supported major, update the corresponding tuple entry, bump the Compose `:-` default if the major changed, and verify the smoke job passes against the new tag."
  - A unit test **MUST** assert `set(ENGINE_VERSION_MATRIX.keys()) == set(get_args(EngineTypeWire))` so a future engine added to `EngineTypeWire` cannot silently lack a matrix entry.

### FR-3: install.sh accepts per-engine version env vars

- Requirement:
  - `scripts/install.sh` **MUST** accept three new env vars: `RELYLOOP_ES_VERSION`, `RELYLOOP_OS_VERSION`, `RELYLOOP_SOLR_VERSION`.
  - Each var, when set to a non-empty value, **MUST** be validated against `ENGINE_VERSION_MATRIX` for its engine via a new sourceable helper `scripts/lib/relyloop_engine_versions.sh` (function `parse_relyloop_engine_versions`).
  - Unset OR empty values **MUST** preserve the Compose default (the helper does NOT export the `*_IMAGE_TAG` var, so Compose's `${X:-default}` fallback applies).
  - Validated values **MUST** be exported as `ES_IMAGE_TAG` / `OS_IMAGE_TAG` / `SOLR_IMAGE_TAG` before the first `docker compose` invocation in `install.sh`.
  - The helper **MUST** be invoked AFTER `parse_relyloop_engines` (so engine selection is resolved first) and BEFORE `docker compose config --quiet`.
- Notes: The matrix values are *image tags*, not parsed semver. The helper compares the input verbatim against the tuple. This means `RELYLOOP_ES_VERSION=9.4.1` is valid but `RELYLOOP_ES_VERSION=9.4` is not — the tag must match exactly.

### FR-4: Pre-validation rejects unknown versions BEFORE docker compose

- Requirement:
  - On unknown version, `parse_relyloop_engine_versions` **MUST** print `Unknown <engine> version '<value>'. Allowed: <comma-separated matrix values>.` to stderr and return 1. `install.sh` runs under `set -e`, so the return 1 bubbles to `exit 1`.
  - The validation **MUST** run BEFORE any `docker compose pull` / `docker compose up` / `docker compose config`. (Validating during/after a Compose call would let `docker pull` start an unauthorized registry call against an arbitrary tag.)
  - The helper **MUST** be sourceable + unit-testable in isolation per the pattern at [`scripts/lib/relyloop_engines.sh`](../../../../../scripts/lib/relyloop_engines.sh).
  - Multiple invalid values **MAY** report all of them or stop at the first; the helper SHOULD report all-known-invalid in one error message so the operator fixes them in one cycle.
- Notes: Error message format mirrors the existing `parse_relyloop_engines` error: `Unknown engine '<eng>' in RELYLOOP_ENGINES. Allowed: es, os, solr.` — same tone, same shape.

### FR-5: Frontend mirror of the matrix

- Requirement:
  - `ui/src/lib/enums.ts` **MUST** export `ENGINE_VERSION_MATRIX` as an `as const` object whose keys + values match the backend constant verbatim.
  - The mirror **MUST** carry a `// Values must match backend/app/core/engine_versions.py ENGINE_VERSION_MATRIX` source-of-truth comment per CLAUDE.md "Enumerated Value Contract Discipline".
  - The `verify_enum_source_of_truth.sh` CI guard at [`scripts/ci/verify_enum_source_of_truth.sh`](../../../../../scripts/ci/verify_enum_source_of_truth.sh) **MUST** be extended to cover the new mirror (or a sibling guard added — see implementation plan).
- Notes: Phase 2 of this work does NOT yet add a frontend `<select>` to *choose* a version (out of scope per §3). The mirror exists so the reset modal can display the matrix-recognized values and so a future Phase that adds a `<select>` has the source-of-truth wire ready.

### FR-6: ES/OS sibling version-report probe

- Requirement:
  - A new function `is_engine_reachable_with_version(url, engine_type) -> tuple[bool, str | None]` **MUST** live alongside `is_engine_reachable` in `backend/app/services/demo_seeding.py`.
  - For `engine_type in {"elasticsearch", "opensearch"}`: GET the engine root `/`, validate `"version" in body and isinstance(body["version"].get("number"), str)`, return `(True, body["version"]["number"])`. On any failure (timeout, non-200, malformed body), return `(False, None)` and emit a WARN log identical in shape to `is_engine_reachable`'s existing probe-failed WARN.
  - For `engine_type == "solr"`: delegate to `SolrAdapter.probe_capabilities()` to extract the version field; on any failure return `(False, None)`. (Reusing the existing structured probe avoids a duplicate parser.)
  - The function **MUST** be total — no exception propagates out. The 2s timeout is preserved.
  - `is_engine_reachable` **MUST NOT** be modified. The existing callers (`snapshot_engine_reachability`, `demo_engines()`) continue to use `is_engine_reachable` for the boolean-only path.
- Notes: Decision locked at preflight — sibling not extension. The two functions share the underlying GET / timeout discipline but expose distinct return types so callers pick the one that matches what they need.

### FR-7: `DemoEngineStatus` carries version field

- Requirement:
  - The `DemoEngineStatus` Pydantic model at [`backend/app/api/v1/_test.py:812`](../../../../../backend/app/api/v1/_test.py#L812) **MUST** gain an optional field `version: str | None = None`.
  - The model **MUST** keep `model_config = ConfigDict(extra="forbid")` — the addition is to the explicit-field list, not to the unknown-field policy.
  - The field's value **MUST** be the engine's `version.number` (ES/OS) or the equivalent extracted from `probe_capabilities()` (Solr), when the engine is reachable. It **MUST** be `None` when the engine is unreachable.
- Notes: Back-compat — existing consumers ignoring an unrecognized field keep working. The frontend `DemoEngineStatus` TypeScript interface at [`ui/src/lib/api/demo-engines.ts:38`](../../../../../ui/src/lib/api/demo-engines.ts#L38) is regenerated from the OpenAPI snapshot via `pnpm types:gen` — the change lands automatically.

### FR-8: Capability endpoint returns version field

- Requirement:
  - `GET /api/v1/_test/demo/engines` ([`_test.py:842`](../../../../../backend/app/api/v1/_test.py#L842)) **MUST** call `is_engine_reachable_with_version` (not `is_engine_reachable`) so each `DemoEngineStatus` row is constructed with the version.
  - The endpoint's existing characteristics **MUST** be preserved: always returns 200 (reachability data IS the response, not an error); concurrency via `asyncio.gather`; total wall-clock bounded by the 2s per-probe timeout; same `_require_development_env` gate.
  - The OpenAPI snapshot at `ui/openapi.json` **MUST** be regenerated to include the new `version` field; the `verify_openapi_snapshot_fresh.sh` CI guard at [`scripts/ci/verify_openapi_snapshot_fresh.sh`](../../../../../scripts/ci/verify_openapi_snapshot_fresh.sh) will fail the PR if the snapshot is stale.
- Notes: This change is what makes the version visible to the frontend. The OpenAPI snapshot's regeneration is part of the standard `bash scripts/regen-generated-artifacts.sh` workflow per CLAUDE.md.

### FR-9: Reset modal renders detected version

- Requirement:
  - [`ui/src/components/dashboard/reset-demo-state-button.tsx`](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx) **MUST** render each engine checkbox label with a trailing version annotation when the capability response includes a non-null `version`. Format: `Elasticsearch — 9.4.1` (em-dash separator) when `version == "9.4.1"`.
  - When `version` is `null` (engine unreachable), the label **MUST** render as today: `Elasticsearch` (no trailing annotation).
  - When `enginesQuery.data == null` (pre-load), the label **MUST** render as today (the existing skeleton/empty state). The version-load is opportunistic — never blocks the checkbox render.
  - The annotation **MUST** use a muted text style (Tailwind `text-muted-foreground text-xs`) to indicate it's informational, not interactive.
- Notes: Display-only — clicking the version annotation does nothing. The `<input type="checkbox">` semantics are unchanged.

### FR-10: `.env.example` documents new env vars

- Requirement:
  - A new section in `.env.example`, immediately after the existing "Selective engine startup" block ([`.env.example:109-147`](../../../../../.env.example#L109-L147)), **MUST** document the three new env vars + the matrix.
  - The section **MUST** use the same comment-block style as the existing block.
  - It **MUST** show concrete examples: `RELYLOOP_ES_VERSION=8.15.3 # ES 8.x evaluator path`.
  - It **MUST** state the back-compat-by-default behavior: "Unset → matrix's latest-major default applies (same as today)."
  - It **MUST** name the matrix file: `# Allowed values per engine, see backend/app/core/engine_versions.py ENGINE_VERSION_MATRIX`.

### FR-11: CI smoke job continues to validate default tags

- Requirement:
  - The `pr.yml` smoke job at [`pr.yml:848`](../../../../../.github/workflows/pr.yml#L848) **MUST NOT** explicitly set `*_IMAGE_TAG` env vars. The Compose `${X:-default}` fallback applies, so the smoke job continues to test the matrix's latest-major default tags by default.
  - The existing `verify_install_builds_all_services.sh` CI guard **MUST** be extended (or a sibling guard added) to assert: every matrix value's `[0]` element matches the corresponding Compose `image: …:${X_IMAGE_TAG:-<default>}` literal. This prevents the matrix and Compose defaults from drifting apart.
- Notes: The smoke job is gated OFF by default per `SMOKE_TEST=true` opt-in (state.md). When OFF, the regression risk is the existing matrix-vs-Compose drift gate above — that gate runs on every PR via `pr.yml`.

### FR-12: Docs update

- Requirement:
  - `docs/03_runbooks/local-dev.md` **MUST** gain a "Selecting an engine version" subsection, immediately after the existing [§ "Selecting a subset of engines"](../../../../03_runbooks/local-dev.md). The new section MUST mirror the existing tone + structure (3-line intro, copy-pasteable `echo … >> .env` example, "DX hazard" sub-note about Compose's `${X:-default}` fallback).
  - `docs/01_architecture/deployment.md` **MUST** gain an engine-version-matrix block (a table listing the three engines, their supported majors per [`adapters.md`](../../../../01_architecture/adapters.md), and the current matrix values).
  - The top of `backend/app/core/engine_versions.py` **MUST** carry a maintainer release-update process comment (named in FR-2).
  - `CONTRIBUTING.md` **MUST** reference the maintainer process — one-line pointer at the matrix file.

## 8) API and data contract baseline

### 8.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `GET` | `/api/v1/_test/demo/engines` | (existing endpoint extended) Probes ES/OS/Solr concurrently, returns per-engine `{engine_type, reachable, version}`. Always 200. | (none — total handler) |

Note: No new endpoints. The dev-only `_test` namespace is gated by `_require_development_env` per Phase 1; outside development the route 404s per existing behavior. Validation errors (the install.sh paths) are bash, not API.

### 8.2 Contract rules

- Response body **MUST** include the new `version` field on every `DemoEngineStatus` row (nullable string).
- The endpoint **MUST** continue to return 200 even when all three engines are unreachable (data IS the response).
- The `engine_type` ordering in the response **MUST** stay deterministic (preserved from Phase 1's `_DEMO_ENGINE_PROBE_URLS` tuple order).
- The OpenAPI snapshot **MUST** include the `version` field. CI fails if the snapshot is stale.

### 8.3 Response examples

Success — all three engines reachable, versions populated:

```json
{
  "engines": [
    {"engine_type": "elasticsearch", "reachable": true, "version": "9.4.1"},
    {"engine_type": "opensearch",    "reachable": true, "version": "3.6.0"},
    {"engine_type": "solr",          "reachable": true, "version": "10.0.0"}
  ]
}
```

Partial — OpenSearch unreachable:

```json
{
  "engines": [
    {"engine_type": "elasticsearch", "reachable": true,  "version": "9.4.1"},
    {"engine_type": "opensearch",    "reachable": false, "version": null},
    {"engine_type": "solr",          "reachable": true,  "version": "10.0.0"}
  ]
}
```

Reachable but version probe failed (malformed body / unexpected shape):

```json
{
  "engines": [
    {"engine_type": "elasticsearch", "reachable": true, "version": null}
  ]
}
```

Non-auth failure example — endpoint accessed outside development (existing Phase 1 behavior, copied from the parent spec):

```json
{
  "detail": "Not Found"
}
```

Note: The `_require_development_env` gate returns FastAPI's default `404 Not Found` shape — a plain-string `detail`, not the structured envelope. This is the existing behavior of the `_test` namespace, NOT a deviation from `api-conventions.md`. (Verified at [`_test.py`](../../../../../backend/app/api/v1/_test.py) — the dev-env gate raises `HTTPException(404, "Not Found")`.) The capability endpoint never produces a non-auth structured-envelope error inside development because it's a total handler.

Auth failure example: N/A — no auth surface (MVP1–MVP3).

### 8.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `ENGINE_VERSION_MATRIX["elasticsearch"]` (`*_IMAGE_TAG` allowlist) | `9.4.1`, `8.15.3` | `backend/app/core/engine_versions.py` `ENGINE_VERSION_MATRIX["elasticsearch"]` | `ui/src/lib/enums.ts` `ENGINE_VERSION_MATRIX.elasticsearch` mirror (display only — no `<select>` in scope) |
| `ENGINE_VERSION_MATRIX["opensearch"]` | `3.6.0`, `2.18.0` | same file | same mirror |
| `ENGINE_VERSION_MATRIX["solr"]` | `10.0`, `9.7` | same file | same mirror |
| `RELYLOOP_ES_VERSION` env var | one of `ENGINE_VERSION_MATRIX["elasticsearch"]` values | `scripts/lib/relyloop_engine_versions.sh` (`parse_relyloop_engine_versions`) reading the constant | N/A (install-time only) |
| `RELYLOOP_OS_VERSION` env var | one of `ENGINE_VERSION_MATRIX["opensearch"]` values | same helper | N/A |
| `RELYLOOP_SOLR_VERSION` env var | one of `ENGINE_VERSION_MATRIX["solr"]` values | same helper | N/A |
| `DemoEngineStatus.version` field | any nullable string (open value — the engine's `version.number`) | `backend/app/services/demo_seeding.is_engine_reachable_with_version` parsed output | `ui/src/lib/api/demo-engines.ts` `DemoEngineStatus.version` (regenerated from OpenAPI snapshot) |

**Rules:**
- The image-tag values are checked verbatim. The bash helper does `[[ "$input" == "$matrix_value" ]]` — there is no semver parsing or "9.4.x" expansion. An operator who wants 9.4.0 specifically can hand-edit `docker-compose.yml` (out-of-band path documented in `local-dev.md`).
- `DemoEngineStatus.version` is the *observed* engine version — NOT validated against the matrix. An operator who runs against a non-matrix tag will see that tag echoed back; the capability endpoint reports what's running, period.
- When the backend matrix adds a new value, the frontend mirror MUST be updated in the same PR — same as `ENGINE_TYPE_VALUES`. The `verify_enum_source_of_truth.sh` guard enforces this.

### 8.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| (none — bash install-time path) | exit 1 | `Unknown <engine> version 'X'. Allowed: <matrix values>.` — printed to stderr by `parse_relyloop_engine_versions`; `install.sh` exits 1 under `set -e`. No new API error code. |

The capability endpoint has no new error codes — it's a total handler. The reset modal's POST to `/api/v1/_test/demo/reseed` is unchanged from Phase 1 (no engine-version concern in the reseed POST body — versions are install-time).

## 9) Data model and state transitions

### New/changed entities

**No new tables. No migration.** This work touches:
- A new Python constant (`backend/app/core/engine_versions.py`)
- A new Pydantic model field (`DemoEngineStatus.version`)
- A new bash function (`parse_relyloop_engine_versions`)
- Three `image:` line edits in `docker-compose.yml`
- A frontend mirror (`ui/src/lib/enums.ts`)
- A frontend component (`reset-demo-state-button.tsx`)
- An updated OpenAPI snapshot (regenerated)
- Docs

The Alembic head stays `0023_proposals_superseded_status` (unchanged).

### Required invariants

- **Matrix-Compose default sync.** Every `ENGINE_VERSION_MATRIX[<engine>][0]` value MUST equal the corresponding `${X_IMAGE_TAG:-<default>}` literal in `docker-compose.yml`. Enforced by an extended CI guard (FR-11).
- **Matrix-EngineTypeWire key sync.** `set(ENGINE_VERSION_MATRIX.keys()) == set(get_args(EngineTypeWire))`. Enforced by a unit test (FR-2).
- **Backend-frontend mirror sync.** The frontend `ENGINE_VERSION_MATRIX` mirror MUST equal the backend constant. Enforced by `verify_enum_source_of_truth.sh` (extended in FR-5) or a sibling guard.
- **Pre-validation discipline.** `parse_relyloop_engine_versions` MUST be sourced + invoked BEFORE any `docker compose` call in `install.sh`. (Same discipline as `parse_relyloop_engines`.)
- **`is_engine_reachable_with_version` totality.** No exception propagates out; failures surface as `(False, None)`. (Mirrors `is_engine_reachable`'s totality contract.)

### State transitions

N/A — no state machine added.

### Idempotency / replay behavior

- `parse_relyloop_engine_versions` is pure: same input → same output. Safe to invoke on every `install.sh` run.
- The capability endpoint is read-only and stateless. No idempotency concern.
- The reset modal POST is unchanged from Phase 1's contract.

## 10) Security, privacy, and compliance

- **Threats:**
  1. **Arbitrary tag injection** — operator sets `RELYLOOP_ES_VERSION=foo:tagsyntax` thinking it's a free-form tag. **Control:** pre-validation rejects unknown values BEFORE any `docker pull`; no registry call happens with operator-controlled input.
  2. **Out-of-window version chosen** — operator sets `RELYLOOP_ES_VERSION=7.17.0` (below the adapter window). **Control:** the matrix only contains supported-window values; pre-validation rejects.
  3. **Stale matrix in production** — maintainer forgets to bump the matrix when upstream releases a new patch. **Control:** the matrix-Compose-default sync invariant ensures the smoke job validates whatever is in the matrix; the operational risk is "running slightly stale" not "running unsupported."
  4. **Image-tag leak in logs** — the version annotation in the reset modal is informational, not sensitive. **Control:** N/A.
- **Controls:** All four threats are covered by the listed controls. No new threat surface.
- **Secrets/key handling:** No new secret. Image tags are non-secret per the existing `.env`-for-non-secret-overrides pattern.
- **Auditability:** No state mutation; no audit-log emission. (`audit_log` arrives at MVP2 anyway — `_test` namespace is excluded per Phase 1.)
- **Data retention/deletion/export impact:** N/A.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** No new pages. The reset-to-demo modal stays at its existing home (`/` → "Reset to demo state" button → modal). The version annotation appears inline next to each engine checkbox label.
- **Labeling taxonomy:**
  - Engine label: `Elasticsearch` / `OpenSearch` / `Apache Solr` (existing).
  - Version annotation: `— 9.4.1` (em-dash separator, version string from `DemoEngineStatus.version`).
  - When version is `null` (engine unreachable or version-probe failed): no annotation (label renders as today).
- **Content hierarchy:** The version annotation is *secondary* to the checkbox + engine label. Muted text style (`text-muted-foreground text-xs`) signals informational role.
- **Progressive disclosure:** N/A — the version is shown inline on first render of the modal once the capability response lands. No expand/collapse.
- **Relationship to existing pages:** Extends — same modal, same checkboxes, additive label.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---|---|---|---|
| Engine checkbox label version annotation (`— 9.4.1`) | (none — the version IS the info; no further tooltip needed) | N/A | N/A |
| `RELYLOOP_ES_VERSION` env var (in `.env.example`) | (inline comment) "Pin Elasticsearch to a specific supported version. Allowed: 9.4.1, 8.15.3. Unset → 9.4.1 (latest 9.x)." | comment | inline next to the example |
| `ENGINE_VERSION_MATRIX` mirror in `enums.ts` | (top-of-file source-of-truth comment) "Values must match backend/app/core/engine_versions.py ENGINE_VERSION_MATRIX." | comment | inline |

No new in-app tooltips required. The version display is self-explanatory once the operator sees a version number next to an engine name.

### Primary flows

1. **Operator pins to ES 8.x at install.** Operator clones the repo, sets `RELYLOOP_ES_VERSION=8.15.3` in `.env`, runs `make up`. install.sh's helper validates `8.15.3` is in `ENGINE_VERSION_MATRIX["elasticsearch"]`, exports `ES_IMAGE_TAG=8.15.3`, then `docker compose` pulls `elasticsearch:8.15.3` instead of `9.4.1`. The OS and Solr defaults (`3.6.0`, `10.0`) apply unchanged. Operator opens `/`, clicks "Reset to demo state," sees the modal with `Elasticsearch — 8.15.3` in the checkbox row, confirms, and a demo is seeded against the 8.x cluster.
2. **Operator runs default `make up`.** No `.env` change. install.sh's helper sees `$RELYLOOP_ES_VERSION` unset, does not export `ES_IMAGE_TAG`, Compose's `${ES_IMAGE_TAG:-9.4.1}` resolves to `9.4.1` — bit-for-bit identical to today. The reset modal renders `Elasticsearch — 9.4.1` once the capability response lands.
3. **Operator picks the wrong version.** Operator sets `RELYLOOP_ES_VERSION=9.5.0` (a tag not in the matrix). install.sh's helper prints `Unknown elasticsearch version '9.5.0'. Allowed: 9.4.1, 8.15.3.` to stderr and exits 1. No image pull happens; `make up` halts cleanly with a clear error.
4. **Operator runs against an out-of-band tag.** Operator hand-edits `docker-compose.yml`'s `image:` line to use an arbitrary tag (e.g. 9.4.0). install.sh's helper is bypassed because the var stays unset; Compose pulls the operator-chosen tag. The reset modal displays whatever version the running container reports — the capability endpoint does NOT validate against the matrix (it reports what's actually running). The operator owns the support burden.

### Edge / error flows

- **Engine reachable but version probe fails** (malformed body, version field missing, unexpected shape): `is_engine_reachable_with_version` returns `(True, None)`. The capability endpoint emits `{"engine_type": "x", "reachable": true, "version": null}`. The reset modal renders the engine label with no version annotation. The operator can still proceed with the reseed.
- **Engine unreachable**: `(False, None)`. Same modal rendering as today — checkbox disabled (Phase 1's existing behavior); no version annotation.
- **All three engines unreachable**: same as today — Phase 1's "Engine unreachable" footer message renders; no version annotations anywhere; Confirm button disabled.
- **Capability response load error**: same as today — the existing skeleton/error fallback renders; version annotations are absent because there's no data to render them from.

## 12) Given/When/Then acceptance criteria

### AC-1: Default `make up` behavior preserved

- Given a fresh clone with no `.env` and no `RELYLOOP_*_VERSION` env vars in the shell
- When the operator runs `make up`
- Then `docker compose config` reports the same image references as before this work — `${BASE_REGISTRY:-}elasticsearch:9.4.1`, `${BASE_REGISTRY:-}opensearchproject/opensearch:3.6.0`, `${BASE_REGISTRY:-}solr:10.0`
- Example: `docker compose config | grep -E 'image:.*(elasticsearch|opensearch|solr):' | sort` matches the pre-PR baseline byte-for-byte.

### AC-2: `RELYLOOP_ES_VERSION=8.15.3` boots ES 8.x

- Given `RELYLOOP_ES_VERSION=8.15.3` exported in the shell
- When the operator runs `make up`
- Then install.sh exports `ES_IMAGE_TAG=8.15.3`
- And `docker compose config` reports `image: elasticsearch:8.15.3` for the `elasticsearch` service
- And the OS and Solr image refs stay at their latest-major defaults (`3.6.0`, `10.0`)
- Example: `docker compose config | grep 'image:.*elasticsearch:'` → contains `8.15.3`, NOT `9.4.1`.

### AC-3: Unknown version rejected before docker compose

- Given `RELYLOOP_ES_VERSION=9.9.9` exported in the shell (not in the matrix)
- When the operator runs `make up`
- Then `parse_relyloop_engine_versions` prints `Unknown elasticsearch version '9.9.9'. Allowed: 9.4.1, 8.15.3.` to stderr
- And install.sh exits 1
- And no `docker compose pull` / `docker compose up` was invoked
- Example: `docker images | grep elasticsearch` shows no new layers for the rejected tag after the failed run.

### AC-4: Matrix-Compose-default sync invariant

- Given the matrix `ENGINE_VERSION_MATRIX["elasticsearch"] = ("9.4.1", "8.15.3")`
- When the CI guard (extended `verify_install_builds_all_services.sh` or sibling) runs
- Then it asserts `docker-compose.yml`'s `elasticsearch` service `image:` line ends with `:${ES_IMAGE_TAG:-9.4.1}` (matching `ENGINE_VERSION_MATRIX["elasticsearch"][0]`)
- And similarly for opensearch (`:${OS_IMAGE_TAG:-3.6.0}`) and solr (`:${SOLR_IMAGE_TAG:-10.0}`)
- And the guard fails the PR if any of the three pairs drift

### AC-5: Capability endpoint returns version field

- Given the stack is running with all three engines reachable on their default tags
- When the client calls `GET /api/v1/_test/demo/engines`
- Then the response is 200 with body `{"engines": [{"engine_type": "elasticsearch", "reachable": true, "version": "9.4.1"}, …]}`
- And each row's `version` matches the running container's `version.number` field for ES/OS, or Solr's `probe_capabilities()` version field
- Example: against the default tags, all three `version` values are non-null strings matching the matrix's `[0]` element.

### AC-6: Capability endpoint returns null version when engine unreachable

- Given the OpenSearch engine is stopped (`docker compose stop opensearch`) while ES and Solr stay up
- When the client calls `GET /api/v1/_test/demo/engines`
- Then the OS row is `{"engine_type": "opensearch", "reachable": false, "version": null}`
- And the ES + Solr rows still report `reachable: true` with non-null version strings
- And the endpoint returns 200 (NOT an error)

### AC-7: Capability endpoint returns null version when engine reachable but probe malformed

- Given a probe stub returns `{"version": {"build_flavor": "default"}}` (no `number` field) for ES
- When `is_engine_reachable_with_version` runs
- Then it returns `(True, None)` and emits a WARN log identical in shape to `is_engine_reachable`'s existing probe-failed log
- And the capability endpoint emits `{"engine_type": "elasticsearch", "reachable": true, "version": null}`

### AC-8: Reset modal renders version annotation

- Given the capability response includes `{"engine_type": "elasticsearch", "reachable": true, "version": "9.4.1"}`
- When the operator opens the reset-to-demo modal
- Then the Elasticsearch checkbox label renders `Elasticsearch — 9.4.1` (em-dash separator, version in muted text)
- And the OpenSearch/Solr labels render the same pattern with their respective versions

### AC-9: Reset modal omits version annotation when null

- Given the capability response includes `{"engine_type": "opensearch", "reachable": false, "version": null}`
- When the modal renders
- Then the OpenSearch checkbox label renders `OpenSearch` only — no annotation
- And the checkbox is disabled (existing Phase 1 behavior for unreachable engines — unchanged)

### AC-10: Matrix-EngineTypeWire key sync invariant

- Given the unit test asserts `set(ENGINE_VERSION_MATRIX.keys()) == set(get_args(EngineTypeWire))`
- When `EngineTypeWire` adds a new engine but `ENGINE_VERSION_MATRIX` is not updated
- Then the unit test fails with a clear message naming the missing key

### AC-11: `is_engine_reachable` unchanged

- Given the existing unit tests at `backend/tests/unit/services/test_demo_seeding_engine_reachability.py`
- When the new sibling function is added
- Then all existing tests pass without modification
- And `is_engine_reachable`'s return-type annotation stays `-> bool`
- And `snapshot_engine_reachability` continues to call `is_engine_reachable` (NOT the new sibling)

### AC-12: OpenAPI snapshot freshness gate enforces `version` field

- Given the spec adds `version: str | None = None` to `DemoEngineStatus`
- When the developer commits without running `bash scripts/regen-generated-artifacts.sh`
- Then `verify_openapi_snapshot_fresh.sh` fails the PR with a diff showing the missing `version` field

### AC-13: Frontend mirror sync gate enforces matrix parity

- Given the backend `ENGINE_VERSION_MATRIX` has `("9.4.1", "8.15.3")` for elasticsearch
- And the frontend mirror has `["9.4.1"]` (out of sync)
- When the source-of-truth CI guard runs
- Then it fails the PR with a diff showing the missing value

### AC-14: `.env.example` section documents the new vars

- Given the docs gate verifies `.env.example` content
- When the new section is added per FR-10
- Then it shows: `RELYLOOP_ES_VERSION` / `RELYLOOP_OS_VERSION` / `RELYLOOP_SOLR_VERSION` examples; the allowed-values pointer at `backend/app/core/engine_versions.py`; the back-compat default behavior; the matrix-Compose-default sync invariant.

### AC-15: Contract test covers the new field

- Given `test_demo_engines_response_shape` at [`backend/tests/contract/test_openapi_surface.py:397`](../../../../../backend/tests/contract/test_openapi_surface.py#L397)
- When the spec adds `version` to `DemoEngineStatus`
- Then the test is extended to assert `version` in `row_props` with `type: string` AND `nullable: true` (or anyOf `string`/`null`)

## 13) Non-functional requirements

- **Performance:** No regression. The capability endpoint's wall-clock stays bounded by the existing 2s per-probe timeout; the new version parse is a single dict lookup inside the same HTTP response body — no additional network round-trips. install.sh's pre-validation is a bash array lookup — O(1) per engine, negligible.
- **Reliability:** Probe failures are total — `is_engine_reachable_with_version` returns `(False, None)` on any failure, identical to `is_engine_reachable`'s discipline. No new failure mode introduced into the install or capability path.
- **Operability:** Same WARN-log shape as the existing probe-failed log. Operators reading logs can grep for `demo_reseed_engine_probe_failed` and see both bool-only and version-aware probe failures with the same `engine_type` / `engine_base` / `error_type` extras.
- **Accessibility:** The version annotation uses standard text (Tailwind muted-foreground). Screen readers announce `Elasticsearch — 9.4.1` as plain text alongside the checkbox label. No new ARIA work required.

## 14) Test strategy requirements (spec-level)

Minimum required coverage by layer:

- **Unit (`backend/tests/unit/`):**
  - `test_engine_versions_matrix.py` — asserts matrix-key/EngineTypeWire-arg parity (AC-10); asserts `[0]` element matches Compose `:-` default for each engine.
  - `test_is_engine_reachable_with_version.py` — companion to the existing `test_demo_seeding_engine_reachability.py`. Cases: (a) ES happy path → returns `(True, "9.4.1")`; (b) OS happy path; (c) Solr happy path (delegates to `probe_capabilities()`); (d) reachable but `version.number` missing → `(True, None)` + WARN; (e) reachable but `version` field missing → `(True, None)` + WARN; (f) HTTP 500 → `(False, None)` + WARN; (g) timeout → `(False, None)` + WARN; (h) connection refused → `(False, None)` + WARN.
- **Integration (`backend/tests/integration/`):**
  - Extend `test_demo_engines_capability.py` with two cases: (a) all three engines reachable → `version` populated; (b) one engine unreachable → that row has `version: null` + the others stay populated.
- **Contract (`backend/tests/contract/`):**
  - Extend `test_demo_engines_response_shape` (AC-15) to assert `version` field exists with string-or-null type.
- **Frontend (vitest):**
  - Component test in `ui/src/components/dashboard/__tests__/reset-demo-state-button.test.tsx` (extend if exists, add if not). Cases: (a) capability data includes `version` → label renders `Engine — version`; (b) capability data includes null `version` → label renders engine name only; (c) capability data is null (pre-load) → label renders engine name only (matches today).
- **CI guards (`scripts/ci/`):**
  - New `scripts/ci/test_parse_relyloop_versions.sh` — mirrors `test_parse_relyloop_engines.sh`. Cases: (a) unset → no export; (b) valid value → exports `*_IMAGE_TAG`; (c) invalid value → exits 1 with the documented error message; (d) all three vars set independently.
  - Extend `verify_install_builds_all_services.sh` (or add sibling) to enforce matrix-Compose-default sync (AC-4).
  - Extend `verify_enum_source_of_truth.sh` (or add sibling) to enforce backend-frontend mirror sync (AC-13).

The 80% backend coverage gate at `pyproject.toml` applies unchanged.

## 15) Documentation update requirements

- `docs/01_architecture/deployment.md` — add engine-version-matrix block listing the three engines, their supported majors per `adapters.md`, and the current matrix values. Link to maintainer release-update process.
- `docs/01_architecture/adapters.md` — cross-link to the new matrix block (one-line "See deployment.md §… for the curated install-time version matrix.").
- `docs/03_runbooks/local-dev.md` — add "Selecting an engine version" subsection immediately after the existing "Selecting a subset of engines" (mirror the existing block's structure exactly).
- `CONTRIBUTING.md` — add a one-line pointer to the maintainer release-update process at `backend/app/core/engine_versions.py`.
- `.env.example` — add the new env-var documentation block per FR-10.
- `state.md` — flip the in-flight note when implementation starts; add to "Last 5 merges" on completion (standard finalization).

No `docs/04_security/` or `docs/05_quality/` change required.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None — purely additive infra change. Default unset → today's behavior. No staged rollout needed.
- **Migration/backfill expectations:** None — no schema change. Alembic head unchanged.
- **Operational readiness gates:** The matrix-Compose-default sync invariant (FR-11) + the matrix-EngineTypeWire key sync invariant (AC-10) are the two regression guards. Both fire on every PR.
- **Release gate:** Standard — all `pr.yml` checks green (smoke OFF per state.md, opt-in via `SMOKE_TEST=true`). The matrix-update process is documented at `backend/app/core/engine_versions.py` for the *next* time upstream releases a new patch — no operational change at release time for this PR.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-2, AC-4 | Story 1.1 (Compose image-tag interpolation) | Existing `verify_install_builds_all_services.sh` (extended) | `deployment.md` matrix block |
| FR-2 | AC-10, AC-4 | Story 1.2 (engine_versions.py constant) | `backend/tests/unit/test_engine_versions_matrix.py` (new) | inline maintainer-process comment + `CONTRIBUTING.md` |
| FR-3 | AC-2, AC-3 | Story 1.3 (install.sh helper) | `scripts/ci/test_parse_relyloop_versions.sh` (new) | inline install.sh comment |
| FR-4 | AC-3 | Story 1.3 (validation discipline) | same | same |
| FR-5 | AC-13 | Story 1.4 (frontend mirror) | extended `verify_enum_source_of_truth.sh` | inline `enums.ts` comment |
| FR-6 | AC-7, AC-11 | Story 2.1 (`is_engine_reachable_with_version`) | `backend/tests/unit/services/test_is_engine_reachable_with_version.py` (new) | none (internal) |
| FR-7 | AC-5, AC-6, AC-7, AC-12, AC-15 | Story 2.2 (`DemoEngineStatus.version` field) | extended `test_demo_engines_response_shape` + integration | none (OpenAPI snapshot regenerated) |
| FR-8 | AC-5, AC-6, AC-12 | Story 2.2 | extended `test_demo_engines_capability.py` + OpenAPI snapshot freshness gate | none |
| FR-9 | AC-8, AC-9 | Story 3.1 (reset modal version annotation) | extended `reset-demo-state-button.test.tsx` | none (UI only) |
| FR-10 | AC-14 | Story 1.5 (.env.example section) | (manual review — no test) | `.env.example` |
| FR-11 | AC-4 | Story 1.6 (CI guard extension) | extended `verify_install_builds_all_services.sh` | none |
| FR-12 | (all UX flows) | Story 4.1 (docs) | (manual review) | `local-dev.md`, `deployment.md`, `adapters.md`, `CONTRIBUTING.md`, inline comments |

## 18) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-1 through AC-15) pass in CI.
- [ ] All test layers (unit/integration/contract/vitest + new bash CI scripts) are green.
- [ ] Documentation updates across `docs/01_architecture/`, `docs/03_runbooks/`, `CONTRIBUTING.md`, `.env.example`, and inline maintainer-process comments are merged.
- [ ] Matrix-Compose-default sync invariant verified on a default `make up` (no `*_IMAGE_TAG` env vars set) — `docker compose config` reports the pre-PR baseline image references byte-for-byte.
- [ ] `RELYLOOP_ES_VERSION=8.15.3 make up` boots Elasticsearch 8.15.3 in a manual smoke test on the maintainer's laptop (the smoke job in CI exercises the *default* tags; non-default tag selection is a manual verification gate per the standard chore release checklist).
- [ ] OpenAPI snapshot regenerated; `verify_openapi_snapshot_fresh.sh` green.
- [ ] Frontend mirror sync gate green.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

(None at spec time.) Both locked-at-preflight forks are reflected in §3 and §4:
- Matrix file location → `backend/app/core/engine_versions.py` (locked, rationale in §4 anti-patterns).
- Version-report API shape → sibling `is_engine_reachable_with_version` not extension of `is_engine_reachable` (locked, rationale in FR-6 + §4 anti-patterns).
- Matrix bound → one entry per supported major in the adapter compatibility window (locked at preflight after the operator asked "should we include more than the last 2 versions?").

### Decision log

- **2026-06-17** — Priority reset from `Backlog` to `P1` at operator confirmation. Original Phase 1 finalization carved this folder off with a "Why deferred" rationale ("polish on top of engine selection"); operator clarified version selection is a core requirement, not polish. RelyLoop must not assume every customer runs the latest engine version. The "Why deferred" rationale in idea.md was rewritten as "Why this is core" for the record.
- **2026-06-17** — Matrix bound locked as "one entry per supported major in the adapter compatibility window," NOT "last 2 versions." The two happen to coincide today (ES 8.x+9.x, OS 2.x+3.x, Solr 9.x+10.x → 2 per engine) but anchoring to the adapter window makes the matrix self-bounding: when the adapter drops a major, the row drops with it. Rationale: extra minors within a major are pure maintenance cost (adapter behaves identically); out-of-window majors are untested compatibility claims and Solr's runtime version-floor at [`solr.py:585`](../../../../../backend/app/adapters/solr.py#L585) would abort the probe outright.
- **2026-06-17** — Matrix file location locked as `backend/app/core/engine_versions.py` (preflight). `demo_seeding.py` was the original alternative but the matrix is consumed by BOTH `demo_seeding.py` and `_test.py`'s capability endpoint; `core/` avoids an import-direction cycle.
- **2026-06-17** — Version-report function locked as a sibling `is_engine_reachable_with_version`, NOT an extension of `is_engine_reachable` (preflight). The existing function is called from `snapshot_engine_reachability` which only needs the boolean; widening the return type there would ripple through the orchestrator's scenario filter for no operator value.
- **2026-06-17** — Single-phase spec (no `phase2_idea.md`). Capability D (ES/OS version-report) is estimated at ~1 line per engine; if implementation discovers it grows beyond ~10 LOC per engine, the standard impl-execute Step 8.6 deferred-work mechanism splits it into a follow-up at that time. Pre-allocating a phase boundary now would over-commit to a deferral that may not be needed.
