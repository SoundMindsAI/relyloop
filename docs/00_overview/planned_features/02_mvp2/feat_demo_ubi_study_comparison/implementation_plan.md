# Implementation Plan — feat_demo_ubi_study_comparison

**Date:** 2026-05-29
**Status:** Draft
**Primary spec:** [feature_spec.md](./feature_spec.md)
**Policy source(s):** [CLAUDE.md](../../../../CLAUDE.md) (Absolute Rules #1, #2, #4), [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md), [`docs/01_architecture/mvp2-overview.md`](../../../../01_architecture/mvp2-overview.md) §4 (UBI on-ramp), [`bug_demo_reseed_fake_metric_regression`](../../implemented_features/2026_05_28_bug_demo_reseed_fake_metric_regression/) (CLI ↔ home-button parity)

---

## 0) Planning principles

- Spec traceability first: every story maps to one or more FRs from the spec.
- Phase gates are hard stops. Phase 1 has two gates: backend Epic 1+2 must turn `rung_0 → rung_3` on `acme-products-prod` deterministically before frontend chip work starts; frontend Epic 3 plus tests Epic 4 must land together so no PR ships data without disclosure.
- Fail-loud tests: the FR-11 fast-lane integration test must assert the rung classifier returns the target rung after `seed_synthetic_ubi(...)` writes — not just that the bulk write returned 200.
- Reuse existing patterns: the synthetic-UBI generator lives in `backend/app/domain/demo/synthetic_ubi.py` (pure) and the engine-write helper in `backend/app/services/demo_ubi_seed.py` (I/O) to match the established domain/service split.
- Keep increments narrow: 14 stories across 4 epics. Each story closes one FR cleanly so per-story review is bounded.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (canonical mapping JSON) | Epic 1 / Story 1.1 | New file `samples/ubi_index_mappings.json`; round-trip unit test pins shape vs the existing `seed_ubi.ts` inline mappings |
| FR-2 (pure-domain generator) | Epic 1 / Story 1.2 | New module `backend/app/domain/demo/synthetic_ubi.py`; Hamilton allocator + per-rung volume math |
| FR-3 (engine-write helper + allowlist guard) | Epic 1 / Story 1.3 | New module `backend/app/services/demo_ubi_seed.py`; `DEMO_UBI_SCENARIO_ALLOWLIST` frozenset |
| FR-4 (reseed wiring — UBI seed + dispatch + dual study) | Epic 2 / Stories 2.2 + 2.3 | Extends `reseed_demo_state` at `backend/app/services/demo_seeding.py:1065` |
| FR-5 (CLI parity) | Epic 2 / Story 2.5 | Mirrors the same wiring inside `scripts/seed_meaningful_demos.py:seed_scenario` (line ~851) |
| FR-6 (cleanup adds UBI indices) | Epic 2 / Story 2.2 | Adds `ubi_queries` + `ubi_events` to `DEMO_ES_INDICES` in `scripts/seed_meaningful_demos.py` |
| FR-7 (disclaimer chips on 5 surfaces + 3-branch component tests) | Epic 3 / Stories 3.1 + 3.2 | New helper `isDemoSyntheticUbiClusterName` + `<DemoBadge variant="synthetic-ubi">` chip |
| FR-8 (SCENARIOS keys + invariant assertion) | Epic 2 / Story 2.1 | Adds `ubi_target_rung` + `ubi_converter` to each SCENARIOS entry |
| FR-9 (dual studies with `(LLM)` / `(UBI)` suffixes) | Epic 2 / Story 2.3 | Second `_seed_real_study_for_scenario` call; both renamed in step 3 of reseed |
| FR-10 (status sub-step labels + log events) | Epic 2 / Story 2.4 | Extends `ReseedStatusResponse.current_step` strings and adds 4 structured-log events |
| FR-11 (fast + heavy lane integration tests) | Epic 4 / Stories 4.1 + 4.2 | Two test files: `test_demo_seeding_ubi_fast.py` + `test_demo_seeding_ubi_full.py` |
| FR-12 (E2E spec with reseed precondition) | Epic 4 / Story 4.3 | New `ui/tests/e2e/demo-ubi.spec.ts` (FLAT path, not `specs/`) |
| Spec §15 (docs updates) | Epic 4 / Story 4.4 | `mvp2-overview.md` §4, `ubi-judgment-generation.md` runbook, `testing.md`, tutorial Step 11 |

**Deferred work tracking:** Phase 2 (side-by-side UBI-vs-LLM study comparison view) is tracked at [`phase2_idea.md`](./phase2_idea.md) per spec-gen Step 10 — no work in this plan.

## 2) Delivery structure

**Structure:** Epic → Story → Tasks → DoD. Four epics, 14 stories total.

### Story-level detail requirements

Every story below includes: Outcome, New files, Modified files (when applicable), Tasks, Key interfaces (when introducing new modules), and DoD.

### Conventions (project-specific)

- **No new migrations.** Per spec §9, Phase 1 introduces zero DB schema changes. Alembic head stays at `0021_judgment_lists_generation_params`.
- **Pure-domain module placement** at `backend/app/domain/demo/synthetic_ubi.py` matches the existing `backend/app/domain/{git,query,study,ubi}/` split.
- **Engine-write helper placement** at `backend/app/services/demo_ubi_seed.py` matches the existing `demo_seeding.py` placement (service-layer, async, owns httpx.AsyncClient).
- **Test layout:** `backend/tests/integration/<file>.py` is FLAT (no `services/` subdir — confirmed by `find backend/tests/integration` showing existing `test_demo_seeding.py` at the top level). `backend/tests/unit/<area>/<file>.py` IS subdivided. `ui/tests/e2e/<name>.spec.ts` is FLAT.
- **Conventional Commits per CLAUDE.md Rule #7.** No `--no-verify`.
- **DCO signoff required.** Every commit uses `git commit -s`.
- **No bare env vars for secrets** (Rule #2). N/A in this plan — no new secrets.
- **CLI/home-button parity per `bug_demo_reseed_fake_metric_regression`.** Every change in `reseed_demo_state` has a mirror in `scripts/seed_meaningful_demos.py:seed_scenario`. Plan Story 2.5 covers the CLI side explicitly.

### AI Agent Execution Protocol

0. Load context: read `architecture.md` and `state.md` before starting Story 1.1.
1. Implement Epic 1 (pure-domain + service helper + canonical mapping) first — these are unit-testable in isolation and de-risk Epic 2.
2. Implement Epic 2 (SCENARIOS catalog + reseed orchestrator + CLI parity) second — depends on Epic 1's modules.
3. Implement Epic 3 (frontend chip) third — depends on Epic 2 producing the demo data the chip surfaces describe.
4. Implement Epic 4 (tests + docs) last — fast-lane test (Story 4.1) actually rides alongside Epic 1 Story 1.3 as the verification of FR-3; the heavy-lane test (Story 4.2) lands after Epic 2 completes; E2E (Story 4.3) lands after Epic 3 ships the chips.

---

## Epic 1 — Pure-domain generator + canonical mapping + engine-write helper

**Goal:** ship the seed-side data-generation layer so Epic 2's reseed orchestrator can call `seed_synthetic_ubi(...)` with confidence the rows it writes will deterministically hit the target rungs.

### Story 1.1 — Canonical UBI index mapping JSON file

**Outcome:** A single `samples/ubi_index_mappings.json` file holds the canonical `ubi_queries` + `ubi_events` mappings; both the existing Playwright helper and the new Python generator load it instead of inlining the JSON.

**New files**

| File | Purpose |
|---|---|
| `samples/ubi_index_mappings.json` | Canonical mapping with two top-level keys `ubi_queries.mappings.properties` and `ubi_events.mappings.properties`. Exact field types per [`seed_ubi.ts:26-51`](../../../../ui/tests/e2e/helpers/seed_ubi.ts) (keyword/text/date/integer/float). |
| `backend/tests/unit/services/test_demo_ubi_seed.py` | Hosts the FR-1 round-trip test `test_mapping_file_round_trips_to_seed_ubi_helper_shape` plus subsequent Story 1.3 helper tests. **File and test name match spec FR-1 verbatim.** |

**Modified files**

| File | Change |
|---|---|
| `ui/tests/e2e/helpers/seed_ubi.ts` | Replace inlined `UBI_QUERIES_MAPPING` + `UBI_EVENTS_MAPPING` consts with `JSON.parse(readFileSync('samples/ubi_index_mappings.json', 'utf8'))` resolved relative to the Playwright `process.cwd()`. Keep the rest of the helper (delete-then-recreate posture for E2E) unchanged. |

**Tasks**
1. Write `samples/ubi_index_mappings.json` by copying the two mapping dicts from `seed_ubi.ts:26-51` exactly.
2. Add the round-trip unit test that loads the JSON and asserts deep equality vs a hard-coded literal mirroring the original TS const.
3. Refactor `seed_ubi.ts` to load from the JSON via `readFileSync` + `JSON.parse`, deleting the two `const UBI_*_MAPPING` declarations.
4. Run `cd ui && pnpm test` to confirm no E2E helper unit tests break.

**DoD**
- [ ] `samples/ubi_index_mappings.json` exists with both top-level keys.
- [ ] `pytest backend/tests/unit/services/test_demo_ubi_seed.py::test_mapping_file_round_trips_to_seed_ubi_helper_shape -v` green (matches spec FR-1 test name).
- [ ] `seed_ubi.ts` no longer inlines the mapping dicts; uses the canonical JSON.
- [ ] No vitest / Playwright helper smoke regression.

### Story 1.2 — Pure-domain synthetic UBI generator

**Outcome:** `backend/app/domain/demo/synthetic_ubi.py` provides `fabricate_ubi_for_scenario(...)` returning deterministic `(queries, events)` lists that hit the target rung when written to ES.

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/demo/__init__.py` | Empty package init. |
| `backend/app/domain/demo/synthetic_ubi.py` | Pure-domain generator: dataclasses `UbiQueryRow`, `UbiEventRow`, `RungVolumes`; functions `_volumes_for_rung`, `_decay_weights`, `_allocate_impressions` (Hamilton allocator), `_click_probability_for_rating`, `fabricate_ubi_for_scenario`. |
| `backend/tests/unit/domain/test_synthetic_ubi.py` | Unit tests: determinism, per-rung event-count exact sums, click-probability mapping, position-bias monotone-decreasing impression-per-rank, all events carry `application=target_application`. |

**Key interfaces** (`backend/app/domain/demo/synthetic_ubi.py`)

```python
from dataclasses import dataclass
from typing import Literal

UbiRung = Literal["rung_1", "rung_2", "rung_3"]


@dataclass(frozen=True)
class UbiQueryRow:
    query_id: str
    user_query: str
    application: str
    timestamp: str  # ISO-8601


@dataclass(frozen=True)
class UbiEventRow:
    query_id: str
    action_name: Literal["impression", "click", "dwell"]
    object_id: str
    application: str
    timestamp: str
    position: int | None = None
    dwell_seconds: float | None = None


@dataclass(frozen=True)
class RungVolumes:
    """Per-rung event-volume targets. Five fields per spec FR-2:
    the first three drive event counts; the last two embed the expected
    scenario shape for unit-test pinning (so a regression that changes
    queries-per-scenario or docs-per-query is caught at the generator
    level, not at the integration test)."""
    impressions_total: int
    clicks_total: int
    dwell_events_total: int
    num_queries: int               # FR-2: expected query count per scenario for this rung
    num_docs_per_query: int        # FR-2: expected docs-per-query for this rung


def _volumes_for_rung(rung: UbiRung) -> RungVolumes: ...
# rung_3 → RungVolumes(560, 40, 40, num_queries=5, num_docs_per_query=5)  → 640 total events
# rung_2 → RungVolumes(200, 20, 20, num_queries=5, num_docs_per_query=5)  → 240 total events
# rung_1 → RungVolumes(40, 5, 5,    num_queries=5, num_docs_per_query=3)  → 50 total events


def _decay_weights(num_docs: int, decay: float = 0.6) -> list[float]:
    """weights[n] = decay^n for n in [0, num_docs); not yet normalized."""


def _allocate_impressions(impressions_total: int, num_docs: int, decay: float = 0.6) -> list[int]:
    """Hamilton (largest-remainder) allocator. Returns a list whose sum == impressions_total."""


def _click_probability_for_rating(rating: int, base: float = 1.0) -> float:
    """Maps rating to a click probability scaled by `base`:
    0 → 0.0 × base, 1 → 0.2 × base, 2 → 0.5 × base, 3 → 0.8 × base.
    `base` lets callers parameterize correlation strength
    (default 1.0 matches spec FR-2 default).
    Raises ValueError on rating outside {0,1,2,3}."""


def fabricate_ubi_for_scenario(
    *,
    scenario_judgments_map: list[tuple[int, str, int]],   # (query_index, doc_id, rating)
    query_id_by_index: dict[int, str],                     # API-assigned UUID per query_index
    query_text_by_index: dict[int, str],                   # see "Signature note" below
    target_application: str,
    target_rung: UbiRung,
    seed_anchor_iso: str,                                  # reseed's started_at ISO timestamp
    seed: int = 42,
) -> tuple[list[UbiQueryRow], list[UbiEventRow]]: ...
```

**Signature note (refines spec FR-2):** spec FR-2 omits `query_text_by_index` from the contract signature, but `UbiQueryRow.user_query` requires a text value — the spec's data shape implies the input must be provided somehow. This plan makes it an explicit parameter (cleaner than threading the SCENARIOS' full `queries` list through). The CLI and reseed call sites both construct it from the same `qtext_to_id` mapping the existing orchestrator builds at [demo_seeding.py:1252](../../../../backend/app/services/demo_seeding.py#L1252). Update spec FR-2's signature in the same PR as Story 1.2 lands so the contract stays accurate.

**Tasks**
1. Add the dataclasses + `_volumes_for_rung` constants (rung_3=560/40/40, rung_2=200/20/20, rung_1=40/5/5).
2. Add `_decay_weights` and `_allocate_impressions` (Hamilton) + unit test that `sum(_allocate_impressions(t, n)) == t` for every `(impressions_total, num_docs_per_query)` pair actually used by `_volumes_for_rung`'s return values — currently `{(560,5), (200,5), (40,3)}`. (Covers FR-2's "all five num_docs choices in the catalog" — Phase 1 only uses two distinct num_docs values because the rich scenario is excluded; if Phase 2 adds more docs-per-query shapes, this list grows.)
3. Add `_click_probability_for_rating` with the `base` parameter + unit test on the four ratings at `base=1.0` AND at `base=0.5` (proves the scaling) + ValueError on `rating=4` AND `rating=-1`.
4. Implement `fabricate_ubi_for_scenario`:
   - For each query in `query_id_by_index`: emit one `UbiQueryRow` with `timestamp = seed_anchor_iso`.
   - Compute `volumes = _volumes_for_rung(target_rung)`.
   - Distribute impressions: for each query, allocate `volumes.impressions_total / num_queries` (rounded with leftover to last query) across the query's docs using `_allocate_impressions`. Emit one `UbiEventRow(action='impression', position=rank+1)` per impression with a deterministic in-window timestamp via `random.Random(seed).uniform`.
   - Distribute clicks: build the candidate (query, doc, rating) pairs from `scenario_judgments_map`; weight by `_click_probability_for_rating(rating)`; Bernoulli-sample using `random.Random(seed)` until exactly `volumes.clicks_total` clicks land. Emit `UbiEventRow(action='click', position=None)` plus a paired `UbiEventRow(action='dwell', dwell_seconds=<per-rating>)`. Per-rating dwell ranges: 3→[30,60], 2→[10,30], 1→[3,10], 0 unused.
5. Add unit tests:
   - Determinism: same inputs → identical output lists (`assert events_run1 == events_run2`).
   - Volume invariants: `len(impressions) == volumes.impressions_total`, `len(clicks) == volumes.clicks_total`, `len(dwells) == volumes.dwell_events_total` for each rung.
   - `all(ev.application == target_application for ev in events)`.
   - All event `timestamp` values fall inside `[seed_anchor - 60s, seed_anchor]` (parse ISO, compare).
   - Click-rating correlation: among clicked (query, doc) pairs, the **mean** rating exceeds the mean rating of all judgment-map pairs (sanity check that the Bernoulli weighting biases toward higher ratings).

**DoD**
- [ ] All 9 unit tests green.
- [ ] `make lint && make typecheck` green.
- [ ] Generator has zero imports from `httpx`, `sqlalchemy`, `backend.app.core.settings`, or `backend.app.adapters` (verified by an `ast`-based import-allowlist test or visual grep).

### Story 1.3 — Engine-write helper with scenario allowlist guard

**Outcome:** `backend/app/services/demo_ubi_seed.py` provides `ensure_ubi_indices(...)` and `seed_synthetic_ubi(...)` that the reseed orchestrator can call. The allowlist guard rejects non-demo scenario/target pairs.

**New files**

| File | Purpose |
|---|---|
| `backend/app/services/demo_ubi_seed.py` | `DEMO_UBI_SCENARIO_ALLOWLIST` frozenset of `(scenario_slug, target_application)` pairs; `ensure_ubi_indices`; `seed_synthetic_ubi`. |
| `backend/tests/unit/services/test_demo_ubi_seed.py` (extended) | Unit tests: allowlist guard accepts the 3 demo pairs, rejects every other pair with a clear error; bulk-write payload shape; `?refresh=wait_for` query param present; **NDJSON body ends with trailing `\n`**; **`application` tag enforced/normalized on every row**. Same file as the FR-1 round-trip test from Story 1.1 — additive. |

**Key interfaces** (`backend/app/services/demo_ubi_seed.py`)

```python
from typing import Final
import json
from pathlib import Path
import httpx

from backend.app.domain.demo.synthetic_ubi import UbiQueryRow, UbiEventRow

DEMO_UBI_SCENARIO_ALLOWLIST: Final[frozenset[tuple[str, str]]] = frozenset({
    ("acme-products-prod", "products"),
    ("corp-docs-search", "docs-articles"),
    ("jobs-marketplace-prod", "job-listings"),
})

# In-container path mirrors _SAMPLES_DIR in demo_seeding.py
_MAPPING_PATH: Final[Path] = Path("/app/samples/ubi_index_mappings.json")


async def ensure_ubi_indices(
    *,
    engine_client: httpx.AsyncClient,
    engine_base_url: str,
    host_auth: tuple[str, str],
) -> None:
    """PUT both ubi_queries and ubi_events with the canonical mapping.
    Tolerates 400 resource_already_exists per the same posture as
    seed_ubi.ts:createIndex (handles concurrent worker race)."""


async def seed_synthetic_ubi(
    *,
    engine_client: httpx.AsyncClient,
    engine_base_url: str,
    host_auth: tuple[str, str],
    scenario_slug: str,
    target_application: str,
    queries: list[UbiQueryRow],
    events: list[UbiEventRow],
) -> int:
    """Bulk-write via _bulk?refresh=wait_for. Returns event count.

    Raises:
        ValueError: if (scenario_slug, target_application) is not in
                    DEMO_UBI_SCENARIO_ALLOWLIST.
    """
```

**Tasks**
1. Implement `ensure_ubi_indices` — PUT `{engine_base_url}/ubi_queries` and `/ubi_events` with mappings loaded from `_MAPPING_PATH`. Accept HTTP 200/201/400 (the last only when the response body contains `resource_already_exists_exception`); raise `DemoSeedingError`-style error otherwise.
2. Implement `seed_synthetic_ubi`:
   - Pair `(scenario_slug, target_application)` guard: raise `ValueError(f"seed_synthetic_ubi refuses non-demo (scenario, target): ({scenario_slug!r}, {target_application!r}) not in DEMO_UBI_SCENARIO_ALLOWLIST")` if not allowlisted.
   - **`application` normalization (FR-3 contract)**: before serializing, replace `application` on every `UbiQueryRow` and `UbiEventRow` with `target_application` (defense-in-depth — the generator already sets it, but the helper is the contract boundary). Alternatively raise `ValueError("seed_synthetic_ubi: row.application mismatch")` on the first divergent row. Choose normalize-then-write so the helper is the source of truth.
   - Build NDJSON: alternate `{"index": {}}` + the row's `dataclasses.asdict()` for each query in `queries`, then each event in `events`. Body construction: `body = "\n".join(lines) + "\n"` — Elasticsearch's `_bulk` API requires the **trailing newline**; omitting it causes silent skipping of the final row on some ES versions.
   - Two POSTs: `{engine_base_url}/ubi_queries/_bulk?refresh=wait_for` and `{engine_base_url}/ubi_events/_bulk?refresh=wait_for`. Use `Content-Type: application/x-ndjson`.
   - Return `len(events)`.
3. Add unit tests against a mocked `httpx.AsyncClient`:
   - All 3 allow-pairs round-trip (write completes, count returned).
   - 5 reject-pairs (each demo slug × wrong target; production slug × demo target; entirely unknown pair) raise `ValueError` with the exact message format.
   - Bulk POST URL includes `?refresh=wait_for`.
   - First line of every NDJSON body is `{"index": {}}` (proves bulk indexing, not create).
   - **NDJSON body ends with exactly one `\n`** — `assert body.endswith("\n") and not body.endswith("\n\n")`.
   - **Content-Type header is `application/x-ndjson`** on both bulk POSTs.
   - **`application` normalization**: pass rows with the wrong `application` value; assert the bulk-body rows all carry `application == target_application`.
   - On engine 400 for a `_bulk` (not just for index PUT), the helper raises `DemoSeedingError("ubi_seed/bulk_write: HTTP 400 ...")`.

**Modified files**

| File | Change |
|---|---|
| `backend/app/services/__init__.py` (if it exports anything) | No change required — services modules are imported directly by call sites. |

**DoD**
- [ ] `pytest backend/tests/unit/services/test_demo_ubi_seed.py -v` green (round-trip + 11 helper tests including the NDJSON trailing-newline assertion and the `application` normalization test).
- [ ] `make lint && make typecheck` green.
- [ ] Allowlist tuple is `frozenset` (immutable; verified by an `isinstance(..., frozenset)` assertion in the test).

---

## Epic 1 gate (hard stop)

Before starting Epic 2, all three Epic 1 stories must be green AND:

- [ ] `pytest backend/tests/unit/domain/test_synthetic_ubi.py backend/tests/unit/services/test_demo_ubi_seed*.py -v` green.
- [ ] `samples/ubi_index_mappings.json` round-trips equal to the original `seed_ubi.ts` shape.
- [ ] `seed_synthetic_ubi` reject-path returns the exact ValueError message format expected by Story 2.2.
- [ ] No `httpx`/`asyncio`/`sqlalchemy` imports in `backend/app/domain/demo/synthetic_ubi.py` (purity invariant — `make lint` is too loose for this; the dedicated import-allowlist test from Story 1.2 covers it).

---

## Epic 2 — SCENARIOS catalog + reseed orchestrator + CLI parity

**Goal:** the home-button reseed and `make seed-demo` both produce the dual-list + dual-study demo state with deterministic rung assignments.

### Story 2.1 — Add `ubi_target_rung` + `ubi_converter` keys to SCENARIOS

**Outcome:** Each entry in `scripts/seed_meaningful_demos.py` `SCENARIOS` carries (optional) UBI configuration; a module-level assertion enforces `ubi_converter is None ↔ ubi_target_rung is None`.

**Modified files**

| File | Change |
|---|---|
| `scripts/seed_meaningful_demos.py` | Add `ubi_target_rung` + `ubi_converter` keys to each of the 4 SCENARIOS entries (acme=`("rung_3","ctr_threshold")`, corp=`("rung_1","hybrid_ubi_llm")`, jobs=`("rung_2","hybrid_ubi_llm")`, news=both `None`). Add a module-level assertion loop validating the implication. |

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/scripts/test_scenarios_ubi_config.py` | Unit tests: assert exactly 3 scenarios have non-None UBI config; assert the 3 (slug, target) pairs match `DEMO_UBI_SCENARIO_ALLOWLIST`; assert the implication holds; assert `news-search-staging` has both None. |

**Tasks**
1. Patch each SCENARIOS entry with the new keys per the D-2 lock in the spec.
2. Add the module-level invariant assertion: `for s in SCENARIOS: assert (s.get("ubi_converter") is None) == (s.get("ubi_target_rung") is None)`.
3. Add the unit test file pinning the parity with `DEMO_UBI_SCENARIO_ALLOWLIST` (imports from `backend.app.services.demo_ubi_seed`).

**DoD**
- [ ] `pytest backend/tests/unit/scripts/test_scenarios_ubi_config.py -v` green (4 tests).
- [ ] Module import (`python -c "from scripts.seed_meaningful_demos import SCENARIOS"`) succeeds (no assertion failure).

### Story 2.2 — Wire synthetic UBI seeding into `reseed_demo_state` + cleanup pass

**Outcome:** `reseed_demo_state` ensures the two UBI indices exist (once per invocation, after cleanup deletes them) and writes synthetic events for each UBI-enabled scenario at the correct point in the per-scenario flow. The reseed cleanup pass deletes `ubi_queries` + `ubi_events` at the start.

**Insertion point (precise — supersedes any earlier order language).** The synthetic generator requires the API-assigned `query_id` values to label its `ubi_queries` rows. The reseed builds `qtext_to_id` at step 2f (`get_queries`, [demo_seeding.py:1244-1252](../../../../backend/app/services/demo_seeding.py#L1244-L1252)) and writes the LLM judgment list at step 2g ([demo_seeding.py:1282-1296](../../../../backend/app/services/demo_seeding.py#L1282-L1296)). The new UBI sub-steps land **between 2f and 2g**, NOT between `_refresh` and `post_cluster`. This is a refinement of spec FR-4's prose phrasing ("after engine docs are indexed") — engine writes are still on the same `engine_client`; the timing constraint is "after the API has minted query UUIDs", which is step 2f.

**Modified files**

| File | Change |
|---|---|
| `scripts/seed_meaningful_demos.py` | Add `"ubi_queries"` and `"ubi_events"` to `DEMO_ES_INDICES` (FR-6) — imported into `demo_seeding.py:45-50` so the cleanup pass sees the additions automatically. |
| `backend/app/services/demo_seeding.py` | (a) In the scenario loop at ~line 1141, after step 2f (line 1252) and before step 2g (line 1282), branch on `scenario.get("ubi_target_rung")`: if non-None, run `_ensure_ubi_indices_local_once` → `fabricate_ubi_for_scenario` → `seed_synthetic_ubi`. (b) Capture `seed_anchor_iso = _now_iso()` from the orchestrator top (line 1099 `started_at = time.monotonic()`; separately capture `started_at_dt = datetime.now(UTC)` for ISO conversion). (c) Maintain a local `ubi_indices_ready: bool = False` inside the `reseed_demo_state` body; flip it on first successful `ensure_ubi_indices` call so subsequent scenarios skip the PUT. |

**Key interfaces** (additions inside `reseed_demo_state` — NOT module-level)

```python
# Inside reseed_demo_state(...) body, before the scenario loop:
ubi_indices_ready: bool = False  # local, per-invocation; resets every reseed (cleanup
                                  # deletes the indices at start, so this MUST be local)

# Inside the per-scenario branch:
if scenario.get("ubi_target_rung") is not None:
    if not ubi_indices_ready:
        await ensure_ubi_indices(
            engine_client=engine_client,
            engine_base_url=engine_base,
            host_auth=host_auth,
        )
        ubi_indices_ready = True
    queries, events = fabricate_ubi_for_scenario(...)
    await seed_synthetic_ubi(...)
```

**Why a local boolean instead of a module-level cached function:** module-level caching persists across `reseed_demo_state` invocations within the same worker process. Since the cleanup pass DELETEs the indices on every reseed start, a module-level guard would skip the PUT on the second reseed and subsequent bulk writes would fail against a missing index. The local boolean is bound to the current invocation and naturally resets per call.

**Tasks**
1. Add `"ubi_queries"`, `"ubi_events"` to `DEMO_ES_INDICES` in `scripts/seed_meaningful_demos.py`.
2. In `reseed_demo_state`, before the scenario loop (around line 1141): capture `started_at_dt = datetime.now(UTC)` and `seed_anchor_iso = started_at_dt.isoformat()`. Initialize `ubi_indices_ready = False`.
3. Inside the scenario loop, between lines 1252 (`qtext_to_id` built) and 1282 (judgments import POST), branch on `scenario.get("ubi_target_rung")`:
   - If non-None: (a) PUT the indices once via the `ubi_indices_ready` gate; (b) build `query_id_by_index` and `query_text_by_index` dicts from `qtext_to_id` + the SCENARIOS' `scenario_queries`; (c) call `fabricate_ubi_for_scenario(...)`; (d) call `seed_synthetic_ubi(engine_client=engine_client, engine_base_url=engine_base, host_auth=host_auth, scenario_slug=slug, target_application=target, queries=queries, events=events)`.
4. Use `(scenario["slug"], scenario["target"])` as the allowlist pair — matches `DEMO_UBI_SCENARIO_ALLOWLIST` exactly.

**DoD**
- [ ] Manual run of `reseed_demo_state` against a real `make up` stack writes events into both UBI indices (verified by `curl http://127.0.0.1:9200/ubi_events/_count?q=application:products` returning ≥ 640).
- [ ] Cleanup pass DELETEs both indices on the next reseed (verified by `curl http://127.0.0.1:9200/ubi_queries` returning 404 after cleanup).
- [ ] Per-scenario rung classifier output: `classify_rung(...)` returns `"rung_3"` for acme, `"rung_2"` for jobs, `"rung_1"` for corp, `"rung_0"` for news (asserted in Story 4.2 heavy-lane test; this story verifies manually).
- [ ] No regression in existing `test_demo_seeding.py` (run `pytest backend/tests/integration/test_demo_seeding.py -v`).

### Story 2.3 — UBI judgment dispatch + dual study seeding + study renaming

**Outcome:** For each UBI-enabled scenario, the reseed dispatches a UBI judgment generation against the synthetic data, polls it to `complete`, and then runs a second `_seed_real_study_for_scenario` call against that judgment list. Both studies are renamed with `(LLM)` / `(UBI)` suffixes.

**Modified files**

| File | Change |
|---|---|
| `backend/app/services/demo_seeding.py` | (a) After step 2g (existing LLM judgment-list import at line 1284-1296), for UBI-enabled scenarios, POST `/api/v1/judgments/generate-from-ubi` with the body specified in spec FR-4 (using `seed_anchor` for `since/until`). (b) Poll `GET /api/v1/judgment-lists/{id}` until `status == "complete"` or `"failed"` (180s ceiling, 3s interval). (c) Call `_seed_real_study_for_scenario` a second time with the UBI judgment-list id. (d) In step 3 (study rename, line 1346), use `f"{study_name} (LLM)"` for the LLM studies and `f"{study_name} (UBI)"` for the UBI studies. |

**Key interfaces** (additions)

```python
async def _poll_judgment_list_until_terminal(
    api_client: httpx.AsyncClient,
    judgment_list_id: str,
    *,
    slug: str,
    ceiling_s: float = 180.0,
    interval_s: float = 3.0,
) -> dict:
    """GET /api/v1/judgment-lists/{id} until status ∈ {complete, failed}.

    Raises DemoSeedingError on 'failed' or on poll-ceiling timeout.
    """
```

**Tasks**
1. Implement `_poll_judgment_list_until_terminal` — mirrors the existing study-poll loop at `demo_seeding.py:685-707` for shape.
2. After step 2g (LLM list imported), branch on `scenario.get("ubi_converter")`:
   - Build the `CreateJudgmentListFromUbiRequest` body:
     ```python
     ubi_body = {
         "name": f"{scenario['judgment_list_name']} (UBI)",
         "query_set_id": qset_id,
         "cluster_id": cluster_id,
         "target": scenario["target"],
         "since": (started_at_dt - timedelta(seconds=60)).isoformat(),
         "until": started_at_dt.isoformat(),
         "converter": scenario["ubi_converter"],
         "mapping_strategy": "reject",
     }
     if scenario["ubi_converter"] == "hybrid_ubi_llm":
         ubi_body["current_template_id"] = template_id
         ubi_body["rubric"] = scenario["rubric"]
     ```
   - POST `/api/v1/judgments/generate-from-ubi` with that body; read `.judgment_list_id` from the response.
   - Poll until terminal via `_poll_judgment_list_until_terminal`.
3. After the UBI judgment list reaches `complete`, call `_seed_real_study_for_scenario(api_client, scenario=scenario, cluster_id=cluster_id, template_id=template_id, qset_id=qset_id, judgment_list_id=<ubi_jlist_id>, status_callback=status_callback, progress=progress)` — same shape as the existing call at line 1307.
4. Track both study IDs: append `(slug, llm_study_id, llm_study_name)` and `(slug, ubi_study_id, ubi_study_name)` to `results`. Use `f"{scenario['study_name']} (LLM)"` and `f"{scenario['study_name']} (UBI)"` as the names.
5. In step 3 rename loop (line 1348), use the names as already set in `results` — no additional logic needed.
6. **Do not** bump `scenarios_total` (FR-10 requires it stay at `len(SCENARIOS) + 1 = 5`). `scenarios_completed` advances per-scenario, not per-study — three additional studies per UBI scenario still count as one scenario completion. The progress visibility comes entirely from the new `current_step` strings (Story 2.4), not from `scenarios_total`/`scenarios_completed`.

**DoD**
- [ ] Manual reseed produces 8 `judgment_lists` rows and 8 `studies` rows.
- [ ] The 3 UBI scenarios each have exactly two studies, named `"<name> (LLM)"` and `"<name> (UBI)"`.
- [ ] The 3 UBI judgment lists have `generation_params->>'generation_kind' = 'ubi'` AND `generation_params->>'converter'` matches the scenario's `ubi_converter`.
- [ ] A simulated UBI worker failure (manually set the judgment_list row to `status='failed'` mid-poll) causes `DemoSeedingError("ubi_judgments/{slug}: failed ...")` to bubble to the 503 route response.

### Story 2.4 — Status sub-step labels + structured-log events

**Outcome:** The reseed status banner shows operator-visible UBI sub-steps; structured-log events emit at start/complete of each major UBI step.

**Modified files**

| File | Change |
|---|---|
| `backend/app/services/demo_seeding.py` | Add the 5 `current_step` strings per FR-10 + 4 structured-log events at the appropriate points. |

**Tasks**
1. Set `progress.current_step` at:
   - `f"{slug}: writing synthetic UBI ({rung}, {event_count} events)"` before `seed_synthetic_ubi`.
   - `f"{slug}: dispatching UBI judgment generation ({converter})"` before the POST.
   - `f"{slug}: polling UBI judgment list {id[:8]} for completion"` inside the poll loop.
   - `f"{slug}: creating UBI study (max_trials=12)"` before the second `_seed_real_study_for_scenario`.
   - `f"{slug}: polling UBI study {id[:8]} for trial completion"` (handled by the existing study-poll inside `_seed_real_study_for_scenario` — it uses `study_id[:8]`; no change required there).
2. Emit log events:
   - `logger.info("demo_reseed_ubi_seed_started", extra={"slug": slug, "rung": target_rung, "event_count_target": ...})`
   - `logger.info("demo_reseed_ubi_seed_complete", extra={"slug": slug, "event_count": ..., "duration_ms": ...})`
   - `logger.info("demo_reseed_ubi_judgment_dispatch_started", extra={"slug": slug, "converter": converter})`
   - `logger.info("demo_reseed_ubi_study_complete", extra={"slug": slug, "study_id": ubi_study_id, "duration_ms": ...})`
3. Use `time.monotonic()` deltas for `duration_ms` (mirrors existing `started_at = time.monotonic()` pattern at line 1099).

**DoD**
- [ ] Manual reseed shows all 5 sub-step labels in the home-button banner over a typical 13-19 min reseed.
- [ ] `docker compose logs api worker | grep demo_reseed_ubi_` shows the 4 structured events for each of the 3 UBI scenarios.

### Story 2.5 — CLI parity in `scripts/seed_meaningful_demos.py:seed_scenario`

**Outcome:** `make seed-demo` produces the same 8 judgment lists + 8 studies + same per-rung event counts as the home button.

**Modified files**

| File | Change |
|---|---|
| `scripts/seed_meaningful_demos.py` | In `seed_scenario` (line ~851), mirror the wiring from Story 2.2 + 2.3: after queries are seeded, for UBI scenarios run `ensure_ubi_indices` → `fabricate_ubi_for_scenario` → `seed_synthetic_ubi`; after LLM judgments import, dispatch UBI generation + poll + create the paired UBI study. Use the same Optuna config + `(LLM)`/`(UBI)` naming. |

**Tasks**
1. Mirror the Story 2.2 insertion in `seed_scenario` (the CLI's per-scenario flow).
2. Mirror the Story 2.3 UBI judgment dispatch + dual study seeding.
3. Mirror the Story 2.4 status / log emission (the CLI logs differently — print to stdout — but the events should be parallel).
4. Run `make seed-demo` end-to-end on a clean stack as the per-story manual verification.

**DoD**
- [ ] `make seed-demo` succeeds on a clean stack, producing 8 judgment lists + 8 studies.
- [ ] The `(scenario_slug, target, ubi_target_rung)` triples match between CLI output and the home-button output — verified by Story 4.2's CLI parity test asserting structural equivalence (per spec §4 "structurally-equivalent").

---

## Epic 2 gate (hard stop)

Before starting Epic 3, Epic 2 must be green AND:

- [ ] A clean manual reseed produces 8 judgment lists + 8 studies + the per-cluster rungs match AC-2 exactly (acme=3, jobs=2, corp=1, news=0).
- [ ] No regression in `backend/tests/integration/test_demo_seeding.py` (existing test).
- [ ] CLI and home button produce the same row counts on independent clean-stack runs.

---

## Epic 3 — Frontend disclaimer chips

**Goal:** Five UI surfaces correctly render the "Synthetic demo data" chip on the three synthetic-UBI demo clusters, never on production clusters and never on `news-search-staging`.

### Story 3.1 — Add `isDemoSyntheticUbiClusterName` helper + glossary key + CI parity extension

**Outcome:** A new TypeScript helper exists in `ui/src/lib/demo-data.ts` for the chip's gating; the glossary has a new key; the existing CI parity guard verifies the three slugs match the backend allowlist.

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/demo-data.ts` | Add `DEMO_SYNTHETIC_UBI_CLUSTER_SLUGS = ['acme-products-prod', 'corp-docs-search', 'jobs-marketplace-prod'] as const`. Add `isDemoSyntheticUbiClusterName(name: string): boolean` mirroring the existing `isDemoClusterName` pattern. Add a top-of-file source-of-truth comment: `// Values must match backend/app/services/demo_ubi_seed.py DEMO_UBI_SCENARIO_ALLOWLIST` |
| `ui/src/lib/glossary.ts` | Add to the `feat_ubi_judgments` section (line ~483): `ubi_synthetic_demo_data: { label: "Synthetic demo data", helpText: "This UBI data was fabricated by the demo reseed to demonstrate the UBI path; it is not real user behavior." }` |
| `scripts/ci/verify_demo_slug_parity.sh` | Extend to also pin `DEMO_SYNTHETIC_UBI_CLUSTER_SLUGS` against the 3 first-position entries of `DEMO_UBI_SCENARIO_ALLOWLIST`. |
| `ui/src/__tests__/lib/demo-data.test.ts` (or new file if absent) | Add tests: `isDemoSyntheticUbiClusterName('acme-products-prod') === true`; `isDemoSyntheticUbiClusterName('news-search-staging') === false`; `isDemoSyntheticUbiClusterName('production-real-cluster') === false`. |

**Tasks**
1. Add the helper + constant to `demo-data.ts` with the source-of-truth comment.
2. Add the glossary key in the `feat_ubi_judgments` section.
3. Extend the parity CI script — read both Python and TS allowlists, assert the three slugs are present in both.
4. Add the three vitest cases.

**DoD**
- [ ] `cd ui && pnpm test src/__tests__/lib/demo-data.test.ts` green.
- [ ] `bash scripts/ci/verify_demo_slug_parity.sh` exits 0.
- [ ] Glossary entry visible via the existing glossary lookup mechanism (manual UI smoke).

### Story 3.2 — `<DemoBadge variant="synthetic-ubi">` chip on five surfaces

**Outcome:** The chip renders on the five surfaces enumerated in spec FR-7, gated by `isDemoSyntheticUbiClusterName(...)` + (for UBI-only surfaces) `generation_params?.generation_kind === 'ubi'`.

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/common/demo-badge.tsx`](../../../../ui/src/components/common/demo-badge.tsx) | Add a `variant?: "default" \| "synthetic-ubi"` prop. For `"synthetic-ubi"`, render the "Synthetic demo data" text with the `ubi_synthetic_demo_data` glossary tooltip + `aria-label="Synthetic demo data"`. Tooltip MUST be reveal-on-keyboard-focus AND hover (per spec §13 accessibility). |
| [`ui/src/components/query-sets/generate-judgments-dialog.tsx`](../../../../ui/src/components/query-sets/generate-judgments-dialog.tsx) | Insert the chip next to each UBI method-picker `<SelectItem>` for `ctr_threshold`, `dwell_time`, `hybrid_ubi_llm`, gated by `isDemoSyntheticUbiClusterName(cluster.name)`. |
| [`ui/src/components/judgments/judgment-list-header.tsx`](../../../../ui/src/components/judgments/judgment-list-header.tsx) | Insert the chip in the header line for `isDemoSyntheticUbiClusterName(cluster.name) && list.generation_params?.generation_kind === 'ubi'`. |
| [`ui/src/components/clusters/cluster-detail-summary.tsx`](../../../../ui/src/components/clusters/cluster-detail-summary.tsx) | Insert the chip adjacent to `<UbiRungBadge>`, gated by `isDemoSyntheticUbiClusterName(cluster.name)`. |
| [`ui/src/components/studies/study-header.tsx`](../../../../ui/src/components/studies/study-header.tsx) | Insert the chip next to the study title for studies whose judgment list has `generation_params.generation_kind === 'ubi'` AND `isDemoSyntheticUbiClusterName(cluster.name)`. **Verified location** — `<StudyHeader>` is rendered by `ui/src/app/studies/[id]/page.tsx`. |
| [`ui/src/components/dashboard/demo-data-banner.tsx`](../../../../ui/src/components/dashboard/demo-data-banner.tsx) | Append "Three demo clusters include simulated UBI clickstream so the UBI judgment + study path is visible end-to-end." to the existing copy. Prose-only — banner is not chip-gated per spec FR-7 #5. |
| [`ui/src/__tests__/components/common/demo-badge.test.tsx`](../../../../ui/src/__tests__/components/common/demo-badge.test.tsx) (extend) | Add vitest tests for the `synthetic-ubi` variant: text rendered; `aria-label` set; tooltip reveal-on-focus (use `keyboard.press('Tab')` + check tooltip visibility); tooltip text matches glossary key. |
| `ui/src/__tests__/components/judgments/judgment-list-header.test.tsx` (new) | **Three-branch** test: (a) synthetic-UBI demo cluster + UBI list → chip; (b) `news-search-staging` (demo cluster, no synthetic UBI) + UBI list → no chip; (c) non-demo cluster + UBI list → no chip. |
| `ui/src/__tests__/components/clusters/cluster-detail-summary.test.tsx` (new) | Three-branch chip-gating test on the cluster-detail surface. |
| `ui/src/__tests__/components/studies/study-header.test.tsx` (new) | Three-branch chip-gating test on the study-header surface. |
| `ui/src/__tests__/components/query-sets/generate-judgments-dialog.test.tsx` (new or extend) | Three-branch chip-gating test on the dialog method-picker surface. |
| `ui/src/__tests__/components/dashboard/demo-data-banner.test.tsx` (new or extend) | **Prose assertion** (NOT chip-gated): the new sentence renders. Single-branch test (banner is global; not gated per FR-7 #5). |

**Tasks**
1. Read the existing `<DemoBadge>` at [`ui/src/components/common/demo-badge.tsx`](../../../../ui/src/components/common/demo-badge.tsx) to confirm the current API and add the `variant` prop without breaking existing call sites.
2. Implement the chip changes in the 5 component files. Each gating expression must be exactly: `isDemoSyntheticUbiClusterName(cluster.name)` plus the UBI discriminator where relevant.
3. **Accessibility (FR-7 + spec §13):** the synthetic-ubi variant MUST be (a) keyboard-focusable (`tabindex="0"` or by wrapping in a focusable element if not already); (b) have `aria-label="Synthetic demo data"` so screen readers announce intent; (c) reveal its tooltip on keyboard focus, not hover-only — use the project's existing tooltip primitive (likely shadcn's `<Tooltip>` which supports both focus and hover triggers).
4. Write the chip-gating + accessibility vitest tests:
   - 4 surfaces × 3 branches = 12 chip-gating assertions (judgment-list-header, cluster-detail-summary, study-header, generate-judgments-dialog).
   - 1 prose assertion on `<DemoDataBanner>` (single-branch).
   - 3 accessibility assertions on `<DemoBadge variant="synthetic-ubi">` in the existing demo-badge test file (`aria-label`, keyboard-focusability, tooltip-on-focus).
5. Manual smoke: run `cd ui && pnpm dev` against a manually reseeded backend, verify the chip on each surface by clicking through AND tabbing through with the keyboard.

**Legacy behavior parity table** (Story 3.2 is **additive** to the existing components — no >100-LOC deletion):

> No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan. All Story 3.2 modifications are additive: inserting a chip next to an existing UI element. No existing handlers, validations, or state machinery is replaced.

**DoD**
- [ ] `cd ui && pnpm test` green; all 12 chip-gating assertions + 1 banner-prose assertion + 3 accessibility assertions pass.
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm build` all green.
- [ ] Manual smoke confirms the chip on all 5 surfaces against a reseeded backend, including keyboard navigation revealing the tooltip.
- [ ] `<DemoBadge variant="synthetic-ubi">` has `aria-label="Synthetic demo data"` (vitest asserts the rendered attribute).

---

## Epic 3 gate (hard stop)

Before starting Epic 4 tests, the chip MUST NOT render on `news-search-staging` (the negative case is the biggest correctness risk for this epic).

- [ ] All 16 vitest assertions green: 12 chip-gating (4 surfaces × 3 branches) + 1 banner prose + 3 accessibility (`aria-label`, keyboard-focusability, tooltip-on-focus).
- [ ] Manual confirmation: open `/clusters/news-search-staging` on a reseeded stack — no chip near UbiRungBadge, no chip on the cluster-detail header.

---

## Epic 4 — Tests + docs

### Story 4.1 — Fast-lane integration test

**Outcome:** A <60s integration test exercises `seed_synthetic_ubi` against the real ES container, verifies the rung classifier returns the target rung for one scenario, and runs even with `SKIP_HEAVY_CI=true`.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_demo_seeding_ubi_fast.py` | Always-on; <60s; isolates `acme-products-prod` rung_3 generator + writer + classifier. |

**Tasks**
1. Test setup: ensure `ubi_queries` + `ubi_events` indices are clean (DELETE via the test ES container's HTTP API).
2. Test body:
   - Call `fabricate_ubi_for_scenario(target_application="products", target_rung="rung_3", seed_anchor_iso="2026-01-01T00:00:00Z", ...)` with a minimal hand-built scenario_judgments_map.
   - Call `ensure_ubi_indices(...)` + `seed_synthetic_ubi(...)` against the test ES base URL.
   - Call `classify_rung(...)` (the real one from `backend/app/services/ubi_readiness.py`) and assert `rung == "rung_3"`.
3. Verify the canonical mapping file round-trip via the existing Story 1.1 unit test (already covered; reference it here in the docstring).
4. Mark with `@pytest.mark.integration` so it joins the standard suite.

**DoD**
- [ ] `pytest backend/tests/integration/test_demo_seeding_ubi_fast.py -v` green.
- [ ] Wall-clock < 60s on a typical dev laptop (assert via `pytest --durations=5`).
- [ ] Test passes under `SKIP_HEAVY_CI=true` (no special gating).

### Story 4.2 — Heavy-lane integration test + CLI parity test + AC-8 ceiling

**Outcome:** Full-reseed integration test asserts all 10 ACs against the live stack; CLI parity test confirms `make seed-demo` produces structurally-equivalent output; AC-8 ceiling at 1140s.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_demo_seeding_ubi_full.py` | Full `reseed_demo_state` + assertions for AC-1, AC-2, AC-8, AC-9, AC-10. Gated by `not os.environ.get("SKIP_HEAVY_CI")`. |
| `backend/tests/integration/test_seed_meaningful_demos_ubi.py` | CLI parity: run `seed_scenario` against a clean DB, assert the same row counts as the home button. Heavy lane. |

**Tasks**
1. Set up: clean Postgres + clean ES + Redis (use existing integration-test fixtures).
2. Run `reseed_demo_state(db, api_client, engine_client)` with the real stack; record `duration_s = time.monotonic() - start`.
3. Assertions (AC-1, AC-2, AC-9, AC-10):
   ```python
   # AC-1
   judgment_count = (await db.scalar(text("SELECT COUNT(*) FROM judgment_lists")))
   study_count = (await db.scalar(text("SELECT COUNT(*) FROM studies")))
   assert judgment_count == 8
   assert study_count == 8
   for slug, expected_converter in [
       ("acme-products-prod", "ctr_threshold"),
       ("corp-docs-search", "hybrid_ubi_llm"),
       ("jobs-marketplace-prod", "hybrid_ubi_llm"),
   ]:
       rows = await db.execute(text(
           "SELECT generation_params FROM judgment_lists jl "
           "JOIN clusters c ON jl.cluster_id = c.id WHERE c.name = :slug"
       ), {"slug": slug})
       gps = [r[0] for r in rows]
       assert len(gps) == 2  # one LLM (NULL) + one UBI (non-NULL)
       assert any(g is None for g in gps)  # LLM list
       ubi = next(g for g in gps if g is not None)
       assert ubi["generation_kind"] == "ubi"
       assert ubi["converter"] == expected_converter
   # AC-2 (includes acme-products-rich-prod as rung_0 — verifies the
   # rich scenario stays LLM-only per D-12; a future regression that
   # accidentally seeds UBI for the rich scenario would surface here)
   for slug, expected_rung in [
       ("acme-products-prod", "rung_3"),
       ("corp-docs-search", "rung_1"),
       ("jobs-marketplace-prod", "rung_2"),
       ("news-search-staging", "rung_0"),
       ("acme-products-rich-prod", "rung_0"),
   ]:
       cluster = await get_cluster_by_name(db, slug)
       query_set = (await get_query_sets_for_cluster(db, cluster.id))[0]
       readiness = await classify_rung(...)  # use the real classifier
       assert readiness.rung == expected_rung
   # AC-8
   assert duration_s < 1140, f"reseed wall-clock {duration_s}s exceeded ceiling 1140s"
   logger.info("demo_reseed_full_duration_s", extra={"duration_s": duration_s})
   # AC-10 — verify cleanup pass deletes BOTH ubi_queries AND ubi_events
   # (FR-6: both indices are added to DEMO_ES_INDICES). No second full
   # reseed — just direct `run_demo_reseed_cleanup` after sentinel insert.
   for index_name, doc_id, doc_payload in [
       ("ubi_queries", "__cleanup_sentinel__",
        {"query_id": "x", "user_query": "y", "application": "__sentinel__",
         "timestamp": "2026-01-01T00:00:00Z"}),
       ("ubi_events", "__cleanup_sentinel__",
        {"query_id": "x", "action_name": "impression", "object_id": "y",
         "application": "__sentinel__", "timestamp": "2026-01-01T00:00:00Z"}),
   ]:
       sentinel_resp = await engine_client.put(
           f"{es_base}/{index_name}/_doc/{doc_id}?refresh=wait_for",
           json=doc_payload, auth=_ES_DELETE_AUTH,
       )
       assert sentinel_resp.status_code in (200, 201)
   await run_demo_reseed_cleanup(engine_client)  # direct call — milliseconds
   # Both indices should be gone (404 on the index itself, not just the doc).
   for index_name in ("ubi_queries", "ubi_events"):
       index_check = await engine_client.get(
           f"{es_base}/{index_name}", auth=_ES_DELETE_AUTH,
       )
       assert index_check.status_code == 404, (
           f"cleanup did not delete {index_name}: HTTP {index_check.status_code}"
       )
   ```
4. AC-9 failure-mode test: use a fixture that mid-poll sets `judgment_lists.status = 'failed'` for the next UBI list, assert `DemoSeedingError` is raised.
5. CLI parity test (`test_seed_meaningful_demos_ubi.py`):
   - Invoke the **full top-level CLI path** (`python -m scripts.seed_meaningful_demos` or the equivalent function the `make seed-demo` Makefile target calls) so the rich `acme-products-rich-prod` scenario is included — NOT a per-scenario direct call which would miss the 5th study. The CLI parity contract per `bug_demo_reseed_fake_metric_regression` is at the top-level command, not at `seed_scenario`-per-call granularity.
   - After the CLI run, snapshot counts and per-scenario structure: 8 judgment lists, 8 studies, 5 scenarios completed (4 small + 1 rich), same per-rung event counts on the 3 UBI scenarios as the home-button run.
   - Per §4 spec parity rule: compare **structural** equivalence (row counts, names, configs, rating values, per-rung event counts) — NOT timestamps. `created_at` / `id` (UUIDv7 embeds wall-clock) / `generation_params.since` are explicitly excluded from the comparison.

**DoD**
- [ ] `SKIP_HEAVY_CI= pytest backend/tests/integration/test_demo_seeding_ubi_full.py -v` green.
- [ ] AC-8 ceiling enforced as a hard `assert duration_s < 1140` (NOT p95 calculation per spec cycle-3 patch).
- [ ] CLI parity test green on the same heavy-lane run.

### Story 4.3 — E2E spec for demo-ubi UI surfaces

**Outcome:** A Playwright spec at `ui/tests/e2e/demo-ubi.spec.ts` (FLAT path) asserts the 5 user-visible AC-2/AC-4/AC-5/AC-6 behaviors against a real reseeded stack.

**New files**

| File | Purpose |
|---|---|
| `ui/tests/e2e/demo-ubi.spec.ts` | Playwright spec: `beforeAll` POSTs to `/api/v1/_test/demo/reseed`, polls until `complete` (25-min ceiling), then runs the 5 test cases enumerated in spec FR-12. |

**Tasks**
1. `beforeAll`: invoke `POST /api/v1/_test/demo/reseed` via the Playwright `request` fixture; poll `GET` (the existing reseed-status endpoint) until `status === "complete"` or fail with a diagnostic. Mark the test `test.setTimeout(25 * 60 * 1000)` to allow the 25-min ceiling.
2. Test 1 — `/clusters/{acme_id}` shows `rung_3` badge + synthetic-data chip. Discover `acme_id` via `request.get('/api/v1/clusters')` filtered by `name === 'acme-products-prod'`.
3. Test 2 — Generate-judgments dialog method-picker chip visible on acme query set.
4. Test 3 — Acme UBI judgment-list detail page shows `<ValueDeltaCard>` with non-zero deltas + synthetic chip in header.
5. Test 4 — Acme `(UBI)` study detail page shows synthetic chip next to title.
6. Test 5 — `/clusters/news-search-staging` shows `rung_0` badge + on-ramp nudge + **no** synthetic-data chip (negative case).
7. **Real-backend rule:** No `page.route()` mocking anywhere in this spec. All API setup via `request`; all assertions via `page`.
8. Pattern: setup via API helpers → interact via `page`. Anchor to existing `ui/tests/e2e/ubi-onramp-rung-3.spec.ts` and `ui/tests/e2e/dashboard-reseed.spec.ts` for the real-backend reseed + cluster-discovery pattern.
9. **SKIP_HEAVY_CI skip gate (FR-12)**: at the top of the spec, before `beforeAll`, check `process.env.SKIP_HEAVY_CI` and call `test.skip(true, "SKIP_HEAVY_CI=true — see state.md")` if set, matching the skip pattern other heavy specs use (verify the exact log/skip incantation by reading [`ui/tests/e2e/dashboard-reseed.spec.ts`](../../../../ui/tests/e2e/dashboard-reseed.spec.ts) at file load). DoD asserts the spec is skipped (not just unrun) when the env var is set.

**Modified files** (existing E2E specs whose assertions shift because the demo dataset now has 8 studies instead of 5)

| File | Change |
|---|---|
| `ui/tests/e2e/dashboard-reseed.spec.ts` | Update study-count assertion from 5 to 8 (the post-reseed dashboard now shows 5 LLM + 3 UBI studies). |
| `ui/tests/e2e/studies-data-table.spec.ts` | Update table row-count expectation from 5 to 8. |
| `ui/tests/e2e/ubi-onramp-rung-0.spec.ts` | Pin the rung_0 nudge assertion to `news-search-staging` specifically (acme/corp/jobs now report rung_3/1/2). |
| `ui/tests/e2e/ubi-onramp-rung-3.spec.ts` | Pin to `acme-products-prod` specifically. |
| `backend/tests/integration/test_demo_seeding.py` | Update study-count assertion from 5 to 8; add a minimal sanity check that UBI indices were created (full AC coverage lives in `_full.py`). |

**DoD**
- [ ] `cd ui && pnpm exec playwright test demo-ubi.spec.ts` green against a reseeded local stack.
- [ ] Spec contains zero `page.route(` invocations (grep verification in the DoD task).
- [ ] All 5 test cases pass; test 5 (negative case) explicitly asserts the chip is absent.
- [ ] Spec is **skipped** (not failed, not unrun) when `SKIP_HEAVY_CI=true` — verified by running `SKIP_HEAVY_CI=true pnpm exec playwright test demo-ubi.spec.ts` and observing the skip status.
- [ ] All 5 existing E2E specs in the table above updated; `pnpm exec playwright test` (full suite) still green.
- [ ] `backend/tests/integration/test_demo_seeding.py` updated and green (`pytest backend/tests/integration/test_demo_seeding.py -v`).

### Story 4.4 — Documentation updates

**Outcome:** The four doc surfaces enumerated in spec §15 are updated to reflect the synthetic-UBI demo path.

**Modified files**

| File | Change |
|---|---|
| `docs/01_architecture/mvp2-overview.md` §4 ("UBI on-ramp") | Add a paragraph noting that the demo dataset includes synthetic UBI on three of four clusters so the on-ramp ladder is browser-visible without operator setup. Cite this spec. |
| `docs/03_runbooks/ubi-judgment-generation.md` | Add a "Diagnosing synthetic-data issues" section — how to confirm the indices exist, how to read the rung classifier output for a demo cluster, how to manually rerun the synthetic generator outside the reseed. |
| `docs/05_quality/testing.md` | Add `ui/tests/e2e/demo-ubi.spec.ts` to the real-backend Playwright suite inventory. Add the fast-lane + heavy-lane integration tests to the integration-test inventory. |
| `docs/08_guides/tutorial-first-study.md` Step 11 | Add 1-2 paragraphs explaining the demo's new UBI surfaces. Phase 2 will add a "Compare two studies" subsection; reference `phase2_idea.md` as future work. |
| `state.md` | Update "Last 5 merges" (newest first), "In flight" (empty after this feature ships), MVP2 backlog counts. Move the full per-merge narrative to `state_history.md`. |
| `state_history.md` | Append the full feature-merge narrative entry. |

**Tasks**
1. `mvp2-overview.md` paragraph addition.
2. `ubi-judgment-generation.md` runbook section.
3. `testing.md` inventory updates.
4. `tutorial-first-study.md` Step 11 prose.
5. `state.md` + `state_history.md` per the post-merge convention.

**DoD**
- [ ] All four docs render correctly (link resolution check via `grep` + manual click-through).
- [ ] `state.md` stays under 60 KB (pre-commit hook enforces).

---

## Epic 4 gate (final hard stop)

Before merge:

- [ ] All ACs (AC-1..AC-10) pass in CI heavy lane.
- [ ] Real-backend E2E spec green.
- [ ] All test layers green (`make test-unit && make test-integration && make test-contract && cd ui && pnpm test && pnpm lint && pnpm typecheck && pnpm build`).
- [ ] Docs updated.
- [ ] CLI parity test green.
- [ ] No `page.route()` in `demo-ubi.spec.ts`.

---

## 3) Testing workstream

### 3.1 Unit tests

- Location: `backend/tests/unit/<area>/` (subdivided by area)
- Scope: generator math, allowlist guard, SCENARIOS catalog assertions, mapping round-trip, glossary entry, demo-data helper
- Tasks:
  - [ ] `backend/tests/unit/domain/test_synthetic_ubi.py` — Story 1.2 (≈9 tests)
  - [ ] `backend/tests/unit/services/test_demo_ubi_seed.py` — Stories 1.1 + 1.3 (combined: round-trip + ≈11 helper tests including NDJSON trailing-newline + application normalization)
  - [ ] `backend/tests/unit/scripts/test_scenarios_ubi_config.py` — Story 2.1 (4 tests)
  - [ ] `ui/src/__tests__/lib/demo-data.test.ts` — Story 3.1 (3 tests, extending existing if present)
  - [ ] `ui/src/__tests__/components/common/demo-badge.test.tsx` — Story 3.2 (3 accessibility assertions, extends existing test file at this path)
  - [ ] `ui/src/__tests__/components/judgments/judgment-list-header.test.tsx` — Story 3.2 (3-branch chip gating)
  - [ ] `ui/src/__tests__/components/clusters/cluster-detail-summary.test.tsx` — Story 3.2 (3-branch chip gating)
  - [ ] `ui/src/__tests__/components/studies/study-header.test.tsx` — Story 3.2 (3-branch chip gating; file matches verified component name)
  - [ ] `ui/src/__tests__/components/query-sets/generate-judgments-dialog.test.tsx` — Story 3.2 (3-branch chip on method picker)
  - [ ] `ui/src/__tests__/components/dashboard/demo-data-banner.test.tsx` — Story 3.2 (single-branch prose assertion)
- DoD: All critical math + gating + allowlist branches covered and deterministic.

### 3.2 Integration tests

- Location: `backend/tests/integration/` (flat, no `services/` subdir per the verified codebase layout)
- Scope: full reseed orchestrator, UBI indices on real ES, rung classifier output, CLI parity
- Tasks:
  - [ ] `backend/tests/integration/test_demo_seeding_ubi_fast.py` — Story 4.1 (always-on, <60s)
  - [ ] `backend/tests/integration/test_demo_seeding_ubi_full.py` — Story 4.2 (heavy lane)
  - [ ] `backend/tests/integration/test_seed_meaningful_demos_ubi.py` — Story 4.2 (CLI parity, heavy lane)
- DoD: Happy path + AC-9 failure path covered.

### 3.3 Contract tests

- Location: `backend/tests/contract/`
- Scope: **none added in Phase 1**. Phase 1 adds no new endpoints; all wire shapes are inherited from `feat_ubi_judgments` + `feat_llm_judgments` + `feat_study_lifecycle` which already have contract coverage.
- DoD: Existing contract coverage suffices.

### 3.4 E2E tests

- Location: `ui/tests/e2e/<name>.spec.ts` (flat, verified)
- Scope: 5 user-visible AC checks against a reseeded live stack
- Rule: **real browser interactions only**. No `page.route()` mocking. `request` fixture for setup (POSTing to `/api/v1/_test/demo/reseed`, GETting cluster IDs); `page` fixture for all assertions.
- Tasks:
  - [ ] `ui/tests/e2e/demo-ubi.spec.ts` — Story 4.3
- DoD: 5 test cases pass; spec contains zero `page.route(` calls.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `ui/tests/e2e/dashboard-reseed.spec.ts` | study count assertions on the dashboard | TBD (grep at story execution) | Update to expect 8 studies (was 5) |
| `ui/tests/e2e/studies-data-table.spec.ts` | study row count expectations | TBD | Update study count to 8 |
| `ui/tests/e2e/ubi-onramp-rung-0.spec.ts` | rung_0 nudge visibility | 1 expected | Pin assertion to `news-search-staging` (the only remaining rung_0 demo cluster) |
| `ui/tests/e2e/ubi-onramp-rung-3.spec.ts` | rung_3 badge presence | 1 expected | Pin to `acme-products-prod` |
| `backend/tests/integration/test_demo_seeding.py` | existing reseed integration | 1 expected | Update study-count assertion from 5 to 8; add minimal sanity check that UBI indices were created (not full AC coverage — that lives in `_full.py`) |

The plan-gen pass cannot precisely grep these counts without running; Story 4.3 includes a sub-task to grep the actual occurrences and update accordingly.

### 3.5 Migration verification

**N/A** — no new migrations. Alembic head stays at `0021_judgment_lists_generation_params`.

### 3.6 CI gates

- [ ] `make test-unit` (existing + 4 new unit-test files)
- [ ] `make test-integration` (existing + 3 new integration files; fast-lane always; heavy lane gated by `SKIP_HEAVY_CI`)
- [ ] `make test-contract` (no new files; no regressions)
- [ ] `cd ui && pnpm test && pnpm lint && pnpm typecheck && pnpm build`
- [ ] `cd ui && pnpm exec playwright test demo-ubi.spec.ts` (manual + nightly)

---

## 4) Documentation update workstream

### 4.0 Core context files

**`state.md`** — update:
- [x] Active branch: `feature/feat_demo_ubi_study_comparison` → none active after merge
- [x] New feature shipped (this one): move from in-flight to "Last 5 merges (newest first)" one-liner
- [x] MVP2 backlog count: from 17 to 16 (this feature moves to implemented_features)
- [ ] Alembic head: unchanged (`0021_judgment_lists_generation_params`)

**`architecture.md`** — likely no change. The `backend/app/domain/demo/` subdirectory is new, but it's small; only update if the existing `backend/app/domain/` enumeration needs the new entry.

**`CLAUDE.md`** — no change. No new conventions, env vars, or absolute rules.

### 4.1-4.5 Doc updates

Covered by Story 4.4. See that story for the file-by-file diff list.

### 4.6 Phase 2 tracking artifact

[`phase2_idea.md`](./phase2_idea.md) was created at spec-finalization (Step 10 of `/spec-gen`). No additional action needed in the impl plan unless the plan changes the Phase 2 scope.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- The shared mapping JSON (Story 1.1) consolidates a duplicate-source-of-truth between TS and Python. This is a refactor disguised as a feature.

### 5.2 Planned refactor tasks

- [x] Story 1.1 refactors `seed_ubi.ts` to load the canonical mapping from `samples/ubi_index_mappings.json`. **Behavioral parity** is the unit test asserting round-trip equality.

### 5.3 Refactor guardrails

- [x] `seed_ubi.ts` behavioral parity — unit test pins the new file's content equals the original inline shape.
- [x] No expansion of product scope.
- [x] Discovered debt during execution captured as `bug_`/`chore_` idea files per CLAUDE.md tangential-discoveries rule.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_ubi_judgments` shipped (PR #317) | All stories | Shipped 2026-05-29 | Feature is meaningless without the UBI judgment infrastructure |
| `bug_demo_reseed_fake_metric_regression` shipped | Story 2.5 (CLI parity) | Shipped (pre-MVP2) | Without the parity policy, CLI/home-button drift is unbounded |
| Docker Compose stack with ES container | Stories 1.3, 4.1, 4.2 | Existing | Fast-lane test fails if test ES container missing |
| `feat_chat_agent` glossary infrastructure | Story 3.1 (glossary key) | Shipped | Without `feat_contextual_help` discipline, glossary key would be a new pattern |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Reseed wall-clock exceeds 1140s ceiling | M | M | §13 mitigation gate: lower UBI demo-study `max_trials=12 → 6` first; then drop corp UBI sweep; then bump `DEMO_RESEED_JOB_TIMEOUT_S` to 1800 with operator opt-in |
| Hybrid converter LLM call rate-limits in test environment | L | M | Use the test-env `OPENAI_API_KEY` (existing CI fixture); hybrid only fills sparse tail (~5-10 pairs per scenario) → low call count |
| Synthetic generator's rating-correlation produces a degenerate case (e.g., all queries get the same clicked doc) on edge-case ratings | L | L | Unit test covers the click-correlation property; if it ever degenerates, the value-delta card just shows fewer non-zero deltas — still demonstrably valuable |
| E2E spec flakes on slow CI runners (reseed takes >25 min) | M | L | `test.setTimeout(25 * 60 * 1000)`; if CI is consistently above 25 min, mark the spec as `@nightly`-only |
| GPT-5.5 / Gemini find a contract drift between this plan and the spec | M | L | The 3-cycle spec convergence already addressed this; if plan-cycle review surfaces more, accept and patch before approval |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| `seed_synthetic_ubi` called with non-allowlisted (slug, target) pair | Future code change introducing a new call site | `ValueError` raised; reseed orchestrator catches it as `DemoSeedingError("ubi_seed/...")`; route returns 503 SEED_FAILED | Operator sees error; reseed needs code fix |
| ES container 503 / network blip during bulk write | Transient network failure | First retry within the existing httpx.AsyncClient timeout; if it persists, `DemoSeedingError` raised | `docker compose restart api && click "Force refresh" again` |
| UBI judgment worker fails (LLM timeout in hybrid mode) | OpenAI 503 | `judgment_list.status = 'failed'`; reseed poll detects it; raises `DemoSeedingError("ubi_judgments/{slug}: failed ...")` | Retry the reseed |
| UBI study fails | Optuna study fails | Same as today's LLM-study-fail path — `_seed_real_study_for_scenario` raises `DemoSeedingError` | Retry |
| Operator opens chip-bearing UI before reseed completes | Race condition between operator action and worker | Existing reseed-status banner displays in-progress state; UBI lists may be `generating` and the chip surface decisions degrade gracefully (chip absent until list present) | Wait for banner to show "complete" |
| `samples/ubi_index_mappings.json` drift between Python and TS load paths | Operator edits one but not the other | Story 1.1 unit test fails immediately on the changed side; no production exposure | Reconcile before merge |
| Synthetic events fall outside the dispatcher's window | `seed_anchor_iso` not passed correctly to generator | UBI judgment generation returns 422 `UBI_INSUFFICIENT_DATA`; `DemoSeedingError("ubi_judgments/{slug}: 422 UBI_INSUFFICIENT_DATA ...")` | Code fix — never expected outside dev |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1** (Stories 1.1, 1.2, 1.3) — pure backend; high test density; lowest risk.
2. **Epic 2** (Stories 2.1, 2.2, 2.3, 2.4, 2.5) — depends on Epic 1; touches the production reseed flow.
3. **Epic 3** (Stories 3.1, 3.2) — frontend; depends on Epic 2 producing the data.
4. **Epic 4** (Stories 4.1, 4.2, 4.3, 4.4) — finalizes coverage + docs. Story 4.1 (fast-lane integration test) may land alongside Story 1.3 as part of the verification of FR-3; the heavy lane lands after Epic 2; E2E lands after Epic 3.

### Parallelization opportunities

- Stories 1.1, 1.2, 1.3 can run in parallel (no shared files; each owns its own new module).
- Story 4.1 can begin as soon as Story 1.3 lands.
- Within Epic 3, Story 3.1 must complete before Story 3.2 (the chip's gating uses Story 3.1's new helper).
- Documentation (Story 4.4) can be drafted in parallel with Epic 3.

## 8) Rollout and cutover plan

- **Rollout stages:** none — single-tenant dev-only change. Single PR; merge → next `make seed-demo` or home-button click produces the new state.
- **Feature flag strategy:** none. The synthetic generator is gated by the SCENARIOS allowlist + (frontend) `isDemoSyntheticUbiClusterName`; both are compile-time gates.
- **Migration / cutover steps:** none (no DB migrations).
- **Operator action after merge:** click "Force refresh demo data" on the dashboard, OR run `make seed-demo`, to populate the new demo state. The existing reseed-status banner shows progress.

## 9) Execution tracker (copy/paste section)

### Current sprint
- [ ] Story 1.1 — Canonical UBI mapping JSON
- [ ] Story 1.2 — Pure-domain generator
- [ ] Story 1.3 — Engine-write helper + allowlist
- [ ] Story 2.1 — SCENARIOS catalog UBI keys
- [ ] Story 2.2 — Reseed UBI seeding + cleanup
- [ ] Story 2.3 — UBI judgment dispatch + dual studies
- [ ] Story 2.4 — Status sub-step labels + log events
- [ ] Story 2.5 — CLI parity
- [ ] Story 3.1 — `isDemoSyntheticUbiClusterName` + glossary + CI parity
- [ ] Story 3.2 — `<DemoBadge variant="synthetic-ubi">` on 5 surfaces
- [ ] Story 4.1 — Fast-lane integration test
- [ ] Story 4.2 — Heavy-lane integration + CLI parity + AC-8
- [ ] Story 4.3 — E2E spec
- [ ] Story 4.4 — Docs

### Blocked items
- _None at plan-creation time._

### Done this sprint
- _Updated as stories complete._

## 10) Story-by-Story Verification Gate

Before marking any story complete, the executing agent must confirm:

- [ ] Files created / modified match the story's New files + Modified files tables exactly.
- [ ] Key interfaces implemented with the signatures from the story.
- [ ] All required tests added (unit + integration + E2E as applicable).
- [ ] Commands executed and passed:
    - [ ] `make test-unit`
    - [ ] `make test-integration` (or the targeted file for stories scoped to a single test)
    - [ ] `cd ui && pnpm test && pnpm lint && pnpm typecheck` (frontend stories)
- [ ] No new contract tests required (Phase 1 adds no endpoints — verified by §3.3 above).
- [ ] No migration round-trip needed (Phase 1 adds no migrations).
- [ ] Related docs updated in the same PR when the story changes user-observable behavior or contracts.

## 11) Plan consistency review

### 11.1 Spec ↔ plan endpoint count

Spec §8.1 lists 6 endpoints invoked by the reseed; all 6 are **existing** endpoints (none added in Phase 1). Plan endpoint tables: 0 (no new endpoints). **Match.**

### 11.2 Spec ↔ plan error code coverage

Spec §8.5 lists 3 error codes (`VALIDATION_ERROR`, `UBI_INSUFFICIENT_DATA`, `DemoSeedingError`/`SEED_FAILED`). All 3 are existing codes from owning features. Plan does not require new contract tests (§3.3) and that's correct — covered by existing tests.

### 11.3 Spec ↔ plan FR coverage

All 12 FRs (FR-1 through FR-12) mapped to at least one story in §1 traceability. **No gaps.**

### 11.4 Story internal consistency

- New files: every file in §1 New files is owned by exactly one story.
- Modified files: `backend/app/services/demo_seeding.py` is modified by Stories 2.2 + 2.3 + 2.4 — same author, sequential ordering, no conflict.
- `scripts/seed_meaningful_demos.py` modified by Stories 2.1 + 2.2 + 2.5 — same author, sequential.

### 11.5 Test file count and assignment

13 unit/integration test files across the stories; each assigned to exactly one story's DoD. CLI parity test owned by Story 4.2.

### 11.6 Gate arithmetic

- Epic 1 gate cites 3 stories (1.1, 1.2, 1.3) ✓
- Epic 2 gate cites 5 stories (2.1-2.5) ✓
- Epic 3 gate cites 2 stories (3.1, 3.2) ✓
- Epic 4 gate cites 4 stories (4.1-4.4) ✓

### 11.7 Open questions resolved

Spec §19 has zero open questions at plan-creation time. **No blockers.**

### 11.8 Frontend UI Guidance completeness

Story 3.2 is the only substantial frontend story. The "Modified files" table lists 5 components + 5 test files + the demo-badge component. The spec's §11 Information Architecture and §11 Tooltips tables are referenced by Story 3.2 directly. **Legacy Behavior Parity table:** Story 3.2 is purely additive (no >100 LOC deletion); the explicit "No legacy behavior parity table" statement appears in Story 3.2 per the template rule.

### 11.9 Codebase verification (Pass 2 highlights)

- Migration directory `backend/alembic/versions/` — N/A, no migrations.
- Alembic head `0021_judgment_lists_generation_params` — verified via `ls migrations/versions/`.
- Test layout: `backend/tests/integration/` is flat (no `services/` subdir) — verified.
- `ui/tests/e2e/<name>.spec.ts` is flat (no `specs/` subdir) — verified; spec patched accordingly.
- `backend/app/main.py:207-214` shows `include_router(... prefix="/api/v1")` pattern — N/A, no new routers.

### 11.10 Enumerated value contract audit

| Field | Backend source | Spec §8.4 cite | Plan story | Source-of-truth comment in plan |
|---|---|---|---|---|
| `ubi_target_rung` (SCENARIOS) | New literal — `Literal["rung_1", "rung_2", "rung_3"] \| None` | spec §8.4 | Story 2.1 | Comment added to SCENARIOS entries citing `backend/app/services/ubi_readiness.py:53` UbiReadinessRung |
| `ubi_converter` (SCENARIOS) | `UbiConverterKind` at `backend/app/api/v1/schemas.py:846` | spec §8.4 | Story 2.1 | Source-of-truth comment cites `schemas.py:846` |
| `mapping_strategy="reject"` (reseed → UBI dispatch) | `UbiMappingStrategyWire` at `schemas.py:864` | spec §8.4 | Story 2.3 | Hard-coded `"reject"` is the default; no dropdown drift risk |
| `DEMO_SYNTHETIC_UBI_CLUSTER_SLUGS` (frontend) | `DEMO_UBI_SCENARIO_ALLOWLIST` at `demo_ubi_seed.py` | spec §8.4 | Story 3.1 | Top-of-file comment in `demo-data.ts` + CI parity guard |

All four enumerated-value flows have a single source of truth + a comment marker + a test/CI guard.

### 11.11 Audit-event coverage audit

Per spec §6: Phase 1 emits **no** new audit events. The plan introduces no state-mutating endpoint or service function — only seed-side data-generation code and orchestration of existing endpoints. **No gaps.**

---

## 12) Definition of plan done

- [x] Every FR mapped to stories/tasks/tests/docs updates.
- [x] Every story includes New files, Modified files, Tasks, and DoD; Key interfaces included where new modules are introduced.
- [x] Test layers (unit/integration/E2E) explicitly scoped; contract layer documented as N/A with rationale.
- [x] Documentation updates across docs/01-05 planned and owned (Story 4.4).
- [x] Lean refactor scope minimal (mapping JSON consolidation) with parity proof.
- [x] Phase/epic gates measurable.
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review completed with no unresolved findings.
- [x] `phase2_idea.md` exists for the deferred dual-study comparison view.
