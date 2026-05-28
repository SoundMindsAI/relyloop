# Feature Specification — feat_study_preflight_overlap_probe

**Date:** 2026-05-22
**Status:** Draft
**Owners:** RelyLoop maintainers
**Related docs:**
- [idea.md](idea.md)
- [api-conventions.md](../../../01_architecture/api-conventions.md)
- [adapters.md](../../../01_architecture/adapters.md)
- Upstream Tier 1: [feat_study_target_judgment_mismatch_guard](../../../00_overview/implemented_features/2026_05_21_feat_study_target_judgment_mismatch_guard/feature_spec.md) — shipped PR #184, 2026-05-21
- Composes with Tier 3: [feat_orchestrator_zero_streak_abort](../../../00_overview/implemented_features/2026_05_22_feat_orchestrator_zero_streak_abort/feature_spec.md) — shipped PR #191, 2026-05-22

**Depends on:** [`feat_study_target_judgment_mismatch_guard`](../../../00_overview/implemented_features/2026_05_21_feat_study_target_judgment_mismatch_guard/feature_spec.md) — **satisfied** (PR #184, merged 2026-05-21). Feature is purely additive (no migration, no new external dep). Builds on the existing studies POST validator chain at [`backend/app/api/v1/studies.py:206-283`](../../../../backend/app/api/v1/studies.py#L206-L283) and the existing `acquire_adapter()` context manager at [`backend/app/services/cluster.py:227-253`](../../../../backend/app/services/cluster.py#L227-L253).

---

## 1) Purpose

- **Problem:** Tier 1 (`feat_study_target_judgment_mismatch_guard`, PR #184) catches *string-equality* mismatches between `study.target` and `judgment_list.target`. It does NOT catch cases where the names match but the underlying doc IDs do not overlap: (a) operator re-indexed the corpus via `_reindex` with new doc IDs while keeping the index name; (b) judgments were authored against a snapshot that has since rotated. Both look identical at create time (`judgment_list.target == study.target`, `judgment_count > 0`, `query_count > 0`); the orchestrator then runs the full trial budget with `best_metric=0.0` because every (params, query) pair scores zero — pytrec_eval has no judged docs to score against. Tier 3 (`feat_orchestrator_zero_streak_abort`, PR #191) catches this mid-flight after 20 zero-metric trials, but burns ~10 minutes of operator wall-clock budget before firing. This feature closes the gap with a create-time probe.
- **Outcome:** `POST /api/v1/studies` issues a single bounded `ids`-existence query against the study's target asking "for the *first* query in the query set that has any judgments (chosen deterministically by `id ASC`), do its judged doc IDs still exist in the current index? Probe up to `MAX_PROBED_DOCS=200` of them." If the probed overlap is below `min(MIN_OVERLAP, max(judged_doc_count, 1))`, reject with `INSUFFICIENT_JUDGMENT_OVERLAP` (422) before any orchestrator budget is spent. This is a *representative-qid* probe — it does not check every qid in the query set, so it cannot prove "every trial will score 0", but in the stated failure modes (re-indexed corpus, rotated index, stale judgments) all qids' doc IDs are uniformly affected and the representative qid is a strong proxy. If the cluster is unreachable at probe time, fall through with a WARN log (the orchestrator's existing per-trial failure handling catches the cluster issue mid-flight; rejection here would conflict with the cluster-registration philosophy of tolerating transient adapter failures at write time).
- **Non-goal:** Detecting partial overlap (1–2 doc IDs intersecting at a representative qid with ≥3 judgments) and surfacing it as a non-blocking warning. Per Decision Log "Q1 → B (2-tier matrix)", any overlap below the threshold rejects with the same code — there is no `metric_delta_warning` field on the success response and no new envelope pattern is introduced. Detecting query-string-vs-index mismatches (queries reference content that doesn't exist in the corpus; idea.md case (c)) — out of scope, because the ids-existence probe answers "do these doc IDs exist in the index?" not "does running this query against the index return these doc IDs?". The query-string failure mode is owned by Tier 3 (`feat_orchestrator_zero_streak_abort`, shipped PR #191) which catches it mid-flight after 20 zero-metric trials. Detecting template-body breakage at edge param values is also Tier 3's responsibility.

## 2) Current state audit

### Existing implementations

- **[`backend/app/api/v1/studies.py:206-283`](../../../../backend/app/api/v1/studies.py#L206-L283)** — the `POST /api/v1/studies` validator chain. The new probe inserts itself between line 283 (end of `JUDGMENT_TARGET_MISMATCH` check) and line 286 (config serialization). No structural change to the handler; one async function call wrapped in try/except. The existing `_err(...)` helper at [`studies.py:74-78`](../../../../backend/app/api/v1/studies.py#L74-L78) is reused for the new 422 envelope.
- **[`backend/app/services/cluster.py:227-253`](../../../../backend/app/services/cluster.py#L227-L253)** — `acquire_adapter()` async context manager. Already translates `CredentialsMissing` (adapter construction failure) → `ClusterUnreachable` service-layer exception. The probe enters its `try:` block within the existing studies handler's exception-translation scope; `ClusterUnreachable` + `ClusterUnreachableError` are caught and translated to a WARN log + skip-probe rather than re-raising as 503 (the studies POST is not the cluster-targets/run_query path that surfaces 503 for adapter failures).
- **[`backend/app/adapters/protocol.py:117-208`](../../../../backend/app/adapters/protocol.py#L117-L208)** — `SearchAdapter` Protocol. The probe uses `adapter.search_batch(target, queries, top_k, *, strict_errors, timeout)` directly with a hand-built `NativeQuery` whose body is `{"query": {"ids": {"values": [...]}}, "size": <N>}`. No new Protocol method needed; the `NativeQuery` + `search_batch` surface already supports passing raw engine-native bodies (the `dispatch_run_query` service path at [`cluster.py:256-289`](../../../../backend/app/services/cluster.py#L256-L289) does the same for the `POST /run_query` endpoint). The Elasticsearch `ids` query and OpenSearch `ids` query are wire-compatible on both engines (the only two MVP1 adapters); no engine-specific branching needed.
- **[`backend/app/db/models/judgment.py:36-86`](../../../../backend/app/db/models/judgment.py#L36-L86)** — `Judgment` ORM model. Columns used by the probe: `judgment_list_id` (FK), `query_id` (FK), `doc_id` (Text NOT NULL). The probe pulls `doc_id` rows filtered by `(judgment_list_id, query_id)`. Index `judgments_list_query_idx` at [`judgment.py:55`](../../../../backend/app/db/models/judgment.py#L55) on `(judgment_list_id, query_id)` makes the lookup O(log N).
- **[`backend/app/db/models/query.py:25-40`](../../../../backend/app/db/models/query.py#L25-L40)** — `Query` ORM model. Columns: `id` (PK, `Mapped[str]`/`String(36)` — UUIDv7-as-text), `query_set_id` (FK), `query_text`. The probe needs only `id` for the JOIN to `judgments`. `query_text` is NOT logged (per §10 Threat 2 — no PII / no query text in logs); the probe is doc-ID-existence, not text-relevance (see Anti-patterns §4).
- **[`backend/app/db/repo/judgment.py:228-245`](../../../../backend/app/db/repo/judgment.py#L228-L245)** — `count_judgments_for_list_and_query(db, judgment_list_id, query_id)` already exists. The probe reuses it directly (a second SELECT round-trip after `find_first_judged_query`) to populate `OverlapProbeResult.judged_doc_count` BEFORE the cap is applied. The probe is intentionally 3 SELECT round-trips total — `find_first_judged_query` + `count_judgments_for_list_and_query` + `list_doc_ids_for_list_and_query` — followed by one adapter `search_batch`. Performance budget per FR-2 absorbs the extra round-trips comfortably (~5ms each on local Postgres).
- **[`backend/app/db/repo/judgment.py`](../../../../backend/app/db/repo/judgment.py)** — no `list_doc_ids_for_list_and_query` function exists yet. The probe introduces a new repo function `list_doc_ids_for_list_and_query(db, judgment_list_id, query_id) -> list[str]` returning the `judgments.doc_id` rows for one (list, qid) pair.
- **[`backend/app/db/repo/__init__.py`](../../../../backend/app/db/repo/__init__.py)** — `__all__` export list. The new repo functions must be appended to keep the public surface intact.
- **No equivalent service module exists.** This feature introduces a new `backend/app/services/study_preflight.py` (~80 LOC) with one public coroutine `probe_judgment_overlap(...)` per CLAUDE.md service layer conventions.

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| (none) | (no URL/route changes) | — |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/contract/test_studies_error_codes.py` | Asserts error envelopes for `POST /api/v1/studies` failure paths | (no change) | Add 1 new case for 422 `INSUFFICIENT_JUDGMENT_OVERLAP`. |
| `backend/tests/contract/test_studies_api_contract.py` | Ordering source-presence locks on the POST handler | (no change) | Add 1 new source-presence case asserting the probe call sits AFTER the `JUDGMENT_TARGET_MISMATCH` check at `studies.py:271-283` and BEFORE the config-serialize block at `studies.py:286`. |
| `backend/tests/integration/test_studies_api.py` | Studies POST integration tests | (no change) | Add 5 new cases — see §14 Test strategy. **Subsequently migrated to real-engine end-to-end** in [`infra_study_preflight_real_engine_integration`](../../../00_overview/planned_features/infra_study_preflight_real_engine_integration/feature_spec.md): AC-1 through AC-4b were rewritten from `monkeypatch.setattr("backend.app.api.v1.studies.probe_judgment_overlap", fake_probe)` to real seeded judgments + bulk-indexed ES docs + real probe, via the helpers in `backend/tests/integration/fixtures/es_overlap_probe.py`. AC-5..AC-13 stayed as `_FakeProbeAdapter` synthetic tests. |
| `backend/tests/unit/services/` (existing dir) | Pure unit tests for service helpers | (existing siblings) | Add `test_study_preflight.py` covering the probe orchestration with a mocked adapter (≥3 cases: happy path with ≥3 hits → `OverlapProbeResult` returned; empty-judgments → INFO log + sentinel `representative_query_id=None`; cluster-unreachable → `None` returned + WARN log with `reason="unreachable"`). |
| `ui/tests/e2e/` | No new E2E. The dropdown's existing target+cluster filter already prevents this 422 in the modal happy path; chat-agent and direct-API callers exercise the 422 path. | (no change) | — |

### Existing behaviors affected by scope change

- **Existing studies with re-indexed corpora:** Current: pass create-time validation (no overlap check exists); orchestrator runs all trials at 0.0 metric until Tier 3 (`feat_orchestrator_zero_streak_abort`) aborts at trial 20. New: such studies cannot be created via `POST /api/v1/studies` when the overlap probe returns <3. Existing queued/running rows are NOT retroactively rejected. **Decision needed: no** — locked per Decision Log "Q1 → B (2-tier)" and "forward-only fix" matching Tier 1's precedent.
- **`POST /studies` latency:** Current p99 ~50ms (FK lookups + INSERT). New: adds one bounded `_search` round-trip to the configured cluster (one `acquire_adapter` build + `search_batch` call). Expected p99 ~150ms on a healthy cluster (probe budget capped at 2.0s — see FR-4). **Decision needed: no** — operator-visible only on study create, which is a low-frequency operation.
- **`POST /studies` on unreachable cluster:** Current: 201, study queued, orchestrator detects the cluster is unreachable on first trial and fails the study. New: 201 still issued (probe falls through with WARN log per Q2 → A); behavior unchanged for the operator. **Decision needed: no** — locked per Decision Log "Q2 → A".
- **`POST /studies` on cluster that returns the probe's `ids` query as a 4xx/5xx:** Current: N/A (no probe). New: probe catches `InvalidQueryDSLError` / `QueryTimeoutError` / generic `ClusterUnreachableError` → WARN log + skip-probe + study creates. The `ids` query is engine-native on both ES + OpenSearch (no version-skew risk through MVP1's ES 8.11+/9.x and OpenSearch 2.x/3.x support matrix). **Decision needed: no** — graceful-degrade is the existing pattern at the create-time write boundary.

---

## 3) Scope

### In scope

- **(B1) New service helper.** New module `backend/app/services/study_preflight.py` exporting:
  - A frozen `@dataclass` `OverlapProbeResult` with fields `overlap_size: int` (intersection count, 0..MAX_PROBED_DOCS), `probed_doc_count: int` (number of judged doc IDs actually shipped in the `ids` query — equal to `min(judged_doc_count_for_qid, MAX_PROBED_DOCS)`), `judged_doc_count: int` (total `judgments.doc_id` rows for the chosen qid, BEFORE the cap), `representative_query_id: str | None` (`None` only on the empty-judgments path). The handler reads these to compose the 422 error message.
  - An async public function `probe_judgment_overlap(db, cluster, judgment_list_id, query_set_id, target) -> OverlapProbeResult | None` returning a `OverlapProbeResult` on a successful probe (including the empty-judgments path, where `overlap_size=0, judged_doc_count=0, probed_doc_count=0, representative_query_id=None`), or `None` to signal "probe skipped, caller should allow creation" (returned ONLY on cluster-unreachable / probe-timeout per Q2).
  - Module-level constants: `MIN_OVERLAP = 3`, `PROBE_TIMEOUT_S = 2.0`, `MAX_PROBED_DOCS = 200`. No `Settings` field — module-level constants match the [`feat_orchestrator_zero_streak_abort`](../../../00_overview/implemented_features/2026_05_22_feat_orchestrator_zero_streak_abort/feature_spec.md) precedent (its `_NO_SIGNAL_STREAK_LIMIT = 20` is a module-level constant in `backend/workers/orchestrator.py`).
- **(B2) New repo function.** `list_doc_ids_for_list_and_query(db, judgment_list_id, query_id, *, limit: int) -> list[str]` in `backend/app/db/repo/judgment.py`. Single `SELECT doc_id FROM judgments WHERE judgment_list_id = :list AND query_id = :qid ORDER BY doc_id ASC LIMIT :limit`. `limit` is a required keyword arg (NOT a default-valued arg) so callers cannot accidentally fetch an unbounded list; the probe passes `limit=MAX_PROBED_DOCS`. A separate `count_judgments_for_list_and_query` (already exists at `backend/app/db/repo/judgment.py:228-245`) is reused by the probe to capture the pre-cap `judged_doc_count` for the error message.
- **(B3) New repo function.** `find_first_judged_query(db, query_set_id, judgment_list_id) -> str | None` in `backend/app/db/repo/query.py` returning the `queries.id` value (UUIDv7-as-text) of the first query (by `id ASC`) in the query set that has ≥1 judgment in the list, or `None` if no qid in the set has any judgments. Single JOIN-SELECT per the idea: `SELECT q.id FROM queries q WHERE EXISTS (SELECT 1 FROM judgments j WHERE j.query_id = q.id AND j.judgment_list_id = :list) AND q.query_set_id = :set ORDER BY q.id ASC LIMIT 1`. `query_text` is NOT selected (per §10 Threat 2 — query strings stay out of logs).
- **(B4) POST handler integration.** Insert a call to `probe_judgment_overlap(...)` between the existing `JUDGMENT_TARGET_MISMATCH` block (`studies.py:271-283`) and the `config_payload = body.config.model_dump(...)` line at `studies.py:286`. On `probe_judgment_overlap` returning an `OverlapProbeResult` with `overlap_size < min(MIN_OVERLAP, max(result.judged_doc_count, 1))`, raise `_err(422, "INSUFFICIENT_JUDGMENT_OVERLAP", ...)` with the message composed from the result fields + the resolved `cluster.name` + `body.target` + `judgment_list.name`. On `None` (probe skipped), fall through silently (the probe function already emitted the WARN log; the handler does NOT log a second time). Exception handling for the service-level `ClusterUnreachable`/adapter-level `ClusterUnreachableError`/`TimeoutError`/`QueryTimeoutError`/`InvalidQueryDSLError` happens INSIDE the probe function — the handler is exception-free on these paths.
- **(B5) Error-code registration.** New `INSUFFICIENT_JUDGMENT_OVERLAP` row added to `docs/01_architecture/api-conventions.md` directly after the `JUDGMENT_TARGET_MISMATCH` row (in firing order: cluster → target → overlap).
- **(B6) Unit test file.** Add `backend/tests/unit/services/test_study_preflight.py`. The `backend/tests/unit/services/` subdirectory already exists with siblings `test_agent_judgments_dispatch.py`, `test_agent_proposals_dispatch.py`, `test_dispatch_run_query.py`, `test_study_state.py` — the new file follows the established naming convention for service-layer unit tests.
- **(B7) Structlog events.** Two new event names emitted from the probe:
  - `studies.preflight.overlap_probe.skipped` (WARNING level) — fired when the probe catches a cluster-unreachable / timeout / invalid-DSL exception per FR-4. Fields: `study_judgment_list_id`, `study_query_set_id`, `study_target`, `cluster_id`, `cluster_name`, `reason` (`unreachable` | `timeout` | `invalid_query_dsl`). Both `cluster_id` (UUIDv7) and `cluster_name` (operator-set kebab-case) are included so the log is grep-friendly without a join to `clusters` at triage time.
  - `studies.preflight.overlap_probe.empty` (INFO level) — fired when no qid in the query set has any judgments (FR-3). Fields: `study_judgment_list_id`, `study_query_set_id`. The handler still raises 422 `INSUFFICIENT_JUDGMENT_OVERLAP`; this log records the edge case for operator triage.

### Out of scope

- **Re-running the probe at orchestrator startup.** The probe is create-time only. If an operator re-indexes the corpus AFTER a study is queued but BEFORE it starts, the orchestrator's existing per-trial failure handling + the Tier 3 zero-streak abort catch it mid-flight. Re-probing at orchestrator startup would re-implement the same logic at a second boundary — out of scope.
- **Probing multiple representative queries.** The probe uses ONE representative qid (the first by `id ASC` with ≥1 judgment). Probing K queries multiplies the latency cost by K and changes the operator-perceived semantics (currently `INSUFFICIENT_JUDGMENT_OVERLAP` = "this representative qid found <3 overlap"; with K-query it becomes "the AND/OR across K reps found <3"). Locked to K=1 for MVP1 simplicity.
- **`metric_delta_warning` field on the success response.** Per Q1 → B; no new envelope pattern. Operators with overlap 1–2 receive the same 422 they'd get for 0 overlap.
- **Operator-tunable `STUDY_PREFLIGHT_OVERLAP_MIN` setting.** Per "Settings: ... Default literal is fine for MVP1" in the idea + the orchestrator-zero-streak-abort precedent: module-level constant only. If a real operator hits the 3-floor and needs to tune it, file a follow-up.
- **Migration.** None — no schema changes; both `judgments` + `queries` already exist with the columns the probe needs.
- **Audit-event emission.** Pre-MVP2 — `audit_log` table not present yet.
- **Frontend UI work.** None. The chat-agent's `create_study` tool and direct-API callers surface the new 422 via the existing 422-handler in the orchestrator (no new tool branching needed). The create-study modal's existing target+cluster filter prevents the most-common path to this 422 in practice.
- **Probe via `render(template, params, query_text)`-then-`search_batch` pattern.** Per Decision Log "Probe shape" → the probe uses a hand-built `{"query": {"ids": {"values": [...]}}}` body directly, bypassing template rendering. Rationale: deterministic, no param synthesis, false-positive-immune to template-body breakage. The idea's original proposal of rendering the template was based on "the probe should mirror what the orchestrator does"; the ids-existence probe answers the exact stated question ("do judged doc IDs exist in the current index?") more cleanly. See Decision Log entry for full rationale.

### API convention check

- **Endpoint prefix convention:** `/api/v1/<resource>` for business endpoints. Verified in [`backend/app/api/v1/studies.py:188`](../../../../backend/app/api/v1/studies.py#L188). No new endpoints introduced.
- **Router file:** `backend/app/api/v1/studies.py` (existing).
- **HTTP methods:** No new endpoints; existing POST `/studies` keeps its method.
- **Non-auth error envelope shape:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` per the `_err(...)` helper at [`studies.py:74-78`](../../../../backend/app/api/v1/studies.py#L74-L78). The new `INSUFFICIENT_JUDGMENT_OVERLAP` follows this exact shape.
- **Auth error shape:** N/A in MVP1 (no auth surface).

### Phase boundaries

Single phase. Entire feature ships in one PR. No deferred phases.

## 4) Product principles and constraints

- **Fail fast on deterministic create-time problems.** Spending 2.0s budget at create time to spare 10 minutes of trial budget is a strictly positive operator UX trade.
- **One adapter round-trip, capped.** The probe issues exactly one `search_batch` call against one target. No fan-out across queries, no per-trial probe, no recursive retries.
- **Tolerate transient cluster failures at write time.** Consistent with cluster registration philosophy — the cluster being temporarily unreachable does not block study creation. The orchestrator surfaces the cluster failure at trial time anyway.
- **No new envelope pattern.** The 422 follows the canonical envelope. No `metric_delta_warning` field, no per-endpoint success-with-warning shape.
- **Forward-only.** Pre-existing queued/running studies are not retroactively rejected (mirrors Tier 1's precedent).
- **Specific over generic error codes** when the failure has a deterministic recovery path. `INSUFFICIENT_JUDGMENT_OVERLAP` is preferred over a generic `VALIDATION_ERROR` so the frontend (when later wired) can render a targeted helper UI linking to `/judgments`.

### Anti-patterns

- **Do not** probe via `adapter.render(template, params, query_text)`-then-`search_batch`. Rendering requires concrete parameter values that the create-study handler does not have (the search space defines distributions, not values); synthesizing midpoints introduces a brittle code path that can false-positive on template bodies that happen to be broken at the synthesized values. The ids-existence probe answers the exact stated question without parameter synthesis.
- **Do not** issue multiple probe queries (e.g., K representative queries with majority voting). Multiplies latency by K, introduces tunables, and changes the operator-perceived semantics of `INSUFFICIENT_JUDGMENT_OVERLAP`. Locked at K=1.
- **Do not** retry the probe on `ClusterUnreachableError`. The adapter already handles connection retry semantics; a second probe call would just multiply the create-time latency without changing the outcome.
- **Do not** add a `metric_delta_warning` field on the 201 response (Q1 → B). RelyLoop has no existing success-with-warning envelope pattern; introducing one for this feature creates a precedent every future "warn-but-allow" feature will reference.
- **Do not** persist the probe result (intersection size, chosen qid, etc.) on the `studies` row. The probe is ephemeral — its sole purpose is the create-time decision. Persisting it implies a contract for re-running / displaying it, which is out of scope.
- **Do not** reject when the probe is skipped due to cluster-unreachable. The fall-through 201 is the contract; rejecting here would conflict with the cluster-registration philosophy of tolerating transient adapter failures at write time.
- **Do not** raise the new error before FK + query_set + cluster + target checks. The ordering at `studies.py:206-283` is meaningful (FK → query_set → cluster → target → overlap). Reordering changes which 404/422 the caller sees for ambiguous failures.
- **Do not** retroactively probe pre-existing studies. The check fires only at `POST /studies`; existing queued/running rows are out of scope.

## 5) Assumptions and dependencies

- **`Judgment.doc_id` is `Text NOT NULL`.** Confirmed at [`backend/app/db/models/judgment.py:69`](../../../../backend/app/db/models/judgment.py#L69). Every judgment row has a doc_id, so the SELECT always returns concrete strings.
- **`judgments_list_query_idx` exists on `(judgment_list_id, query_id)`.** Confirmed at [`backend/app/db/models/judgment.py:55`](../../../../backend/app/db/models/judgment.py#L55). The probe's repo queries hit this index.
- **`acquire_adapter()` translates credential failures to `ClusterUnreachable`.** Confirmed at [`backend/app/services/cluster.py:246-249`](../../../../backend/app/services/cluster.py#L246-L249). The probe's `try/except` covers both `ClusterUnreachable` (service-layer) and `ClusterUnreachableError` (adapter-layer) — same pattern as `clusters.py:316-321`.
- **`SearchAdapter.search_batch` accepts a hand-built `NativeQuery` with raw `body`.** Confirmed via the `dispatch_run_query` service path at [`cluster.py:256-289`](../../../../backend/app/services/cluster.py#L256-L289). No `render()` step required.
- **ES `ids` query is wire-compatible with OpenSearch.** Verified against [Elasticsearch query DSL reference](https://www.elastic.co/guide/en/elasticsearch/reference/current/query-dsl-ids-query.html) and [OpenSearch query DSL reference](https://opensearch.org/docs/latest/query-dsl/term/ids/). Both engines accept `{"query": {"ids": {"values": [...]}}, "size": N}` against the unified `_search` endpoint.
- **`feat_study_target_judgment_mismatch_guard` (Tier 1) is shipped.** Confirmed via PR #184 (squash `ce3fcf4`, merged 2026-05-21). The new probe inserts itself AFTER Tier 1's checks so the cluster + target equality precondition holds for every probe execution.
- **CLAUDE.md Absolute Rule #4 ("Never bypass the engine adapter Protocol") is honored.** The probe uses `adapter.search_batch(...)` — a Protocol method. Bypassing `render()` does NOT bypass the Protocol; it constructs the `NativeQuery` body directly, the same way `dispatch_run_query` does for the run_query endpoint.
- **`Settings` is not extended.** The three module-level constants live in `backend/app/services/study_preflight.py`. Settings extension is explicitly out of scope per the idea.

## 6) Actors and roles

- **Primary actor:** Relevance engineer (per umbrella spec §6).
- **Role model:** N/A — single-tenant install, no auth surface (MVP1).
- **Permission boundaries:** N/A.

### Authorization

N/A — single-tenant install, no auth surface (per [`docs/01_architecture/tech-stack.md` "Canonical release matrix"](../../../01_architecture/tech-stack.md)).

### Audit events

N/A — `audit_log` lands at MVP2 per [`docs/01_architecture/data-model.md` §"Reserved for later releases"](../../../01_architecture/data-model.md). Pre-MVP2, mutations do not emit audit events.

## 7) Functional requirements

### FR-1: Run the overlap probe at POST /studies after Tier 1's checks

- Requirement:
  - The system **MUST** invoke `probe_judgment_overlap(db, cluster, judgment_list_id, query_set_id, target)` in [`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py) AFTER the existing `JUDGMENT_TARGET_MISMATCH` block (line 271-283) and BEFORE the `config_payload = ...` line at line 286.
  - The system **MUST** evaluate this check AFTER the FK resolution (`JUDGMENT_LIST_NOT_FOUND`, `QUERY_SET_NOT_FOUND`, `CLUSTER_NOT_FOUND`, `TEMPLATE_NOT_FOUND`), AFTER the existing `query_set_id` cross-check at [`studies.py:240-247`](../../../../backend/app/api/v1/studies.py#L240-L247), AFTER the `JUDGMENT_CLUSTER_MISMATCH` check at [`studies.py:249-265`](../../../../backend/app/api/v1/studies.py#L249-L265), and AFTER the `JUDGMENT_TARGET_MISMATCH` check at [`studies.py:267-283`](../../../../backend/app/api/v1/studies.py#L267-L283).
  - The handler **MUST** reuse the existing `_err(...)` envelope helper for the 422 response.
- Notes: Ordering preserves the 404-before-422 contract Tier 1 established. The probe is the last create-time check before the row is committed.

### FR-2: Probe shape — bounded `ids`-query against the study's target

- Requirement:
  - The probe **MUST** select a single representative `query_id` from `(judgment_list_id, query_set_id)` via a deterministic JOIN-SELECT: `SELECT q.id FROM queries q WHERE EXISTS (SELECT 1 FROM judgments j WHERE j.query_id = q.id AND j.judgment_list_id = :list) AND q.query_set_id = :set ORDER BY q.id ASC LIMIT 1` (encapsulated in `repo.find_first_judged_query`). `query_text` is intentionally NOT selected (privacy — query strings stay out of logs and the probe doesn't need them).
  - The probe **MUST** capture the total per-qid judged-doc count via `count_judgments_for_list_and_query` (existing repo function) BEFORE applying the cap, to populate `OverlapProbeResult.judged_doc_count` for the error-message contract.
  - The probe **MUST** fetch up to `MAX_PROBED_DOCS = 200` `judgments.doc_id` rows for `(judgment_list_id, query_id)` ordered deterministically by `doc_id ASC` via `repo.list_doc_ids_for_list_and_query(..., limit=MAX_PROBED_DOCS)`. The cap protects against degenerate judgment lists with thousands of judgments per qid; the deterministic ordering keeps the probe replayable.
  - The probe **MUST** issue exactly one `adapter.search_batch(target=target, queries=[NativeQuery(query_id="overlap_probe", body={"query": {"ids": {"values": <judged_doc_ids>}}, "size": <N>})], top_k=N, strict_errors=True, timeout=PROBE_TIMEOUT_S)` call where `N = len(judged_doc_ids)` (i.e. `probed_doc_count`). `strict_errors=True` so engine errors raise typed exceptions (`InvalidQueryDSLError` / `ClusterUnreachableError`) the probe catches per FR-4, rather than silently returning empty hits and producing a false 422. `top_k=N` because the ids query returns at most one hit per requested id.
  - The probe **MUST** wrap the adapter call in `asyncio.wait_for(..., timeout=PROBE_TIMEOUT_S + 1.0)` for an outer wall-clock guard, mirroring the `dispatch_run_query` pattern at [`cluster.py:277-286`](../../../../backend/app/services/cluster.py#L277-L286).
  - The probe **MUST** extract its hits from the `search_batch` response — per the Protocol at [`backend/app/adapters/protocol.py:174-196`](../../../../backend/app/adapters/protocol.py#L174-L196), `search_batch` returns `dict[str, list[ScoredHit]]` keyed by the input `query_id`. The probe reads `hits = result.get("overlap_probe", [])` (same pattern as [`cluster.py:289`](../../../../backend/app/services/cluster.py#L289) `dispatch_run_query`), and populates `OverlapProbeResult.overlap_size = len(hits)`. The `ids` query semantics guarantee `hits ⊆ judged_doc_ids`, so the count IS the intersection size — no separate set-intersection logic is needed.
- Notes: `strict_errors=True` is the run_query endpoint's existing pattern at [`backend/app/services/cluster.py:278-289`](../../../../backend/app/services/cluster.py#L278-L289). The probe inherits the same exception model.

### FR-3: Decision matrix — 2-tier with cap-aware threshold

- Requirement:
  - When `probe_judgment_overlap(...)` returns an `OverlapProbeResult`, the handler **MUST** compute `required = min(MIN_OVERLAP, max(result.judged_doc_count, 1))` and compare `result.overlap_size` against it:
    - `overlap_size < required` → return HTTP 422 with `error_code = "INSUFFICIENT_JUDGMENT_OVERLAP"`. No row is inserted into `studies`; no Arq job is enqueued.
    - `overlap_size >= required` → proceed to the config-serialize block (201).
  - The `required = min(MIN_OVERLAP, max(judged_doc_count, 1))` formula closes the GPT-5.5 cycle-1 F7 case: a judgment list whose representative qid has only 2 judgments requires overlap=2 (all of them present) rather than overlap=3 (impossible). The `max(..., 1)` floor handles the empty-judgments path where `judged_doc_count = 0` — required collapses to 1, and overlap=0 < 1 → 422, matching the empty-path expectation.
  - When `find_first_judged_query` returns `None` (no qid in the query_set has any judgments), the probe **MUST** emit a structlog INFO event `studies.preflight.overlap_probe.empty` with fields `{study_judgment_list_id, study_query_set_id}` and return `OverlapProbeResult(overlap_size=0, probed_doc_count=0, judged_doc_count=0, representative_query_id=None)` (which the handler maps to the rejection branch via the formula above). No `acquire_adapter`/`search_batch` is invoked on this path — there are no judged doc IDs to probe against.
  - The error message **MUST** be of the form: `f"judgment_list {judgment_list.name!r}: representative query_id={result.representative_query_id!r} has {result.overlap_size} of {result.probed_doc_count} probed doc IDs present in cluster {cluster.name!r} target {body.target!r} (judged_doc_count={result.judged_doc_count}). This is a strong signal of corpus/judgment mismatch (e.g., the target index was re-indexed or rotated since the judgments were authored) — pytrec_eval will likely score 0 on every trial. Regenerate judgments against the current index, or rebuild the index from the snapshot the judgments were authored on."`. When `judged_doc_count > probed_doc_count` (the cap fired), the message explicitly says "X of N probed" so the operator knows the result is sampled. The wording is deliberately "likely score 0" rather than "will score 0 on every trial" because the probe checks only the representative qid, not all qids.
  - The error envelope **MUST** match the canonical shape: `{"detail": {"error_code": "INSUFFICIENT_JUDGMENT_OVERLAP", "message": "...", "retryable": false}}`. `retryable=false` because the same request body will produce the same 422 until the operator regenerates judgments or rebuilds the index.
- Notes: The cutoff value `MIN_OVERLAP = 3` is locked at the module level. It is NOT an environment variable, NOT a `Settings` field, and NOT operator-tunable in MVP1.

### FR-4: Cluster-unreachable behavior — fall through with WARN log

- Requirement:
  - When the probe's `search_batch` call (or the surrounding `acquire_adapter` / `asyncio.wait_for` wrappers) raises any of the following exceptions, the probe function **MUST** catch the exception, emit a structlog WARNING event `studies.preflight.overlap_probe.skipped` with fields `{study_judgment_list_id, study_query_set_id, study_target, cluster_id, cluster_name, reason}` (reason ∈ `{"unreachable", "timeout", "invalid_query_dsl"}`) BEFORE returning, and return `None`:
    - `backend.app.services.cluster.ClusterUnreachable` (raised by `acquire_adapter` when `CredentialsMissing` resolves to a missing secret file) → `reason="unreachable"`
    - `backend.app.adapters.errors.ClusterUnreachableError` (adapter-layer: connection failure / auth 401-403 not under target ACL / 5xx) → `reason="unreachable"`
    - `asyncio.TimeoutError` (raised by the outer `asyncio.wait_for(PROBE_TIMEOUT_S + 1.0)`) → `reason="timeout"`
    - `backend.app.adapters.errors.QueryTimeoutError` (adapter-layer: inner httpx timeout) → `reason="timeout"`
    - `backend.app.adapters.errors.InvalidQueryDSLError` (adapter-layer: engine rejected the `ids` body) → `reason="invalid_query_dsl"`
  - When `probe_judgment_overlap` returns `None`, the handler **MUST** fall through to the config-serialize block (no additional log; the probe function already logged the reason).
  - On fall-through, the study **MUST** be created (201) exactly as if the probe never ran.
- Notes: This is the Q2=A decision. The orchestrator catches the cluster issue per-trial at job time; the operator sees the same failure surface they would for any cluster-unreachable study. Adding a 503 here would be inconsistent with cluster-registration philosophy (a transiently-unreachable cluster is still registerable). The `InvalidQueryDSLError` catch is a defense-in-depth safety net — the `ids` query body is one of the most basic engine surfaces and should not be rejected; if it IS rejected, that's an adapter defect (or engine version skew) worth WARN-logging but not worth blocking create on. Target-not-exists-at-probe-time is rare in practice (Tier 1 already string-matched `judgment_list.target` against `body.target`, and adapter-layer target-missing surfaces as different behavior — either empty hits per `search_batch`'s `_msearch` semantics, or a `ClusterUnreachableError` covered above; the probe does not need to special-case `TargetNotFoundError` because `search_batch` is not documented to raise it per [`backend/app/adapters/protocol.py:174-196`](../../../../backend/app/adapters/protocol.py#L174-L196)).

### FR-5: New error code in api-conventions.md

- Requirement:
  - The system **MUST** register `INSUFFICIENT_JUDGMENT_OVERLAP` as a stable machine-readable error code in [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md), in the studies-endpoint error-code table, in firing order: after `JUDGMENT_TARGET_MISMATCH` and before any subsequent codes.
  - The code **MUST** be 422 with `retryable: false`.
  - The api-conventions.md entry **MUST** describe the recovery path (regenerate judgments against the current index, OR rebuild the index from the snapshot the judgments were authored on).
- Notes: Two registration sites (this spec §7.5 + api-conventions.md), per Tier 1's precedent at api-conventions.md:78-79.

## 8) API and data contract baseline

### 7.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/studies` | Create + enqueue start_study | `INSUFFICIENT_JUDGMENT_OVERLAP` (422 — new, fires after target check); existing: `CLUSTER_NOT_FOUND` (404), `TEMPLATE_NOT_FOUND` (404), `QUERY_SET_NOT_FOUND` (404), `JUDGMENT_LIST_NOT_FOUND` (404), `INVALID_SEARCH_SPACE` (400), `SEARCH_SPACE_UNKNOWN_PARAM` (400), `SEARCH_SPACE_MISSING_DECLARED_PARAM` (400), `VALIDATION_ERROR` (422 query_set mismatch), `JUDGMENT_CLUSTER_MISMATCH` (422), `JUDGMENT_TARGET_MISMATCH` (422). |

### 7.2 Contract rules

- Error body **MUST** include `error_code` (machine-readable, never renamed once shipped).
- Status code 422 **MUST** be deterministic per scenario: representative-qid overlap below `min(MIN_OVERLAP, max(judged_doc_count, 1))` → `INSUFFICIENT_JUDGMENT_OVERLAP`; target mismatch (existing) → `JUDGMENT_TARGET_MISMATCH`; cluster mismatch (existing) → `JUDGMENT_CLUSTER_MISMATCH`; query_set mismatch (existing) → `VALIDATION_ERROR`; FK lookup → 404 with the specific entity code.
- The new probe **MUST** fire AFTER all FK resolutions AND after the three Tier 1 422 checks. Source-presence locked in a contract test.

### 7.3 Response examples

**Success — POST /api/v1/studies (existing shape, unchanged):**
```json
{
  "id": "01990000-0000-7000-8000-000000000001",
  "name": "tune-products-boost",
  "cluster_id": "01990000-0000-7000-8000-000000000010",
  "target": "products",
  "template_id": "01990000-0000-7000-8000-000000000020",
  "query_set_id": "01990000-0000-7000-8000-000000000030",
  "judgment_list_id": "01990000-0000-7000-8000-000000000040",
  "search_space": {"params": {"boost": {"kind": "float", "low": 0.5, "high": 10}}},
  "objective": {"metric": "ndcg", "k": 10, "direction": "maximize"},
  "config": {"max_trials": 100, "sampler": "tpe", "pruner": "median"},
  "status": "queued",
  "failed_reason": null,
  "optuna_study_name": "01990000-0000-7000-8000-000000000001",
  "...": "...remaining StudyDetail fields..."
}
```

**Failure — POST /api/v1/studies, insufficient overlap (NEW):** HTTP 422
```json
{
  "detail": {
    "error_code": "INSUFFICIENT_JUDGMENT_OVERLAP",
    "message": "judgment_list 'products-judgments-v1': representative query_id='01990000-0000-7000-8000-000000000050' has 0 of 50 probed doc IDs present in cluster 'acme-products-prod' target 'products' (judged_doc_count=50). This is a strong signal of corpus/judgment mismatch (e.g., the target index was re-indexed or rotated since the judgments were authored) — pytrec_eval will likely score 0 on every trial. Regenerate judgments against the current index, or rebuild the index from the snapshot the judgments were authored on.",
    "retryable": false
  }
}
```

Above example has `judged_doc_count = probed_doc_count = 50` (no cap-firing). When the cap fires (e.g., qid has 500 judgments), the message reads `"0 of 200 probed doc IDs ... (representative query_id='...', judged_doc_count=500)"` so the operator can see both numbers.

### 7.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `POST /studies` `error_code` | `INSUFFICIENT_JUDGMENT_OVERLAP` (new); existing per `studies.py` `_err(...)` call sites | `backend/app/api/v1/studies.py` (`_err(...)` invocations) — codes are string literals, not a centralized Literal | None on frontend yet — the modal pre-filters by target+cluster so the operator rarely submits this. The chat agent's `create_study` tool surfaces the error via the orchestrator's existing 422-handler; no new branching needed. |
| `studies.preflight.overlap_probe.skipped` `reason` | `unreachable`, `timeout`, `invalid_query_dsl` | `backend/app/services/study_preflight.py` (string literals in the log statement) | None — log field only. |

No new option lists, status enums, or filter chips introduced. No new `<select>` dropdowns added.

### 7.5 Error code catalog

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `INSUFFICIENT_JUDGMENT_OVERLAP` | 422 | `POST /api/v1/studies` create-time probe sampled up to `MAX_PROBED_DOCS=200` judged `doc_id`s from the first qid in the query set with any judgments (by `id ASC`); the count present in the study's target index was below `min(MIN_OVERLAP, max(judged_doc_count, 1))`. `retryable: false`. Recovery: regenerate judgments against the current index (most common cause: target index was rebuilt or `_reindex`'d with new doc IDs since the judgments were authored), or rebuild the index from the snapshot the judgments were authored on. Fires after `JUDGMENT_TARGET_MISMATCH`. Probe is skipped (with WARN log) when the cluster is unreachable at probe time — the orchestrator's per-trial failure handling catches that case mid-flight. |

Register in BOTH the feature spec §7.5 (this section, canonical) AND `docs/01_architecture/api-conventions.md` directly after the `JUDGMENT_TARGET_MISMATCH` row.

## 9) Data model and state transitions

### New/changed entities

**Modified table: (none)** — no schema changes. `judgments`, `queries`, `judgment_lists`, `studies` all exist with the columns the probe needs.

**No Pydantic schema changes.** The 422 envelope uses the canonical `_err(...)` helper; no new request/response models.

### Required invariants

- **Probe is read-only.** `probe_judgment_overlap(...)` issues only SELECTs (no INSERT, UPDATE, or DELETE). Verified by absence of `db.add` / `update(...)` / `delete(...)` in the service-module diff at PR review time.
- **Probe is bounded-round-trip.** AT MOST ONE `acquire_adapter` enter/exit pair AND at most one `search_batch` call per `POST /studies` invocation that reaches the probe. ZERO adapter calls on the empty-judgments path (`find_first_judged_query` returned `None`) — the probe short-circuits before `acquire_adapter`. No retries, no fan-out.
- **Probe cap honored.** `len(judged_doc_ids)` passed to `search_batch` is `≤ MAX_PROBED_DOCS = 200`. The repo function's required `limit` keyword arg enforces the LIMIT at the SQL boundary; the probe passes `limit=MAX_PROBED_DOCS` explicitly.

### State transitions

None. Feature is purely validation; no new state machine states or transitions.

### Idempotency/replay behavior

N/A — this is a synchronous validator on the request handler. No event delivery, no Arq job, no Redis state.

## 10) Security, privacy, and compliance

- **Threats:**
  1. **Operator submits valid-looking but doc-ID-disjoint (target, judgment_list) via the chat agent's `create_study` tool, bypassing the modal.** Mitigated by the backend `POST /studies` rejection (FR-1+FR-3) — the contract layer is the security/correctness boundary.
  2. **Probe leaks data via the log fields.** The `skipped`/`empty` log statements record only IDs (UUIDv7 strings), the target name (already public — operator-set), the cluster id, and the cluster name (also operator-set, public). No PII, no judgment ratings, no `query_text`. Verified by the explicit field list in §3 B7 + FR-4.
  3. **Probe `ids`-query body size attack via a degenerate judgment list with 10⁵ rows for one qid.** Mitigated by `MAX_PROBED_DOCS = 200` cap at the repo layer. The cluster sees an `ids` query with at most 200 values regardless of how many judgments exist.
  4. **Probe timeout amplifying create-time latency under cluster pressure.** Mitigated by `PROBE_TIMEOUT_S = 2.0` (adapter call) + 1.0s `asyncio.wait_for` outer guard. Total wall-clock cost is bounded at 3.0s; on healthy clusters the probe completes in ~50ms.
- **Controls:** Pure read-only validation logic; no new attack surface beyond the existing adapter call path that `dispatch_run_query` already exposes via `POST /clusters/{id}/run_query`.
- **Secrets/key handling:** N/A. The probe uses the existing `acquire_adapter(cluster)` which reads credentials from the same `./secrets/<cluster.credentials_ref>` mount used by every other adapter call.
- **Auditability:** N/A in MVP1 (`audit_log` lands at MVP2). Two structlog events (FR-4) provide operator-visible traceability of probe skips + empty-judgment-set rejections.
- **Data retention/deletion/export impact:** None.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** No new routes. All frontend behavior is the existing create-study modal at [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx); the modal's existing target+cluster filter already prevents the most common path to this 422.
- **Labeling taxonomy:** No new labels.
- **Content hierarchy:** Existing 5-step wizard preserved.
- **Progressive disclosure:** None.
- **Relationship to existing pages:** Backend-only validator. No UI surface added.

### Tooltips and contextual help

No new tooltip placements. The error envelope's `message` field carries the operator-readable recovery copy when the 422 surfaces.

### Primary flows

1. **Happy path — operator submits a matching tuple via the modal.**
   - Step 1: operator picks cluster `acme-products-prod` + target `products`.
   - Step 2: dropdown filters by target+cluster, operator picks a judgment list whose doc IDs are present in the current index.
   - Steps 3–5 complete; `POST /api/v1/studies` issues the probe → returns ≥3 overlap → 201 + StudyDetail + Arq enqueue.

2. **Backend rejection — chat agent submits a stale-judgments tuple.**
   - Chat agent's `create_study` tool sends `{cluster_id, target, judgment_list_id, ...}` where `judgment_list.target == body.target` (Tier 1 check passes) but the index was re-built since the judgments were authored.
   - Handler reaches the new probe → probe returns `0` → handler raises 422 `INSUFFICIENT_JUDGMENT_OVERLAP` with the structured recovery message.
   - Chat agent's existing 422-handler surfaces the message to the user, who clicks through to `/judgments` and regenerates.

3. **Cluster unreachable at probe time — graceful fall-through.**
   - Operator submits a valid-looking study but the configured cluster is temporarily offline.
   - Handler reaches the probe → `acquire_adapter` raises (or `search_batch` raises) `ClusterUnreachable*` → the probe function catches the exception, emits the `studies.preflight.overlap_probe.skipped` WARN log with `reason="unreachable"`, and returns `None`.
   - Handler treats `None` as fall-through (no second log) → continues to config-serialize + INSERT + 201.
   - Orchestrator picks up the study, attempts the first trial, surfaces the cluster failure per the existing per-trial failure pipeline.

### Edge/error flows

- **Empty judgment list (judgment_list exists but has 0 judgment rows).** Probe's `find_first_judged_query` returns `None` → emit `studies.preflight.overlap_probe.empty` INFO log → return `overlap_size = 0` → 422 `INSUFFICIENT_JUDGMENT_OVERLAP`. Operator regenerates judgments.
- **Empty query_set (query_set exists but has 0 queries).** Same as above — `find_first_judged_query` returns `None`. The pre-existing `query_set` FK passed, so the empty-set case falls into the empty-judgments code path.
- **Judgment list status='generating' (worker hasn't finished writing rows).** The probe queries whatever exists at probe time. If some rows are written and at least one qid has ≥3 overlap, the study creates. If zero rows are written yet, 422. Consistent with the "no special-casing of status" decision from Tier 1.
- **Adapter raises `InvalidQueryDSLError`.** Probe returns `None` → WARN log with `reason="invalid_query_dsl"` → study creates. The `ids` query is one of the most basic engine bodies; an adapter rejecting it indicates a defect worth investigating but not worth blocking create.
- **MAX_PROBED_DOCS cap is hit (qid has >200 judgments).** Probe samples the lexicographically-first 200 by `doc_id`. The probability of zero overlap in 200 random doc-IDs from a re-indexed corpus is effectively 0; the probability of zero overlap in 200 lexicographically-first doc-IDs is also 0 unless the operator's re-index happened to preserve only the lexicographically-LAST doc IDs (pathological). Acceptable trade.

## 12) Given/When/Then acceptance criteria

### AC-1: Insufficient overlap → 422 INSUFFICIENT_JUDGMENT_OVERLAP

- Given a cluster `C`, query set `Q` with one query `q1`, query template `T`, and a judgment list `J` with `target=products`, `query_set_id=Q.id`, `cluster_id=C.id`, and 50 judgments for `q1` whose `doc_id` values are `["doc_old_001", ..., "doc_old_050"]`
- And the cluster's `products` index currently contains ONLY doc IDs `["doc_new_001", ..., "doc_new_100"]` (re-indexed; no overlap with the judgments)
- When the operator calls `POST /api/v1/studies` with body `{cluster_id: C.id, target: "products", template_id: T.id, query_set_id: Q.id, judgment_list_id: J.id, name: "stale-judgments-study", search_space: {...}, objective: {...}, config: {...}}`
- Then the response is HTTP 422 with body `{"detail": {"error_code": "INSUFFICIENT_JUDGMENT_OVERLAP", "message": <contains "0 of 50 probed">, "retryable": false}}`
- And no row is inserted into `studies`
- And no Arq job is enqueued
- Example values:
  - `judgment_count_for_q1`: `50`
  - `index_doc_count`: `100`
  - `overlap_size`: `0`
  - Expected message contains substrings `"0 of 50 probed"`, `"products"`, the cluster name, the judgment list name, and `"judged_doc_count=50"`.

### AC-2: Sufficient overlap → 201

- Given the same setup as AC-1 except the cluster's `products` index contains 100 docs whose IDs are `["doc_old_001", "doc_old_002", "doc_old_003", "doc_new_004", ..., "doc_new_100"]` (3 of the 50 judgments are present)
- When `POST /api/v1/studies` is called with the same body
- Then the response is HTTP 201 with the existing `StudyDetail` shape (`status: "queued"`)
- And a row is inserted into `studies`
- And `start_study(study_id)` is enqueued

### AC-3: Overlap exactly at threshold → 201

- Given the same setup with `overlap_size == 3` (exactly at `MIN_OVERLAP`)
- When `POST /api/v1/studies` is called
- Then the response is HTTP 201 (≥ MIN_OVERLAP semantics — boundary inclusive)
- Notes: Locks the inclusive-≥ boundary against accidental drift to strict-> in the implementation.

### AC-4: Overlap one below threshold → 422

- Given `overlap_size == 2`
- When `POST /api/v1/studies` is called
- Then the response is HTTP 422 with `INSUFFICIENT_JUDGMENT_OVERLAP`
- Notes: Boundary lock for the strict-< side.

### AC-5: Probe fires AFTER FK + Tier 1 checks

- Given a `judgment_list_id` that does NOT exist in `judgment_lists`
- When `POST /api/v1/studies` is called
- Then the response is HTTP 404 `JUDGMENT_LIST_NOT_FOUND` (not 422 `INSUFFICIENT_JUDGMENT_OVERLAP`)
- And the probe is never called (verified by mock-assertion in the test)
- Notes: Same precedent as Tier 1 AC-3.

### AC-6: Probe fires AFTER JUDGMENT_TARGET_MISMATCH

- Given a judgment list with `target="indexA"` and a study `body.target="indexB"` (with matching cluster_id)
- When `POST /api/v1/studies` is called
- Then the response is HTTP 422 with `error_code = "JUDGMENT_TARGET_MISMATCH"` (target mismatch wins — fires first)
- And the probe is never called
- Notes: Ordering source-presence test in contract layer locks `studies.py` line-order across refactors.

### AC-7: Cluster unreachable → 201 with WARN log

- Given a study create body that would otherwise pass the probe
- And the cluster's adapter raises `ClusterUnreachableError` when `search_batch` is invoked (mocked via fixture)
- When `POST /api/v1/studies` is called
- Then the response is HTTP 201 with the existing `StudyDetail` shape
- And a structlog event `studies.preflight.overlap_probe.skipped` is emitted at WARNING level with fields `{study_judgment_list_id, study_query_set_id, study_target, cluster_id, reason: "unreachable"}`
- And a row IS inserted into `studies`
- And `start_study(study_id)` IS enqueued

### AC-8: Probe timeout → 201 with WARN log

- Given a study create body that would otherwise pass the probe
- And the adapter's `search_batch` blocks beyond `PROBE_TIMEOUT_S + 1.0` seconds (mocked via fixture using `asyncio.sleep`)
- When `POST /api/v1/studies` is called
- Then the response is HTTP 201
- And a structlog event `studies.preflight.overlap_probe.skipped` is emitted at WARNING with `reason: "timeout"`
- And the study row IS inserted

### AC-9: Empty judgments → 422 + INFO log

- Given a judgment list `J` with `target=products`, matching `cluster_id` + `query_set_id`, status `complete`, and ZERO judgment rows (the worker reported `complete` with empty output, OR the operator imported an empty CSV — both are valid current states)
- When `POST /api/v1/studies` is called with `judgment_list_id=J.id`
- Then the response is HTTP 422 with `INSUFFICIENT_JUDGMENT_OVERLAP`
- And a structlog event `studies.preflight.overlap_probe.empty` is emitted at INFO level
- Notes: `find_first_judged_query` returns `None` → probe returns `overlap_size = 0` → handler raises 422.

### AC-10: MAX_PROBED_DOCS cap is honored

- Given a judgment list with 500 judgment rows for the first qid (`doc_id` values `["doc_001", "doc_002", ..., "doc_500"]`)
- And the cluster's index contains ONLY `["doc_499", "doc_500"]` (the lexicographically-LAST two)
- When `POST /api/v1/studies` is called
- Then the response is HTTP 422 `INSUFFICIENT_JUDGMENT_OVERLAP` (overlap_size = 0 because the cap fetches `doc_001..doc_200` and none of those are in the index)
- And the `adapter.search_batch` call receives a NativeQuery body with `len(values) == 200` (not 500) — asserted via mock
- And the error message contains substrings `"0 of 200 probed"` AND `"judged_doc_count=500"` (so the operator sees both numbers and understands the sample is capped)
- Notes: Validates the `MAX_PROBED_DOCS` cap at the wire boundary AND the message wording when the cap fires.

### AC-11: Probe payload + target + timeout passed correctly to adapter

- Given a probe call with judged_doc_ids = `["doc_A", "doc_B", "doc_C"]` and target `"products"`
- When the probe invokes `search_batch`
- Then `adapter.search_batch` is called with `target="products"`, exactly one `NativeQuery` whose `body == {"query": {"ids": {"values": ["doc_A", "doc_B", "doc_C"]}}, "size": 3}` and `query_id="overlap_probe"`, `top_k=3`, `strict_errors=True`, and `timeout=PROBE_TIMEOUT_S`
- And when the mocked adapter returns `{"overlap_probe": [ScoredHit(doc_id="doc_A", score=1.0), ScoredHit(doc_id="doc_B", score=1.0)]}` (note: dict keyed by query_id, per the Protocol's `dict[str, list[ScoredHit]]` return type), the probe **MUST** read `result.get("overlap_probe", [])` and populate `OverlapProbeResult.overlap_size = 2`
- Notes: Locks the exact wire shape, the `strict_errors=True` choice, AND the dict-key unpacking pattern so future refactors can't silently revert to `strict_errors=False` (false 422) or misread `result["wrong_key"]` (KeyError or False 0-overlap).

### AC-13: FR-4 exception matrix — every fall-through path produces 201 + WARN log

- Given a study create body that would otherwise pass the probe
- And the mocked adapter (via `monkeypatch` on `ElasticAdapter.search_batch`) is parameterized over each of the five FR-4 exception classes
- When `POST /api/v1/studies` is called
- Then for each parameterized case, the response **MUST** be HTTP 201, the study row **MUST** be inserted, the Arq job **MUST** be enqueued, AND a `studies.preflight.overlap_probe.skipped` WARN log event **MUST** be emitted with the corresponding `reason` field:
  - `ClusterUnreachable` raised inside `acquire_adapter` → `reason="unreachable"`
  - `ClusterUnreachableError` raised by `search_batch` → `reason="unreachable"`
  - `asyncio.TimeoutError` raised by the outer `asyncio.wait_for` → `reason="timeout"`
  - `QueryTimeoutError` raised by `search_batch` → `reason="timeout"`
  - `InvalidQueryDSLError` raised by `search_batch` → `reason="invalid_query_dsl"`
- Notes: AC-7 + AC-8 cover two of the five paths via separate test functions; AC-13 wraps the parametrized matrix so future exception additions (or removals from FR-4) require a synchronized test update. Use `pytest.mark.parametrize` over a `(exception_factory, expected_reason)` list.

### AC-12: Pre-existing studies on read paths are not affected

- Given a study row with insufficient overlap was inserted before this feature shipped (or seeded by a fixture)
- When `GET /api/v1/studies/{id}` is called for that row
- Then the response is HTTP 200 with the existing `StudyDetail` shape
- Notes: Negative-existence test — proves the probe did not leak into read paths.

## 13) Non-functional requirements

- **Performance:** Probe wall-clock cost on a healthy cluster: ~50ms (one DB JOIN + one DB doc_id fetch + one `_search` round-trip). p99 budget capped at 3.0s by `PROBE_TIMEOUT_S + 1.0` `asyncio.wait_for`. New per-call overhead on `POST /api/v1/studies`: ~50-150ms typical, 3.0s worst case before fall-through.
- **Reliability:** Probe failure modes (cluster unreachable, timeout, invalid query) ALL fall through to create-success per FR-4. Zero new write-time blocking failure modes.
- **Operability:** Two new structlog events (`studies.preflight.overlap_probe.skipped` WARN + `studies.preflight.overlap_probe.empty` INFO). The existing FastAPI access log captures the 422. No new metrics.
- **Accessibility/usability:** The 422 envelope `message` field surfaces operator-readable recovery copy. No new UI elements.

## 14) Test strategy requirements (spec-level)

| Layer | Required tests |
|---|---|
| Unit (backend) | New file `backend/tests/unit/services/test_study_preflight.py` (alongside the existing `test_agent_judgments_dispatch.py`, `test_dispatch_run_query.py`, `test_study_state.py` siblings — 3 cases minimum): (1) probe returns `OverlapProbeResult` with `overlap_size=3` on happy path with mocked adapter returning 3 ScoredHits; (2) probe returns `OverlapProbeResult(0, 0, 0, None)` when `find_first_judged_query` returns None AND emits the `studies.preflight.overlap_probe.empty` INFO log (no `acquire_adapter` invoked — assert via mock); (3) probe returns `None` when mocked adapter raises `ClusterUnreachableError` AND emits the `studies.preflight.overlap_probe.skipped` WARN log with `reason="unreachable"`. |
| Integration (backend, real engine) | Extend `backend/tests/integration/test_studies_api.py` with 6 new real-engine cases against the dockerized ES service container: (1) AC-1 zero-overlap → 422; (2) AC-2 sufficient overlap → 201; (3) AC-3 boundary-inclusive (overlap=3) → 201; (4) AC-4 boundary-exclusive (overlap=2) → 422; (5) AC-9 empty-judgments → 422 + INFO log assertion; (6) AC-12 pre-existing study read-path negative test. Real seeded ES + real judgments + real judgment-list rows; mocked LLM (per existing project convention). These cases validate the probe end-to-end against a real engine. |
| Integration (backend, adapter-call-shape via mocks) | Extend `test_studies_api.py` with 5 adapter-call-shape cases via `monkeypatch` on `ElasticAdapter.search_batch`: (1) AC-7 unreachable → 201 + WARN log; (2) AC-8 timeout → 201 + WARN log; (3) AC-10 MAX_PROBED_DOCS cap honored at the wire boundary + message wording assertion; (4) AC-11 NativeQuery body shape lock including `strict_errors=True` AND dict-key unpacking; (5) AC-13 parametrized FR-4 exception matrix — `pytest.mark.parametrize` over `[(ClusterUnreachable, "unreachable"), (ClusterUnreachableError, "unreachable"), (asyncio.TimeoutError, "timeout"), (QueryTimeoutError, "timeout"), (InvalidQueryDSLError, "invalid_query_dsl")]`, each asserting 201 + INSERT + Arq enqueue + the matching `reason` field on the WARN log. Mocking is intentional here — these cases assert that the probe code path makes the right adapter call AND handles every documented exception, not that the engine behaves as expected. Use the existing `_log_helpers.py` structlog assertion helpers from `infra_structlog_test_helpers` (PR #114). |
| Contract (backend) | (1) Extend `backend/tests/contract/test_studies_error_codes.py` with the `INSUFFICIENT_JUDGMENT_OVERLAP` 422 envelope assertion. (2) Extend `backend/tests/contract/test_studies_api_contract.py` with a source-presence ordering lock: assert that the substring `"INSUFFICIENT_JUDGMENT_OVERLAP"` in `studies.py` appears strictly AFTER `"JUDGMENT_TARGET_MISMATCH"` and strictly BEFORE the line `config_payload = body.config.model_dump`. |
| Contract (backend, openapi) | (none) — no schema changes; the OpenAPI surface lock at `test_openapi_surface.py` is not affected. |
| Adapter coverage (ES + OpenSearch) | The probe relies on the `{"query": {"ids": {"values": [...]}}}` body being wire-compatible across both MVP1 engines. Per Decision Log entry, the existing `infra_adapter_elastic` adapter Protocol contract tests already cover both engines for `search_batch`; the probe inherits this coverage without adding engine-specific test cases. If real-engine integration tests use only ES (the CI service-container default), this is accepted for MVP1; OpenSearch compatibility is covered by the adapter Protocol contract. |
| E2E (frontend) | (none) — the modal's existing target+cluster filter prevents the modal path to this 422 in practice; chat-agent path is covered by integration tests. |

## 15) Documentation update requirements

- `docs/01_architecture/api-conventions.md` — add the `INSUFFICIENT_JUDGMENT_OVERLAP` row to the studies-endpoint error-code table, directly after `JUDGMENT_TARGET_MISMATCH`.
- `docs/00_overview/planned_features/feat_study_preflight_overlap_probe/` — this spec file; `pipeline_status.md` to be added.
- `docs/03_runbooks/` — no new runbook (the 422 message is self-explanatory; the existing `study-lifecycle-debugging.md` runbook already covers POST /studies failure modes — extend with one paragraph on `INSUFFICIENT_JUDGMENT_OVERLAP` recovery during impl).
- `docs/04_security/` — no change (no new attack surface; the probe is read-only).
- `docs/05_quality/` — no change (existing unit + integration + contract layers cover the new code; the first `unit/services/` subdirectory does NOT require a doc update because it follows the existing test-layer convention).
- `state.md` — updated with the feature in the "Most recent meaningful changes" log on merge.
- `architecture.md` — no change (no new layer, no new flow; `backend/app/services/study_preflight.py` is a new module but doesn't introduce a new top-level layer).
- `CLAUDE.md` — no change (no new convention, no new env var, no new absolute rule).

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. Hard-gate at the API boundary; staged rollout would mean half of POST /studies calls trigger the probe and half don't — strictly worse than shipping atomically.
- **Migration/backfill expectations:** None — no schema changes.
- **Operational readiness gates:** None new — existing CI gates (`make lint`, `make typecheck`, `make test-unit`, `make test-integration`, `make test-contract`) plus the contract-layer source-presence ordering lock catch all regressions.
- **Release gate:**
  - All 12 ACs (AC-1 through AC-12) pass in CI.
  - `api-conventions.md` is updated in the same PR.
  - At least 1 cycle of GPT-5.5 cross-model review on the implementation plan.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-5, AC-6, AC-12 | (B4) Insert probe call in `studies.py` POST handler between lines 283 and 286 (no surrounding try/except — the probe function handles its own exceptions) | `tests/contract/test_studies_api_contract.py` (source-presence ordering lock for AC-5 + AC-6 — locks the substring positions of `JUDGMENT_LIST_NOT_FOUND`, `JUDGMENT_TARGET_MISMATCH`, `INSUFFICIENT_JUDGMENT_OVERLAP` in `studies.py`); `tests/integration/test_studies_api.py` (AC-5 + AC-6 runtime ordering tests via `monkeypatch` on `probe_judgment_overlap` to assert it is NOT invoked on FK-404 / target-mismatch paths; AC-12 read-path negative test) | this spec §7.5 |
| FR-2 | AC-10, AC-11 | (B1) `probe_judgment_overlap` service function; (B2) `list_doc_ids_for_list_and_query` repo function; (B3) `find_first_judged_query` repo function | `tests/unit/services/test_study_preflight.py` (3 cases); `tests/integration/test_studies_api.py` (AC-10, AC-11 mock assertions) | (none — internal) |
| FR-3 | AC-1, AC-2, AC-3, AC-4, AC-9 | (B4) Conditional `if result.overlap_size < min(MIN_OVERLAP, max(result.judged_doc_count, 1)): raise _err(422, ...)` in handler; (B7) `studies.preflight.overlap_probe.empty` INFO log on the `None`-qid path | `tests/contract/test_studies_error_codes.py` (envelope assertion); `tests/integration/test_studies_api.py` (AC-1..4 real-engine, AC-9 mocked) | `api-conventions.md`, this spec §7.5 |
| FR-4 | AC-7, AC-8 | (B1) `try/except (ClusterUnreachable, ClusterUnreachableError, asyncio.TimeoutError, QueryTimeoutError, InvalidQueryDSLError)` INSIDE the probe function — emits WARN log + returns `None`; the POST handler treats `None` as fall-through, no second log | `tests/integration/test_studies_api.py` (AC-7, AC-8 adapter-call-shape mocks) | (none) |
| FR-5 | (none direct — documentation) | (B5) Add row to `docs/01_architecture/api-conventions.md` | (covered by contract envelope test asserting code lives at the route) | `api-conventions.md` |

## 18) Definition of feature done

- [ ] All acceptance criteria AC-1 through AC-12 pass in CI.
- [ ] Backend unit/integration/contract tests pass.
- [ ] `docs/01_architecture/api-conventions.md` updated with the new error-code row.
- [ ] Source-presence ordering lock in `test_studies_api_contract.py` passes (probe fires AFTER target check, BEFORE config-serialize).
- [ ] No open questions remain in §19.
- [ ] PR includes GPT-5.5 final review pass + Gemini Code Assist adjudication.
- [ ] `state.md` updated with the feature's merge entry.

## 19) Open questions and decision log

### Open questions

(none — all decisions locked. See Decision log below.)

### Decision log

- **2026-05-22 — Q1 (decision matrix) → B (2-tier).** Rationale per idea.md "Open questions Q1": RelyLoop has no existing success-with-warning envelope pattern; introducing one for a partial-overlap case creates a precedent every future "warn-but-allow" feature would reference. Operators with 1-2 overlap have the same recovery action (regenerate judgments) as operators with 0 overlap, so collapsing them into one 422 simplifies the spec, the contract test, and the operator's mental model. The trade is "more aggressive — a study with overlap=2 might still produce some signal that the operator now can't see"; accepted because a study with 2 judged docs ⊆ a top-50 retrieval cannot reliably tune any parameter regardless.
- **2026-05-22 — Q2 (cluster-unreachable behavior) → A (fall through with WARN log).** Rationale per idea.md "Open questions Q2": consistent with cluster-registration philosophy — a temporarily-unreachable cluster is still registerable, and the orchestrator's per-trial failure handling already surfaces cluster issues at trial time. Rejecting at probe time would force operators into a different recovery path (wait for cluster + retry POST) than the rest of the codebase's "tolerate transient adapter failures at write time" pattern.
- **2026-05-22 — Probe shape: `ids`-existence (NEW) over `render(template, params)`-then-`search_batch` (idea's original proposal).** Rationale: the idea's original proposal of rendering the study's query template required synthesizing concrete parameter values from the search-space distributions (Optuna samples them at trial time; create-time has only the distributions, not values). Synthesizing midpoints introduces a brittle path that can false-positive on template bodies that happen to be broken at the synthesized values. The ids-existence probe (a `{"query": {"ids": {"values": [...]}}}` body) answers the exact stated question — "do judged doc IDs exist in the current index?" — deterministically, without parameter synthesis, and is wire-compatible across both MVP1 adapters (ES + OpenSearch). The idea-author's stated risk ("the probe relies on top_k being large enough to surface the judged docs ... if the template body is itself broken, the probe will false-positive on 'no overlap'") is exactly the failure mode this design choice eliminates. The probe still uses the `SearchAdapter` Protocol (`search_batch`), so CLAUDE.md Absolute Rule #4 is honored.
- **2026-05-22 — `MIN_OVERLAP = 3` is a module-level constant, NOT a `Settings` field.** Rationale: matches the [`feat_orchestrator_zero_streak_abort`](../../../00_overview/implemented_features/2026_05_22_feat_orchestrator_zero_streak_abort/feature_spec.md) precedent (its `_NO_SIGNAL_STREAK_LIMIT = 20` is module-level). Operator tunability deferred until a real operator hits the floor.
- **2026-05-22 — `MAX_PROBED_DOCS = 200` cap at the repo layer.** Rationale: protects against degenerate judgment lists with thousands of judgments per qid shipping a huge `ids` payload to the cluster. 200 is well below typical ES/OpenSearch `_search` `ids`-clause limits; large enough that the lexicographic-first-200 sample of a re-indexed corpus has near-zero false-positive risk.
- **2026-05-22 — `PROBE_TIMEOUT_S = 2.0` (adapter call) + 1.0s outer `asyncio.wait_for` guard.** Rationale: matches the `dispatch_run_query` pattern at [`cluster.py:277-286`](../../../../backend/app/services/cluster.py#L277-L286) but tighter (run_query allows 5–30s; the probe is a single bounded `ids` query and should not exceed 2.0s on a healthy cluster).
- **2026-05-22 — Single representative qid (K=1), NOT majority voting across K reps.** Rationale: K>1 multiplies latency by K, introduces tunables, and changes the operator-perceived semantics of `INSUFFICIENT_JUDGMENT_OVERLAP` from "one rep has <3 overlap" to "the AND/OR across K reps has <3". MVP1 simplicity wins; if operators report false negatives in production, a K-bumping follow-up can revisit.
- **2026-05-22 — Probe is read-only; no persistence of overlap size, chosen qid, or any probe metadata on `studies` row.** Rationale: persisting it implies a contract for re-running / displaying it. The probe is ephemeral — its sole purpose is the create-time decision.
- **2026-05-22 — `studies.preflight.overlap_probe.empty` is INFO (not WARN).** Rationale: empty-judgment-set is an operator-input error, not an infrastructure failure. The 422 surfaces the issue to the operator; the log records it for triage without polluting WARN-level alerts.
- **2026-05-22 — `studies.preflight.overlap_probe.skipped` is WARN (not INFO).** Rationale: cluster-unreachable at probe time is an actual transient infrastructure failure. Operators monitoring WARN-level events should see it.
- **2026-05-22 — Pre-existing queued/running studies with insufficient overlap are NOT retroactively rejected.** Rationale: matches Tier 1's forward-only precedent. Mid-flight catch belongs to Tier 3 (`feat_orchestrator_zero_streak_abort`, shipped PR #191).
- **2026-05-22 (post-GPT-5.5 cycle 1)** — Probe return type upgraded from `int | None` to `OverlapProbeResult | None` (dataclass with `overlap_size`, `probed_doc_count`, `judged_doc_count`, `representative_query_id`). Rationale: cycle-1 finding F1 — the canonical error message references `judgment list name`, `cluster name`, `target`, `representative qid`, and `overlap of total`, none of which a bare `int` carries. Returning a structured result also makes the empty-judgments path expressible without a sentinel value collision (overlap=0, judged_doc_count=0, representative_query_id=None is unambiguous).
- **2026-05-22 (post-GPT-5.5 cycle 1)** — Probe uses `strict_errors=True` on `adapter.search_batch`. Rationale: cycle-1 finding F2 — `strict_errors=False` silently turns engine errors into empty hits, which would produce a false 422 INSUFFICIENT_JUDGMENT_OVERLAP rather than a WARN-and-fall-through. With `strict_errors=True`, `InvalidQueryDSLError`/`ClusterUnreachableError` raise from the adapter, the probe catches them, logs WARN, and returns `None`. Matches the existing `dispatch_run_query` pattern.
- **2026-05-22 (post-GPT-5.5 cycle 1)** — Threshold computed as `required = min(MIN_OVERLAP, max(judged_doc_count, 1))` rather than a flat `< MIN_OVERLAP`. Rationale: cycle-1 finding F7 — a judgment list whose representative qid has 2 judgments cannot have overlap=3 even on a healthy cluster (max overlap = 2). The flat formula would reject all such judgment lists; the cap-aware formula requires "all judged docs present" for qids with <3 judgments. The `max(..., 1)` floor handles the empty-judgments path (overlap=0 < required=1 → 422 as expected).
- **2026-05-22 (post-GPT-5.5 cycle 1)** — Error message format uses "X of N probed" wording (with separate `judged_doc_count=N_total`) rather than "X of N judged". Rationale: cycle-1 finding F8 — when the `MAX_PROBED_DOCS=200` cap fires, the probe samples 200 of N>200 judged docs; the operator must be able to distinguish "200 sampled" from "all judgments checked". The new wording exposes both numbers.
- **2026-05-22 (post-GPT-5.5 cycle 1)** — `find_first_judged_query` returns `str | None` (just the query_id), NOT `tuple[str, str] | None` (the original `(query_id, query_text)` proposal). Rationale: cycle-1 finding F10 — logging `query_text` would put query strings into structured logs, which conflicts with §10 Threat 2 ("no PII / no query_text in logs"). The probe doesn't need the text for the `ids`-existence check; the `query_id` alone is sufficient for operator triage.
- **2026-05-22 (post-GPT-5.5 cycle 1)** — REJECTED finding F5 ("`find_first_judged_query` return annotation likely mismatches the ORM id type — should be `UUID` not `str`"). Counter-evidence: [`backend/app/db/models/query.py:30`](../../../../backend/app/db/models/query.py#L30) declares `id: Mapped[str] = mapped_column(String(36), primary_key=True)`. RelyLoop's `Query` ORM stores UUIDv7s as `String(36)` (text), NOT as the native `UUID` type. The `tuple[str, str]` annotation (subsequently simplified to `str` per F10) was correct.
- **2026-05-22 (post-GPT-5.5 cycle 1)** — OpenSearch coverage is implicit via the adapter Protocol contract tests, NOT via per-engine real-engine integration tests for this feature. Rationale: cycle-1 finding F13 — `infra_adapter_elastic`'s Protocol contract tests already exercise `search_batch` on both ES + OpenSearch. The probe code does not branch on engine, so adding engine-specific real-engine integration tests for this feature would duplicate adapter Protocol coverage. CI runs the probe's real-engine integration tests against the ES service container; OpenSearch coverage is satisfied at the Protocol layer.
- **2026-05-22 (post-GPT-5.5 cycle 1)** — DEFERRED finding F14 ("201 gives no indication probe was skipped"). Rationale: the success-with-warning envelope is exactly the precedent §3 In-scope rejects (per Decision Log "Q1 → B"). If operators report confusion about silent probe-skip behavior after MVP1 ships, a follow-up `feat_studies_probe_skip_diagnostic` can add a separate (non-contractual) diagnostics endpoint or response header. Captured here only — not implemented.
- **2026-05-22 (post-GPT-5.5 cycle 2)** — REJECTED cycle-2 F2 ("counts rows not distinct doc IDs — should use `COUNT(DISTINCT doc_id)` and `SELECT DISTINCT doc_id`"). Counter-evidence: [`backend/app/db/models/judgment.py:49-54`](../../../../backend/app/db/models/judgment.py#L49-L54) declares `UniqueConstraint("judgment_list_id", "query_id", "doc_id", name="judgments_unique_key")`. Rows are unique per `(judgment_list_id, query_id, doc_id)`, so a `SELECT doc_id WHERE judgment_list_id = :list AND query_id = :qid` query already returns distinct values. The `DISTINCT` keyword is redundant.
- **2026-05-22 (post-GPT-5.5 cycle 2)** — Contract text scrubbed of legacy "<3" / "<MIN_OVERLAP=3" shorthand. Rationale: cycle-2 F1 — the cap-aware threshold formula `min(MIN_OVERLAP, max(judged_doc_count, 1))` is the actual rule; leaving "<3" in §8.2 / §8.5 / §17 traceability would mislead implementers. All cited locations updated to the formula.
- **2026-05-22 (post-GPT-5.5 cycle 2)** — Spec text aligned on "3 SELECT round-trips + 1 adapter call". Rationale: cycle-2 F3 — §2 Current-state-audit described the probe as "a single JOIN-select" while §3 + FR-2 describe 3 separate repo calls. Tightened §2 to match the implementation reality; performance impact is negligible (~5ms per local-Postgres SELECT) and the separation keeps each repo function single-purpose.
- **2026-05-22 (post-GPT-5.5 cycle 2)** — §11 Primary flow 3 corrected to attribute the WARN log to the probe function (not the handler). Rationale: cycle-2 F4 — FR-4 says probe emits + handler falls through silently; §11's "Handler emits `studies.preflight.overlap_probe.skipped` WARN log" contradicted FR-4. The flow now matches FR-4.
- **2026-05-22 (post-GPT-5.5 cycle 2)** — §1 Outcome + FR-3 error message + §11 narrative updated to clarify the probe checks the *representative* qid only, not the whole judgment list. The error message softened from "pytrec_eval will score 0 on every trial" to "pytrec_eval will likely score 0 on every trial. This is a strong signal of corpus/judgment mismatch." Rationale: cycle-2 F5 + F7 — the K=1 probe can't prove study-wide zero-signal, but in the stated failure modes (re-indexed corpus, rotated index, stale judgments) all qids are uniformly affected. The softened wording matches the actual evidence the probe gathers; the recovery advice is unchanged.
- **2026-05-22 (post-GPT-5.5 cycle 2)** — AC-5 + AC-6 coverage clarified in §17 traceability. Rationale: cycle-2 F6 — §14 test strategy initially under-specified the ordering tests. The traceability matrix now explicitly cites both the source-presence contract test AND the runtime mock-assertion integration test for AC-5 + AC-6.
- **2026-05-22 (post-GPT-5.5 cycle 3)** — `search_batch` response unpacking spelled out explicitly in FR-2 + AC-11. Rationale: cycle-3 F1 — the Protocol returns `dict[str, list[ScoredHit]]` keyed by `query_id`, so the probe accesses `result.get("overlap_probe", [])` (mirroring `dispatch_run_query`'s pattern at [`backend/app/services/cluster.py:289`](../../../../backend/app/services/cluster.py#L289)). Without explicit spec text, an implementer might write `result[0].hits` or `result.hits` and get a runtime error or false 0-overlap.
- **2026-05-22 (post-GPT-5.5 cycle 3)** — FR-4 exception list expanded to enumerate each exception class explicitly with its `reason` value, AND a new AC-13 added covering the parametrized exception matrix. Rationale: cycle-3 F2 + F3 — the spec previously bundled "the cluster-unreachable family" as a single line; the explicit per-exception mapping prevents an implementer from missing a class, and the parametrized AC ensures CI fails if a future refactor breaks any single path. The five exceptions are `ClusterUnreachable` (service), `ClusterUnreachableError` (adapter), `asyncio.TimeoutError` (wait_for), `QueryTimeoutError` (adapter), `InvalidQueryDSLError` (adapter). Target-not-exists is NOT in the list because `search_batch` is not documented to raise `TargetNotFoundError` (per the Protocol docstring).
- **2026-05-22 (post-GPT-5.5 cycle 3)** — Structlog field list aligned: `cluster_name` added alongside `cluster_id` to the `studies.preflight.overlap_probe.skipped` event. Rationale: cycle-3 F4 — §10 Threat 2 said the log records "the cluster name"; FR-4 originally listed only `cluster_id`. Aligned by adding `cluster_name` to FR-4 + §3 B7 (both fields are operator-set / public, so no privacy concern; including both keeps the log grep-friendly at triage time).
