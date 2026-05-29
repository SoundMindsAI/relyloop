# Implementation Plan — UBI Judgments (engine-neutral User Behavior Insights)

**Date:** 2026-05-29
**Status:** Approved (cross-model converged at 3-cycle cap; all 3 GPT-5.5 findings accepted — see footer)
**Primary spec:** [feature_spec.md](feature_spec.md) (Approved 2026-05-29; cross-model converged at cycle-3 cap with all 10 findings accepted — see spec §19 D-10)
**Policy source(s):**
- [docs/01_architecture/api-conventions.md](../../../../01_architecture/api-conventions.md) — `/api/v1/<resource>` prefix, error envelope `{"detail":{"error_code","message","retryable"}}`, cursor pagination, `X-Total-Count`
- [docs/01_architecture/adapters.md](../../../../01_architecture/adapters.md) — `SearchAdapter` Protocol; UBI uses `search_batch` + `get_schema` only
- [docs/01_architecture/llm-orchestration.md](../../../../01_architecture/llm-orchestration.md) — capability cache, daily-budget gate, `rate_query_batch` is the only LLM entry
- [docs/01_architecture/data-model.md](../../../../01_architecture/data-model.md) — `judgments` + `judgment_lists` shapes; CHECK constraints
- [CLAUDE.md](../../../../../CLAUDE.md) — Absolute Rules #2 (mounted secrets), #3/#8/#10 (LLM via shared client + Settings.openai_model), #4 (engine code in adapters), #5 (migration downgrade)

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs from the spec.
- The migration is the single hard gate (Story 1.1) — it lands first because every later story reads/writes `judgment_lists.generation_params`.
- The `SignalsConverter` Protocol is **async** (cycle-3 fix D-10e); all three concrete converters await uniformly even when the pure ones don't actually await anything. One Protocol shape for the worker to consume.
- LLM calls in hybrid mode go through `rate_query_batch` + `peek_daily_total` + `record_cost` from [`backend/app/llm/budget_gate.py`](../../../../../backend/app/llm/budget_gate.py). No new LLM client. (Absolute Rules #3/#8/#10.)
- Engine I/O is the existing `SearchAdapter.search_batch` + `get_schema` surface — no new adapter method (Absolute Rule #4).
- `UBI_INSUFFICIENT_DATA` is **sync 422 from preflight U-D2**; the worker terminal `failed` path is the race-condition fallback only (cycle-3 fix D-10d).
- Per-query ambiguous mapping under `mapping_strategy='reject'` is a **skip + counter** (calibration JSONB), not a 422 (cycle-3 fix D-10f). The endpoint catalog removed `UBI_QUERY_MAPPING_AMBIGUOUS`.
- Wire enums live in `backend/app/api/v1/schemas.py` and mirror in `ui/src/lib/enums.ts` with the `// Values must match backend/...` comment. Form `<Select>` consumes `*_VALUES.map(...)` per [`ui/src/__tests__/components/common/form-select-discipline.test.tsx`](../../../../../ui/src/__tests__/components/common/form-select-discipline.test.tsx).
- Single-phase delivery default. Phase-2 split contingency stays in-spec; this plan ships everything.

---

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (`UbiReader` two-index scan) | Epic 2 / Story 2.1 | `backend/app/services/ubi_reader.py` + supporting `domain/ubi/features.py`; engine-agnostic via `SearchAdapter.search_batch` + `get_schema`. Empty-features case is the race-condition fallback — preflight U-D2 covers the sync path. |
| FR-2 (`SignalsConverter` Protocol + 3 impls) | Epic 1 / Story 1.2 | `backend/app/domain/ubi/converter.py` with async Protocol + `CtrThresholdConverter` + `DwellTimeThresholdConverter` + `HybridUbiLlmConverter`. Hybrid converter takes an injected `llm_rate` callback wired to `rate_query_batch` by the worker (no direct `openai.AsyncClient` construction in domain code). |
| FR-3 (`POST /api/v1/judgments/generate-from-ubi`) | Epic 3 / Story 3.2 | Router addition in `backend/app/api/v1/judgments.py`; request shape `CreateJudgmentListFromUbiRequest`; conditional `current_template_id`/`rubric` validator. |
| FR-4 (`start_ubi_judgment_generation` dispatcher + shared-helper refactor) | Epic 2 / Story 2.2 | New function in `backend/app/services/agent_judgments_dispatch.py`; refactors common preflight + INSERT + enqueue logic out of `start_judgment_generation`. |
| FR-5 (`generate_judgments_from_ubi` Arq worker) | Epic 3 / Story 3.3 | New job in `backend/workers/judgments.py`; reads `generation_params` from the row; mirrors LLM-worker lifecycle (resume-skip + terminal flip). Hybrid LLM-fill via `rate_query_batch`. |
| FR-6 (agent tool + system-prompt update) | Epic 3 / Story 3.4 | `backend/app/agent/tools/judgments/generate_judgments_from_ubi.py` + registry wiring; orchestrator system prompt update at [`backend/app/agent/orchestrator.py`](../../../../../backend/app/agent/orchestrator.py) `_load_system_prompt`. |
| FR-7 (readiness probe + endpoint) | Epic 2 / Story 2.2 (service) + Epic 3 / Story 3.1 (endpoint) | `backend/app/services/ubi_readiness.py` + `GET /api/v1/clusters/{cluster_id}/ubi-readiness?query_set_id=&target=` in `backend/app/api/v1/clusters.py`; Redis-cached 60s per scope tuple. |
| FR-8 (frontend picker + on-ramp UX) | Epic 4 / Stories 4.1, 4.2, 4.3 | Story 4.1: enums + `useUbiReadiness` hook + rung badge. Story 4.2: dialog method picker + UBI window controls + engine-aware nudge + sparse-data card. Story 4.3: value-delta card on judgment-list detail page + ambiguous-skip recovery card. |
| FR-9 (wire-value contracts) | Epic 2 / Story 2.3 (backend Literals) + Epic 4 / Story 4.1 (UI mirror) | `UbiConverterKind`, `JudgmentGenerationMethodWire`, `UbiReadinessRungWire`, `UbiMappingStrategyWire` in `schemas.py`; widen `JudgmentSourceFilterWire`. UI mirror with `// Values must match` comments. |
| FR-10 (`_SourceBreakdown` evolution) | Epic 2 / Story 2.3 | Add `click: int` field; evolve repo `source_breakdown_for_list`; update `_detail()` populator; update contract tests asserting the shape. |
| FR-11 (position-bias prior file) | Epic 1 / Story 1.2 | `backend/app/domain/ubi/position_bias_prior.py` + new `UBI_POSITION_BIAS_PRIOR_FILE` setting on `Settings`; uninformed default; WARN-on-malformed. |

**Spec endpoint count:** 2 (POST `/judgments/generate-from-ubi` + GET `/clusters/{id}/ubi-readiness`). Plan endpoint count: 2 (Story 3.1 + Story 3.2). ✓

**Spec error code count (UBI-specific):** 3 (`UBI_NOT_ENABLED`, `UBI_INSUFFICIENT_DATA`, `UBI_WINDOW_TOO_LARGE`). All reused codes: `VALIDATION_ERROR`, `CLUSTER_NOT_FOUND`, `QUERY_SET_NOT_FOUND`, `TEMPLATE_NOT_FOUND` (hybrid only), `JUDGMENT_LIST_NAME_TAKEN`, `CLUSTER_UNREACHABLE`, `OPENAI_NOT_CONFIGURED`, `LLM_PROVIDER_INCAPABLE`, `UNKNOWN_MODEL_PRICING`, `OPENAI_BUDGET_EXCEEDED`. Plan contract test coverage: all 13 codes asserted in Story 3.2 contract test (UBI envelopes) + Story 3.1 contract test (readiness envelopes). ✓

**Deferred phase tracking:** Spec §3 declares single-phase delivery default with Phase-2 split contingency to be decided at this plan time. **Decision: ship single-phase.** Scope estimate (see §6 Dependencies / §7 Sequencing) is ~1350 LOC bundled which is at the upper edge of reviewability — split was considered but the reviewer benefits from seeing the substrate + on-ramp in one pass per the spec's "impossible to ship half" rationale (spec §"How this feature stays a single coherent unit"). If pre-push gate or Gemini review surfaces reviewability concerns during `/impl-execute`, the split escape hatch remains: spawn `phase2_idea.md` for Capabilities A/B/C/D and revert Stories 4.2 (nudge + sparse card halves), 4.3 (value-delta), and 3.1 (readiness endpoint) into the phase-2 PR. **No `phase2_idea.md` created here** — this is contingency-only.

---

## 2) Delivery structure

Epic → Story → Tasks → DoD.

### Story-level detail requirements

Each story includes: **Outcome · New files · Modified files · Endpoints (when API-facing) · Key interfaces · Pydantic schemas (when API-facing) · UI element inventory (when frontend) · Tasks · DoD**.

### Conventions (project-specific — apply to every story)

- All repo functions take `db: AsyncSession` first; use `db.flush()` (caller commits) per [CLAUDE.md §"Repository Layer"](../../../../../CLAUDE.md).
- Services / worker jobs are async; create `judgment_lists` row + commit upfront so the worker is fully self-contained on `judgment_list_id` (matches `feat_llm_judgments` pattern).
- Domain / `backend/app/domain/ubi/` is pure — no DB access, no I/O. The `HybridUbiLlmConverter` takes an injected `llm_rate` callback; it does NOT construct an `openai.AsyncClient`.
- Models use `Mapped[]` typed columns, `String(36)` UUIDs.
- Routers return typed Pydantic response models; errors use `HTTPException(detail={"error_code","message","retryable"})` via the existing `_err()` helper at [`backend/app/api/v1/judgments.py:86-90`](../../../../../backend/app/api/v1/judgments.py#L86-L90).
- LLM access via `rate_query_batch` from `backend/app/llm/openai_judge.py` (CLAUDE.md Rules #3/#8/#10 — always read `OPENAI_BASE_URL` + `OPENAI_MODEL` from `Settings`).
- All `backend/app/db/models/__init__.py`, `backend/app/db/repo/__init__.py`, `backend/app/agent/tools/__init__.py` `__all__` / `TOOLS` / `TOOL_REGISTRY` / `TOOL_ARG_MODELS` entries updated when new models / repo functions / tools ship.
- Migration numbering: head is `0020_studies_baseline_trial`; this feature ships `0021_judgment_lists_generation_params` (next sequential).
- Engine-specific code lives ONLY in `backend/app/adapters/<engine>.py` — UBI never adds engine-specific code.
- Wire enums live in `backend/app/api/v1/schemas.py` (`Literal[...]`) and `ui/src/lib/enums.ts` (`as const` array with `// Values must match backend/...` comment); form `<Select>` consumes `*_VALUES.map(...)`.

### AI Agent Execution Protocol

0. Load context: read `CLAUDE.md`, `architecture.md`, `state.md`, this plan, and the spec top-to-bottom before the first story.
1. Read scope of the current story (Outcome, New/Modified files, Endpoints, Key interfaces, DoD).
2. Backend-first per story: migration → model → repo → domain → service → worker (when applicable) → router → schemas → agent-tool.
3. Run unit + integration + contract tests after each story; if migration touched, also `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`.
4. Frontend (Epic 4): enums first → hook → primitive (`<UbiRungBadge>`) → integration into existing dialog/detail pages.
5. E2E (Epic 5): real-backend Playwright against the existing OpenSearch service container + the new `tests/e2e/helpers/seed_ubi.ts` helper.
6. Update docs/checklists in the same PR when behavior/contract changed.
7. Migration round-trip verified before merging Story 1.1.
8. Attach evidence (commands run, pass/fail) in the PR description.
9. After the final story, update `state.md` + `architecture.md` per §4.0.

---

## Epic 1 — Foundations (migration + pure-domain UBI library)

### Story 1.1 — Migration `0021_judgment_lists_generation_params` (FR-4 + FR-5 backing)

**Outcome:** `judgment_lists.generation_params` JSONB column exists in Postgres at Alembic head `0021_judgment_lists_generation_params`; round-trips cleanly.

**New files**

| File | Purpose |
|---|---|
| `migrations/versions/0021_judgment_lists_generation_params.py` | Add nullable JSONB column `generation_params` to `judgment_lists`. `downgrade()` drops the column. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/models/judgment_list.py` | Add `generation_params: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)` with docstring noting UBI-only population (LLM lists stay NULL). |

**Tasks**

1. Create `migrations/versions/0021_judgment_lists_generation_params.py` with `revision="0021"` and `down_revision="0020"` matching the `0020_studies_baseline_trial.py` style.
2. `upgrade()`: `op.add_column("judgment_lists", sa.Column("generation_params", postgresql.JSONB, nullable=True))`. No CHECK constraint (free-form JSONB).
3. `downgrade()`: `op.drop_column("judgment_lists", "generation_params")`.
4. Add `generation_params` to `JudgmentList` ORM model in `backend/app/db/models/judgment_list.py` after the `calibration` field (line 58). Update the module docstring's "MVP1 shape" reference to note the column is `feat_ubi_judgments` MVP2 additive.
5. Run `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` and capture output for the PR description.

**Definition of Done (DoD)**

- [ ] `migrations/versions/0021_judgment_lists_generation_params.py` exists; `alembic upgrade head` succeeds locally and in CI.
- [ ] Round-trip works: `alembic downgrade -1` (back to `0020`) and `alembic upgrade head` both succeed.
- [ ] Pre-existing `judgment_lists` rows (LLM lists) survive both directions cleanly (column is nullable; never read on LLM path).
- [ ] Integration test at `backend/tests/integration/db/test_migration_0021_generation_params.py` introspects `information_schema.columns` and asserts column type `jsonb` + nullable.
- [ ] `state.md` bump to `0021_judgment_lists_generation_params` happens in the finalization step (NOT this story).

---

### Story 1.2 — `domain/ubi/` package (FR-2 + FR-11)

**Outcome:** Pure-domain UBI library with feature vectors, async `SignalsConverter` Protocol + 3 concrete converters, and the position-bias prior loader. No I/O, no DB, no LLM client construction.

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/ubi/__init__.py` | Exports `FeatureVec`, `SignalsConverter`, `CtrThresholdConverter`, `DwellTimeThresholdConverter`, `HybridUbiLlmConverter`, `ConverterConfig`, `load_position_bias_prior`. |
| `backend/app/domain/ubi/features.py` | `FeatureVec` Pydantic model + `aggregate_features(events_by_pair)` pure aggregation (sums clicks, impressions, computes corrected CTR, dwell mean). |
| `backend/app/domain/ubi/converter.py` | `SignalsConverter` async Protocol + 3 concrete impls + `ConverterConfig` Pydantic model + per-converter config sub-models. |
| `backend/app/domain/ubi/position_bias_prior.py` | `load_position_bias_prior(path: Path \| None) -> dict[int, float]`; returns `{}` (uninformed) on missing/empty; WARN-logs on malformed JSON. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/core/settings.py` | Add optional `ubi_position_bias_prior_file: Path \| None` field + `@cached_property ubi_position_bias_prior` accessor (delegates to `load_position_bias_prior`). |

**Key interfaces**

```python
# domain/ubi/features.py
class FeatureVec(BaseModel):
    click_count: int
    impression_count: int
    corrected_ctr: float       # Wang-Bendersky-corrected
    dwell_mean_seconds: float | None
    conversion_rate: float | None
    refinement_rate: float | None

def aggregate_features(
    events_by_pair: dict[tuple[str, str], list["UbiEvent"]],
    position_bias_prior: dict[int, float],
) -> dict[tuple[str, str], FeatureVec]: ...

# domain/ubi/converter.py
class ConverterConfig(BaseModel):
    """Discriminated by converter kind in the serializer; opaque to the Protocol."""
    extra: dict[str, Any] = Field(default_factory=dict)

class SignalsConverter(Protocol):
    async def convert(
        self,
        features: dict[tuple[str, str], FeatureVec],
        config: ConverterConfig,
    ) -> dict[tuple[str, str], int]: ...

class CtrThresholdConverter:
    """Pure UBI — no LLM I/O. Default thresholds: {1: 0.05, 2: 0.15, 3: 0.30}."""
    async def convert(self, features, config) -> dict[tuple[str, str], int]: ...

class DwellTimeThresholdConverter:
    """Pure UBI — no LLM I/O. Default thresholds (seconds): {1: 10.0, 2: 30.0, 3: 90.0}."""
    async def convert(self, features, config) -> dict[tuple[str, str], int]: ...

LlmRateCallback = Callable[
    [list[tuple[str, str, str]]],  # [(query_id, doc_id, query_text), ...]
    Awaitable[dict[tuple[str, str], int]],
]

class HybridUbiLlmConverter:
    """UBI-head + LLM-tail. inner = CtrThresholdConverter or DwellTimeThresholdConverter.

    Pairs with impression_count >= llm_fill_threshold (default 20) → inner.convert(...).
    Pairs below threshold → llm_rate(...) callback (worker-supplied; routes through
    rate_query_batch + budget gate).
    """
    def __init__(self, inner: SignalsConverter, llm_rate: LlmRateCallback): ...
    async def convert(self, features, config) -> dict[tuple[str, str], int]: ...

# domain/ubi/position_bias_prior.py
def load_position_bias_prior(path: Path | None) -> dict[int, float]:
    """Return {rank: weight} or {} for uninformed default. WARN-log on malformed JSON."""
```

**Tasks**

1. Implement `FeatureVec` and `aggregate_features` per FR-1 feature shape; position-bias correction: `corrected_ctr = clicks / sum(impressions[r] * prior.get(r, 1.0))`.
2. Implement `CtrThresholdConverter` + `DwellTimeThresholdConverter` as async classes (their body doesn't `await` anything — trivially async to satisfy the Protocol).
3. Implement `HybridUbiLlmConverter` with the splitter: partition `features` into head (`impression_count >= llm_fill_threshold`) → call `inner.convert`; tail → build the `(query_id, doc_id, query_text)` payload and await `llm_rate(...)`. Merge dicts; `head` wins on collision (impossible by construction, but explicit).
4. Implement `load_position_bias_prior(path)`: read JSON `{positions: {1: 1.0, 2: 0.65, ...}}`; on `FileNotFoundError` / `OSError` / `json.JSONDecodeError` / unexpected shape → `logger.warning(event_type='ubi_position_bias_prior_malformed', error=...)` and return `{}` (uninformed).
5. Wire `Settings.ubi_position_bias_prior_file` + `@cached_property ubi_position_bias_prior` (calls `load_position_bias_prior` once per process via `@cached_property`).
6. Update `backend/app/domain/__init__.py` (if present) and `backend/app/core/settings.py` `Settings` fields.
7. Write unit tests in `backend/tests/unit/domain/ubi/test_features.py`, `test_converter.py`, `test_position_bias_prior.py` per §3.1.

**Definition of Done (DoD)**

- [ ] `FeatureVec.click_count == sum(events.click_count_for_pair)`; corrected CTR matches a hand-computed example with informed prior `{1: 1.0, 2: 0.5, 3: 0.25}` (verified in `test_features.py`).
- [ ] `CtrThresholdConverter` maps `corrected_ctr ∈ {0.04, 0.10, 0.20, 0.40}` → `{0, 1, 2, 3}` respectively with default thresholds.
- [ ] `DwellTimeThresholdConverter` maps `dwell_mean ∈ {5, 15, 60, 120}` → `{0, 1, 2, 3}` respectively.
- [ ] `HybridUbiLlmConverter` invokes the inner converter for above-threshold pairs and the `llm_rate` callback for below-threshold pairs; merged dict size matches input size (no dropped pairs).
- [ ] `HybridUbiLlmConverter` does NOT import `openai` or construct an `AsyncOpenAI` instance (lint guard: `ast`-based test asserts neither import nor `AsyncOpenAI(` token in `converter.py`).
- [ ] `load_position_bias_prior(None)` returns `{}`; malformed JSON returns `{}` + WARN log captured by `caplog`.
- [ ] `Settings().ubi_position_bias_prior` returns `{}` when the env var is unset.

---

## Epic 2 — Reader + dispatcher + breakdown evolution

### Story 2.1 — `UbiReader` service (FR-1)

**Outcome:** `UbiReader.read_features(...)` reads `ubi_queries` + `ubi_events` via `SearchAdapter.search_batch`, performs the `query_id` join client-side, returns `dict[tuple[str, str], FeatureVec]`. Raises `UbiNotEnabledError` when the schema probe fails.

**New files**

| File | Purpose |
|---|---|
| `backend/app/services/ubi_reader.py` | `UbiReader` class + `UbiNotEnabledError` + `_probe_enabled(adapter)` helper. Issues two scrolling `search_batch` calls; joins on `query_id` in Python. Disambiguates per-application emissions by `target`. |
| `backend/app/services/ubi_errors.py` | `UbiNotEnabledError`, `UbiInsufficientDataError` (raised by `read_features` on empty post-filter; race-condition fallback only). |

**Modified files**

| File | Change |
|---|---|
| `backend/app/services/__init__.py` | Re-export `UbiReader`, `UbiNotEnabledError`, `UbiInsufficientDataError` if `__all__` is used. |

**Key interfaces**

```python
# services/ubi_reader.py
class UbiReader:
    def __init__(self, adapter: SearchAdapter, position_bias_prior: dict[int, float]):
        ...

    async def read_features(
        self,
        *,
        target: str,
        since: datetime,
        until: datetime | None = None,
        query_filter: str | None = None,
        max_queries: int = 5000,
    ) -> dict[tuple[str, str], FeatureVec]:
        """Two-index scan + client-side join. Raises UbiNotEnabledError on rung_0."""

    async def _probe_enabled(self) -> None:
        """get_schema('ubi_queries') — raises UbiNotEnabledError on TargetNotFoundError."""

# services/ubi_errors.py
class UbiNotEnabledError(RuntimeError): ...
class UbiInsufficientDataError(RuntimeError): ...
```

**Tasks**

1. Implement `UbiReader._probe_enabled` calling `adapter.get_schema('ubi_queries')`; catch `TargetNotFoundError` → raise `UbiNotEnabledError(f"ubi_queries index not found on engine {adapter.engine_type}")`.
2. Implement `read_features`:
   - Build the `ubi_queries` scroll query: filter `timestamp >= since AND timestamp < (until or now) AND application = target`, paginate via `search_batch` with `top_k=max_queries`. Optional `query_filter` adds an `AND user_query ~ <substring>` clause when present.
   - Build the `ubi_events` scroll query keyed by the `query_id` set from step 1's result. Same `search_batch` mechanism.
   - Join in Python: bucket events by `(query_id, doc_id)`; pass to `aggregate_features(...)` from Story 1.2.
3. Treat empty post-filter results as the race-condition fallback path: log `event_type='ubi_reader_empty_features'` and return `{}` (worker terminal `failed` path picks this up — preflight U-D2 covers the sync case).
4. Write integration test `backend/tests/integration/services/test_ubi_reader.py` that mocks `adapter.search_batch` to return canned `ubi_queries` + `ubi_events` payloads; asserts the joined `FeatureVec` shape.
5. Write integration test `backend/tests/integration/services/test_ubi_reader_no_writes.py` per §10 threat #2 — mock the underlying `httpx.AsyncClient.send`; run `read_features` end-to-end; assert zero requests with HTTP method `PUT`/`DELETE` or path containing `_bulk`/`_update`/`_doc`/`_create`.

**Definition of Done (DoD)**

- [ ] `UbiReader.read_features` returns the expected `FeatureVec` map against stubbed canned data.
- [ ] `UbiNotEnabledError` raised when `get_schema('ubi_queries')` raises `TargetNotFoundError`.
- [ ] `test_ubi_reader_no_writes.py` asserts zero write-shaped HTTP calls.
- [ ] Empty-features path returns `{}` without raising (race fallback per FR-1).
- [ ] No new method added to `SearchAdapter` Protocol — verified by re-running `backend/tests/unit/adapters/test_protocol.py` shape assertions.

---

### Story 2.2 — Readiness service + `start_ubi_judgment_generation` dispatcher (FR-4 + FR-7)

**Outcome:** A new `ubi_readiness` service classifies a `(cluster, query_set, target)` tuple on the rung 0–3 ladder. A new `start_ubi_judgment_generation` dispatcher runs the full UBI preflight + INSERT + Arq enqueue. The existing `start_judgment_generation` is refactored to share helpers with the new function (no copy-pasted body).

**New files**

| File | Purpose |
|---|---|
| `backend/app/services/ubi_readiness.py` | `classify_rung(adapter, query_set, target) -> UbiReadiness` + `UbiReadiness` dataclass. Uses `_probe_enabled` from `UbiReader` + a single `_count` aggregation on `ubi_events` filtered by `(application=target, timestamp >= now-30d, query_id IN <query_set ids>)`. Redis-cached 60s per scope. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/services/agent_judgments_dispatch.py` | Add `start_ubi_judgment_generation(...)` alongside the existing `start_judgment_generation`. Factor shared helpers: `_resolve_cluster_query_set`, `_check_consistency`, `_check_llm_preflight` (A+B+B.1+C from existing dispatcher), `_check_oversized_query_set`, `_insert_generating_list_and_enqueue(kind: Literal["llm","ubi"], **fields)`. Existing `start_judgment_generation` body is rewritten to call the shared helpers. |

**Key interfaces**

```python
# services/ubi_readiness.py
@dataclass(frozen=True, slots=True)
class UbiReadiness:
    rung: Literal["rung_0", "rung_1", "rung_2", "rung_3"]
    covered_pairs_pct: float | None
    head_covered: bool | None
    checked_at: datetime

async def classify_rung(
    *,
    adapter: SearchAdapter,
    cluster_id: str,
    query_set_id: str,
    query_set_query_ids: list[str],
    target: str,
    redis: Redis,
    min_impressions_threshold: int = 100,
) -> UbiReadiness:
    """Probe + classify; 60s Redis cache per (cluster_id, query_set_id, target)."""

# services/agent_judgments_dispatch.py
@dataclass(frozen=True, slots=True)
class UbiJudgmentGenerationRequest:
    name: str
    description: str | None
    query_set_id: str
    cluster_id: str
    target: str
    since: datetime
    until: datetime | None
    converter: Literal["ctr_threshold", "dwell_time", "hybrid_ubi_llm"]
    converter_config: dict[str, Any] | None
    llm_fill_threshold: int | None
    min_impressions_threshold: int | None
    mapping_strategy: Literal["reject", "first_match", "most_recent"]
    current_template_id: str | None  # required for hybrid
    rubric: str | None               # required for hybrid

async def start_ubi_judgment_generation(
    *,
    db: AsyncSession,
    redis: Redis,
    arq_pool: ArqRedis | None,
    settings: Settings,
    req: UbiJudgmentGenerationRequest,
) -> JudgmentGenerationResult:
    """Full preflight U-A..U-H + INSERT + best-effort Arq enqueue.

    Sync 422 on UBI_INSUFFICIENT_DATA per FR-4 U-D2 (cycle-3 D-10d).
    """
```

**Tasks**

1. Implement `classify_rung`:
   - Cache key `ubi-readiness:{cluster_id}:{query_set_id}:{target}` (60s TTL).
   - On cache miss: call `UbiReader._probe_enabled(adapter)` (catch `UbiNotEnabledError` → rung_0); otherwise run a single `_count` aggregation. Apply the FR-7 rung rules. Cache + return.
2. Factor shared helpers in `agent_judgments_dispatch.py`:
   - Extract `_resolve_cluster_query_set(db, cluster_id, query_set_id, template_id=None) -> (Cluster, QuerySet, QueryTemplate|None)` raising `_err(404, ...)` per failure.
   - Extract `_check_consistency(query_set, cluster, template=None)` raising `_err(422, "VALIDATION_ERROR", ...)`.
   - Extract `_check_llm_preflight(settings, redis)` raising the existing OPENAI_NOT_CONFIGURED / LLM_PROVIDER_INCAPABLE / UNKNOWN_MODEL_PRICING / OPENAI_BUDGET_EXCEEDED codes.
   - Extract `_check_oversized_query_set(db, query_set_id)` raising 422.
   - Extract `_insert_generating_list_and_enqueue(db, arq_pool, kind, fields, enqueue_job_name)` with the existing IntegrityError → 409 JUDGMENT_LIST_NAME_TAKEN handling; commit; best-effort enqueue.
3. Rewrite `start_judgment_generation` body to call the helpers (behavioral parity — existing contract tests at `backend/tests/contract/test_judgments_generate*.py` must still pass with no assertion changes).
4. Implement `start_ubi_judgment_generation`:
   - U-A: `_resolve_cluster_query_set(db, ..., template_id=req.current_template_id if hybrid)`.
   - U-B: `_check_consistency(...)`.
   - U-C: `await UbiReader._probe_enabled` (build adapter once via `build_adapter(cluster)`); raise 412 UBI_NOT_ENABLED.
   - U-D: window validity + 90-day cap → 422 UBI_WINDOW_TOO_LARGE.
   - U-D2 (NEW): issue one `_count` aggregation; if `count < min_impressions_threshold` → 422 UBI_INSUFFICIENT_DATA with message per spec §8.5.
   - U-E (hybrid only): `_check_llm_preflight(settings, redis)`.
   - U-F: `_check_oversized_query_set`.
   - U-G: build `generation_params` via a dedicated helper that **injects `generation_kind: 'ubi'` server-side** (Spec FR-4 U-G mandates this discriminator; without it Story 3.3's resume reconstruction loses its kind hint and Story 4.3's `<ValueDeltaCard>` can't discriminate UBI/hybrid from LLM lists). The helper signature: `_build_ubi_generation_params(req: UbiJudgmentGenerationRequest) -> dict[str, Any]`; body: `return {"generation_kind": "ubi", **req.model_dump(mode="json")}`. Pass the resulting dict to `_insert_generating_list_and_enqueue(kind='ubi', fields={..., generation_params=_build_ubi_generation_params(req)}, enqueue_job_name='generate_judgments_from_ubi')`.
   - Return `JudgmentGenerationResult(judgment_list_id, status='generating')`.
5. Write integration test `backend/tests/integration/services/test_agent_judgments_dispatch_ubi.py` covering all preflight branches; verify the shared `start_judgment_generation` still returns the same shapes/codes for the LLM path (parity). **Additional assertion**: the persisted `judgment_lists.generation_params` JSONB MUST contain `generation_kind == 'ubi'` AND the round-trip via `UbiJudgmentGenerationRequest(**{k: v for k, v in persisted.items() if k != 'generation_kind'})` succeeds (i.e., the discriminator is additive, not field-replacing).

**Definition of Done (DoD)**

- [ ] `classify_rung` returns the right rung for canned `_count` results (rung_0 / rung_1 / rung_2 / rung_3); Redis caching round-trip verified (second call within 60s does not re-probe).
- [ ] `start_ubi_judgment_generation` raises the right `HTTPException` for each preflight step with the spec §8.5 envelope shape.
- [ ] `start_judgment_generation` (LLM path) behavior unchanged — existing contract tests pass with no modification.
- [ ] Hybrid-mode rejection when `current_template_id` or `rubric` missing surfaces as 422 (Pydantic validator at the request schema layer — Story 3.2 owns the validator; this dispatcher merely consumes a validated `req`).
- [ ] Persisted `judgment_lists.generation_params` JSONB contains `generation_kind == 'ubi'` (spec FR-4 U-G discriminator) + the request fields; round-trip via `UbiJudgmentGenerationRequest(**{k: v for k, v in persisted.items() if k != 'generation_kind'})` succeeds.

---

### Story 2.3 — `_SourceBreakdown` evolution + filter widening + Literals (FR-9 + FR-10)

**Outcome:** `_SourceBreakdown` returns `{llm, human, click}` with invariant `llm + human + click == judgment_count`. `?source=` filter accepts `click`. New backend Literals (`UbiConverterKind`, `JudgmentGenerationMethodWire`, `UbiReadinessRungWire`, `UbiMappingStrategyWire`) live in `schemas.py`.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/schemas.py` | Evolve `_SourceBreakdown` to add `click: int`; widen `JudgmentSourceFilterWire` from `Literal["llm", "human"]` to `Literal["llm", "human", "click"]`; add `UbiConverterKind`, `JudgmentGenerationMethodWire`, `UbiReadinessRungWire`, `UbiMappingStrategyWire` (all per FR-9). Update the `_SourceBreakdown` docstring to remove the cycle-2 F6 fold-into-human contract; cite cycle-3 D-10 + FR-10 as the new contract. |
| `backend/app/db/repo/judgment.py` | Evolve `source_breakdown_for_list` from `{'llm': 0, 'human': 0}` start dict to `{'llm': 0, 'human': 0, 'click': 0}`; route `click` to the `click` key (was folding into `human`). Update the function docstring to cite FR-10 and remove the cycle-2 F6 "click folds into human" contract. |
| `backend/app/api/v1/judgments.py` | `_detail()` populates `_SourceBreakdown(llm=..., human=..., click=breakdown.get("click", 0))`. |

**Key interfaces**

```python
# api/v1/schemas.py
class _SourceBreakdown(BaseModel):
    """{llm + human + click == judgment_count} per FR-10 (evolved 2026-05-29
    from the cycle-2 F6 two-term shape now that UBI ships click rows)."""
    llm: int
    human: int
    click: int

JudgmentSourceFilterWire = Literal["llm", "human", "click"]  # widened from {llm, human}

UbiConverterKind = Literal["ctr_threshold", "dwell_time", "hybrid_ubi_llm"]
JudgmentGenerationMethodWire = Literal["llm", "ctr_threshold", "dwell_time", "hybrid_ubi_llm"]
UbiReadinessRungWire = Literal["rung_0", "rung_1", "rung_2", "rung_3"]
UbiMappingStrategyWire = Literal["reject", "first_match", "most_recent"]

# db/repo/judgment.py
async def source_breakdown_for_list(db: AsyncSession, judgment_list_id: str) -> dict[str, int]:
    """{'llm': N, 'human': M, 'click': K} — invariant llm + human + click == judgment_count.
    Evolved from the cycle-2 F6 two-term contract now that UBI ships click rows (FR-10)."""
```

**Tasks**

1. Add new Literals to `schemas.py` per FR-9. Group them under a `# UBI wire-value contracts (feat_ubi_judgments FR-9)` section comment.
2. Evolve `_SourceBreakdown` class definition + docstring.
3. Widen `JudgmentSourceFilterWire` and remove the "click reserved, rejected at API filter" comment.
4. Update `backend/app/db/repo/judgment.py` `source_breakdown_for_list` to count `click` separately; update the function docstring + the module docstring's "Source breakdown folds click into human" decision note (mark as superseded by FR-10).
5. Update `backend/app/api/v1/judgments.py` `_detail()` populator to pass `click`.
6. Update existing contract test at `backend/tests/contract/test_judgments_list_detail.py` (or equivalent — verify path at impl time) to assert all 3 keys on the source_breakdown shape. New assertion: on LLM-only lists `click == 0`.
7. Update existing contract test at `backend/tests/contract/test_judgments_filter.py` (or equivalent) — remove the assertion that `?source=click` returns 422 VALIDATION_ERROR; add assertion that `?source=click` returns 200 with rows where `source == 'click'`.
8. Write unit test `backend/tests/unit/api/test_source_breakdown_evolution.py` directly constructing `_SourceBreakdown(llm=10, human=5, click=20)` and asserting field access + JSON serialization shape.

**Definition of Done (DoD)**

- [ ] `_SourceBreakdown` has all 3 fields; existing LLM-list contract tests pass with `click=0`.
- [ ] `?source=click` returns 200 with matching rows; `?source=human` and `?source=llm` unchanged.
- [ ] Repo function returns all 3 keys; `click` is no longer aggregated into `human`.
- [ ] Mypy `--strict` clean across `schemas.py`, `judgment.py`, `judgments.py`.

---

## Epic 3 — API + worker + agent tool

### Story 3.1 — `GET /api/v1/clusters/{cluster_id}/ubi-readiness` endpoint (FR-7)

**Outcome:** The readiness endpoint returns `{rung, covered_pairs_pct, head_covered, checked_at}` for a `(cluster, query_set, target)` tuple. Cached 60s server-side per scope.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/clusters.py` | Add `GET /clusters/{cluster_id}/ubi-readiness` handler. Required `?query_set_id=<uuid>&target=<string>` query params (else 422 VALIDATION_ERROR per cycle-3 D-10c). Calls `classify_rung` from Story 2.2. |
| `backend/app/api/v1/schemas.py` | Add `UbiReadinessResponse(BaseModel)` with the 4 fields. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/clusters/{cluster_id}/ubi-readiness?query_set_id=&target=` | — (query params required) | `200` `{ rung: UbiReadinessRungWire, covered_pairs_pct: float \| null, head_covered: bool \| null, checked_at: datetime }` | `404 CLUSTER_NOT_FOUND`, `404 QUERY_SET_NOT_FOUND`, `422 VALIDATION_ERROR` (missing query params), `503 CLUSTER_UNREACHABLE` |

**Pydantic schemas**

```python
class UbiReadinessResponse(BaseModel):
    rung: UbiReadinessRungWire
    covered_pairs_pct: float | None
    head_covered: bool | None
    checked_at: datetime
```

**Tasks**

1. Add the handler `get_cluster_ubi_readiness` in `backend/app/api/v1/clusters.py` after `get_cluster_schema` (line ~317). FastAPI signature mirrors `get_cluster_schema` for cluster resolution + builds the adapter via `build_adapter(cluster)`.
2. Resolve `query_set_id` → `repo.get_query_set` (404 QUERY_SET_NOT_FOUND); pull query IDs via `repo.list_queries_for_set` (Story 2.2's `classify_rung` needs the id list for the `query_id IN` filter).
3. Open Redis client per request (use the same `_open_redis` helper pattern from `judgments.py:107`).
4. Call `classify_rung(...)` and return `UbiReadinessResponse(**asdict(reading))`.
5. Catch `ClusterUnreachableError` from the adapter → 503 CLUSTER_UNREACHABLE; catch generic exception → 500 with `event_type='ubi_readiness_unexpected_error'` log.
6. Write contract test `backend/tests/contract/test_clusters_ubi_readiness_shape.py` asserting all 4 error envelopes + 200 shape.
7. Write integration test `backend/tests/integration/api/test_clusters_ubi_readiness.py` with the 4-rung paths (mock the adapter); Redis cache hit verified on second call.

**Definition of Done (DoD)**

- [ ] All 4 error envelopes (404 ×2, 422, 503) return the structured `{"detail": {"error_code", "message", "retryable"}}` shape.
- [ ] 200 response shape matches `UbiReadinessResponse` exactly.
- [ ] Cache hit within 60s returns identical response without re-running the cluster aggregation (verified via spy on `adapter.search_batch`).
- [ ] Endpoint registered in `backend/app/main.py` via the existing `clusters_router.router` mount (no new mount required).

---

### Story 3.2 — `POST /api/v1/judgments/generate-from-ubi` endpoint (FR-3)

**Outcome:** The UBI generate endpoint returns 202 with `GenerateJudgmentsResponse{judgment_list_id, status}`. Delegates to `start_ubi_judgment_generation`. Conditional `current_template_id`/`rubric` validator on the request body.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/judgments.py` | Add `POST /judgments/generate-from-ubi` handler `generate_judgments_from_ubi` after the existing `generate_judgments` (line ~170). |
| `backend/app/api/v1/schemas.py` | Add `CreateJudgmentListFromUbiRequest(BaseModel)` with the 12 fields per FR-3 + a `model_validator(mode='after')` for the hybrid conditional. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/judgments/generate-from-ubi` | `CreateJudgmentListFromUbiRequest` (12 fields, see schema below) | `202` `GenerateJudgmentsResponse{ judgment_list_id, status: "generating" }` | `412 UBI_NOT_ENABLED`, `422 UBI_INSUFFICIENT_DATA`, `422 UBI_WINDOW_TOO_LARGE`, `422 VALIDATION_ERROR`, `404 CLUSTER_NOT_FOUND`, `404 QUERY_SET_NOT_FOUND`, `404 TEMPLATE_NOT_FOUND` (hybrid only), `409 JUDGMENT_LIST_NAME_TAKEN`, `503 OPENAI_NOT_CONFIGURED` (hybrid only), `503 LLM_PROVIDER_INCAPABLE` (hybrid only), `503 UNKNOWN_MODEL_PRICING` (hybrid only), `503 OPENAI_BUDGET_EXCEEDED` (hybrid only) |

**Pydantic schemas**

```python
class CreateJudgmentListFromUbiRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2000)
    query_set_id: str = Field(min_length=1, max_length=36)
    cluster_id: str = Field(min_length=1, max_length=36)
    target: str = Field(min_length=1, max_length=256)
    since: datetime
    until: datetime | None = None
    converter: UbiConverterKind
    converter_config: dict[str, Any] | None = None
    llm_fill_threshold: int | None = Field(default=20, ge=1)
    min_impressions_threshold: int | None = Field(default=100, ge=1)
    mapping_strategy: UbiMappingStrategyWire = "reject"
    current_template_id: str | None = Field(default=None, min_length=36, max_length=36)
    rubric: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _validate_hybrid_conditional(self) -> "CreateJudgmentListFromUbiRequest":
        is_hybrid = self.converter == "hybrid_ubi_llm"
        has_template = self.current_template_id is not None
        has_rubric = self.rubric is not None
        if is_hybrid and not (has_template and has_rubric):
            raise ValueError(
                "current_template_id and rubric are REQUIRED when converter == 'hybrid_ubi_llm'"
            )
        if not is_hybrid and (has_template or has_rubric):
            raise ValueError(
                "current_template_id and rubric MUST be null for non-hybrid converters"
            )
        return self
```

**Tasks**

1. Add `CreateJudgmentListFromUbiRequest` to `schemas.py` after the existing `CreateJudgmentListGenerateRequest` (line ~840).
2. Add the handler in `judgments.py`:
   ```python
   @router.post(
       "/judgments/generate-from-ubi",
       response_model=GenerateJudgmentsResponse,
       status_code=status.HTTP_202_ACCEPTED,
       tags=["judgments"],
   )
   async def generate_judgments_from_ubi(
       body: CreateJudgmentListFromUbiRequest,
       request: Request,
       db: Annotated[AsyncSession, Depends(get_db)],
   ) -> GenerateJudgmentsResponse:
       """Start a UBI-derived judgment generation job."""
       settings = get_settings()
       arq_pool = getattr(request.app.state, "arq_pool", None)
       redis_client: Redis | None = None
       try:
           redis_client = await _open_redis()
           result = await start_ubi_judgment_generation(
               db=db, redis=redis_client, arq_pool=arq_pool, settings=settings,
               req=UbiJudgmentGenerationRequest(**body.model_dump()),
           )
           return GenerateJudgmentsResponse(
               judgment_list_id=result.judgment_list_id,
               status=result.status,
           )
       finally:
           if redis_client is not None:
               try:
                   await redis_client.aclose()
               except Exception as exc:
                   logger.debug("redis close raised", error=str(exc))
   ```
3. Write contract test `backend/tests/contract/test_judgments_generate_from_ubi_shape.py` asserting the 202 response shape + each of the 13 error envelopes documented in the endpoint table.
4. Write integration test `backend/tests/integration/api/test_judgments_generate_from_ubi.py` exercising every preflight branch end-to-end against a stubbed `UbiReader` + adapter; verify the `judgment_lists.generation_params` JSONB column is populated correctly on success.
5. Update OpenAPI schema lock test (if any) to include the new endpoint in the inventory.

**Definition of Done (DoD)**

- [ ] All 13 error envelopes match the spec §8.5 catalog + spec §8.3 example bodies.
- [ ] 202 success returns `GenerateJudgmentsResponse` with `judgment_list_id` matching the row's `id` and `generation_params` populated for inspection in the integration test.
- [ ] Hybrid-mode missing `current_template_id` returns 422 with detail mentioning the field name.
- [ ] Non-hybrid with `rubric` present returns 422 with the conditional-validator message.
- [ ] `model_validator` test asserts both branches of the conditional via FastAPI's `RequestValidationError` envelope.

---

### Story 3.3 — `generate_judgments_from_ubi` Arq worker (FR-5)

**Outcome:** The UBI worker pipeline reads UBI features → applies the chosen converter (awaiting LLM-fill for hybrid pairs) → bulk-inserts judgments with the correct `source`/`rater_ref` → writes calibration JSONB → terminal-status flip.

**Modified files**

| File | Change |
|---|---|
| `backend/workers/judgments.py` | Add `generate_judgments_from_ubi(ctx, judgment_list_id)` after the existing `generate_judgments_llm` (line ~354). Reuse `_safe_record_cost`, `_fail_list`. Add a worker-local `_make_llm_rate_callback(...)` helper that wraps `rate_query_batch` for the hybrid converter's `llm_rate` parameter. |
| `backend/workers/all.py` | Register `generate_judgments_from_ubi` in `WorkerSettings.functions`. Extend the boot-time resume sweep at `backend/workers/all.py:148-161` to enqueue both `generate_judgments_llm` (for LLM lists where `generation_params IS NULL`) AND `generate_judgments_from_ubi` (for UBI lists where `generation_params IS NOT NULL`) on `status='generating'` rows. |

**Key interfaces**

```python
# workers/judgments.py
async def generate_judgments_from_ubi(ctx: dict[str, Any], judgment_list_id: str) -> None:
    """Arq entry point — run the UBI judge pipeline for one judgment list.

    Contract (per FR-5):
    1. Load judgment_list row + generation_params; bail if missing/terminal/missing params.
    2. Build adapter, UbiReader, position-bias prior.
    3. Read features → apply converter (awaits LLM-fill via injected callback for hybrid).
    4. Apply mapping_strategy per query; count per-query skips.
    5. Bulk-insert judgments (source='click' for UBI rows, 'llm' for hybrid LLM-fill).
    6. Write calibration JSONB with coverage + skip counts.
    7. Terminal status flip.
    """

def _make_llm_rate_callback(
    *,
    openai_client: AsyncOpenAI,
    model: str,
    rubric: str,
    bundle_system: str,
    query_id_to_text: dict[str, str],
    redis: Redis,
    budget_usd: float,
) -> LlmRateCallback:
    """Worker-local: build the LlmRateCallback for HybridUbiLlmConverter.

    Each call routes through rate_query_batch + _safe_record_cost so the
    daily-budget gate + capability cache fire unchanged.
    """
```

**Tasks**

1. Implement `generate_judgments_from_ubi`:
   - Load row → bail if missing or `status != 'generating'`.
   - Read `generation_params`; bail with `_fail_list(..., 'MISSING_GENERATION_PARAMS')` if NULL (race guard).
   - Build adapter via `build_adapter(cluster)`; build `UbiReader` with `Settings.ubi_position_bias_prior`.
   - `features = await ubi_reader.read_features(target, since, until, ...)`. Catch `UbiNotEnabledError` → `_fail_list(..., 'UBI_NOT_ENABLED')`; empty `features` → `_fail_list(..., 'UBI_INSUFFICIENT_DATA')` (race fallback per FR-1).
   - Construct the converter:
     - `'ctr_threshold'` → `CtrThresholdConverter()`
     - `'dwell_time'` → `DwellTimeThresholdConverter()`
     - `'hybrid_ubi_llm'` → `HybridUbiLlmConverter(inner=..., llm_rate=_make_llm_rate_callback(...))`. Pull `inner` per `converter_config.inner` (default `'ctr_threshold'`).
   - `ratings = await converter.convert(features, ConverterConfig(extra=generation_params.get('converter_config') or {}))`.
   - Apply `mapping_strategy` per query (Python-side dict resolution; track `ambiguous_query_skip_count`).
   - Build the rows: UBI pairs → `{source: 'click', rater_ref: f'ubi:{converter_kind}'}`; hybrid LLM-fill pairs (carried through via the callback's persistence pattern — see step 2) → `{source: 'llm', rater_ref: f'openai:{model}'}`.
   - `await repo.bulk_create_judgments(db, rows)`; `await db.commit()`.
   - Write calibration JSONB: `{coverage_pct, head_pairs, tail_pairs, position_bias_prior_id, llm_fill_calls?, ambiguous_query_skip_count, sparse_query_skip_count}`.
   - Terminal flip to `complete` (or `failed` on caught error per FR-5 step 8).
2. Implement `_make_llm_rate_callback`: closure over openai_client/model/rubric/redis/budget; per call computes `expected_doc_ids`, runs `rate_query_batch`, persists rows immediately (NOT deferred to caller — matches the LLM-worker persist-first / record-cost-second pattern in `_process_query`), calls `_safe_record_cost`. Returns `{(query_id, doc_id): rating}`.
3. Register the job in `backend/workers/all.py` `WorkerSettings.functions = [..., generate_judgments_from_ubi]`.
4. Extend the boot-time resume sweep at `backend/workers/all.py:148-161` per the spec FR-5 + the `feat_judgments_periodic_resume_sweep` pattern. Use `generation_params IS NOT NULL` as the UBI discriminator (LLM lists have NULL).
5. Write integration test `backend/tests/integration/workers/test_generate_judgments_from_ubi.py` covering: clean-loop completes with all-`click` rows; hybrid produces mixed list; resume after crash skips already-rated queries; ambiguous-mapping per-query skip; `UbiInsufficientDataError` mid-loop → `failed_reason='UBI_INSUFFICIENT_DATA'`; `BudgetExceededError` mid-hybrid → `failed_reason='OPENAI_BUDGET_EXCEEDED'`.

**Definition of Done (DoD)**

- [ ] Clean loop on a rung_3 fixture completes with `judgment_count > 0`, all rows `source='click'`, `calibration.coverage_pct >= 0.5`.
- [ ] Hybrid loop produces both `source='click'` and `source='llm'` rows; `calibration.llm_fill_calls == count(source='llm')`.
- [ ] Ambiguous-mapping per-query skip increments `calibration.ambiguous_query_skip_count` without flipping status to `failed`.
- [ ] Race-fallback `UbiInsufficientDataError` mid-loop → terminal `status='failed'`, `failed_reason='UBI_INSUFFICIENT_DATA'`.
- [ ] Resume sweep re-enqueues a UBI list with `status='generating'` and per-query resume-skip prevents re-spending LLM calls.
- [ ] Worker file does NOT instantiate `openai.AsyncClient(...)` outside `_make_llm_rate_callback`'s parameter binding (lint guard: ast scan).

---

### Story 3.4 — `generate_judgments_from_ubi` agent tool + orchestrator system-prompt update (FR-6)

**Outcome:** The chat agent exposes a new MUTATING tool `generate_judgments_from_ubi`. The orchestrator's system prompt prefers UBI when the cluster's readiness rung ≥ 1.

**New files**

| File | Purpose |
|---|---|
| `backend/app/agent/tools/judgments/generate_judgments_from_ubi.py` | `GenerateJudgmentsFromUbiArgs` + `generate_judgments_from_ubi_impl` + `GENERATE_JUDGMENTS_FROM_UBI_TOOL` triad. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/agent/tools/__init__.py` | Import + add to `TOOLS`, `TOOL_REGISTRY`, `TOOL_ARG_MODELS`. Module-load drift assertion at line 232–236 catches a missing registration. |
| `backend/app/agent/tools/judgments/__init__.py` | Re-export the new tool symbols. |
| `prompts/orchestrator.system.md` (verify path at impl time; if `_load_system_prompt` in `orchestrator.py` reads from a different path, adjust) | Update the "generate a judgment list" tool selection guidance: prefer `generate_judgments_from_ubi` when the cluster has UBI rung ≥ 1; default to `generate_judgments_llm` otherwise. Provide one-line examples for both. |

**Key interfaces**

```python
# agent/tools/judgments/generate_judgments_from_ubi.py
class GenerateJudgmentsFromUbiArgs(BaseModel):
    """Mirrors CreateJudgmentListFromUbiRequest (the router's request body)."""
    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=2000)
    query_set_id: UUID
    cluster_id: UUID
    target: str = Field(min_length=1, max_length=256)
    since: datetime
    until: datetime | None = None
    converter: UbiConverterKind
    converter_config: dict[str, Any] | None = None
    llm_fill_threshold: int | None = Field(default=20, ge=1)
    min_impressions_threshold: int | None = Field(default=100, ge=1)
    mapping_strategy: UbiMappingStrategyWire = "reject"
    current_template_id: UUID | None = None
    rubric: str | None = None

async def generate_judgments_from_ubi_impl(
    args: GenerateJudgmentsFromUbiArgs, ctx: ToolContext,
) -> dict[str, Any]:
    """Start a UBI-judgment job. MUTATING — confirmation guard required."""

GENERATE_JUDGMENTS_FROM_UBI_TOOL: ChatCompletionToolParam = {...}
```

**Tasks**

1. Implement the triad following the exact pattern from `backend/app/agent/tools/judgments/generate_judgments_llm.py`.
2. Add `model_validator(mode='after')` mirroring the API schema's hybrid conditional so the agent-tool dispatch rejects the same bad shape locally (before hitting the dispatcher) for cleaner error messages in the chat stream.
3. Register in `TOOLS` / `TOOL_REGISTRY` / `TOOL_ARG_MODELS` — the module-load assertion at `__init__.py:232-236` will fail if any of the three is missed.
4. Update `prompts/orchestrator.system.md` (or wherever `_load_system_prompt` reads) — add a "Choosing between LLM and UBI judgment generation" section. Reference both tool names. Note the rung-detection heuristic (probe via `get_schema` if the operator's intent is judgment-generation and the rung is unknown).
5. Write integration test `backend/tests/integration/agent/test_generate_judgments_from_ubi_tool.py`: tool dispatch returns the expected shape on a stubbed `start_ubi_judgment_generation`; confirmation guard fires; tool registry drift assertion catches a forced mis-registration (negative test).
6. Add the tool to the contract-test agent-tool inventory at `backend/tests/contract/test_agent_tool_inventory.py` (or equivalent).

**Definition of Done (DoD)**

- [ ] Tool dispatch round-trips through the confirmation guard → `start_ubi_judgment_generation` → returns `{judgment_list_id, status}`.
- [ ] Removing the tool from any one of `TOOLS` / `TOOL_REGISTRY` / `TOOL_ARG_MODELS` causes a `RuntimeError` at module import time (negative test).
- [ ] Updated system prompt mentions both tool names; the orchestrator system-prompt unit test (if present) verifies the names appear.

---

## Epic 4 — Frontend (method picker + on-ramp UX + value-delta)

### Story 4.1 — Wire enums + `useUbiReadiness` hook + `<UbiRungBadge>` primitive (FR-7 + FR-8 + FR-9 mirror)

**Outcome:** UI mirrors of the four backend Literals exist with the `// Values must match backend/...` discipline comment. `useUbiReadiness(clusterId, querySetId, target)` hook hits the new endpoint with 60s React Query stale time. `<UbiRungBadge>` renders the rung as a text-only badge with a glossary-keyed tooltip.

**New files**

| File | Purpose |
|---|---|
| `ui/src/lib/api/ubi.ts` | TanStack Query hooks: `useUbiReadiness(clusterId, querySetId, target)`, `useGenerateJudgmentsFromUbi()`. |
| `ui/src/components/clusters/ubi-rung-badge.tsx` | `<UbiRungBadge rung={…} />` text-only badge with glossary-keyed tooltip (per rung label per spec §11). **Single variant** — renders one of the 4 `UBI_READINESS_RUNG_VALUES` labels. Only consumed inside the generate-judgments dialog (Story 4.2) where the parent has `clusterId` + `querySetId` + `target` to call `useUbiReadiness(...)`. NOT rendered on cluster cards or cluster detail (those pages lack query_set/target context — spec FR-7 requires both as query params, so calling the endpoint without them returns 422). |

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/enums.ts` | Add `JUDGMENT_GENERATION_METHOD_VALUES` (4 values, mirrors `JudgmentGenerationMethodWire`), `UBI_CONVERTER_VALUES` (3 values, mirrors `UbiConverterKind`), `UBI_READINESS_RUNG_VALUES` (4 values), `UBI_MAPPING_STRATEGY_VALUES` (3 values). Widen `JUDGMENT_SOURCE_FILTER_VALUES` from `['llm', 'human']` to `['llm', 'human', 'click']`. Each new array carries the `// Values must match backend/app/api/v1/schemas.py <Symbol>` comment per the source-of-truth policy. |
| `ui/src/lib/glossary.ts` | Add 5 new entries: `judgment.converter`, `judgment.converter.llm`, `judgment.converter.ubi`, `judgment.converter.hybrid`, `cluster.ubi_readiness` (per spec §11 + §15). Each carries a `// Source-of-truth: backend/app/api/v1/schemas.py <Symbol>` comment. |
| (none) | **No changes to `ui/src/app/clusters/page.tsx` or `ui/src/app/clusters/[id]/page.tsx`.** Cycle-3 plan review: the spec FR-7 readiness endpoint requires `?query_set_id` + `?target` as query params (returns 422 without). Cluster cards / cluster detail pages don't have a query_set/target in their data flow, so calling the endpoint there would either always 422 or require inventing a separate cluster-level capability endpoint outside spec scope. Decision: render `<UbiRungBadge>` ONLY inside the generate-judgments dialog (Story 4.2), where the parent supplies all three context fields. Operators discover UBI when they open the dialog — the same surface where they choose the converter. If a future operator-feedback signal asks for a cluster-card-level UBI indicator, capture as `chore_cluster_card_ubi_indicator` idea file with a proposed `GET /clusters/{id}/ubi-enabled` endpoint scoped to a simple plugin-present/absent boolean. |

**UI element inventory**

- `<UbiRungBadge rung={...} />` — text-only badge. Single variant. Renders one of 4 labels per rung: "rung_0: UBI not enabled", "rung_1: UBI sparse", "rung_2: UBI dense head", "rung_3: UBI full coverage" (final wording verify against spec §11 IA labels at impl time).
- Color: text-only with subtle muted-background, no color-only meaning. WCAG AA contrast.
- Tooltip: `HelpPopover` keyed off `cluster.ubi_readiness` glossary entry.
- **Consumption surface**: ONLY inside the generate-judgments dialog (Story 4.2). NOT rendered on cluster list/detail (cycle-3 review: spec FR-7 requires `?query_set_id`+`?target`; those pages don't have it).

**Wire value enumeration table** (per CLAUDE.md "Enumerated Value Contract Discipline"):

| Frontend array | Backend source-of-truth | Values |
|---|---|---|
| `JUDGMENT_GENERATION_METHOD_VALUES` | `JudgmentGenerationMethodWire` | `'llm', 'ctr_threshold', 'dwell_time', 'hybrid_ubi_llm'` |
| `UBI_CONVERTER_VALUES` | `UbiConverterKind` | `'ctr_threshold', 'dwell_time', 'hybrid_ubi_llm'` |
| `UBI_READINESS_RUNG_VALUES` | `UbiReadinessRungWire` | `'rung_0', 'rung_1', 'rung_2', 'rung_3'` |
| `UBI_MAPPING_STRATEGY_VALUES` | `UbiMappingStrategyWire` | `'reject', 'first_match', 'most_recent'` |
| `JUDGMENT_SOURCE_FILTER_VALUES` (widened) | `JudgmentSourceFilterWire` (widened in Story 2.3) | `'llm', 'human', 'click'` |

**Tasks**

1. Add the 4 new arrays + the widening to `enums.ts`. Run the existing enum-source-of-truth grep gate (CI gate at `scripts/ci/verify_enum_source_of_truth.sh` — verify path during impl) on a local branch to confirm parity.
2. Add the 5 glossary entries to `glossary.ts` with the source-of-truth comment.
3. Implement `useUbiReadiness` with React Query: queryKey `['ubi-readiness', clusterId, querySetId, target]`, 60s `staleTime`, gracefully degrades to `{rung: 'rung_0', covered_pairs_pct: null, head_covered: null}` on 503/404 (operator gets the LLM-default behavior).
4. Implement `useGenerateJudgmentsFromUbi` as a TanStack mutation hitting `POST /api/v1/judgments/generate-from-ubi`.
5. Implement `<UbiRungBadge>` (single variant). Tooltip uses `<HelpPopover>` keyed off `cluster.ubi_readiness`. Per-rung labels per the UI element inventory above.
6. (Removed at cycle-3 plan review per finding `readiness-snapshot-badge-contract-drift` — no cluster-card / cluster-detail badge render. The component is solely consumed inside Story 4.2's dialog.)
7. Write component tests `ui/src/__tests__/components/clusters/ubi-rung-badge.test.tsx` for all 4 rungs (single variant, no snapshot mode).
8. Write enum lint guard pass: the new arrays MUST appear in `enums.ts` with the discipline comment; the lint guard at `ui/src/__tests__/lib/enums-source-of-truth.test.ts` (verify path at impl time — may need to add to the regex if not generic).

**Definition of Done (DoD)**

- [ ] All 4 new enum arrays + the widened `JUDGMENT_SOURCE_FILTER_VALUES` in `enums.ts` with the discipline comment.
- [ ] All 5 new glossary entries with source-of-truth comments.
- [ ] `useUbiReadiness` returns the expected shape against a mocked API response; falls back gracefully on 503/404.
- [ ] `<UbiRungBadge>` component tests pass; all 4 rung labels render correctly; tooltip wired to glossary.
- [ ] Cluster list + detail pages unchanged (no badge added there per cycle-3 plan-review fix `readiness-snapshot-badge-contract-drift`).

---

### Story 4.2 — Generate-judgments dialog: method picker + UBI window controls + engine-aware nudge + sparse-data card (FR-8)

**Outcome:** The existing `<GenerateJudgmentsDialog>` extends with a 4-option **method** picker, conditional UBI window controls, conditional LLM-fill threshold, an engine-aware dismissible nudge above the dialog body when rung_0, and a sparse-data recommendation card when rung_1.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/clusters/ubi-onramp-nudge.tsx` | Dismissible nudge card. Engine-aware copy via switch on `cluster.engine_type`. Persists dismissal in localStorage keyed by `cluster_id` (per D-7). |
| `ui/src/components/query-sets/ubi-sparse-data-card.tsx` | Inline recommendation card with "Switch to hybrid" affordance. Visible when `useUbiReadiness().rung === 'rung_1'` AND the picker currently selects a pure UBI converter. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/query-sets/generate-judgments-dialog.tsx` | (i) Render `<UbiOnrampNudge>` above the dialog body when `useUbiReadiness().rung === 'rung_0'`. (ii) Add **Method** `<Select>` consuming `JUDGMENT_GENERATION_METHOD_VALUES.map(...)`. (iii) Add `<UbiSparseDataCard>` inline when applicable. (iv) Conditionally render: UBI window controls (`since`/`until`) when method ≠ `llm`; LLM-fill threshold when method == `hybrid_ubi_llm`; rubric only when method involves LLM (`llm` or `hybrid_ubi_llm`). (v) Update `submit(values)` to route: method `llm` → existing `useGenerateJudgments()` (LLM endpoint); method ∈ UBI three → `useGenerateJudgmentsFromUbi()` (new endpoint). (vi) Picker default seeded from `useUbiReadiness({clusterId, querySetId, target})` rung. |

**UI element inventory**

- **Method `<Select>`** — 4 options from `JUDGMENT_GENERATION_METHOD_VALUES`. Labels per D-2: "LLM-as-judge", "UBI (click-through)", "UBI (dwell-time)", "Hybrid UBI + LLM". Default selection from rung (rung_0 → `llm`; rung_1/rung_2 → `hybrid_ubi_llm`; rung_3 → `ctr_threshold`). Each option has an inline `<HelpPopover>` keyed off the matching `judgment.converter.*` glossary entry (per spec §11 tooltip table).
- **Window controls** — `<Input type="datetime-local" name="since">` + `<Input type="datetime-local" name="until">`. Default `since = now - 30 days`. Both visible when method ≠ `llm`.
- **LLM-fill threshold** — `<Input type="number" name="llm_fill_threshold" min="1" defaultValue={20}>`. Visible when method == `hybrid_ubi_llm`.
- **Rubric** — existing `<Textarea>` shown when method ∈ {`llm`, `hybrid_ubi_llm`}; hidden for pure UBI (the column stores a converter-description string at INSERT time for those, no operator input needed).
- **Engine-aware nudge** — `<Card>` above dialog body when rung_0. Header "Enable real user signals". Body: engine-specific runbook deep-link (OpenSearch → OpenSearch UBI plugin; Elasticsearch → o19s ES UBI fork; Solr arm dark until `infra_adapter_solr`). Dismiss button persists dismissal in localStorage keyed `relyloop.ubi-onramp-nudge.dismissed:{cluster_id}`.
- **Sparse-data card** — `<Card role="region" aria-labelledby="...">` inline below the picker when rung_1 + pure-UBI method selected. Body: "Only ~X% of your query set has dense UBI signal. Hybrid rates that head and the LLM fills the rest." "Switch to hybrid" button mutates the picker to `hybrid_ubi_llm`.

**Tasks**

1. Implement `<UbiOnrampNudge>` following the `<DemoDataBanner>` pattern (SSR-safe via `useSyncExternalStore` + `safeLocalStorageGet`/`safeLocalStorageSet`). Storage key includes `cluster_id` per D-7.
2. Implement `<UbiSparseDataCard>` with the "Switch to hybrid" action firing the picker mutation via a `onSwitchToHybrid` callback prop.
3. Extend `<GenerateJudgmentsDialog>` form values to add `method`, `since`, `until`, `llm_fill_threshold`. Update `react-hook-form`'s `useForm<>` typing.
4. Add the **Method** `<Select>` using `JUDGMENT_GENERATION_METHOD_VALUES.map(...)`. Each `<SelectItem>` carries a `<HelpPopover>` inside (verify via `<Select>` primitive composition; if Radix `<SelectItem>` doesn't accept popover children, render the helper inline under the trigger when the option is highlighted).
5. Wire submission routing: `if values.method === 'llm'` → call `useGenerateJudgments()` with the existing LLM body shape; else → call `useGenerateJudgmentsFromUbi()` with the UBI body shape (converter = method).
6. Wire `<UbiOnrampNudge>` + `<UbiSparseDataCard>` conditional rendering on the `useUbiReadiness` rung.
7. Update existing dialog vitest at `ui/src/__tests__/components/query-sets/generate-judgments-dialog.test.tsx` for the new flow: rung_0 → nudge + LLM-default picker; rung_1 → hybrid-default picker + sparse card on switch to pure UBI; rung_3 → ctr_threshold-default picker; method switch routes correctly.
8. Run the form-select discipline lint guard at `ui/src/__tests__/components/common/form-select-discipline.test.tsx` to confirm the new `<Select>` doesn't trip the inline-SelectItem regression.

**Legacy behavior parity**

Spec §2 audit identifies the existing dialog as the modification target — no >100 LOC user-facing component is being deleted. The dialog grows in place. Existing fields (name, target, current_template_id, rubric) keep their current validation + submit behavior on the LLM path. The new fields layer on top with conditional render gates. **No legacy behavior parity table required** — no component is being deleted or replaced.

**Definition of Done (DoD)**

- [ ] Method `<Select>` renders all 4 options using `JUDGMENT_GENERATION_METHOD_VALUES.map(...)` (form-select discipline lint guard passes).
- [ ] Default selection per rung verified in vitest (rung_0 → `llm`; rung_1 → `hybrid_ubi_llm`; rung_3 → `ctr_threshold`).
- [ ] `<UbiOnrampNudge>` renders only when rung_0; dismissal persists across page reload for the same `cluster_id` (E2E covers this in Story 5.2).
- [ ] `<UbiSparseDataCard>` renders only when rung_1 AND method is a pure UBI converter; "Switch to hybrid" mutates the picker.
- [ ] Submit routes to the correct endpoint per method selection (verified via vitest with mocked `useGenerateJudgments` / `useGenerateJudgmentsFromUbi`).
- [ ] Rubric textarea hidden when method ∈ {`ctr_threshold`, `dwell_time`}.

---

### Story 4.3 — Judgment-list detail page: value-delta card + ambiguous-skip recovery card (FR-8 Capability D)

**Outcome:** The judgment-list detail page renders a value-delta card on UBI/hybrid lists (vs. prior LLM list when one exists on the same query_set; coverage-only when no prior exists per D-9). Ambiguous-mapping-skip recovery card surfaces when `calibration.ambiguous_query_skip_count > 0` with a one-shot "Re-run with `most_recent` tiebreaker" affordance.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/judgments/value-delta-card.tsx` | Value-delta card. Receives `currentList` + optional `priorList`. Renders coverage-only when `priorList` is null. |
| `ui/src/components/judgments/ambiguous-skip-recovery-card.tsx` | Recovery card with "Re-run with `most_recent`" button that re-POSTs the original request. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/app/judgments/[id]/page.tsx` | Conditionally render `<ValueDeltaCard>` for UBI/hybrid lists (detected via `judgment.calibration && 'coverage_pct' in calibration`); render `<AmbiguousSkipRecoveryCard>` when `calibration.ambiguous_query_skip_count > 0`. Inject a query for the prior LLM list on the same `query_set_id` (`useJudgmentLists({query_set_id, sort: 'created_at:desc'})` filtered to LLM-only — sourced via the existing list endpoint's existing filters). |
| `ui/src/lib/api/judgments.ts` | Add helper to detect "prior LLM list on same query_set" — a thin wrapper around `useJudgmentLists({query_set_id, …})`. |

**UI element inventory**

- **`<ValueDeltaCard>`** — `<Card role="region">`. Header "What real signals bought you". Body (with prior LLM list): "This UBI list covered N% of last week's real traffic with C ratings — the previous LLM list (`<PriorListName>`) rated L pairs on a snapshot." (Coverage-only): "This UBI list covered N% of last week's real traffic with C ratings."
- **`<AmbiguousSkipRecoveryCard>`** — `<Card role="region">`. Header "Skipped queries due to ambiguous UBI mapping". Body: "We skipped K queries because the same `user_query` matched more than one entry in your query set, and your `mapping_strategy` is `reject`." Action button: "Re-run with `most_recent` tiebreaker" → calls `useGenerateJudgmentsFromUbi()` with the original request body + `mapping_strategy='most_recent'` + a derived name (`<original>-most-recent`).

**Tasks**

1. Implement `<ValueDeltaCard>` with both branches.
2. Implement `<AmbiguousSkipRecoveryCard>` with the re-run mutation; the prior request body is reconstructed from the current list's `generation_params` JSONB (so the endpoint MUST surface that column in the detail response — see Story 2.3 follow-up note: the existing `JudgmentListDetail` response does NOT expose `generation_params`; add it to the response model in Story 2.3's `_detail()` populator). **Add to Story 2.3 task list:** "Expose `generation_params: dict[str, Any] | None` on `JudgmentListDetail`."
3. Render conditionally on the detail page. UBI/hybrid detection: `judgment.calibration && 'coverage_pct' in calibration` OR `judgment.generation_params && generation_params.generation_kind === 'ubi'`.
4. Write vitest tests for both card variants (with prior, without prior, with skip-count, without skip-count).

**Legacy behavior parity**

No component >100 LOC is being deleted or replaced. The detail page gains two cards. **No legacy parity table required.**

**Definition of Done (DoD)**

- [ ] `<ValueDeltaCard>` renders coverage-only when no prior LLM list exists.
- [ ] `<ValueDeltaCard>` renders the delta when a prior LLM list exists (verified via vitest with mocked prior).
- [ ] `<AmbiguousSkipRecoveryCard>` renders only when `calibration.ambiguous_query_skip_count > 0`; "Re-run" button fires the mutation with the original body + `mapping_strategy='most_recent'` (verified via vitest mock).
- [ ] Story 2.3 follow-up confirmed: `JudgmentListDetail` response includes `generation_params` (required by the recovery card).

---

## Epic 5 — Docs + E2E

### Story 5.1 — Operator docs (runbook + glossary + FAQ + tutorial + umbrella spec patches)

**Outcome:** A new UBI runbook ships at `docs/03_runbooks/ubi-judgment-generation.md`. Glossary + FAQ are populated. Tutorial Step 7 is added. Umbrella spec patches land per spec §15.

**New files**

| File | Purpose |
|---|---|
| `docs/03_runbooks/ubi-judgment-generation.md` | Sections: install OpenSearch UBI plugin → configure event capture in operator application → choose converter → calibrate position-bias prior → debug `UBI_INSUFFICIENT_DATA` / per-query skip events. Cross-link to engine UBI projects (OpenSearch UBI plugin GitHub, o19s ES UBI fork, Solr `solr.UBIComponent` reference guide). |

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/glossary.ts` | (Already covered in Story 4.1 — the 5 keys live there.) Verify no duplication. |
| `ui/src/lib/faq.ts` | Add 3 entries to the `judgments` category: "Do I need UBI to use RelyLoop?", "Should I trust UBI ratings over LLM ratings?", "My cluster shows 'No UBI' — is that a problem?". Anchors `do-i-need-ubi`, `trust-ubi-over-llm`, `cluster-no-ubi`. |
| `docs/08_guides/tutorial-first-study.md` | Add Step 7: "Swap the LLM judgment list for a UBI-derived one." Demonstrates the value-delta upgrade by re-running the tutorial study against the new list. **Tutorial must clearly state this step is OPTIONAL** — the tutorial completes fully on the LLM path for readers with no UBI cluster. |
| `docs/00_overview/relyloop-spec.md` §14 + §706 + §724 | Apply the 3 preflight-discovered patches: (a) §706 `(MVP1.5)` → `(MVP2)`; (b) §724 relative paths corrected to `planned_features/02_mvp2/<feature>/idea.md`; (c) §14 re-anchor (already in spec §1 Purpose — formalize the prose). |
| `docs/01_architecture/api-conventions.md` | One-line addition: `POST /api/v1/judgments/generate-from-ubi` follows the existing `/judgments/generate-*` action pattern. |
| `docs/01_architecture/adapters.md` | One paragraph: UBI uses `SearchAdapter.search_batch` + `get_schema` — no new adapter methods. Cross-link to umbrella spec §14. |
| `docs/01_architecture/llm-orchestration.md` | One subsection: "Hybrid UBI + LLM fill" — same `rate_query_batch` callsite as judgment generation; same budget gate. |
| `docs/01_architecture/data-model.md` §"judgments" + §"judgment_lists" | (a) `source='click'` now in use (was reserved); (b) `_SourceBreakdown` invariant evolution to `{llm, human, click}`; (c) `judgment_lists.generation_params` JSONB column documented; (d) UBI calibration JSONB shape `{coverage_pct, head_pairs, tail_pairs, position_bias_prior_id, llm_fill_calls?, ambiguous_query_skip_count, sparse_query_skip_count}` alongside the existing LLM shape. |
| `docs/04_security/llm-data-flow.md` | New "Hybrid UBI + LLM fill" subsection: what data leaves the cluster on a hybrid call (same `query_text` + truncated doc body; only for below-threshold pairs). |
| `docs/05_quality/testing.md` | Note the new `tests/integration/services/test_ubi_reader_no_writes.py` enforcement pattern (mock HTTP transport, assert zero write-shaped calls). |

**Tasks**

1. Write the runbook end-to-end. Cite the OpenSearch UBI plugin repo + the o19s ES fork + the Solr `solr.UBIComponent` reference guide. Include the standard troubleshooting matrix (per spec §8.5 codes).
2. Add the 3 FAQ entries with anchors. Use markdown bullet structure matching the existing `judgments` entries.
3. Add tutorial Step 7. Order: after the existing final step (likely the "review the digest" step — verify at impl time). Title: "Step 7 (optional) — Upgrade your judgment list to UBI." Body walks the operator through opening the dialog, selecting Hybrid, viewing the value-delta card.
4. Patch umbrella spec §706 + §724 + §14 per the audit (in-place edits — no preservation of old text per the user's "no legacy preservation" memory).
5. Add the api-conventions one-liner.
6. Add the adapters paragraph.
7. Add the llm-orchestration subsection.
8. Patch data-model §"judgments" + §"judgment_lists".
9. Add the llm-data-flow subsection.
10. Add the testing.md note.

**Definition of Done (DoD)**

- [ ] All 10 doc files merged in this PR.
- [ ] Tutorial completes successfully on both paths (LLM-only AND optional Step 7 against a seeded UBI cluster) — verified manually before merge.
- [ ] Runbook cross-references resolve (no dead links).
- [ ] FAQ entries deep-linkable via `/guide/faq#<anchor>`.

---

### Story 5.2 — E2E suite + seed helper (FR-8 + spec §14 E2E rule)

**Outcome:** Four UBI E2E specs run mandatory in CI against the existing OpenSearch service container, seeded via `tests/e2e/helpers/seed_ubi.ts`.

**New files**

| File | Purpose |
|---|---|
| `ui/tests/e2e/helpers/seed_ubi.ts` | `seedUbiQueries(opensearchUrl, queries)` + `seedUbiEvents(opensearchUrl, events)` helpers. Writes the standardized `ubi_queries` + `ubi_events` index shapes directly via the OpenSearch HTTP API (bypasses RelyLoop's backend — RelyLoop never writes UBI, only reads it). |
| `ui/tests/e2e/ubi-onramp-rung-0.spec.ts` | Rung_0 cluster: nudge surfaces; dismiss persists per `cluster_id`; method picker defaults to `llm`; submit routes to LLM endpoint. |
| `ui/tests/e2e/ubi-onramp-rung-3.spec.ts` | Rung_3 cluster: picker defaults to `ctr_threshold`; submit → 202 → polls list → completes with `source=click` rows. |
| `ui/tests/e2e/ubi-hybrid-mode.spec.ts` | Rung_1 cluster: picker defaults to `hybrid_ubi_llm`; sparse-data card surfaces; submit succeeds; list detail shows mixed `source_breakdown` and value-delta vs prior LLM list. |
| `ui/tests/e2e/ubi-source-filter.spec.ts` | Operator filters judgment-list by `source=click` then `source=llm` in the UI; both views render correctly. |

**Tasks**

1. Implement `seed_ubi.ts` helpers:
   - `seedUbiQueries(opensearchUrl, queries)`: writes records of shape `{query_id, timestamp, user_query, application, ...}` via `POST {opensearchUrl}/ubi_queries/_doc/{query_id}` (and creates the index on first call with the canonical mapping). Application is set to the test target name for scoping.
   - `seedUbiEvents(opensearchUrl, events)`: writes records `{query_id, doc_id, event_type, timestamp, position, dwell_seconds}` via `POST {opensearchUrl}/ubi_events/_doc/{auto_id}`. Same scoping convention.
2. Each spec follows the project's E2E rule (real backend, no `page.route()` mocking). Pattern: setup via API helpers (register cluster, create query-set + queries + LLM template) → seed UBI via OpenSearch direct → navigate via `page` → assert browser-visible state.
3. The rung_3 spec creates ~10 queries × ~5 docs each × ~50 impressions + ~20 clicks per pair so corrected CTR puts each pair at rating ≥ 1.
4. The rung_1 spec creates ~10 queries × ~5 docs each × ~5 impressions per pair (below `min_impressions_threshold=100` total) → triggers the sparse-data card.
5. The source-filter spec reuses the hybrid-mode list (cross-spec dependency via a fixture or in-test setup).
6. Mark all 4 specs in the @stable Playwright tag set so the existing `make smoke` / `cd ui && pnpm test:e2e:stable` job picks them up.

**Definition of Done (DoD)**

- [ ] All 4 E2E specs green in CI against the existing OpenSearch service container.
- [ ] No `page.route()` calls in any of the 4 specs (verified via grep in CI lint step).
- [ ] `seed_ubi.ts` helpers are reusable across all 4 specs without copy-paste.
- [ ] Nudge dismissal persistence verified via real `localStorage` (NOT mocked).
- [ ] The hybrid-mode spec creates BOTH the LLM-only prior list AND the new UBI list, then asserts the value-delta card text contains both list names.

---

## UI Guidance (frontend-facing work in Epic 4)

### Reference: current component structure

**File: `ui/src/components/query-sets/generate-judgments-dialog.tsx`** (140 lines)

Current section structure:
- Imports + interface declarations (lines 1–35)
- `DEFAULT_RUBRIC` constant (lines 37–44)
- Component body with `useForm`, `useGenerateJudgments`, `useTemplates` hooks (lines 46–86)
- JSX render with `<Dialog>` → `<DialogContent>` → `<DialogHeader>` → `<form>` with 4 form fields (name, target, current_template_id, rubric) + `<DialogFooter>` (lines 88–138)

Current state variables:
- `submitting: boolean` (line 54)
- React Hook Form's `form` with `name`, `description`, `target`, `current_template_id`, `rubric` (lines 55–63)

Current props:
- `open: boolean`, `onOpenChange: (open: boolean) => void`, `clusterId: string`, `querySetId: string` (lines 30–35)

**Insertion points for Story 4.2:**

- Add new form fields to `useForm` defaults at lines 56–62: `method: 'llm', since: <30d ago>, until: undefined, llm_fill_threshold: 20`.
- Above the existing `<form>` opening (around line 97), insert `{rung === 'rung_0' && <UbiOnrampNudge clusterId={clusterId} engineType={cluster.engine_type} />}`.
- After the "Judgment list name" `<div>` (line 105), insert the **Method** `<Select>`.
- After the Method `<Select>`, insert `{rung === 'rung_1' && method !== 'hybrid_ubi_llm' && <UbiSparseDataCard onSwitchToHybrid={() => form.setValue('method', 'hybrid_ubi_llm')} />}`.
- After the existing "Target index / collection" (line 109), insert window controls when `method !== 'llm'`.
- After the template select (line 121), insert LLM-fill threshold input when `method === 'hybrid_ubi_llm'`.
- The rubric `<div>` (lines 123–126) is conditionally rendered when `method ∈ {'llm', 'hybrid_ubi_llm'}`.

**File: `ui/src/components/dashboard/demo-data-banner.tsx`** (164 lines) — pattern source for `<UbiOnrampNudge>`

Key idioms to copy:
- SSR-safe hydration via `useSyncExternalStore` (lines 70–74)
- `getDismissedSnapshot` / `getDismissedServerSnapshot` (lines 51–63)
- Same-tab dismissal via separate `useState` (lines 78–80)
- Tooltip on dismiss button (lines 143–159)

### Analogous markup patterns

**Method `<Select>`** — analogous to other form selects in the project. The form-select discipline lint guard at `ui/src/__tests__/components/common/form-select-discipline.test.tsx` requires the `*_VALUES.map(...)` pattern. Inspect a recent compliant example (e.g., `ui/src/components/studies/*` after `chore_form_dropdown_primitive` shipped) and copy the exact shape.

```tsx
{/* Method picker — JUDGMENT_GENERATION_METHOD_VALUES.map(...) pattern per chore_form_dropdown_primitive */}
<div className="space-y-1.5">
  <Label htmlFor="gen-method">
    Method
    <HelpPopover glossaryKey="judgment.converter" />
  </Label>
  <Select
    value={form.watch('method')}
    onValueChange={(v) => form.setValue('method', v as JudgmentGenerationMethod)}
  >
    <SelectTrigger id="gen-method"><SelectValue /></SelectTrigger>
    <SelectContent>
      {JUDGMENT_GENERATION_METHOD_VALUES.map((method) => (
        <SelectItem key={method} value={method}>
          {METHOD_LABELS[method]}
        </SelectItem>
      ))}
    </SelectContent>
  </Select>
</div>
```

Where `METHOD_LABELS: Record<JudgmentGenerationMethod, string> = { llm: 'LLM-as-judge', ctr_threshold: 'UBI (click-through)', dwell_time: 'UBI (dwell-time)', hybrid_ubi_llm: 'Hybrid UBI + LLM' }` is defined alongside the consumer (Story 4.2). Inline help (per-option `HelpPopover`) is rendered as a row of supplementary text below the picker when the highlighted option changes — verify whether Radix `<SelectItem>` accepts children rich enough to host an inline popover during implementation; if not, fall back to a description block beneath the select.

**`<UbiOnrampNudge>`** — copy the `<DemoDataBanner>` markup structure (lines 110–163 of `demo-data-banner.tsx`):

```tsx
{/* UBI on-ramp nudge — adapted from DemoDataBanner (ui/src/components/dashboard/demo-data-banner.tsx) */}
<Card
  role="region"
  aria-labelledby="ubi-nudge-heading"
  data-testid="ubi-onramp-nudge"
  className="border-blue-200 bg-blue-50/50 dark:border-blue-900/40 dark:bg-blue-950/20"
>
  <CardHeader>
    <CardTitle id="ubi-nudge-heading" className="text-base">
      Enable real user signals
    </CardTitle>
  </CardHeader>
  <CardContent className="space-y-3">
    <p className="text-sm">
      {ENGINE_NUDGE_COPY[engineType]}
    </p>
    <div className="flex items-center gap-3">
      <Link
        href={ENGINE_RUNBOOK_LINKS[engineType]}
        data-testid="ubi-nudge-runbook-cta"
        className="text-sm font-medium text-blue-600 underline-offset-4 hover:underline"
      >
        Install instructions →
      </Link>
      <Button variant="outline" size="sm" onClick={handleDismiss} data-testid="ubi-nudge-dismiss">
        Dismiss
      </Button>
    </div>
  </CardContent>
</Card>
```

Where `ENGINE_NUDGE_COPY` and `ENGINE_RUNBOOK_LINKS` are defined inline:

```ts
const ENGINE_NUDGE_COPY: Record<EngineType, string> = {
  elasticsearch: "Install the o19s ES UBI fork to start capturing click + dwell behavior — RelyLoop reads it as click-derived judgments without needing the LLM.",
  opensearch: "Install the OpenSearch UBI plugin to start capturing click + dwell behavior — RelyLoop reads it as click-derived judgments without needing the LLM.",
  // `solr` arm is dark until infra_adapter_solr ships (spec §3 Out of scope).
};
const ENGINE_RUNBOOK_LINKS: Record<EngineType, string> = {
  elasticsearch: "/guide/runbooks/ubi-judgment-generation#elasticsearch",
  opensearch: "/guide/runbooks/ubi-judgment-generation#opensearch",
};
```

**`<UbiSparseDataCard>`** — inline `<Alert>` or `<Card>` with primary action button:

```tsx
{/* Sparse-data recommendation card */}
<Card
  role="region"
  aria-labelledby="ubi-sparse-card-heading"
  data-testid="ubi-sparse-data-card"
  className="border-amber-200 bg-amber-50/50 dark:border-amber-900/40 dark:bg-amber-950/20"
>
  <CardHeader>
    <CardTitle id="ubi-sparse-card-heading" className="text-sm">
      Your UBI data is sparse — consider Hybrid mode
    </CardTitle>
  </CardHeader>
  <CardContent>
    <p className="text-sm">
      Only ~{Math.round(coveragePct * 100)}% of your query set has dense UBI signal.
      Hybrid rates that head and the LLM fills the rest.
    </p>
    <Button
      type="button"
      variant="default"
      size="sm"
      onClick={onSwitchToHybrid}
      data-testid="ubi-sparse-switch-to-hybrid"
      className="mt-2"
    >
      Switch to Hybrid UBI + LLM
    </Button>
  </CardContent>
</Card>
```

**`<ValueDeltaCard>`** — coverage and delta variants. Inline below the source-breakdown on the judgment-list detail page.

```tsx
{/* Value-delta card — coverage-only OR coverage + LLM-list comparison */}
<Card data-testid="value-delta-card" className="border-green-200 bg-green-50/50">
  <CardHeader>
    <CardTitle className="text-base">What real signals bought you</CardTitle>
  </CardHeader>
  <CardContent>
    {priorList ? (
      <p className="text-sm">
        This UBI list covered <strong>{Math.round(coveragePct * 100)}%</strong> of recent traffic
        with <strong>{judgmentCount}</strong> ratings — the previous LLM list (
        <Link href={`/judgments/${priorList.id}`}>{priorList.name}</Link>) rated{' '}
        <strong>{priorList.judgment_count}</strong> pairs on a snapshot.
      </p>
    ) : (
      <p className="text-sm">
        This UBI list covered <strong>{Math.round(coveragePct * 100)}%</strong> of recent traffic
        with <strong>{judgmentCount}</strong> ratings.
      </p>
    )}
  </CardContent>
</Card>
```

**`<AmbiguousSkipRecoveryCard>`**:

```tsx
{/* Ambiguous-skip recovery — one-shot re-run with most_recent tiebreaker */}
<Card
  role="region"
  data-testid="ambiguous-skip-recovery-card"
  className="border-amber-200 bg-amber-50/50"
>
  <CardHeader>
    <CardTitle className="text-base">Skipped {skipCount} queries</CardTitle>
  </CardHeader>
  <CardContent>
    <p className="text-sm">
      We skipped {skipCount} queries because the same UBI <code>user_query</code> matched more than
      one entry in your query set, and your <code>mapping_strategy</code> is{' '}
      <code>reject</code>.
    </p>
    <Button
      type="button"
      onClick={handleRerunWithMostRecent}
      data-testid="ambiguous-skip-rerun-most-recent"
      className="mt-2"
    >
      Re-run with <code>most_recent</code> tiebreaker
    </Button>
  </CardContent>
</Card>
```

### Layout and structure

- Dialog body grows vertically; method picker is the new primary decision and sits between the name/target inputs and the template/rubric inputs.
- The nudge + sparse-data card use the existing `<Card>` primitive with `border-*-200 bg-*-50/50` muted backgrounds (matching the `<DemoDataBanner>` pattern).
- Rung badge on cluster cards is a text-only inline element (`<span className="text-xs text-muted-foreground">UBI: rung_N</span>` or similar) — no color-only meaning. Tooltip wraps the badge.

### Confirmation/modal dialog pattern

No new modal dialogs are introduced. The existing generate-judgments dialog grows in place. Confirmation guards happen on the chat-agent side (Story 3.4) via the existing orchestrator confirmation pattern — no UI-side confirmation primitive needed.

### Visual consistency table

| New UI element | CSS pattern source | Notes |
|---|---|---|
| Method `<Select>` | `chore_form_dropdown_primitive` shipped pattern | Inspect a recent compliant component (e.g., studies-related form selects) for exact JSX. Lint guard at form-select-discipline.test.tsx is the enforcement. |
| `<UbiOnrampNudge>` | `demo-data-banner.tsx` SSR-safe pattern | Blue-tinted muted card. Dismiss button + runbook link side-by-side. |
| `<UbiSparseDataCard>` | Same Card primitive, amber tint | Inline action button to flip the picker. |
| `<UbiRungBadge>` | Existing text-only badge pattern (verify which) | No color-only meaning; tooltip wraps the badge. |
| `<ValueDeltaCard>` | Card primitive, green-tint variant | Coverage + delta semantics in plain text. |
| `<AmbiguousSkipRecoveryCard>` | Card primitive, amber-tint variant | Mirrors the sparse-data card visually so operators read them as related "recovery affordances". |

### Component composition

- `<UbiOnrampNudge>` and `<UbiSparseDataCard>` are extracted components (Story 4.2 new files) — they have non-trivial dismiss / re-render logic that benefits from isolation + reuse.
- `<UbiRungBadge>` is extracted (Story 4.1) — used in ONE place (generate-judgments dialog top). Cluster list/detail pages do NOT render it per cycle-3 plan-review fix `readiness-snapshot-badge-contract-drift` (spec FR-7 requires `?query_set_id`+`?target` which those pages don't have).
- `<ValueDeltaCard>` and `<AmbiguousSkipRecoveryCard>` are extracted (Story 4.3) — clean isolation of conditional rendering + variant logic.
- Method labels (`METHOD_LABELS`) are defined inline in `generate-judgments-dialog.tsx` — small enough to not warrant extraction.

### Interaction behavior table

| User action | Frontend behavior | API call |
|---|---|---|
| Opens generate-judgments dialog | `useUbiReadiness(clusterId, querySetId, target)` fires | `GET /api/v1/clusters/{cluster_id}/ubi-readiness?query_set_id=&target=` |
| Selects "Hybrid UBI + LLM" from picker | Picker value updates; rubric textarea + LLM-fill threshold input become visible | none (local state) |
| Clicks "Switch to hybrid" on sparse-data card | Picker value mutates to `hybrid_ubi_llm`; card dismisses; rubric/threshold inputs appear | none (local state) |
| Submits dialog with method=`llm` | Calls existing `useGenerateJudgments()` mutation | `POST /api/v1/judgments/generate` |
| Submits dialog with method ∈ UBI three | Calls new `useGenerateJudgmentsFromUbi()` mutation | `POST /api/v1/judgments/generate-from-ubi` |
| Dismisses on-ramp nudge | `safeLocalStorageSet('relyloop.ubi-onramp-nudge.dismissed:{cluster_id}', '1')` | none |
| Opens UBI/hybrid judgment-list detail | Detail page renders + `useJudgmentLists({query_set_id, …})` query fires for the prior-LLM-list lookup | `GET /api/v1/judgment-lists/{id}` + `GET /api/v1/judgment-lists?query_set_id=&sort=created_at:desc` |
| Clicks "Re-run with `most_recent`" on recovery card | Calls `useGenerateJudgmentsFromUbi()` with the original body + override | `POST /api/v1/judgments/generate-from-ubi` |

### Handler function patterns

```tsx
// Submit routing — method `llm` → LLM endpoint, else → UBI endpoint
function submit(values: GenerateFormValues) {
  setSubmitting(true);
  if (values.method === 'llm') {
    generateLlm.mutate(
      {
        name: values.name,
        description: values.description || null,
        query_set_id: querySetId,
        cluster_id: clusterId,
        target: values.target,
        current_template_id: values.current_template_id,
        rubric: values.rubric,
      },
      {
        onSuccess: () => { toast.success('LLM generation started'); form.reset(); onOpenChange(false); },
        onSettled: () => setSubmitting(false),
      },
    );
  } else {
    generateUbi.mutate(
      {
        name: values.name,
        description: values.description || null,
        query_set_id: querySetId,
        cluster_id: clusterId,
        target: values.target,
        since: values.since,
        until: values.until || null,
        converter: values.method,  // 'ctr_threshold' | 'dwell_time' | 'hybrid_ubi_llm'
        llm_fill_threshold: values.method === 'hybrid_ubi_llm' ? values.llm_fill_threshold : null,
        mapping_strategy: 'reject',
        current_template_id: values.method === 'hybrid_ubi_llm' ? values.current_template_id : null,
        rubric: values.method === 'hybrid_ubi_llm' ? values.rubric : null,
      },
      {
        onSuccess: () => { toast.success('UBI generation started'); form.reset(); onOpenChange(false); },
        onSettled: () => setSubmitting(false),
      },
    );
  }
}

// Nudge dismissal — SSR-safe via useSyncExternalStore (copy DemoDataBanner pattern)
function handleDismiss(): void {
  setSessionDismissed(true);
  safeLocalStorageSet(`relyloop.ubi-onramp-nudge.dismissed:${clusterId}`, '1');
}

// Re-run with most_recent tiebreaker — reconstructs the prior request body from generation_params
function handleRerunWithMostRecent(): void {
  if (!detail.generation_params) return;
  const priorParams = detail.generation_params;
  generateUbi.mutate(
    {
      ...priorParams,
      name: `${detail.name}-most-recent`,
      mapping_strategy: 'most_recent',
    },
    { onSuccess: (result) => { navigate(`/judgments/${result.judgment_list_id}`); } },
  );
}
```

### Information architecture placement

Per spec §11 IA:
- Method picker lives inside the existing "Generate judgments" dialog opened from the query-sets detail page (`ui/src/app/query-sets/[id]/page.tsx`). No new route, no new tab.
- Rung badge — surfaced ONLY inside the generate-judgments dialog (where the parent has the required `query_set_id` + `target` to call `useUbiReadiness`). Cluster list/detail pages do NOT show it (cycle-3 plan-review constraint per spec FR-7). Operators discover UBI when they open the dialog — same surface where they choose the converter.
- Value-delta card on judgment-list detail — the "payoff" surface. Operators see it after generation completes.

No changes to the sidebar navigation.

### Tooltips and contextual help

Per spec §11 tooltip table — every entry has a corresponding glossary key added in Story 4.1. The dialog's method picker each option uses `<HelpPopover glossaryKey="judgment.converter.{llm|ubi|hybrid}">` per the existing `feat_contextual_help` idiom. Inline helper text under the LLM-fill threshold input uses a plain `<p className="text-xs text-muted-foreground">` (not glossary-backed — too feature-specific to warrant a glossary entry).

Required source-of-truth comments in `glossary.ts`:
- `judgment.converter` → `// Source-of-truth: backend/app/api/v1/schemas.py UbiConverterKind + JudgmentGenerationMethodWire`
- `judgment.converter.llm` → `// Source-of-truth: backend/app/api/v1/schemas.py JudgmentGenerationMethodWire`
- `judgment.converter.ubi` → `// Source-of-truth: backend/app/api/v1/schemas.py UbiConverterKind`
- `judgment.converter.hybrid` → `// Source-of-truth: backend/app/api/v1/schemas.py UbiConverterKind`
- `cluster.ubi_readiness` → `// Source-of-truth: backend/app/api/v1/schemas.py UbiReadinessRungWire`

### Legacy behavior parity

**No legacy behavior parity table required.** No user-facing component >100 LOC is deleted or migrated in this plan. The existing `<GenerateJudgmentsDialog>` (140 LOC) grows in place; all existing form fields + submit behavior are preserved on the LLM path (verified by the existing dialog vitest test continuing to pass + the new vitest cases extending it).

### Client-side persistence

- **`localStorage`** — Nudge dismissal key `relyloop.ubi-onramp-nudge.dismissed:{cluster_id}` persists indefinitely; re-surfaces only when the underlying rung is still 0 (the `useUbiReadiness` hook is the trigger gate). Per D-7.
- **React state only** — Method picker, window controls, LLM-fill threshold — all transient form state; reset on dialog close.

DoD: persistence scope matches the task description — localStorage = "persists across visits for the same cluster" (verified in the rung-0 E2E spec by reloading the page after dismiss).

---

## 3) Testing workstream

### 3.1 Unit tests

- Location: `backend/tests/unit/`
- Scope: pure-domain UBI library (features, converters, position-bias prior), Pydantic schema validation, source-breakdown evolution
- Tasks:
  - [ ] `tests/unit/domain/ubi/test_features.py` — feature aggregation, position-bias correction edge cases (zero impressions, single-impression queries, NULL dwell, NULL conversion)
  - [ ] `tests/unit/domain/ubi/test_converter.py` — `CtrThresholdConverter`, `DwellTimeThresholdConverter`, `HybridUbiLlmConverter` rating math (boundary values, threshold-crossing inputs, all-pairs-below-threshold hybrid → 100% LLM-fill, head-only hybrid → 0% LLM-fill)
  - [ ] `tests/unit/domain/ubi/test_position_bias_prior.py` — valid prior JSON, missing file → uninformed, malformed JSON → WARN + uninformed
  - [ ] `tests/unit/domain/ubi/test_converter_no_openai_import.py` — ast scan asserting `HybridUbiLlmConverter` doesn't import `openai` or instantiate `AsyncOpenAI`
  - [ ] `tests/unit/api/test_schemas_ubi.py` — `CreateJudgmentListFromUbiRequest` validator (hybrid requires template+rubric; non-hybrid rejects them; window > 90 days → ValueError; converter enum validates exactly the 3 wire values)
  - [ ] `tests/unit/api/test_source_breakdown_evolution.py` — `_SourceBreakdown(llm, human, click)` field access + JSON serialization
- DoD:
  - [ ] All critical branches covered; tests deterministic

### 3.2 Integration tests

- Location: `backend/tests/integration/`
- Scope: DB-backed flows, dispatcher preflight, worker pipeline, readiness service, no-cluster-writes invariant
- Tasks:
  - [ ] `tests/integration/services/test_ubi_reader.py` — stubbed `adapter.search_batch` returning canned UBI payloads → expected `FeatureVec` map
  - [ ] `tests/integration/services/test_ubi_reader_no_writes.py` — HTTP-transport mock; assert zero `PUT`/`DELETE`/`_bulk`/`_update`/`_doc`/`_create` calls during full reader exercise
  - [ ] `tests/integration/services/test_ubi_readiness.py` — rung_0/1/2/3 classification per canned `_count` results; Redis cache hit
  - [ ] `tests/integration/services/test_agent_judgments_dispatch_ubi.py` — all preflight branches of `start_ubi_judgment_generation`; behavior parity for refactored `start_judgment_generation`
  - [ ] `tests/integration/api/test_judgments_generate_from_ubi.py` — endpoint end-to-end with stubbed `UbiReader` + adapter; `generation_params` JSONB populated
  - [ ] `tests/integration/api/test_judgments_filter_click_widening.py` — `?source=click` returns matching rows; backward-compat: `?source=human` and `?source=llm` unchanged
  - [ ] `tests/integration/api/test_judgment_list_detail_breakdown.py` — hybrid list returns `{llm: N, human: M, click: K}`; LLM-only list returns `{llm: N, human: M, click: 0}`
  - [ ] `tests/integration/api/test_clusters_ubi_readiness.py` — rung_0/1/2/3 paths; 503 on `ClusterUnreachableError`; 422 on missing query params
  - [ ] `tests/integration/workers/test_generate_judgments_from_ubi.py` — clean loop / hybrid / resume-skip / ambiguous-skip / `UbiInsufficientDataError` fallback / `BudgetExceededError` mid-hybrid
  - [ ] `tests/integration/agent/test_generate_judgments_from_ubi_tool.py` — tool dispatch round-trip + confirmation guard + registry drift negative test
  - [ ] `tests/integration/db/test_migration_0021_generation_params.py` — column existence + nullable + round-trip
- DoD:
  - [ ] Happy + critical failure paths covered for every new endpoint and worker
  - [ ] All integration tests pass against the project's existing service-container Postgres + ES + OpenSearch in CI

### 3.3 Contract tests

- Location: `backend/tests/contract/`
- Scope: endpoint shape lock + every error code envelope
- Tasks:
  - [ ] `tests/contract/test_judgments_generate_from_ubi_shape.py` — 202 success shape; each of the 13 error codes returns the structured envelope (`UBI_NOT_ENABLED` 412, `UBI_INSUFFICIENT_DATA` 422, `UBI_WINDOW_TOO_LARGE` 422, `VALIDATION_ERROR` 422, `CLUSTER_NOT_FOUND` 404, `QUERY_SET_NOT_FOUND` 404, `TEMPLATE_NOT_FOUND` 404, `JUDGMENT_LIST_NAME_TAKEN` 409, `OPENAI_NOT_CONFIGURED` 503, `LLM_PROVIDER_INCAPABLE` 503, `UNKNOWN_MODEL_PRICING` 503, `OPENAI_BUDGET_EXCEEDED` 503)
  - [ ] `tests/contract/test_judgment_list_detail_source_breakdown_v2.py` — `_SourceBreakdown` is 3-key on every list; OpenAPI schema lock
  - [ ] `tests/contract/test_clusters_ubi_readiness_shape.py` — 200 shape; 404 / 422 / 503 envelopes
  - [ ] `tests/contract/test_agent_tool_inventory.py` — extend to include `generate_judgments_from_ubi`; verify the registry triad consistency
- DoD:
  - [ ] No new or evolved endpoint without contract coverage

### 3.4 E2E tests

- Location: `ui/tests/e2e/`
- Scope: real-backend Playwright via the existing OpenSearch service container + new `seed_ubi.ts` helpers
- **Rule:** No `page.route()` mocking. Setup via API helpers; assertions via `page` object. Per spec §14.
- Tasks (own Story 5.2):
  - [ ] `tests/e2e/ubi-onramp-rung-0.spec.ts`
  - [ ] `tests/e2e/ubi-onramp-rung-3.spec.ts`
  - [ ] `tests/e2e/ubi-hybrid-mode.spec.ts`
  - [ ] `tests/e2e/ubi-source-filter.spec.ts`
- DoD:
  - [ ] All 4 E2E specs green in CI against the existing OpenSearch service container
  - [ ] No `page.route()` calls (grep gate)
  - [ ] `seed_ubi.ts` helpers reusable across all specs

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/contract/test_judgments_*` | Asserts `_SourceBreakdown` shape `{llm, human}` | (verify at impl time) | Update to assert 3-key shape per FR-10 |
| `backend/tests/contract/test_judgments_filter*` | Asserts `?source=click` → 422 VALIDATION_ERROR | (verify at impl time) | Invert: assert `?source=click` returns 200 with matching rows |
| `backend/tests/integration/agent/test_tool_registry*` | Enumerates `TOOLS` / `TOOL_REGISTRY` / `TOOL_ARG_MODELS` | (verify at impl time) | Extend to include `generate_judgments_from_ubi` |
| `backend/tests/integration/workers/test_all_resume_sweep*` | Boot-time resume sweep | (verify at impl time) | Extend to assert UBI rows with `generation_params IS NOT NULL` get re-enqueued via `generate_judgments_from_ubi` |
| `ui/src/__tests__/components/query-sets/generate-judgments-dialog.test.tsx` | Existing 4-field form submit | (verify at impl time) | Extend with new method-picker / window / threshold / nudge / sparse-card / submit-routing cases per Story 4.2 |
| `ui/src/__tests__/lib/enums-source-of-truth.test.ts` (verify path) | Asserts source-of-truth comments | — | Verify the new arrays pass the existing regex; extend if not |
| `ui/src/__tests__/components/common/form-select-discipline.test.tsx` | Rejects inline `<SelectItem value="...">` for wire-value enums | — | New method `<Select>` must comply (`JUDGMENT_GENERATION_METHOD_VALUES.map(...)`) |

### 3.5 Migration verification

- [ ] `migrations/versions/0021_judgment_lists_generation_params.py` includes `downgrade()` implementation
- [ ] `alembic upgrade head` succeeds
- [ ] Round-trip verified: `alembic downgrade -1 && alembic upgrade head`
- [ ] DB revision guard at API startup (MVP2 reminder per CLAUDE.md "Activates at MVP2"): if the guard isn't yet active, **defer to** `infra_db_revision_guard` (verify the feature exists or capture as idea); if active, ensure boot succeeds with the new head.

### 3.6 CI gates

- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `cd ui && pnpm test`
- [ ] `cd ui && pnpm test:e2e:stable` (the 4 UBI specs included)
- [ ] `make lint && make typecheck`

---

## 4) Documentation update workstream

### 4.0 Core context files

- **`state.md`** — bump Alembic head to `0021_judgment_lists_generation_params`; add `feat_ubi_judgments` to "Last 5 merges"; update "Current branch" + "In flight" / "Queued"; MVP2 backlog drops by 1.
- **`architecture.md`** — extend the "Where the code lives" tree to include `backend/app/services/ubi_reader.py`, `backend/app/services/ubi_readiness.py`, `backend/app/domain/ubi/`. Add a "Critical flows" cross-link for "UBI judgment generation (POST → preflight → worker → calibration)".
- **`CLAUDE.md`** — Feature Status section: add `feat_ubi_judgments` to MVP2 features. No new conventions or absolute rules (the existing rules cover the LLM-fill path).

### 4.1 Architecture docs (`docs/01_architecture/`)

Per Story 5.1: api-conventions, adapters, llm-orchestration, data-model. (One-line / one-paragraph / one-subsection updates per file.)

### 4.2 Product docs (`docs/02_product/`)

No update — UBI is opt-in progressive enhancement; no user-story flips required beyond the tutorial Step 7 addition (which lives in `docs/08_guides/`).

### 4.3 Runbooks (`docs/03_runbooks/`)

Per Story 5.1: new `ubi-judgment-generation.md`.

### 4.4 Security docs (`docs/04_security/`)

Per Story 5.1: `llm-data-flow.md` gets the "Hybrid UBI + LLM fill" subsection.

### 4.5 Quality docs (`docs/05_quality/`)

Per Story 5.1: `testing.md` documents the no-cluster-writes integration test pattern.

**Documentation DoD**

- [ ] `state.md`, `architecture.md`, `CLAUDE.md` updated in the finalization step
- [ ] All 10 doc files in Story 5.1 merged
- [ ] Tutorial Step 7 walks the operator through the value-delta upgrade end-to-end

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- Centralize the dispatcher preflight + INSERT + Arq enqueue logic (Story 2.2) so `start_judgment_generation` (LLM) and `start_ubi_judgment_generation` (UBI) share helpers. Duplication is the exact failure the shared dispatcher pattern was created to prevent.
- No speculative redesign.

### 5.2 Planned refactor tasks

- [ ] Backend refactor (Story 2.2): factor 5 shared helpers in `backend/app/services/agent_judgments_dispatch.py` (`_resolve_cluster_query_set`, `_check_consistency`, `_check_llm_preflight`, `_check_oversized_query_set`, `_insert_generating_list_and_enqueue`).
- [ ] Backend refactor (Story 2.3): evolve `source_breakdown_for_list` to return all 3 keys; remove the cycle-2 F6 "click folds into human" decision note.
- [ ] No frontend refactor — the dialog grows in place; no extraction beyond the three new components (nudge, sparse card, badge).
- [ ] No dead-code removal — `UbiReader._probe_enabled` reused by both `start_ubi_judgment_generation` preflight U-C and `classify_rung` (single probe shape across both call sites — built that way, no later cleanup needed).

### 5.3 Refactor guardrails

- [ ] Behavioral parity proven by tests — existing `start_judgment_generation` contract tests pass without modification (Story 2.2 DoD).
- [ ] `make lint` + `make typecheck` green.
- [ ] No expansion of product scope — refactor strictly enables the new dispatcher without changing LLM-path behavior.
- [ ] Track any discovered debt as `chore_*` idea files per CLAUDE.md "Tangential discoveries" rule.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_llm_judgments` (shipped 2026-05-11) | Stories 2.2, 3.3 | Implemented | N/A — MVP1 precondition |
| `feat_chat_agent` shipped tool-registry triad pattern | Story 3.4 | Implemented | N/A |
| `feat_contextual_help` shipped `HelpPopover` | Stories 4.1, 4.2 | Implemented | N/A |
| `chore_form_dropdown_primitive` shipped form-select discipline lint guard | Story 4.2 | Implemented (verify at impl time — should be shipped by now per state.md) | If not shipped: method picker risks regressing to inline `<SelectItem>`; ship discipline manually + capture as idea if missing |
| OpenSearch UBI plugin in operator's CI container | Story 5.2 E2E | Not assumed — E2E seeds the indices directly via HTTP, bypassing the plugin's write path | N/A — RelyLoop reads UBI; the standardized index schema is what matters |
| `infra_adapter_solr` (planned MVP2) | Capability B Solr arm only | Planned (sibling feature) | If missed: the Solr nudge arm stays dark; ES + OpenSearch UBI ship unaffected |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Hybrid converter callback signature mismatches `rate_query_batch`'s expected shape (per_query vs batched) | M | M | Story 1.2 implements `_make_llm_rate_callback` carefully; integration test in Story 3.3 exercises end-to-end. If signature doesn't fit, the callback becomes a thin per-pair adapter — small extra code, no contract change. |
| Adapter's `search_batch` against `ubi_events` scrolls too slowly on large clusters | M | M | Cap `max_queries` at 5000 default; document scaling considerations in the runbook. Future optimization (server-side aggregation) is additive and out of scope for MVP2. |
| Sparse-data card client-side detection (`useUbiReadiness().rung === 'rung_1'`) races with the actual server-side coverage check | L | L | Server-side preflight U-D2 is the authoritative gate; the card is UX-only and doesn't gate submit. Race produces a brief "shows card → submit → success" stutter at worst. |
| Method picker `<HelpPopover>` integration with Radix `<Select>` doesn't compose cleanly | L | L | Fallback to a description block under the picker; verify during impl. |
| Worker terminal `failed` race between preflight U-D2 and worker `read_features` | L | L | Documented as race-condition fallback (FR-1 + FR-5); essentially impossible in practice (the same data window can't disappear between two reads seconds apart). Caught by `UbiInsufficientDataError` and surfaced cleanly. |
| GPT-5.5 finds new structural issues in the impl plan that the spec didn't catch | M | M | Run cross-model review per Step 6 below; apply fixes; cap at 3 cycles per skill rules. |
| Solr arm of Capability B is dark code that grows stale before `infra_adapter_solr` ships | L | L | Capture as `chore_ubi_nudge_solr_arm_activation` idea file when `infra_adapter_solr` lands. |
| `_SourceBreakdown` shape evolution breaks an external OpenAPI consumer | L | M | Spec D-1 confirmed only the project's own UI + contract tests consume the shape. Re-verify via `grep _SourceBreakdown` at impl time; if any consumer surfaces, escalate before merging. |

### Failure mode catalog

| Failure mode | Trigger | Expected behavior | Recovery |
|---|---|---|---|
| `ubi_queries` index disappears mid-generation | Operator drops/renames the index during a run | Worker hits `UbiNotEnabledError` on next read → terminal `failed`, `failed_reason='UBI_NOT_ENABLED'`. | Operator re-enables UBI + re-submits the request (boot-time sweep does NOT re-enqueue `failed` rows; this is a fresh request). |
| Cluster unreachable mid-worker | Network blip / cluster restart | Per-query `search_batch` throws; the existing per-query isolation logs WARN and skips; if every query fails the list completes with `judgment_count=0` (degenerate but valid). | Operator inspects the list, re-submits if needed. |
| Hybrid-mode budget exhausted mid-loop | LLM-fill calls cross the daily budget | Worker raises `BudgetExceededError` → terminal `failed`, `failed_reason='OPENAI_BUDGET_EXCEEDED'`. Already-persisted click rows + LLM-fill rows up to the cutoff stay. | Operator raises budget OR waits for daily rollover; re-submits. |
| Position-bias prior file malformed | Operator provides bad JSON | `load_position_bias_prior` WARN-logs and returns `{}` (uninformed). Worker uses uninformed prior — corrected CTR equals raw CTR. | Operator fixes the file + redeploys; no row corruption. |
| `generation_params` JSONB column NULL on a UBI row (shouldn't happen) | Partial deploy mid-rollout | Worker bails with `_fail_list(..., 'MISSING_GENERATION_PARAMS')`. | Operator inspects, deletes the orphan row, re-submits. |
| Tool registry drift (one of 3 data structures missing the new tool) | Implementation error | Module load raises `RuntimeError` at API/worker startup — fail-fast. | Fix the registration; restart. Negative test in Story 3.4 catches this in CI. |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** (migration) — gating step. Must land + verify round-trip before any code that reads `generation_params`.
2. **Story 1.2** (domain/ubi library) — pure-Python; testable in isolation.
3. **Story 2.1** (UbiReader) + **Story 2.3** (`_SourceBreakdown` + Literals) — can run in parallel (different files).
4. **Story 2.2** (readiness + dispatcher refactor) — depends on Story 2.1 (uses `UbiReader._probe_enabled`).
5. **Story 3.1** (readiness endpoint) + **Story 3.2** (UBI generate endpoint) — both depend on Story 2.2; can run in parallel.
6. **Story 3.3** (worker) — depends on Story 1.2 (converters), Story 2.1 (reader), Story 2.2 (dispatcher for the resume sweep glue).
7. **Story 3.4** (agent tool) — depends on Story 3.2 (dispatcher); can run parallel with Story 3.3.
8. **Story 4.1** (enums + hook + badge) — depends on Story 2.3 (backend Literals); independent of the worker.
9. **Story 4.2** (dialog method picker + nudge + sparse card) — depends on Story 4.1 + Story 3.1 (readiness endpoint live) + Story 3.2 (UBI endpoint live).
10. **Story 4.3** (value-delta + recovery card) — depends on Story 3.3 (worker writes the calibration shape).
11. **Story 5.1** (docs) — can run mostly in parallel with backend stories once spec is locked.
12. **Story 5.2** (E2E suite + seed helper) — must come last (depends on everything above being live).

### Parallelization opportunities

- Stories 2.1 + 2.3 in parallel (different files, no shared state).
- Stories 3.1 + 3.2 in parallel (both depend on Story 2.2 but write to different routers).
- Stories 3.3 + 3.4 in parallel (both depend on Story 2.2/3.2; worker and agent tool are independent files).
- Story 4.1 can start as soon as Story 2.3 lands (independent of backend service implementations).
- Story 5.1 (docs) can ship in parallel with any backend stories once the contract is locked.

---

## 8) Rollout and cutover plan

- **Rollout stages:** Single stage — MVP2 ships UBI as part of the "Three-Engine + Real Signals" release alongside `infra_adapter_solr`. No feature flag (UBI is fully additive; the default LLM path is unchanged for any operator who never opens the method picker).
- **Feature flag strategy:** None.
- **Migration / cutover steps:**
  1. PR merges → CI runs `alembic upgrade head` against staging Postgres (when remote staging exists; MVP1 is local-only).
  2. Worker restarts pick up the new `generate_judgments_from_ubi` job registration via `WorkerSettings.functions`.
  3. Frontend Next.js build picks up the new components + enums.
  4. Operator-facing: no migration steps — UBI surfaces appear automatically; operators with rung_0 clusters see the nudge.
- **Reconciliation / repair strategy:** N/A — no external system integration.

---

## 9) Execution tracker

### Current sprint

- [x] Story 1.1 — Migration `0021_judgment_lists_generation_params` (commit `5acdee15`)
- [x] Story 1.2 — `domain/ubi/` package (commit `6036586a`)
- [x] Story 2.1 — `UbiReader` service
- [x] Story 2.2 — Readiness service + dispatcher refactor
- [x] Story 2.3 — `_SourceBreakdown` evolution + Literals + filter widening
- [x] Story 3.1 — `GET /api/v1/clusters/{id}/ubi-readiness` endpoint
- [x] Story 3.2 — `POST /api/v1/judgments/generate-from-ubi` endpoint
- [x] Story 3.3 — `generate_judgments_from_ubi` Arq worker
- [x] Story 3.4 — `generate_judgments_from_ubi` agent tool + orchestrator prompt update
- [x] Story 4.1 — Wire enums + `useUbiReadiness` + `<UbiRungBadge>`
- [x] Story 4.2 — Dialog method picker + nudge + sparse-data card
- [x] Story 4.3 — Value-delta card + ambiguous-skip recovery card
- [x] Story 5.1 — Operator docs (runbook + 3 FAQ + data-model + tutorial Step 11 + umbrella spec patches + api-conventions/llm-orchestration/llm-data-flow/testing one-liners). All 10 doc artifacts shipped (folded in after the Gemini-review pass per operator direction).
- [x] Story 5.2 (partial — integration tests) + [~] (E2E deferred). The 6 DB-backed integration tests (migration round-trip, worker happy/fail paths, both endpoints, detail breakdown, agent tool) shipped this PR. The 4 Playwright E2E specs + `seed_ubi.ts` helper remain deferred to `chore_ubi_e2e_suite` (needs an OpenSearch UBI-plugin Compose change + SKIP_HEAVY_CI is currently on so E2E wouldn't run in CI until ~2026-06-01).

### Blocked items

(None at plan time.)

### Done this sprint

(empty — populated during execution)

---

## 10) Story-by-Story Verification Gate

Before marking any story complete, the executing agent must attach evidence for:

- [ ] Files created/modified match story scope (cross-checked against `New files` / `Modified files` tables)
- [ ] Endpoint contract implemented exactly as documented (method/path/body/status/error code)
- [ ] Key interfaces implemented with compatible signatures (mypy strict clean)
- [ ] Required tests added/updated for all four layers where applicable
- [ ] Commands executed and passed:
  - [ ] `make test-unit`
  - [ ] `make test-integration` (or targeted subset for the story's surface, with explanation)
  - [ ] `make test-contract`
  - [ ] `cd ui && pnpm test` (if UI touched)
  - [ ] `cd ui && pnpm test:e2e:stable` (after Story 5.2)
- [ ] Migration round-trip evidence included (Story 1.1)
- [ ] Related docs/checklists updated in same PR when behavior/contract changed
- [ ] No `openai.AsyncClient(...)` instances outside the worker's `_make_llm_rate_callback` parameter binding (lint guard / ast scan)
- [ ] No new write-shaped HTTP calls from `UbiReader` (mock-HTTP integration test)
- [ ] Enum source-of-truth comments present on every new `*_VALUES` array
- [ ] Form-select discipline lint guard passes (Story 4.2)

---

## 11) Plan consistency review

1. **Spec ↔ plan endpoint count**: spec §8.1 lists 2 endpoints (POST `/judgments/generate-from-ubi` + GET `/clusters/{id}/ubi-readiness`). Plan covers both (Stories 3.1 + 3.2). ✓
2. **Spec ↔ plan error code coverage**: spec §8.5 lists 13 codes (3 new UBI codes + 10 reused). Plan contract tests in §3.3 cover all 13 in `test_judgments_generate_from_ubi_shape.py` + `test_clusters_ubi_readiness_shape.py`. ✓
3. **Spec ↔ plan FR coverage**: every FR in §1 traceability table is assigned to at least one story. ✓ (11/11 FRs covered.)
4. **Story internal consistency**:
   - Endpoint table fields match Pydantic schema fields (verified manually). ✓
   - DoD assertions reference the correct error codes from the endpoint tables. ✓
   - New files not duplicated across stories (no ownership conflicts). ✓
   - Modified files all exist in the codebase (verified at draft time via `ls`). ✓
5. **Test file count + assignment**: 6 unit + 11 integration + 4 contract + 4 e2e + 1 migration = 26 test files. Every file assigned to exactly one story's DoD (cross-referenced in §3.1–3.4 task lists). ✓
6. **Gate arithmetic**: no explicit "all N endpoints live" gates in this plan (the sequencing in §7 is dependency-based, not count-based). ✓
7. **Open questions resolved**: spec §19 D-1..D-10 cover all idea-stage + cycle-3 OQs. None remain open. ✓
8. **Frontend UI Guidance completeness**: all required subsections present — Insertion point ✓; Analogous markup patterns ✓ (actual JSX for method picker, nudge, sparse card, value-delta card, ambiguous-skip card); Layout and structure ✓; Confirmation/modal pattern ✓ (no new modal — explicit); Visual consistency table ✓; Component composition ✓; Interaction behavior table ✓; Handler function patterns ✓; Information architecture placement ✓; Tooltips ✓ (with glossary keys + source-of-truth comments); Legacy behavior parity ✓ (explicit "not required" with rationale).
9. **Plan ↔ codebase verification (refactors)**: §5.2 refactors verified — `start_judgment_generation` exists at `agent_judgments_dispatch.py:69`; `source_breakdown_for_list` exists at `judgment.py:278`; the 5 shared-helper extraction targets correspond to existing inline logic at the cited line ranges. ✓
10. **Infrastructure path verification**: migration dir `migrations/versions/` ✓ (`ls` shows `0020_studies_baseline_trial.py` as current head; next is `0021`); router registration via `app.include_router(judgments_router.router, prefix="/api/v1")` ✓ (Story 3.2 router added to existing `judgments.py` — no new mount); cluster router registration ✓ (Story 3.1).
11. **Frontend data plumbing**: `useUbiReadiness(clusterId, querySetId, target)` requires the parent component to have all three. Verified in §"UI Guidance / Interaction behavior table": the generate-judgments dialog opens with `clusterId` + `querySetId` from props + `target` from the form's `target` field (live state). The cluster-list/detail pages use the "snapshot" badge variant which doesn't require query_set/target context — explicit per Story 4.1. ✓
12. **Persistence scope**: nudge dismissal uses `localStorage` and the DoD says "persists across visits for the same cluster" — match. ✓
13. **Enumerated value contract audit**: spec §8.4 enumerates all 5 wire-value contracts (converter, method, mapping_strategy, rung, source filter). Plan §"UI Guidance / Wire value enumeration table" mirrors them character-for-character with backend source-of-truth files cited. Story 4.1 DoD enforces. ✓
14. **Audit-event coverage (MVP2+)**: `audit_log` arrives at MVP2 per CLAUDE.md "Activates at MVP3" (the table doesn't ship in this feature's PR). Per spec §6, the audit-event matrix is defined for MVP3 activation. **This plan does NOT add audit emission code** because the canonical `audit_log` table doesn't exist yet in MVP2. When the table lands in MVP3 (separate feature), audit emission for `judgment_list.ubi_generation_requested` / `_completed` and `cluster.ubi_readiness_probed` will be wired in then. ✓ (explicit per the spec §6 rule — "Activates at MVP3"; this feature is pre-table).

---

## 12) Definition of plan done

This implementation plan is execution-ready when:

- [ ] Every FR is mapped to stories/tasks/tests/docs updates (§1 traceability). ✓
- [ ] Every story includes New files, Modified files, Endpoints (when API-facing), Key interfaces, Tasks, and DoD. ✓
- [ ] Test layers (unit/integration/contract/e2e) are explicitly scoped (§3). ✓
- [ ] Documentation updates across docs/01-05 are planned and owned (§4 + Story 5.1). ✓
- [ ] Lean refactor scope and guardrails are explicit (§5). ✓
- [ ] Phase/epic gates: none required (sequencing via dependencies in §7). ✓
- [ ] Story-by-Story Verification Gate (§10) is included. ✓
- [ ] Plan consistency review (§11) performed with no unresolved findings. ✓ (pending GPT-5.5 cross-model review)

---

**Cross-model review status:** Converged at 3-cycle cap (2026-05-29). All 3 GPT-5.5 findings accepted and applied:

- **Cycle 1 (Medium):** `template-not-found-error-scope-drift` — spec §8.5 + §8.1 now list `TEMPLATE_NOT_FOUND` (404, hybrid only) inherited from `start_judgment_generation` preflight D via the shared `_resolve_cluster_query_set` helper. Spec edit; plan unchanged.
- **Cycle 2 (High):** `ubi-generation-params-kind-missing` — Story 2.2 now builds `generation_params` via `_build_ubi_generation_params(req)` that injects `generation_kind: 'ubi'` before persistence; integration test asserts the discriminator present + round-trip succeeds.
- **Cycle 3 (Medium):** `readiness-snapshot-badge-contract-drift` — dropped the snapshot variant of `<UbiRungBadge>` entirely. Story 4.1 component is single-variant; no badge render on cluster list/detail pages (spec FR-7 requires `?query_set_id`+`?target` query params; those pages don't have them). Operators discover UBI inside the generate-judgments dialog where the parent supplies the full context.

Cycle 3 hit the skill's max-cycle cap; the cycle-3 edits were not re-submitted for cycle 4. Future implementation review during `/impl-execute` phase gates will surface any structural issues introduced by the post-cycle-3 fixes.

**Status:** Approved.
