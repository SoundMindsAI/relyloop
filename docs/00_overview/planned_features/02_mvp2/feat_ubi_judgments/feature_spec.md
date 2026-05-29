# Feature Specification — UBI Judgments (engine-neutral User Behavior Insights as an optional, first-class judgment source)

**Date:** 2026-05-29
**Status:** Approved (cross-model converged at cycle-3 cap with all findings accepted; see D-10)
**Owners:** RelyLoop maintainers (Product + Engineering)
**Related docs:**
- [`idea.md`](idea.md)
- [`infra_adapter_solr/idea.md`](../infra_adapter_solr/idea.md) (co-ships in MVP2 "Three-Engine + Real Signals")
- [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md)
- [`docs/01_architecture/adapters.md`](../../../../01_architecture/adapters.md)
- [`docs/01_architecture/data-model.md`](../../../../01_architecture/data-model.md)
- [`docs/00_overview/relyloop-spec.md`](../../../relyloop-spec.md) §14, §19, §27 (UBI patches)
- Reuses: [`feat_llm_judgments`](../../../implemented_features/2026_05_11_feat_llm_judgments/) (Arq worker shape, calibration helpers, `start_judgment_generation` dispatcher), [`feat_contextual_help`](../../../implemented_features/2026_05_15_feat_contextual_help/) (HelpPopover idiom), [`feat_chat_agent`](../../../implemented_features/2026_05_12_feat_chat_agent/) (tool-registry triad), [`chore_form_dropdown_primitive`](../../../implemented_features/) (form-select discipline)

---

## 1) Purpose

- **Problem:** MVP1 ships LLM-as-judge as the only authoritative judgment source. That is a weak trust anchor for any operator with production search traffic, the long tail of real queries never gets rated, and judgment lists go stale the moment they are snapshotted. The architecture has anticipated this — `judgments.source` CHECK already accepts `click` at [`backend/app/db/models/judgment.py:46-47`](../../../../../backend/app/db/models/judgment.py#L46-L47), `JudgmentSourceWire` already enumerates `('llm', 'human', 'click')` at [`backend/app/api/v1/schemas.py:827`](../../../../../backend/app/api/v1/schemas.py#L827), and the umbrella spec §14 calls out the mixed-source contract — but the actual UBI reader, signal converters, ingestion endpoint, and agent tool have never been built.
- **Outcome:** Operators with the OpenSearch / ES UBI plugin installed (today; Solr's first-party `solr.UBIComponent` lights up with the sibling `infra_adapter_solr` MVP2 release) can derive judgments from real click + dwell behavior via three converters (`ctr_threshold`, `dwell_time`, `hybrid_ubi_llm`) — the hybrid mode interleaves LLM-fill rows with `source='click'` rows in the same judgment list. Operators **without** UBI keep MVP1's LLM-as-judge experience unchanged, with a dismissible engine-aware nudge surfacing the on-ramp. Every UBI touchpoint is progressive enhancement — never a gate. The PR-body confidence claim grows from "scored against 500 LLM ratings against a snapshot query set" to "scored against 50,000 UBI-derived ratings covering 90% of last week's traffic."
- **Non-goal:** RelyLoop never installs the UBI plugin, never writes to the cluster, never modifies schema/mapping/analyzer settings (umbrella spec §4 non-goals). Detection is **read-only** via a `get_schema` probe for the `ubi_queries` index. RelyLoop never runs online A/B tests, never trains LTR models, never sits on the live serving path. Counterfactual click models (CCM / DBN) are out of scope — same `SignalsConverter` Protocol, additive in v1.5+ post-GA.

## 2) Current state audit

### Existing implementations

| File / component | What it does | API used | Notes |
|---|---|---|---|
| [`backend/app/db/models/judgment.py`](../../../../../backend/app/db/models/judgment.py) | `Judgment` ORM with `source` CHECK `IN ('llm', 'human', 'click')` | — | `click` is reserved-but-unused per the module docstring (line 11–12). This spec lights it up. |
| [`backend/app/db/models/judgment_list.py`](../../../../../backend/app/db/models/judgment_list.py) | `JudgmentList` ORM with `calibration` JSONB (line 58) and `status IN ('generating', 'complete', 'failed')` CHECK | — | UBI worker writes calibration rows of a different shape (`coverage_pct`, `head_pairs`, `tail_pairs`, `position_bias_prior_id`, `ambiguous_query_skip_count`). Adds a new `generation_params` JSONB column (Alembic head `0021`) populated at INSERT for UBI lists so the boot-time resume sweep can reconstruct the worker call without depending on the Arq job payload (cycle-3 finding `ubi-generation-params-not-persisted`). LLM lists leave the new column NULL — the existing `current_template_id` + `rubric` already carry their resume state. |
| [`backend/app/api/v1/judgments.py:170-220`](../../../../../backend/app/api/v1/judgments.py#L170-L220) | `POST /api/v1/judgments/generate` — 202 + `GenerateJudgmentsResponse{judgment_list_id, status}` | Delegates to `start_judgment_generation` | The new UBI endpoint mirrors this shape exactly; same router, same prefix, same `generate-*` action verb. |
| [`backend/app/api/v1/judgments.py:126-147`](../../../../../backend/app/api/v1/judgments.py#L126-L147) | `_detail()` populates `_SourceBreakdown(llm=…, human=…)` from `repo.source_breakdown_for_list` | — | `_SourceBreakdown` currently locks `llm + human == judgment_count` per `feat_llm_judgments` cycle-2 F6. With UBI shipping mixed lists, this invariant becomes user-visible inaccuracy. This spec evolves the shape (D-1). |
| [`backend/app/api/v1/schemas.py:864-873`](../../../../../backend/app/api/v1/schemas.py#L864-L873) | `_SourceBreakdown(llm: int, human: int)` Pydantic model | — | Path A evolution: add `click: int`. The only consumers are the project's own UI + contract tests. |
| [`backend/app/api/v1/schemas.py:833`](../../../../../backend/app/api/v1/schemas.py#L833) | `JudgmentSourceFilterWire = Literal["llm", "human"]` | — | Spec §8.4 rejected `click` at the API filter boundary in MVP1 (cycle-1 F1) because no UBI rows existed yet. This spec promotes the filter to `Literal["llm", "human", "click"]` so operators can audit UBI-only or hybrid lists. |
| [`backend/app/services/agent_judgments_dispatch.py:69`](../../../../../backend/app/services/agent_judgments_dispatch.py#L69) | `start_judgment_generation` — shared dispatcher (preflight A–F + INSERT + Arq enqueue) used by router AND chat-agent tool | — | This spec adds a sibling `start_ubi_judgment_generation` in the same module, mirroring the seven-stage preflight (UBI-shaped: capability probe, query-mapping, coverage gate, FK, optional budget-peek for hybrid, INSERT, enqueue). |
| [`backend/workers/judgments.py:354`](../../../../../backend/workers/judgments.py#L354) | `generate_judgments_llm` Arq job — full pipeline with budget gate, per-query resume-skip, set-equal validation | — | UBI worker (`generate_judgments_from_ubi`) lives in the same module; shares `_safe_record_cost`, `_fail_list`, the `bulk_create_judgments` ON CONFLICT DO NOTHING pattern, and the `source='click'` / `rater_ref='ubi:{converter}'` row shape. Hybrid mode delegates LLM-fill calls to a new `_process_query_llm_fill` helper that wraps the existing `rate_query_batch` so the daily-budget gate at [`backend/app/llm/budget_gate.py`](../../../../../backend/app/llm/budget_gate.py) fires unchanged. |
| [`backend/app/agent/tools/judgments/generate_judgments_llm.py`](../../../../../backend/app/agent/tools/judgments/generate_judgments_llm.py) | LLM-judgment agent tool — `GenerateJudgmentsLLMArgs` + `generate_judgments_llm_impl` + `GENERATE_JUDGMENTS_LLM_TOOL` triad | — | New sibling `generate_judgments_from_ubi.py` follows the same triad pattern; registered in [`backend/app/agent/tools/__init__.py`](../../../../../backend/app/agent/tools/__init__.py) (the `TOOLS` / `TOOL_REGISTRY` / `TOOL_ARG_MODELS` registry with module-load drift assertion at line 232–236). |
| [`backend/app/adapters/protocol.py`](../../../../../backend/app/adapters/protocol.py) | `SearchAdapter` Protocol with `search_batch`, `get_schema`, `list_targets` | — | UBI reader uses only the existing surface — two scrolling `search_batch` calls (one against `ubi_queries`, one against `ubi_events`) plus a `get_schema('ubi_queries')` probe for the readiness ladder. No adapter Protocol changes. |
| [`backend/app/db/models/cluster.py:30`](../../../../../backend/app/db/models/cluster.py#L30) | `engine_type IN ('elasticsearch', 'opensearch')` CHECK | — | Solr arm of Capability B's engine-aware nudge is dark until `infra_adapter_solr` extends this CHECK. Spec accommodates by branching on `cluster.engine_type` with a `solr` arm that returns a placeholder runbook link guarded by a feature check. |
| [`ui/src/lib/enums.ts:111-120`](../../../../../ui/src/lib/enums.ts#L111-L120) | `JUDGMENT_SOURCE_VALUES`, `JUDGMENT_SOURCE_FILTER_VALUES` | — | Spec adds three new arrays, each with the `// Values must match backend/...` discipline comment: `JUDGMENT_GENERATION_METHOD_VALUES = ['llm', 'ctr_threshold', 'dwell_time', 'hybrid_ubi_llm']` (mirrors `JudgmentGenerationMethodWire`; consumed by the picker `<Select>`), `UBI_CONVERTER_VALUES = ['ctr_threshold', 'dwell_time', 'hybrid_ubi_llm']` (mirrors `UbiConverterKind`; consumed by any future advanced/CLI surface that hits `POST /judgments/generate-from-ubi` directly), `UBI_READINESS_RUNG_VALUES = ['rung_0', 'rung_1', 'rung_2', 'rung_3']`. The existing `JUDGMENT_SOURCE_FILTER_VALUES` widens to include `'click'`. |
| [`ui/src/components/query-sets/generate-judgments-dialog.tsx`](../../../../../ui/src/components/query-sets/generate-judgments-dialog.tsx) | Existing 4-field generation form (name / target / template / rubric) | `POST /api/v1/judgments/generate` | Extended in-place with the converter picker (Capability E), UBI window controls (`since`/`until`), and the engine-aware enablement card (Capability B). The picker's `<Select>` MUST follow the `chore_form_dropdown_primitive` discipline — `UBI_CONVERTER_VALUES.map(...)` imported from `@/lib/enums`. |
| [`ui/src/lib/glossary.ts:436-452`](../../../../../ui/src/lib/glossary.ts#L436-L452) | Existing `judgment.source.*` entries (definitional) | — | Spec adds 4 new keys: `judgment.converter`, `judgment.converter.ubi`, `judgment.converter.hybrid`, `cluster.ubi_readiness`. |
| [`ui/src/lib/faq.ts`](../../../../../ui/src/lib/faq.ts) | Operator-judgment-shaped Q&A | — | Spec adds 3 new entries under the `judgments` category (see §15). |
| [`ui/src/components/dashboard/demo-data-banner.tsx`](../../../../../ui/src/components/dashboard/demo-data-banner.tsx) | Dismissible card using `useSyncExternalStore` + `safeLocalStorageGet`/`safeLocalStorageSet` (SSR-safe pattern) | — | The Capability B nudge follows this exact pattern (NOT the `useLocalStorageSet` hook, which is Set-shaped for column visibility). Storage key shape: `relyloop.ubi-onramp-nudge.dismissed:{cluster_id}`. |
| [`ui/src/components/common/help-popover.tsx`](../../../../../ui/src/components/common/help-popover.tsx) | Glossary-backed popover (`feat_contextual_help`) | — | Inline helper text under each converter picker option uses `HelpPopover` keyed off the new glossary entries. |

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| [`docs/00_overview/relyloop-spec.md:706`](../../../relyloop-spec.md) | `### Click-derived judgments — OpenSearch UBI as the engine-neutral primary path (MVP1.5)` | `### Click-derived judgments — OpenSearch UBI as the engine-neutral primary path (MVP2)` — drift fix from the 2026-05-27 release-matrix compression |
| [`docs/00_overview/relyloop-spec.md:724`](../../../relyloop-spec.md) | Sibling planned-feature refs missing the `02_mvp2/` bucket | `planned_features/02_mvp2/feat_ubi_judgments/idea.md` and `planned_features/02_mvp2/infra_adapter_solr/idea.md` (correct relative path from inside `docs/00_overview/`) |
| [`docs/08_guides/tutorial-first-study.md`](../../../../08_guides/tutorial-first-study.md) | No "Step 7 — swap LLM list for UBI" yet | New optional Step 7 demonstrating the value-delta upgrade; tutorial must still complete fully on the LLM path for readers with no UBI cluster. |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/contract/test_judgments_*.py` | Asserts `_SourceBreakdown` shape `{llm, human}` (no `click`) | TBD at impl time | Update to assert `{llm, human, click}` shape; assertions covering `source_breakdown.human` on LLM-only lists keep working (`click=0`); new assertions cover mixed-source lists. |
| `backend/tests/contract/test_judgments_*.py` | Asserts `?source=` filter rejects `click` with 422 (cycle-1 F1) | TBD | Update — `click` is now an accepted filter value (returns matching click-derived rows). Spec §8.4 in `feat_llm_judgments` was authored when no UBI rows existed; this feature is the moment to invert it. |
| `backend/tests/unit/eval/test_qrels_loader.py` | Loads qrels via `SELECT … FROM judgments WHERE judgment_list_id = :id` | — | No change — qrels_loader is source-agnostic (just reads `rating`). UBI and LLM rows blend identically for the optimizer. |
| `backend/tests/integration/agent/test_tool_registry.py` (or equivalent) | Enumerates tools in `TOOLS` / `TOOL_REGISTRY` / `TOOL_ARG_MODELS` | — | Add `generate_judgments_from_ubi` to all three; the module-load drift assertion at `backend/app/agent/tools/__init__.py:232-236` catches a missing-from-one regression at import time. |
| `ui/src/__tests__/components/query-sets/generate-judgments-dialog.test.tsx` | Submits the 4-field form | TBD | Add cases for: converter picker default selection (per rung), `hybrid_ubi_llm` showing the LLM-fill threshold field, `since`/`until` window controls, engine-aware nudge dismissal, sparse-data hybrid recommendation copy. |
| `ui/src/__tests__/components/common/form-select-discipline.test.tsx` | Lint guard rejects inline `<SelectItem value="...">` for wire-value enums in `ui/src/components/` form `.tsx` files | — | No change to the guard itself; the new converter `<Select>` must use the `UBI_CONVERTER_VALUES.map(...)` pattern or the guard fails. |
| `ui/src/__tests__/lib/enums-source-of-truth.test.ts` (or equivalent) | Asserts each `*_VALUES` array has a `// Values must match backend/...` comment immediately above | — | New `UBI_CONVERTER_VALUES` and `UBI_READINESS_RUNG_VALUES` must carry the comment. |

### Existing behaviors affected by scope change

- **`?source=` filter on `GET /api/v1/judgment-lists/{id}/judgments`** — Current: rejects `click` (422 VALIDATION_ERROR) because `JudgmentSourceFilterWire = Literal["llm", "human"]`. New: accepts all three values; `click` returns the UBI-derived rows. Decision needed: **No** (locked at D-3).
- **`_SourceBreakdown` response field on `GET /api/v1/judgment-lists/{id}`** — Current: `{llm, human}` with the invariant `llm + human == judgment_count` (click rows fold into `human`). New: `{llm, human, click}` with `llm + human + click == judgment_count`. Decision needed: **No** (locked at D-1).
- **`JudgmentList.calibration` JSONB content shape** — Current: `{cohens_kappa, weighted_kappa, per_class, n_samples, warning}` (computed by `compute_calibration` at [`backend/app/eval/calibration.py`](../../../../../backend/app/eval/calibration.py)). New on UBI lists: `{coverage_pct, head_pairs, tail_pairs, position_bias_prior_id, llm_fill_calls?}` (no kappa — UBI doesn't have human samples by default; if the operator later runs `POST /judgment-lists/{id}/calibration` against a UBI list, the merge appends the kappa keys to the existing UBI-shaped object). Decision needed: **No** (the JSONB column accepts both shapes — UI branches on `'cohens_kappa' in calibration`).
- **Tutorial-first-study guide flow** — Current: completes on LLM-as-judge path. New: adds optional Step 7 demonstrating LLM → UBI swap. The Step 7 is gated on the reader having a UBI-enabled cluster; the tutorial completes fully without it.

## 3) Scope

### In scope

- **Capability 1 — `UbiReader` engine-agnostic read layer.** New module `backend/app/services/ubi_reader.py` + supporting feature aggregation in `backend/app/domain/ubi/features.py`. Reads `ubi_queries` + `ubi_events` via `SearchAdapter.search_batch` with a client-side join on `query_id`. Output: per-`(query_id, doc_id)` feature dict (`click_count`, `impression_count`, `corrected_ctr`, `dwell_mean_seconds`, `conversion_rate`, `refinement_rate`). Position-bias correction: Wang-Bendersky correction with configurable prior (`UBI_POSITION_BIAS_PRIOR_FILE` env var; default behaves as uninformed prior).
- **Capability 2 — `SignalsConverter` Protocol + 3 concrete impls.** New `backend/app/domain/ubi/converter.py` with `SignalsConverter` Protocol + `CtrThresholdConverter` + `DwellTimeThresholdConverter` + `HybridUbiLlmConverter`. Pure-domain (no I/O). Protocol: `convert(features: dict[tuple[str, str], FeatureVec]) -> dict[tuple[str, str], int]` returning 0–3 ratings.
- **Capability 3 — `POST /api/v1/judgments/generate-from-ubi` endpoint** mirroring the existing `POST /api/v1/judgments/generate` shape. 202 → `{judgment_list_id, status: "generating"}`. Preflight: query-set / cluster FK + consistency, UBI readiness probe, oversize gate, optional LLM-fill prerequisites (capability cache, budget peek) when `converter='hybrid_ubi_llm'`. Shared dispatch via `start_ubi_judgment_generation` in `backend/app/services/agent_judgments_dispatch.py`.
- **Capability 4 — `generate_judgments_from_ubi` Arq job** at `backend/workers/judgments.py`. Mirrors the `generate_judgments_llm` lifecycle (resume-skip per query, terminal-status flip, structured `failed_reason`). Persists UBI rows with `source='click'`, `rater_ref='ubi:{converter}'`. Hybrid-mode LLM-fill calls route through the existing `rate_query_batch` + budget gate.
- **Capability 5 — `generate_judgments_from_ubi` chat-agent tool.** New `backend/app/agent/tools/judgments/generate_judgments_from_ubi.py` following the LLM-tool triad (`<NAME>_TOOL` / `<NAME>Args` / `<name>_impl`). Registered in `backend/app/agent/tools/__init__.py` `TOOLS` + `TOOL_REGISTRY` + `TOOL_ARG_MODELS`. System-prompt update: orchestrator prefers UBI when readiness probe succeeds, falls back to LLM otherwise.
- **Capability A — Readiness probe + ladder classification.** New `backend/app/services/ubi_readiness.py` (pure read-side wrapper). Classifies each cluster on rung 0–3 via a single `get_schema('ubi_queries')` probe + (for rung 1+) a lightweight aggregation on `ubi_events`. Exposed as `GET /api/v1/clusters/{id}/ubi-readiness` (202 if probe in flight, 200 with rung otherwise). Returns `{rung: 'rung_0' | 'rung_1' | 'rung_2' | 'rung_3', covered_pairs_pct?: float, head_covered?: bool}`. **No cluster writes.**
- **Capability B — Engine-aware dismissible nudge.** New `ui/src/components/clusters/ubi-onramp-nudge.tsx` rendered on the generate-judgments dialog when rung == 0. Engine-specific copy switches on `cluster.engine_type` (`elasticsearch` → o19s ES UBI fork; `opensearch` → OpenSearch UBI plugin; `solr` arm dark until `infra_adapter_solr` extends the `engine_type` CHECK). Dismissal persisted via `safeLocalStorageGet`/`Set` keyed by `cluster_id`. Re-surfaces only when the underlying rung is still 0.
- **Capability C — Sparse-data guidance (rung 1).** When UBI is present but below `min_impressions_threshold`, the would-be 422 `UBI_INSUFFICIENT_DATA` path renders an inline recommendation card ("~12% of your query set has enough signal — hybrid rates that head, LLM fills the rest") with a one-click "Switch to hybrid" affordance. Never bounces with a bare 422.
- **Capability D — Value-delta surfacing on list completion.** UBI/hybrid list detail page surfaces coverage stats (`covered_pairs_pct`, `total_query_impressions`). When a prior LLM list exists on the same `query_set_id`, surface a metric/coverage delta. PR-body confidence framing (composes with shipped [`feat_pr_metric_confidence`](../../../implemented_features/2026_05_21_feat_pr_metric_confidence/)) reads the same coverage stats from the calibration JSONB.
- **Capability E — Point-of-choice converter picker.** Converter `<Select>` in the generate-judgments dialog with four options (`llm`, `ctr_threshold`, `dwell_time`, `hybrid_ubi_llm`). Default selection follows the detected rung (rung 0 → `llm`; rung 1–2 → `hybrid_ubi_llm`; rung 3 → `ctr_threshold` if no dwell signal, else operator picks). `InfoTooltip` + `HelpPopover` glossary backing for each option. The picker MUST use the `UBI_CONVERTER_VALUES.map(...)` pattern per `chore_form_dropdown_primitive` lint guard.
- **Glossary + FAQ + runbook + tutorial.** 4 new glossary keys, 3 new FAQ entries, new runbook `docs/03_runbooks/ubi-judgment-generation.md`, optional Step 7 in `docs/08_guides/tutorial-first-study.md`, umbrella spec §14 + §706 + §724 patches.
- **Promote `JudgmentSourceFilterWire` from `Literal["llm", "human"]` to `Literal["llm", "human", "click"]`.** UI `JUDGMENT_SOURCE_FILTER_VALUES` widens to match. The `?source=` query on `GET /api/v1/judgment-lists/{id}/judgments` now accepts `click`. (D-3.)
- **Evolve `_SourceBreakdown` in-place to `{llm, human, click}` with the invariant `llm + human + click == judgment_count`.** No `V2` versioning — the only OpenAPI consumers today are the project's own UI + contract tests. (D-1.)

### Out of scope

- **Cluster writes / plugin installation.** RelyLoop never installs the UBI plugin, never modifies cluster schema/mapping/analyzer, never writes to `ubi_queries` or `ubi_events`. Detection is read-only via `get_schema` + aggregation searches.
- **Solr adapter.** Solr ships in the sibling `infra_adapter_solr` MVP2 feature. Capability B's `solr` arm is **dark code** in this PR — guarded by an `engine_type === 'solr'` branch that won't fire until `infra_adapter_solr` extends `clusters_engine_type_check`. When that lands, the Capability B copy switches on without code change here.
- **Counterfactual click models (CCM, DBN).** Same `SignalsConverter` Protocol, additive in v1.5+ post-GA when adopters have enough impressions per `(query, doc)` to be statistically valid.
- **Multi-tenancy.** RelyLoop is single-tenant through GA v1. No `tenant_id` column on new tables (there are no new tables — UBI rides existing `judgments` + `judgment_lists`).
- **`Idempotency-Key` header.** Scheduled for GA v1 per [`docs/01_architecture/api-conventions.md` line 179 + 225](../../../../01_architecture/api-conventions.md). The UBI endpoint follows the existing MVP2 pattern — name-uniqueness on `judgment_lists.name` catches duplicate-request collisions.
- **Online A/B testing, LTR training, query-time-config writes back to the cluster.** All explicitly excluded by umbrella spec §4.
- **Native non-OpenAI provider SDKs** for the hybrid LLM-fill path. Hybrid mode uses the existing `openai` SDK pointed at any OpenAI-compatible endpoint via `OPENAI_BASE_URL` (Absolute Rule #3 / #8 / #10).

### API convention check

Verified against [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md):

- **Endpoint prefix:** `/api/v1/<resource>` for business endpoints. The new endpoint is `POST /api/v1/judgments/generate-from-ubi` — same `/judgments` prefix, same `generate-*` action verb as the existing `POST /api/v1/judgments/generate` ([`backend/app/api/v1/judgments.py:171`](../../../../../backend/app/api/v1/judgments.py#L171)). Readiness endpoint: `GET /api/v1/clusters/{id}/ubi-readiness` (per-cluster sub-resource pattern, mirrors `GET /api/v1/clusters/{id}/schema` shipped in `infra_adapter_elastic`).
- **Router namespace:** existing [`backend/app/api/v1/judgments.py`](../../../../../backend/app/api/v1/judgments.py) for the generate endpoint; existing [`backend/app/api/v1/clusters.py`](../../../../../backend/app/api/v1/clusters.py) for the readiness endpoint.
- **HTTP methods:** POST=create; GET=read.
- **Non-auth error envelope:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` — exact shape from the existing `_err()` helper at [`backend/app/api/v1/judgments.py:86-90`](../../../../../backend/app/api/v1/judgments.py#L86-L90).
- **Auth error shape:** N/A — single-tenant, no auth in MVP2.

### Phase boundaries

**Default delivery: single phase.** All 10 capabilities (1, 2, 3, 4, 5, A, B, C, D, E) ship in one PR. The idea author explicitly merged the on-ramp folder (`feat_ubi_onramp`) back into this feature 2026-05-29 to make it impossible to ship half — the substrate without the on-ramp creates the exact "UBI is a wall" failure mode the on-ramp exists to prevent.

**Contingency (decided at `/impl-plan-gen` time):** If the combined PR exceeds reviewability thresholds (~1500 LOC bundled diff is the historical pain point on this project; current scope estimate is ~1350 LOC bundled), the correct split is **by delivery phase within this folder**:

- **Phase 1 — Substrate + always-LLM picker.** Capabilities 1, 2, 3, 4, 5, E with `converter='llm'` as the picker default for ALL rungs. Ships `UbiReader`, `SignalsConverter`, the endpoint, the worker, the agent tool, the converter picker, the in-place `_SourceBreakdown` evolution, the filter widening. Does NOT ship the on-ramp UX (Capabilities A, B, C, D); a rung-0 operator who picks UBI hits a bare 412 `UBI_NOT_ENABLED`. Acceptable for a 1–2-week gap because Phase 2 ships before the MVP2 release tag.
- **Phase 2 — Readiness + on-ramp UX.** Capabilities A, B, C, D. Wires the rung-detection probe, the dismissible nudge, the sparse-data guidance, the value-delta surface. Picker default per rung becomes active.

A `phase2_idea.md` tracker file is **NOT created up front** because the default delivery is single-phase. If `/impl-plan-gen` elects to split, it creates `phase2_idea.md` at that time per the impl-plan-gen skill's Step 10 (deferred-phase tracking).

## 4) Product principles and constraints

- **UBI is opt-in progressive enhancement, never a gate.** Every UBI touchpoint MUST have a no-UBI fallback (or sparse-UBI hybrid recommendation). The 412 / 422 UBI error codes are structured renderable states the UI turns into on-ramps — never bare error pages.
- **No cluster writes ever.** RelyLoop reads `ubi_queries` + `ubi_events` via the existing `SearchAdapter.search_batch` surface. It NEVER calls `_index`, `_update`, `_bulk`, `PUT _mapping`, or any write API. The `get_schema` readiness probe is a read.
- **Engine-neutral by Protocol.** `UbiReader` consumes only `SearchAdapter` — no `ElasticAdapter`-specific code. When `infra_adapter_solr` ships, UBI on Solr works the same day, no UBI code change required.
- **Per-row source provenance.** Every persisted judgment carries the exact `source` (`llm` / `human` / `click`) and `rater_ref` (`openai:{model}` for LLM, `operator` for human, `ubi:{converter}` for click) so audit + calibration + delta-surfacing all trace back to the row's origin.
- **LLM-fill always routes through the existing budget gate.** Hybrid-mode LLM calls reuse `rate_query_batch` + `peek_daily_total` + `record_cost` from [`backend/app/llm/budget_gate.py`](../../../../../backend/app/llm/budget_gate.py). No new LLM client, no direct `openai.AsyncClient(...)` outside the shared helper (Absolute Rule #3 / #8 / #10).
- **Wire-value contracts grounded in backend Literals.** `converter` field values, readiness rung values, source filter values — all live as `Literal[...]` in `backend/app/api/v1/schemas.py` (or `backend/app/domain/ubi/converter.py` for the converter enum) and mirror in `ui/src/lib/enums.ts` with the `// Values must match backend/...` comment. Frontend `<Select>` follows the `*_VALUES.map(...)` pattern; the form-select discipline lint guard at [`ui/src/__tests__/components/common/form-select-discipline.test.tsx`](../../../../../ui/src/__tests__/components/common/form-select-discipline.test.tsx) enforces.
- **`source` (per-row provenance) vs `converter` (per-list generation strategy) are distinct.** The picker chooses a converter; the worker writes per-row sources. The spec MUST never label the picker `source`.

### Anti-patterns

- **Do not** name the converter picker field `source` — it is not the per-row `judgments.source` value. The wire field is `converter` (locked at D-2). Conflating the two reintroduces the exact confusion that motivated Capability E.
- **Do not** call OpenAI directly from the hybrid-mode worker. Reuse the existing `rate_query_batch` + budget gate (Absolute Rule #3 / #8 / #10). A direct `openai.AsyncClient(...)` instance bypasses the daily-budget gate and the capability cache.
- **Do not** install the UBI plugin or write to `ubi_queries` / `ubi_events`. Detection is read-only via `get_schema`. The operator MUST enable UBI on their own infrastructure (the nudge deep-links to the runbook).
- **Do not** add an `Idempotency-Key` header to the UBI endpoint. No existing endpoint implements it; [`docs/01_architecture/api-conventions.md`](../../../../01_architecture/api-conventions.md) lines 179 + 225 schedule it for GA v1. The UBI endpoint follows MVP2 patterns — name-uniqueness on `judgment_lists.name` catches duplicates.
- **Do not** add an Alembic migration beyond the single additive `0021_judgment_lists_generation_params.py` (one new nullable JSONB column for UBI worker resume — see §9). The `judgments` table is unchanged; the `source IN ('llm', 'human', 'click')` CHECK already accepts the new value. Other UBI metadata (calibration rows, coverage) lives in the existing `calibration` JSONB.
- **Do not** silently fold `click` rows into `human` in the `_SourceBreakdown` response. The Path A evolution (D-1) is the explicit fix to the cycle-2 F6 invariant from `feat_llm_judgments`, which was made in a click-rows-don't-yet-exist world.
- **Do not** bounce a sparse-UBI operator with a bare 422 `UBI_INSUFFICIENT_DATA`. Capability C is the recommendation card; the 422 stays the error envelope shape (so contract tests can lock it), but the UI transforms it into a guidance state with the "Switch to hybrid" affordance.
- **Do not** inline `<SelectItem value="ctr_threshold">` in the method picker. Use `JUDGMENT_GENERATION_METHOD_VALUES.map(...)` imported from `@/lib/enums` per the `chore_form_dropdown_primitive` discipline — the picker carries all four options (`llm` + three UBI converters). `UBI_CONVERTER_VALUES` is the 3-value mirror of the request-side `UbiConverterKind` reserved for any future advanced/CLI surface that calls `POST /judgments/generate-from-ubi` directly. The lint guard at `ui/src/__tests__/components/common/form-select-discipline.test.tsx` will fail the suite if either array is inlined.
- **Do not** copy `start_judgment_generation`'s preflight body into the new dispatcher. Refactor common phases (FK resolution, consistency, oversize, INSERT, enqueue) into shared helpers in `backend/app/services/agent_judgments_dispatch.py` and call them from both `start_judgment_generation` and `start_ubi_judgment_generation`. Duplication is the failure mode that motivated the dispatcher in the first place.

## 5) Assumptions and dependencies

- **MVP1 shipped.** `judgments` + `judgment_lists` tables, `ElasticAdapter` with `search_batch`, `generate_judgments_llm` agent tool, `start_judgment_generation` dispatcher all exist. Status: implemented. Risk if missing: N/A — MVP1 is the precondition for MVP2.
- **OpenSearch UBI plugin** installed in the operator's application — for any UBI converter to function. The plugin writes the standardized `ubi_queries` + `ubi_events` indices. Status: external (operator-owned). Risk if missing: 412 `UBI_NOT_ENABLED` returned; Capability B nudge surfaces the install runbook. Capability E ensures `llm` is always pickable so a no-UBI operator can still create judgment lists.
- **OpenAI-compatible LLM endpoint** + valid `OPENAI_API_KEY_FILE` — required for hybrid-mode LLM fill. Status: existing dependency from `feat_llm_judgments`. Risk if missing: hybrid mode returns 503 `OPENAI_NOT_CONFIGURED` at preflight (same code path as `start_judgment_generation`); pure-UBI converters (`ctr_threshold`, `dwell_time`) still work.
- **`infra_adapter_solr`** — co-ships in MVP2. UBI on Solr lights up when that feature extends `clusters_engine_type_check` to include `'solr'`. Status: planned (sibling feature). Risk if missing for the *Solr UBI story*: Capability B's Solr nudge arm stays dark; ES + OpenSearch UBI ship unaffected. This feature does NOT block on `infra_adapter_solr` for the ES/OpenSearch path.
- **`feat_pr_metric_confidence`** (shipped 2026-05-21) — Capability D's PR-body framing builds on the shipped confidence shape. Status: implemented. Risk if missing: N/A.
- **`feat_contextual_help`** (shipped 2026-05-15) — Capability E's `HelpPopover` glossary backing reuses the shipped idiom. Status: implemented. Risk if missing: N/A.
- **`chore_form_dropdown_primitive`** — the form-select discipline lint guard at `ui/src/__tests__/components/common/form-select-discipline.test.tsx`. Status: shipped. Risk if missing: converter picker could regress to inline `<SelectItem value="...">` and drift from backend Literal.

## 6) Actors and roles

- **Primary actor:** Relevance Engineer — registers clusters, configures UBI converters, runs UBI / hybrid judgment generation, reviews completed lists.
- **Role model:** N/A — RelyLoop is single-tenant + no auth through GA v1 per [`docs/01_architecture/tech-stack.md`](../../../../01_architecture/tech-stack.md).
- **Permission boundaries:** N/A — every operator on the install can run every UBI endpoint.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

**Activates at MVP3** per [`docs/01_architecture/data-model.md` §"Forthcoming: audit_log"](../../../../01_architecture/data-model.md) and [CLAUDE.md "Activates at MVP3"](../../../../../CLAUDE.md). MVP2 (this release) is pre-`audit_log`. When MVP3 lands, this feature's audit-event instrumentation matrix is:

| Event type | Emitted by | Visibility | Metadata fields |
|---|---|---|---|
| `judgment_list.ubi_generation_requested` | `start_ubi_judgment_generation` (before `db.commit()`) | tenant-visible | `{judgment_list_id, converter, query_set_id, cluster_id, target, since, until, llm_fill_threshold?, min_impressions_threshold}` |
| `judgment_list.ubi_generation_completed` | `generate_judgments_from_ubi` Arq job (terminal-status flip) | system | `{judgment_list_id, status, judgment_count, click_count, llm_count, coverage_pct, head_pairs, tail_pairs, llm_fill_calls, duration_ms, failed_reason?}` |
| `judgment_list.source_filter_widened` | N/A — the `?source=` filter widening (D-3) is a schema change, not a per-request mutation |
| `cluster.ubi_readiness_probed` | `GET /api/v1/clusters/{id}/ubi-readiness` | system | `{cluster_id, rung, covered_pairs_pct?, head_covered?, probe_duration_ms}` |

**No credentials, tokens, or PII** in metadata — `target` is the operator-supplied index name (`products`, `articles`), `query_set_id` / `cluster_id` are UUIDs.

## 7) Functional requirements

### FR-1: UBI reader — engine-agnostic two-index scan with client-side join

- **Requirement:**
  - The system **MUST** expose a `UbiReader` class in `backend/app/services/ubi_reader.py` with method `async read_features(adapter: SearchAdapter, target: str, since: datetime, until: datetime | None, query_filter: str | None, max_queries: int = 5000) -> dict[tuple[str, str], FeatureVec]`.
  - The reader **MUST** issue exactly two scrolling `SearchAdapter.search_batch` calls — one against the `ubi_queries` index, one against `ubi_events` — and perform the `query_id` join client-side. No new adapter method.
  - The reader **MUST** disambiguate UBI events emitted from multiple operator applications against the same UBI indices using `target` (the live index being tuned).
  - The reader **MUST** raise `UbiNotEnabledError` when `get_schema('ubi_queries')` returns `TargetNotFoundError`.
  - The reader **MUST** return an empty dict when `ubi_queries` exists but the `(since, until)` window yields zero events. The empty-features case is the **race-condition fallback** — the dispatcher's preflight count check (FR-4 U-D / U-D2) catches the obvious "no data" case sync (HTTP 422 `UBI_INSUFFICIENT_DATA`); the worker terminal `failed` path with `failed_reason='UBI_INSUFFICIENT_DATA'` only fires when an in-flight window changes between preflight and execution (essentially impossible in practice; covered for safety).
- **Notes:** `FeatureVec` is a Pydantic model in `backend/app/domain/ubi/features.py`: `{click_count: int, impression_count: int, corrected_ctr: float, dwell_mean_seconds: float | None, conversion_rate: float | None, refinement_rate: float | None}`.

### FR-2: SignalsConverter Protocol + three converters

- **Requirement:**
  - The system **MUST** define a `SignalsConverter` Protocol in `backend/app/domain/ubi/converter.py`: `async convert(features: dict[tuple[str, str], FeatureVec], config: ConverterConfig) -> dict[tuple[str, str], int]` returning ratings in `{0, 1, 2, 3}`. The Protocol is async because the hybrid converter awaits an LLM-fill callback; the two pure converters are trivially async (they `return …` without awaiting anything). Keeping one Protocol shape (instead of splitting sync/async) lets the worker treat all three uniformly.
  - The system **MUST** ship three concrete implementations:
    - `CtrThresholdConverter` (pure UBI, no LLM I/O) — maps position-bias-corrected CTR to 0/1/2/3 via configurable thresholds. Defaults: `{1: 0.05, 2: 0.15, 3: 0.30}`.
    - `DwellTimeThresholdConverter` (pure UBI, no LLM I/O) — maps post-click dwell-time (seconds) to ratings. Defaults: `{1: 10.0, 2: 30.0, 3: 90.0}`.
    - `HybridUbiLlmConverter` — applies an inner pure converter (`CtrThresholdConverter` by default; `DwellTimeThresholdConverter` if `converter_config.inner == 'dwell_time'`) where `impression_count >= llm_fill_threshold` (default 20); below the threshold, defers the pair to LLM-fill via an injected callback `llm_rate: Callable[[list[tuple[str, str, str]]], Awaitable[dict[tuple[str, str], int]]]` (taking `(query_id, doc_id, query_text)` tuples and returning ratings). The worker constructs the converter with the callback bound to a thin wrapper over `rate_query_batch` so the existing daily-budget gate and capability cache fire unchanged.
  - Each converter **MUST** be instantiable from a JSON-serializable `ConverterConfig` so the request body can pass `converter_config?: dict` through unchanged (the LLM callback is injected separately at construction time — not serialized into config).
  - **Anti-pattern:** the hybrid converter MUST NOT instantiate its own `openai.AsyncClient(...)`. The LLM callback is the only legal LLM entry point — it routes through `rate_query_batch` + `peek_daily_total` + `record_cost` from [`backend/app/llm/budget_gate.py`](../../../../../backend/app/llm/budget_gate.py) (Absolute Rules #3 / #8 / #10).

### FR-3: API endpoint — `POST /api/v1/judgments/generate-from-ubi`

- **Requirement:**
  - The system **MUST** add the endpoint at [`backend/app/api/v1/judgments.py`](../../../../../backend/app/api/v1/judgments.py) with request shape `CreateJudgmentListFromUbiRequest`:
    ```
    name: str (min 1, max 256, unique on judgment_lists.name)
    description: str | None (max 2000)
    query_set_id: str (uuid)
    cluster_id: str (uuid)
    target: str (min 1, max 256)
    since: datetime (ISO-8601 UTC; UBI event timestamp lower bound, inclusive)
    until: datetime | None (UBI event timestamp upper bound, exclusive; defaults to now)
    converter: Literal["ctr_threshold", "dwell_time", "hybrid_ubi_llm"]
    converter_config: dict[str, Any] | None
    llm_fill_threshold: int | None (default 20; only honored when converter == "hybrid_ubi_llm")
    min_impressions_threshold: int | None (default 100; total events required to consider the window valid)
    mapping_strategy: Literal["reject", "first_match", "most_recent"] | None (default "reject")
    current_template_id: str | None (uuid; REQUIRED when converter == "hybrid_ubi_llm", REJECTED otherwise — provides the Jinja template the LLM-fill path uses to retrieve docs per query)
    rubric: str | None (REQUIRED when converter == "hybrid_ubi_llm", REJECTED otherwise — passed through to rate_query_batch's system prompt for LLM-fill calls; mirrors the existing LLM-judgment rubric contract)
    ```
  - The request schema **MUST** include a Pydantic `model_validator` that enforces the conditional requiredness: when `converter == "hybrid_ubi_llm"`, `current_template_id` and `rubric` MUST be non-null (else 422 `VALIDATION_ERROR` with a per-field detail); when `converter ∈ {"ctr_threshold", "dwell_time"}`, both fields MUST be absent or null (pure UBI doesn't call the LLM — accepting them silently would create a confusing partial-config state).
  - The endpoint **MUST** return HTTP 202 with `GenerateJudgmentsResponse{judgment_list_id, status: "generating"}` on success.
  - The endpoint **MUST** delegate to `start_ubi_judgment_generation` in `backend/app/services/agent_judgments_dispatch.py`.
  - The endpoint **MUST NOT** accept the `llm` value for `converter` — the LLM path is `POST /api/v1/judgments/generate`. The picker UI surfaces `llm` as an option but routes to the LLM endpoint when chosen.

### FR-4: Shared service-layer dispatcher `start_ubi_judgment_generation`

- **Requirement:**
  - The system **MUST** add `start_ubi_judgment_generation` in [`backend/app/services/agent_judgments_dispatch.py`](../../../../../backend/app/services/agent_judgments_dispatch.py) alongside the existing `start_judgment_generation`.
  - The dispatcher **MUST** run preflight in this order:
    - **U-A.** FK resolution: cluster, query_set, `current_template_id` if `converter == 'hybrid_ubi_llm'` (required per FR-3 conditional rule).
    - **U-B.** Consistency: `query_set.cluster_id == request.cluster_id`; for hybrid mode `template.engine_type == cluster.engine_type` (mirrors `start_judgment_generation` D.1).
    - **U-C.** UBI readiness probe: `get_schema('ubi_queries')` — 412 `UBI_NOT_ENABLED` on missing. Use the same `UbiReader._probe_enabled(adapter)` helper as FR-7's readiness endpoint to keep one probe shape.
    - **U-D.** Window validity: `since < (until or now)`; if `until - since > 90 days` reject with 422 `UBI_WINDOW_TOO_LARGE`.
    - **U-D2.** **Coverage gate (sync 422 — locked here per cycle-3 finding `ubi-insufficient-data-sync-async-contract`).** Issue one `_count` aggregation against `ubi_events` filtered by `(application=target, timestamp >= since, timestamp < until)`. If `count < min_impressions_threshold` (default 100), reject sync with 422 `UBI_INSUFFICIENT_DATA` and include the actual count + the threshold in `detail.message`. For `converter ∈ {'ctr_threshold', 'dwell_time'}` the message also includes "Try hybrid_ubi_llm converter for LLM-fill on sparse pairs"; for `converter == 'hybrid_ubi_llm'` it cites the window-widening recovery path. Cost budget for U-D2: one `_count` call (typically <100ms against any reasonably-sized cluster). The worker still carries a terminal `failed_reason='UBI_INSUFFICIENT_DATA'` path as a race-condition fallback (FR-1 + FR-5).
    - **U-E.** Hybrid-mode LLM prerequisites (only when `converter == 'hybrid_ubi_llm'`): rerun the existing `start_judgment_generation` preflight steps A (key configured), B (capability cache), B.1 (model pricing), C (daily budget peek). Reuse via refactored shared helpers.
    - **U-F.** Oversized query set: `count_queries_in_set > 10_000` → 422.
    - **U-G.** INSERT `judgment_lists` row with `status='generating'`, `rubric=<converter description for non-hybrid; the operator-supplied rubric for hybrid>`, `current_template_id=request.current_template_id` (NULL for non-hybrid), and **`generation_params` JSONB** (new column from migration 0021) populated with the JSON-serialized request shape `{generation_kind: 'ubi', target, since, until, converter, converter_config, llm_fill_threshold, min_impressions_threshold, mapping_strategy}` so the boot-time resume sweep can reconstruct the worker call. LLM lists leave `generation_params=NULL`.
    - **U-H.** Best-effort Arq enqueue (`generate_judgments_from_ubi` job with payload `(judgment_list_id,)`; the worker reads `generation_params` from the row on entry).
  - The dispatcher **MUST** raise `HTTPException` with the spec §8.5 error envelope so router and agent-tool dispatcher both surface identical wire shapes.
  - The dispatcher **MUST** factor U-A / U-B / U-E / U-F / U-G / U-H out as shared helpers used by `start_judgment_generation` too (refactor in this PR — duplication is the failure the dispatcher was created to prevent). The shared `_insert_generating_list_and_enqueue(...)` helper takes a `kind: Literal["llm", "ubi"]` discriminator and the per-kind params; the rest of the body (UNIQUE-name catch + commit + enqueue) is unified.

### FR-5: Background worker `generate_judgments_from_ubi`

- **Requirement:**
  - The system **MUST** add `generate_judgments_from_ubi` in [`backend/workers/judgments.py`](../../../../../backend/workers/judgments.py) alongside `generate_judgments_llm`.
  - The worker **MUST** mirror the `generate_judgments_llm` lifecycle:
    1. Load `judgment_list` row → bail if missing or already-terminal. Read `generation_params` JSONB to reconstruct the worker call shape (target, since, until, converter, converter_config, llm_fill_threshold, mapping_strategy). Bail with `status='failed'`, `failed_reason='MISSING_GENERATION_PARAMS'` if the column is NULL on a row the worker received (the dispatcher always populates it for UBI lists — this guards a partial-deploy race).
    2. Build adapter via `build_adapter(cluster)`.
    3. Construct `UbiReader` → `await read_features(adapter, target, since, until, query_filter, max_queries)`.
    4. Translate features → ratings via the chosen converter (await per FR-2 async Protocol). For `hybrid_ubi_llm`, the converter is constructed with the LLM callback bound to a worker-local async function that wraps `rate_query_batch` per the contract in FR-2.
    5. Apply the locked `mapping_strategy` (D-4) per query when joining UBI `user_query` strings to `query_set.queries.query_text`. **Per-query ambiguous mappings under `mapping_strategy='reject'` are skipped, NOT terminal** (cycle-3 finding `ambiguous-mapping-behavior-contradictory`) — log WARN with `event_type='ubi_per_query_skipped_ambiguous_mapping'`, increment a per-list counter, continue the loop. The counter surfaces in calibration JSONB as `ambiguous_query_skip_count`.
    6. Bulk-insert judgments with `source='click'` (UBI rows) and `source='llm'` (hybrid LLM-fill rows), `rater_ref='ubi:{converter}'` / `rater_ref=f'openai:{model}'` respectively.
    7. Write calibration JSONB: `{coverage_pct, head_pairs, tail_pairs, position_bias_prior_id, llm_fill_calls?, ambiguous_query_skip_count, sparse_query_skip_count}`.
    8. Terminal-status flip: `status='complete'` on clean loop; `status='failed'` + structured `failed_reason` on `UbiInsufficientDataError` (race-condition fallback only — preflight covers the sync case per FR-4 U-D2), `BudgetExceededError`, `UnknownModelPricingError`, or unexpected exception. Per-query ambiguity from `mapping_strategy='reject'` is NOT a terminal cause — it's a skip; if EVERY query skips, the list still completes with `judgment_count=0` and `ambiguous_query_skip_count == query_set.size`, and the operator can re-submit with `mapping_strategy='first_match'` or `'most_recent'`.
  - Hybrid-mode LLM-fill **MUST** route through the existing `rate_query_batch` + `peek_daily_total` + `record_cost` from [`backend/app/llm/budget_gate.py`](../../../../../backend/app/llm/budget_gate.py). No direct `openai.AsyncClient(...)` instances.
  - The worker **MUST** be idempotent against re-runs via the `judgments_unique_key` UNIQUE constraint + ON CONFLICT DO NOTHING semantics in `repo.bulk_create_judgments`.
  - Per-query failures (ambiguous mapping under `reject`, sparse signal on one query, hybrid LLM-fill rate-limit) **MUST** be isolated — log WARN, skip the query, increment the matching skip counter in calibration. Terminal `failed` only on global failures (race-condition `UBI_INSUFFICIENT_DATA`, budget exhausted, capability broken, unexpected exception).

### FR-6: Chat-agent tool `generate_judgments_from_ubi`

- **Requirement:**
  - The system **MUST** add `backend/app/agent/tools/judgments/generate_judgments_from_ubi.py` following the triad pattern from `generate_judgments_llm.py`:
    - `GenerateJudgmentsFromUbiArgs` (Pydantic `BaseModel`)
    - `generate_judgments_from_ubi_impl(args, ctx)` (async impl)
    - `GENERATE_JUDGMENTS_FROM_UBI_TOOL` (`ChatCompletionToolParam`)
  - The tool **MUST** be registered in [`backend/app/agent/tools/__init__.py`](../../../../../backend/app/agent/tools/__init__.py) `TOOLS` + `TOOL_REGISTRY` + `TOOL_ARG_MODELS`. The module-load drift assertion at line 232–236 will fail if registration is incomplete.
  - The tool **MUST** be classified as MUTATING — the orchestrator's confirmation guard requires affirmative user message before dispatch (per `feat_chat_agent` §19 Decision log).
  - The orchestrator system prompt **MUST** update to prefer UBI when the cluster's readiness rung ≥ 1 (probed via `get_schema('ubi_queries')` at conversation start when judgment-generation intent is detected), and fall back to `generate_judgments_llm` otherwise.

### FR-7: Readiness probe + ladder endpoint

- **Requirement:**
  - The system **MUST** add `GET /api/v1/clusters/{cluster_id}/ubi-readiness?query_set_id=<uuid>&target=<string>` in [`backend/app/api/v1/clusters.py`](../../../../../backend/app/api/v1/clusters.py) returning `{rung: UbiReadinessRungWire, covered_pairs_pct: float | None, head_covered: bool | None, checked_at: datetime}`.
  - The endpoint **REQUIRES** `?query_set_id` and `?target` query parameters (cycle-3 finding `readiness-endpoint-missing-scope-inputs`) because rung classification is per-(cluster, query_set, target) — coverage on `query_set_A/products` says nothing about `query_set_B/articles`. Omitting either returns 422 `VALIDATION_ERROR`.
  - Rung classification (fixed MVP2 defaults — operator-configurable deferred per OQ7 recommendation):
    - **rung_0** — `get_schema('ubi_queries')` raises `TargetNotFoundError`. `covered_pairs_pct` and `head_covered` are `null` (no UBI data to assess).
    - **rung_1** — `ubi_queries` present, but for the `(query_set_id, target)` pair fewer than 50% of query-set queries have `impression_count >= min_impressions_threshold` (default 100, scoped to the last 30 days).
    - **rung_2** — head covered (≥50% of query-set queries above threshold), tail thin. `head_covered=true`.
    - **rung_3** — ≥`min_impressions_threshold` impressions on every query in the set, last 30 days.
  - The endpoint **MUST** complete within 2 seconds (a snapshot read; not a window-wide aggregation) — uses `_count` aggregations on `ubi_events` filtered by `(application=target, timestamp >= now-30d, query_id IN <query_set ids>)`.
  - The endpoint **MUST** be cached server-side per `(cluster_id, query_set_id, target)` for 60 seconds in Redis (key shape `ubi-readiness:{cluster_id}:{query_set_id}:{target}`) to avoid hammering the cluster on every page navigation. The frontend `useUbiReadiness(clusterId, querySetId, target)` hook layers a 60s React Query stale time on top so the worst-case cluster hit rate is one request per minute per scope tuple.

### FR-8: Frontend converter picker + on-ramp UX

- **Requirement:**
  - The system **MUST** extend [`ui/src/components/query-sets/generate-judgments-dialog.tsx`](../../../../../ui/src/components/query-sets/generate-judgments-dialog.tsx) with:
    - A **method** `<Select>` with four options (`llm`, `ctr_threshold`, `dwell_time`, `hybrid_ubi_llm`) using `JUDGMENT_GENERATION_METHOD_VALUES.map(...)` imported from `@/lib/enums`. Labels per D-2. The picker drives endpoint routing: `llm` → `POST /api/v1/judgments/generate` (the existing endpoint); the other three → `POST /api/v1/judgments/generate-from-ubi` with the picker value passed as the request `converter` field.
    - Default selection from `useUbiReadiness(cluster_id, query_set_id)` hook: rung_0 → `llm`; rung_1 / rung_2 → `hybrid_ubi_llm`; rung_3 → `ctr_threshold`.
    - UBI window controls (`since` date-time picker + optional `until`); shown only when converter ≠ `llm`. Default `since = now - 30 days`.
    - LLM-fill threshold input (default 20); shown only when converter == `hybrid_ubi_llm`.
    - `InfoTooltip` + `HelpPopover` under each converter option backed by glossary keys (`judgment.converter.llm`, `judgment.converter.ubi`, `judgment.converter.hybrid`).
  - The system **MUST** render the dismissible nudge (`ui/src/components/clusters/ubi-onramp-nudge.tsx`) above the dialog body when `rung === 'rung_0'`. Engine-aware copy switches on `cluster.engine_type`.
  - The system **MUST** render the sparse-data recommendation card when the request would have returned 422 `UBI_INSUFFICIENT_DATA` (caught client-side by inspecting `useUbiReadiness().rung === 'rung_1'` before submit). Card includes a "Switch to hybrid" button that flips the picker to `hybrid_ubi_llm`.
  - The system **MUST** display the value-delta on the judgment-list detail page (`ui/src/app/judgments/[id]/page.tsx`) for UBI/hybrid lists: `coverage_pct` always; `vs. previous LLM list X` delta only when a prior LLM list exists on the same `query_set_id` (resolved via a server-side helper `repo.list_judgment_lists(query_set_id=…, sort='created_at:desc')`).

### FR-9: Wire-value contract — `converter` + `method` + `readiness rung`

The picker's value space is intentionally larger than the new endpoint's accepted set: the picker chooses between *all four* judgment-generation methods (including `llm`, which routes to the existing `POST /api/v1/judgments/generate` endpoint), while the new `POST /api/v1/judgments/generate-from-ubi` endpoint accepts only the *three UBI converters*. Two distinct enums are required so the backend can reject `llm` at the new endpoint while the UI can still surface it as a first-class picker option.

- **Requirement:**
  - The system **MUST** define `UbiConverterKind = Literal["ctr_threshold", "dwell_time", "hybrid_ubi_llm"]` in [`backend/app/api/v1/schemas.py`](../../../../../backend/app/api/v1/schemas.py). This is the *request-side* enum — the value the new UBI endpoint accepts on `CreateJudgmentListFromUbiRequest.converter`.
  - The system **MUST** define `JudgmentGenerationMethodWire = Literal["llm", "ctr_threshold", "dwell_time", "hybrid_ubi_llm"]` in the same file. This is the *picker-side* enum — the union of all 4 generation methods the UI surfaces. The `llm` value routes the submit to `POST /api/v1/judgments/generate`; the other three route to `POST /api/v1/judgments/generate-from-ubi`. The two are kept in sync structurally — `UbiConverterKind ⊂ JudgmentGenerationMethodWire` — but they are distinct types so static checks at the endpoint boundary correctly reject `llm`.
  - The system **MUST** define `UbiReadinessRungWire = Literal["rung_0", "rung_1", "rung_2", "rung_3"]` in the same file.
  - The system **MUST** add `JUDGMENT_GENERATION_METHOD_VALUES` (4 values; mirrors `JudgmentGenerationMethodWire`), `UBI_CONVERTER_VALUES` (3 values; mirrors `UbiConverterKind`), and `UBI_READINESS_RUNG_VALUES` (4 values) arrays to [`ui/src/lib/enums.ts`](../../../../../ui/src/lib/enums.ts), each with the `// Values must match backend/app/api/v1/schemas.py <Symbol>` comment per the source-of-truth policy. The converter `<Select>` in the generate-judgments dialog consumes `JUDGMENT_GENERATION_METHOD_VALUES` (so the picker can show all 4 options); the future advanced/CLI surface that hits the UBI endpoint directly consumes `UBI_CONVERTER_VALUES`.
  - The system **MUST** widen `JUDGMENT_SOURCE_FILTER_VALUES` in `enums.ts` from `['llm', 'human']` to `['llm', 'human', 'click']` and update `JudgmentSourceFilterWire` in `schemas.py` correspondingly (D-3).

### FR-10: `_SourceBreakdown` evolution

- **Requirement:**
  - The system **MUST** evolve [`backend/app/api/v1/schemas.py`](../../../../../backend/app/api/v1/schemas.py) `_SourceBreakdown` from `{llm: int, human: int}` to `{llm: int, human: int, click: int}` with the invariant `llm + human + click == judgment_count`. (D-1.)
  - The system **MUST** update [`backend/app/api/v1/judgments.py`](../../../../../backend/app/api/v1/judgments.py) `_detail()` to populate `click=breakdown.get("click", 0)`.
  - The system **MUST** update [`backend/app/db/repo/judgment.py`](../../../../../backend/app/db/repo/judgment.py) `source_breakdown_for_list` to return all three keys.
  - The system **MUST** update existing contract tests asserting `{llm, human}` to assert `{llm, human, click}`; on LLM-only lists `click == 0`.

### FR-11: Position-bias prior (optional operator override)

- **Requirement:**
  - The system **MUST** support an optional `UBI_POSITION_BIAS_PRIOR_FILE` env var pointing to a JSON file with shape `{positions: {[rank: int]: float}}` (e.g., `{positions: {1: 1.0, 2: 0.65, 3: 0.45, ...}}`).
  - The system **MUST** default to an uninformed prior (all positions weighted 1.0 — equivalent to raw CTR) when the env var is absent or the file is empty.
  - The system **MUST NOT** crash on a malformed prior file — log a structured WARN and fall back to the uninformed prior.

## 8) API and data contract baseline

### 8.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/judgments/generate-from-ubi` | Start a UBI-derived judgment list (CTR / dwell / hybrid) | `UBI_NOT_ENABLED` (412), `UBI_INSUFFICIENT_DATA` (422), `UBI_WINDOW_TOO_LARGE` (422), `VALIDATION_ERROR` (422), `CLUSTER_NOT_FOUND` (404), `QUERY_SET_NOT_FOUND` (404), `TEMPLATE_NOT_FOUND` (404 — hybrid only), `JUDGMENT_LIST_NAME_TAKEN` (409), `OPENAI_NOT_CONFIGURED` (503 — hybrid only), `LLM_PROVIDER_INCAPABLE` (503 — hybrid only), `UNKNOWN_MODEL_PRICING` (503 — hybrid only), `OPENAI_BUDGET_EXCEEDED` (503 — hybrid only). Note: `UbiQueryMappingAmbiguous` is NOT an endpoint error — per-query mapping ambiguity is a worker-side skip (logged with `event_type='ubi_per_query_skipped_ambiguous_mapping'`, counted into `calibration.ambiguous_query_skip_count`), not a 422; see FR-5 step 5 + cycle-3 finding `ambiguous-mapping-behavior-contradictory`. |
| `GET` | `/api/v1/clusters/{cluster_id}/ubi-readiness` | Probe the cluster's UBI rung (0–3) for the operator's most recent query set | `CLUSTER_NOT_FOUND` (404), `CLUSTER_UNREACHABLE` (503) |

The `?source=` query parameter on the existing `GET /api/v1/judgment-lists/{id}/judgments` is **widened** to accept `click` (was `Literal["llm", "human"]`, now `Literal["llm", "human", "click"]`).

The `_SourceBreakdown` sub-shape on `GET /api/v1/judgment-lists/{id}` is **evolved in-place** to `{llm: int, human: int, click: int}`.

### 8.2 Contract rules

- Every error response body **MUST** include `detail.error_code` (machine-readable, stable, screaming-snake-case).
- Every error response body **MUST** include `detail.retryable: bool` (`false` for terminal-config / validation failures; `true` for budget / capability / unreachable failures).
- Status codes **MUST** be deterministic per scenario (per the §8.5 catalog).
- Cross-tenant unauthorized access: N/A — single-tenant install.

### 8.3 Response examples

**Success — `POST /api/v1/judgments/generate-from-ubi` (202 Accepted):**
```json
{
  "judgment_list_id": "0190a3b7-4c81-7000-8f00-1a2b3c4d5e6f",
  "status": "generating"
}
```

**Failure — UBI not enabled (412 Precondition Failed):**
```json
{
  "detail": {
    "error_code": "UBI_NOT_ENABLED",
    "message": "ubi_queries index not found on cluster acme-search; install the OpenSearch UBI plugin and enable event capture in your application",
    "retryable": false
  }
}
```

**Failure — Sparse UBI data (422 Unprocessable Entity):**
```json
{
  "detail": {
    "error_code": "UBI_INSUFFICIENT_DATA",
    "message": "only 23 UBI events match the window 2026-04-29..2026-05-29 against query_set 0190…; need at least 100 (min_impressions_threshold). Try hybrid_ubi_llm converter for LLM-fill on sparse pairs",
    "retryable": false
  }
}
```

**Failure — Window too large (422):**
```json
{
  "detail": {
    "error_code": "UBI_WINDOW_TOO_LARGE",
    "message": "since..until window is 120 days; max 90 days per request (cost guardrail). Run multiple narrower windows and merge via separate judgment lists.",
    "retryable": false
  }
}
```

**Success — `GET /api/v1/clusters/{id}/ubi-readiness` (200 OK, rung 2):**
```json
{
  "rung": "rung_2",
  "covered_pairs_pct": 0.78,
  "head_covered": true,
  "checked_at": "2026-05-29T14:32:11Z"
}
```

**Success — `GET /api/v1/clusters/{id}/ubi-readiness` (200 OK, rung 0):**
```json
{
  "rung": "rung_0",
  "covered_pairs_pct": null,
  "head_covered": null,
  "checked_at": "2026-05-29T14:32:11Z"
}
```

**Success — `GET /api/v1/judgment-lists/{id}` (200 OK, hybrid list with click rows):**
```json
{
  "id": "0190…",
  "name": "products-q2-2026-hybrid",
  "description": null,
  "query_set_id": "0190…",
  "cluster_id": "0190…",
  "target": "products",
  "current_template_id": "0190…",
  "rubric": "Generated via hybrid_ubi_llm converter (window 2026-04-29..2026-05-29; llm_fill_threshold=20)",
  "status": "complete",
  "failed_reason": null,
  "judgment_count": 1432,
  "source_breakdown": { "llm": 312, "human": 0, "click": 1120 },
  "calibration": {
    "coverage_pct": 0.91,
    "head_pairs": 1120,
    "tail_pairs": 312,
    "position_bias_prior_id": "uninformed",
    "llm_fill_calls": 312
  },
  "created_at": "2026-05-29T14:30:00Z"
}
```

### 8.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `converter` (request body of `POST /judgments/generate-from-ubi`) | `ctr_threshold`, `dwell_time`, `hybrid_ubi_llm` | `backend/app/api/v1/schemas.py` `UbiConverterKind` (request-side: 3 values). | `ui/src/lib/enums.ts` `UBI_CONVERTER_VALUES` (3 values; used by any future advanced/CLI surface that hits the endpoint directly) |
| `method` (UI picker — drives endpoint routing) | `llm`, `ctr_threshold`, `dwell_time`, `hybrid_ubi_llm` | `backend/app/api/v1/schemas.py` `JudgmentGenerationMethodWire` (picker-side: 4 values; superset of `UbiConverterKind` plus `llm` for the existing LLM endpoint) | `ui/src/components/query-sets/generate-judgments-dialog.tsx` converter `<Select>`; `ui/src/lib/enums.ts` `JUDGMENT_GENERATION_METHOD_VALUES` (4 values). `llm` selection routes the submit to `POST /api/v1/judgments/generate`; the other three route to `POST /api/v1/judgments/generate-from-ubi`. |
| `mapping_strategy` (request body, optional) | `reject` (default), `first_match`, `most_recent` | `backend/app/api/v1/schemas.py` `UbiMappingStrategyWire` | Future advanced-settings panel; not exposed in MVP2 dialog default form |
| `rung` (response — `GET /clusters/{id}/ubi-readiness`) | `rung_0`, `rung_1`, `rung_2`, `rung_3` | `backend/app/api/v1/schemas.py` `UbiReadinessRungWire` | `ui/src/lib/enums.ts` `UBI_READINESS_RUNG_VALUES`; `ui/src/components/clusters/ubi-rung-badge.tsx` |
| `?source` (existing filter on `GET /judgment-lists/{id}/judgments`) | `llm`, `human`, `click` (widened from `{llm, human}` per D-3) | `backend/app/api/v1/schemas.py` `JudgmentSourceFilterWire` | `ui/src/lib/enums.ts` `JUDGMENT_SOURCE_FILTER_VALUES` |
| `source_breakdown` keys (response on `GET /judgment-lists/{id}`) | `llm`, `human`, `click` (evolved from `{llm, human}` per D-1) | `backend/app/api/v1/schemas.py` `_SourceBreakdown` | `ui/src/app/judgments/[id]/page.tsx` breakdown rendering |
| `judgments.source` (per-row, persisted) | `llm`, `human`, `click` | `backend/app/db/models/judgment.py` `judgments_source_check` CHECK + `JudgmentSourceWire = Literal["llm", "human", "click"]` (unchanged) | `ui/src/lib/enums.ts` `JUDGMENT_SOURCE_VALUES` (unchanged) |

UI labels for the converter picker (per D-2):
- `llm` → "LLM-as-judge"
- `ctr_threshold` → "UBI (click-through)"
- `dwell_time` → "UBI (dwell-time)"
- `hybrid_ubi_llm` → "Hybrid UBI + LLM"

### 8.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| `UBI_NOT_ENABLED` | 412 | `ubi_queries` index does not exist on the cluster. Operator must install the UBI plugin + enable event capture. Capability B nudge surfaces this state inline; the 412 envelope is the structured form. |
| `UBI_INSUFFICIENT_DATA` | 422 | Fewer than `min_impressions_threshold` (default 100) UBI events match the `(since, until, target)` window. Returned **sync from preflight U-D2**; Capability C surfaces a "Switch to hybrid" recommendation card; the 422 envelope is the structured form. The worker also carries a terminal `failed_reason='UBI_INSUFFICIENT_DATA'` path as a race-condition fallback for the (essentially impossible) case where data disappears between preflight and execution. |
| `UBI_WINDOW_TOO_LARGE` | 422 | `(until - since) > 90 days`. Cost guardrail — operators run multiple narrower windows and merge via separate lists. |
| `VALIDATION_ERROR` | 422 | Generic request-shape failures (FK consistency, oversize query set, etc.) — reuses the existing envelope from `feat_llm_judgments`. |
| `CLUSTER_NOT_FOUND` | 404 | `cluster_id` does not resolve. Existing code, unchanged. |
| `QUERY_SET_NOT_FOUND` | 404 | `query_set_id` does not resolve. Existing code, unchanged. |
| `TEMPLATE_NOT_FOUND` | 404 | Hybrid mode only — `current_template_id` does not resolve. Reused from `start_judgment_generation` preflight D (see [`backend/app/services/agent_judgments_dispatch.py:146-152`](../../../../../backend/app/services/agent_judgments_dispatch.py#L146-L152)); inherited verbatim by the shared `_resolve_cluster_query_set` helper in FR-4. |
| `JUDGMENT_LIST_NAME_TAKEN` | 409 | `name` collides with an existing `judgment_lists.name`. Existing code, unchanged. |
| `CLUSTER_UNREACHABLE` | 503 | Engine reachability failure during the readiness probe. Retryable. Existing code, unchanged. |
| `OPENAI_NOT_CONFIGURED` | 503 | Hybrid-mode only — operator hasn't configured a key. Existing code (Absolute Rule #2), unchanged. |
| `LLM_PROVIDER_INCAPABLE` | 503 | Hybrid-mode only — capability cache miss or structured-output unsupported. Existing code, unchanged. |
| `UNKNOWN_MODEL_PRICING` | 503 | Hybrid-mode only — `OPENAI_MODEL` not in `cost_model`. Existing code, unchanged. |
| `OPENAI_BUDGET_EXCEEDED` | 503 | Hybrid-mode only — daily-budget peek already at cap. Existing code, unchanged. Retryable. |

## 9) Data model and state transitions

### One additive migration: `0021_judgment_lists_generation_params.py`

**Modified table: `judgment_lists`** — adds one nullable JSONB column to support UBI worker resume:

- `generation_params` (`JSONB`, nullable) — UBI lists populate this at INSERT with the JSON-serialized request shape so the boot-time resume sweep can reconstruct the worker call without depending on the Arq job payload (cycle-3 finding `ubi-generation-params-not-persisted`). LLM lists leave it NULL — `current_template_id` + `rubric` already carry LLM resume state.

Migration `0021_judgment_lists_generation_params.py`:

```python
def upgrade() -> None:
    op.add_column(
        "judgment_lists",
        sa.Column("generation_params", postgresql.JSONB, nullable=True),
    )

def downgrade() -> None:
    op.drop_column("judgment_lists", "generation_params")
```

Round-trip verified via `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` per Absolute Rule #5. Pre-existing LLM judgment lists pass through both directions cleanly because the column is nullable and never read on the LLM path.

**Modified columns / responses (not migrations — Pydantic-level evolutions):**

- **`_SourceBreakdown` (Pydantic, [`backend/app/api/v1/schemas.py:864-873`](../../../../../backend/app/api/v1/schemas.py#L864-L873))** — adds `click: int` field. Invariant evolves to `llm + human + click == judgment_count`. (D-1.)
- **`JudgmentSourceFilterWire` (Pydantic, [`backend/app/api/v1/schemas.py:833`](../../../../../backend/app/api/v1/schemas.py#L833))** — widens from `Literal["llm", "human"]` to `Literal["llm", "human", "click"]`. (D-3.)
- **`JudgmentList.calibration` (JSONB column, existing)** — adds new content shape for UBI lists: `{coverage_pct, head_pairs, tail_pairs, position_bias_prior_id, llm_fill_calls?, ambiguous_query_skip_count, sparse_query_skip_count}`. The column is free-form JSONB; no schema change. LLM and UBI lists are distinguished by the presence of `cohens_kappa` (LLM/calibrated) vs `coverage_pct` (UBI). When `POST /judgment-lists/{id}/calibration` runs against a UBI list later, the merge appends `cohens_kappa` + sibling keys to the existing UBI-shaped object.

### Required invariants

- **UNIQUE `(judgment_list_id, query_id, doc_id)`** on `judgments` — enforced by existing `judgments_unique_key` constraint. UBI worker's `bulk_create_judgments` ON CONFLICT DO NOTHING relies on it for resume idempotency.
- **`source IN ('llm', 'human', 'click')`** on `judgments` — enforced by existing `judgments_source_check` CHECK. No change.
- **`status IN ('generating', 'complete', 'failed')`** on `judgment_lists` — enforced by existing `judgment_lists_status_check` CHECK. No change. UBI worker terminal flips use the same three states.
- **`rating BETWEEN 0 AND 3`** on `judgments` — enforced by existing `judgments_rating_check` CHECK. Each `SignalsConverter` MUST return ratings in `{0, 1, 2, 3}`.
- **`name`** uniqueness on `judgment_lists` (existing UNIQUE on the column) — UBI `POST` collides with 409 `JUDGMENT_LIST_NAME_TAKEN` on conflict.
- **`llm + human + click == judgment_count`** on `_SourceBreakdown` — invariant evolved from the cycle-2 F6 two-term form.

### State transitions

`judgment_lists.status` for a UBI-generated list:

```
(create) → generating
generating → complete       [worker: clean loop, all pairs persisted]
generating → failed         [worker: UbiInsufficientDataError | UbiQueryMappingAmbiguousError |
                              BudgetExceededError (hybrid) | UnknownModelPricingError (hybrid) |
                              UNEXPECTED:<ErrorType>]
```

Identical lifecycle to `generate_judgments_llm`. The boot-time resume sweep at `backend/workers/all.py:148-161` re-enqueues any `status='generating'` row (UBI or LLM) when the worker boots — UBI worker MUST also handle the resume-skip per query (`count_judgments_for_list_and_query > 0` ⇒ skip).

### Idempotency / replay

- The Arq job is keyed by `_job_id=f"generate_judgments_from_ubi:{judgment_list_id}"` — duplicate enqueues collapse to one running job.
- Per-query resume-skip via `count_judgments_for_list_and_query` (same pattern as `generate_judgments_llm`).
- The worker's `bulk_create_judgments` uses ON CONFLICT DO NOTHING — re-runs after partial crashes don't double-insert.

## 10) Security, privacy, and compliance

**Threats:**

1. **Leaked operator query text through the LLM-fill path.** Hybrid-mode LLM calls send `query_text` and (truncated, ≤500 char) document bodies to whatever endpoint `OPENAI_BASE_URL` points at. Mitigation: same data-flow document as `feat_llm_judgments` ([`docs/04_security/llm-data-flow.md`](../../../../04_security/llm-data-flow.md)) — the runbook (§15) extends with a "Hybrid-mode UBI fill" subsection. The capability check is the operator's signal that LLM-dependent paths will fire.
2. **Inadvertent cluster writes.** Bug class: somebody adds `_index` / `_bulk` / `_update` to `UbiReader`. Mitigation: code-review checklist + an integration test asserting that `UbiReader.read_features` never issues a write-shaped HTTP call (mock the adapter, fail the test if `client.send` is called with an HTTP method other than GET / POST `_search`).
3. **PII in UBI events.** UBI events may carry `client_id`, `session_id`, `user_query` text — operator-emitted. RelyLoop never persists raw events; it persists per-(query, doc) ratings derived from them. The original event data stays in the cluster. Mitigation: persist only ratings + `rater_ref='ubi:{converter}'` — no per-user identifiers in `judgments` rows.
4. **Budget-gate bypass on hybrid mode.** A naive implementation might call `openai.AsyncClient(...)` directly in the converter for LLM-fill, bypassing `peek_daily_total` / `record_cost`. Mitigation: the worker MUST inject `rate_query_batch` (which wraps the budget gate) as the converter's `llm_rate` callback. Code review + an integration test stubbing `rate_query_batch` and asserting it's invoked is the gate.
5. **Position-bias prior file path traversal.** Operator-supplied `UBI_POSITION_BIAS_PRIOR_FILE` env var — could point at arbitrary file. Mitigation: file is read via the existing `_FILE` mount-secret pattern (Absolute Rule #2 / [`backend/app/core/settings.py`](../../../../../backend/app/core/settings.py)); JSON parse failure logs WARN and falls back to uninformed prior (no error propagation). The container's mount surface is the operator's own infra.

**Controls:**

- **Secrets:** `UBI_POSITION_BIAS_PRIOR_FILE` follows the `_FILE`-mounted pattern. No new secret types.
- **Audit:** N/A in MVP2 — see §6 audit-event matrix for MVP3 activation.
- **Data retention/deletion:** UBI judgments persist on the existing `judgments` table — same CASCADE behavior on `judgment_lists` delete.
- **Logging:** Every UBI worker log line MUST include `judgment_list_id`, `event_type`, and (where relevant) `query_id` for traceability. NEVER log raw UBI event bodies, query text, or doc bodies (only counts + IDs).

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** the converter picker lives inside the existing "Generate judgments" dialog opened from the query-sets detail page (`ui/src/app/query-sets/[id]/page.tsx`). The dialog gains a top-bar "Method:" select; the rest of the dialog (name / target / template / rubric) stays in place.
- **Cluster rung badge:** small text-only badge on cluster cards (`ui/src/app/clusters/page.tsx`) + on the cluster detail page (`ui/src/app/clusters/[id]/page.tsx`). Reads from a per-cluster `useUbiReadiness(cluster_id)` hook with a 60s React Query stale time + the server-side 60s Redis cache.
- **Labeling taxonomy:**
  - "Generate judgments" — dialog title (unchanged)
  - "Method" — converter `<Select>` label (new; replaces the implicit "always LLM" mode)
  - "LLM-as-judge" / "UBI (click-through)" / "UBI (dwell-time)" / "Hybrid UBI + LLM" — converter option labels (D-2)
  - "Time window" — `since` / `until` group label (visible when method ≠ LLM)
  - "Hybrid fill threshold" — `llm_fill_threshold` label (visible when method = Hybrid)
  - "UBI status: not enabled / sparse / dense head / full coverage" — rung labels (rung_0 / rung_1 / rung_2 / rung_3) on the cluster badge
- **Content hierarchy:** dialog top → engine-aware nudge (when rung_0, dismissible) → name / target / template (primary inputs) → method picker (the new primary decision) → method-specific config (window / threshold / advanced) → rubric (visible when method involves LLM) → submit.
- **Progressive disclosure:**
  - Rung-0 operators see: nudge → 4-option picker with `llm` pre-selected → rubric → submit. UBI controls hidden.
  - Rung-1/2 operators see: 4-option picker with `hybrid_ubi_llm` pre-selected → window + LLM-fill-threshold + rubric → submit. Nudge hidden.
  - Rung-3 operators see: 4-option picker with `ctr_threshold` pre-selected → window + advanced config → submit. Rubric hidden (UBI converters don't use it; the column stores the converter description for lineage).
- **Relationship to existing pages:** extends the existing generate-judgments dialog; no new pages. The judgment-list detail page (`ui/src/app/judgments/[id]/page.tsx`) gains the value-delta card (Capability D) inline above the existing source-breakdown.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement | Glossary key |
|---|---|---|---|---|
| "Method" select label | "Choose how the judgment list is generated. LLM is always available; UBI options require the OpenSearch UBI plugin." | hover info icon | right | `judgment.converter` (new) |
| "LLM-as-judge" option | "An LLM rates each (query, doc) pair against your rubric. Works anywhere, no plugin needed. ~500–2000 pairs per list." | hover on option | inline | `judgment.converter.llm` (new) |
| "UBI (click-through)" option | "Click-derived ratings from real user behavior. Requires the UBI plugin + dense traffic. Position-bias-corrected." | hover on option | inline | `judgment.converter.ubi` (new) |
| "UBI (dwell-time)" option | "Post-click dwell-time ratings — best for content discovery. Requires the UBI plugin + dense traffic." | hover on option | inline | `judgment.converter.ubi` (new, shared) |
| "Hybrid UBI + LLM" option | "UBI rates pairs with enough traffic; the LLM judge fills the long tail. The mode most adopters ship to production." | hover on option | inline | `judgment.converter.hybrid` (new) |
| "Time window" group label | "UBI events in this window are aggregated into the judgment list. Default: last 30 days. Max: 90 days per request." | hover info icon | right | (inline helper, no glossary) |
| "Hybrid fill threshold" label | "Pairs with at least this many impressions get a UBI rating; below this, the LLM judge fills in. Default 20." | hover info icon | right | (inline helper, no glossary) |
| Rung badge on cluster card | (per rung text — e.g., "rung_2: dense head coverage; long tail thin. Hybrid recommended.") | hover | top | `cluster.ubi_readiness` (new) |
| Engine-aware nudge body | (engine-specific copy with deep-link to runbook) | always visible when rung_0 + not dismissed | dialog body header | (no tooltip — inline card content) |
| Sparse-data recommendation card | "Only ~12% of your query set has dense UBI signal. Hybrid rates that head and the LLM fills the rest. Click below to switch." | always visible when rung_1 + converter chosen is `ctr_threshold` or `dwell_time` | dialog body inline | (no tooltip — inline card with action) |
| Value-delta card on judgment-list detail | "This UBI list covered 91% of last week's real traffic with 1432 ratings — the previous LLM list rated 500 pairs on a snapshot." | always visible when prior LLM list exists | judgment-list detail page above breakdown | (inline card content) |

All glossary keys must be added to [`ui/src/lib/glossary.ts`](../../../../../ui/src/lib/glossary.ts) in the same PR with the `// Source-of-truth: backend/...` comment per the file's source-of-truth policy.

### Primary flows

1. **Rung-3 operator generates a UBI list.** Opens query-set page → "Generate judgments" → picker defaults to `ctr_threshold` → adjusts time window → submit → 202 → polls list status → completes with full UBI coverage. Existing list-detail page shows source_breakdown = `{llm: 0, human: 0, click: <count>}` and the calibration JSONB shows `{coverage_pct: 0.95, head_pairs: <n>, tail_pairs: 0, ...}`.
2. **Rung-1 operator chooses hybrid.** Same start → picker defaults to `hybrid_ubi_llm` → sees the sparse-data card → adjusts `llm_fill_threshold` → submit → 202 → completes with mixed list. Source_breakdown shows all three counts; calibration shows `{coverage_pct: 0.91, head_pairs: 1120, tail_pairs: 312, llm_fill_calls: 312}`.
3. **Rung-0 operator dismisses the nudge and picks LLM.** Same start → nudge surfaces above dialog body with the OpenSearch-specific runbook deep-link → operator clicks "Dismiss" → nudge hides for this cluster (localStorage write per `cluster_id`) → picks `llm` (default) → submits → flows through the existing `POST /api/v1/judgments/generate` (not the new UBI endpoint).
4. **Operator audits a hybrid list by source.** Opens judgment-list detail → filters `?source=click` → sees only UBI rows. Switches to `?source=llm` → sees only LLM-fill rows. Both filters work post-D-3 widening.
5. **Chat agent generates a UBI list.** Operator says "generate a judgment list for products from the last 30 days of clicks" → orchestrator probes `get_schema('ubi_queries')` → succeeds → emits `generate_judgments_from_ubi` tool call with `converter='hybrid_ubi_llm'` → confirmation guard prompts → operator confirms → tool dispatched → SSE stream shows progress events → completes.

### Edge / error flows

- **Plugin missing (rung_0) + operator submits UBI explicitly via API.** Backend returns 412 `UBI_NOT_ENABLED`. UI surfaces the same engine-aware nudge content as the 412 error envelope's `message`.
- **Sparse data (rung_1) + operator submits `ctr_threshold`.** Backend returns 422 `UBI_INSUFFICIENT_DATA`. UI catches it client-side via `useUbiReadiness` BEFORE the submit network round-trip and shows the inline recommendation card with the "Switch to hybrid" button. Defensive: even if the client-side check is bypassed, the backend's 422 envelope carries the same recommendation in `message`.
- **Query mapping ambiguous + `mapping_strategy='reject'` (per-query).** Worker logs `event_type='ubi_per_query_skipped_ambiguous_mapping'` and skips the query (per FR-5 step 5; NOT a 422). The completed list's calibration JSONB carries `ambiguous_query_skip_count: N`; the UI judgment-list detail page renders a card: "Skipped N queries due to ambiguous UBI mapping under your `reject` tiebreaker — re-run with `first_match` or `most_recent`." The card includes a one-shot "Re-run with `most_recent` tiebreaker" affordance (POSTs a fresh `generate-from-ubi` request with the same body except `mapping_strategy='most_recent'`).
- **Cluster unreachable during readiness probe.** Endpoint returns 503 `CLUSTER_UNREACHABLE`. UI shows rung as `unknown` (a fallback rendered state — NOT a new wire value) with a retry button; picker behaves as if rung_0 (LLM pre-selected) so the operator isn't blocked.
- **Hybrid-mode budget exhausted mid-loop.** Worker raises `BudgetExceededError`; terminal `status='failed'`, `failed_reason='OPENAI_BUDGET_EXCEEDED: current $9.87 + estimated $0.20 > budget $10.00'`. Already-persisted click rows stay (LLM-fill rows do too, up to the cutoff); operator sees a partial list on the detail page.
- **Worker crashes after partial persist.** Boot-time resume sweep re-enqueues the `generating` row. Per-query resume-skip prevents re-running converters on already-rated pairs.

## 12) Given/When/Then acceptance criteria

### AC-1: UBI list generation succeeds end-to-end on a rung-3 cluster (ctr_threshold)

- Given a cluster with `ubi_queries` populated for the last 30 days against the operator's query set
- And `POST /api/v1/judgments/generate-from-ubi` with `converter='ctr_threshold'`, `since=now-30d`, `until=null`
- When the worker completes
- Then `judgment_lists.status == 'complete'`
- And every row's `source == 'click'` and `rater_ref == 'ubi:ctr_threshold'`
- And `calibration.coverage_pct >= 0.5` for the test fixture
- Example values:
  - Input: `{converter: "ctr_threshold", since: "2026-04-29T00:00:00Z", query_set_id: "0190…", cluster_id: "0190…", target: "products", name: "products-ubi-q2-2026"}`
  - Expected: 202 with `{judgment_list_id: "<uuid>", status: "generating"}`; after worker completion `GET /api/v1/judgment-lists/<uuid>` returns `source_breakdown: {llm: 0, human: 0, click: 847}` and `status: "complete"`

### AC-2: Hybrid mode interleaves click + LLM rows in one list

- Given a cluster with `ubi_queries` populated but ~30% of pairs have `impression_count < 20`
- And `POST /api/v1/judgments/generate-from-ubi` with `converter='hybrid_ubi_llm'`, `llm_fill_threshold=20`
- When the worker completes
- Then `judgment_lists.status == 'complete'`
- And `source_breakdown.click > 0` AND `source_breakdown.llm > 0`
- And `source_breakdown.llm + source_breakdown.click == judgment_count` (no `human` rows)
- And `calibration.llm_fill_calls == source_breakdown.llm`
- Example values:
  - Expected `source_breakdown`: `{llm: 312, human: 0, click: 1120}`
  - Expected `calibration`: `{coverage_pct: 0.91, head_pairs: 1120, tail_pairs: 312, position_bias_prior_id: "uninformed", llm_fill_calls: 312}`

### AC-3: Rung-0 cluster returns 412 with engine-aware message

- Given a cluster where `get_schema('ubi_queries')` raises `TargetNotFoundError`
- When `POST /api/v1/judgments/generate-from-ubi` is called
- Then HTTP 412 `UBI_NOT_ENABLED` returns with `detail.message` referencing the operator's cluster name + the install runbook
- Example values:
  - Cluster `engine_type='opensearch'`, `name='acme-search'`
  - Expected response: `{"detail": {"error_code": "UBI_NOT_ENABLED", "message": "ubi_queries index not found on cluster acme-search; install the OpenSearch UBI plugin and enable event capture in your application", "retryable": false}}`

### AC-4: Sparse UBI on rung_1 returns 422 with hybrid recommendation in message

- Given `ubi_queries` present but only 23 events match the window
- And `min_impressions_threshold=100` (default)
- When `POST /api/v1/judgments/generate-from-ubi` with `converter='ctr_threshold'`
- Then HTTP 422 `UBI_INSUFFICIENT_DATA` with `detail.message` containing "Try hybrid_ubi_llm converter for LLM-fill on sparse pairs"
- And the same submit with `converter='hybrid_ubi_llm'` succeeds (subject to LLM-fill budget)

### AC-5: `_SourceBreakdown` evolution preserves backward compat for LLM-only lists

- Given a pre-existing LLM-only judgment list (no UBI rows)
- When `GET /api/v1/judgment-lists/{id}` returns the detail
- Then `source_breakdown.llm == judgment_count`
- And `source_breakdown.human == 0` (or the actual human-override count)
- And `source_breakdown.click == 0`
- And `source_breakdown.llm + source_breakdown.human + source_breakdown.click == judgment_count`

### AC-6: `?source=click` filter returns only UBI rows

- Given a hybrid judgment list with 1120 click + 312 LLM rows
- When `GET /api/v1/judgment-lists/{id}/judgments?source=click&limit=200` is called
- Then `X-Total-Count: 1120` header is set
- And every returned row has `source == 'click'`
- And `source=llm` returns 312 rows

### AC-7: Chat-agent UBI tool dispatch

- Given a cluster with `ubi_queries` populated
- And the operator says in chat "generate a judgment list for products from the last 30 days of clicks"
- When the orchestrator processes the message
- Then the orchestrator emits a `generate_judgments_from_ubi` tool call with `converter='hybrid_ubi_llm'`
- And the confirmation guard prompts the operator before dispatch
- And on operator confirmation the tool returns `{judgment_list_id, status: "generating"}`

### AC-8: Rung badge renders correctly per rung

- Given clusters at each rung 0–3
- When the operator views the clusters list page
- Then each cluster card shows the rung-specific text badge
- And the badge tooltip cites the recommended converter
- And the rung value uses one of the four `UBI_READINESS_RUNG_VALUES` (no string outside the Literal)

### AC-9: Engine-aware nudge dismissal persists per cluster

- Given a rung_0 cluster
- And the operator opens the generate-judgments dialog
- When the operator clicks "Dismiss" on the nudge
- Then the nudge hides for the current dialog session
- And reloading the page shows the dialog without the nudge for the same `cluster_id`
- And opening the dialog on a different rung_0 cluster shows the nudge (per-cluster keying)

### AC-10: Value-delta card surfaces on completed hybrid list

- Given a hybrid list completes on `query_set_X`
- And a prior LLM list exists on the same `query_set_X`
- When the operator opens the new list detail
- Then a card surfaces: "This UBI list covered N% of last week's real traffic with C ratings — the previous LLM list rated L pairs on a snapshot"
- And C, N, L are read from the new list's calibration + the prior list's `judgment_count`

### AC-11: Converter picker default follows rung

- Given a query-set with a known cluster at rung_0
- When the operator opens the generate-judgments dialog
- Then `<Select name="converter">` has `llm` pre-selected
- And at rung_1 it has `hybrid_ubi_llm` pre-selected
- And at rung_3 it has `ctr_threshold` pre-selected

### AC-12: Worker resume-skip after crash

- Given a hybrid generation interrupted after 500/847 queries persisted
- When the worker reboots and the resume sweep re-enqueues the row
- Then the worker skips the 500 already-persisted queries (resume-skip on `count_judgments_for_list_and_query > 0`)
- And processes the remaining 347 queries
- And total cost-recorded amount equals the second-run cost only (not the first run again)

### AC-13: Tool registry drift assertion fails on missing registration

- Given the `generate_judgments_from_ubi_impl` is added to `backend/app/agent/tools/judgments/generate_judgments_from_ubi.py`
- And the tool is added to `TOOLS` but NOT to `TOOL_REGISTRY` or `TOOL_ARG_MODELS` in `backend/app/agent/tools/__init__.py`
- When the module loads
- Then `RuntimeError("TOOLS / TOOL_REGISTRY / TOOL_ARG_MODELS drift: ...")` is raised at import time
- Example: every PR-CI suite that imports `agent.tools` catches the regression before any test runs

### AC-14: `UBI_WINDOW_TOO_LARGE` caps long windows

- Given a request with `since=2026-01-01T00:00:00Z, until=2026-06-01T00:00:00Z` (151 days)
- When the request reaches preflight U-D
- Then HTTP 422 `UBI_WINDOW_TOO_LARGE` is returned with `detail.message` citing the 90-day cap

### AC-15: No cluster writes during readiness probe or generation

- Given an integration test that mocks the `ElasticAdapter` HTTP client
- When `GET /api/v1/clusters/{id}/ubi-readiness` runs AND when the UBI worker runs end-to-end
- Then zero HTTP requests are issued with a write-shaped method (`PUT`, `DELETE`) or path (`_bulk`, `_update`, `_doc`, `_create`)
- And only `GET` + `POST _search` calls fire

## 13) Non-functional requirements

- **Performance:**
  - `GET /api/v1/clusters/{cluster_id}/ubi-readiness` p99 ≤ 2 s (server-side 60s Redis cache + cluster `_count` aggregation).
  - UBI worker throughput for `ctr_threshold` on a 1000-pair query set: ≤ 60 s (dominated by the two `search_batch` scrolls + client-side join — no per-query LLM cost).
  - Hybrid-mode throughput: same as `generate_judgments_llm` for the LLM-fill subset (~1–2 s per query when LLM-fill fires; ~50 ms when UBI alone covers).
- **Reliability:**
  - Per-query failures (one ambiguous mapping, one sparse query) are isolated — log WARN, skip, continue.
  - Boot-time resume sweep at `backend/workers/all.py` re-enqueues any `generating` UBI list when the worker boots.
  - Terminal `failed` only on global failures.
- **Operability:**
  - Every worker log line includes `judgment_list_id`, `event_type` (one of: `ubi_read_complete`, `ubi_converter_complete`, `ubi_persist_complete`, `ubi_resume_skip`, `ubi_per_query_skipped`, `ubi_list_complete`, `ubi_list_failed`, `ubi_budget_exceeded`).
  - `/healthz` is unaffected — UBI doesn't introduce a startup-time check (the readiness probe is per-request, not boot-time).
  - Metrics surfaced on the judgment-list detail page: `judgment_count`, `source_breakdown`, `calibration.coverage_pct`, `calibration.llm_fill_calls` (hybrid only).
- **Accessibility / usability:**
  - Engine-aware nudge follows the dismiss-button + `aria-labelledby` pattern from `demo-data-banner.tsx`.
  - Sparse-data recommendation card uses `role='region'` + `aria-labelledby` for the heading, matching the existing card pattern.
  - Rung badge color contrast ≥ 4.5:1 (WCAG AA) — text-only badge, no color-only meaning.
  - Converter `<Select>` is keyboard-navigable via the shipped `@/components/ui/select` primitive (Radix-based).

## 14) Test strategy requirements (spec-level)

**Unit tests (`backend/tests/unit/`):**

- `tests/unit/domain/ubi/test_converter.py` — `CtrThresholdConverter`, `DwellTimeThresholdConverter`, `HybridUbiLlmConverter` math + edge cases (zero impressions, single-impression queries, NULL dwell, all-pairs-below-threshold hybrid → 100% LLM-fill, threshold-boundary inputs)
- `tests/unit/domain/ubi/test_features.py` — feature-vector aggregation (click count = sum of click events, position-bias correction applied with informed + uninformed priors, refinement-rate calculation, NULL conversion handling)
- `tests/unit/domain/ubi/test_position_bias_prior.py` — prior file loader (valid prior JSON, missing file → uninformed default, malformed JSON → WARN + uninformed default)
- `tests/unit/services/test_ubi_readiness.py` — rung classification (TargetNotFoundError → rung_0, sparse coverage → rung_1, head-covered → rung_2, full-coverage → rung_3, mocked aggregation responses)
- `tests/unit/api/test_schemas_ubi.py` — Pydantic validation (`CreateJudgmentListFromUbiRequest` rejects `converter='llm'` at request time; window > 90 days → ValidationError; `mapping_strategy` defaults; converter enum)
- `tests/unit/api/test_source_breakdown_evolution.py` — `_SourceBreakdown` now `{llm, human, click}`; LLM-only response shape sets `click=0`

**Integration tests (`backend/tests/integration/`):**

- `tests/integration/api/test_judgments_generate_from_ubi.py` — full preflight matrix against a stubbed `UbiReader` returning canned features (succeeds on full coverage; 412 on rung_0 simulated via `get_schema` raising `TargetNotFoundError`; 422 on rung_1 simulated via under-threshold features; 422 on window > 90 days; 503 on hybrid-with-no-OpenAI-key; 409 on name collision)
- `tests/integration/api/test_judgments_filter_click_widening.py` — `?source=click` returns matching rows; `?source=llm` returns LLM-fill rows; backward-compat: `?source=human` still works
- `tests/integration/api/test_judgment_list_detail_breakdown.py` — `_SourceBreakdown` returns all three keys; hybrid-list invariant `llm+human+click == judgment_count`; LLM-only list returns `{llm: N, human: 0, click: 0}`
- `tests/integration/api/test_clusters_ubi_readiness.py` — rung_0/1/2/3 paths; 60s Redis cache hit; 503 on `ClusterUnreachableError`; rung response schema matches `UbiReadinessRungWire` Literal
- `tests/integration/workers/test_generate_judgments_from_ubi.py` — clean-loop completes with all-`click` rows; hybrid produces mixed list; resume after crash skips already-rated queries; `BudgetExceededError` mid-hybrid-loop terminal `failed`; `UbiInsufficientDataError` mid-loop terminal `failed` with `failed_reason='UBI_INSUFFICIENT_DATA'`
- `tests/integration/services/test_ubi_reader_no_writes.py` — mock the HTTP transport; assert zero write-method calls during full reader exercise (the "no cluster writes" invariant from §10 threat #2)
- `tests/integration/agent/test_generate_judgments_from_ubi_tool.py` — tool registration drift assertion fires when removed from any of the three triad data structures; tool dispatch returns expected `{judgment_list_id, status}` shape; confirmation guard fires on dispatch

**Contract tests (`backend/tests/contract/`):**

- `tests/contract/test_judgments_generate_from_ubi_shape.py` — 202 response shape matches `GenerateJudgmentsResponse`; 412 / 422 / 503 envelopes carry the correct `error_code` per §8.5 catalog
- `tests/contract/test_judgment_list_detail_source_breakdown_v2.py` — `_SourceBreakdown` returns 3 keys; OpenAPI schema lock at `/openapi.json` shows the evolved shape
- `tests/contract/test_clusters_ubi_readiness_shape.py` — 200 response shape; 404 / 503 envelopes
- `tests/contract/test_agent_tool_inventory.py` — `TOOLS` includes `generate_judgments_from_ubi`; `TOOL_REGISTRY` and `TOOL_ARG_MODELS` align (the existing drift assertion test, extended)

**E2E tests (`ui/tests/e2e/`):**

- `tests/e2e/ubi-onramp-rung-0.spec.ts` — rung_0 cluster: nudge surfaces; dismiss persists per `cluster_id`; method picker defaults to `llm`; submit routes to LLM endpoint (test setup seeds a cluster with no UBI plugin; uses real backend per the project's no-`page.route()` rule).
- `tests/e2e/ubi-onramp-rung-3.spec.ts` — rung_3 cluster: picker defaults to `ctr_threshold`; submit → 202 → polls list → completes with `source=click` rows. **Mandatory in CI** (cycle-3 finding `ubi-success-e2e-optional-in-ci`). Test setup seeds `ubi_queries` + `ubi_events` indices in the existing CI OpenSearch service container via shared helpers `tests/e2e/helpers/seed_ubi.ts` (`seedUbiQueries(opensearchUrl, queries)` + `seedUbiEvents(opensearchUrl, events)`) called from a `beforeAll` hook. No new service container required — the CI OpenSearch + Elasticsearch containers already run for the rest of the suite. The seed helper writes synthesized click + impression events that put the test query-set at rung_3 unambiguously.
- `tests/e2e/ubi-hybrid-mode.spec.ts` — rung_1 cluster: picker defaults to `hybrid_ubi_llm`; sparse-data card surfaces; submit succeeds; list detail shows mixed `source_breakdown` and value-delta vs prior LLM list. Same seed helpers, calibrated for sparse coverage.
- `tests/e2e/ubi-source-filter.spec.ts` — operator filters judgment-list by `source=click` then `source=llm` in the UI; both views render correctly. Reuses a seeded hybrid list from `ubi-hybrid-mode.spec.ts`.

**E2E coverage rule:** all four UBI E2E specs are required to be green for the §18 "All four test layers green" gate. The historical pattern of "skip E2E if fixture unavailable" is rejected — the OpenSearch container is always available in CI; the seed helper is the fixture.

**Test completeness rule (CLAUDE.md):** UBI is a feature that touches DB (judgments rows), API (4 endpoints), worker (Arq job), agent (chat tool), and frontend (5 UI elements). Coverage at every layer is mandatory — unit + integration + contract + E2E.

## 15) Documentation update requirements

- `docs/01_architecture/api-conventions.md` — add `/api/v1/judgments/generate-from-ubi` to the resource-naming canon (it follows the existing `/judgments/generate-*` action pattern; one-line addition).
- `docs/01_architecture/adapters.md` — note that UBI reads via the existing `SearchAdapter.search_batch` + `get_schema` surface; no new adapter methods. Cross-link to the umbrella spec §14 patch.
- `docs/01_architecture/llm-orchestration.md` — under "Per-task LLM patterns" add a "Hybrid UBI + LLM fill" subsection: same `rate_query_batch` callsite as judgment generation; same budget gate; LLM-fill calls subject to the same `OPENAI_DAILY_BUDGET_USD` cap.
- `docs/01_architecture/data-model.md` §"judgments" — note the `source='click'` value is now in use (was reserved); add the `_SourceBreakdown` invariant evolution to `{llm, human, click}`.
- `docs/01_architecture/data-model.md` §"judgment_lists" — add the UBI calibration JSONB shape `{coverage_pct, head_pairs, tail_pairs, position_bias_prior_id, llm_fill_calls?}` alongside the existing LLM calibration shape.
- `docs/00_overview/relyloop-spec.md` §14 + §706 + §724 — apply the three preflight-discovered patches (release-stage rename + the relative-path fixes).
- `docs/03_runbooks/ubi-judgment-generation.md` — **new runbook**. Sections: install OpenSearch UBI plugin → configure event capture in operator application → choose converter → calibrate position-bias prior → debug `UBI_INSUFFICIENT_DATA` / `UBI_QUERY_MAPPING_AMBIGUOUS` / per-query skip events.
- `docs/04_security/llm-data-flow.md` — add a "Hybrid UBI + LLM fill" subsection (what data leaves the cluster on a hybrid call: same `query_text` + truncated doc body as MVP1 judgment generation; only for below-threshold pairs).
- `docs/05_quality/testing.md` — note the new `tests/integration/services/test_ubi_reader_no_writes.py` enforcement pattern (mock HTTP transport, assert write-method count == 0) for any feature that should be read-only against external systems.
- `docs/08_guides/tutorial-first-study.md` — new optional Step 7 (swap LLM list for UBI). Tutorial completion still possible without it.
- [`ui/src/lib/glossary.ts`](../../../../../ui/src/lib/glossary.ts) — add 4 keys: `judgment.converter`, `judgment.converter.llm`, `judgment.converter.ubi`, `judgment.converter.hybrid`, `cluster.ubi_readiness`. Each with the `// Source-of-truth: backend/app/api/v1/schemas.py <Symbol>` comment.
- [`ui/src/lib/faq.ts`](../../../../../ui/src/lib/faq.ts) — add 3 entries to the `judgments` category: "Do I need UBI to use RelyLoop?", "Should I trust UBI ratings over LLM ratings?", "My cluster shows 'No UBI' — is that a problem?".

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None — UBI is fully additive. The picker's `llm` option (default for rung_0 clusters) preserves the MVP1 experience byte-for-byte. The new endpoint, agent tool, and UI controls are dark for any operator who never opens the picker.
- **Migration / backfill:** None — no schema changes. The `_SourceBreakdown` shape evolution is a Pydantic response-model change; existing rows return `click: 0` correctly without backfill.
- **Operational readiness gates:**
  - Runbook `docs/03_runbooks/ubi-judgment-generation.md` merged before release.
  - Tutorial Step 7 merged before release.
  - Contract tests for the evolved `_SourceBreakdown` shape green.
  - `tests/integration/services/test_ubi_reader_no_writes.py` green (the "no cluster writes" invariant guard).
- **Release gate:**
  - All AC-1..AC-15 pass in CI.
  - All four test layers green.
  - Cross-model review (GPT-5.5) converged on this spec + the impl plan + the phase-gate diff.
  - Documentation updates §15 merged.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks (high-level) | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (UbiReader) | AC-1, AC-2, AC-15 | Story: `backend/app/services/ubi_reader.py` + `domain/ubi/features.py` | `tests/unit/domain/ubi/test_features.py`, `tests/integration/services/test_ubi_reader_no_writes.py` | `docs/01_architecture/adapters.md` |
| FR-2 (SignalsConverter) | AC-1, AC-2 | Story: `backend/app/domain/ubi/converter.py` (3 impls) | `tests/unit/domain/ubi/test_converter.py` | `docs/01_architecture/llm-orchestration.md` |
| FR-3 (Endpoint) | AC-1, AC-2, AC-3, AC-4, AC-14 | Story: `backend/app/api/v1/judgments.py` `generate-from-ubi` route | `tests/integration/api/test_judgments_generate_from_ubi.py`, `tests/contract/test_judgments_generate_from_ubi_shape.py` | `docs/01_architecture/api-conventions.md`, runbook |
| FR-4 (Dispatcher) | AC-1, AC-2, AC-3, AC-4, AC-14 | Story: `start_ubi_judgment_generation` in `agent_judgments_dispatch.py` + shared-helper refactor | `tests/integration/api/test_judgments_generate_from_ubi.py` | runbook |
| FR-5 (Worker) | AC-1, AC-2, AC-12, AC-15 | Story: `generate_judgments_from_ubi` Arq job in `backend/workers/judgments.py` | `tests/integration/workers/test_generate_judgments_from_ubi.py` | runbook |
| FR-6 (Agent tool) | AC-7, AC-13 | Story: `agent/tools/judgments/generate_judgments_from_ubi.py` + registry wiring + system-prompt update | `tests/integration/agent/test_generate_judgments_from_ubi_tool.py`, `tests/contract/test_agent_tool_inventory.py` | `docs/01_architecture/agent-tools.md` |
| FR-7 (Readiness probe) | AC-8, AC-9 | Story: `backend/app/services/ubi_readiness.py` + `GET /api/v1/clusters/{id}/ubi-readiness` | `tests/unit/services/test_ubi_readiness.py`, `tests/integration/api/test_clusters_ubi_readiness.py`, `tests/contract/test_clusters_ubi_readiness_shape.py` | runbook |
| FR-8 (Frontend picker + on-ramp) | AC-3, AC-4, AC-8, AC-9, AC-10, AC-11 | Stories: extend `generate-judgments-dialog.tsx`; new `ubi-onramp-nudge.tsx`; new `ubi-rung-badge.tsx`; new value-delta card | `ui/src/__tests__/components/query-sets/generate-judgments-dialog.test.tsx`, e2e suites | tutorial Step 7 |
| FR-9 (Wire-value contracts) | AC-3, AC-4, AC-6, AC-8 | Story: add `UbiConverterKind` / `UbiReadinessRungWire` + UI enums + widen filter | `tests/unit/api/test_schemas_ubi.py`, `ui/src/__tests__/lib/enums-source-of-truth.test.ts` | `docs/01_architecture/api-conventions.md` |
| FR-10 (_SourceBreakdown evolution) | AC-2, AC-5, AC-6 | Story: evolve Pydantic model + `_detail()` + repo function + contract test update | `tests/unit/api/test_source_breakdown_evolution.py`, `tests/integration/api/test_judgment_list_detail_breakdown.py`, `tests/contract/test_judgment_list_detail_source_breakdown_v2.py` | `docs/01_architecture/data-model.md` |
| FR-11 (Position-bias prior) | AC-1 (uninformed default applied) | Story: `UBI_POSITION_BIAS_PRIOR_FILE` env var + JSON loader + WARN-on-malformed | `tests/unit/domain/ubi/test_position_bias_prior.py` | runbook |

## 18) Definition of feature done

- [ ] All AC-1..AC-15 pass in CI
- [ ] All four test layers green (unit, integration, contract, E2E)
- [ ] Documentation §15 merged (runbook, llm-data-flow, adapters, data-model, api-conventions, llm-orchestration, glossary, FAQ, tutorial, umbrella spec patches)
- [ ] Cross-model review (GPT-5.5) clean on the spec, the implementation plan, and the final phase-gate diff
- [ ] No open questions remain in §19 (all 8 OQs already locked at D-1..D-9 below)
- [ ] PR description quotes the test count + worker behavior (resume-skip, terminal failure modes) + the "no cluster writes" invariant

## 19) Open questions and decision log

### Open questions

**None — all 8 idea-stage OQs are locked at the decision log below.** Future spec-stage questions raised by GPT-5.5 will be tracked here in subsequent cycles.

### Decision log

- **2026-05-29 — D-1: `_SourceBreakdown` Path A (evolve in-place to `{llm, human, click}`).** Locks idea OQ1 to Path A. Rationale: the cycle-2 F6 two-term invariant was made when no UBI rows existed; UBI is the moment to update it. In-place evolution (no `V2` versioning) is safe because the only OpenAPI consumers today are the project's own UI + contract tests. Audit confirmed via `grep _SourceBreakdown` — no external consumers.
- **2026-05-29 — D-2: Wire field name `converter` on the request body; UI picker field name `method`; labels per Capability E.** Locks idea OQ5. Field name on `POST /api/v1/judgments/generate-from-ubi`: `converter` (NOT `source`, which is the per-row provenance value). UI picker field name: `method` (the broader concept — "how is this list generated?" — that includes LLM-as-judge as one of four choices). Labels: "LLM-as-judge", "UBI (click-through)", "UBI (dwell-time)", "Hybrid UBI + LLM". Two enums kept structurally aligned: backend `UbiConverterKind = Literal["ctr_threshold", "dwell_time", "hybrid_ubi_llm"]` (request-side, 3 values); backend `JudgmentGenerationMethodWire = Literal["llm", "ctr_threshold", "dwell_time", "hybrid_ubi_llm"]` (picker-side, 4 values). The `llm` value in the picker routes the submit to `POST /api/v1/judgments/generate` (the existing endpoint, unchanged), not to the new UBI endpoint.
- **2026-05-29 — D-3: Widen `JudgmentSourceFilterWire` to include `click`.** Promotes the existing `Literal["llm", "human"]` to `Literal["llm", "human", "click"]`. Reverses the `feat_llm_judgments` cycle-1 F1 decision (made when no UBI rows existed). Operators can audit UBI-only or hybrid lists via `?source=click`. UI `JUDGMENT_SOURCE_FILTER_VALUES` widens in lockstep.
- **2026-05-29 — D-4: `mapping_strategy` defaults to `'reject'`.** Locks idea OQ2. Wire enum: `Literal["reject", "first_match", "most_recent"]`. The default is the most operator-control-preserving and matches the existing 422-on-ambiguity pattern. `first_match` / `most_recent` are opt-in escape hatches surfaced via a "Re-run with tiebreaker" affordance in the error-handling UI.
- **2026-05-29 — D-5: `min_impressions_threshold` default 100; `llm_fill_threshold` default 20.** Locks idea OQ3. Two separate gates: `min_impressions_threshold` (total events for the window to be valid) and `llm_fill_threshold` (per-pair threshold for the hybrid converter to defer to LLM). 100 events total is well below any realistic operator scale; 20 per-pair matches the idea's recommended hybrid default.
- **2026-05-29 — D-6: Single-phase delivery default; phased fallback to be decided at `/impl-plan-gen` time.** Locks the idea's phase boundary contingency. The operator explicitly merged `feat_ubi_onramp` back into this feature 2026-05-29 to ship the substrate + on-ramp UX as one reviewable unit. If the implementation plan judges the bundled diff (~1350 LOC) too large, the split is Phase 1 (substrate + always-LLM picker) / Phase 2 (readiness ladder + nudge + value-delta), tracked via a `phase2_idea.md` file created by `/impl-plan-gen` at that decision point.
- **2026-05-29 — D-7: Nudge dismissal persisted in `safeLocalStorage` keyed by `cluster_id`.** Locks idea OQ6. Re-surfaces only when the rung is still 0 (per the `useUbiReadiness` hook). Storage key shape: `relyloop.ubi-onramp-nudge.dismissed:{cluster_id}`. Follows the `demo-data-banner.tsx` SSR-safe pattern (NOT the Set-shaped `useLocalStorageSet` hook).
- **2026-05-29 — D-8: Fixed MVP2 rung thresholds; operator-configurability deferred.** Locks idea OQ7. Rung 1 = `ubi_queries` present + <`min_impressions_threshold` on >50% of pairs; rung 2 = head covered (≥50% above); rung 3 = ≥`min_impressions_threshold` across the query set. Operator-configurable thresholds revisit if adopter feedback surfaces it (icebox).
- **2026-05-29 — D-9: Value-delta on first UBI list = coverage-only (no synthetic LLM baseline).** Locks idea OQ8. When no prior LLM list exists on the same query_set, the value-delta card shows only `coverage_pct` + raw rating count. Do NOT spend an LLM spot-rating call to manufacture a comparison baseline — cost + latency outweigh the marginal informational value.
- **2026-05-29 — D-10: GPT-5.5 cross-model review cycle 1+2+3 outcomes.** Three review cycles ran 2026-05-29; all 10 findings (1 H + 1 M cycle 1+2; 2 H + 4 M + 2 L cycle 3) accepted. Cycle 1 introduced the `UbiConverterKind` / `JudgmentGenerationMethodWire` enum split. Cycle 2 cleaned up a residual single-enum reference in §2. Cycle 3 surfaced structural gaps and the spec was edited in place: (a) `judgment_lists.generation_params` JSONB column + Alembic migration `0021` added for UBI worker resume (cycle-3 #1 + #6); (b) hybrid mode `current_template_id` + `rubric` now required on the request body via a Pydantic `model_validator` (cycle-3 #2); (c) readiness endpoint now requires `?query_set_id` + `?target` query params and caches per scope tuple (cycle-3 #3); (d) `UBI_INSUFFICIENT_DATA` locked as **sync 422 from preflight U-D2** with the worker terminal path as race-condition fallback only (cycle-3 #4); (e) `SignalsConverter.convert` is async to accommodate the hybrid LLM callback uniformly (cycle-3 #5); (f) ambiguous-mapping is per-query skip with `calibration.ambiguous_query_skip_count` rather than a 422 endpoint code — `UBI_QUERY_MAPPING_AMBIGUOUS` removed from §8.5 (cycle-3 #7); (g) all four UBI E2E specs mandatory in CI via the existing OpenSearch service container + `tests/e2e/helpers/seed_ubi.ts` (cycle-3 #8). Cycle 3 hit the skill's max-cycles cap; the cycle-3 edits were not re-submitted for cycle 4 — future cross-model review at `/impl-plan-gen` time covers the new endpoint shapes + Protocol async migration + migration round-trip.

---

**Notes on cross-model review:**

This spec was generated 2026-05-29 by Claude Opus 4.8 against the 2026-05-29-refreshed idea.md and verified against the live codebase (Alembic head pre-`0021_judgment_lists_generation_params` is `0020_studies_baseline_trial`; agent tool registry at [`backend/app/agent/tools/__init__.py`](../../../../../backend/app/agent/tools/__init__.py); existing `start_judgment_generation` dispatcher at [`backend/app/services/agent_judgments_dispatch.py`](../../../../../backend/app/services/agent_judgments_dispatch.py); existing UI source-of-truth policy in [`ui/src/lib/enums.ts`](../../../../../ui/src/lib/enums.ts)). GPT-5.5 cross-model review per [`CLAUDE.md`](../../../../../CLAUDE.md): three cycles ran 2026-05-29; all 10 findings accepted and applied in place (see D-10). The 3-cycle cap was hit; the cycle-3 fixes will be re-reviewed when `/impl-plan-gen` derives the implementation plan from this spec.
