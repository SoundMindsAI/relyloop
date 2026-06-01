# Implementation Plan — infra_solr_ci_readiness (Phase 1: unblock pr.yml against Solr)

**Date:** 2026-06-01
**Status:** Ready for Execution
**Primary spec:** [feature_spec.md](feature_spec.md)
**Policy source(s):** CLAUDE.md (Absolute Rules, Common Pitfalls), [`docs/01_architecture/data-model.md`](../../../../01_architecture/data-model.md) (audit_log forthcoming — N/A here)

---

## 0) Planning principles

- Spec traceability first: every story maps to FR IDs (FR-1 … FR-6; FR-7 is Phase 2, out of scope).
- No migration, no new endpoints, no schema change (Alembic head stays `0022_solr_engine_auth_check`).
- The reseed is **async** — the all-engines-unreachable failure travels through the Redis-backed `ReseedStatusResponse` (worker writes `status="failed"` + stable `failed_reason` token), NOT a synchronous HTTP envelope.
- Reachability gate runs BEFORE scenario dispatch. Mid-scenario errors stay `DemoSeedingError` (unchanged).
- Fail-loud tests: assert explicit status / skip-set / failed_reason token.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic/Story | Notes |
|---|---|---|
| FR-1 | Epic 1 / Story 1.1 | Solr reachability probe fixture (`solr_reachability.py`) |
| FR-2 | Epic 1 / Story 1.2 | `is_engine_reachable` + `snapshot_engine_reachability` (incl. rich scenario) + orchestrator skip + WARN + typed `AllEnginesUnreachableError` + `ReseedStatusResponse.scenarios_skipped` model field + worker failed-status write |
| FR-3 | Epic 1 / Story 1.3 | CLI parity in `seed_meaningful_demos.py` (skip + rich gate + skipped summary + all-unreachable hard-fail) |
| FR-4 | Epic 1 / Story 1.4 | Heavy-lane test dynamic-count via shared slug-keyed snapshot (6 scenarios incl. rich) |
| FR-5 | Epic 1 / Story 1.5 | TS mirror `scenarios_skipped` + UI hint + contract/vitest (backend field + worker token are in Story 1.2) |
| FR-6 | Epic 1 / Story 1.6 | Runbook + CLAUDE.md edits |
| FR-7 | **Phase 2 — deferred** | Smoke Solr stability. Tracked in [`phase2_idea.md`](phase2_idea.md). NOT in this plan. |

**Deferred work tracking:** FR-7 (smoke stability) is Phase 2; tracking artifact [`phase2_idea.md`](phase2_idea.md) already exists in this directory (verified). No new tracking file needed.

## 2) Delivery structure

Single epic, 6 stories. Backend-first (Stories 1.1–1.2 are the foundation; 1.3–1.5 depend on the `is_engine_reachable` + `snapshot_engine_reachability` helpers from 1.2; 1.6 is docs). The feature touches one UI component (Story 1.5) — see UI Guidance.

### Conventions (project-specific)

```
- Domain/service helpers: is_engine_reachable is async (needs httpx.AsyncClient); snapshot_engine_reachability is async (awaits the probe per scenario).
- The orchestrator reseed_demo_state already takes (db, api_client, engine_client, status_callback). The new probe reuses the passed engine_client where possible, or opens a short-lived httpx.AsyncClient (matching _seed_solr_scenario_sync's pattern).
- Reseed status model ReseedStatusResponse has model_config = ConfigDict(extra="forbid") — new fields MUST be declared on the model, can't be injected.
- ReseedStatusLiteral stays Literal["idle", "running", "complete", "failed"] — DO NOT extend.
- CLI (scripts/seed_meaningful_demos.py) runs on the HOST and uses s['host_base_url'] directly (no Compose-DNS resolution). The orchestrator runs in-container and resolves via _resolve_engine_base_url first.
- All new test files follow the existing layer split: unit (no DB/network), integration (DB + real engines, @pytest.mark.integration + heavy-lane skip), contract (OpenAPI shape).
- Conventional Commits + DCO signoff on every commit (git commit -s).
```

### AI Agent Execution Protocol

0. Load context: read `architecture.md` + `state.md` first.
1. Read story scope (outcome + interfaces + DoD).
2. Implement backend first: Story 1.1 (fixture) → 1.2 (helpers + orchestrator + worker) → 1.3 (CLI) → 1.4 (test) → 1.5 (model field + worker token + UI) → 1.6 (docs).
3. Run `make test-unit` + targeted contract tests after each backend story.
4. Implement frontend (Story 1.5 UI hint).
5. Run `cd ui && pnpm test` for the vitest fixture.
6. Update docs (Story 1.6) in the same PR.
7. No migration — skip round-trip.
8. Attach evidence in PR description.
9. After the final story, update `state.md` (known-debt entry) + leave `architecture.md` unchanged (no new layer).

---

## Epic 1 — Engine-tolerant demo reseed (unblock pr.yml backend job)

### Story 1.1 — Solr reachability probe fixture

**Outcome:** A reusable Solr reachability probe symmetric to the existing ES probe, so tests and (indirectly) the orchestrator share one reachability shape across all three engines.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/fixtures/solr_reachability.py` | `_solr_base_url() -> str` (probe `localhost:8983` then `solr:8983`, 2.0s timeout, returns base URL or `""`) + `solr_required` pytest skip marker. Mirrors [`es_reachability.py`](../../../../../backend/tests/integration/fixtures/es_reachability.py). |
| `backend/tests/unit/integration_fixtures/test_solr_reachability.py` | Unit tests for `_solr_base_url` shape-checking (200 + valid Solr body → URL; 200 + non-Solr body → `""`; ConnectError → `""`). |

**Key interfaces**

```python
# backend/tests/integration/fixtures/solr_reachability.py
def _solr_base_url() -> str: ...   # probe order localhost:8983 -> solr:8983; verify GET /solr/admin/info/system 200 + responseHeader.status==0 + "lucene" key
solr_required = pytest.mark.skipif(not _solr_base_url(), reason="...")
```

**Tasks**
1. Copy the structure of `es_reachability.py`; swap port `9200`→`8983`, health path `/`→`/solr/admin/info/system`, body check `"version" in r.json()` → `r.json().get("responseHeader", {}).get("status") == 0 and "lucene" in r.json()`.
2. Add the skip-reason string pointing at `docs/03_runbooks/local-dev.md`.
3. Write the unit test with a mocked `httpx.Client` for the three cases.

**Definition of Done (DoD)**
- `_solr_base_url()` returns `""` when no Solr is reachable, the base URL when it is.
- Unit test passes (`backend/tests/unit/integration_fixtures/test_solr_reachability.py`).
- `make test-unit` green.

---

### Story 1.2 — Orchestrator skip-on-unreachable + typed all-engines-unreachable exception + model field

**Outcome:** The reseed orchestrator probes each scenario's engine (including the separately-seeded rich ESCI scenario) before dispatch, skips unreachable engines (accumulating `scenarios_skipped`), emits a WARN summary on partial completion, and raises a typed exception carrying the skip list when nothing succeeds. The `ReseedStatusResponse.scenarios_skipped` model field lands here (required because the model has `extra="forbid"` — Story 1.2 cannot append to an undeclared field).

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/services/test_demo_seeding_engine_reachability.py` | Unit tests for `is_engine_reachable` (Solr/ES/OS shapes; ConnectError/Timeout/unexpected → False + WARN per AC-9). |
| `backend/tests/unit/services/test_demo_seeding_partial_completion.py` | Unit: monkeypatch `is_engine_reachable` → False for solr; assert `scenarios_skipped` accumulates, structured skip log per skip, one WARN summary, `status="complete"` with non-empty `scenarios_skipped`. |
| `backend/tests/unit/services/test_demo_seeding_no_engines_reachable.py` | Unit (AC-10): monkeypatch all engines → False; assert `reseed_demo_state` raises `AllEnginesUnreachableError` with `str(exc) == "all_engines_unreachable"`, `exc.scenarios_skipped` = all 6 slugs (incl. rich), `scenarios_completed == 0`. Plus a worker-level unit asserting the worker maps it to `status="failed"` + `failed_reason="all_engines_unreachable"` + `scenarios_skipped` (all 6) + `scenarios_completed=0` in the Redis status. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/services/demo_seeding.py` | (1) Add `class AllEnginesUnreachableError(DemoSeedingError)` with `__init__(self, scenarios_skipped: list[str])` storing the attr + `super().__init__("all_engines_unreachable")`. (2) Add `async def is_engine_reachable(...)`. (3) Add `async def snapshot_engine_reachability(scenarios) -> dict[str, bool]` (slug-keyed; covers the 5 `SCENARIOS` **plus** the rich scenario `_RICH_SCENARIO_SLUG` keyed to ES reachability). (4) **Add `scenarios_skipped: list[str] = Field(default_factory=list)` to `ReseedStatusResponse`** (the model has `extra="forbid"` — the field must be declared before the orchestrator appends to it). (5) In `reseed_demo_state`'s `SCENARIOS` loop (after `_resolve_engine_base_url`), call the probe; on False → skip + structured log + append slug to `progress.scenarios_skipped`. (6) **Gate the rich-scenario seeding** (`_seed_rich_scenario`/inline rich block at ≈[demo_seeding.py:990](../../../../../backend/app/services/demo_seeding.py#L990)) on ES reachability: when ES unreachable → append `_RICH_SCENARIO_SLUG` to `scenarios_skipped` + skip (don't raise). (7) After all seeding: if `scenarios_completed == 0 and scenarios_skipped` → raise `AllEnginesUnreachableError(progress.scenarios_skipped)`; elif `scenarios_skipped` → emit WARN `demo_reseed_partial_completion_engines_unreachable`. |
| `backend/workers/demo_reseed.py` | In the `except (DemoSeedingError, httpx.HTTPError, Exception)` barrier ([line 175](../../../../../backend/workers/demo_reseed.py#L175)): special-case `isinstance(exc, AllEnginesUnreachableError)` → write `ReseedStatusResponse(status="failed", failed_reason="all_engines_unreachable", scenarios_skipped=exc.scenarios_skipped, scenarios_completed=0, started_at=..., finished_at=...)`. Other exceptions keep the existing generic `failed_reason=f"{type(exc).__name__}: {str(exc)[:200]}"` write (unchanged). Import `AllEnginesUnreachableError` from `demo_seeding`. |
| `ui/src/lib/api/demo-reseed.ts` | (Moved here from Story 1.5's note for clarity — see Story 1.5 which owns the TS + UI changes.) No change in this story. |

**Key interfaces**

```python
# backend/app/services/demo_seeding.py
class AllEnginesUnreachableError(DemoSeedingError):
    def __init__(self, scenarios_skipped: list[str]) -> None:
        self.scenarios_skipped = scenarios_skipped
        super().__init__("all_engines_unreachable")

async def is_engine_reachable(
    engine_base_url: str,
    engine_type: Literal["elasticsearch", "opensearch", "solr"],
    *,
    timeout_s: float = 2.0,
) -> bool: ...   # GET health path; True iff 200 + expected body shape; total (never raises) — any exception → False + WARN

async def snapshot_engine_reachability(
    scenarios: list[dict[str, Any]],
) -> dict[str, bool]: ...  # slug-keyed; covers 5 SCENARIOS + rich (_RICH_SCENARIO_SLUG @ ES); resolves host_base_url via _resolve_engine_base_url, then probes
```

**Pydantic schema (lands in this story)**

```python
class ReseedStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: ReseedStatusLiteral
    # ... existing fields ...
    scenarios_skipped: list[str] = Field(default_factory=list)   # NEW (top-level, not in summary)
```

**Tasks**
1. Add `AllEnginesUnreachableError` + the `scenarios_skipped` model field.
2. Add `is_engine_reachable` (Solr: `/solr/admin/info/system`, `lucene` key + `responseHeader.status==0`; ES/OS: `/`, `version` key). Wrap all I/O in try/except → False + `logger.warning("demo_reseed_engine_probe_failed", ...)`.
3. Add `snapshot_engine_reachability` covering the 5 `SCENARIOS` + the rich scenario (synthetic entry: slug `_RICH_SCENARIO_SLUG`, engine `elasticsearch`, resolved via `_resolve_engine_base_url(ES)`).
4. In `reseed_demo_state`: insert the `SCENARIOS`-loop probe right after `engine_base = _resolve_engine_base_url(...)` (≈ [demo_seeding.py:1381](../../../../../backend/app/services/demo_seeding.py#L1381)). On unreachable → `logger.info("demo_reseed_scenario_skipped_engine_unreachable", extra={...})`, `progress.scenarios_skipped.append(slug)`, `continue`.
5. Gate the rich-scenario block on ES reachability (skip + append slug, don't raise).
6. After all seeding: the all-engines-unreachable raise (typed exception carrying the slug list), then the partial-completion WARN.
7. Update the worker barrier to write the full failed status (token + slugs + completed=0) for the typed exception.
8. Write the 3 unit test files.

**Definition of Done (DoD)**
- AC-1: partial completion → `status="complete"` + `scenarios_skipped=["acme-kb-docs-solr"]` + WARN emitted (unit test).
- AC-3: mid-scenario error still raises generic `DemoSeedingError` → generic `failed_reason` (unit test, unchanged path).
- AC-7: exactly one `demo_reseed_partial_completion_engines_unreachable` WARN on partial (unit assertion via `caplog`).
- AC-9: probe returns False + logs on unexpected exception (unit test).
- AC-10: all-unreachable → `AllEnginesUnreachableError` raised carrying all 6 slugs (incl. rich); worker writes `status="failed"` + `failed_reason="all_engines_unreachable"` + `scenarios_skipped`=all 6 + `scenarios_completed=0` (unit test covers both the raise and the worker mapping).
- `make test-unit` green; `make typecheck` green (new model field + typed exception).

---

### Story 1.3 — CLI parity (`make seed-demo` engine-tolerance)

**Outcome:** The CLI reseed skips unreachable-engine scenarios (exit 0 on partial) and hard-fails (exit 1) when no engine is reachable, mirroring the orchestrator invariant.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/scripts/test_seed_meaningful_demos_engine_tolerance.py` | Unit: monkeypatch reachability → solr unreachable → scenario skipped, exit 0; all engines unreachable → exit 1 + error line. |

**Modified files**

| File | Change |
|---|---|
| `scripts/seed_meaningful_demos.py` | (1) Add `skipped: list[str] = []` next to the existing `failures` list ([line 1781](../../../../../scripts/seed_meaningful_demos.py#L1781)). (2) In the per-scenario loop (≈ [line 1782](../../../../../scripts/seed_meaningful_demos.py#L1782)): before `seed_scenario(s)`, probe `is_engine_reachable(s['host_base_url'], s['engine_type'])` (CLI runs on host — uses `host_base_url` directly, NO Compose resolution). On False → print `[skip] <slug> — <engine_type> unreachable at <host_base_url>` to stderr, append slug to `skipped`, `continue`. (3) Gate the separate `seed_rich_scenario()` call (≈[line 1828](../../../../../scripts/seed_meaningful_demos.py#L1828)) on ES reachability: probe `is_engine_reachable(ES, "elasticsearch")` first; on False → print the `[skip] acme-products-rich-prod — elasticsearch unreachable …` line, append `_RICH_SCENARIO_SLUG` to `skipped`, don't call `seed_rich_scenario()`. (4) **Final summary**: when `skipped` is non-empty, print a distinct `Skipped (engine unreachable): <slug>, …` section to stderr (separate from the existing `failures` summary). (5) Exit-code logic (order matters — check `failures` FIRST so a mid-flight error is never mislabeled as "all engines unreachable"): if `failures` non-empty → existing failure path → exit 1 (unchanged); elif `not results and skipped` (zero successes, no real failures, at least one skip) → print `ERROR: all engines unreachable — start at least one engine (ES/OS/Solr) and retry` + `sys.exit(1)`; else (some results, maybe some skips) → exit 0. |

**Key interfaces**

```python
# scripts/seed_meaningful_demos.py — the CLI is sync; wrap the async probe.
# CRITICAL: demo_seeding.py imports SCENARIOS *from this module* (see
# demo_seeding.py:70-74 `from scripts.seed_meaningful_demos import SCENARIOS`),
# so a TOP-LEVEL `from backend.app.services.demo_seeding import is_engine_reachable`
# here would create a circular import (seed_meaningful_demos -> demo_seeding ->
# seed_meaningful_demos). Use a LOCAL/late import inside the function, matching
# the existing deferred-import pattern in `_async_seed_synthetic_ubi`:
import asyncio
def _engine_reachable(host_base_url: str, engine_type: str) -> bool:
    from backend.app.services.demo_seeding import is_engine_reachable  # late — avoids cycle
    return asyncio.run(is_engine_reachable(host_base_url, engine_type))
```

**Tasks**
1. Add `skipped: list[str] = []` next to the existing `failures` list ([line 1781](../../../../../scripts/seed_meaningful_demos.py#L1781)).
2. Add the per-scenario reachability gate via a `_engine_reachable(...)` helper that does a LATE/local import of `is_engine_reachable` (NOT top-level — `demo_seeding.py` imports `SCENARIOS` from this module, so a top-level import cycles; matches the existing deferred-import pattern in `_async_seed_synthetic_ubi`). Sync `asyncio.run` wrapper around the async probe. (GPT-5.5 plan-cycle-3 finding.)
3. Gate `seed_rich_scenario()` on ES reachability (append `_RICH_SCENARIO_SLUG` to `skipped` when ES down).
4. Add the final `Skipped (engine unreachable): …` summary section (distinct from the `failures` summary) when `skipped` is non-empty.
5. Add the exit-code logic in order: `failures` non-empty → exit 1 (existing path) FIRST; then `not results and skipped` → all-unreachable error + exit 1; else exit 0. (Checking `failures` first prevents a mid-flight error + some skips from being mislabeled as "all engines unreachable" — GPT-5.5 plan-cycle-2 F1.)
6. Write the unit test (monkeypatch the probe; assert exit codes + stderr `[skip]` lines + summary section via `capsys`).

**Definition of Done (DoD)**
- AC-6: solr unreachable → `[skip]` line + summary lists the slug + exit 0 (unit test).
- AC-6b: all engines unreachable → error line + exit 1 (unit test).
- The final summary lists every skipped slug in a section distinct from `failures` (unit assertion via `capsys`).
- `make test-unit` green.

---

### Story 1.4 — Heavy-lane test dynamic count via shared snapshot

**Outcome:** `test_demo_seeding_ubi_full` computes expected counts + per-scenario assertions from the same slug-keyed reachability snapshot the orchestrator uses, and covers the Solr scenario when Solr is reachable.

**Modified files**

| File | Change |
|---|---|
| `backend/tests/integration/test_demo_seeding_ubi_full.py` | Add `acme-kb-docs-solr` to `_EXPECTED_RUNGS` (`"rung_2"`), `_SCENARIO_TARGET` (`"acme-kb-docs"`), `_EXPECTED_UBI_CONVERTERS` (`"hybrid_ubi_llm"`). Before `reseed_demo_state`, call `snapshot = await snapshot_engine_reachability(SCENARIOS)` — **note `snapshot_engine_reachability` itself injects the rich scenario** (`_RICH_SCENARIO_SLUG` keyed to ES), so the returned dict has 6 keys, not 5. Skip whole test if NO ES-backed scenario reachable (replaces the host-first `_es_base_url()` skip at [line 142](../../../../../backend/tests/integration/test_demo_seeding_ubi_full.py#L142)). Compute expected `(jl, study)` counts across all 6 reachable scenarios: each `SCENARIOS` entry contributes 2 if `ubi_target_rung` set else 1; the rich scenario contributes 1 (LLM-only) when ES reachable. Iterate the 3 expectation dicts conditioned on `snapshot[slug]`. Assert `set(summary.scenarios_skipped) == {slug for slug, ok in snapshot.items() if not ok}`. |

**Tasks**
1. Import `snapshot_engine_reachability` + `SCENARIOS` + `_RICH_SCENARIO_SLUG` from `demo_seeding`.
2. Replace the host-first ES skip with a snapshot-derived "no ES-backed scenario reachable → skip" gate.
3. Add the 3 Solr expectation-dict entries; gate each loop on `snapshot[slug]`.
4. Replace the hard `assert jl_count == 8 / study_count == 8` with the dynamic computation over all 6 scenarios (5 SCENARIOS + rich).
5. Assert `scenarios_skipped` matches the snapshot's unreachable set (which includes the rich slug when ES is down — though in CI ES is always up, so only solr skips).

**Definition of Done (DoD)**
- AC-4: ES+OS reachable, Solr not → `scenarios_completed==5` (4 ES/OS `SCENARIOS` + rich; Solr skipped), `jl_count==8`, `study_count==8`, `scenarios_skipped==["acme-kb-docs-solr"]` (this is the CI backend-job posture — the test the whole feature unblocks). The count math: acme-products-prod(2) + corp-docs-search(2) + jobs-marketplace-prod(2) + news-search-staging(1) + rich(1) = 8; Solr(2) skipped.
- AC-5: all 3 engines reachable → `scenarios_completed==6`, `jl_count==10`, `study_count==10` (8 + Solr's 2), Solr rung/converter asserted.
- The heavy-lane test PASSES in the `backend` CI job (Solr absent) — the unblock proof.

---

### Story 1.5 — TS mirror + UI partial-completion hint + contract test

**Outcome:** The TypeScript `ReseedStatusResponse` mirror carries `scenarios_skipped`, the dashboard reseed button shows a partial-completion hint, and a contract test pins the additive field + the unchanged enum. (The backend model field + worker token write landed in Story 1.2.)

**Modified files**

| File | Change |
|---|---|
| `backend/app/services/demo_seeding.py` | (Backend model field `scenarios_skipped` already added in Story 1.2 — listed here only for contract context; no change in this story.) |
| `backend/workers/demo_reseed.py` | (Done in Story 1.2 — the typed-exception failed-status write. Listed here for the contract surface; no change in this story.) |
| `ui/src/lib/api/demo-reseed.ts` | Add `scenarios_skipped: string[]` to the `ReseedStatusResponse` interface ([line 37](../../../../../ui/src/lib/api/demo-reseed.ts#L37)). `ReseedStatusLiteral` stays `'idle' \| 'running' \| 'complete' \| 'failed'` (unchanged). |
| `ui/src/components/dashboard/reset-demo-state-button.tsx` | In the `status === 'complete'` render branch, when `scenarios_skipped.length > 0`, render an inline italic hint: `Partial completion — N engine(s) skipped: <slugs>` + a "Why?" link (anchor, keyboard-focusable) to the runbook. |
| `ui/src/__tests__/components/dashboard/reset-demo-state-button.test.tsx` | Add `scenarios_skipped: []` to the EXISTING `STATUS_IDLE`, `STATUS_RUNNING`, `STATUS_COMPLETE`, `STATUS_FAILED` fixtures (required because the TS interface field is non-optional — without it `tsc` fails on the fixtures). Add a NEW `STATUS_COMPLETE_PARTIAL` fixture (status `complete`, `scenarios_skipped: ['acme-kb-docs-solr']`) + a test asserting the hint + Why-link render. |
| `backend/tests/contract/test_openapi_surface.py` | Assert `scenarios_skipped` is present in the `ReseedStatusResponse` OpenAPI schema, typed as `array` of `string`, and **NOT in the schema's `required` list** (it has a `default_factory`, so Pydantic v2 emits it as optional — do NOT assert `default: []` in the JSON Schema, which `default_factory` does not emit; verify the runtime `[]` default separately via a model-instantiation assertion if desired). Assert the `ReseedStatusLiteral` enum in the schema is exactly `{idle, running, complete, failed}`. |

**UI element inventory (Story 1.5 frontend scope)**
- Element: inline hint text (rendered conditionally in the existing `complete` branch). Data source: `status.scenarios_skipped` from `useDemoReseedStatus`. Interaction: none (static text + one link).
- Element: "Why?" anchor → `href="/docs/...` or external link to the runbook path. Keyboard-focusable, descriptive link text (not icon-only).
- No new state variables, no new props, no removed elements.

**Tasks**
1. Add the backend model field.
2. Add the TS interface field.
3. Add the conditional hint + Why-link in the `complete` branch of the button component.
4. Add the vitest fixture + assertion.
5. Extend the contract test.

**Definition of Done (DoD)**
- AC-8: `scenarios_skipped` present in the OpenAPI schema as optional `array<string>` (not in `required`; runtime default `[]` verified by model instantiation, NOT by a JSON-Schema `default` assertion — `default_factory` doesn't emit one); polling-stop logic at `demo-reseed.ts:85-94` unchanged + still green.
- AC-11: dashboard button renders the partial hint + Why-link for `STATUS_COMPLETE_PARTIAL` (vitest).
- Enum guard: contract test confirms `ReseedStatusLiteral` is exactly the 4 unchanged values.
- `make test-contract` + `cd ui && pnpm test` green.

---

### Story 1.6 — Documentation

**Outcome:** Operators have a runbook explaining partial-completion + retry, and CLAUDE.md points at it.

**New files**

| File | Purpose |
|---|---|
| `docs/03_runbooks/demo-reseed-engine-tolerance.md` | When scenarios skip, how to inspect `scenarios_skipped`, how to re-seed after starting the missing engine, the contract that `status=="complete"` + non-empty `scenarios_skipped` is a legitimate partial (not a failure), and that all-engines-unreachable surfaces as `status=="failed"` + `failed_reason=="all_engines_unreachable"`. |

**Modified files**

| File | Change |
|---|---|
| `CLAUDE.md` | Add one "Common Pitfalls" line (do-not-treat-partial-as-failure) + one "Key Runbooks" table row pointing at the new runbook. |

**Tasks**
1. Write the runbook.
2. Add the CLAUDE.md pitfall line + Key Runbooks row.

**Definition of Done (DoD)**
- Runbook exists + is linked from CLAUDE.md Key Runbooks.
- CLAUDE.md Common Pitfalls has the partial-completion line.

---

## 3) Testing workstream

### 3.1 Unit tests (`backend/tests/unit/`)
- [ ] `test_solr_reachability.py` (Story 1.1) — probe shape-checking
- [ ] `test_demo_seeding_engine_reachability.py` (Story 1.2) — `is_engine_reachable` all branches incl. AC-9
- [ ] `test_demo_seeding_partial_completion.py` (Story 1.2) — skip accumulation + WARN + AC-1/AC-7
- [ ] `test_demo_seeding_no_engines_reachable.py` (Story 1.2) — AC-10 marker raise + worker token mapping
- [ ] `test_seed_meaningful_demos_engine_tolerance.py` (Story 1.3) — AC-6/AC-6b CLI exit codes
- DoD: all branches deterministic; no DB/network (monkeypatched probes + `caplog`/`capsys`).

### 3.2 Integration tests (`backend/tests/integration/`)
- [ ] `test_demo_seeding_ubi_full.py` extended (Story 1.4) — AC-4 (CI posture, real probe) + AC-5 (full-stack). Heavy-lane (skips without ES; honors `SKIP_HEAVY_CI`).
- DoD: the test PASSES in the backend CI job with Solr absent (the unblock proof).

### 3.3 Contract tests (`backend/tests/contract/`)
- [ ] `test_openapi_surface.py` extended (Story 1.5) — `scenarios_skipped` field present + `ReseedStatusLiteral` enum unchanged.
- DoD: no enum drift; new field in schema.

### 3.4 E2E tests (`ui/tests/e2e/`)
- None in Phase 1. The partial-hint render is covered by vitest (`reset-demo-state-button.test.tsx`). No new user journey warrants a Playwright spec.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/integration/test_demo_seeding_ubi_full.py` | `assert jl_count == 8` / `study_count == 8` / `_EXPECTED_*` dicts | 1 file | Rewritten in Story 1.4 (dynamic counts + Solr entries). |
| `ui/src/__tests__/components/dashboard/reset-demo-state-button.test.tsx` | `STATUS_*` fixtures | 1 file | Extended in Story 1.5. The TS `scenarios_skipped: string[]` field is non-optional, so EVERY existing fixture (`STATUS_IDLE/RUNNING/COMPLETE/FAILED`) MUST gain `scenarios_skipped: []` or `tsc` fails — they are NOT left unchanged. Plus a new `STATUS_COMPLETE_PARTIAL` fixture. |
| `ui/src/lib/api/demo-reseed.ts` (+ any other TS files constructing `ReseedStatusResponse`) | `ReseedStatusResponse` literal | grep | Story 1.5 adds the interface field; run `grep -rn "ReseedStatusResponse" ui/src/` to find every object literal that must add `scenarios_skipped: []`. |
| `backend/tests/contract/test_openapi_surface.py` | `ReseedStatusResponse` schema | 1 file | Extended in Story 1.5. |
| Other `test_demo_seeding_*` (fast/unit) | `ReseedStatusResponse(...)` construction | several | No change needed — `scenarios_skipped` defaults to `[]`, so existing constructions stay valid (verify during impl via `grep -rn "ReseedStatusResponse(" backend/tests/`). |

### 3.5 Migration verification
- N/A — no schema changes.

### 3.6 CI gates
- [ ] `make test-unit`
- [ ] `make test-contract`
- [ ] `make test-integration` (heavy-lane; the `backend` CI job is the real gate — its `test_demo_seeding_ubi_full` must go green with Solr absent)
- [ ] `cd ui && pnpm test`

---

## 4) Documentation update workstream

### 4.0 Core context files
- [ ] `state.md` — update the known-debt "Solr is not CI-ready (P1)" entry: backend job unblocked (Phase 1 shipped); smoke still red (Phase 2, `phase2_idea.md`). Add the merge one-liner to "Last 5 merges" at finalization.
- [ ] `architecture.md` — no change (no new layer / data flow).
- [ ] `CLAUDE.md` — Common Pitfalls line + Key Runbooks row (Story 1.6).

### 4.3 Runbooks
- [ ] `docs/03_runbooks/demo-reseed-engine-tolerance.md` (Story 1.6).

Other docs/01,02,04,05: no change.

**Documentation DoD**
- `state.md` reflects backend-unblocked / smoke-deferred.
- Runbook dry-read validated.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals
- Centralize engine-reachability into one helper (`is_engine_reachable`) reused by orchestrator + CLI + test snapshot — eliminates the would-be duplication of three ad-hoc probes.

### 5.2 Planned refactor tasks
- [ ] Keep `_es_base_url` (test fixture) and `is_engine_reachable` (service) distinct — the fixture is test-time host-shell; the service helper is the production/CI path. Do NOT merge them (different layers).

### 5.3 Refactor guardrails
- [ ] Behavioral parity: the heavy-lane test still validates the full 10/10 when all engines up.
- [ ] Lint/typecheck green (`make lint && make typecheck`).
- [ ] No product-scope expansion.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `_resolve_engine_base_url` (existing, demo_seeding.py:338) | Story 1.2 snapshot | implemented | none |
| Worker exception barrier (demo_reseed.py:175) | Story 1.2 token write | implemented | none |
| `ReseedStatusResponse` model (demo_seeding.py:223) | Story 1.5 field | implemented | none |
| UI button consumer (reset-demo-state-button.tsx) | Story 1.5 hint | implemented | none |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Probe adds latency to reseed (up to 6×2s worst case) | L | L | Documented in spec §13 — acceptable vs 13-19min reseed. |
| `extra="forbid"` rejects existing `ReseedStatusResponse(...)` calls missing the field | L | M | Field has `default_factory=list` — existing constructions stay valid. Verified by grep in §3.5. |
| Heavy-lane test still flaky for non-Solr reasons | L | M | Out of scope — this plan only fixes the Solr ConnectError; pre-existing flakes tracked separately. |
| Circular import (CLI imports `is_engine_reachable` from `demo_seeding`, which imports `SCENARIOS` from the CLI) | M | M | Story 1.3 uses a LATE/local import inside `_engine_reachable(...)`, matching the existing `_async_seed_synthetic_ubi` deferred-import pattern. Verified `demo_seeding.py:70-74` imports `SCENARIOS` from `scripts.seed_meaningful_demos`. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Engine unreachable at probe | engine container down | skip scenario, log, accumulate `scenarios_skipped`, continue | operator starts engine + re-runs reseed |
| All engines unreachable | full misconfiguration | raise marker → worker writes `status=failed` + `failed_reason=all_engines_unreachable` | operator starts ≥1 engine + re-clicks (no Arq dedup wedge — failed results don't cache as success) |
| Engine reachable at probe, dies mid-seed | transient crash | generic `DemoSeedingError` → `status=failed` + generic `failed_reason` | operator investigates + re-clicks |
| Probe itself raises (DNS, etc.) | resolver hiccup | probe returns False (total), scenario skipped | same as unreachable |

## 7) Sequencing and parallelization

### Suggested sequence
1. Story 1.1 (fixture) — no deps.
2. Story 1.2 (helpers + orchestrator + worker) — depends on nothing but provides `is_engine_reachable` + `snapshot_engine_reachability` for 1.3/1.4.
3. Stories 1.3, 1.4, 1.5 — all depend on 1.2's helpers; can be done in any order (1.4 + 1.5 ideally together since both touch the reseed contract).
4. Story 1.6 (docs) — last.

### Parallelization opportunities
- 1.3 (CLI), 1.4 (test), 1.5 (model+UI) are independent once 1.2 lands. Single-developer flow → sequential is fine.

## 8) Rollout and cutover plan

- No feature flag. Additive field + new skip behavior. Ships in one PR.
- The PR merges with the `smoke` CI job still red (Phase 2 territory) — documented in the PR body citing `phase2_idea.md`. `main` no longer enforces heavy-CI required-status-checks (per `state.md`), so the operator merges on judgment.
- No migration, no cutover steps.

## 9) Execution tracker

### Current sprint
- [ ] Story 1.1 — Solr reachability fixture
- [ ] Story 1.2 — orchestrator skip + marker + worker token
- [ ] Story 1.3 — CLI parity
- [ ] Story 1.4 — heavy-lane test dynamic count
- [ ] Story 1.5 — model field + TS mirror + UI hint + contract
- [ ] Story 1.6 — runbook + CLAUDE.md

### Blocked items
- _None._

### Done this sprint
- _(none yet)_

## 10) Story-by-Story Verification Gate

Before marking any story complete:
- [ ] Files created/modified match story scope.
- [ ] Key interfaces implemented with compatible signatures.
- [ ] Required tests added for touched layers.
- [ ] Commands passed: `make test-unit`, `make test-contract`, `make test-integration` (or targeted subset w/ explanation), `cd ui && pnpm test` (Story 1.5).
- [ ] No migration (skip round-trip).
- [ ] Docs updated in same PR when behavior/contract changed.

## 11) Plan consistency review

1. **Spec ↔ plan endpoint count:** spec adds 0 endpoints; plan adds 0 endpoints. ✓ Match.
2. **Spec ↔ plan FR coverage:** FR-1→1.1, FR-2→1.2, FR-3→1.3, FR-4→1.4, FR-5→1.5, FR-6→1.6, FR-7→Phase 2 (tracked). ✓ All 6 Phase-1 FRs assigned.
3. **Story internal consistency:** file ownership is clean — `demo_seeding.py` + `demo_reseed.py` are edited ONLY in Story 1.2 (the `scenarios_skipped` model field, the typed exception, and the worker failed-status write all land there to keep the backend contract atomic); Story 1.5 lists them as "no change in this story" context rows. The TS/UI files (`demo-reseed.ts`, `reset-demo-state-button.tsx`, the vitest test, `test_openapi_surface.py`) are owned by Story 1.5. `seed_meaningful_demos.py` by Story 1.3. `test_demo_seeding_ubi_full.py` by Story 1.4. All modified files verified to exist. ✓
4. **Test file count:** 5 new unit files + 1 extended integration + 1 extended contract + 1 extended vitest = matches §3 inventory. Each assigned to exactly one story. ✓
5. **Gate arithmetic:** N/A (no endpoint-count gate).
6. **Open questions resolved:** spec §19 has no open questions (Q-1/Q-2 resolved). ✓
7. **Enum contract audit:** the only enum touched is `ReseedStatusLiteral` — explicitly NOT extended; the UI mirror at `demo-reseed.ts:27` stays in sync; Story 1.5 contract test guards against drift. The UI hint renders no `<select>` (static text only) so no wire-value option list is introduced. ✓
8. **Audit-event coverage:** N/A — `audit_log` not yet shipped (migration head 0022); the reseed flow emits no audit events and this feature adds none. Explicitly justified. ✓
9. **Infrastructure paths:** no migration. Test paths verified against existing dirs (`backend/tests/unit/services/`, `backend/tests/integration/fixtures/`, `backend/tests/contract/`). ✓
10. **Frontend data plumbing:** `scenarios_skipped` flows from `useDemoReseedStatus` (already returns the full `ReseedStatusResponse`) into the button component — no new plumbing needed; the field is on the existing payload once Story 1.5 adds it to the TS interface. Every existing TS object literal of `ReseedStatusResponse` must add `scenarios_skipped: []` (non-optional field) — captured in §3.5 + Story 1.5. ✓
11. **Legacy behavior parity:** N/A — no user-facing component >100 LOC is deleted or migrated. Story 1.5 ADDS a hint to the existing `complete` branch; it removes nothing.
12. **Rich-scenario coverage (GPT-5.5 plan-cycle-1 F1):** the rich ESCI scenario (`acme-products-rich-prod`, ES, seeded separately at `demo_seeding.py:990`) is included in `snapshot_engine_reachability` (Story 1.2), gated in both the orchestrator (Story 1.2) and the CLI (Story 1.3), and counted in the heavy-lane expectation math (Story 1.4). The reachability-relevant set is 6 scenarios (5 `SCENARIOS` + rich), matching `scenarios_total = len(SCENARIOS) + 1`. ✓
13. **All-engines-unreachable status fidelity (GPT-5.5 plan-cycle-1 F2):** the typed `AllEnginesUnreachableError` carries `scenarios_skipped`, and the worker writes them (+ `scenarios_completed=0` + the stable token) into the failed Redis status, so the spec §8.3 all-unreachable example is reproducible. Asserted in Story 1.2 DoD. ✓

## 12) Definition of plan done

- [x] Every Phase-1 FR mapped to a story/tests/docs.
- [x] Every story includes New/Modified files, Key interfaces (where applicable), Tasks, DoD.
- [x] Test layers (unit/integration/contract) scoped; E2E explicitly N/A with rationale.
- [x] Documentation updates planned (runbook + CLAUDE.md + state.md).
- [x] Lean refactor scope bounded (one shared probe helper).
- [x] Phase/epic gate measurable (the backend CI job's heavy-lane test goes green with Solr absent = the unblock proof).
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review performed, no unresolved findings.
