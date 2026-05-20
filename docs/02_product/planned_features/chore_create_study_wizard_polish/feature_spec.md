# Feature Specification — Create-Study Wizard Polish

**Date:** 2026-05-19
**Status:** Draft
**Owners:** Eric Starr (product + engineering)
**Related docs:**
- [`idea.md`](idea.md) — the source brief (created 2026-05-19, audited & patched via `/idea-preflight`)
- [`implementation_plan.md`](implementation_plan.md) — TBD (next stage)
- [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) — wizard + glossary patterns
- [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) — error envelope contract

---

## 1) Purpose

A relevance engineer creating a study via the 5-step wizard at [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) lands on Step 4 (search space) facing a blank JSON textarea. Steps 1–3 are dropdowns with `<InfoTooltip>` contextual help (added by `feat_contextual_help`, PR #122). Step 5 (objective) has full glossary coverage except for a silent metric+k coupling. This polish chore closes those gaps in one PR.

- **Problem:** Step 4 has no contextual help, no starter content, no validation against the selected template — typo'd param names fail on trial 1 instead of at create time. Step 5 silently ignores `k` for `map`/`mrr`/`err`.
- **Outcome:** Step 4 auto-fills from the template's `declared_params` with conservative ranges, rejects unknown/missing params at create time with new machine-readable error codes, and surfaces four new glossary entries. Step 5 renders `k` as required-with-description for ranked metrics and hides it (with explanation) for non-ranked metrics.
- **Non-goal:** Visual builder UI for per-param row editing (deferred to `feat_create_study_search_space_builder`); template library expansion (deferred to `chore_template_library_expansion`); engine-aware parameter awareness in Step 4 (out of scope until library expansion lands).

## 2) Current state audit

### Existing implementations

- **[`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx)** — the 5-step `react-hook-form`-backed modal. Internal `step` counter is 0-indexed (`step === 3` shows the user-facing "Step 4"). Step 4 (line 322-339) is a single `<Textarea>` with `form.register('search_space_text')`; client-side validation at lines 141-145 only verifies JSON parses. Step 5 (lines 340-468) has 9 form fields each with an `<InfoTooltip>` except where the k field lives — k uses placeholder-only "required"/"optional" copy at line 377, computed via `K_REQUIRED.has(metric)` (constant at line 46: `new Set(['ndcg', 'precision', 'recall'])`).
- **[`backend/app/domain/study/search_space.py`](../../../../backend/app/domain/study/search_space.py)** — `SearchSpace` Pydantic model with `params: dict[str, ParamSpec]`. `model_validate` checks: ParamSpec discriminated-union type, low<high (float) / low<=high (int) bounds, log requires low>0 (float), choices non-empty (categorical), total cardinality ≤ 10⁶. Failure → `pydantic.ValidationError`. **Does not** validate against any template — that's the gap this spec closes. Also exports `estimate_cardinality(space)` (line 132-151) — floats counted as 100, ints as `high-low+1`, categoricals as `len(choices)`, product.
- **[`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py)** — POST handler at line 185-250. Order: (1) `SearchSpace.model_validate` → 400 `INVALID_SEARCH_SPACE` (line 191-195); (2) FK lookups: `CLUSTER_NOT_FOUND` / `TEMPLATE_NOT_FOUND` / `QUERY_SET_NOT_FOUND` / `JUDGMENT_LIST_NOT_FOUND` (lines 198-214); (3) judgment_list↔query_set consistency check → 422 `VALIDATION_ERROR` (lines 217-223); (4-6) serialize, insert, enqueue. Helper `_err(status_code, code, message, retryable)` at line 68-72 produces the standard envelope.
- **[`backend/app/adapters/elastic.py:493-495`](../../../../backend/app/adapters/elastic.py#L493-L495)** — the runtime gate that hard-fails on missing declared params during trial render: `missing = set(template.declared_params) - set(params.keys()); if missing: raise ValueError(...)`. Today's behavior: a study with an incomplete or typo'd search space fails on trial 1 with this `ValueError`. The new create-time validation makes this gate unreachable for valid inputs.
- **[`backend/app/domain/study/template_defaults.py`](../../../../backend/app/domain/study/template_defaults.py)** — exports `compute_default_params(template_row)` which picks per-param midpoint / first-categorical / `False` / `""` *concrete values* for a template's declared params. **Currently unused in app code** (grep across `backend/app/workers/`, `backend/app/services/`, `backend/app/agent/`, `backend/app/api/` returns zero call sites; only its own unit tests reference it). The spec does NOT wire this in; the dead-code observation is captured separately (see §19 Open Questions).
- **[`ui/src/components/common/info-tooltip.tsx`](../../../../ui/src/components/common/info-tooltip.tsx)** — the standalone `<InfoTooltip glossaryKey="..." />` component (PR #122, `feat_contextual_help` Phase 1). Renders a 24×24 button with a `lucide-react` `<Info>` icon; tooltip body opens on hover/focus. `glossaryKey` is typed as `ShortGlossaryKey` (compile-time narrowed to entries with a `short` field). Test ids: `tooltip-trigger-${key}` + `tooltip-body-${key}`. **Consequence for this spec:** any glossary entry surfaced via `<InfoTooltip>` MUST include a `short` field (`GlossaryEntryShort` or `GlossaryEntryDual`); `GlossaryEntryLong`-only entries are not surfaceable as tooltips.
- **[`ui/src/components/common/help-popover.tsx`](../../../../ui/src/components/common/help-popover.tsx)** — the click-to-open `<HelpPopover glossaryKey="..." />` component (PR #122, same phase). Renders a button trigger; popover body uses `react-markdown` with a safety filter to render `long`-form content. Signature: `function HelpPopover({ glossaryKey }: HelpPopoverProps): React.ReactElement | null` at line 29; the `glossaryKey` prop is typed to entries that include a `long` field.
- **[`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts)** — 49-key glossary source-of-truth (per `feat_contextual_help` FR-5). Entry shapes: `GlossaryEntryShort` (`short ≤ 140 chars`), `GlossaryEntryLong` (`long ≤ 800 chars` with Markdown subset), `GlossaryEntryDual` (both). Existing test at [`ui/src/__tests__/lib/glossary.test.ts`](../../../../ui/src/__tests__/lib/glossary.test.ts) enforces: no backend-jargon in user copy, length bounds, parity with `OBJECTIVE_METRIC_VALUES` for `study.metric.*` keys.
- **[`backend/app/api/v1/query_templates.py`](../../../../backend/app/api/v1/query_templates.py)** — exposes `GET /api/v1/query-templates/{id}` returning the template row including `declared_params: dict[str, str]` (simple-form: `{"param_name": "type-name"}` where type-name is `"int"`, `"float"`, `"bool"`, or `"string"`). The wizard already fetches templates list (Step 3); it does not currently re-fetch the single selected template's full body. This spec adds that fetch.

### Navigation and link impact

None. The chore extends one modal; no routes change, no URLs renamed.

| Source file | Current link target | New link target |
|---|---|---|
| (none) | — | — |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| [`ui/tests/e2e/studies.spec.ts`](../../../../ui/tests/e2e/studies.spec.ts) | `cs-search-space` Textarea fill | 1 | Update to assert auto-fill behavior + new validation flow |
| [`ui/src/__tests__/components/studies/create-study-modal.test.tsx`](../../../../ui/src/__tests__/components/studies/create-study-modal.test.tsx) | Step-4 / Step-5 rendering | varies | Add cases for auto-fill, metric+k conditional render, client-side validator |
| [`backend/tests/contract/test_studies_create.py`](../../../../backend/tests/contract/test_studies_create.py) | `INVALID_SEARCH_SPACE` envelope | 1+ | Add cases for `SEARCH_SPACE_UNKNOWN_PARAM` + `SEARCH_SPACE_MISSING_DECLARED_PARAM` |
| [`backend/tests/integration/test_studies_create.py`](../../../../backend/tests/integration/test_studies_create.py) | round-trip POST | varies | Add cases for unknown-param 400 + missing-param 400 |
| [`ui/src/__tests__/lib/glossary.test.ts`](../../../../ui/src/__tests__/lib/glossary.test.ts) | parity + length tests | 1 | Auto-covers new keys via existing length test; no test changes needed beyond key additions |

### Existing behaviors affected by scope change

- **Step 4 textarea is empty on first render.** Current: empty string `''`. New: pre-filled JSON derived from selected template's `declared_params`. **Decision needed:** no (resolved — see §19 Decision Log).
- **Step 3 (template selection) does not trigger a fetch of the full template body.** Current: the list endpoint payload is sufficient (id + name + version are all the picker needs). New: when a template is picked, fetch `GET /api/v1/query-templates/{id}` to obtain `declared_params` for the auto-fill. Cached for the remainder of the modal session.
- **Step 4 → Step 5 transition allows typo'd search-space param names through.** Current: only JSON-parse + client-side `SearchSpace.model_validate`-equivalent checks run. New: client-side validator additionally checks every param key against the selected template's `declared_params`; server-side `POST /api/v1/studies` adds the same check.
- **`?: 'required' | 'optional'` placeholder on k field collapses three tiers into two.** Current: placeholder says `required` for `ndcg`/`precision`/`recall` and `optional` for everything else. But the backend treats `map` as truly optional (map@k vs full-recall MAP) and `mrr`/`err` as ignored. New: tri-state rendering — required-with-description for `K_REQUIRED`, optional-with-clearable for `map`, hidden-with-explanation for `K_IGNORED = {mrr, err}`.

---

## 3) Scope

### In scope

- Auto-fill Step 4 textarea from the selected template's `declared_params` using a deterministic naming-convention heuristic.
- Add two new error codes (`SEARCH_SPACE_UNKNOWN_PARAM`, `SEARCH_SPACE_MISSING_DECLARED_PARAM`) and a `validate_against_template(search_space, template)` function used by both the backend `POST /api/v1/studies` handler and a mirrored client-side validator in the modal.
- Step 5 metric+k conditional rendering: required-with-description for ranked metrics; hidden with explanatory caption for non-ranked.
- Four new glossary entries: `study.search_space`, `study.search_space.param_spec`, `study.search_space.log`, `study.search_space.cardinality`.
- Extend each existing per-metric glossary entry (`study.metric.{ndcg,map,precision,recall,mrr,err}`) with one clause stating whether k applies.
- Surface all new glossary entries via `<InfoTooltip>` adjacent to the relevant Step-4 / Step-5 labels.
- Unit + contract + integration + component test coverage.

### Out of scope

- Visual builder UI for per-param row editing → `feat_create_study_search_space_builder`.
- Curated template library expansion → `chore_template_library_expansion`.
- Wiring `compute_default_params` into the trial run path → captured as `chore_template_defaults_dead_code` (separate idea).
- Engine-specific parameter awareness (different defaults for ES vs OpenSearch vs Fusion) → emerges naturally when template library expansion lands.
- `parent_study_id` clone lineage → `feat_study_clone_from_previous`.
- LLM-proposed search spaces → `feat_agent_propose_search_space`.

### API convention check

Per [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md):

- **Endpoint prefix:** `/api/v1/<resource>` — confirmed in `backend/app/api/v1/studies.py:179` (`@router.post("/studies")`).
- **Router namespace for this feature's endpoints:** the existing `backend/app/api/v1/studies.py` only — no new endpoints.
- **HTTP methods for CRUD:** standard set; this spec only modifies the existing `POST /api/v1/studies` handler. No new method/path combinations.
- **Non-auth error envelope:** `{"detail": {"error_code": "<CODE>", "message": "<human>", "retryable": <bool>}}` — confirmed at `studies.py:68-72` (`_err()` helper). The two new error codes follow this exact shape with `retryable: false`.
- **Auth error shape:** N/A — RelyLoop is single-tenant with no auth surface in MVP1–MVP3.

### Phase boundaries

Single phase — this chore ships in one PR. No deferred phases; no `phase*_idea.md` artifacts required.

## 4) Product principles and constraints

- **Make the canonical JSON the source of truth.** No alternate representation should drift from the textarea content; auto-fill and client-side validation both read/write the same `search_space_text` form field.
- **Match the trial worker's behavior.** Create-time validation must reject any input that would fail at trial render time. A study that POSTs successfully must run.
- **No silent ignores.** When a user supplies a value the backend will discard (a `k` value for `mrr` or `err`), the UI must not accept it. Hide the field or block submission. Note: `k` for `map` is **not** discarded — it switches the metric to `map@k`, so `map` is correctly rendered with an optional-k surface (FR-4).
- **Single naming convention for defaults heuristic.** Frontend `search-space-defaults.ts` is the canonical source; if `feat_agent_propose_search_space` later needs the same heuristic on the backend, it mirrors this module rather than reinventing.
- **Glossary entries follow the established length, jargon, and source-of-truth conventions.** No backend file paths in user-visible copy; max 140 chars for `short`, 800 for `long`.

### Anti-patterns

- **Do not** wire `backend/app/domain/study/template_defaults.compute_default_params` into the trial run path as part of this chore — that's a separate, larger design decision (warn-instead-of-fail) that should be made with full understanding of the dead-code state and any orchestrator-side implications. Hard-fail at create-time is the present-behavior-preserving choice.
- **Do not** introduce a per-engine defaults heuristic in this chore. The heuristic is naming-convention-based across all engines; engine-aware defaults emerge from the curated template library.
- **Do not** create a centralized backend error-code constants module. RelyLoop's current convention is inline string literals at `_err()` call sites (see `backend/app/api/v1/clusters.py:94`, `judgments.py:89`, `proposals.py:84`, etc.). Introducing a constants module to add two codes would be a cross-cutting refactor that doesn't belong in a chore.
- **Do not** add the auto-fill as a "fill on click" button. It must trigger automatically when the template selection finalizes — buttons that "do the obvious thing" add a confirmation step nobody wants.
- **Do not** silently overwrite user-edited Step-4 content when the template changes. Replace the content immediately AND show a toast with an Undo action that restores the prior content if clicked within 10 seconds.

## 5) Assumptions and dependencies

| Dependency | Why required | Status | Risk if missing |
|---|---|---|---|
| `<InfoTooltip>` component at [`ui/src/components/common/info-tooltip.tsx`](../../../../ui/src/components/common/info-tooltip.tsx) | Glossary entry rendering follows the established pattern | **Shipped** in PR #122 (`feat_contextual_help` Phase 1, 2026-05-15) | None — fully landed |
| `INVALID_SEARCH_SPACE` error code precedent | Two new error codes follow this established shape | **Shipped** — `backend/app/domain/study/search_space.py:9,125`, used at `backend/app/api/v1/studies.py:195` | None |
| `K_REQUIRED` predicate in `create-study-modal.tsx:46` | Step 5 metric+k rendering reuses this | **Shipped** — current code | None |
| `template.declared_params` populated on every template | Auto-fill source | **Shipped** — required by `template_validator.py` (declared_params ↔ body referential integrity) | None — protected by existing template-create validation |
| `<EntitySelect>` for template selection | Step 3 picker (existing) | **Shipped** — used at `create-study-modal.tsx:300` | None |
| TanStack Query cache for the selected template body | Auto-fill needs single-template fetch | **Existing infra** — `feat_studies_ui` ships `useQueryTemplate(id)` hook pattern; reuse | Low — if not present, drop in a new hook |

## 6) Actors and roles

- **Primary actor:** Relevance engineer creating a study via the wizard.
- **Role model:** N/A — single-tenant install, no auth surface (MVP1).
- **Permission boundaries:** N/A.

### Authorization

N/A — single-tenant install, no auth surface (MVP1 per [`docs/01_architecture/tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md)).

### Audit events

N/A — `audit_log` table activates at MVP2 per [`docs/01_architecture/data-model.md` §"Forthcoming: audit_log"](../../../01_architecture/data-model.md). No new state-mutating endpoints; existing `POST /api/v1/studies` gains two new validation paths only.

## 7) Functional requirements

### FR-1: Auto-fill Step 4 from `declared_params`

- Requirement:
  - The system **MUST** populate the Step 4 `search_space_text` textarea with a generated JSON object derived from the selected template's `declared_params` when the user enters Step 4 with an empty textarea OR with a textarea that exactly matches a previously-generated auto-fill for a different template.
  - When the user has edited Step 4 content AND the selected template changes (Step-3 revisit) OR the template-body fetch resolves with the user mid-edit, the system **MUST** immediately replace the textarea content with the new auto-fill, AND **MUST** show a toast offering Undo for 10 seconds. Clicking Undo within the 10-second window restores the pre-replacement content. The toast auto-dismisses at 10s. (This is the standard shadcn/sonner toast-with-action pattern — replacement is immediate, not delayed.)
  - The generated JSON **MUST** be valid against `backend.app.domain.study.search_space.SearchSpace.model_validate` (i.e., it parses and meets all bound/cardinality checks).
  - The heuristic mapping **MUST** live in a single TypeScript module at `ui/src/lib/search-space-defaults.ts` (no inline mapping in the modal).
- Notes:
  - Heuristic (locked, see §19 Decision Log): names matching `^(field_boost|boost_)` → `{type: 'float', low: 0.5, high: 10.0, log: true}`; names matching `^(tie_breaker|.*_weight)$` → `{type: 'float', low: 0.0, high: 1.0}`; names matching `^(slop|min_should_match|.*_size)$` → `{type: 'int', low: 0, high: 5}`; name `fuzziness` → `{type: 'categorical', choices: ['AUTO', '0', '1', '2']}`; everything else → `{type: 'float', low: 0.0, high: 1.0}`.
  - `declared_params` simple-form values (`'int'`/`'float'`/`'bool'`/`'string'`) inform a fallback when the regex misses: `'int'` → `{type: 'int', low: 0, high: 5}`; `'float'` → `{type: 'float', low: 0.0, high: 1.0}`; `'bool'` → `{type: 'categorical', choices: [true, false]}`; `'string'` → `{type: 'categorical', choices: ['__placeholder__']}` (degenerate single-choice; the client-side validator (FR-2) emits a non-blocking warning "Replace `__placeholder__` before submitting" for any ParamSpec containing this sentinel — but `SearchSpace.model_validate` accepts it, so the user can still iterate Step-4 → Step-5 → back-to-4 without being blocked).
  - **Why not omit `'string'`-typed declared params:** FR-3 rejects any submission where a declared param is missing from the search space. Auto-fill producing a `__placeholder__` is preferable to silently emitting an invalid-by-its-own-rules output that fails Next-click.
  - **Cap-aware fallback (deviation from locked heuristic):** the per-param heuristic can produce search spaces whose cardinality exceeds 10⁶ for templates with ≥4 float declared params (each float contributes 100 to the product per `estimate_cardinality()`). When the heuristic output's cardinality exceeds 10⁶, `buildStarterSearchSpace` MUST narrow the result by converting float params to `{type: 'int', low: 0, high: 5}` (contribution 6 each) — preserving the regex-matched assignments first (boost-like, tie_breaker-like, fuzziness) and converting the unmatched fall-through float params first. The function also emits a `console.warn` indicating the cap-aware fallback fired. This is an explicit deviation from FR-1's locked-heuristic rule, accepted because the alternative (invalid auto-fill rejected by server) violates the "MUST be valid" constraint.

### FR-1 invariant
- The result of `buildStarterSearchSpace(declared_params)` for any non-empty `declared_params` MUST validate against `SearchSpace.model_validate` (cardinality ≤ 10⁶ guaranteed). The cap-aware fallback above is the mechanism that holds this invariant.

### FR-2: Reject unknown search-space params at create time

- Requirement:
  - The system **MUST** add a domain function `validate_against_template(search_space: SearchSpace, declared_params: dict[str, str], template_name: str) -> None` in [`backend/app/domain/study/search_space.py`](../../../../backend/app/domain/study/search_space.py) that raises a new exception class `UnknownSearchSpaceParamError(ValueError)` when `search_space.params` contains a key not in `declared_params`. The `template_name` argument is required for the exception's message format to match the exact text below (without it, the router would have to re-compose the message and the spec contract would drift).
  - `POST /api/v1/studies` **MUST** invoke `validate_against_template` after the template FK lookup succeeds (between current lines 203 and 204) and before any subsequent FK lookups.
  - The handler **MUST** translate `UnknownSearchSpaceParamError` to HTTP 400 with `error_code: "SEARCH_SPACE_UNKNOWN_PARAM"`, `retryable: false`, and a `message` of the exact form `"Param '{name}' is not declared by template '{template_name}'. Declared params: {sorted_declared_names}."`.
  - The frontend **MUST** mirror this validation client-side in `create-study-modal.tsx` using the cached `declared_params` from the Step-3 template fetch; the inline error label appears under the Step-4 textarea on blur or on Next-click.

### FR-3: Reject missing declared params at create time

- Requirement:
  - The same `validate_against_template` function **MUST** raise a new exception class `MissingDeclaredParamError(ValueError)` when `declared_params` contains a key not in `search_space.params`.
  - `POST /api/v1/studies` **MUST** translate to HTTP 400 with `error_code: "SEARCH_SPACE_MISSING_DECLARED_PARAM"`, `retryable: false`, and a `message` of the exact form `"Template '{template_name}' declares param '{name}' but it is missing from the search space. Add it or remove from the template."`.
  - Both unknown-param and missing-declared-param errors **MUST** fire deterministically: if both conditions apply, the unknown-param error fires first (lexicographic order on the offending param name within each class).
  - Client-side mirroring is identical to FR-2's client-side behavior.

### FR-4: Step 5 metric+k tri-state conditional rendering

The metric+k coupling is **tri-state** on the backend (verified at [`backend/app/eval/scoring.py:32`](../../../../backend/app/eval/scoring.py#L32)): k is **required** for `ndcg`/`precision`/`recall`, **optional** for `map` (controlling `map@k` vs full-recall MAP), and **ignored** for `mrr`/`err`. Today's `K_REQUIRED.has(metric) ? 'required' : 'optional'` placeholder hides this distinction. FR-4 surfaces the three tiers correctly.

- Requirement:
  - The system **MUST** introduce a second frontend predicate `K_IGNORED: ReadonlySet<ObjectiveMetric> = new Set(['mrr', 'err'])` in `create-study-modal.tsx`. Together with the existing `K_REQUIRED = new Set(['ndcg', 'precision', 'recall'])`, the three tiers are:
    - **Required:** `K_REQUIRED.has(metric)` — `ndcg`, `precision`, `recall`.
    - **Optional:** `!K_REQUIRED.has(metric) && !K_IGNORED.has(metric)` — `map` (the only metric in this tier today).
    - **Ignored:** `K_IGNORED.has(metric)` — `mrr`, `err`.
  - When the metric is **required-k**, the k `<Select>` **MUST** render with:
    1. A sub-label below the field reading `"Top-k cutoff (required for {metric.toUpperCase()})"`.
    2. The existing `<InfoTooltip glossaryKey="study.k" />`.
    3. The existing `OBJECTIVE_K_VALUES`-derived option list.
  - When the metric is **optional-k**, the k `<Select>` **MUST** render with:
    1. A sub-label below the field reading `"Top-k cutoff (optional — leave empty for full-recall {metric.toUpperCase()})"`.
    2. The existing `<InfoTooltip glossaryKey="study.k" />`.
    3. The existing `OBJECTIVE_K_VALUES`-derived option list (with an explicit clearable "—" entry so the user can remove a previously-set k).
  - When the metric is **ignored-k**, the k `<Select>` **MUST** be hidden from the DOM, and a single-line caption **MUST** appear in its place reading `"{metric.toUpperCase()} evaluates the full ranked list — no cutoff used."` (verb is "used," not "needed" — matches the backend's "k is ignored" semantics).
  - Switching metric **MUST** clear any previously-set k value from the form state when the new metric is in `K_IGNORED`. When switching between `K_REQUIRED` and the optional tier, k is preserved (it's still a meaningful value).
  - Both `K_REQUIRED` and `K_IGNORED` are frontend-only predicates; the backend's `ObjectiveSpec` validator (at [`backend/app/api/v1/schemas.py:494-500`](../../../../backend/app/api/v1/schemas.py#L494-L500)) is the source of truth and remains unchanged. Drift between frontend predicates and backend reality is detected by AC-13's contract test.

### FR-5: Glossary entries for Step-4 concepts

- Requirement:
  - The system **MUST** add four new entries to [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts):
    - `study.search_space` — `GlossaryEntryDual` (both `short` and `long`). `short` (≤ 140 chars) surfaces via `<InfoTooltip>` adjacent to the Step-4 label; `long` (≤ 800 chars, Markdown allowed) surfaces via `<HelpPopover>` below the textarea. Same key, both shapes — the existing `study.metric` entry already uses this pattern.
    - `study.search_space.param_spec` — `short` form (≤ 140 chars). Distinguishes `float` / `int` / `categorical`.
    - `study.search_space.log` — `short` form. Explains log scale and the "use when high/low > 10" rule of thumb.
    - `study.search_space.cardinality` — `short` form. States the 10⁶ cap and a one-line "how it's estimated" hint.
  - Each entry **MUST** include an `ariaLabel`.
  - Each entry **MUST** comply with [`ui/src/__tests__/lib/glossary.test.ts`](../../../../ui/src/__tests__/lib/glossary.test.ts) constraints (length, no backend jargon, Markdown subset).

### FR-6: Extend existing per-metric glossary entries with k-tier copy

- Requirement:
  - The system **MUST** extend each of `study.metric.ndcg`, `study.metric.map`, `study.metric.precision`, `study.metric.recall`, `study.metric.mrr`, `study.metric.err` (currently `short`-only, lines 70-92 of `glossary.ts`) with a tier-specific clause appended to the existing `short` text:
    - **`ndcg`, `precision`, `recall`:** append `" Requires a top-k cutoff."`
    - **`map`:** append `" Top-k cutoff optional — set it for map@k, leave blank for full-recall MAP."`
    - **`mrr`, `err`:** append `" Top-k cutoff is not used."`
  - Length budget: stay within 140 chars per `short`. The current entries are 76–127 chars; the longest extension adds ~70 chars, putting `study.metric.map` over budget — that entry MUST be tightened.
  - The parity check at `ui/src/__tests__/lib/glossary.test.ts` (key-set parity with `OBJECTIVE_METRIC_VALUES`) MUST continue to pass.

### FR-7: Surface new glossary entries in the wizard

- Requirement:
  - The system **MUST** add `<InfoTooltip glossaryKey="study.search_space" />` adjacent to the Step-4 "Search space (JSON)" label (currently a plain `<Label>` at `create-study-modal.tsx:331`). InfoTooltip reads the `short` field of the dual entry.
  - The system **MUST** add `<HelpPopover glossaryKey="study.search_space" />` below the textarea. HelpPopover reads the `long` field of the same dual entry — the `long` content contains the combined "what it is + ParamSpec types + log scale + cardinality cap" narrative as one Markdown body.
  - The three subkey entries (`study.search_space.param_spec`, `.log`, `.cardinality`) **MUST** still be added to glossary.ts as short-only entries, but are **NOT** wired into the Step-4 surface by this chore. They are forward-compatibility hooks for the per-param row tooltips that `feat_create_study_search_space_builder` will surface. This avoids needing to extend `<HelpPopover>` to render multiple keys (which would be an out-of-scope component change).
  - Step-5 sub-label additions from FR-4 reuse the existing `<InfoTooltip glossaryKey="study.k" />` (no relocation needed).

## 8) API and data contract baseline

### 8.1 Endpoint surface

No new endpoints. Modifies the existing `POST /api/v1/studies`.

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/studies` | Create + enqueue a study | Existing: `INVALID_SEARCH_SPACE` (400), `CLUSTER_NOT_FOUND` (404), `TEMPLATE_NOT_FOUND` (404), `QUERY_SET_NOT_FOUND` (404), `JUDGMENT_LIST_NOT_FOUND` (404), `VALIDATION_ERROR` (422). **New:** `SEARCH_SPACE_UNKNOWN_PARAM` (400), `SEARCH_SPACE_MISSING_DECLARED_PARAM` (400) |

### 8.2 Contract rules

- The error envelope shape is **unchanged**: `{"detail": {"error_code": "<CODE>", "message": "<human>", "retryable": <bool>}}` per `studies.py:68-72`. Both new codes use `retryable: false`.
- HTTP status for both new codes is 400, matching the existing `INVALID_SEARCH_SPACE` precedent in this file (search-space-shape errors are 400; cross-resource consistency errors are 422).
- The new validation **MUST** fire BEFORE the query_set / judgment_list FK lookups so that a search-space typo is reported even when other downstream errors would also apply (most informative first).
- Status code ordering when multiple checks would fail:
  1. `SearchSpace.model_validate` → 400 `INVALID_SEARCH_SPACE`
  2. Cluster FK → 404 `CLUSTER_NOT_FOUND`
  3. Template FK → 404 `TEMPLATE_NOT_FOUND`
  4. **NEW:** `validate_against_template` → 400 `SEARCH_SPACE_UNKNOWN_PARAM` or `SEARCH_SPACE_MISSING_DECLARED_PARAM`
  5. Query-set FK → 404 `QUERY_SET_NOT_FOUND`
  6. Judgment-list FK → 404 `JUDGMENT_LIST_NOT_FOUND`
  7. Query-set consistency → 422 `VALIDATION_ERROR`

### 8.3 Response examples

**Success (existing — no change):**
```json
{
  "id": "01931b6e-...-...",
  "name": "tune product_search v1",
  "cluster_id": "01931b6e-...",
  "target": "products",
  "template_id": "01931b6e-...",
  "query_set_id": "01931b6e-...",
  "judgment_list_id": "01931b6e-...",
  "search_space": { "params": { "boost_title": { "type": "float", "low": 0.5, "high": 10.0, "log": true } } },
  "objective": { "metric": "ndcg", "k": 10, "direction": "maximize" },
  "config": { "max_trials": 50, "parallelism": 4 },
  "status": "queued",
  "...": "..."
}
```
HTTP 201.

**Failure — unknown param (NEW):**
```json
{
  "detail": {
    "error_code": "SEARCH_SPACE_UNKNOWN_PARAM",
    "message": "Param 'boos_title' is not declared by template 'product_search v1'. Declared params: ['boost_body', 'boost_title', 'fuzziness'].",
    "retryable": false
  }
}
```
HTTP 400.

**Failure — missing declared param (NEW):**
```json
{
  "detail": {
    "error_code": "SEARCH_SPACE_MISSING_DECLARED_PARAM",
    "message": "Template 'product_search v1' declares param 'fuzziness' but it is missing from the search space. Add it or remove from the template.",
    "retryable": false
  }
}
```
HTTP 400.

**Failure — pre-existing `INVALID_SEARCH_SPACE` (unchanged, for reference):**
```json
{
  "detail": {
    "error_code": "INVALID_SEARCH_SPACE",
    "message": "<Pydantic ValidationError serialization>",
    "retryable": false
  }
}
```
HTTP 400.

### 8.4 Enumerated value contracts

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `objective.metric` | `ndcg`, `map`, `precision`, `recall`, `mrr`, `err` | `backend/app/api/v1/schemas.py:167` (`ObjectiveMetric = Literal[...]`) | `OBJECTIVE_METRIC_VALUES` at `ui/src/lib/enums.ts:66`, used at `create-study-modal.tsx:357` |
| `objective.k` | `1`, `3`, `5`, `10`, `20`, `50`, `100` | `backend/app/api/v1/schemas.py:170` (`ObjectiveK = Literal[1, 3, 5, 10, 20, 50, 100]`) | `OBJECTIVE_K_VALUES` at `ui/src/lib/enums.ts:77`, used at `create-study-modal.tsx:380` |
| `objective.direction` | `maximize`, `minimize` | `backend/app/api/v1/schemas.py` (`ObjectiveDirection`) | `OBJECTIVE_DIRECTION_VALUES` at `ui/src/lib/enums.ts`, used at `create-study-modal.tsx` |
| `K_REQUIRED` (frontend predicate, mirror of backend `_K_REQUIRED_METRICS`) | `ndcg`, `precision`, `recall` | `backend/app/api/v1/schemas.py:474` (`_K_REQUIRED_METRICS: frozenset[str]`) | `ui/src/components/studies/create-study-modal.tsx:46`; Step-5 conditional rendering at line 377 |
| `K_IGNORED` (new frontend predicate; backend has no symmetric set) | `mrr`, `err` | `backend/app/eval/scoring.py:32` (comment `"map → k OPTIONAL"`, `"mrr → k IGNORED"`, `"err → k IGNORED"`) | `ui/src/components/studies/create-study-modal.tsx` (new constant); FR-4 hidden-with-caption logic |

The metric+k coupling is **tri-state** on the backend:
- **Required:** `_K_REQUIRED_METRICS = frozenset({"ndcg", "precision", "recall"})`. Backend rejects with ValueError when k is None.
- **Optional:** `map` only. Presence of k → `map@k`; absence → full-recall MAP.
- **Ignored:** `mrr`, `err`. Backend accepts k but `scoring.py` discards it during pytrec_eval token construction.

Both frontend predicates are typed as `ReadonlySet<ObjectiveMetric>` so TypeScript prevents unknown-metric leakage. Drift between either predicate and backend reality is detected by AC-13 and AC-14.

### 8.5 Error code catalog

| Code | HTTP Status | Meaning |
|------|-------------|---------|
| `SEARCH_SPACE_UNKNOWN_PARAM` | 400 | A `search_space.params` key is not in the selected template's `declared_params`. Retryable: false. |
| `SEARCH_SPACE_MISSING_DECLARED_PARAM` | 400 | A `declared_params` key is not in the submitted `search_space.params`. Retryable: false. |

Both codes are stable (never renamed) per `api-conventions.md` §"Error code stability."

## 9) Data model and state transitions

**N/A.** No schema changes. No new tables, no migrations, no column additions. The new validation reads `query_templates.declared_params` (existing JSONB column) and `studies.search_space` (existing JSONB column); no persistence shape changes.

State transitions: unchanged. The study's `status` machine remains `queued → running → completed | cancelled | failed`.

## 10) Security, privacy, and compliance

- **Threats:**
  1. Information disclosure via error messages — the unknown-param error message includes the full list of declared params for the template. This is internal data the operator already has access to via `GET /api/v1/query-templates/{id}`; not a leak.
  2. Validation-bypass timing attacks — N/A; no auth surface.
  3. Cardinality DoS — already mitigated by the existing 10⁶ cap in `SearchSpace.model_validate`.
- **Controls:** The new validation strictly tightens the create-study contract; it cannot accept inputs that the existing handler would reject. No relaxation paths.
- **Secrets/key handling:** N/A — no new secrets.
- **Auditability:** N/A in MVP1. At MVP2 the existing `study.created` audit event will carry the validated search_space verbatim; no additional event types needed for failed validations (failed POSTs don't audit).
- **Data retention/deletion/export impact:** None.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** Unchanged — the create-study modal is reached from the studies list page's "New study" button at [`ui/src/app/studies/page.tsx`](../../../../ui/src/app/studies/page.tsx). This spec modifies the existing modal's Step 4 and Step 5 only.
- **Labeling taxonomy:**
  - Step-4 label `"Search space (JSON)"` (unchanged).
  - **NEW:** sibling info icon (the standalone `<InfoTooltip>` 24×24 button) immediately to the right of the label, opening tooltip `study.search_space`.
  - **NEW:** `<HelpPopover glossaryKey="study.search_space" />` icon below the textarea, opening the dual entry's `long` field (single Markdown body covering ParamSpec types, log scale, and the cardinality cap).
  - Step-5 k field sub-label `"Top-k cutoff (required for {METRIC})"` when required-k metric selected; `"Top-k cutoff (optional — leave empty for full-recall {METRIC})"` when optional-k (`map`).
  - Step-5 k field replacement caption `"{METRIC} evaluates the full ranked list — no cutoff used."` when ignored-k metric (`mrr`/`err`) selected.
- **Content hierarchy (Step 4):** label + info icon → textarea → help popover → (existing) Next button.
- **Progressive disclosure:** The `<HelpPopover>` keeps the long-form details collapsed by default; user clicks to expand. The headline `<InfoTooltip>` on the label is always-available via hover/focus.
- **Relationship to existing pages:** Extends the existing modal; no new pages.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement |
|---------|-------------------|---------|-----------|
| Step-4 label "Search space (JSON)" | `study.search_space.short` (TBD copy in implementation — see §19 Open Q) | hover / focus on info icon | right of label, `<InfoTooltip glossaryKey="study.search_space" />` standalone (reads `short`) |
| Step-4 help popover | `study.search_space.long` (the combined "what it is + ParamSpec types + log scale + cardinality cap" narrative as one Markdown body) | click on help icon | below textarea, `<HelpPopover glossaryKey="study.search_space" />` (reads `long`) |
| Step-5 k field (required-k metric) | existing `study.k.short` (unchanged copy); sub-label below field is plain text (not a tooltip) | hover / focus on info icon | right of "k" label, `<InfoTooltip>` standalone (unchanged from today) |
| Step-5 k field (optional-k metric, `map`) | existing `study.k.short`; sub-label below field is plain text | hover / focus on info icon | right of "k" label (unchanged surface) |
| Step-5 k field (ignored-k metric, `mrr` / `err`) | replacement caption inline (plain text, not a tooltip) | always visible | inline where the k field used to be |
| Each per-metric option (extended) | existing `study.metric.<metric>.short` + new tier-specific clause (per FR-6) | hover / focus | (current behavior, unchanged surface) |

**Note on the three `study.search_space.*` subkey entries:** `param_spec`, `log`, and `cardinality` are added to glossary.ts by FR-5 but are NOT wired into the Step-4 surface by this chore (only the parent `study.search_space` entry is surfaced, via the dual InfoTooltip/HelpPopover pair above). The three subkeys exist as forward-compatibility hooks for `feat_create_study_search_space_builder`'s future per-param-row InfoTooltips.

### Primary flows

1. **Auto-fill flow.** User completes Step 3 (template selection). User clicks Next. The modal's `useEffect` (keyed on `template_id`) fetches `GET /api/v1/query-templates/{id}` if not already cached, then sets `search_space_text` to the auto-fill JSON if the current textarea content is empty or matches a known auto-fill signature. Step 4 renders with the textarea pre-filled. User edits if needed, clicks Next.
2. **Validation flow (happy path).** Step 4 textarea content parses as JSON and validates against `declared_params` client-side (the unknown-param / missing-declared-param checks from FR-2 + FR-3 mirror). The full `SearchSpace` semantic validation (bounds, log requires low>0, cardinality cap) runs **server-side only** — adding the full mirror in TypeScript is deferred (would duplicate ~80 LOC of Pydantic logic with parity-test risk); if a user submits a bound violation, they see the 400 `INVALID_SEARCH_SPACE` envelope after the POST round-trip. Step 4 → Step 5 transition succeeds when JSON-parse + client-side declared-param checks pass. POST 201 when server-side `SearchSpace.model_validate` + `validate_against_template` both pass.
3. **Step-5 metric+k flow.** User picks `ndcg`. k `<Select>` renders with `"Top-k cutoff (required for NDCG)"` sub-label. User picks `10`. User changes mind, picks `map` — sub-label flips to `"Top-k cutoff (optional — leave empty for full-recall MAP)"`; k value of `10` is preserved (now means map@10). User clears k via the "—" entry. User picks `mrr` — k `<Select>` hides, replacement caption `"MRR evaluates the full ranked list — no cutoff used."` shows; form state for k clears to `undefined`. POST succeeds with no `k` in the objective body.

### Edge/error flows

- **Edge: user edits Step 4 then revisits Step 3 and changes template.** Toast appears: "Selecting a new template will replace your Step-4 content with defaults for the new template. Undo (10s)." Toast Undo button restores the prior `search_space_text` value.
- **Edge: template has zero declared params.** Block the Step-3 → Step-4 transition before auto-fill runs. When the fetched template body has `Object.keys(template.declared_params).length === 0`, the Step-3 Next button shows an inline error reading `"This template has no tunable parameters. Pick a different template, or add params to this one before running a study."` and is disabled. Auto-fill never runs in this case (avoiding any tension with FR-1's "MUST be valid against SearchSpace.model_validate" rule, which would be violated by an empty `params: {}`).
- **Error: unknown param on submit.** Client-side validator catches before POST; inline error label under textarea. If the user bypasses the client-side check (rare; only possible by editing form state via devtools), the server returns 400 `SEARCH_SPACE_UNKNOWN_PARAM` and the modal displays the server's `message` in the same inline-error location.
- **Error: missing declared param on submit.** Same handling as unknown-param.
- **Error: stale k value retained when metric changes.** Prevented by FR-4 — k form state is cleared on metric change.
- **Recovery: GET /api/v1/query-templates/{id} 404.** The template was deleted between Step-3 selection and Step-4 entry. Toast: "The selected template is no longer available. Pick another." User is bumped back to Step 3.
- **Loading state: GET /api/v1/query-templates/{id} pending.** The Step-3 → Step-4 transition does NOT block on the template fetch. Step 4 renders with an empty textarea and a "Loading template…" inline notice while the fetch is in flight. Auto-fill runs as soon as the fetch resolves, replacing the empty textarea content (no toast/Undo prompt — replacing empty content is always safe). If the user starts typing into the textarea before the fetch resolves, the resolution is treated like a template change (FR-1's toast+Undo flow applies).
- **Error: GET /api/v1/query-templates/{id} 5xx or network failure.** Toast: "Couldn't load the template. Retry?" with a Retry button that re-fires the fetch. Step 4 still renders (the modal does not bump the user back to Step 3 on transient errors — only on 404). Auto-fill does not run. The user MAY hand-write Step-4 content and proceed to Step 5 / submit — the Next button is **not** disabled. Client-side declared-param validation (FR-2 / FR-3 mirror) cannot fire because `declared_params` is unavailable, so a typo'd param will surface as the server-side 400 `SEARCH_SPACE_UNKNOWN_PARAM` after the POST round-trip. This is the explicit safety-net path; the spec accepts the worse-UX-on-transient-error tradeoff rather than blocking the user behind an external dependency.

## 12) Given/When/Then acceptance criteria

### AC-1: Step-4 auto-fill from template's declared params

- Given a template `T1` with `declared_params: {"boost_title": "float", "boost_body": "float", "min_should_match": "int", "fuzziness": "string"}`
- And the user has reached Step 3 and selected `T1`
- When the user advances to Step 4 with an empty textarea
- Then the textarea content equals (after `JSON.parse`):
  ```json
  {"params":{"boost_title":{"type":"float","low":0.5,"high":10.0,"log":true},"boost_body":{"type":"float","low":0.5,"high":10.0,"log":true},"min_should_match":{"type":"int","low":0,"high":5},"fuzziness":{"type":"categorical","choices":["AUTO","0","1","2"]}}}
  ```

### AC-2: Auto-fill skipped when user has edited Step 4

- Given the user has typed any non-empty content into Step 4 that doesn't match a known auto-fill signature
- When the user goes back to Step 3 and re-selects the same template
- Then the Step-4 textarea content is unchanged (auto-fill does not run silently)

### AC-3: Toast + Undo on template change with edited Step-4 content

- Given the user has typed `{"params": {"custom_param": {"type": "float", "low": 0.1, "high": 1.0}}}` into Step 4
- When the user goes back to Step 3 and selects a different template `T2`
- Then the textarea content is **immediately** replaced with the auto-fill for `T2`
- And a toast appears with text `"Replaced your Step-4 content with defaults for the new template."` and an "Undo" action button
- And the toast auto-dismisses after 10 seconds if no action is taken
- And clicking the toast's "Undo" action within 10 seconds restores the user's original `{"params": {"custom_param": ...}}` content into the textarea

### AC-4: Unknown param rejected client-side

- Given a template `T1` with `declared_params: {"boost_title": "float"}`
- And the user has entered `{"params": {"boost_titl": {"type": "float", "low": 0.5, "high": 10.0}}}` into Step 4
- When the user clicks Next
- Then an inline error label appears under the textarea reading `"Param 'boost_titl' is not declared by template 'T1'. Declared params: ['boost_title']."`
- And the Next button does not advance to Step 5

### AC-5: Unknown param rejected server-side

- Given a study POST body whose `search_space.params` contains a key `boost_titl` not in the template's `declared_params`
- When the request is sent (bypassing client-side validation)
- Then the server responds with HTTP 400 and body
  ```json
  {"detail":{"error_code":"SEARCH_SPACE_UNKNOWN_PARAM","message":"Param 'boost_titl' is not declared by template 'T1'. Declared params: ['boost_title'].","retryable":false}}
  ```

### AC-6: Missing declared param rejected server-side

- Given a study POST body whose `search_space.params` omits a key `fuzziness` that exists in the template's `declared_params`
- When the request is sent
- Then the server responds with HTTP 400 and body
  ```json
  {"detail":{"error_code":"SEARCH_SPACE_MISSING_DECLARED_PARAM","message":"Template 'T1' declares param 'fuzziness' but it is missing from the search space. Add it or remove from the template.","retryable":false}}
  ```

### AC-7: Unknown-param error wins over missing-declared-param error

- Given a study POST body that has both an unknown key AND a missing key
- When the request is sent
- Then the server responds with `SEARCH_SPACE_UNKNOWN_PARAM` (not `SEARCH_SPACE_MISSING_DECLARED_PARAM`), reporting the first unknown key in lexicographic order

### AC-8: Step-5 k field renders as required for required-k metrics

- Given the user has selected metric `ndcg` on Step 5
- Then the k `<Select>` is visible
- And a sub-label below the k field reads `"Top-k cutoff (required for NDCG)"`
- And the `<InfoTooltip glossaryKey="study.k" />` is rendered adjacent to the "k" label

### AC-9a: Step-5 k field renders as optional for `map`

- Given the user has selected metric `map` on Step 5
- Then the k `<Select>` is visible
- And a sub-label below the k field reads `"Top-k cutoff (optional — leave empty for full-recall MAP)"`
- And the `<Select>` option list includes a clearable "—" entry that returns the form state for k to `undefined`

### AC-9b: Step-5 k field hidden for ignored-k metrics

- Given the user has selected metric `mrr` (or `err`) on Step 5
- Then the k `<Select>` is not in the DOM
- And in its place, a single-line caption reads `"MRR evaluates the full ranked list — no cutoff used."` (or `"ERR ... no cutoff used."`)

### AC-10a: Stale k cleared when switching into the ignored tier

- Given the user has selected `ndcg` and set k to `10`
- When the user changes metric to `mrr`
- Then the form state for `k` is `undefined`
- And when the user changes metric back to `ndcg`, the k `<Select>` shows the placeholder `"required"` (no value pre-populated)

### AC-10b: k preserved when switching between required and optional tiers

- Given the user has selected `ndcg` and set k to `10`
- When the user changes metric to `map`
- Then the form state for `k` remains `10` (preserved across the required→optional tier transition)
- And when the user changes metric to `precision` (still required), `k` remains `10`

### AC-11: New glossary entries comply with parity/length tests

- Given the new keys `study.search_space`, `study.search_space.param_spec`, `study.search_space.log`, `study.search_space.cardinality` have been added to `glossary.ts`
- When `pnpm test ui/src/__tests__/lib/glossary.test.ts` runs
- Then the test passes (length bounds, no backend jargon, key parity not regressed)

### AC-12: Step-4 `<InfoTooltip>` opens on label hover

- Given Step-4 is rendered
- When the user hovers (or focuses via keyboard tab) the info icon next to the "Search space (JSON)" label
- Then a tooltip with `data-testid="tooltip-body-study.search_space"` appears with the `short` copy

### AC-13: `K_REQUIRED` membership matches backend `_K_REQUIRED_METRICS`

- Given the set of metrics for which the backend's `ObjectiveSpec` validator requires `k` (the frozenset `_K_REQUIRED_METRICS` at [`backend/app/api/v1/schemas.py:474`](../../../../backend/app/api/v1/schemas.py#L474))
- Then `K_REQUIRED` (the frontend predicate at `create-study-modal.tsx:46`) equals that set exactly
- Asserted by **two** tests that together detect drift in either direction:
  1. **Backend contract test** at `backend/tests/contract/test_k_required_membership.py` — POSTs each metric in `OBJECTIVE_METRIC_VALUES` with and without k. The `ObjectiveSpec`'s `model_validator` raises during Pydantic body parsing (FastAPI runs this BEFORE the route handler), so the failure surfaces via the project's `RequestValidationError` exception handler at [`backend/app/api/errors.py:108`](../../../../backend/app/api/errors.py#L108) as **HTTP 422** with `error_code: VALIDATION_ERROR`, **not** the router-local `_err()` envelope. Expected results:
     - `ndcg` / `precision` / `recall` without k → 422 `VALIDATION_ERROR` (envelope `{"detail": {"error_code": "VALIDATION_ERROR", "message": "<...>", "retryable": false}}`)
     - `ndcg` / `precision` / `recall` with k=10 → 201
     - `map` / `mrr` / `err` without k → 201
     - `map` / `mrr` / `err` with k=10 → 201
  2. **Frontend unit test** at `ui/src/__tests__/components/studies/k-required.test.ts` — imports `K_REQUIRED` from the modal module and asserts it equals `new Set(['ndcg', 'precision', 'recall'])`. Includes a source-of-truth comment citing `backend/app/api/v1/schemas.py:474` so future edits update both halves. Without this second test, a wrong frontend predicate would pass the backend contract test silently.

### AC-14: `K_IGNORED` membership matches the metrics scoring layer ignores

- Given the metric → pytrec_eval token mapper inside [`backend/app/eval/scoring.py`](../../../../backend/app/eval/scoring.py) (whichever function name produces tokens like `"recip_rank"`, `"err"`, `"ndcg_cut_10"`, `"map_cut_10"`)
- Then for every metric the function ignores `k` when constructing the token, that metric appears in the frontend `K_IGNORED` set, and vice versa.
- Asserted by **two** tests:
  1. **Backend unit test** at `backend/tests/unit/eval/test_scoring_metric_tokens.py` — calls the mapper for each `metric ∈ OBJECTIVE_METRIC_VALUES` with `k=None` and `k=10`; asserts that for `mrr` and `err` the output is identical (k ignored), for `ndcg`/`precision`/`recall` the `k=None` call raises or is rejected upstream, and for `map` the `k=None` call returns the full-recall token (`"map"`) while `k=10` returns `"map_cut_10"`.
  2. **Frontend unit test** at `ui/src/__tests__/components/studies/k-ignored.test.ts` — imports `K_IGNORED` from the modal module, asserts it equals `new Set(['mrr', 'err'])`. Includes a source-of-truth comment citing the backend test by path so future edits update both halves.

## 13) Non-functional requirements

- **Performance:** Auto-fill is purely client-side after the single-template GET (one network round-trip, sub-100ms locally; cached for the remainder of the modal session). Client-side validation is O(|declared_params| + |search_space.params|) — sub-millisecond for realistic template sizes.
- **Reliability:** No new long-running paths. The new validation is synchronous Python inside a single existing endpoint.
- **Operability:** No new metrics needed. The new error codes appear in existing structured-log fields (`error_code`); operators can grep for them.
- **Accessibility/usability:**
  - Tooltips must be focusable via keyboard tab (existing `<InfoTooltip>` already meets this — verified at PR #122 AC-11).
  - Inline error labels for FR-2 / FR-3 must be `aria-live="polite"` (matches `feat_studies_ui` pattern).
  - Step-5 caption replacement for non-ranked metrics must be readable by screen readers — implement as a `<p>` (not visually-hidden + sr-only) so users with low vision see the explanation.

## 14) Test strategy requirements

### Unit (`backend/tests/unit/domain/`)
- `test_validate_against_template_unknown_param`: search_space has key not in declared_params → raises `UnknownSearchSpaceParamError`.
- `test_validate_against_template_missing_declared`: declared_params has key not in search_space → raises `MissingDeclaredParamError`.
- `test_validate_against_template_happy_path`: keys match → returns None.
- `test_validate_against_template_both_errors_ordering`: both conditions present → unknown-param raised first.

### Unit (`ui/src/__tests__/lib/`)
- `search-space-defaults.test.ts`: each heuristic case (regex match for boost, tie_breaker, slop, fuzziness, fallback) produces the expected ParamSpec.
- `search-space-defaults.cardinality.test.ts`: TS port of `estimate_cardinality` produces identical values to the backend on a snapshot set of search spaces (parity test).
- `glossary.test.ts` (existing): runs unchanged; new entries auto-covered.

### Integration (`backend/tests/integration/`)
- `test_studies_create_unknown_param`: POST with unknown param → 400 SEARCH_SPACE_UNKNOWN_PARAM, study row not created.
- `test_studies_create_missing_declared_param`: POST with missing declared → 400 SEARCH_SPACE_MISSING_DECLARED_PARAM, study row not created.
- `test_studies_create_both_errors_ordering`: POST with both → 400 with UNKNOWN code.

### Contract (`backend/tests/contract/`)
- `test_studies_error_codes`: POST `/api/v1/studies` with bodies that trigger each new error path; assert the response status code and envelope match (per AC-5, AC-6). The test asserts **behavior**, not OpenAPI enum membership — `_err()` is an inline raise pattern that does not populate `responses=` decorator metadata, and adding `responses={400: {...}}` decorators to the route is out of scope for this chore.
- `test_k_required_membership`: POSTs each metric in `OBJECTIVE_METRIC_VALUES` with and without k; asserts the actual response status code and envelope for each case (per AC-13). Surfaces drift between frontend `K_REQUIRED` and backend `_K_REQUIRED_METRICS`.

### Component (`ui/src/__tests__/components/studies/`)
- `create-study-modal.auto-fill.test.tsx`: Step-3 → Step-4 transition pre-fills textarea with computed JSON for various declared_params shapes.
- `create-study-modal.auto-fill.undo.test.tsx`: toast Undo restores user-edited content within 10s.
- `create-study-modal.metric-k.test.tsx`: switching metric shows/hides k, clears stale value.
- `create-study-modal.client-validation.test.tsx`: unknown / missing param surfaces inline error on Next-click.

### E2E (`ui/tests/e2e/`)
- `studies.spec.ts` (existing): extend the happy-path "create a study" test to assert auto-fill text presence after template selection.
- `studies-create-validation.spec.ts` (new): real-browser E2E that types an unknown-param payload into Step 4 and clicks Next; asserts the client-side validator renders the spec's exact message format inline. The **server-side** error path is covered by the backend contract test `test_studies_error_codes.py` (Story 1.1) and `test_k_required_membership.py` (Story 1.2) — an E2E test of the server-rejection display path is technically possible only by bypassing the client-side validator, which would require either `page.route()` mocking (forbidden by this section) or a deliberate template-fetch-failure setup that the spec's §11 edge flow handles differently (it allows hand-typed submission to fall through to server-side rejection, but the test surface is fragile). The client-side mirror E2E + backend contract test together prove the contract holds in both layers; an explicit server-side display E2E is deferred (see §19 decision log).

## 15) Documentation update requirements

- `docs/01_architecture/ui-architecture.md` — extend the "Glossary keys (canonical)" sub-section with the four new `study.search_space.*` keys and a one-line note that Step-4 auto-fill exists.
- `docs/01_architecture/api-conventions.md` — append the two new error codes to the canonical catalog table (per `api-conventions.md` §"Error code stability").
- `docs/02_product` — no user-facing doc updates beyond this spec.
- `docs/03_runbooks` — N/A (no new operational surfaces).
- `docs/04_security` — N/A.
- `docs/05_quality` — N/A (no test framework changes).
- `docs/08_guides/tutorial-first-study.md` — update Step 7 (template creation) to mention that the wizard now auto-fills Step 4 from `declared_params`; remove the "copy this JSON" verbatim block, replace with "the wizard will auto-fill Step 4 once you've picked the template" instruction.
- `state.md` — append a "Just shipped" line on completion.
- `CLAUDE.md` — no rule changes (the new error codes follow the existing inline-string-literal pattern; the SoT comment in `glossary.ts` follows the existing pattern).

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None. Single-tenant install, no flags.
- **Migration/backfill expectations:** None.
- **Operational readiness gates:** No new alerts/metrics; existing structured logging covers the new error codes by virtue of the standard envelope.
- **Release gate:** All ACs passing in CI; `pnpm test` and `make test` green; `pnpm playwright` green for the touched E2E specs; Gemini Code Assist review addressed per CLAUDE.md.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-2, AC-3 | Implementation plan (TBD) — Stories "Search-space defaults module" + "Auto-fill wiring + Undo toast" | `ui/src/__tests__/lib/search-space-defaults.test.ts`, `create-study-modal.auto-fill.test.tsx`, `create-study-modal.auto-fill.undo.test.tsx`, `studies.spec.ts` | `ui-architecture.md` |
| FR-2 | AC-4, AC-5, AC-7 | "validate_against_template + UnknownSearchSpaceParamError", "Wire into POST /studies", "Client-side mirror" | `test_validate_against_template_unknown_param.py`, `test_studies_create_unknown_param.py`, `test_studies_error_codes.py`, `create-study-modal.client-validation.test.tsx` | `api-conventions.md` |
| FR-3 | AC-6, AC-7 | "MissingDeclaredParamError", "Client-side mirror" | `test_validate_against_template_missing_declared.py`, `test_studies_create_missing_declared_param.py`, `test_studies_error_codes.py` | `api-conventions.md` |
| FR-4 | AC-8, AC-9a, AC-9b, AC-10a, AC-10b, AC-13, AC-14 | "Step-5 metric+k tri-state rendering" | `create-study-modal.metric-k.test.tsx`, `test_k_required_membership.py`, `test_k_ignored_membership.test.ts` | — |
| FR-5 | AC-11, AC-12 | "Add four glossary entries" | `glossary.test.ts`, `create-study-modal.test.tsx` (tooltip presence) | `ui-architecture.md` |
| FR-6 | AC-11 | "Extend per-metric glossary entries with k-applicability" | `glossary.test.ts` | — |
| FR-7 | AC-12 | "Wire `<InfoTooltip>` + `<HelpPopover>` into Step 4" | `create-study-modal.test.tsx` | — |

## 18) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-1 through AC-14, including AC-9a, AC-9b, AC-10a, AC-10b) pass in CI.
- [ ] All test layers (unit/integration/contract/component/e2e) are green.
- [ ] Documentation updates to `ui-architecture.md` and `api-conventions.md` are merged.
- [ ] Tutorial doc updated to remove the verbatim search-space paste step.
- [ ] No open questions remain in §19.
- [ ] Gemini Code Assist review comments adjudicated and addressed.
- [ ] Final GPT-5.5 review clean.

## 19) Open questions and decision log

### Open questions

- **Q1: Final copy for the four new glossary entries (`study.search_space`, `.param_spec`, `.log`, `.cardinality`).** Owner: Eric Starr. Due: before plan generation. Recommended approach in plan-gen: draft per `feat_contextual_help` voice / length norms, run through GPT-5.5 for polish, snapshot in glossary.test.ts. *Not blocking for plan generation* — copy decisions belong with the writing, not the architecture.
- **Q2: Exact wording of the toast + Undo on template change.** Owner: Eric Starr. Due: before plan generation. Same disposition as Q1.

### Decision log

- **2026-05-19 — Hard-reject missing-declared-param at create time (not warn).** Rationale: today's run_trial path calls `adapter.render` which hard-fails on `set(declared_params) - set(params.keys())` at [`backend/app/adapters/elastic.py:493-495`](../../../../backend/app/adapters/elastic.py#L493-L495); `compute_default_params` is exported from `template_defaults.py` but **not called from any current app code** (grep confirmed). A "warn at create time" path would let users POST a study guaranteed to fail on trial 1. Locking the validation to mirror the trial worker's reality. The "wire `compute_default_params` into the trial path → downgrade to warn" alternative is captured separately as a future `chore_template_defaults_dead_code` idea.
- **2026-05-19 — HTTP status 400 (not 422) for both new error codes.** Rationale: matches the existing `INVALID_SEARCH_SPACE` precedent at [`studies.py:195`](../../../../backend/app/api/v1/studies.py#L195) for search-space-shape errors. 422 in this codebase is reserved for cross-resource consistency errors (judgment_list ↔ query_set match).
- **2026-05-19 — Auto-fill heuristic is naming-convention-based, not engine-aware.** Rationale: this chore intentionally keeps engine-aware defaults out of scope (deferred to `chore_template_library_expansion`). The single naming-convention heuristic works for ES and OpenSearch (which share the same query DSL in MVP1).
- **2026-05-19 — Defaults heuristic lives in `ui/src/lib/search-space-defaults.ts` (frontend canonical).** Rationale: `feat_agent_propose_search_space` will later mirror this module to backend (`backend/app/domain/study/search_space_defaults.py`) for its `propose_search_space` agent tool. Keeping the canonical version on the frontend (where it's used immediately) and mirroring later, rather than building the backend module speculatively now.
- **2026-05-19 — Step-4 help surface uses `<InfoTooltip>` + `<HelpPopover>` both pointing at the dual entry `study.search_space`.** Rationale: `<HelpPopover>` accepts a single `glossaryKey` with `long` content (verified at `ui/src/components/common/help-popover.tsx:29`), so wiring three separate short-only subkeys into one popover would require extending the component — out of scope for this chore. Putting the consolidated narrative in `study.search_space.long` keeps both surfaces fed from one entry. The three subkeys (`param_spec`, `.log`, `.cardinality`) stay in glossary.ts as future-builder-UI hooks but aren't wired by this chore.
- **2026-05-19 — Unknown-param error wins over missing-declared-param error when both apply.** Rationale: unknown params are usually typos the user can fix immediately; missing-declared params often mean the user wanted to omit them (and the spec authoritatively rejects that). Reporting the "user mistake" first improves the fix loop.
- **2026-05-19 — No backend constants module for the two new error codes.** Rationale: RelyLoop's current convention is inline string literals at `_err()` call sites (per `clusters.py:94`, `judgments.py:89`, `proposals.py:84`). Introducing a `backend/app/api/v1/error_codes.py` constants module for two new codes would be a cross-cutting refactor outside the scope of this chore. The behavioral contract test (POST → expected envelope) is the safety net — not an OpenAPI schema enum check, since `_err()` is an inline raise pattern that does not populate `responses=` decorator metadata.
- **2026-05-19 — Metric+k is tri-state, not binary.** Rationale: Pass-1 codebase review surfaced that the backend treats `map` as optional-k ([`backend/app/eval/scoring.py:32`](../../../../backend/app/eval/scoring.py#L32): "map → k OPTIONAL (presence = map@k cut; absence = full-recall MAP)") while treating `mrr` and `err` as ignored-k. The initial spec draft conflated map/mrr/err into a single "non-ranked, hide k" tier — that would have removed the ability to compute `map@k` from the UI. FR-4 corrected to three tiers (required / optional / ignored) with the new frontend predicate `K_IGNORED = {mrr, err}`. The optional tier currently has only `map` but is structurally distinct so a future metric in this category (if any) doesn't force another spec round.
- **2026-05-19 — k value preservation policy across metric changes.** Rationale: switching from ndcg (k=10) to map should preserve `k=10` (map@10 is meaningful); switching from ndcg to mrr should clear k (mrr ignores it; carrying stale state into the POST body is sloppy). Specifically: k clears when the new metric is in `K_IGNORED`; k preserves otherwise.
- **2026-05-19 — Cap-aware fallback for `buildStarterSearchSpace`.** Discovered during plan generation (GPT-5.5 cycle 1 finding B3): the locked heuristic in FR-1 produces search spaces whose cardinality exceeds 10⁶ for templates with ≥4 float declared params (4 × 100 = 10⁸). To preserve FR-1's "MUST be valid against SearchSpace.model_validate" rule, the auto-fill function falls back by converting unmatched float params to `{type: 'int', low: 0, high: 5}` (contribution 6 each) when cardinality would exceed 10⁶. The fall-through (unmatched) floats are converted first to preserve the regex-matched (boost-like, tie_breaker-like, fuzziness) param shapes. The function also emits a `console.warn` so developers see the fallback fire during testing.
- **2026-05-19 — Server-side error display E2E deferred.** Discovered during plan generation (GPT-5.5 cycle 2 finding B4): the spec's original §14 wording called for an E2E test driving the modal to display a server-returned `SEARCH_SPACE_UNKNOWN_PARAM` envelope. That requires bypassing the client-side mirror, which can be done only via `page.route()` mocking (forbidden by §14's E2E rule) or a fragile template-fetch-failure setup. The client-side mirror E2E (`studies-create-validation.spec.ts`) + backend contract tests (`test_studies_error_codes.py`, `test_k_required_membership.py`) together prove the contract holds in both layers; an explicit server-side display E2E is deferred — capture as `chore_create_study_server_error_e2e` if a stable bypass mechanism (test-only env var or hidden URL param) lands later.
