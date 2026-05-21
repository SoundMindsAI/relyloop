# Feature Specification — `propose_search_space` agent tool

**Date:** 2026-05-21
**Status:** Draft
**Owners:** Eric Starr (product + engineering)
**Related docs:**
- [`idea.md`](idea.md)
- [`implementation_plan.md`](implementation_plan.md) (forthcoming)
- [`docs/01_architecture/llm-orchestration.md`](../../../01_architecture/llm-orchestration.md)
- [`docs/01_architecture/agent-tools.md`](../../../01_architecture/agent-tools.md)
- Heuristic source-of-truth: [`ui/src/lib/search-space-defaults.ts`](../../../../ui/src/lib/search-space-defaults.ts)
- Existing 19-tool registry: [`backend/app/agent/tools/__init__.py`](../../../../backend/app/agent/tools/__init__.py)

---

## 1) Purpose

The chat agent's `create_study` tool requires a fully-formed `search_space` (Pydantic `SearchSpace`) at call time ([`backend/app/agent/tools/studies/create_study.py:36-46`](../../../../backend/app/agent/tools/studies/create_study.py#L36-L46)) — yet the agent has no deterministic backend callable that builds one. Today the LLM looks at a template's `declared_params` (via `get_template`) and invents bounds from training-data intuition. The result is search spaces that drift across model versions, look alarmingly like guesses for unfamiliar templates, and aren't grounded in the cluster's data.

- **Problem:** The agent surface is RelyLoop's marketing front door ("describe your relevance problem in chat → tuned config"), but its first concrete step — building the `search_space` — is non-deterministic and ungrounded.
- **Outcome:** A new read-only agent tool `propose_search_space(template_id, cluster_id, judgment_list_id?, prior_study_id?) → SearchSpace JSON` that emits a deterministic, code-generated search space using the same heuristic table that powers the create-study wizard's Step-4 auto-fill ([`ui/src/lib/search-space-defaults.ts`](../../../../ui/src/lib/search-space-defaults.ts)), optionally narrowed by a prior winning trial. The orchestrator's system prompt directs the LLM to call `propose_search_space` before `create_study` so the search space is always grounded.
- **Non-goal:** Force the chain server-side (no 422 on `create_study` without a prior `propose_search_space` call), persist proposals as a new table, expose the tool to the REST API, or change the create-study UI in v1. Cluster-stats grounding (term-frequency, field-length distribution) is deferred to phase 2 once an adapter helper exists.

## 2) Current state audit

### Existing implementations

- [`backend/app/agent/tools/__init__.py:141-228`](../../../../backend/app/agent/tools/__init__.py#L141-L228) — three parallel data structures (`TOOLS`, `TOOL_REGISTRY`, `TOOL_ARG_MODELS`) with a module-load assertion that fails fast on drift. **All three need a `propose_search_space` entry; the expected-count constant in [`backend/tests/unit/agent/test_tool_registry.py`](../../../../backend/tests/unit/agent/test_tool_registry.py) advances from 19 → 20.**
- [`backend/app/agent/tools/studies/create_study.py:1-148`](../../../../backend/app/agent/tools/studies/create_study.py#L1-L148) — canonical tool shape: Pydantic args re-exported as `<ToolName>Args`, `async def <name>_impl(args, ctx) -> dict`, `HTTPException(status_code=…, detail={error_code, message, retryable})` for errors, dict return for success, `_DESCRIPTION` derived from docstring, `<NAME>_TOOL: ChatCompletionToolParam` with `model_json_schema()`. **`propose_search_space` mirrors this shape; it is *read-only* and therefore NOT added to [`backend/app/agent/confirmation.py:14-24`](../../../../backend/app/agent/confirmation.py#L14-L24)'s `MUTATING_TOOL_NAMES`.**
- [`backend/app/agent/tools/studies/get_study.py:1-71`](../../../../backend/app/agent/tools/studies/get_study.py#L1-L71) — closest analog for a read-only tool that takes a UUID and returns a JSON dict. **`propose_search_space` is shaped like `get_study`: read-only, no `ctx.db.commit()`, single UUID arg + optional UUID args.**
- [`ui/src/lib/search-space-defaults.ts:1-211`](../../../../ui/src/lib/search-space-defaults.ts#L1-L211) — the canonical naming-convention heuristic that ships today on the wizard's Step-4 auto-fill. `HEURISTIC_RULES` (lines 38-55), `simpleFormSpec` (lines 73-86), `estimateParamCardinality` (lines 99-110), `estimateCardinality` (lines 120-126), `buildStarterSearchSpace` (lines 147-196) — **mirror this verbatim into [`backend/app/domain/study/search_space_defaults.py`](../../../../backend/app/domain/study/search_space_defaults.py) with a docstring pointer back. Both files must produce byte-identical JSON for any given `declared_params` dict.**
- [`backend/app/domain/study/search_space.py:1-266`](../../../../backend/app/domain/study/search_space.py#L1-L266) — Pydantic `SearchSpace`/`FloatParam`/`IntParam`/`CategoricalParam` discriminated union, `estimate_cardinality()` (lines 177-196, floats=100), `SearchSpace.model_validate()` enforces `min_length=1` on params and ≤10⁶ cardinality cap (line 113-117). **`propose_search_space` returns a JSON dict that passes `SearchSpace.model_validate()` — the cap-aware fallback in `search_space_defaults.py` ensures cardinality ≤ 10⁶.**
- [`backend/app/domain/study/template_defaults.py:49-105`](../../../../backend/app/domain/study/template_defaults.py#L49-L105) — `compute_default_params(template_row) → dict[str, Any]` picks *single concrete values* (midpoints, first categorical, simple-form fallbacks) for template rendering at digest/judgment time. Called from [`backend/workers/digest.py:65,774`](../../../../backend/workers/digest.py#L65) and [`backend/workers/judgments.py:52,189`](../../../../backend/workers/judgments.py#L52). **Not dead code — preserved unchanged. Cross-reference in both docstrings: `compute_default_params` picks values; the new code picks ParamSpec ranges.**
- [`backend/app/db/models/study.py:36-90`](../../../../backend/app/db/models/study.py#L36-L90) — `Study` has `best_trial_id` (line 80, denormalized) and `best_metric` (line 78, denormalized). **Prior-study narrowing path uses `repo.get_study(prior_study_id) → study.best_trial_id → fetch trial → trial.params`.**
- [`backend/app/db/models/trial.py:30-73`](../../../../backend/app/db/models/trial.py#L30-L73) — `Trial.params` JSONB (line 55), `Trial.primary_metric` (line 57), `Trial.status` (line 67). **No `get_trial(db, trial_id)` repo function exists yet** ([`backend/app/db/repo/trial.py`](../../../../backend/app/db/repo/trial.py) — the closest is `list_trials_for_study(study_id)` at line 67). This spec adds `repo.get_trial(db, trial_id) → Trial | None` (parallel to `get_study`) inside Story-2-equivalent work.
- [`backend/app/db/models/proposal.py`](../../../../backend/app/db/models/proposal.py) — `Proposal.study_trial_id` (the winning trial), `Proposal.config_diff` (JSONB). **Judgment-list narrowing path** (`judgment_list_id` arg, v1 keeps this *signature-only* — see §3 Out of scope).
- [`prompts/orchestrator.system.md:7-21`](../../../../prompts/orchestrator.system.md#L7-L21) — hardcodes "You have 19 tools" + lists the 7-tool mutation set. **Both surfaces update: tool count → 20; new bullet under "Studies (3)" → "Studies (4)" with `propose_search_space` as the fourth, read-only.**
- [`backend/tests/unit/agent/test_tool_registry.py`](../../../../backend/tests/unit/agent/test_tool_registry.py) — registry sanity test. Expected tool count + canonical-name set update.

### Navigation and link impact

No URL/route changes. Agent tools are dispatched in-process; there is no router surface.

| Source file | Current link target | New link target |
|---|---|---|
| N/A | N/A | N/A |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`backend/tests/unit/agent/test_tool_registry.py`](../../../../backend/tests/unit/agent/test_tool_registry.py) | `EXPECTED_TOOL_COUNT_MVP1 = 19`, `CANONICAL_MVP1_TOOL_NAMES = {...}` | 1 file | Update count to 20 and add `"propose_search_space"` to the canonical set. |
| [`backend/tests/integration/agent/`](../../../../backend/tests/integration/agent/) | orchestrator/dispatch fixtures that snapshot the tool count or list | TBD | Audit during Story 1 and adjust expected counts; do not invent counts the snapshots don't currently assert. |
| [`backend/tests/unit/domain/test_template_defaults.py`](../../../../backend/tests/unit/domain/test_template_defaults.py) | `compute_default_params` assertions | 1 file | **Unchanged.** This spec does not modify `compute_default_params`. |
| `ui/src/__tests__/lib/search-space-defaults.cardinality.test.ts` (existing) | TS↔Python cardinality fixture | 1 file | **Unchanged for cardinality.** A new parity fixture (next row) covers the heuristic-table parity. |
| **NEW** `backend/tests/unit/domain/test_search_space_defaults_parity.py` | Reads the same JSON fixture the UI parity test consumes; asserts Python `build_starter_search_space()` produces byte-identical output for every input row. | 1 new file | Create; mirror the pattern of [`backend/tests/unit/domain/test_search_space_cardinality_parity.py`](../../../../backend/tests/unit/domain/test_search_space_cardinality_parity.py). |

### Existing behaviors affected by scope change

- **Agent's `create_study` flow.** Current: LLM constructs `search_space` inline from `declared_params` intuition. New: LLM is directed by the system prompt to call `propose_search_space` first; the returned JSON dict is passed verbatim as the `search_space` arg to `create_study`. **Decision needed: no** — system prompt change is the only behavior change. The `create_study` Pydantic contract is unchanged.
- **`prompts/orchestrator.system.md` tool inventory.** Current: "You have 19 tools, … Studies (3): create_study (mutating), get_study, cancel_study (mutating)". New: "You have 20 tools, … Studies (4): propose_search_space, create_study (mutating), get_study, cancel_study (mutating)" + a one-sentence guidance line: "Before calling `create_study`, call `propose_search_space` with the chosen template + cluster (and a `prior_study_id` if the user references one) to ground the bounds; pass its result verbatim to `create_study.search_space`."
- **Adherence telemetry on `create_study` and `propose_search_space`.** Current: no telemetry. New: both tool impls emit paired structlog INFO events tagged with `conversation_id` (`agent.search_space_proposed` from propose, `agent.create_study.invoked` from create). Offline correlation by `conversation_id` measures chain adherence. **Observation-only — never raises, never blocks dispatch.** See §7 FR-6.

---

## 3) Scope

### In scope

- New tool file [`backend/app/agent/tools/studies/propose_search_space.py`](../../../../backend/app/agent/tools/studies/propose_search_space.py): args model, `propose_search_space_impl(args, ctx)`, `_DESCRIPTION`, `PROPOSE_SEARCH_SPACE_TOOL`. Read-only (no `ctx.db.commit()`).
- New shared defaults module [`backend/app/domain/study/search_space_defaults.py`](../../../../backend/app/domain/study/search_space_defaults.py): Python port of `ui/src/lib/search-space-defaults.ts`. Exports `HEURISTIC_RULES`, `simple_form_spec(type_name) → ParamSpec | None`, `estimate_param_cardinality(spec) → int`, `build_starter_search_space(declared_params: dict[str, str]) → StarterSearchSpace` where `StarterSearchSpace` is a small frozen dataclass `{space: SearchSpace, cap_aware_fallback_param_names: list[str]}`. Cap-aware fallback identical to the TS implementation (convert fall-through floats first, then regex-matched floats, lexicographic) — the TS sibling returns `{space, capAwareFallbackParamNames}` from `buildStarterSearchSpace` for parity. Existing TS callers of `buildStarterSearchSpace` (only the create-study wizard's Step-4 auto-fill) update to consume `.space`; the parity test fixture treats `space` as the comparison field.
- New repo function [`backend/app/db/repo/trial.py`](../../../../backend/app/db/repo/trial.py): `async def get_trial(db, trial_id: str) -> Trial | None` — needed for the prior-study narrowing path.
- New domain helper [`backend/app/domain/study/search_space_defaults.py`](../../../../backend/app/domain/study/search_space_defaults.py): `narrow_bounds_around_winner(space: SearchSpace, winning_params: dict[str, Any], bracket: float = 0.5) → tuple[SearchSpace, list[str]]` — ±50% bracket around each winning numeric value (see §7 FR-3 for full math); returns the (possibly-narrowed) `SearchSpace` AND the list of param names that were actually narrowed (per the skip-on-out-of-bounds and non-numeric-winner rules).
- Registry wiring in [`backend/app/agent/tools/__init__.py`](../../../../backend/app/agent/tools/__init__.py) (3 entries: TOOLS, TOOL_REGISTRY, TOOL_ARG_MODELS).
- System-prompt update at [`prompts/orchestrator.system.md`](../../../../prompts/orchestrator.system.md) (tool count 19→20; "Studies (4)" entry; one-line guidance directing the LLM to chain).
- Paired structlog INFO adherence-telemetry events from `propose_search_space_impl` and `create_study_impl`, correlated on `conversation_id` (see FR-6).
- TS↔Python parity test fixture + Python test: any drift in `HEURISTIC_RULES` or `simple_form_spec` fails one of the two parity tests.
- Tests at unit + integration layers (see §14).

### Out of scope

- Frontend "Use in new study" action that pre-fills the create-study modal from a proposal. (Coordinate-only with `feat_study_clone_from_previous`; defer until that ships.)
- New REST endpoint surface. The tool is dispatched only via the agent orchestrator. Operators who want a programmatic search-space proposal go through the chat.
- Cluster-stats grounding (term-frequency, field-length distribution). MVP1 adapter has no such helper; the `cluster_id` arg exists only to validate the cluster exists in v1.
- ±1σ bound-narrowing math (more defensible but needs trial-history aggregation across all complete trials, not just the winner). Locked at ±50% bracket for v1.
- Persisting proposal outputs as a new DB table. v1 is purely in-conversation; the LLM holds the proposal in chat history and passes it verbatim to `create_study`.
- Audit-log event `agent.search_space_proposed` (MVP1 has no `audit_log` table per CLAUDE.md "Activates at MVP2"). v1 logs via structlog only; the event catalog entry lands when MVP2's audit-log machinery does.
- Server-side enforcement that `create_study` was preceded by `propose_search_space`. The orchestrator's per-turn state isn't structured for chain enforcement; encouragement via system prompt + paired INFO-event telemetry (FR-6) is sufficient for v1. Ratchet to force when telemetry shows <80% adherence.
- Modifications to [`backend/app/domain/study/template_defaults.py:compute_default_params`](../../../../backend/app/domain/study/template_defaults.py). It lives side-by-side; its two live callers ([`backend/workers/digest.py:774`](../../../../backend/workers/digest.py#L774), [`backend/workers/judgments.py:189`](../../../../backend/workers/judgments.py#L189)) are unchanged.

### API convention check

This feature does NOT add a REST endpoint. The "API" surface is the agent tool wire-shape (OpenAI function-calling JSON schema generated from a Pydantic model). For internal consistency:

- **Tool registration:** three-struct pattern at [`backend/app/agent/tools/__init__.py:141-228`](../../../../backend/app/agent/tools/__init__.py#L141-L228). The module-load assertion enforces drift-free naming.
- **Error envelope inside a tool:** `HTTPException(status_code=…, detail={"error_code": "...", "message": "...", "retryable": <bool>})` per [`backend/app/agent/tools/studies/create_study.py:39-47`](../../../../backend/app/agent/tools/studies/create_study.py#L39-L47). The orchestrator catches `HTTPException` and wraps the `detail` dict in a `<tool_result>` payload visible to the LLM.
- **Mutating-vs-read-only:** read-only tools dispatch immediately ([`backend/app/agent/confirmation.py:14-24`](../../../../backend/app/agent/confirmation.py#L14-L24)). `propose_search_space` is read-only and stays out of `MUTATING_TOOL_NAMES`.
- **HTTP status codes (inside `HTTPException`):** 400 for invalid input / unknown template that fails to produce a usable starter space, 404 for unknown `cluster_id`/`template_id`/`prior_study_id`. No 422 path — Pydantic-side validation errors at the orchestrator boundary surface as `ValidationError` not 422.

### Phase boundaries (if multi-phase)

This is a **single-phase** delivery. Cluster-stats grounding (mentioned in `idea.md` §"Optional grounding signals") is captured separately in the §3 Out-of-scope list; it requires a new adapter helper that doesn't exist yet, so a phase-2 idea file is **not required** at spec time. Should the operator want it later, capture as `feat_agent_propose_search_space_cluster_stats` (or extend this folder with a `phase2_idea.md` if the work stays minor).

## 4) Product principles and constraints

- **Determinism.** Same inputs → byte-identical output. The tool's output JSON is a pure function of its arguments. No randomness, no model-version sensitivity, no clock dependency. This is the property that distinguishes "code-generated proposal" from "LLM intuition."
- **Cap-aware.** `build_starter_search_space()` returns a `SearchSpace` whose cardinality is ≤ 10⁶ whenever the cap-aware fallback can achieve it; otherwise it raises `InvalidSearchSpaceError` (subclass of `ValueError`) so the tool surfaces `HTTPException(400, INVALID_SEARCH_SPACE)`. The cap-aware fallback (convert floats to `int[0, 5]` in lexicographic priority — fall-through floats first, then regex-matched floats) matches the TS implementation, plus this spec extends both implementations with a post-conversion guard: if cardinality is still > 10⁶ after every float has been converted, the helper raises rather than returning an invalid space. **TS parity:** the TS source [`ui/src/lib/search-space-defaults.ts:147-196`](../../../../ui/src/lib/search-space-defaults.ts#L147-L196) currently returns the invalid space silently with a `console.warn`; this spec's TS-side fix is included in the parity contract (FR-1) and a sibling `bug_search_space_defaults_overflow_ts` idea file is not needed because the fix lands in this PR's parity work.
- **Read-only.** No DB writes. No `ctx.db.commit()`. No background-job enqueue. The tool reads `clusters`, `query_templates`, optionally `studies` + `trials`, and returns a JSON dict.
- **Forward-compatible signature.** `cluster_id` and `judgment_list_id` are required-vs-optional per their primary purpose (cluster=validate-exists, judgment_list=signature-only-for-v1); both ride into the same signature so phase-2 cluster-stats grounding doesn't need a tool rename or arg shuffle.
- **No model name hardcoding.** This rule is moot for `propose_search_space` itself (no LLM call), but the system-prompt update at [`prompts/orchestrator.system.md`](../../../../prompts/orchestrator.system.md) must keep the existing "runs on `gpt-4o-mini`" line (line 51) intact; do not "fix" it to a literal model ID.
- **CLAUDE.md Absolute Rule #4 — adapter gating.** Not engaged by this feature (no engine adapter calls in v1).

### Anti-patterns

- **Do not** add a `force_chain` server-side check on `create_study` that refuses dispatch without a prior `propose_search_space` result in the same chat turn — the orchestrator's per-turn state isn't structured for it, the LLM can be redirected via system prompt + telemetry, and the user can override an awkward LLM call manually. Encouragement + paired INFO-event telemetry is the v1 contract.
- **Do not** persist propose-tool calls in a new DB table. v1 lives in-conversation; the LLM passes the result verbatim into `create_study.search_space`. The MVP2 audit-log table is where adherence eventually graduates from grep-the-logs to query-the-DB.
- **Do not** reimplement the heuristic table inline in `propose_search_space.py`. The Python port lives at `backend/app/domain/study/search_space_defaults.py` and is unit-testable without the agent context. The tool calls it; the wizard ports the same logic (forward path: TS→Python parity test guards drift).
- **Do not** merge or rename `compute_default_params` and `build_starter_search_space`. They serve different purposes (single-value vs range-spec). Cross-reference in each docstring instead.
- **Do not** add the tool to `MUTATING_TOOL_NAMES`. `propose_search_space` is read-only — adding it to the mutation set would force the LLM to ask "are you sure?" before every chain, which adds friction without value.
- **Do not** invent narrowing math beyond ±50% in v1. ±1σ from trial variance is on the table for v2, but locking in ±50% gives `feat_study_clone_from_previous` a shared shape to depend on.
- **Do not** introduce a `chore_template_defaults_dead_code` follow-up. The earlier preflight claim that `compute_default_params` is dead is incorrect — confirmed live in two worker call sites.

## 5) Assumptions and dependencies

- **`feat_chat_agent`** ([`docs/00_overview/implemented_features/2026_05_12_feat_chat_agent/`](../../../00_overview/implemented_features/2026_05_12_feat_chat_agent/)) — shipped PR #60. Provides the 19-tool registry pattern, ToolContext, confirmation guard, and orchestrator dispatch loop. **Hard dependency.**
- **`chore_create_study_wizard_polish`** ([`docs/00_overview/implemented_features/2026_05_20_chore_create_study_wizard_polish/`](../../../00_overview/implemented_features/2026_05_20_chore_create_study_wizard_polish/)) — shipped PR #157. Provides [`ui/src/lib/search-space-defaults.ts`](../../../../ui/src/lib/search-space-defaults.ts) as the heuristic source-of-truth. **Hard dependency** — `backend/app/domain/study/search_space_defaults.py` mirrors this file byte-for-byte.
- **`feat_create_study_search_space_builder`** ([`docs/00_overview/implemented_features/2026_05_20_feat_create_study_search_space_builder/`](../../../00_overview/implemented_features/2026_05_20_feat_create_study_search_space_builder/)) — shipped PR #163. Confirms the visual editor uses the same TS heuristic table; no further coordination required.
- **`feat_study_lifecycle`** Phase 2 — shipped. Provides `Study.best_trial_id`, `Trial.params`, the trial repo. **Hard dependency** for the `prior_study_id` narrowing path.
- **`feat_study_clone_from_previous`** — coordinate-only (still idea-stage). The "narrow bounds around prior winning trial" math lands HERE first; that feature consumes the shared helper once both ship. No blocking interaction.
- **MVP2 audit log** — coordinate-only. `agent.search_space_proposed` event row gets a catalog entry when MVP2's `audit_log` table arrives. v1 logs adherence via structlog only.

Risk if missing: every dependency in the "hard" tier is already shipped to `main`. The only risk is downstream — if `feat_study_clone_from_previous` ships first and lands divergent narrowing math, this spec's helper needs to be reconciled. Mitigation: lock ±50% in §7 FR-3 and document it as the shared contract.

## 6) Actors and roles

- Primary actor: the chat agent's LLM (currently `gpt-4o-mini` per [`prompts/orchestrator.system.md:51`](../../../../prompts/orchestrator.system.md#L51)), driving the tool call on behalf of a relevance engineer.
- Secondary actor: the relevance engineer in the chat surface, observing the proposal in the tool-result block before confirming the subsequent `create_study`.
- Role model: **N/A — single-tenant install, no auth surface** (MVP1).
- Permission boundaries: the agent can call any tool in the registry without RBAC checks; the `propose_search_space` tool itself reads `clusters`, `query_templates`, and optionally `studies`/`trials` — all single-tenant tables in MVP1.

### Authorization

N/A — single-tenant install, no auth surface (MVP1).

### Audit events

N/A — `audit_log` lands at MVP2 per [`docs/01_architecture/data-model.md` §"Forthcoming: audit_log"](../../../01_architecture/data-model.md). v1 emits a structlog event (FR-6) but does not insert into a dedicated event table; the catalog entry `agent.search_space_proposed` is captured for MVP2 in this spec's §15 doc deltas.

## 7) Functional requirements

### FR-1: Heuristic-based starter search space

- Requirement:
  - The system **MUST** expose a Python function `build_starter_search_space(declared_params: dict[str, str]) → StarterSearchSpace` at [`backend/app/domain/study/search_space_defaults.py`](../../../../backend/app/domain/study/search_space_defaults.py), where `StarterSearchSpace` is a frozen dataclass with fields `space: SearchSpace` and `cap_aware_fallback_param_names: list[str]` (empty list when the cap-aware fallback did not fire). The function mirrors the TS [`buildStarterSearchSpace`](../../../../ui/src/lib/search-space-defaults.ts#L147-L196): same heuristic rules, same fall-through, same cap-aware fallback (convert fall-through floats to `int[0,5]` in lex order, then regex-matched floats), same warning emission (Python `logger.warning`, TS `console.warn`). The TS sibling is updated in the same PR to return `{space, capAwareFallbackParamNames}` instead of a bare `SearchSpace`.
  - The system **MUST** publish `HEURISTIC_RULES: list[tuple[re.Pattern, dict[str, Any]]]` as a module-level constant with the exact regex strings from [`ui/src/lib/search-space-defaults.ts:38-55`](../../../../ui/src/lib/search-space-defaults.ts#L38-L55).
  - The system **MUST** publish `simple_form_spec(type_name: str) → ParamSpec | None` matching [`simpleFormSpec`](../../../../ui/src/lib/search-space-defaults.ts#L73-L86) (`'int'` → IntParam[0,5]; `'float'` → FloatParam[0,1]; `'bool'` → CategoricalParam[true,false]; `'string'` → CategoricalParam['__placeholder__']; else None).
  - **Cap-aware overflow guard.** After the cap-aware fallback runs through every float (fall-through then regex-matched, lex order), if `estimate_cardinality(space) > 1_000_000`, the function **MUST** raise [`InvalidSearchSpaceError`](../../../../backend/app/domain/study/search_space.py#L121-L129) with a message that names the declared_params and the post-fallback cardinality. **TS parity:** the TS `buildStarterSearchSpace` is updated in the same PR to `throw new Error(...)` under the same condition (the TS implementation today silently returns a `SearchSpace` that fails Pydantic's `_check_cardinality` — this PR fixes both sides at once). The shared parity fixture (FR-7) includes a fixture row that exercises this boundary (e.g., 8 fall-through floats → both sides throw).
  - For any input that does NOT trigger the overflow guard, the returned `SearchSpace` **MUST** pass [`SearchSpace.model_validate`](../../../../backend/app/domain/study/search_space.py#L92-L118).
- Notes: A parity test (`backend/tests/unit/domain/test_search_space_defaults_parity.py`) reads a shared JSON fixture mirroring the existing cardinality-parity pattern at [`backend/tests/unit/domain/test_search_space_cardinality_parity.py`](../../../../backend/tests/unit/domain/test_search_space_cardinality_parity.py); a sibling TS test (`ui/src/__tests__/lib/search-space-defaults.parity.test.ts`) asserts the same fixture against `buildStarterSearchSpace`. Either file failing flags drift. Fixture row schema is `{name, declared_params, expected_search_space | expected_error}` — the `expected_error` branch covers the overflow case symmetrically (`pytest.raises(InvalidSearchSpaceError)` ↔ `expect(...).toThrow()`).

### FR-2: `propose_search_space` agent tool

- Requirement:
  - The system **MUST** add a tool at [`backend/app/agent/tools/studies/propose_search_space.py`](../../../../backend/app/agent/tools/studies/propose_search_space.py) with signature `async def propose_search_space_impl(args: ProposeSearchSpaceArgs, ctx: ToolContext) → dict[str, Any]`.
  - `ProposeSearchSpaceArgs` **MUST** accept four fields: `template_id: UUID` (required), `cluster_id: UUID` (required), `judgment_list_id: UUID | None = None` (optional), `prior_study_id: UUID | None = None` (optional). All UUID fields are validated by Pydantic.
  - The tool **MUST** be registered in all three structures in [`backend/app/agent/tools/__init__.py`](../../../../backend/app/agent/tools/__init__.py) (`TOOLS`, `TOOL_REGISTRY`, `TOOL_ARG_MODELS`) under the canonical name `"propose_search_space"`.
  - The tool **MUST NOT** appear in [`backend/app/agent/confirmation.py:14-24`](../../../../backend/app/agent/confirmation.py#L14-L24)'s `MUTATING_TOOL_NAMES` (read-only — dispatches without confirmation).
  - The tool **MUST** look up the template via `repo.get_query_template(ctx.db, template_id)`; missing template → `HTTPException(404, {"error_code": "TEMPLATE_NOT_FOUND", …})` (parity with [`create_study.py:60-68`](../../../../backend/app/agent/tools/studies/create_study.py#L60-L68)).
  - The tool **MUST** look up the cluster via `repo.get_cluster(ctx.db, cluster_id)`; missing cluster → `HTTPException(404, {"error_code": "CLUSTER_NOT_FOUND", …})`.
  - When `judgment_list_id` is provided, the tool **MUST** validate it exists via `repo.get_judgment_list`; missing → `HTTPException(404, {"error_code": "JUDGMENT_LIST_NOT_FOUND", …})`. v1 does NOT use its content; the validation is signature-only.
  - When `prior_study_id` is provided, the tool **MUST** load the study via `repo.get_study`; missing → `HTTPException(404, {"error_code": "STUDY_NOT_FOUND", …})`.
  - The tool **MUST** return a JSON-serializable dict shaped `{"search_space": {"params": {...}}, "grounding": {"template_id": "...", "template_name": "...", "cluster_id": "...", "used_prior_study_id": "<id or null>", "narrowed_param_names": ["..."], "cap_aware_fallback_param_names": ["..."], "prior_study_template_mismatch": <bool>}}` so the LLM can pass `result["search_space"]` verbatim into `create_study.search_space`. The `cap_aware_fallback_param_names` field is populated whenever the cap-aware float→int fallback fires (parallel to the structlog WARN); empty list otherwise. The `prior_study_template_mismatch` field is `True` when a `prior_study_id` was provided but its `template_id` did not match (FR-3 graceful degrade); `False` otherwise.
  - The tool **MUST NOT** call `ctx.db.commit()` (read-only).
- Notes: The `grounding` sub-object is for the LLM (to construct an explanation in the chat reply) and for telemetry inspection. It is *not* persisted.

### FR-3: Optional prior-study narrowing (±50% bracket)

- Requirement:
  - **Template-match guard.** When `prior_study_id` resolves, the tool **MUST** compare `prior_study.template_id` to the call's `template_id` argument. If they differ, the tool **MUST NOT** apply narrowing — it returns the heuristic-only starter space, sets `grounding.prior_study_template_mismatch = True`, sets `grounding.used_prior_study_id = str(prior_study.id)` (echoed back so the LLM sees what it asked for), sets `grounding.narrowed_param_names = []`, and emits a structlog WARN `"agent.propose_search_space.prior_template_mismatch"` with `{conversation_id, prior_study_id, prior_template_id, requested_template_id}`. **No error is raised** — the tool degrades gracefully so the LLM can recover with a chat reply rather than a tool-result error.
  - **Trial fetch.** When the template-match guard passes AND `study.best_trial_id is not None`, the tool **MUST** load the winning trial via `repo.get_trial(db, study.best_trial_id)` and read `trial.params` (a `dict[str, Any]`).
  - **Missing trial row.** If `study.best_trial_id` is set but `repo.get_trial` returns `None` (cascade-delete race), the tool **MUST** degrade to heuristic-only (same shape as the template-mismatch graceful degrade: empty `narrowed_param_names`, `used_prior_study_id` echoed back) and emit a structlog WARN `"agent.propose_search_space.missing_winner_trial"`. No error is raised.
  - For each param in the starter `SearchSpace` whose name appears in `trial.params`:
    - **FloatParam (linear, `log=False`):** new bounds = `[max(low, winner * 0.5), min(high, winner * 1.5)]`. If `winner ≤ low` or `winner ≥ high` (out of original bounds), narrowing is skipped for that param (logged at DEBUG); the original bounds carry through.
    - **FloatParam (log-uniform, `log=True`):** geometric narrowing: new bounds = `[max(low, winner / sqrt(2)), min(high, winner * sqrt(2))]`. Same skip-on-out-of-bounds rule.
    - **IntParam:** new bounds = `[max(low, floor(winner * 0.5)), min(high, ceil(winner * 1.5))]`. If `winner ≤ low` or `winner ≥ high`, narrowing is skipped.
    - **CategoricalParam:** **No narrowing** — leave choices intact. (The LLM is expected to read the grounding metadata and choose whether to filter; v1's helper deliberately does not narrow categoricals because removing options can hide useful signal and the math is not symmetric with the numeric path.)
  - The tool **MUST** return the list of narrowed param names in `grounding.narrowed_param_names` for telemetry.
  - The tool **MUST** call the helper as `space, narrowed_names = narrow_bounds_around_winner(space, winning_params, bracket=0.5)` so the bracket constant lives in a single named argument; callers downstream (e.g., `feat_study_clone_from_previous`) consume the same helper. The returned `narrowed_names` list is what populates `grounding.narrowed_param_names`.
  - **Type guards inside narrowing.** `narrow_bounds_around_winner` **MUST** skip narrowing (no exception) when `winning_params[name]` is not a numeric type for FloatParam/IntParam (e.g., the winner stored a string for a param that used to be categorical before a template change). Skipped params are NOT added to `grounding.narrowed_param_names`.
- Notes: The "skip on out-of-bounds" rule means stale winners (a trial from a much narrower historical search) don't degrade the proposal. Skipped params still appear in the returned `SearchSpace` — just with the original starter bounds. The graceful-degrade behavior above (template mismatch, missing trial row, type mismatch) means a stale or inconsistent `prior_study_id` is observed in telemetry but never blocks the proposal.

### FR-4: Narrowing is cardinality non-increasing

- Requirement:
  - `narrow_bounds_around_winner` **MUST** be cardinality non-increasing for every input: FloatParams retain `estimate_cardinality` contribution = 100 regardless of bounds width (per the existing rule at [`backend/app/domain/study/search_space.py:191`](../../../../backend/app/domain/study/search_space.py#L191)), IntParam contributions are `high - low + 1` which can only shrink under ±50% bracket clamping, CategoricalParams are not touched.
  - If `narrow_bounds_around_winner` is called with a `SearchSpace` whose cardinality is already ≤10⁶, the result is also ≤10⁶ by construction. The helper documents this invariant in its docstring; no runtime assertion is required.
- Notes: This is a documentation FR. The non-increasing property — not "always reduces" — is what's true: a FloatParam's `estimate_cardinality` contribution is fixed at 100 regardless of bounds width, so narrowing a float leaves the contribution unchanged. The shrinkage happens only for IntParams under ±50% bracket clamping. Either way, narrowing can't push cardinality over the cap.

### FR-5: Orchestrator system-prompt update

- Requirement:
  - [`prompts/orchestrator.system.md`](../../../../prompts/orchestrator.system.md) **MUST** be updated:
    - Tool count `19` → `20` (line 9).
    - "Studies (3): `create_study` (mutating), `get_study`, `cancel_study` (mutating)" → "Studies (4): `propose_search_space`, `create_study` (mutating), `get_study`, `cancel_study` (mutating)" (line 17).
    - Insert one new bullet (or extend rule #1) directing the LLM: "When the user asks to start an optimization study, call `propose_search_space(template_id, cluster_id, prior_study_id?)` *before* `create_study`. Pass `result.search_space` verbatim into `create_study.search_space` and cite the grounding fields in your chat reply."
  - The mutation set list (lines 28-31) **MUST NOT** include `propose_search_space`.
- Notes: The system prompt is consumed by both [`backend/app/llm/openai_client.py`](../../../../backend/app/llm/openai_client.py) for the OpenAI Chat Completions API and by the orchestrator's tool-result framing. The wording is normative — implementers must not rephrase it materially.

### FR-6: Adherence telemetry via conversation-scoped event correlation

- Requirement:
  - Add a `conversation_id: str` field to [`backend/app/agent/context.py:ToolContext`](../../../../backend/app/agent/context.py) (currently a 4-field frozen dataclass — `db`, `redis`, `arq_pool`, `settings`). Plumb the value from `orchestrator.run_turn`'s existing `conversation_id` parameter ([`backend/app/agent/orchestrator.py:162`](../../../../backend/app/agent/orchestrator.py#L162)) into the `ToolContext(...)` construction site (audit during Story 4 for the construction call site).
  - `propose_search_space_impl` **MUST** emit a structlog INFO event `"agent.search_space_proposed"` on every successful invocation with fields: `conversation_id`, `template_id`, `cluster_id`, `judgment_list_id` (nullable), `prior_study_id` (nullable), `param_names` (sorted), `cardinality`, `narrowed_param_names` (the FR-3 list).
  - `create_study_impl` **MUST** emit a structlog INFO event `"agent.create_study.invoked"` after step 1 (search_space validation, [`create_study.py:35-46`](../../../../backend/app/agent/tools/studies/create_study.py#L35-L46)) with fields: `conversation_id`, `study_id_pending` (the freshly-generated UUIDv7 before INSERT, for trace correlation), `template_id`, `cluster_id`, `search_space_param_names` (sorted), `search_space_cardinality` (the result of `estimate_cardinality`).
  - Neither event **MUST** block dispatch under any circumstance. Logging errors are swallowed.
- Notes: Adherence is computed offline by correlating the two events on `conversation_id`. A `create_study.invoked` with no preceding `search_space_proposed` in the same conversation = the LLM invented the space inline. A `create_study.invoked` with one or more preceding `search_space_proposed` = the chain was followed (the deep-equal check between the proposed JSON and the submitted JSON is left for an analytics step, not a per-call structlog field — keeps the hot path simple). Both event names are stable identifiers; renaming requires a spec patch.

### FR-7: TS↔Python heuristic parity test

- Requirement:
  - A new fixture file (e.g., `backend/tests/fixtures/search_space_defaults_parity.json`) **MUST** define an array of `{declared_params: dict[str, str], expected_search_space: dict}` rows covering: (a) every heuristic rule in `HEURISTIC_RULES`, (b) every `simple_form_spec` branch, (c) the cap-aware fallback (a declared_params with enough fall-through floats to bust 10⁶), (d) an empty `declared_params` edge case (which MUST raise — Pydantic rejects min_length=1).
  - A new test [`backend/tests/unit/domain/test_search_space_defaults_parity.py`](../../../../backend/tests/unit/domain/test_search_space_defaults_parity.py) **MUST** iterate the fixture, call `build_starter_search_space()` for each row, and assert the result matches `expected_search_space` (or `pytest.raises(InvalidSearchSpaceError)` for `expected_error` rows).
  - A new test `ui/src/__tests__/lib/search-space-defaults.parity.test.ts` **MUST** iterate the same fixture and assert `buildStarterSearchSpace()` produces the same shape (the TS side reads the JSON via `await fs.readFile` or static import).
- Notes: Either test failing flags drift between the two implementations. The fixture is the source of truth for what "byte-identical" means.

## 8) API and data contract baseline

### 7.1 Endpoint surface

**No REST endpoints.** The tool is dispatched in-process via the agent orchestrator.

For the agent-tool wire shape (OpenAI function-calling JSON):

| Tool name | Args (Pydantic model) | Returns | Errors |
|---|---|---|---|
| `propose_search_space` | `ProposeSearchSpaceArgs(template_id: UUID, cluster_id: UUID, judgment_list_id: UUID? , prior_study_id: UUID?)` | `{"search_space": {"params": {...}}, "grounding": {...}}` | `INVALID_SEARCH_SPACE` (400 — empty declared_params or cap-aware overflow), `TEMPLATE_NOT_FOUND` (404), `CLUSTER_NOT_FOUND` (404), `JUDGMENT_LIST_NOT_FOUND` (404), `STUDY_NOT_FOUND` (404) |

### 7.2 Contract rules

- Tool-result envelope is the orchestrator's standard `<tool_result>{json}</tool_result>` shape ([`backend/app/agent/orchestrator.py`](../../../../backend/app/agent/orchestrator.py)). The `HTTPException.detail` dict surfaces unchanged.
- Output `search_space` field **MUST** validate against `SearchSpace.model_validate` (i.e., is consumable verbatim by `create_study.search_space`).
- UUID arguments are accepted in any form Pydantic's `UUID` type supports (canonical hyphenated, hex-no-hyphen, URN, braces). Other tools return canonical hyphenated form, so the wire shape in practice is canonical. The tool's grounding object echoes IDs back in canonical hyphenated form via `str(UUID(...))`.

### 7.3 Response examples

**Success — heuristic-only (no prior study):**
```json
{
  "search_space": {
    "params": {
      "title_boost": {"type": "float", "low": 0.5, "high": 10.0, "log": true},
      "description_boost": {"type": "float", "low": 0.5, "high": 10.0, "log": true},
      "min_should_match": {"type": "int", "low": 0, "high": 5},
      "fuzziness": {"type": "categorical", "choices": ["AUTO", "0", "1", "2"]}
    }
  },
  "grounding": {
    "template_id": "0190fb40-...-7f01",
    "template_name": "product_search v1",
    "cluster_id": "0190fb3f-...-aa12",
    "used_prior_study_id": null,
    "narrowed_param_names": [],
    "cap_aware_fallback_param_names": [],
    "prior_study_template_mismatch": false
  }
}
```

**Success — with `prior_study_id` narrowing:**
```json
{
  "search_space": {
    "params": {
      "title_boost": {"type": "float", "low": 1.41, "high": 4.0, "log": true},
      "description_boost": {"type": "float", "low": 0.5, "high": 10.0, "log": true},
      "min_should_match": {"type": "int", "low": 1, "high": 4},
      "fuzziness": {"type": "categorical", "choices": ["AUTO", "0", "1", "2"]}
    }
  },
  "grounding": {
    "template_id": "0190fb40-...-7f01",
    "template_name": "product_search v1",
    "cluster_id": "0190fb3f-...-aa12",
    "used_prior_study_id": "0190fb42-...-cc34",
    "narrowed_param_names": ["title_boost", "min_should_match"],
    "cap_aware_fallback_param_names": [],
    "prior_study_template_mismatch": false
  }
}
```

**Failure — unknown cluster (envelope from [`backend/app/agent/tools/studies/create_study.py:50-58`](../../../../backend/app/agent/tools/studies/create_study.py#L50-L58)):**
```json
{
  "detail": {
    "error_code": "CLUSTER_NOT_FOUND",
    "message": "cluster 0190fb3f-...-aa12 not found",
    "retryable": false
  }
}
```

**Failure — unknown prior study:**
```json
{
  "detail": {
    "error_code": "STUDY_NOT_FOUND",
    "message": "study 0190fb42-...-cc34 not found",
    "retryable": false
  }
}
```

Auth failure example: **N/A — no auth surface in MVP1.**

### 7.4 Enumerated value contracts

The tool's args and return don't enumerate against a fixed allowlist beyond the existing `SearchSpace` discriminated union ([`backend/app/domain/study/search_space.py:83-89`](../../../../backend/app/domain/study/search_space.py#L83-L89)):

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `search_space.params[*].type` | `float`, `int`, `categorical` | `backend/app/domain/study/search_space.py` (`ParamSpec` discriminator on `type`) | N/A (tool result; not a UI dropdown) |
| Tool-error `error_code` | `INVALID_SEARCH_SPACE`, `TEMPLATE_NOT_FOUND`, `CLUSTER_NOT_FOUND`, `JUDGMENT_LIST_NOT_FOUND`, `STUDY_NOT_FOUND` | This spec §7.5 + per-tool `HTTPException` call sites in `propose_search_space.py` | N/A |
| `simple_form_spec` input `type_name` | `int`, `float`, `bool`, `string` | `backend/app/domain/study/search_space_defaults.py` (Python port) + `ui/src/lib/search-space-defaults.ts:73-86` (TS source) | Parity test fixture |

No new wire enums for the UI to consume. The TS↔Python parity test (FR-7) is the contract gate.

### 7.5 Error code catalog

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `TEMPLATE_NOT_FOUND` | 404 | The provided `template_id` does not resolve via `repo.get_query_template`. Surface unchanged from `create_study`'s identical code. |
| `CLUSTER_NOT_FOUND` | 404 | The provided `cluster_id` does not resolve via `repo.get_cluster`. Surface unchanged from `create_study`. |
| `JUDGMENT_LIST_NOT_FOUND` | 404 | Optional `judgment_list_id` argument resolved to no row. |
| `STUDY_NOT_FOUND` | 404 | Optional `prior_study_id` argument resolved to no row. (Re-uses `get_study`'s identical code.) |
| `INVALID_SEARCH_SPACE` | 400 | `build_starter_search_space` cannot produce a ≤10⁶ cardinality space even after the cap-aware fallback exhausts all float→int conversions (FR-1 overflow guard). Re-uses [`create_study.py`](../../../../backend/app/agent/tools/studies/create_study.py)'s identical code; the Pydantic validation error message is included in `detail.message`. |

No new error codes are introduced; all five are stable identifiers already in the codebase ([`create_study.py`](../../../../backend/app/agent/tools/studies/create_study.py) + [`get_study.py`](../../../../backend/app/agent/tools/studies/get_study.py)).

## 9) Data model and state transitions

### New/changed entities

**No DB schema changes.** No Alembic migration. The tool is purely computational + reads three existing tables (`query_templates`, `clusters`, optionally `studies` + `trials` + `judgment_lists`).

### Required invariants

- The returned `search_space` JSON **MUST** validate against [`SearchSpace.model_validate`](../../../../backend/app/domain/study/search_space.py#L92-L118) (min_length=1, ≤10⁶ cardinality).
- The returned `search_space.params` keys **MUST** be a subset of the template's `declared_params` keys (no unknown params will be proposed) and SHOULD cover every declared param. Coverage is enforced by `build_starter_search_space()` producing one entry per declared param. (Coverage is also tested in the parity fixture.)
- `narrow_bounds_around_winner` **MUST** produce a `SearchSpace` whose every numeric param's bounds are a subset of the input space's bounds for that param (monotonic narrowing).

### State transitions

N/A — read-only tool.

### Idempotency/replay behavior

Pure function. Same `(template_id, cluster_id, judgment_list_id, prior_study_id)` plus the same DB state → same output. Replays are trivially safe.

## 10) Security, privacy, and compliance

- **Threats:**
  1. **Cardinality bomb.** A pathological template with many fall-through-float `declared_params` could push the starter space past 10⁶ before the cap-aware fallback fires. Mitigation: the fallback IS the mitigation; it has parity tests on both sides. The 10⁶ ceiling is also enforced by `SearchSpace.model_validate`.
  2. **Leak of internal trial data.** The `grounding` field exposes `template_id`, `cluster_id`, and `used_prior_study_id` — all internal UUIDs. Mitigation: in single-tenant MVP1 these are not sensitive; revisit at MVP4 when tenant boundaries arrive (the audit-log event `agent.search_space_proposed` will need a tenant-scoping check).
  3. **Stale winner skews proposal.** A historical trial run with a much narrower search space narrows the new proposal so tightly that Optuna can't explore. Mitigation: FR-3's skip-on-out-of-bounds rule (winner outside original starter bounds → skip narrowing for that param), plus the `grounding.narrowed_param_names` list so the user sees what was touched.
- **Controls:** Read-only DB access; no writes; no `commit()`. Validation parity tests catch heuristic drift before it reaches production.
- **Secrets/key handling:** N/A — no LLM call, no engine call.
- **Auditability:** v1 — paired structlog INFO events `agent.search_space_proposed` (on the propose path) and `agent.create_study.invoked` (on the create path), correlated on `conversation_id` per FR-6. MVP2 — formal `audit_log` row.
- **Data retention/deletion/export impact:** None. No new data is persisted.

## 11) UX flows and edge cases

### Information architecture

The tool is consumed by the chat agent. The chat UI ([`/chat`](../../../../ui/src/app/chat/)) already renders tool calls as `<ToolCallBlock>` components per [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) — `propose_search_space` shows up automatically with no UI work. The tool's grounding object is rendered inside the JSON `<tool_result>` block, mirroring `get_study` and similar read-only tools.

- **Navigation placement:** N/A — agent surface only.
- **Labeling taxonomy:** N/A — the tool name and arg names ARE the user-visible labels; the LLM cites them in chat replies.
- **Content hierarchy:** N/A.
- **Progressive disclosure:** The grounding object is opt-in surface area for the LLM (it may or may not cite it in the chat reply); the search_space dict is the primary product.
- **Relationship to existing pages:** None directly. Coordinates loosely with `feat_study_clone_from_previous` (still idea-stage) which is the natural follow-on for "Use this proposal in a new study."

### Tooltips and contextual help

N/A — no new UI elements. The chat surface's existing `<ToolCallBlock>` styling is sufficient.

### Primary flows

1. **Greenfield study (no prior_study_id):**
   - User: "Tune the product_search template against our tutorial queries on local-es."
   - LLM: calls `list_templates` → `list_clusters` → `list_query_sets` (resolves IDs).
   - LLM: calls `propose_search_space(template_id, cluster_id, judgment_list_id?)`.
   - Tool: returns heuristic-only starter space with `grounding.used_prior_study_id = null`.
   - LLM: chat reply summarizes the proposal, citing template_name + cluster_id + param count + cardinality. Asks for confirmation to start the study.
   - User: "Yes, go."
   - LLM: calls `create_study(... , search_space=<the returned dict>)`. Both `agent.search_space_proposed` and `agent.create_study.invoked` events fire with the same `conversation_id`; offline correlation shows the chain was followed.

2. **Follow-on study from a prior winner:**
   - User: "Run another study like study_abc123 but tightened around its winner."
   - LLM: calls `get_study(study_abc123)` → notes `best_trial_id`.
   - LLM: calls `propose_search_space(template_id, cluster_id, prior_study_id=study_abc123)`.
   - Tool: narrows each numeric param by ±50% (or skips if winner is out of starter bounds); returns narrowed space + `grounding.narrowed_param_names` populated.
   - LLM: chat reply explains which params were narrowed and around what values; asks for confirmation.
   - Onward as flow #1.

### Edge/error flows

- **Unknown cluster.** LLM passed a stale ID. Tool returns 404 `CLUSTER_NOT_FOUND`. The orchestrator wraps in `<tool_result>` and shows the error to the LLM, which apologizes and re-resolves the cluster via `list_clusters`.
- **Unknown template.** Same shape as above with `TEMPLATE_NOT_FOUND`.
- **`prior_study_id` resolves but `study.best_trial_id is None`** (study is queued, running, or failed without a best trial). Tool returns the heuristic-only starter space with `grounding.used_prior_study_id = <id>` and `grounding.narrowed_param_names = []`. **No error** — degraded gracefully.
- **`prior_study_id` study has `best_trial_id` but the trial row is missing** (cascade-delete race). Tool logs a WARN and degrades to heuristic-only, same as the previous case.
- **Cap-aware fallback fires.** Logger emits WARN. The grounding object's `cap_aware_fallback_param_names` field (FR-2) lists the converted param names so tests and the LLM can both see the signal. If the cap-aware fallback exhausts every float without dropping cardinality ≤10⁶, the helper raises `InvalidSearchSpaceError` and the tool surfaces `HTTPException(400, INVALID_SEARCH_SPACE)`.

## 12) Given/When/Then acceptance criteria

### AC-1: Heuristic-only starter space, no grounding
- Given a template `T` with `declared_params = {"title_boost": "float", "min_should_match": "int", "fuzziness": "categorical"}`.
- And cluster `C` exists.
- When the agent calls `propose_search_space(template_id=T, cluster_id=C)`.
- Then the tool returns `result.search_space.params` with exactly three keys.
- And `params["title_boost"] == {"type": "float", "low": 0.5, "high": 10.0, "log": true}` (matches `HEURISTIC_RULES` `<x>_boost` suffix).
- And `params["min_should_match"] == {"type": "int", "low": 0, "high": 5}` (matches `min_should_match` rule).
- And `params["fuzziness"] == {"type": "categorical", "choices": ["AUTO", "0", "1", "2"]}` (matches `fuzziness` rule).
- And `result.grounding.used_prior_study_id is None`.
- And `result.grounding.narrowed_param_names == []`.

### AC-2: Prior-study narrowing — linear float
- Given a template `T` with `declared_params = {"title_boost": "float"}` (linear; `title_boost` matches `_boost` suffix and is *log-uniform* per the rule, but for this AC use the simpler linear `tie_breaker` to keep math obvious).
- And a prior study `S` with `best_trial_id = TR` and `TR.params = {"tie_breaker": 0.4}`.
- Given `declared_params = {"tie_breaker": "float"}` → starter `{"type": "float", "low": 0.0, "high": 1.0}`.
- When the agent calls `propose_search_space(template_id=T, cluster_id=C, prior_study_id=S)`.
- Then `result.search_space.params["tie_breaker"] == {"type": "float", "low": 0.2, "high": 0.6}` (0.4 × 0.5 and 0.4 × 1.5, clamped to original [0, 1]).
- And `result.grounding.narrowed_param_names == ["tie_breaker"]`.

### AC-3: Prior-study narrowing — log-uniform float
- Given a template with `declared_params = {"title_boost": "float"}` → starter `{type: "float", low: 0.5, high: 10.0, log: true}`.
- And prior study's winner had `title_boost = 2.0`.
- When the tool is called with `prior_study_id`.
- Then the returned bounds are `[max(0.5, 2.0/sqrt(2)), min(10.0, 2.0*sqrt(2))] ≈ [1.4142, 2.8284]`.
- And `result.grounding.narrowed_param_names` contains `"title_boost"`.

### AC-4: Prior-study narrowing — winner out of bounds → skip
- Given starter `min_should_match: {"type": "int", "low": 0, "high": 5}`.
- And prior winner had `min_should_match = 8`.
- When the tool runs.
- Then `result.search_space.params["min_should_match"]` is unchanged (`{"low": 0, "high": 5}`).
- And `"min_should_match"` is NOT in `result.grounding.narrowed_param_names`.

### AC-5: Prior-study has no best_trial yet
- Given `prior_study_id` resolves to a study `S` with `S.best_trial_id is None`.
- When the tool runs.
- Then the result is the heuristic-only starter space (no narrowing).
- And `result.grounding.used_prior_study_id == str(S.id)` (the ID is still echoed back).
- And `result.grounding.narrowed_param_names == []`.
- And no error is raised.

### AC-6: Unknown cluster
- Given `cluster_id = "00000000-0000-7000-0000-000000000000"` (no such cluster).
- When the tool is dispatched.
- Then it raises `HTTPException(404, detail={"error_code": "CLUSTER_NOT_FOUND", "message": "cluster 00000000-0000-7000-0000-000000000000 not found", "retryable": false})`.

### AC-7: Returned search_space is `create_study`-compatible
- Given any AC-1..AC-5 success path.
- When `result.search_space` is passed verbatim into `SearchSpace.model_validate`.
- Then it validates without error (i.e., `create_study` can accept it).

### AC-8: Telemetry — `propose_search_space` emits `agent.search_space_proposed`
- Given a successful `propose_search_space_impl` call with `conversation_id = "conv-abc"`, template + cluster resolved, no prior study.
- When the impl returns its dict result.
- Then a structlog INFO event `agent.search_space_proposed` is emitted with `conversation_id == "conv-abc"`, the sorted `param_names`, the `cardinality`, and `narrowed_param_names == []`.

### AC-9: Telemetry — `create_study` emits `agent.create_study.invoked`
- Given a `create_study_impl` call with `conversation_id = "conv-abc"`.
- When the impl passes search_space validation (step 1).
- Then a structlog INFO event `agent.create_study.invoked` is emitted with `conversation_id == "conv-abc"`, `study_id_pending` populated (UUIDv7 format), `search_space_param_names` sorted, and `search_space_cardinality` set to the `estimate_cardinality` return value.
- And the event fires even if a subsequent step (FK resolution, judgment-list consistency, DB INSERT) later raises.

### AC-10: TS↔Python parity
- Given the shared fixture `backend/tests/fixtures/search_space_defaults_parity.json` with `N` rows.
- When `pytest backend/tests/unit/domain/test_search_space_defaults_parity.py` runs.
- And `pnpm test ui/src/__tests__/lib/search-space-defaults.parity.test.ts` runs.
- Then both test suites pass with all `N` rows producing identical search_space dicts.

### AC-11: Tool registration sanity
- Given the post-feature codebase.
- When [`backend/tests/unit/agent/test_tool_registry.py`](../../../../backend/tests/unit/agent/test_tool_registry.py) runs.
- Then the expected tool count is `20` (was `19`).
- And `"propose_search_space"` is in the canonical tool name set.
- And the module-load assertion in [`backend/app/agent/tools/__init__.py:221-228`](../../../../backend/app/agent/tools/__init__.py#L221-L228) does not raise (drift-free).
- And `propose_search_space` is NOT in `MUTATING_TOOL_NAMES`.

### AC-12: Empty declared_params raises at heuristic boundary
- Given a template with `declared_params = {}` (zero params).
- When `build_starter_search_space({})` is called directly.
- Then it raises `InvalidSearchSpaceError` whose message names the empty input. (`SearchSpace.model_validate`'s `pydantic.ValidationError` is caught inside the helper and re-raised as `InvalidSearchSpaceError` so both empty-input and cap-aware-overflow paths surface the same exception type, simplifying the tool's error mapping.)
- And the tool surfaces this as `HTTPException(400, detail={"error_code": "INVALID_SEARCH_SPACE", "message": "<pydantic message>", "retryable": false})` (parity with [`create_study.py:39-46`](../../../../backend/app/agent/tools/studies/create_study.py#L39-L46)).
- And the TS parity test asserts `buildStarterSearchSpace({})` throws an `Error` whose message contains the substring `"empty declared_params"` (TS doesn't have a Pydantic-style validation error type; the message contract is the parity gate).

### AC-13: Cap-aware overflow guard
- Given a template with eight fall-through float `declared_params` (e.g., `{"a": "float", "b": "float", ..., "h": "float"}` — no name matches any `HEURISTIC_RULES` entry).
- When `build_starter_search_space(declared_params)` runs the cap-aware fallback.
- Then after every float is converted to `int[0, 5]`, `estimate_cardinality` is `6^8 = 1_679_616` (> 10⁶).
- And the function raises `InvalidSearchSpaceError` whose message contains the names and the post-fallback cardinality.
- And the tool surfaces this as `HTTPException(400, INVALID_SEARCH_SPACE)`.
- And the TS parity test asserts `buildStarterSearchSpace` `throw`s under the same input.

### AC-14: Prior-study template mismatch — graceful degrade
- Given a prior study `S` with `S.template_id != requested_template_id`.
- When the tool runs with `prior_study_id = S.id`.
- Then `result.search_space` is the heuristic-only starter space (no narrowing).
- And `result.grounding.prior_study_template_mismatch == True`.
- And `result.grounding.used_prior_study_id == str(S.id)`.
- And `result.grounding.narrowed_param_names == []`.
- And a structlog WARN event `agent.propose_search_space.prior_template_mismatch` is emitted.
- And no error is raised.

### AC-15: Prior-study `best_trial_id` set but trial row missing
- Given a prior study `S` with `S.template_id == requested_template_id` AND `S.best_trial_id = "trial-xyz"`.
- And `repo.get_trial(db, "trial-xyz")` returns `None` (cascade-delete race).
- When the tool runs with `prior_study_id = S.id`.
- Then `result.search_space` is the heuristic-only starter space.
- And `result.grounding.used_prior_study_id == str(S.id)`.
- And `result.grounding.narrowed_param_names == []`.
- And a structlog WARN event `agent.propose_search_space.missing_winner_trial` is emitted.
- And no error is raised.

### AC-16: System-prompt snapshot — tool inventory drift detection
- Given the final [`prompts/orchestrator.system.md`](../../../../prompts/orchestrator.system.md) after FR-5 updates.
- When [`backend/tests/unit/agent/test_orchestrator_system_prompt_inventory.py`](../../../../backend/tests/unit/agent/test_orchestrator_system_prompt_inventory.py) runs.
- Then the assertions hold: (a) the file contains the literal string `"You have 20 tools"`, (b) the studies inventory line names `propose_search_space` before `create_study`, (c) the mutation-set bullet (rule #2) does NOT contain `propose_search_space`, (d) the file contains a phrase matching the regex `before\s+calling\s+`create_study`` (or equivalent) directing the LLM to chain. Test fixture file paths are stable; the four assertions are explicit.

## 13) Non-functional requirements

- **Performance:** Tool latency p99 < 100 ms (no external I/O; one or two DB SELECTs by primary key). The whole loop including LLM round-trip is dominated by the OpenAI API call.
- **Reliability:** No retryable errors emitted; every error path is `retryable: false`. Tool is read-only and idempotent.
- **Operability:** paired structlog INFO events `agent.search_space_proposed` + `agent.create_study.invoked` are the primary telemetry seam. Adherence ratio = count of conversations containing both events ÷ count of conversations containing `agent.create_study.invoked`. Log scrubber list at MVP2 should explicitly allow the field names listed in FR-6.
- **Accessibility/usability:** N/A (no UI changes).

## 14) Test strategy requirements (spec-level)

- **Unit tests** (`backend/tests/unit/`):
  - `backend/tests/unit/domain/test_search_space_defaults.py` — covers `HEURISTIC_RULES` precedence, `simple_form_spec` branches, cap-aware fallback, `narrow_bounds_around_winner` math for each param type, skip-on-out-of-bounds, and categorical no-narrowing.
  - `backend/tests/unit/domain/test_search_space_defaults_parity.py` — fixture-driven parity assertion (FR-7).
  - `backend/tests/unit/agent/test_propose_search_space.py` — tool impl: arg validation (Pydantic), each error code (TEMPLATE_NOT_FOUND, CLUSTER_NOT_FOUND, JUDGMENT_LIST_NOT_FOUND, STUDY_NOT_FOUND, INVALID_SEARCH_SPACE), happy paths (heuristic-only, with-prior-study narrowing, prior-study-without-winner, returned-grounding shape, template-mismatch graceful degrade, missing-trial-row graceful degrade), `ctx.db.commit()` is never called.
  - `backend/tests/unit/agent/test_orchestrator_system_prompt_inventory.py` (new, satisfies AC-16) — reads `prompts/orchestrator.system.md` and asserts the four invariants above.
  - `backend/tests/unit/agent/test_tool_registry.py` — updated to expect 20 tools and contain the new canonical name.
  - `backend/tests/unit/agent/test_propose_search_space_telemetry.py` (new) — covers the FR-6 `agent.search_space_proposed` event via `backend/tests/_log_helpers.py` (factored by `infra_structlog_test_helpers` PR #114).
  - `backend/tests/unit/agent/test_create_study_telemetry.py` (new) — covers the FR-6 `agent.create_study.invoked` event using the same log helpers.
  - `backend/tests/unit/agent/test_tool_context_conversation_id.py` (new) — asserts `ToolContext` exposes `conversation_id: str` and the orchestrator's construction site populates it from `run_turn`'s parameter.
- **Integration tests** (`backend/tests/integration/`):
  - `backend/tests/integration/test_agent_propose_search_space_dispatch.py` — exercises the orchestrator's dispatch loop with a stubbed LLM, asserts the full propose → chat → create_study chain produces a study row with the proposed `search_space` JSON intact (round-trip through DB). Also asserts both telemetry events fire in order with the same `conversation_id`.
- **Contract tests** (`backend/tests/contract/`): **None** — the tool has no REST surface to contract-test. The Pydantic args model's JSON schema (from `model_json_schema()`) is its own contract; the registry sanity test enforces drift detection.
- **E2E tests** (`ui/tests/e2e/`): **None** — no UI changes. The existing chat E2E (lands with `feat_chat_agent` already) covers the agent surface; adding a propose-flow E2E is captured as a follow-up idea only if the chat UI gains a "Use proposal in study" affordance later.
- **Frontend parity test:** `ui/src/__tests__/lib/search-space-defaults.parity.test.ts` (new) — reads the shared fixture; asserts TS `buildStarterSearchSpace` matches.

## 15) Documentation update requirements

- `docs/01_architecture/agent-tools.md` — update the tool inventory section: count 19→20; add `propose_search_space` row with its purpose + read-only marker.
- `docs/01_architecture/llm-orchestration.md` — add a one-paragraph note under the "Function-calling pattern" section about the propose-then-create chain expectation.
- `docs/02_product/mvp1-user-stories.md` — add a new story (or extend the existing `feat_chat_agent` story group) covering the chain ("As a relevance engineer, when I ask the agent to start a study, it grounds the bounds via `propose_search_space` before calling `create_study`").
- `docs/03_runbooks/agent-debugging.md` — add a paragraph on how to grep both adherence events (`agent.search_space_proposed`, `agent.create_study.invoked`) and correlate them by `conversation_id` to compute adherence ratio.
- `docs/04_security/llm-data-flow.md` — **no changes**. The tool makes no LLM call.
- `docs/05_quality/testing.md` — **no changes** (existing test-layer convention covers this feature).
- `prompts/orchestrator.system.md` — see FR-5 (tool count + Studies (4) row + chain guidance).
- `state.md` — append to recent changes with the feature's PR + alembic-head-unchanged note.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. New read-only tool, additive registry entry, additive system-prompt update — no on/off switch needed. The paired INFO-event telemetry doesn't change user behavior.
- **Migration/backfill expectations:** None. No DB schema changes.
- **Operational readiness gates:**
  - Unit + integration tests green.
  - Parity test (FR-7) green on both TS and Python sides.
  - Manual smoke: in a local dev stack, open `/chat`, ask "tune product_search v1 against tutorial_queries", verify the LLM calls `propose_search_space` first and the chat reply cites grounding fields.
- **Release gate:** PR CI green; Gemini Code Assist adjudicated; GPT-5.5 final review clean.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (heuristic + overflow guard) | AC-1, AC-12, AC-13 | Stories 1 (defaults port), 2 (parity fixture) | `test_search_space_defaults.py`, `test_search_space_defaults_parity.py`, `search-space-defaults.parity.test.ts` | `agent-tools.md` |
| FR-2 (tool) | AC-1, AC-5, AC-6, AC-7, AC-11, AC-12 | Story 3 (tool impl), Story 5 (registry wiring) | `test_propose_search_space.py`, `test_tool_registry.py` | `agent-tools.md`, `llm-orchestration.md`, `mvp1-user-stories.md` |
| FR-3 (narrowing + degrade paths) | AC-2, AC-3, AC-4, AC-14, AC-15 | Story 1 (defaults port adds `narrow_bounds_around_winner`), Story 3 (tool impl wires graceful degrade) | `test_search_space_defaults.py`, `test_propose_search_space.py` | `agent-tools.md` |
| FR-4 (narrowing cardinality non-increasing) | (invariant — covered indirectly by AC-2/3/4 narrowing assertions) | Story 1 (helper docstring + invariant) | `test_search_space_defaults.py` | `agent-tools.md` |
| FR-5 (system prompt) | AC-16 | Story 6 (prompt update) + Story 6 (snapshot test) | `test_orchestrator_system_prompt_inventory.py` | `prompts/orchestrator.system.md`, `llm-orchestration.md` |
| FR-6 (telemetry) | AC-8, AC-9 | Story 4 (telemetry events + `ToolContext.conversation_id` plumb-through) | `test_propose_search_space_telemetry.py`, `test_create_study_telemetry.py`, `test_tool_context_conversation_id.py` | `agent-debugging.md` |
| FR-7 (parity) | AC-10, AC-13 | Story 2 (parity fixture + tests) | `test_search_space_defaults_parity.py`, `search-space-defaults.parity.test.ts` | `agent-tools.md` |

## 18) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-1 .. AC-16) pass in CI.
- [ ] Unit, integration, and parity tests are green on both TS and Python sides.
- [ ] Tool count constant in `test_tool_registry.py` is `20`; module-load assertion in `backend/app/agent/tools/__init__.py` does not raise.
- [ ] `propose_search_space` is NOT in `MUTATING_TOOL_NAMES`.
- [ ] `prompts/orchestrator.system.md` is updated per FR-5.
- [ ] Both telemetry events (`agent.search_space_proposed`, `agent.create_study.invoked`) are verified live in a smoke-test container (grep both with the same `conversation_id`).
- [ ] Docs deltas in §15 are merged.
- [ ] No open questions in §19 remain.
- [ ] PR CI is green; Gemini Code Assist + GPT-5.5 final review adjudicated.

## 19) Open questions and decision log

### Open questions

(All preflight open questions resolved during spec generation; see Decision log below.)

- *None at spec time.* `conversation_id` plumbing into `ToolContext` is required for this feature to merge — it is a blocking part of FR-6 and AC-8/AC-9. If plumbing turns out to be unexpectedly invasive during Story 4 (auditing the actual construction call sites is part of that story's preflight), the spec must be patched to either resolve the issue or formally split telemetry into a follow-up; an `"unknown"` fallback is NOT permitted because it would silently break the adherence metric the spec is built around.

### Decision log

- **2026-05-21** — `propose_search_space` is read-only and not in `MUTATING_TOOL_NAMES`. Rationale: confirmation-on-every-chain adds friction without value; the tool only reads existing rows.
- **2026-05-21** — Encourage chaining via system prompt + paired-INFO-event telemetry; do NOT enforce server-side. Rationale (idea Open Question #1): per-turn state tracking is fragile, the LLM is reliably steerable via system prompt, and adherence ratio is observable offline by correlating the two events on `conversation_id`. Re-evaluate at MVP2.
- **2026-05-21** — ±50% bracket for prior-study narrowing (linear); √2 geometric bracket for log-uniform floats. Rationale (idea Open Question #3): defensible starting point; symmetric in log-space for log-uniform; locks in shared math for `feat_study_clone_from_previous`. Re-evaluate at v2 if Optuna convergence data argues for ±1σ.
- **2026-05-21** — Categoricals are not narrowed. Rationale: removing options can hide useful signal; the math is not symmetric with the numeric path; if needed later, surface as a separate tool arg (`narrow_categoricals: bool`).
- **2026-05-21** — Frontend "Use proposal in new study" affordance deferred to follow up with `feat_study_clone_from_previous`. Rationale: backend-only PR keeps the diff reviewable; the frontend pre-fill helper is the natural place for that UX.
- **2026-05-21** — `cluster_id` is a required argument but currently only used to validate the cluster exists. Rationale: forward-compatible signature for phase-2 cluster-stats grounding without a tool rename.
- **2026-05-21** — Tool name kept as `propose_search_space`. Rationale (idea Open Question #4): clearest intent; matches the existing verb-noun convention.
- **2026-05-21** — `compute_default_params` is NOT dead code (preflight claim was wrong; confirmed by `grep` — used in `backend/workers/digest.py:774` and `backend/workers/judgments.py:189`). No cleanup chore.
- **2026-05-21** — Heuristic source-of-truth direction is TS→Python (TS shipped first in PR #157). Rationale: the wizard's Step-4 auto-fill is the user-visible surface; the backend tool is the consumer that mirrors. Parity test goes both ways.
