# Feature Specification — Unblock `pr.yml` against Solr (skip-on-unreachable + smoke healthboot)

**Date:** 2026-06-01
**Status:** Draft
**Owners:** RelyLoop maintainer (eric.starr@soundminds.ai)
**Related docs:**
- [`idea.md`](idea.md)
- [`pipeline_status.md`](pipeline_status.md)
- [`.github/workflows/pr.yml`](../../../../../.github/workflows/pr.yml)
- [`docker-compose.yml`](../../../../../docker-compose.yml)
- [`backend/app/services/demo_seeding.py`](../../../../../backend/app/services/demo_seeding.py)
- [`backend/tests/integration/test_demo_seeding_ubi_full.py`](../../../../../backend/tests/integration/test_demo_seeding_ubi_full.py)
- Sibling [`bug_reseed_failure_blocks_retry_arq_singleton_dedup`](../bug_reseed_failure_blocks_retry_arq_singleton_dedup/idea.md)
- Sibling [`chore_solr_post_pipeline_followups`](../chore_solr_post_pipeline_followups/idea.md)

---

## 1) Purpose

- **Problem:** Post-2026-05-31, no full `pr.yml` run can go green on any branch. The `backend` job has no Solr service container, so the heavy-lane reseed test `test_demo_seeding_ubi_full::test_full_reseed_produces_8_lists_8_studies_per_rung_correct` `ConnectError`s when the orchestrator at [`demo_seeding.py:1379`](../../../../../backend/app/services/demo_seeding.py#L1379) tries to seed the `acme-kb-docs-solr` scenario. Independently, the `smoke` job's `solr` container `exit(1)`s during `make up`, failing the smoke gate. PR #364 had to merge over both reds; further PRs land on the same red baseline.
- **Outcome (Phase 1, this spec):** The `pr.yml` **backend** job goes green on any branch that touches code by making the reseed orchestrator skip-on-unreachable for any engine scenario whose engine isn't reachable (test + product, in lock-step). The smoke job **remains red** until Phase 2 ships separately (smoke healthboot — see [`infra_solr_smoke_stability`](../../planned_features/02_mvp2/infra_solr_smoke_stability/idea.md) + FR-7 / D-5). This is intentional: bundling Phase 2 into this PR would block a clean Phase 1 fix on log evidence we don't yet have from a smoke-job failure run. After both phases ship, every job in `pr.yml` is green on any branch. The Phase 1 fix mirrors the existing Elasticsearch skip pattern at [`test_demo_seeding_ubi_full.py:142`](../../../../../backend/tests/integration/test_demo_seeding_ubi_full.py#L142), so the engine-reachability handling is uniform across all three engines.
- **Non-goal:** Adding a Solr service container to the GHA `backend` job. The configset-upload step that real Solr needs (`make seed-solr` posts to ZooKeeper) is not trivially reproducible from a GHA `services:` container, and the skip-on-unreachable approach gives operators who don't run Solr locally the same behavior CI sees. Also non-goal: changing the on-Solr UBI demo-data shape, the Solr adapter, or any product feature. Also non-goal in Phase 1: stabilizing the Solr container on the smoke runner (Phase 2).

## 2) Current state audit

### Existing implementations

- [`backend/tests/integration/test_demo_seeding_ubi_full.py`](../../../../../backend/tests/integration/test_demo_seeding_ubi_full.py) — the heavy-lane integration test. Already gates on `_check_local_es_credentials_or_skip()` (line 139) and `_es_base_url()` (line 141-142); skips the whole test when ES is unreachable. `_EXPECTED_RUNGS` (lines 71-77) covers **5** scenarios — `acme-products-prod`, `corp-docs-search`, `jobs-marketplace-prod`, `news-search-staging`, `acme-products-rich-prod`. It does **NOT** include `acme-kb-docs-solr` — a pre-existing test gap that masked the Solr count-drift. The test asserts `jl_count == 8` and `study_count == 8` (lines 173-181) unconditionally.
- [`backend/app/services/demo_seeding.py`](../../../../../backend/app/services/demo_seeding.py) — the orchestrator. The Solr branching lives at line 1399 (`if scenario.get("engine_type") == "solr":` → `_seed_solr_scenario(...)`) and the host→Compose URL mapping `http://localhost:8983 → http://solr:8983` lives at line 334 in `_ENGINE_BASE_URL_MAPPING`. When Solr is unreachable, `_seed_solr_scenario` raises `DemoSeedingError` via the `httpx.HTTPError` wrap at line 528, which propagates and fails the whole reseed.
- [`backend/tests/integration/fixtures/es_reachability.py`](../../../../../backend/tests/integration/fixtures/es_reachability.py) — the canonical reachability probe for ES (`_es_base_url()` at line 25-35). 2s timeout, probes `localhost:9200` then `elasticsearch:9200`, returns `""` on no match. This is the exact pattern Capability A will mirror for Solr.
- [`.github/workflows/pr.yml`](../../../../../.github/workflows/pr.yml) — the `backend` job declares services `postgres`, `redis`, `elasticsearch`, `opensearch` (lines 257-309). No `solr`. The `smoke-test` job (lines 487-737) runs `make up` (line 629) which brings up the full Compose stack including the `solr` service.
- [`docker-compose.yml`](../../../../../docker-compose.yml) — the `solr` service (lines 271-285): `solr:10.0`, `SOLR_HEAP: ${SOLR_HEAP_SIZE:-512m}`, `SOLR_MODULES: ltr`, healthcheck `start_period: 30s`, port `127.0.0.1:8983:8983`.

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| No navigation/route changes. One UI **component** is extended in place: [`ui/src/components/dashboard/reset-demo-state-button.tsx`](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx) gains an inline "partial completion" hint + a "Why?" link to the new runbook (FR-5 / AC-11). No links to existing pages move or break. | — | adds outbound link to `docs/03_runbooks/demo-reseed-engine-tolerance.md` |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/integration/test_demo_seeding_ubi_full.py` | `assert jl_count == 8` / `assert study_count == 8` (lines 173-181) | 1 | Make the expected count dynamic based on which engines (and therefore which scenarios) were actually seeded — see FR-4. |
| `backend/tests/integration/test_demo_seeding_ubi_full.py` | `_EXPECTED_RUNGS` (lines 71-77) | 1 | Add `"acme-kb-docs-solr": "rung_2"` (per `SCENARIOS` entry at [`seed_meaningful_demos.py:802`](../../../../../scripts/seed_meaningful_demos.py#L802)), gated on Solr being reachable per FR-4. |
| `backend/tests/integration/test_demo_seeding_ubi_full.py` | `_SCENARIO_TARGET` (lines 80-86) | 1 | Add `"acme-kb-docs-solr": "acme-kb-docs"` for the readiness probe, gated on Solr being reachable. |
| `backend/tests/integration/test_demo_seeding_ubi_full.py` | `_EXPECTED_UBI_CONVERTERS` (lines 89-93) | 1 | Add `"acme-kb-docs-solr": "hybrid_ubi_llm"` gated on Solr being reachable. |

### Existing behaviors affected by scope change

- **Reseed orchestrator's reaction to an unreachable engine.** Current: any `httpx` error during the Solr (or ES, or OS) seed step propagates as `DemoSeedingError`, fails the whole reseed, sets `status=failed`. New: when an engine is unreachable at scenario-dispatch time, the orchestrator emits a structured `demo_reseed_scenario_skipped_engine_unreachable` log event and a single WARN line at the end of the reseed summarizing the skipped scenarios, and the reseed completes with a partial count instead of failing. Decision needed: yes (locked at D-1 below).
- **Heavy-lane test's count assertion.** Current: hard-codes `8 == 8`. New: parameterized by which engines were reachable when the orchestrator ran. Decision needed: yes (locked at D-3 below).

---

## 3) Scope

### In scope

**Phase 1 (this spec; one PR):**
- (FR-1) Add a Solr reachability probe fixture symmetric to `es_reachability.py`.
- (FR-2) Add an `is_engine_reachable(...)` reachability gate to the demo-reseed orchestrator that runs once per scenario at dispatch time; on `False`, skip the scenario with a structured info log + accumulate the skipped slug into the progress summary; emit a single WARN line at end-of-reseed if any scenarios were skipped.
- (FR-3) Update the CLI counterpart in `scripts/seed_meaningful_demos.py` to use the same gate so `make seed-demo` is engine-tolerant.
- (FR-4) Update `test_demo_seeding_ubi_full.py` to compute expected counts and per-scenario assertions based on which engines were reachable at orchestrator-start. Add the missing `acme-kb-docs-solr` entries to `_EXPECTED_RUNGS`, `_SCENARIO_TARGET`, and `_EXPECTED_UBI_CONVERTERS`.
- (FR-5) Surface skipped engines in `ReseedStatusResponse.scenarios_skipped: list[str]` (top-level field, NOT inside the nested `summary` object) so the GET status endpoint + UI can report partial-reseed cleanly (closes the contract with Capability C / sibling `bug_reseed_failure_blocks_retry_arq_singleton_dedup`). Also: the **worker** (`backend/workers/demo_reseed.py`) special-cases the all-engines-unreachable marker to write the stable `failed_reason="all_engines_unreachable"` token (the reseed is async — there is no synchronous error envelope; the signal travels through the Redis status).
- (FR-6) Documentation update: data-model.md (no — N/A), runbook addition at `docs/03_runbooks/demo-reseed-engine-tolerance.md`, CLAUDE.md "Common Pitfalls" line.

**Phase 2 (separate PR, tracked as `infra_solr_smoke_stability`):**
- (FR-7) Smoke job: stabilize the Solr container. Path TBD pending log evidence — default lean is `SOLR_HEAP_SIZE=256m` in the smoke job environment first, then `start_period` extension, then smoke-job tolerance for Solr-down as last resort. Q-1 in §19 captures the diagnostic protocol.

### Out of scope

- Adding a `solr` service container to the GHA backend job.
- Changes to the `SolrAdapter`, the `seed_solr_products` script, or any Solr-side product code.
- Changes to UBI generation, judgment generation, or study orchestration.
- Multi-tenancy, auth, or audit-event emission (the latter intentionally — `audit_log` has not yet shipped; latest migration is `0022_solr_engine_auth_check`).
- Backfilling missing audit-event instrumentation in the existing reseed flow (separate concern; not introduced by this feature).

### API convention check

This feature does **not** add new endpoints or change any path/method. It modifies one service-layer function (`reseed_demo_state`), one Pydantic response model (`ReseedStatusResponse` — adds the top-level `scenarios_skipped: list[str]` field), the Arq worker (`backend/workers/demo_reseed.py` — special-cases the all-engines-unreachable marker to write the stable `failed_reason` token), one CLI script, the heavy-lane integration test, and one UI component (`reset-demo-state-button.tsx` + its type mirror).

- **Endpoint prefix convention:** N/A — no new endpoints.
- **Router namespace:** N/A — existing `_test.py` handlers for `POST /api/v1/_test/demo/reseed` (202, async enqueue) + `GET /api/v1/_test/demo/reseed/status` (200, Redis-backed poll).
- **HTTP methods for CRUD:** N/A — paths + methods unchanged.
- **Async architecture (critical):** the reseed POST enqueues an Arq job and returns `202` immediately with an initial `ReseedStatusResponse(status="running")`. The orchestrator runs in the worker. Therefore **failures do NOT surface as a synchronous error envelope on the POST body** — they surface via the worker writing `status="failed"` + `failed_reason` to the Redis status key, which the GET status endpoint returns. The only synchronous error envelopes on these endpoints are the pre-enqueue guards `ARQ_POOL_UNAVAILABLE` (503) and `SEED_IN_PROGRESS` (409), both unchanged by this spec.
- **All-engines-unreachable signal:** travels through `ReseedStatusResponse.status == "failed"` + `failed_reason == "all_engines_unreachable"` (a stable machine-readable token), NOT through a wire `error_code`. No new HTTP error code is introduced.
- **Auth error shape:** N/A (MVP1–3, no auth).

### Phase boundaries

- **Phase 1 (this spec):** FR-1 → FR-6. Unblocks `backend` CI immediately; smoke remains red until Phase 2. Rationale: Phase 1 is pure-code work with no external dependency. Ship now.
- **Phase 2 (separate PR — tracked as [`infra_solr_smoke_stability`](../../planned_features/02_mvp2/infra_solr_smoke_stability/idea.md)):** FR-7. Rationale: needs log evidence from a smoke-job failure (`docker compose logs solr`) to commit to the right stabilization lever. Treating it as a separate PR keeps Phase 1 reviewable in isolation and lets the smoke-stabilization work be driven by data rather than guesswork.

## 4) Product principles and constraints

- **CI hermeticity.** The fix MUST keep CI hermetic — no managed cloud, no external Solr cluster. This rules out option (a) "add Solr service container with configset bootstrap" because that approach has too much surface area (configset ZooKeeper upload from a GHA `services:` step is fragile); option (b) keeps the backend job lean and predictable.
- **Symmetry with existing engine handling.** ES uses `_es_base_url()` + `pytest.skip(...)`; the new Solr handling MUST follow the same shape so the engine-handling code is uniform.
- **Lock-step product + test.** The orchestrator-side skip and the test-side count adjustment MUST ship together so CI behavior matches operator-local behavior (D-2).
- **Loud-but-survivable.** A skipped engine MUST emit a WARN log at end-of-reseed; silent partial-seeds are a deferral-of-investigation, not a fix. The structured log event MUST carry the slug + scenarios skipped so operators can re-run the engine and reseed.
- **Demo orchestrator scope is local Compose engines only.** All three engines in this repo's local Compose run security-disabled (ES `xpack.security.enabled: "false"` + OS `DISABLE_SECURITY_PLUGIN: "true"` + Solr stock-no-`security.json` — see [`docker-compose.yml:248-285`](../../../../../docker-compose.yml#L248) + CLAUDE.md "Common Pitfalls" "**Do not** install ES + OpenSearch with security plugins enabled in the local Compose"). The `is_engine_reachable` probe and the reseed orchestrator itself are scoped to those local engines; they are **not** designed for secured operator clusters and do not negotiate auth.

### Anti-patterns

- **Do not** add a `solr` service container to the GHA `backend` job — the configset bootstrap step is too brittle and was explicitly rejected at D-1.
- **Do not** make the orchestrator silently swallow connection errors. The skip path is conditional on the reachability probe returning `False` BEFORE the scenario dispatches; if dispatch begins and then an `httpx` call fails mid-scenario, that's still a `DemoSeedingError` (it indicates a transient failure, not "engine not present").
- **Do not** branch the test on `os.environ.get("CI")`. Reachability is the right gate, not "are we in CI" — operators running locally without Solr deserve the same behavior CI gets.
- **Do not** invent a Solr `cluster_credentials.yaml` parallel to `local-es`. The reachability probe alone is sufficient (Solr in this repo runs security-disabled per the `docker-compose.yml` comment at line 254-256). The `solr_basic` auth_kind in the cluster row stays — it's harmless against a security-disabled instance.
- **Do not** add a stricter "Solr required in CI" gate. The point of skip-on-unreachable is that Solr is **optional** in CI; gating on it would re-introduce the failure mode this spec eliminates.
- **Do not** assume `is_engine_reachable` works against secured engines. The probe is unauthenticated by design (matches the local Compose engine security posture). If a future operator secures their local engine, the probe will return `False` (401 ≠ 200 + expected body shape) and the scenario will skip — operator action required. This is acceptable for the demo orchestrator's local-Compose-only scope per the principle above.

## 5) Assumptions and dependencies

- **Dependency:** `ElasticAdapter` + `OpenSearchAdapter` continue to work in CI under the existing `services:` containers (no change). Status: implemented + green pre-2026-05-31.
- **Dependency:** The `_seed_solr_scenario` Solr seed helper remains correct when Solr IS reachable (Phase 2 operator-local path). Status: implemented (PR #348). No change required.
- **Dependency:** `SCENARIOS` list at `scripts/seed_meaningful_demos.py:186` continues to use `engine_type` as the engine-dispatch hint. Status: implemented + asserted at module-import.
- **Risk if missing:** None — this feature only ADDs a reachability gate; without it the existing behavior persists (fail-loud).

## 6) Actors and roles

- Primary actor(s): the CI runner (GitHub Actions). Secondary: operators running `make seed-demo` locally without one of the engines started.
- Role model: N/A — single-tenant install, no auth surface.
- Permission boundaries: N/A.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` table has not yet shipped (latest migration is `0022_solr_engine_auth_check`, no `AuditLog` ORM model exists). The reseed orchestrator does not emit audit events today; this feature does not add or remove any.

---

## 7) Functional requirements

### FR-1: Solr reachability probe fixture

- Requirement:
  - The system **MUST** add a new module `backend/tests/integration/fixtures/solr_reachability.py` exporting `_solr_base_url() -> str` and `solr_required` (pytest skip marker).
  - The probe **MUST** match `_es_base_url`'s shape byte-for-byte modulo the port + version-shape: try `http://localhost:8983` then `http://solr:8983` with a 2.0s `httpx.Client` timeout, returning the matching base URL or `""`.
  - The probe **MUST** verify reachability via `GET /solr/admin/info/system` returning HTTP 200 (matching the Compose healthcheck at [`docker-compose.yml:281`](../../../../../docker-compose.yml#L281)); a 200 with a non-Solr body fails the probe and returns `""`. Specifically: parse the JSON and assert `responseHeader.status == 0` and `lucene` key present (Solr's standard system-info envelope).
- Notes: the existing `_es_base_url` checks `"version" in r.json()` — we need an analogous Solr-shape check so probing accidentally lands at the wrong service (e.g., a misconfigured port) doesn't false-positive.

### FR-2: Orchestrator skip-on-unreachable for any engine scenario

- Requirement:
  - `backend/app/services/demo_seeding.py` **MUST** add a new helper `async def is_engine_reachable(engine_base_url: str, engine_type: Literal["elasticsearch", "opensearch", "solr"], *, timeout_s: float = 2.0) -> bool` that issues a single GET to the engine's standard health path (Solr: `/solr/admin/info/system`; ES/OS: `/`) and returns `True` iff HTTP 200 and the body has the expected engine-shape (Solr: `lucene` key + `responseHeader.status == 0`; ES/OS: `version` key). On any `httpx.HTTPError`, `httpx.TimeoutException`, or unexpected exception, the probe MUST return `False` (and log the unexpected-exception class at WARN per AC-9). The probe is **unauthenticated by design** — matches the local Compose engine security posture per §4.
  - `reseed_demo_state(...)` **MUST** call `is_engine_reachable` ONCE per scenario at scenario-dispatch time (immediately after `_resolve_engine_base_url(...)` resolves the in-container URL). If `False`, the orchestrator **MUST** skip the scenario, emit a structured log event `demo_reseed_scenario_skipped_engine_unreachable` carrying `{slug, engine_type, engine_base}`, and accumulate the slug into a new `scenarios_skipped: list[str]` field on the running `ReseedStatusResponse`. **This gate MUST also cover the rich ESCI scenario** (`acme-products-rich-prod`, an Elasticsearch scenario seeded separately from the `SCENARIOS` loop via `_resolve_engine_base_url(ES)` at [`demo_seeding.py:990`](../../../../../backend/app/services/demo_seeding.py#L990)): when ES is unreachable, the rich scenario is skipped and its slug appended to `scenarios_skipped`, same as any `SCENARIOS` entry. The reachability-relevant scenario set is therefore the 5 `SCENARIOS` entries **plus** the rich scenario (6 total — matching `scenarios_total = len(SCENARIOS) + 1`).
  - If at least one scenario was skipped AND at least one scenario completed successfully, the orchestrator **MUST** emit one WARN-level summary line at end-of-reseed: `demo_reseed_partial_completion_engines_unreachable`, with `{scenarios_skipped, scenarios_completed}` as structured fields.
  - **The existing `ReseedStatusLiteral` enum (`Literal["idle", "running", "complete", "failed"]` at [`demo_seeding.py:220`](../../../../../backend/app/services/demo_seeding.py#L220)) is NOT extended.** Partial-completion runs surface via `status == "complete"` AND `scenarios_skipped` non-empty. The new field is additive; the enum stays closed. See D-4 (flipped) in §19.
  - **Invariant — all engines unreachable is a failure, not a partial.** If `scenarios_completed == 0` AND `scenarios_skipped` is non-empty (i.e., nothing succeeded), the orchestrator **MUST** raise a typed exception `AllEnginesUnreachableError(DemoSeedingError)` that (a) carries the skipped slugs as an attribute (`exc.scenarios_skipped: list[str]`) and (b) has `str(exc) == "all_engines_unreachable"`. The reseed is async (the POST `/api/v1/_test/demo/reseed` returns 202 and an Arq worker runs the orchestrator), so this exception is caught by the worker's existing `except (DemoSeedingError, httpx.HTTPError, Exception)` barrier at [`backend/workers/demo_reseed.py:175`](../../../../../backend/workers/demo_reseed.py#L175), which currently writes a fresh `ReseedStatusResponse(status="failed", ...)` that drops the skip list. **The worker MUST be updated to special-case `isinstance(exc, AllEnginesUnreachableError)`** and write a failed status that carries `failed_reason="all_engines_unreachable"` (the stable token, NOT the generic `f"{type(exc).__name__}: {str(exc)[:200]}"`), `scenarios_skipped=exc.scenarios_skipped` (all slugs), and `scenarios_completed=0`. This is what makes the §8.3 all-engines-unreachable GET-status example reproducible. Routing this case through `status="failed"` (rather than `status="complete"` with `scenarios_completed == 0`) prevents Arq's `keep_result` cache from masquerading a no-op reseed as a success and locking out retries for the dedup window (see sibling [`bug_reseed_failure_blocks_retry_arq_singleton_dedup`](../bug_reseed_failure_blocks_retry_arq_singleton_dedup/idea.md)).
- Notes: the gate is BEFORE dispatch — so transient mid-scenario `httpx` errors still surface as `DemoSeedingError` (unchanged) and produce the generic `failed_reason`. The skip path distinguishes "Solr not present" from "Solr crashed mid-seed." **There is NO synchronous error envelope for the all-engines-unreachable case** — the reseed is async, the POST already returned 202 before the orchestrator ran. The signal travels entirely through the Redis-backed `ReseedStatusResponse` (`status` + `failed_reason`).

### FR-3: CLI parity in `make seed-demo`

- Requirement:
  - `scripts/seed_meaningful_demos.py` **MUST** use the same `is_engine_reachable` gate. When a scenario's engine is unreachable, the CLI **MUST** emit a `[skip] <slug> — <engine_type> unreachable at <host_base_url>` line on stderr, omit the scenario from the per-scenario loop, and accumulate the slug into the failure-summary's `skipped` list (separate from `failures`).
  - The CLI's exit code **MUST** be:
    - `1` when `failures` is non-empty (a scenario errored mid-flight) — unchanged.
    - `1` when `completed == 0 AND skipped` is non-empty (all engines unreachable) — print an explicit `ERROR: all engines unreachable — start at least one engine (ES/OS/Solr) and retry` line on stderr. This MIRRORS the service-layer `SEED_NO_ENGINES_REACHABLE` invariant (FR-2 / AC-10) so the CLI and the orchestrator agree: a no-op reseed is a failure, not a success.
    - `0` when at least one scenario completed AND `skipped` is non-empty (genuine partial success).
    - `0` when all scenarios completed.
- Notes: the existing `failures.append((s["slug"], exc))` pattern at `scripts/seed_meaningful_demos.py:1789` already distinguishes per-scenario failures; this FR extends it with a parallel `skipped` list AND the `completed == 0` hard-fail guard. The CLI has no Arq-cache risk (it's a one-shot process), but aligning its exit semantics with the service keeps operator mental-model consistent across both invocation paths.

### FR-4: Heavy-lane test count assertion (dynamic by reachability)

- Requirement:
  - `backend/tests/integration/test_demo_seeding_ubi_full.py` **MUST** be updated so that, BEFORE invoking `reseed_demo_state`, it computes the **expected** per-scenario coverage using the **same resolved-URL probe the orchestrator will use** — NOT a host-first fixture probe. Concretely: the test MUST call the shared helper `snapshot_engine_reachability(SCENARIOS)` that FR-2 exposes, which internally resolves each scenario's `host_base_url` through `_resolve_engine_base_url(...)` (the same function the orchestrator calls at dispatch) and then calls `is_engine_reachable(resolved_url, engine_type)` — the identical helper + identical resolved URL the orchestrator evaluates. This guarantees the test's predicted skip-set matches the orchestrator's actual skip-set even though the orchestrator runs inside the API container (Compose DNS).
  - **Shared-helper return shape (canonical):** `snapshot_engine_reachability(scenarios) -> dict[str, bool]` is **keyed by scenario slug** (NOT engine name), e.g. `{"acme-products-prod": True, "acme-kb-docs-solr": False, ...}`. Multiple scenarios can share one engine; keying by slug avoids the engine→slug expansion ambiguity. The reachability for a slug is the reachability of that scenario's resolved engine URL. This is the same shape as `scenarios_skipped` (slug list) so the test asserts `set(slug for slug, ok in snapshot.items() if not ok) == set(summary.scenarios_skipped)`.
  - Per-scenario expected `(lists, studies)` contributions are precomputed from `SCENARIOS` (each scenario contributes `(2, 2)` when it has `ubi_target_rung` non-None, else `(1, 1)`), summed across the scenarios whose slug is `True` in the snapshot.
  - The test **MUST** add `acme-kb-docs-solr` to `_EXPECTED_RUNGS` (`"rung_2"`), `_SCENARIO_TARGET` (`"acme-kb-docs"`), and `_EXPECTED_UBI_CONVERTERS` (`"hybrid_ubi_llm"`). Each of these dicts **MUST** be iterated conditionally on the scenario's slug being `True` in the snapshot.
  - **ES-required gate (semantic, not the old host-first probe):** when NO ES-backed scenario is reachable per the snapshot, the test MUST skip entirely (the heavy-lane test cannot validate anything without ES — ES is the dominant engine). This REPLACES the current `pytest.skip(...)` at line 142 that uses the host-first `_es_base_url()` fixture: the skip decision now derives from the same shared snapshot, not a separate host-first probe, so the test never predicts reachability in a different URL namespace than the orchestrator.
- Notes: this is the locked answer to Q-3 — skip only Solr-specific assertions when Solr is unreachable rather than skipping the whole test. Operators running heavy-lane tests against a stack where Solr IS up will see the full 10-list / 10-study coverage; CI sees 8/8. The shared-snapshot requirement (GPT-5.5 cycle-2 Finding 4 + cycle-3 Findings 1 & 2) keeps the test's skip-set and the orchestrator's skip-set in the same URL namespace AND the same key space (scenario slugs).

### FR-5: New response field `scenarios_skipped` on the reseed status (no enum change)

- Requirement:
  - The `ReseedStatusResponse` Pydantic model (in [`backend/app/services/demo_seeding.py`](../../../../../backend/app/services/demo_seeding.py)) **MUST** gain a new field `scenarios_skipped: list[str] = Field(default_factory=list)`. Existing fields are unchanged.
  - The `ReseedStatusLiteral` enum at `demo_seeding.py:220` is **NOT** extended — partial-completion is surfaced via `status="complete"` + `scenarios_skipped` non-empty. All-engines-unreachable surfaces via `status="failed"` per the FR-2 invariant.
  - The TypeScript mirror at [`ui/src/lib/api/demo-reseed.ts`](../../../../../ui/src/lib/api/demo-reseed.ts) **MUST** add `scenarios_skipped: string[]` to the `ReseedStatusResponse` interface. The `ReseedStatusLiteral` type stays exactly `'idle' | 'running' | 'complete' | 'failed'`.
  - The reseed UI button at [`ui/src/components/dashboard/reset-demo-state-button.tsx`](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx) **MUST** render a "partial completion — N engines skipped" hint inline next to the success state when `status === 'complete' && scenarios_skipped.length > 0`. Minimal UX: a small italic line listing the skipped slugs and linking to the new runbook (FR-6). The vitest fixture at [`ui/src/__tests__/components/dashboard/reset-demo-state-button.test.tsx`](../../../../../ui/src/__tests__/components/dashboard/reset-demo-state-button.test.tsx) MUST gain a `STATUS_COMPLETE_PARTIAL` case alongside the existing `STATUS_IDLE / STATUS_RUNNING / STATUS_COMPLETE / STATUS_FAILED` fixtures.
- Notes: this design choice (additive field + reuse `complete`) replaces the original draft's "add `succeeded_partial` wire value" approach. The flip is documented in D-4 (revised). Rationale: smaller wire-contract surface, existing polling logic at `demo-reseed.ts:85-94` already stops on any non-`running` status so no change is needed there; the UI only needs a hint inside the existing `complete` rendering branch.

### FR-6: Documentation updates

- Requirement:
  - A new runbook at `docs/03_runbooks/demo-reseed-engine-tolerance.md` **MUST** be added covering: when scenarios skip, how to inspect `scenarios_skipped`, how to re-seed after starting the missing engine, and the contract that `status == "complete"` with non-empty `scenarios_skipped` is a legitimate partial-completion (not a failure).
  - `CLAUDE.md` **MUST** gain a one-line entry in the "Common Pitfalls" section (or equivalent): "**Do not** treat a reseed with `status == \"complete\"` and non-empty `scenarios_skipped` as a failure — it's a legitimate partial completion. See `docs/03_runbooks/demo-reseed-engine-tolerance.md`."
  - The "Key Runbooks" table at the bottom of `CLAUDE.md` **MUST** gain a row for the new runbook.
- Notes: no `data-model.md` change (no schema change). No `architecture.md` change (no new layer).

### FR-7: Smoke job Solr stabilization (Phase 2 — separate PR)

- Requirement:
  - The `smoke-test` job in `.github/workflows/pr.yml` **MUST** make the Solr container reliably boot on the runner. The chosen lever is selected by reading `docker compose logs solr` from a smoke-job failure run, in this priority:
    1. `SOLR_HEAP_SIZE=256m` in the smoke job's `env:` block, matching the backend job's `ES_JAVA_OPTS: -Xms256m -Xmx256m` pattern at [`pr.yml:287`](../../../../../.github/workflows/pr.yml#L287).
    2. Extended `start_period` for the Solr healthcheck (currently `30s` at [`docker-compose.yml:285`](../../../../../docker-compose.yml#L285)) — bump to `60s` or `90s`.
    3. Smoke-job tolerance for Solr being down: drop `solr` from the failure-log collection at [`pr.yml:719`](../../../../../.github/workflows/pr.yml#L719) and skip any Solr-specific smoke assertion (the current tutorial-path smoke at `backend/tests/smoke/test_tutorial_path.py` is ES-only — verify before relying on this).
- Notes: this FR ships in a follow-up PR — Phase 2. The Phase 2 spec / impl-plan will be generated from `infra_solr_smoke_stability` once log evidence is in hand.

## 8) API and data contract baseline

### 7.1 Endpoint surface

No new endpoints. The existing `POST /api/v1/_test/demo/reseed` + `GET /api/v1/_test/demo/reseed/status` endpoints are unchanged.

### 7.2 Contract rules

- The new `scenarios_skipped: list[str]` field on `ReseedStatusResponse` MUST default to `[]` (never `None`).
- `ReseedStatusLiteral` is NOT extended by this spec — partial-completion is `status == "complete" AND len(scenarios_skipped) > 0`. No new wire-value enum members.
- **The all-engines-unreachable signal travels ONLY through the Redis-backed status** (`ReseedStatusResponse`), because the reseed is async (POST returns 202; the orchestrator runs in the Arq worker). There is no synchronous error envelope for this case.
  - The **GET `/api/v1/_test/demo/reseed/status`** response (the `ReseedStatusResponse` model, which has `model_config = ConfigDict(extra="forbid")`) surfaces the failure as `status == "failed"` + `failed_reason == "all_engines_unreachable"` (a stable machine-readable token) + `scenarios_skipped` = all slugs. The model has NO `error_code` field and MUST NOT gain one.
  - **No new HTTP wire `error_code` is introduced.** `failed_reason` is the machine-readable discriminator. This mirrors how mid-scenario failures already surface: `status == "failed"` + a `failed_reason` string written by the worker's exception barrier ([`demo_reseed.py:185-193`](../../../../../backend/workers/demo_reseed.py#L185)). The only change is that the all-engines-unreachable case writes the STABLE token `"all_engines_unreachable"` instead of the generic `f"{type(exc).__name__}: {str(exc)[:200]}"`.

### 7.3 Response examples

`GET /api/v1/_test/demo/reseed/status` — success-partial example (the new field this spec adds; status stays `complete`):

```json
{
  "status": "complete",
  "scenarios_total": 6,
  "scenarios_completed": 5,
  "scenarios_skipped": ["acme-kb-docs-solr"],
  "current_step": "complete",
  "started_at": "2026-06-01T15:42:00Z",
  "finished_at": "2026-06-01T15:54:32Z",
  "failed_reason": null,
  "summary": { "clusters_created": 5, "query_sets_created": 5, "studies_completed": 8, "proposals_created": 0, "duration_ms": 752341 },
  "steps": ["wipe", "acme-products-prod: indexing 47 docs into products", "..."]
}
```

`GET /api/v1/_test/demo/reseed/status` — success example (all scenarios green; only difference from today is the new `scenarios_skipped: []`):

```json
{
  "status": "complete",
  "scenarios_total": 6,
  "scenarios_completed": 6,
  "scenarios_skipped": [],
  "current_step": "complete",
  "started_at": "2026-06-01T15:42:00Z",
  "finished_at": "2026-06-01T16:01:18Z",
  "failed_reason": null,
  "summary": { "clusters_created": 6, "query_sets_created": 6, "studies_completed": 10, "proposals_created": 0, "duration_ms": 919023 },
  "steps": ["..."]
}
```

All-engines-unreachable failure example (new — surfaces via the existing `failed` status + the stable `failed_reason` token; this is the GET-status payload, NOT a synchronous envelope, because the reseed is async):

```json
{
  "status": "failed",
  "scenarios_total": 6,
  "scenarios_completed": 0,
  "scenarios_skipped": ["acme-products-prod", "corp-docs-search", "news-search-staging", "jobs-marketplace-prod", "acme-products-rich-prod", "acme-kb-docs-solr"],
  "current_step": "all engines unreachable",
  "started_at": "2026-06-01T15:42:00Z",
  "finished_at": "2026-06-01T15:42:12Z",
  "failed_reason": "all_engines_unreachable",
  "summary": null,
  "steps": []
}
```

Mid-scenario failure example (GET status; unchanged — same shape as today; the worker writes the generic `failed_reason` string for non-no-engines failures):

```json
{
  "status": "failed",
  "scenarios_total": 6,
  "scenarios_completed": 2,
  "scenarios_skipped": [],
  "current_step": "acme-products-prod: indexing",
  "started_at": "2026-06-01T15:42:00Z",
  "finished_at": "2026-06-01T15:43:10Z",
  "failed_reason": "DemoSeedingError: acme-products-prod/put_index: HTTP 503 …",
  "summary": null,
  "steps": ["..."]
}
```

Pre-enqueue guard envelopes (synchronous, on the POST — unchanged by this spec): `ARQ_POOL_UNAVAILABLE` (503) and `SEED_IN_PROGRESS` (409) use the standard `{"detail": {"error_code", "message", "retryable"}}` envelope. These are the ONLY synchronous error envelopes on the reseed endpoints; reseed-execution failures (including all-engines-unreachable) surface via the GET status payload above.

### 7.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `status` (reseed) | `idle`, `running`, `complete`, `failed` (**unchanged** by this spec) | [`backend/app/services/demo_seeding.py:220`](../../../../../backend/app/services/demo_seeding.py#L220) `ReseedStatusLiteral` Literal | [`ui/src/lib/api/demo-reseed.ts:27`](../../../../../ui/src/lib/api/demo-reseed.ts#L27) `ReseedStatusLiteral` (mirrors backend — must stay in sync) consumed by [`ui/src/components/dashboard/reset-demo-state-button.tsx`](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx) |

**Rule:** the original draft proposed adding `succeeded_partial` to this enum. **That change has been dropped** (see D-4 revised). The closed enum stays; partial-completion is detected via `scenarios_skipped.length > 0` while `status === 'complete'`. Verification during implementation: `grep -rn '"complete"\|ReseedStatusLiteral' backend/ ui/src/` to confirm no other consumers need updating beyond the two cited above.

### 7.5 Error code catalog

**No new HTTP error code is introduced.** The reseed is async — execution failures never produce a synchronous error envelope (see §8 "Async architecture"). Instead, the all-engines-unreachable case is discriminated by a stable `failed_reason` **token** on the GET-status payload:

| Discriminator | Surface | Value | Meaning |
|---|---|---|---|
| `failed_reason` token | `GET /api/v1/_test/demo/reseed/status` body (`status == "failed"`) | `"all_engines_unreachable"` | All scenarios skipped because no engine was reachable at probe time. Written by the worker special-casing the `AllEnginesUnreachableError(DemoSeedingError)` raised by the orchestrator when `scenarios_completed == 0 AND scenarios_skipped` is non-empty. The failed status also carries `scenarios_skipped` (all slugs) + `scenarios_completed=0` (from the exception's `scenarios_skipped` attribute). Stable (never reworded) so tests + operators can match on it, distinct from the generic `f"{type}: {msg}"` reason written for mid-scenario failures. |

The synchronous pre-enqueue guards `ARQ_POOL_UNAVAILABLE` (503) and `SEED_IN_PROGRESS` (409) are unchanged and remain the only synchronous error envelopes on the reseed endpoints.

## 9) Data model and state transitions

No schema changes. No new tables. No new columns. Alembic head stays at `0022_solr_engine_auth_check`.

### Required invariants

- **Partial-completion is encoded in `scenarios_skipped`, not in `status`.** `status == "complete" AND scenarios_skipped non-empty` is a legitimate terminal state ("partial completion — some engines were not reachable"). `status == "complete" AND scenarios_completed == 0` MUST be unreachable (the orchestrator MUST raise the all-engines-unreachable marker instead, yielding `status == "failed"`).
- **All-engines-unreachable is a hard failure.** When `scenarios_completed == 0`, the orchestrator MUST raise `AllEnginesUnreachableError(DemoSeedingError)` carrying `scenarios_skipped`; the worker special-cases it to write `status = "failed"` + `failed_reason = "all_engines_unreachable"` (stable token) + `scenarios_skipped` (all slugs) + `scenarios_completed = 0` to the Redis status (FR-2 + FR-5). No HTTP wire error code — the reseed is async.
- **The `is_engine_reachable` probe is called BEFORE `_seed_solr_scenario` (or any ES scenario seed) — never after.** A scenario that begins dispatch and then errors is a `DemoSeedingError`, not a skip.
- **Probe is total** — it never raises. Any unexpected exception is treated as "unreachable" (AC-9). This prevents a transient DNS hiccup from breaking the whole reseed.

### State transitions

`ReseedStatusLiteral` transitions stay as-is: `idle → running → (complete | failed) → idle`. **No new states.** Partial completion is a flavor of `complete`, distinguished by `scenarios_skipped.length > 0`.

### Idempotency/replay behavior

Unchanged. The existing Arq-singleton dedup on `demo_reseed:singleton` is independent of the skip path; it still applies. Note: partial-complete runs (`status == "complete"` with non-empty `scenarios_skipped`) ARE terminal successes and are kept in Arq's result cache for the configured `keep_result` window like any other `complete` run — which is exactly why the all-engines-unreachable case must be `failed` and not `complete` (D-6): a no-op cached as a success would wedge retries per sibling [`bug_reseed_failure_blocks_retry_arq_singleton_dedup`](../bug_reseed_failure_blocks_retry_arq_singleton_dedup/idea.md).

## 10) Security, privacy, and compliance

- Threats: none new. The probe sends a GET to a localhost / Compose-DNS Solr endpoint; no auth, no payload, no PII.
- Controls: existing `secrets/cluster_credentials.yaml` mount unchanged.
- Secrets/key handling: N/A — no new secrets.
- Auditability: N/A (`audit_log` not yet shipped).
- Data retention/deletion/export impact: N/A.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** The reseed UI button at [`ui/src/components/dashboard/reset-demo-state-button.tsx`](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx) — already exists on the dashboard. No new pages or routes; this spec extends the existing component's `complete`-state render.
- **Labeling taxonomy:** the current rendering for `status === 'complete'` displays a generic success message. After this PR, when `scenarios_skipped.length > 0`, the component MUST add an inline italic hint below the success message: `Partial completion — N engine(s) skipped: <slug>, <slug>, …` with a "Why?" link to the new runbook (FR-6 / `docs/03_runbooks/demo-reseed-engine-tolerance.md`).
- **Content hierarchy:** the partial hint sits inside the existing success-state block, below the primary success line. It's secondary disclosure — not a banner.
- **Progressive disclosure:** the hint is collapsed by default (a short summary like `Partial — 1 engine skipped`); the operator can hover/click the "Why?" link to navigate to the runbook for the full explanation + retry steps. No modal, no expansion panel in this PR.
- **Relationship to existing pages:** extends the existing success-state render. No removal or replacement of existing functionality.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---------|-------------------|---------|-----------|
| "Partial completion" hint (inline, on `status === 'complete' && scenarios_skipped.length > 0`) | "Some demo scenarios were skipped because their engine wasn't reachable. See the runbook to retry." | hover on the "Why?" link inside the hint | inline (below the success line) |

**Glossary key:** verify during implementation. Grep `grep "reseed\|demo" ui/src/lib/glossary.ts` to determine whether to extend an existing entry or add a new `demo_reseed_partial` key. If a new key is needed, add it in the same story that updates the button component (per `chore_form_dropdown_primitive` / glossary discipline).

### Primary flows

1. **CI backend job runs the heavy-lane reseed test.** The test probes ES, OS, Solr. ES + OS reachable, Solr not. The orchestrator seeds 5 scenarios, skips `acme-kb-docs-solr`, returns `status="complete"` with `scenarios_skipped=["acme-kb-docs-solr"]`. Test asserts the expected per-engine counts and per-engine rung/converter dicts dynamically based on what was reachable.
2. **Operator runs `make seed-demo` locally without Solr started.** CLI probes each engine, prints `[skip] acme-kb-docs-solr — solr unreachable at http://localhost:8983` on stderr, completes the other 5 scenarios, exits 0.
3. **Operator triggers the reseed UI button against a full local stack (all 3 engines up).** All 6 scenarios complete, `status = complete`, `scenarios_skipped = []`. No change from today.

### Edge/error flows

- **All engines unreachable.** Orchestrator raises `DemoSeedingError("all_engines_unreachable")` → `status = "failed"`, `failed_reason = "all_engines_unreachable"`, error code `SEED_NO_ENGINES_REACHABLE`, `scenarios_completed = 0`, `scenarios_skipped` = every slug. This is a FAILURE, not a partial-complete (D-6 / AC-10) — preventing the Arq dedup wedge. Edge case: when the probe itself errors transiently (DNS, etc.), it returns `False` → that's indistinguishable from "engine genuinely absent." Acceptable — the failure path captures every slug + URL so an operator can diagnose.
- **One scenario reachable at probe time but unreachable mid-seed.** The orchestrator's existing `DemoSeedingError` path fires — this is intentional and unchanged. The skip path is BEFORE dispatch, not a graceful-degradation mid-scenario.
- **`is_engine_reachable` itself raises an unexpected exception (not `httpx.HTTPError` / `httpx.TimeoutException`).** The orchestrator MUST treat this as "unreachable" and skip the scenario, NOT propagate the exception (probing must never break the reseed). Captured as a defensive Programming pattern in the implementation plan.

## 12) Given/When/Then acceptance criteria

### AC-1: Reseed skips unreachable Solr scenario, completes others (partial complete)

- **Given** ES + OS are reachable but Solr is not (CI backend-job posture)
- **When** `reseed_demo_state(...)` runs
- **Then** the orchestrator MUST seed 5 scenarios (all ES + OS scenarios), set `scenarios_skipped = ["acme-kb-docs-solr"]`, leave `status = "complete"` (NOT a new enum value), emit `demo_reseed_partial_completion_engines_unreachable` at WARN, and the route handler's status response MUST include `scenarios_skipped` non-empty alongside `status = "complete"`

### AC-2: Reseed completes fully when all engines reachable

- **Given** ES + OS + Solr are all reachable (operator-local full-stack posture)
- **When** `reseed_demo_state(...)` runs
- **Then** the orchestrator MUST seed all 6 scenarios, set `scenarios_skipped = []`, set `status = "complete"`
- Example values:
  - Expected: `scenarios_completed == 6`, `scenarios_skipped == []`, `status == "complete"`

### AC-3: Reseed fails when a scenario errors mid-flight (existing behavior preserved)

- **Given** ES is reachable at probe time but the index PUT fails with HTTP 503
- **When** `reseed_demo_state(...)` runs
- **Then** the orchestrator MUST raise `DemoSeedingError`, the status MUST be `failed`, and `scenarios_skipped` MUST NOT contain that scenario (it was attempted, not skipped)

### AC-4: Heavy-lane test computes expected counts dynamically

- **Given** the heavy-lane test runs with ES + OS reachable, Solr unreachable (CI backend-job posture)
- **When** the test asserts on `scenarios_completed`, `jl_count`, `study_count`
- **Then** the asserted values MUST equal the per-scenario-reachable computation: 5 scenarios completed, 8 judgment lists, 8 studies
- Example values:
  - `snapshot_engine_reachability(SCENARIOS)` result (slug-keyed): `{"acme-products-prod": True, "corp-docs-search": True, "jobs-marketplace-prod": True, "news-search-staging": True, "acme-products-rich-prod": True, "acme-kb-docs-solr": False}` (Solr-backed scenario unreachable; all ES/OS-backed scenarios reachable)
  - Expected: `scenarios_completed == 5`, `jl_count == 8`, `study_count == 8`, `scenarios_skipped == ["acme-kb-docs-solr"]`

### AC-5: Heavy-lane test covers Solr when reachable

- **Given** the heavy-lane test runs with ES + OS + Solr all reachable (operator-local posture)
- **When** the test asserts on counts
- **Then** the asserted values MUST equal: 6 scenarios completed, 10 judgment lists, 10 studies; `_EXPECTED_RUNGS` MUST include `acme-kb-docs-solr → rung_2`, `_EXPECTED_UBI_CONVERTERS` MUST include `acme-kb-docs-solr → hybrid_ubi_llm`

### AC-6: CLI `make seed-demo` is engine-tolerant

- **Given** the operator's local stack has Postgres + ES up but not Solr
- **When** the operator runs `make seed-demo`
- **Then** the CLI MUST print `[skip] acme-kb-docs-solr — solr unreachable at http://localhost:8983` on stderr, complete the other scenarios, and exit `0`

### AC-6b: CLI hard-fails when ALL engines are unreachable

- **Given** the operator's local stack has Postgres up but NO engine (ES, OS, Solr all down)
- **When** the operator runs `make seed-demo`
- **Then** the CLI MUST print `ERROR: all engines unreachable — start at least one engine (ES/OS/Solr) and retry` on stderr and exit `1` (mirrors the service-layer `SEED_NO_ENGINES_REACHABLE` invariant; a no-op reseed is a failure, not a success — per GPT-5.5 cycle-2 Finding 3)

### AC-7: WARN log emitted at end-of-reseed when any scenario skipped

- **Given** any reseed run with at least one unreachable engine AND at least one completed scenario
- **When** the orchestrator completes
- **Then** exactly one WARN log line `demo_reseed_partial_completion_engines_unreachable` MUST be emitted with structured fields `{scenarios_skipped: [...], scenarios_completed: <N>}`

### AC-8: Additive `scenarios_skipped` field is backward-compatible

- **Given** an existing consumer of `GET /api/v1/_test/demo/reseed/status` that hard-codes `status in ("idle", "running", "complete", "failed")` (no new enum value)
- **When** the consumer receives a response with a new `scenarios_skipped: list[str]` field
- **Then** the API MUST still respond with HTTP 200 and a well-formed JSON body containing all the existing fields. The new field MUST default to `[]` and never be `null`. The polling-stop logic at [`demo-reseed.ts:85-94`](../../../../../ui/src/lib/api/demo-reseed.ts#L85) MUST keep working without modification (it stops on `status !== 'running'`, and `complete` was already terminal).

### AC-9: Probe failure does not break the reseed

- **Given** the `is_engine_reachable` probe itself raises an unexpected `Exception` (e.g., DNS failure raising `socket.gaierror`)
- **When** the orchestrator calls the probe for a scenario
- **Then** the probe MUST treat the exception as "unreachable", return `False`, log the unexpected-exception class at WARN, and proceed to skip the scenario. The orchestrator MUST NOT propagate the probe's exception

### AC-10: All-engines-unreachable is a hard failure, not a partial-complete

- **Given** every engine (ES + OS + Solr) is unreachable at probe time (extreme misconfiguration / all engines down)
- **When** `reseed_demo_state(...)` runs
- **Then** the orchestrator MUST raise `AllEnginesUnreachableError(DemoSeedingError)` carrying `scenarios_skipped`. The worker special-cases it and writes to Redis; the polled GET status MUST show `status = "failed"` + `failed_reason = "all_engines_unreachable"` (the stable token, NOT the generic `f"{type}: {msg}"`) + `scenarios_skipped` = all 6 slugs + `scenarios_completed = 0`. There is no synchronous error envelope (the reseed is async — POST already returned 202). The orchestrator MUST NOT return `status = "complete"` with `scenarios_completed == 0`
- Example values:
  - `snapshot_engine_reachability(<all 6 scenarios incl. rich>)` result (slug-keyed): every slug maps to `False`
  - Expected response status: `failed`, `failed_reason: "all_engines_unreachable"`, `scenarios_completed: 0`, `scenarios_skipped: ["acme-products-prod", "corp-docs-search", "news-search-staging", "jobs-marketplace-prod", "acme-products-rich-prod", "acme-kb-docs-solr"]` (all 6 slugs incl. rich)
  - Rationale: per GPT-5.5 cycle-1 Finding 4 — a successful zero-scenario reseed would cache in Arq's `keep_result` window and lock out retries for ~1h via the singleton-dedup wedge documented in [`bug_reseed_failure_blocks_retry_arq_singleton_dedup`](../bug_reseed_failure_blocks_retry_arq_singleton_dedup/idea.md). Surfacing as `failed` keeps retry behavior correct.

### AC-11: UI surfaces the partial-completion hint

- **Given** the dashboard reseed button has just completed a reseed with `status = "complete"` and `scenarios_skipped = ["acme-kb-docs-solr"]`
- **When** the operator looks at the button's success-state render
- **Then** the component MUST render the existing success message AND an inline italic hint below it reading `Partial completion — 1 engine skipped: acme-kb-docs-solr` with a "Why?" link to `docs/03_runbooks/demo-reseed-engine-tolerance.md`. Test fixture `STATUS_COMPLETE_PARTIAL` in [`reset-demo-state-button.test.tsx`](../../../../../ui/src/__tests__/components/dashboard/reset-demo-state-button.test.tsx) MUST cover this case.

## 13) Non-functional requirements

- **Performance:** the new probe adds up to 6 × (2.0s timeout) = 12s wall-clock to any reseed run in the worst case (every engine unreachable, full timeout). Acceptable — the reseed already runs 13-19 minutes per the test docstring.
- **Reliability:** no SLO change. The new code paths are pure-function reachability probes + a skip path; no new failure modes are introduced.
- **Operability:** the WARN log line MUST be greppable in the api worker logs. Structured fields: `scenarios_skipped`, `scenarios_completed`.
- **Accessibility/usability:** the one UI change is the inline partial-completion hint on the dashboard reseed button (FR-5 / AC-11). The hint MUST be plain readable text (not color-only signalling), and the "Why?" link MUST be a real anchor (keyboard-focusable, descriptive link text pointing at the runbook) — not an icon-only affordance.

## 14) Test strategy requirements (spec-level)

- **Unit tests** (`backend/tests/unit/`):
  - New file `backend/tests/unit/services/test_demo_seeding_engine_reachability.py` — tests `is_engine_reachable` for: Solr 200 + valid body → True; Solr 200 + invalid body → False; Solr 404 → False; httpx.ConnectError → False; httpx.TimeoutException → False; unexpected exception → False + log emitted (AC-9).
  - New file `backend/tests/unit/services/test_demo_seeding_partial_completion.py` — tests the orchestrator's per-scenario loop with `is_engine_reachable` **monkeypatched** to return `False` for solr (driver-level unit). Asserts: `scenarios_skipped` accumulates the slug; structured `demo_reseed_scenario_skipped_engine_unreachable` log fires per skip; one summary WARN at end; `status = "complete"` with non-empty `scenarios_skipped`. Per GPT-5.5 cycle-1 Finding 5: this is labeled as a UNIT test (monkeypatched), not integration — the real reachability path is exercised by the heavy-lane test.
  - New file `backend/tests/unit/services/test_demo_seeding_no_engines_reachable.py` — covers AC-10: monkeypatch `is_engine_reachable` to return `False` for all three engines; assert `reseed_demo_state` raises `DemoSeedingError` whose `str(exc)` is the stable marker `"all_engines_unreachable"` AND `scenarios_completed == 0`. Plus a worker-level unit (extend or add to the worker test) asserting the worker maps that marker to `status="failed"` + `failed_reason="all_engines_unreachable"` (the stable token, not the generic reason).
- **Integration tests** (`backend/tests/integration/`):
  - Extend `backend/tests/integration/test_demo_seeding_ubi_full.py` per FR-4 — dynamic count computation based on the **real `is_engine_reachable` probe** at test setup time, Solr-aware skip + assertion gating. This is the heavy-lane integration assertion that exercises the genuine no-Solr-service-container CI path (per F5 — the real probe, not a monkeypatch).
- **Contract tests** (`backend/tests/contract/`):
  - Extend the OpenAPI-surface contract test ([`backend/tests/contract/test_openapi_surface.py`](../../../../../backend/tests/contract/test_openapi_surface.py), which already references `ReseedStatusResponse`). Assert (a) the new `scenarios_skipped: list[str]` field is in the `ReseedStatusResponse` schema with a non-null default, and (b) the `ReseedStatusLiteral` enum in the schema is exactly `{"idle", "running", "complete", "failed"}` (guards against accidental enum expansion). NO error-code assertion — the all-engines-unreachable case has no wire error code (async architecture); it's covered by the unit/worker test asserting the `failed_reason` token.
- **E2E tests** (`ui/tests/e2e/`):
  - None in Phase 1. The dashboard button render under partial-completion is covered by the vitest unit test fixture `STATUS_COMPLETE_PARTIAL` extension to `reset-demo-state-button.test.tsx`.

## 15) Documentation update requirements

- `docs/01_architecture/` — no change.
- `docs/02_product/` — no change.
- `docs/03_runbooks/demo-reseed-engine-tolerance.md` — NEW (per FR-6).
- `docs/04_security/` — no change.
- `docs/05_quality/` — no change.
- `CLAUDE.md` — one-line "Common Pitfalls" entry + "Key Runbooks" table row (per FR-6).
- `state.md` — known-debt entry for `infra_solr_ci_readiness` updates from "P1 — pr.yml red on every branch" → "Phase 1 shipped, Phase 2 in progress (smoke stability — see `infra_solr_smoke_stability`)".

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** N/A. The change is in test + service + UI code, not a runtime feature surface. The new `scenarios_skipped` field is additive; no enum change.
- **Migration/backfill expectations:** N/A. No schema changes (Alembic head stays `0022_solr_engine_auth_check`).
- **Operational readiness gates:** `pr.yml` backend job must go green on this PR (the test the change fixes must pass). Smoke remains red — explicitly acknowledged and tracked as Phase 2 ([`infra_solr_smoke_stability`](../../planned_features/02_mvp2/infra_solr_smoke_stability/idea.md)).
- **Release gate:** `pr.yml` backend + frontend + both docker buildx + static-checks + license jobs green; **smoke explicitly exempted (Phase 2)**; Gemini adjudication clean. Heavy CI is ON (per `state.md` 2026-05-31 note). The PR is mergeable with smoke red because (a) the smoke failure is pre-existing and tracked, (b) `main` no longer enforces heavy-CI required-status-checks (per `state.md` known-state: the ruleset's `required_status_checks` rule was removed 2026-05-31), so the operator merges on judgment with the smoke-red rationale documented in the PR body.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-9 (defensive shielding) | Story 1.1: add `solr_reachability.py` fixture | `backend/tests/unit/integration_fixtures/test_solr_reachability.py` (new) | — |
| FR-2 | AC-1, AC-2, AC-3, AC-7, AC-9, AC-10 | Story 1.2: orchestrator `is_engine_reachable` + skip + WARN log + all-engines-unreachable failure path | `backend/tests/unit/services/test_demo_seeding_engine_reachability.py` (new) + `test_demo_seeding_partial_completion.py` (new) + `test_demo_seeding_no_engines_reachable.py` (new) + extend `test_demo_seeding_ubi_full.py` | — |
| FR-3 | AC-6, AC-6b | Story 1.3: CLI parity (skip + all-unreachable hard-fail) | `backend/tests/unit/scripts/test_seed_meaningful_demos_engine_tolerance.py` (new) | — |
| FR-4 | AC-4, AC-5 | Story 1.4: heavy-lane test dynamic-count | `backend/tests/integration/test_demo_seeding_ubi_full.py` (extend) | — |
| FR-5 | AC-8, AC-10, AC-11 | Story 1.5: `ReseedStatusResponse.scenarios_skipped` field + TypeScript mirror + UI hint + worker `failed_reason="all_engines_unreachable"` token | `backend/tests/contract/test_openapi_surface.py` (extend), `ui/src/__tests__/components/dashboard/reset-demo-state-button.test.tsx` (extend with `STATUS_COMPLETE_PARTIAL`) | — |
| FR-6 | — | Story 1.6: runbook + CLAUDE.md edit | — | `docs/03_runbooks/demo-reseed-engine-tolerance.md`, `CLAUDE.md` |
| FR-7 | — | (Phase 2 — separate PR) | — | — |

## 18) Definition of feature done

This feature is complete when:

- [ ] All Phase 1 acceptance criteria (AC-1 through AC-11, incl. AC-6b) pass in CI.
- [ ] `pr.yml` **backend** job is green on this PR (the count-drift fix unblocks the heavy-lane test).
- [ ] `pr.yml` **smoke** job **remains red** (acknowledged — Phase 2 territory). The PR description MUST cite [`infra_solr_smoke_stability`](../../planned_features/02_mvp2/infra_solr_smoke_stability/idea.md) and the rationale for the split. The `static-checks-backend`, `static-checks-frontend`, `frontend`, `docker buildx (relyloop/api)`, `docker buildx (relyloop/ui)`, `backend-unit-fast`, `license-headers`, and `license-inventory` jobs MUST all be green.
- [ ] All test layers (unit/integration/contract + UI vitest) are green; no new E2E in Phase 1.
- [ ] `docs/03_runbooks/demo-reseed-engine-tolerance.md` is added and linked from CLAUDE.md.
- [ ] `infra_solr_smoke_stability` is added and references this spec.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

_None._ Q-1 and Q-2 from the idea have been resolved during cycle-1 review:
- **Q-1 (Phase 2 lever choice)** moved to [`infra_solr_smoke_stability`](../../planned_features/02_mvp2/infra_solr_smoke_stability/idea.md) per D-5 — Phase 2 is a separate PR and the lever choice is gated on log evidence captured then.
- **Q-2 (UI consumer)** resolved by grep — there IS a real UI consumer at [`ui/src/components/dashboard/reset-demo-state-button.tsx`](../../../../../ui/src/components/dashboard/reset-demo-state-button.tsx) + the type mirror at [`ui/src/lib/api/demo-reseed.ts:27`](../../../../../ui/src/lib/api/demo-reseed.ts#L27). The wire-value design was flipped to additive-field-only (no new enum value) — see D-4 revised below.

### Decision log

- **2026-06-01 — D-1: skip-on-unreachable in the reseed orchestrator + test, do NOT add a Solr service container to the GHA backend job** — Rationale: option (a) (add container + bootstrap configset in a job step) has too much surface area; option (b) mirrors the existing ES skip pattern at `test_demo_seeding_ubi_full.py:142`, keeps CI lean, and gives operators without Solr the same behavior CI gets. From [`idea.md`](idea.md) Capability A.
- **2026-06-01 — D-2: orchestrator-side and test-side skips ship together (one PR)** — Rationale: keeping them in lock-step prevents drift between what CI sees and what operators see. Capability C from the idea (reseed engine-tolerance) is part of this PR, not a separate one. From idea D-2.
- **2026-06-01 — D-3: heavy-lane test uses dynamic count computation by reachability, not "skip the whole test"** — Rationale: when Solr is the only unreachable engine, the test still has meaningful work to do (validate the 5 ES+OS scenarios). The dynamic-count approach is a small deviation from the binary ES skip precedent at line 142 (ES unreachable still skips the whole test — without ES there's no fallback) but it's the right design for the Solr case. Answers idea Q-3.
- **2026-06-01 — D-4 (REVISED after GPT-5.5 cycle-1 Finding 3): skipped engines surface as an additive `scenarios_skipped: list[str]` field on `ReseedStatusResponse`, NOT as a new wire-value status.** Original draft proposed `succeeded_partial`. Flipped because (a) the actual `ReseedStatusLiteral` is `Literal["idle", "running", "complete", "failed"]` at [`demo_seeding.py:220`](../../../../../backend/app/services/demo_seeding.py#L220) (NOT `"succeeded"` as the draft assumed — a wire-value typo); (b) Q-2's grep surfaced a real UI consumer at `reset-demo-state-button.tsx` + the type mirror at `demo-reseed.ts:27`, making the enum change a multi-file contract churn for marginal benefit; (c) the additive field encodes the same information with less wire surface and lets the existing polling-stop logic at `demo-reseed.ts:85-94` work unmodified. UI gets a small inline "partial completion" hint inside the existing `complete`-state render (AC-11).
- **2026-06-01 — D-5: Capability B (smoke stability) ships in a separate PR (Phase 2)** — Rationale: needs `docker compose logs solr` from a runner failure to commit to the right lever; bundling unknowns into a Phase-1-unblocks-CI PR slows both halves.
- **2026-06-01 — D-6 (added after GPT-5.5 cycle-1 Finding 4): all-engines-unreachable is a hard `failed`, not a partial-complete.** Even though `len(scenarios_skipped) == N AND scenarios_completed == 0` is internally consistent, encoding it as `status = "complete"` would cache a no-op success in Arq's `keep_result` window and lock out retries for ~1h (per sibling [`bug_reseed_failure_blocks_retry_arq_singleton_dedup`](../bug_reseed_failure_blocks_retry_arq_singleton_dedup/idea.md)). Routing this case through `status = "failed"` keeps retry behavior correct and prevents misconfiguration from masquerading as success. See AC-10 + FR-2 invariant.
- **2026-06-01 — D-7 (added during plan-gen codebase audit): the all-engines-unreachable signal is a `failed_reason` TOKEN, not an HTTP wire `error_code`.** The plan-gen pass discovered the reseed is async — the POST `/api/v1/_test/demo/reseed` returns 202 and the orchestrator runs in the Arq worker ([`backend/workers/demo_reseed.py:165`](../../../../../backend/workers/demo_reseed.py#L165)). There is therefore NO synchronous error envelope for execution failures; the worker's exception barrier writes `status="failed"` + `failed_reason` to Redis, which the GET status endpoint returns. The earlier draft's `SEED_NO_ENGINES_REACHABLE` HTTP error code was architecturally impossible — replaced with the stable `failed_reason="all_engines_unreachable"` token written by special-casing the marker in the worker. §7.5, §8, §8.2, AC-10, FR-2, FR-5 all corrected.
