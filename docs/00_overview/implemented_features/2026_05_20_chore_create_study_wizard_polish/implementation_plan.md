# Implementation Plan — Create-Study Wizard Polish

**Date:** 2026-05-19
**Status:** Complete (PR #157, merged 2026-05-20)
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):** [`CLAUDE.md`](../../../../CLAUDE.md), [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md), [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md)

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs in spec.
- No new endpoints, no migration, single phase — sequencing risk is low.
- Backend foundations land first (Epic 1); frontend depends on the new error codes via integration tests.
- Each story is independently reviewable + testable; minimum one test file per story.
- Cross-layer parity tests (frontend `K_REQUIRED` / `K_IGNORED` vs backend `_K_REQUIRED_METRICS` / `scoring.py`) ship deliberately as paired tests in adjacent stories to lock the drift gate.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (Auto-fill Step 4) | Epic 2 / Story 2.1 (defaults module) + Epic 3 / Story 3.1 (wiring) | Module defines the heuristic; modal consumes it on Step-3 → Step-4 transition. |
| FR-2 (Reject unknown params) | Epic 1 / Story 1.1 (validator + router) + Epic 3 / Story 3.1 (client-side mirror) | Backend authoritative; frontend mirror is a UX nicety. |
| FR-3 (Reject missing declared params) | Epic 1 / Story 1.1 (validator + router) + Epic 3 / Story 3.1 (client-side mirror) | Same module as FR-2; ordering rule (unknown wins) implemented in `validate_against_template`. |
| FR-4 (Step 5 metric+k tri-state) | Epic 3 / Story 3.2 (rendering) + Epic 1 / Story 1.2 (scoring token test) | Frontend is presentation; backend test locks tier semantics. |
| FR-5 (New glossary entries) | Epic 2 / Story 2.2 (glossary content) | `study.search_space` (dual), `.param_spec` / `.log` / `.cardinality` (short-only). |
| FR-6 (Extend per-metric entries) | Epic 2 / Story 2.2 (glossary content) | Append k-tier clause to `study.metric.{ndcg,map,precision,recall,mrr,err}`. |
| FR-7 (Wire glossary surfaces) | Epic 3 / Story 3.1 (Step-4 InfoTooltip + HelpPopover) + Story 3.2 (Step-5 reuses existing `study.k` tooltip) | InfoTooltip + HelpPopover both read `study.search_space` (dual). |

No spec FRs are out of scope; no `phase*_idea.md` artifacts required (single-phase chore).

## 2) Delivery structure

**Structure:** Epic → Story → Tasks → DoD (product-facing chore).

### Conventions

- All repo functions take `db: AsyncSession` as first arg; use `await db.flush()` (caller commits).
- Services are async; `_err()` helper is per-router in `backend/app/api/v1/<resource>.py`.
- Domain layer is pure — no DB access, no async, no I/O.
- Error codes are inline string literals at `_err()` call sites — no central constants module (RelyLoop convention).
- Frontend: TypeScript strict, Vitest 4, React Hook Form, shadcn/ui primitives.
- New `<select>` / option arrays must carry a `// Source-of-truth: <backend/path.py> <Symbol>` comment and be grounded against a backend `Literal[...]` / `frozenset` / DB CHECK.
- TanStack Query caches the selected template body for the modal session; consumer fetches via `useQueryTemplate(id)` hook (matches `feat_studies_ui` pattern).
- All new tests must run in the standard `make test-unit` / `make test-integration` / `make test-contract` / `cd ui && pnpm test` / `cd ui && pnpm playwright test` lanes — no separate test runner.

### AI Agent Execution Protocol

0. **Load context**: read [`architecture.md`](../../../../architecture.md), [`state.md`](../../../../state.md), [`feature_spec.md`](feature_spec.md), this plan.
1. **Read scope**: verify story outcome + endpoints + interfaces + DoD before implementing.
2. **Backend first**: domain → router wiring → unit → integration → contract.
3. **Run backend tests** (`make test-unit && make test-integration && make test-contract`).
4. **Frontend foundations**: defaults module + tests, glossary entries + parity test.
5. **Frontend wizard**: Step-4 wiring, Step-5 tri-state.
6. **Run frontend tests** (`cd ui && pnpm test`).
7. **E2E**: extend `studies.spec.ts` + add `studies-create-error.spec.ts`. Run `cd ui && pnpm playwright test`.
8. **Docs**: `ui-architecture.md`, `api-conventions.md`, `tutorial-first-study.md` (all in the same PR).
9. **Final review**: `make fmt && make lint && make typecheck && cd ui && pnpm lint && pnpm typecheck && pnpm prettier --check src package.json tsconfig.json eslint.config.mjs .prettierrc.json`.
10. **Attach evidence** in PR description.

---

## Epic 1 — Backend validation foundation

**Epic gate:** all 4 new test files green; new error codes (`SEARCH_SPACE_UNKNOWN_PARAM`, `SEARCH_SPACE_MISSING_DECLARED_PARAM`) return correct envelope shape; `scoring.py` metric+k token semantics locked under test.

### Story 1.1 — `validate_against_template` domain function + router wiring + tests

**Outcome:** `POST /api/v1/studies` rejects search-space param keys that don't match the selected template's `declared_params` (in either direction) at create time with two new machine-readable error codes (HTTP 400). Trial worker no longer fails on this class of drift.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/domain/test_search_space_validation.py` | Unit tests for `validate_against_template` — unknown-param raises, missing-declared-param raises, both-present ordering (unknown wins lexicographically), happy path returns None |
| `backend/tests/integration/test_studies_create_template_validation.py` | DB-backed integration tests asserting POST `/api/v1/studies` → 400 with the correct error code + envelope for unknown-param and missing-declared-param cases; verifies no `studies` row is created on failure |

**Modified files**

| File | Change |
|---|---|
| [`backend/app/domain/study/search_space.py`](../../../../backend/app/domain/study/search_space.py) | Add `UnknownSearchSpaceParamError(ValueError)` + `MissingDeclaredParamError(ValueError)` exception classes; add `validate_against_template(search_space: SearchSpace, declared_params: dict[str, str]) -> None` function below the existing `apply_search_space`; export both via module-level `__all__`. |
| [`backend/app/api/v1/studies.py`](../../../../backend/app/api/v1/studies.py) | In `create_study` handler, after template FK lookup at line 203 and before query_set lookup at line 204, call `validate_against_template(SearchSpace.model_validate(body.search_space), template.declared_params, template.name)` inside a try/except that translates the two new exceptions to `_err(400, "SEARCH_SPACE_UNKNOWN_PARAM" / "SEARCH_SPACE_MISSING_DECLARED_PARAM", str(exc), False)` (the exception's message already contains the spec's exact wording). |
| [`backend/tests/contract/test_studies_error_codes.py`](../../../../backend/tests/contract/test_studies_error_codes.py) | Add two new test cases asserting the **full envelope** for both new error codes, including the spec's exact message text: `"Param 'boost_titl' is not declared by template 'T1'. Declared params: ['boost_title']."` and `"Template 'T1' declares param 'fuzziness' but it is missing from the search space. Add it or remove from the template."` (per AC-5 + AC-6). |
| [`backend/tests/integration/test_studies_api.py`](../../../../backend/tests/integration/test_studies_api.py) | Spot-check: run the existing happy-path tests after wiring the new validation; no change required if happy path still passes (test fixture's `search_space` and `declared_params` already match). |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/studies` | Existing `CreateStudyRequest` shape ([`backend/app/api/v1/schemas.py:536-553`](../../../../backend/app/api/v1/schemas.py#L536-L553)) — unchanged. | `201` `StudyDetail` (unchanged) | Existing: `INVALID_SEARCH_SPACE` (400), `CLUSTER_NOT_FOUND` (404), `TEMPLATE_NOT_FOUND` (404), `QUERY_SET_NOT_FOUND` (404), `JUDGMENT_LIST_NOT_FOUND` (404), `VALIDATION_ERROR` (422). **NEW: `SEARCH_SPACE_UNKNOWN_PARAM` (400), `SEARCH_SPACE_MISSING_DECLARED_PARAM` (400)** — both with `retryable: false`. |

**Key interfaces**

The domain function takes `template_name` as a third argument so the exception classes can emit the spec's exact message format (per FR-2 / FR-3 / AC-5 / AC-6). The router passes `template.name` from the FK lookup row.

```python
# backend/app/domain/study/search_space.py

class UnknownSearchSpaceParamError(ValueError):
    """A search_space.params key is not in the template's declared_params.

    Message format (spec FR-2 exact text):
      "Param '{name}' is not declared by template '{template_name}'. Declared params: {sorted_declared_names}."
    """
    def __init__(self, param_name: str, template_name: str, declared_param_names: list[str]) -> None: ...


class MissingDeclaredParamError(ValueError):
    """A declared_params key is missing from the submitted search_space.params.

    Message format (spec FR-3 exact text):
      "Template '{template_name}' declares param '{name}' but it is missing from the search space. Add it or remove from the template."
    """
    def __init__(self, param_name: str, template_name: str) -> None: ...


def validate_against_template(
    search_space: SearchSpace,
    declared_params: dict[str, str],
    template_name: str,
) -> None:
    """Verify search_space.params keys match declared_params exactly.

    Ordering when both conditions apply:
      1. Unknown-param raised first (lexicographically smallest offender).
      2. Missing-declared-param raised only when no unknown params are present.

    Returns None on success; raises on first violation. `template_name` is required for the
    exact message format mandated by spec FR-2 / FR-3.
    """
```

**Pydantic schemas** — none new (request body is the existing `CreateStudyRequest`; error envelope is the existing `_err()` shape).

**Tasks**

1. Add the two exception classes + `validate_against_template` to `backend/app/domain/study/search_space.py`; update `__all__`.
2. Write `backend/tests/unit/domain/test_search_space_validation.py` with 4 test functions: `test_unknown_param_raises`, `test_missing_declared_raises`, `test_both_errors_unknown_wins`, `test_happy_path_returns_none`. Cover lexicographic ordering when multiple unknown params exist.
3. In `backend/app/api/v1/studies.py:create_study`, insert the validation call after line 203 (template FK resolution) and before line 204 (query_set FK lookup). Translate both new exceptions to `_err(400, "SEARCH_SPACE_UNKNOWN_PARAM" / "SEARCH_SPACE_MISSING_DECLARED_PARAM", str(exc), False)`.
4. Write `backend/tests/integration/test_studies_create_template_validation.py` — three test cases: unknown-param → 400 + correct envelope + no DB row; missing-declared → 400 + correct envelope + no DB row; both present → unknown-param wins.
5. Extend `backend/tests/contract/test_studies_error_codes.py` with response-envelope shape assertions for both new codes (behavior assertion, not OpenAPI enum membership — per spec §14 contract test note).
6. Run `make test-unit && make test-integration && make test-contract`.

**Definition of Done (DoD)**

- [ ] `validate_against_template` returns None for matching params; raises `UnknownSearchSpaceParamError` with sorted declared-names list; raises `MissingDeclaredParamError` for the lexicographically-smallest missing param when no unknowns are present. (AC-7 ordering rule.)
- [ ] `POST /api/v1/studies` with an unknown param key → HTTP 400, `error_code: SEARCH_SPACE_UNKNOWN_PARAM`, no `studies` row inserted. (AC-5)
- [ ] `POST /api/v1/studies` with a missing declared param → HTTP 400, `error_code: SEARCH_SPACE_MISSING_DECLARED_PARAM`. (AC-6)
- [ ] `POST /api/v1/studies` with both → returns `SEARCH_SPACE_UNKNOWN_PARAM`. (AC-7)
- [ ] Contract test asserts envelope shape for both codes.
- [ ] `make test-unit && make test-integration && make test-contract` all pass.

### Story 1.2 — Backend metric+k scoring-token unit test + K_REQUIRED contract test

**Outcome:** `backend/app/eval/scoring.py`'s metric-to-pytrec-eval-token mapper is asserted to treat each metric per its documented tier (required-k / optional-k / ignored-k). Locks the source-of-truth for frontend's `K_REQUIRED` / `K_IGNORED` parity tests (Story 3.2). Additionally, a new contract test exercises `POST /api/v1/studies` for each metric in `OBJECTIVE_METRIC_VALUES` with and without k — asserting backend's tier behavior so frontend predicates have a contract-tested counterpart (AC-13 backend half).

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/eval/test_scoring_metric_tokens.py` | Unit tests asserting the metric → pytrec_eval token function's behavior per metric per k-presence; references `scoring.py:32` as the source-of-truth comment to keep tests + comment in sync. |
| `backend/tests/contract/test_k_required_membership.py` | Contract test (spec AC-13 backend half): POSTs each of the 6 `OBJECTIVE_METRIC_VALUES` with and without `k=10`. Asserts: `ndcg`/`precision`/`recall` without k → 422 `VALIDATION_ERROR` (via FastAPI's `RequestValidationError` handler at `backend/app/api/errors.py:108`); same metrics with k=10 → 201; `map`/`mrr`/`err` both with and without k → 201. Surfaces drift between frontend `K_REQUIRED` and backend `_K_REQUIRED_METRICS` (`schemas.py:474`). |

**Modified files**

None. (The scoring module itself isn't changed — this story adds test coverage of existing behavior so that the frontend tier predicates have a backend-asserted contract to mirror against.)

**Key interfaces**

```python
# backend/tests/unit/eval/test_scoring_metric_tokens.py

# Import whichever function in backend/app/eval/scoring.py converts
# a (metric, k) tuple into a pytrec_eval-compatible token string.
# Implementation discovery: read scoring.py top-to-bottom, locate the
# mapper used by run_trial. Most likely: `metric_to_pytrec_token(metric: str, k: int | None) -> str`.

def test_required_k_metrics_token_with_k() -> None: ...
def test_required_k_metrics_token_missing_k_raises() -> None: ...
def test_map_with_k_returns_map_cut_token() -> None: ...
def test_map_without_k_returns_full_recall_token() -> None: ...
def test_ignored_k_metrics_token_identical_regardless_of_k() -> None: ...
```

**Tasks**

1. Read `backend/app/eval/scoring.py` end-to-end. Locate the metric → pytrec_eval token mapper (function used by `run_trial` to construct token strings for pytrec_eval). Identify the function's signature.
2. Write 5 unit test functions per the Key interfaces above. Each test asserts the mapping for one tier. Use parametrized fixtures over `OBJECTIVE_METRIC_VALUES`.
3. If the mapper does not currently exist as a standalone function (it may be inlined inside `run_trial`), extract it as part of this story — minimum signature change, preserve current behavior.
4. Write `backend/tests/contract/test_k_required_membership.py` per the new-files description above. Use the existing client fixture from sibling contract tests. Cover all 12 cells (6 metrics × {with k, without k}). Each cell asserts (status_code, envelope.error_code) per the matrix.
5. Run `make test-unit && make test-contract` to verify both new test files pass.

**Definition of Done (DoD)**

- [ ] Scoring-token unit test asserts: `ndcg`/`precision`/`recall` with `k=10` → `<metric>_cut_10`; without `k` → raises or returns a sentinel that `run_trial` rejects.
- [ ] Scoring-token unit test asserts: `map` with `k=10` → `map_cut_10`; without `k` → `map`.
- [ ] Scoring-token unit test asserts: `mrr` and `err` produce identical tokens regardless of k value (`recip_rank` and `err` or equivalent — actual token values verified by reading the mapper).
- [ ] (AC-14 backend half) Scoring-token unit test references `scoring.py:32` source-of-truth comment so future edits update both.
- [ ] (AC-13 backend half) `test_k_required_membership.py` covers all 12 cells and matches the expected matrix.
- [ ] `make test-unit && make test-contract` pass.

**Epic 1 gate**
- [ ] Stories 1.1 and 1.2 both DoD-complete.
- [ ] `make test-unit && make test-integration && make test-contract` all pass.
- [ ] Four new backend test files green: `test_search_space_validation.py`, `test_studies_create_template_validation.py`, `test_scoring_metric_tokens.py`, `test_k_required_membership.py`.

---

## Epic 2 — Frontend foundations

**Epic gate:** `search-space-defaults.ts` produces auto-fill output that round-trips through the backend `SearchSpace.model_validate` cleanly for every shape in the test fixture. All new glossary entries pass `glossary.test.ts`.

### Story 2.1 — `search-space-defaults.ts` module + cardinality TS port + tests

**Outcome:** A single TypeScript module exports a pure function that, given a template's `declared_params: dict[str, str]`, produces a starter `search_space` JSON whose every value is a valid `ParamSpec` and whose cardinality stays under the 10⁶ cap. The same module exports a TypeScript port of `estimate_cardinality()` that matches the backend's output character-for-character on the test fixture set.

**New files**

| File | Purpose |
|---|---|
| `ui/src/lib/search-space-defaults.ts` | Pure functions: `buildStarterSearchSpace(declared_params: Record<string, string>): SearchSpaceJson` and `estimateCardinality(space: SearchSpaceJson): number`. Plus the heuristic regex constants. Source-of-truth comment cites `backend/app/domain/study/search_space.py:132-151`. |
| `ui/src/__tests__/lib/search-space-defaults.test.ts` | Unit tests for every regex-match case (boost, tie_breaker, slop, fuzziness) + simple-form fallbacks (int, float, bool, string→__placeholder__) + fall-through default. |
| `ui/src/__tests__/lib/search-space-defaults.cardinality.test.ts` | Snapshot test asserting the TS `estimateCardinality` produces values on a fixture set of 8-10 search spaces matching hand-computed expected values. Includes the 10⁶ boundary case. |
| `backend/tests/unit/domain/test_search_space_cardinality_parity.py` | Mirror of the TS test: asserts `estimate_cardinality()` produces the **same** values for the same fixture set. Frozen as JSON at `backend/tests/_fixtures/search_space_cardinality_fixtures.json` (new). The two tests share the JSON fixture; any drift in either implementation causes one to fail and surface the divergence. |

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/enums.ts` | No changes. The module references `OBJECTIVE_METRIC_VALUES` only by symbol if at all. |

**Key interfaces**

```typescript
// ui/src/lib/search-space-defaults.ts

// The wire-format shape produced by buildStarterSearchSpace — matches
// backend SearchSpace exactly. Re-export from a shared schema or define inline.
export type ParamSpec =
  | { type: 'float'; low: number; high: number; log?: boolean }
  | { type: 'int'; low: number; high: number }
  | { type: 'categorical'; choices: (string | number | boolean)[] };

export type SearchSpaceJson = { params: Record<string, ParamSpec> };

/** Heuristic-driven starter space. Pure function; no IO, no async. */
export function buildStarterSearchSpace(
  declaredParams: Record<string, string>,
): SearchSpaceJson;

/**
 * TypeScript port of backend/app/domain/study/search_space.py:estimate_cardinality.
 * Float counted as 100; Int counted as high - low + 1; Categorical counted as len(choices).
 * Source-of-truth: backend/app/domain/study/search_space.py:132-151
 */
export function estimateCardinality(space: SearchSpaceJson): number;

/** The naming-convention regex table (exported for tests). */
export const HEURISTIC_RULES: ReadonlyArray<{ match: RegExp; spec: ParamSpec }>;
```

**Tasks**

1. Implement `buildStarterSearchSpace` and `estimateCardinality` per the heuristic table in spec §7 FR-1 and the cardinality math in `backend/app/domain/study/search_space.py:132-151`.
2. Write the regex match table as named exports so tests can assert each rule independently.
3. The `'string'` simple-form fallback emits `{type: 'categorical', choices: ['__placeholder__']}` — a degenerate single-choice ParamSpec the user must edit (per spec FR-1 + AC-1).
4. **Cap-aware logic:** after generating the candidate starter space, call `estimateCardinality(candidate)`. If > 1,000,000, fall back per the spec's priority-ordered rule (spec FR-1 "Cap-aware fallback"):
   - **Convert unmatched fall-through floats first** — params that hit the default `^.*$` rule (`{type: 'float', low: 0.0, high: 1.0}`) become `{type: 'int', low: 0, high: 5}` (contribution 100 → 6).
   - **Convert regex-matched floats only if still over cap** — `field_boosts/boost_*` and `tie_breaker/.*_weight` params keep their float shape unless absolutely necessary. Convert these last, in lexicographic order of param name, until cardinality ≤ 10⁶.
   - `fuzziness` (categorical) and `slop/min_should_match` (int) never convert — they don't contribute float weight.
   - The output **MUST** validate against `SearchSpace.model_validate` (cardinality ≤ 10⁶ guaranteed).
   - Emit `console.warn` whenever the fallback fires, naming which params were converted.
5. Create the fixture file at `backend/tests/_fixtures/search_space_cardinality_fixtures.json` listing 8-10 search spaces with hand-computed expected cardinality values. (Both the TS and Python tests consume this file.)
6. Write `search-space-defaults.test.ts` with one test per heuristic case + fall-through default + simple-form fallbacks + the placeholder sentinel for string-typed + cap-fallback test (a 5-float-param declared_params produces a starter with cardinality ≤ 10⁶).
7. Write `search-space-defaults.cardinality.test.ts` consuming the JSON fixture; asserts TS output matches each `expected` value.
8. Write `backend/tests/unit/domain/test_search_space_cardinality_parity.py` consuming the same JSON fixture; asserts Python `estimate_cardinality` output matches each `expected` value.
9. Add a top-of-file comment block citing the spec's FR-1 and the backend source-of-truth file/line.
10. Run `cd ui && pnpm test src/__tests__/lib/search-space-defaults && make test-unit`.

**Definition of Done (DoD)**

- [ ] `buildStarterSearchSpace({"boost_title": "float"})` returns `{params: {boost_title: {type: 'float', low: 0.5, high: 10.0, log: true}}}`. (AC-1 partial)
- [ ] `buildStarterSearchSpace({"fuzziness": "string"})` returns the categorical with `['AUTO', '0', '1', '2']`. (AC-1 partial)
- [ ] `buildStarterSearchSpace({"some_string_param": "string"})` returns the placeholder categorical. (Spec FR-1)
- [ ] `buildStarterSearchSpace` output for any declared_params dict always validates against backend `SearchSpace.model_validate` (cardinality ≤ 10⁶ guaranteed by cap-aware fallback).
- [ ] `estimateCardinality({params: {a: {type: 'float', low: 0, high: 1}}})` returns 100.
- [ ] Cardinality snapshot test verifies values for ≥ 8 shapes.
- [ ] Python parity test passes with identical expected values from the shared fixture.
- [ ] `cd ui && pnpm test` + `make test-unit` both pass.

### Story 2.2 — Glossary entries (4 new + 6 extended)

**Outcome:** Four new entries (`study.search_space` as `GlossaryEntryDual`; `.param_spec`, `.log`, `.cardinality` as `GlossaryEntryShort`) are present in `glossary.ts`. Six existing per-metric entries are extended with a tier-specific k-applicability clause. All entries comply with the existing length and jargon-prohibition rules.

**New files** — none.

**Modified files**

| File | Change |
|---|---|
| [`ui/src/lib/glossary.ts`](../../../../ui/src/lib/glossary.ts) | Add 4 new entries under a new comment block "Create-study Step-4 search space (chore_create_study_wizard_polish)"; extend the 6 existing per-metric entries (`study.metric.{ndcg,map,precision,recall,mrr,err}`) with the tier-specific clause appended to `short`. |
| [`ui/src/__tests__/lib/glossary.test.ts`](../../../../ui/src/__tests__/lib/glossary.test.ts) | No structural changes — existing length, jargon, and parity tests auto-cover the new keys. May need to update the entry-count snapshot if one exists. |

**Tasks**

1. Add the 4 new entries:
   - `study.search_space`: `GlossaryEntryDual` (both `short` and `long`). `short` ≤ 140 chars. `long` ≤ 800 chars, Markdown allowed — combines "what it is" + ParamSpec types + log-scale rule of thumb + 10⁶ cardinality cap into one body.
   - `study.search_space.param_spec`: `short` only. Distinguishes float / int / categorical.
   - `study.search_space.log`: `short` only. Log-scale rule of thumb ("use when high/low > 10").
   - `study.search_space.cardinality`: `short` only. The 10⁶ cap + estimation hint.
   - All 4 carry an `ariaLabel`.
2. Extend the 6 per-metric entries' `short` fields per spec FR-6:
   - `ndcg` / `precision` / `recall`: append `" Requires a top-k cutoff."`
   - `map`: append `" Top-k cutoff optional — set it for map@k, leave blank for full-recall MAP."` (Current entry must be tightened to fit 140-char budget.)
   - `mrr` / `err`: append `" Top-k cutoff is not used."`
3. Add a source-of-truth comment above the new entries block citing this chore's spec.
4. Run `cd ui && pnpm test src/__tests__/lib/glossary.test.ts` — the existing length, jargon, and parity tests catch regressions automatically.
5. If the glossary file has an entry-count snapshot test, regenerate it.

**Definition of Done (DoD)**

- [ ] All 4 new keys present in `glossary.ts` with the documented shapes.
- [ ] All 6 per-metric entries extended with the tier-specific clause; `study.metric.map` fits within 140 chars after extension.
- [ ] `glossary.test.ts` passes (length, no-backend-jargon, key parity all green). (AC-11)
- [ ] No new test files needed; existing tests auto-cover.

**Epic 2 gate**
- [ ] Stories 2.1 and 2.2 both DoD-complete.
- [ ] `cd ui && pnpm test` passes.

---

## Epic 3 — Wizard integration

**Epic gate:** Step 4 auto-fills from `declared_params` on entry; Step 4 rejects unknown / missing declared params client-side; Step 5 renders k field in the correct tier (required / optional / hidden) for each metric; component tests pass for all new behaviors.

### Story 3.1 — Step-4 auto-fill, tooltips, client-side validation, edge handling

**Outcome:** When the user advances to Step 4, the textarea is pre-filled with the auto-fill JSON for the selected template. Both glossary surfaces (`<InfoTooltip>` headline + `<HelpPopover>` details) are rendered. Unknown / missing declared params trigger an inline error on Next-click that mirrors the server-side rejection. Zero-declared-params templates are blocked at the Step-3 → Step-4 transition. Template-fetch failures (5xx / network) allow the user to hand-write and rely on server-side validation.

**New files**

| File | Purpose |
|---|---|
| `ui/src/__tests__/components/studies/create-study-modal.auto-fill.test.tsx` | Auto-fill triggers on Step-3 → Step-4 transition; respects pre-existing user edits; replaces empty textarea unconditionally. |
| `ui/src/__tests__/components/studies/create-study-modal.auto-fill.undo.test.tsx` | Template-change replacement + toast Undo restoration within 10s. |
| `ui/src/__tests__/components/studies/create-study-modal.client-validation.test.tsx` | Unknown-param + missing-declared-param surface inline error on Next-click without hitting the network. |
| `ui/src/__tests__/components/studies/create-study-modal.zero-declared.test.tsx` | Zero-declared-params template blocks Step-3 → Step-4 transition. |
| `ui/src/__tests__/components/studies/create-study-modal.template-fetch-error.test.tsx` | Network-failure path: textarea stays empty, Retry button visible, Next remains enabled, server-validation safety net documented. |

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) | (1) Add `<InfoTooltip glossaryKey="study.search_space" />` adjacent to the Step-4 "Search space (JSON)" label at line 331; (2) add `<HelpPopover glossaryKey="study.search_space" />` below the textarea at line ~336; (3) wire the auto-fill effect (keyed on `template_id` + previous textarea content); (4) wire the toast+Undo flow for template-change replacement; (5) wire the client-side `validate_against_template` mirror that runs on Next-click in Step 4; (6) wire the zero-declared-params block at the Step-3 → Step-4 transition; (7) wire the template-fetch-error inline notice. |
| `ui/src/components/studies/create-study-modal.tsx` (state) | Add a new state slice for the auto-fill signature tracking + the pending Undo content (10s ttl) + the template-fetch error state. |

**Endpoints** — none new. (Existing `GET /api/v1/query-templates/{id}` is invoked via TanStack Query; the contract is unchanged.)

**Key interfaces**

```tsx
// ui/src/components/studies/create-study-modal.tsx (additions)

import { buildStarterSearchSpace } from '@/lib/search-space-defaults';
import { InfoTooltip } from '@/components/common/info-tooltip';
import { HelpPopover } from '@/components/common/help-popover';

// New state slices (additions to existing form state):
const [autoFillSignatures, setAutoFillSignatures] = useState<ReadonlySet<string>>(() => new Set());
// — Set of all previously-generated auto-fill content strings. Matches spec FR-1's
// "exactly matches a previously-generated auto-fill" wording — covers the case where a user
// generates T1's default, switches to T2 (auto-filled), restores T1's default by re-selecting T1,
// then switches to T3 (should auto-fill T3 without an Undo toast, because the T1 content was
// previously generated, not user-edited).
const [pendingUndo, setPendingUndo] = useState<{ priorText: string; timeoutId: number } | null>(null);
// — Set when an auto-fill replacement of edited content is in progress; cleared after 10s.
const [templateFetchError, setTemplateFetchError] = useState<'404' | 'transient' | null>(null);
// — Surface for the template-detail GET error states (404 bumps back to Step 3; transient stays on Step 4 with Retry).
```

**UI element inventory** (Step 4 changes only)

| Element | Current state | New state | Source |
|---|---|---|---|
| Step-4 `<Label htmlFor="cs-space">Search space (JSON)</Label>` | Plain label, no help icon | Label + adjacent `<InfoTooltip glossaryKey="study.search_space" />` | FR-7 |
| Step-4 `<Textarea id="cs-space">` content | Empty `''` on first render; user-typed otherwise | Pre-filled with `buildStarterSearchSpace(template.declared_params)` JSON on Step-3 → Step-4 transition (when empty or matches a prior auto-fill signature) | FR-1, AC-1, AC-2 |
| (NEW) `<HelpPopover glossaryKey="study.search_space" />` below textarea | Does not exist | New help-popover trigger icon; reveals `long` field of `study.search_space` (Markdown body) on click | FR-7 |
| (NEW) Inline error `<p role="alert">` below textarea | Does not exist | Visible when client-side `validate_against_template` mirror finds an unknown or missing declared param on Next-click | FR-2, FR-3, AC-4 |
| (NEW) Loading notice "Loading template…" inline | Does not exist | Visible when GET `/api/v1/query-templates/{id}` is in flight | §11 edge flow |
| (NEW) Retry inline notice for transient errors | Does not exist | Visible when template fetch fails with non-404 error; includes Retry button | §11 edge flow |
| (NEW) Zero-declared-params inline error on Step 3 Next button | Does not exist | Visible when selected template has `Object.keys(declared_params).length === 0`; Step-3 Next is disabled | §11 edge flow |

**State dependency analysis**

```
State being added: autoFillSignatures, pendingUndo, templateFetchError, useQueryTemplate(template_id) cache
Referenced by:
  - The form's useEffect (keyed on template_id) — sets autoFillSignatures
  - The Step-4 `<Textarea>` register — reads form.search_space_text; doesn't need to know about autoFillSignatures directly
  - The Step-3 Next button — reads templateFetchError + declared_params length to gate transition
  - The Step-4 Next button — reads form.search_space_text + client-side validator + templateFetchError
  - The Undo toast handler — reads pendingUndo + clears the timeout
```

**Tasks**

1. Read [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) end-to-end (currently ~470 lines per the spec audit) to understand current state + structure before editing.
2. Add imports: `buildStarterSearchSpace`, `estimateCardinality` from `@/lib/search-space-defaults`; `InfoTooltip`, `HelpPopover` from `@/components/common/*`.
3. Add the three new state slices (`autoFillSignatures`, `pendingUndo`, `templateFetchError`).
4. Wire `useQueryTemplate(template_id)` (or hand-roll a TanStack Query call matching the existing pattern) to fetch the full template body when `template_id` changes; cache the response for the modal session.
5. Add a `useEffect` keyed on `[templateBody]`:
   - When `templateBody` is fetched AND `Object.keys(templateBody.declared_params).length === 0`: surface the zero-declared inline error on Step 3 (Next disabled). (Note: `declared_params` is a JS object/dict, not an array — must use `Object.keys(...).length`, not `.length`.)
   - When `Object.keys(templateBody.declared_params).length >= 1` AND (textarea is empty OR textarea content ∈ `autoFillSignatures`): replace textarea with `buildStarterSearchSpace(declared_params)` JSON; add the new JSON to `autoFillSignatures`. No toast.
   - When textarea has user content (∉ `autoFillSignatures`) AND `templateBody` reference changed (i.e., template_id changed and TanStack Query fetched fresh data): replace immediately, add the new JSON to `autoFillSignatures`, show toast with Undo action + 10s timeout, set `pendingUndo`.
6. Wire the Step-3 Next button's `disabled` predicate: true when `templateBody && Object.keys(templateBody.declared_params).length === 0` (zero-declared block).
7. Wire the **404 recovery flow**: on `templateBody` fetch returning 404 (template deleted between Step 3 and Step 4 OR pre-Step-4 entry), show a sonner toast `"The selected template is no longer available. Pick another."` and call `setStep(2)` to bump the user back to Step 3. The Step-3 EntitySelect will re-fetch the template list on focus.
8. Wire the **transient (5xx / network) recovery flow**: on non-404 fetch failure, set `templateFetchError = 'transient'`; Step 4 renders with empty textarea + an inline notice + a Retry button that re-fires the query. Step-4 Next remains enabled (server-side validation is the safety net).
9. Wire the Step-4 Next button's `onClick` AND each textarea blur (from the start — no Next-click prerequisite, per spec FR-2 "on blur or on Next-click"): run client-side `validate_against_template(JSON.parse(search_space_text), templateBody.declared_params, templateBody.name)`; on error, set an inline-error state; on success, clear the error. Only Next-click advances to Step 5; blur only updates the inline error visibility. (Note: this is more aggressive than `mode: 'onTouched'` — explicitly spec-mandated.)
10. Wire the **`__placeholder__` non-blocking warning**: walk the parsed `search_space.params` values; if any categorical's `choices` contains `'__placeholder__'`, render a separate amber `<p>` warning under the textarea: `"Replace the '__placeholder__' value(s) before submitting — they are starter defaults for params with no inferable type."` This is non-blocking — Next-click still advances. The warning persists alongside any blocking inline error.
11. Add `<InfoTooltip glossaryKey="study.search_space" />` adjacent to the Step-4 label at line 331.
12. Add `<HelpPopover glossaryKey="study.search_space" />` below the textarea.
13. Write the 5 new component test files per the New files table. Each covers one scenario; use React Testing Library + `vi.mock` for `@/components/ui/select` (the shared `mockShadcnSelect` helper from `ui/src/__tests__/helpers/shadcn-select-mock.tsx` per PR #153). Add one extra test: `__placeholder__` warning renders when present in a categorical choices.
14. Run `cd ui && pnpm test src/__tests__/components/studies/create-study-modal`.

**Definition of Done (DoD)**

- [ ] Step-3 → Step-4 transition pre-fills the textarea with auto-fill JSON for templates with ≥1 declared param. (AC-1)
- [ ] User-edited content is not silently overwritten; template change triggers immediate replacement + toast with Undo for 10s. (AC-2, AC-3)
- [ ] Zero-declared-params template blocks Step-3 → Step-4 transition with inline error. (§11 edge)
- [ ] Client-side `validate_against_template` mirror surfaces inline error on Next-click AND on every blur (from the start) for unknown / missing params. (AC-4, FR-2 blur path)
- [ ] `__placeholder__` non-blocking warning renders when present in any categorical's choices. (Spec FR-1)
- [ ] Step-4 `<InfoTooltip>` opens on hover/focus with `study.search_space.short` content. (AC-12)
- [ ] Step-4 `<HelpPopover>` opens on click with `study.search_space.long` content.
- [ ] 404 template fetch shows toast + bumps user back to Step 3. (§11 edge)
- [ ] Transient (5xx / network) template fetch shows Retry; Next remains enabled (server-side validation is safety net). (§11 edge)
- [ ] `cd ui && pnpm test` passes for all 5 new test files + the placeholder-warning test added in Task 13.

### Story 3.2 — Step-5 metric+k tri-state rendering + `K_IGNORED` + parity tests

**Outcome:** Step 5's k field renders as required / optional / hidden according to the metric's k-tier. `K_IGNORED = {mrr, err}` is added as a new frontend predicate. Form state for k clears when switching to an ignored-k metric, preserves when switching between required and optional tiers. Frontend parity tests assert `K_REQUIRED` and `K_IGNORED` match their backend source-of-truth.

**New files**

| File | Purpose |
|---|---|
| `ui/src/__tests__/components/studies/create-study-modal.metric-k.test.tsx` | Tests for required (sub-label), optional (sub-label + clearable "—" entry), ignored (hidden + caption); k clearing on `K_IGNORED` transition; k preservation on required↔optional transition. |
| `ui/src/__tests__/components/studies/k-required.test.ts` | Asserts `K_REQUIRED` equals `new Set(['ndcg', 'precision', 'recall'])`. Source-of-truth comment cites `backend/app/api/v1/schemas.py:474`. (AC-13 frontend half) |
| `ui/src/__tests__/components/studies/k-ignored.test.ts` | Asserts `K_IGNORED` equals `new Set(['mrr', 'err'])`. Source-of-truth comment cites `backend/app/eval/scoring.py:32` + `backend/tests/unit/eval/test_scoring_metric_tokens.py`. (AC-14 frontend half) |

**Modified files**

| File | Change |
|---|---|
| [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx) | (1) Add `K_IGNORED: ReadonlySet<ObjectiveMetric> = new Set(['mrr', 'err'])` adjacent to `K_REQUIRED` at line 46. Include source-of-truth comment citing `backend/app/eval/scoring.py:32`. (2) Replace the `placeholder={K_REQUIRED.has(metric) ? 'required' : 'optional'}` at line 377 with tri-state rendering: required = `<Select>` + sub-label `"Top-k cutoff (required for {metric.toUpperCase()})"`; optional = `<Select>` + sub-label `"Top-k cutoff (optional — leave empty for full-recall {metric.toUpperCase()})"` + clearable "—" entry; ignored = no `<Select>`, replacement `<p>` caption `"{metric.toUpperCase()} evaluates the full ranked list — no cutoff used."`. (3) On metric change: if new metric ∈ `K_IGNORED`, clear form state for `k`. |

**Key interfaces**

```tsx
// ui/src/components/studies/create-study-modal.tsx (additions)

// Source-of-truth: backend/app/api/v1/schemas.py:474 _K_REQUIRED_METRICS
// Exported for parity tests.
export const K_REQUIRED: ReadonlySet<ObjectiveMetric> = new Set(['ndcg', 'precision', 'recall']);

// Source-of-truth: backend/app/eval/scoring.py:32 (metric → pytrec_eval token mapper).
// Asserted by backend/tests/unit/eval/test_scoring_metric_tokens.py and the K_REQUIRED
// membership contract test at backend/tests/contract/test_k_required_membership.py.
// Exported for parity tests.
export const K_IGNORED: ReadonlySet<ObjectiveMetric> = new Set(['mrr', 'err']);

// Sentinel value used by the optional-k "—" SelectItem (Radix SelectItem cannot have value="").
const K_CLEAR_SENTINEL = '__clear__' as const;

type KTier = 'required' | 'optional' | 'ignored';
export function kTier(metric: ObjectiveMetric): KTier {
  if (K_REQUIRED.has(metric)) return 'required';
  if (K_IGNORED.has(metric)) return 'ignored';
  return 'optional';
}
```

**UI element inventory** (Step 5 changes only)

| Element | Current state | New state | Source |
|---|---|---|---|
| k `<Select>` placeholder | `K_REQUIRED.has(metric) ? 'required' : 'optional'` | Removed in favor of explicit sub-label | FR-4 |
| (NEW) Sub-label below k `<Select>` | Does not exist | `"Top-k cutoff (required for {metric.toUpperCase()})"` when required tier; `"Top-k cutoff (optional — leave empty for full-recall {metric.toUpperCase()})"` when optional tier; absent when ignored tier | FR-4, AC-8, AC-9a |
| (NEW) Clearable "—" option in k `<Select>` | Does not exist | Visible only when in optional tier; selecting it sets form state for k to `undefined` | FR-4, AC-9a |
| (NEW) Replacement caption `<p>` for ignored tier | Does not exist | `"{metric.toUpperCase()} evaluates the full ranked list — no cutoff used."` rendered in place of the k `<Select>` when in ignored tier | FR-4, AC-9b |
| k form state behavior on metric change | k retained regardless | k cleared when new metric ∈ `K_IGNORED`; preserved otherwise | FR-4, AC-10a, AC-10b |

**Enumerated value contracts**

| Frontend constant | Wire values | Backend source-of-truth | Source comment required |
|---|---|---|---|
| `K_REQUIRED` | `'ndcg'`, `'precision'`, `'recall'` | `backend/app/api/v1/schemas.py:474` (`_K_REQUIRED_METRICS: frozenset`) | `// Source-of-truth: backend/app/api/v1/schemas.py:474 _K_REQUIRED_METRICS` |
| `K_IGNORED` | `'mrr'`, `'err'` | `backend/app/eval/scoring.py:32` (comment block + the metric token mapper) | `// Source-of-truth: backend/app/eval/scoring.py:32 (metric → pytrec_eval token mapper). Asserted by backend/tests/unit/eval/test_scoring_metric_tokens.py.` |
| metric `<Select>` options | All 6 of `OBJECTIVE_METRIC_VALUES` (unchanged) | `backend/app/api/v1/schemas.py:167` (`ObjectiveMetric = Literal[...]`) | Existing comment at `enums.ts:65` (unchanged) |
| k `<Select>` options | All 7 of `OBJECTIVE_K_VALUES` (unchanged) | `backend/app/api/v1/schemas.py:170` (`ObjectiveK = Literal[...]`) | Existing comment at `enums.ts:77` (unchanged) |

**Tasks**

1. Add `K_IGNORED` constant adjacent to `K_REQUIRED` at line 46 with source-of-truth comment.
2. Add helper `kTier(metric)` returning the tier string.
3. Refactor the k field section of Step 5 (currently lines ~366-391) into a conditional render based on `kTier(metric)`:
   - `required`: `<Select>` + sub-label.
   - `optional`: `<Select>` + sub-label + add a clearable "—" SelectItem at top of options.
   - `ignored`: `<p>` caption only.
4. Hook up the `onValueChange` for the metric `<Select>` to clear `k` form state when new metric ∈ `K_IGNORED`. (Preserve in all other cases.)
5. Write `k-required.test.ts` — single test: `expect(K_REQUIRED).toEqual(new Set(['ndcg', 'precision', 'recall']))`.
6. Write `k-ignored.test.ts` — single test: `expect(K_IGNORED).toEqual(new Set(['mrr', 'err']))`.
7. Write `create-study-modal.metric-k.test.tsx` with 5 cases: required-tier rendering (ndcg), optional-tier rendering (map) with clearable "—", ignored-tier rendering (mrr) showing caption + no k Select, k cleared on required→ignored transition, k preserved on required→optional transition.
8. Run `cd ui && pnpm test src/__tests__/components/studies/`.

**Definition of Done (DoD)**

- [ ] `kTier('ndcg') === 'required'`; `kTier('map') === 'optional'`; `kTier('mrr') === 'ignored'`. (AC-8, AC-9a, AC-9b)
- [ ] Step 5 with metric=`ndcg` → k `<Select>` visible + sub-label "Top-k cutoff (required for NDCG)". (AC-8)
- [ ] Step 5 with metric=`map` → k `<Select>` visible + sub-label "Top-k cutoff (optional — leave empty for full-recall MAP)" + clearable "—" entry. (AC-9a)
- [ ] Step 5 with metric=`mrr` → k `<Select>` not in DOM; caption "MRR evaluates the full ranked list — no cutoff used." visible. (AC-9b)
- [ ] Switching `ndcg` (k=10) → `mrr` clears k to undefined. (AC-10a)
- [ ] Switching `ndcg` (k=10) → `map` preserves k=10. (AC-10b)
- [ ] `K_REQUIRED.test.ts` passes. (AC-13 frontend half)
- [ ] `K_IGNORED.test.ts` passes. (AC-14 frontend half)
- [ ] `cd ui && pnpm test` passes.

**Epic 3 gate**
- [ ] Stories 3.1 and 3.2 both DoD-complete.
- [ ] `cd ui && pnpm test` passes overall.

---

## Epic 4 — E2E + documentation

**Epic gate:** new E2E specs run against the real backend (no `page.route()`) and cover the happy path + a server-side error path. All cited doc files updated to reflect the new behavior.

### Story 4.1 — E2E coverage + documentation updates

**Outcome:** Existing `studies.spec.ts` happy-path is extended to assert Step-4 auto-fill content. A new `studies-create-validation.spec.ts` E2E exercises the **client-side** validation surface (real browser interaction; no `page.route()` mocks). The **server-side** path is already covered by the backend contract tests from Stories 1.1 and 1.2 — an E2E test would have to disable the client-side validator to reach it, which would require either `page.route()` mocking (forbidden by spec §14) or a deliberate template-fetch-failure setup that isn't a stable test surface. `docs/01_architecture/ui-architecture.md` and `docs/01_architecture/api-conventions.md` are updated with the new glossary keys, the two new error codes, and the new `K_IGNORED` predicate. `docs/08_guides/tutorial-first-study.md` removes the verbatim search-space paste block. `state.md` gains a "Just shipped" entry on PR merge.

**New files**

| File | Purpose |
|---|---|
| `ui/tests/e2e/studies-create-validation.spec.ts` | E2E test against real backend: walk Steps 1-3 normally; on Step 4 corrupt the auto-fill with a typo; click Next; assert the inline error renders with the correct message format (asserts the client-side validator works end-to-end — the same message format the server would return, so the message-string assertion doubles as a contract test for message text consistency). |

**Modified files**

| File | Change |
|---|---|
| [`ui/tests/e2e/studies.spec.ts`](../../../../ui/tests/e2e/studies.spec.ts) | Extend the existing happy-path test ("create a study") to assert Step-4 textarea content matches the expected auto-fill JSON after Step-3 → Step-4 transition. |
| [`docs/01_architecture/ui-architecture.md`](../../../01_architecture/ui-architecture.md) | Extend "Glossary keys (canonical)" section with the four new `study.search_space.*` keys + a one-line note that Step-4 auto-fill exists. Mention the dual InfoTooltip + HelpPopover wiring at the parent key. |
| [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) | Append the two new error codes (`SEARCH_SPACE_UNKNOWN_PARAM`, `SEARCH_SPACE_MISSING_DECLARED_PARAM`) to the canonical error-code catalog table. |
| [`docs/08_guides/tutorial-first-study.md`](../../../08_guides/tutorial-first-study.md) | In Step 7 (template creation), remove the verbatim search-space paste block; replace with "the wizard will auto-fill Step 4 once you've picked the template." Keep the declared-params markdown table as-is — it remains useful as a reference. |
| [`state.md`](../../../../state.md) | On PR merge, add a "Just shipped" entry summarizing the chore: 4 surfaces (Step-4 auto-fill, search-space template validation, glossary entries, Step-5 tri-state metric+k); 2 new error codes; new frontend `K_IGNORED` predicate; no migration. |

**E2E test structure** (real-backend, no `page.route()` per spec §14)

```typescript
// ui/tests/e2e/studies-create-validation.spec.ts
import { test, expect } from '@playwright/test';
import { seedCluster, seedQueryTemplate, seedQuerySet, seedJudgmentList } from './helpers/seed';

test('Step-4 client-side validation surfaces inline unknown-param error', async ({ page, request }) => {
  // Setup via API helpers (real backend) — declared_params has one key: boost_title
  const cluster = await seedCluster(request);
  const template = await seedQueryTemplate(request, { declared_params: { boost_title: 'float' } });
  const querySet = await seedQuerySet(request, { cluster_id: cluster.id });
  const judgmentList = await seedJudgmentList(request, { query_set_id: querySet.id });

  // Browser interaction
  await page.goto('/studies');
  await page.getByRole('button', { name: 'New study' }).click();
  // ... walk Steps 1-3 via page interactions, selecting the seeded entities ...

  // Step 4: corrupt the auto-fill with a typo (browser interaction, not API)
  await page.getByTestId('cs-search-space').fill(
    JSON.stringify({ params: { boost_titl: { type: 'float', low: 0.5, high: 10.0, log: true } } }),
  );
  await page.getByRole('button', { name: 'Next' }).click();

  // Assert browser-visible behavior: inline error renders with the message format
  // matching the server-side error (proves client-side validator is correctly mirroring).
  await expect(page.getByRole('alert')).toContainText(
    "Param 'boost_titl' is not declared",
  );
  // Verify no transition to Step 5 occurred
  await expect(page.getByTestId('step-4')).toBeVisible();
  await expect(page.getByTestId('step-5')).not.toBeVisible();
});
```

**Note on server-side coverage:** the backend contract test `test_studies_error_codes.py` (Story 1.1) already asserts the server returns the documented envelope for `SEARCH_SPACE_UNKNOWN_PARAM` when POSTed directly. The E2E test above asserts the *client-side mirror* produces the *same message format* via real browser interaction. Together they prove the contract holds in both layers.

**Tasks**

1. Read existing `ui/tests/e2e/studies.spec.ts` to identify the happy-path test and its current assertions.
2. Extend the happy-path test with a new assertion after Step-3 → Step-4: `await expect(page.getByTestId('cs-search-space')).toHaveValue(expectedAutoFillJsonString)`.
3. Write `studies-create-validation.spec.ts` per the structure above. Use existing seed helpers from `ui/tests/e2e/helpers/seed.ts` (or whatever the canonical helper file is — discovery task: read `ui/tests/e2e/helpers/`).
4. Update `docs/01_architecture/ui-architecture.md` with the new glossary keys + the dual-tooltip pattern note. Cite the chore's spec file in the section header.
5. Update `docs/01_architecture/api-conventions.md` with the two new error codes in the catalog table.
6. Update `docs/08_guides/tutorial-first-study.md` Step 7 — replace the verbatim paste block with the "wizard auto-fills" instruction.
7. Run `cd ui && pnpm playwright test studies.spec.ts studies-create-validation.spec.ts` (requires running stack).
8. Visual smoke: run the modal locally (`docker compose stop ui && cd ui && pnpm dev`), click through the create-study flow, verify auto-fill content matches expected.
9. On PR merge: add a "Just shipped" entry to `state.md` summarizing the 4 surfaces shipped.

**Definition of Done (DoD)**

- [ ] `studies.spec.ts` happy-path asserts Step-4 textarea content matches expected auto-fill JSON.
- [ ] `studies-create-validation.spec.ts` passes against real backend; uses `page` for interactions, `request` only for setup. (Spec §14 E2E rule.)
- [ ] `docs/01_architecture/ui-architecture.md` mentions all 4 new glossary keys + the dual-tooltip pattern.
- [ ] `docs/01_architecture/api-conventions.md` catalog table includes both new error codes.
- [ ] `docs/08_guides/tutorial-first-study.md` Step 7 no longer includes the verbatim paste block.
- [ ] `state.md` "Just shipped" entry added on PR merge.
- [ ] `cd ui && pnpm playwright test` passes.

**Epic 4 gate**
- [ ] Story 4.1 DoD-complete.
- [ ] New E2E specs run against the real backend (no `page.route()`) and cover the happy path + client-side validation. Server-side error display path is covered by backend contract tests (`test_studies_error_codes.py`, `test_k_required_membership.py`) per spec §14 + §19 decision log; not part of this gate.
- [ ] All documentation updates merged.
- [ ] Final visual smoke verified locally.

---

## UI Guidance (required for frontend-facing work)

### Reference: current component structure

**File:** [`ui/src/components/studies/create-study-modal.tsx`](../../../../ui/src/components/studies/create-study-modal.tsx)

- Total lines: ~470 (read end-to-end before editing; line numbers below may drift ±5).
- Section structure:
  - Imports + constants (lines 1-50) — includes `K_REQUIRED` at line 46.
  - Form type + defaults (lines 50-110).
  - Component body + form setup + state (lines 110-200).
  - Step rendering — JSX guarded by `step === N` conditionals (lines 200-470).
- Key insertion points:
  - **Line 46 (after `K_REQUIRED`)**: insert `K_IGNORED` + source-of-truth comment.
  - **Line ~110 (after form defaults block)**: insert the three new state slices (`autoFillSignatures`, `pendingUndo`, `templateFetchError`).
  - **Line 295-340 (`step === 2` block — Step 3 template selection)**: extend with `useQueryTemplate` fetch and Next-button gating.
  - **Line 320-340 (`step === 3` block — Step 4 search space)**: insert `<InfoTooltip>` adjacent to label at line 331; insert `<HelpPopover>` below textarea at line ~336; insert inline-error `<p role="alert">` below textarea.
  - **Line 366-391 (`step === 4` block — k field)**: refactor to tri-state.

### Analogous markup patterns

**Pattern A: InfoTooltip adjacent to a form label (from `create-study-modal.tsx:309-310` — Step 3 template label):**

```tsx
{/* From create-study-modal.tsx Step 3 template label */}
<div className="flex items-center gap-1">
  <Label htmlFor="cs-tpl">Query template (filtered by engine)</Label>
  <InfoTooltip glossaryKey="study.template" />
</div>
```

Adapt to Step 4 (replace `study.template` → `study.search_space`, `cs-tpl` → `cs-space`, label text → "Search space (JSON)").

**Pattern B: HelpPopover below content (from the `feat_contextual_help` shipped placements — `create-study-modal.tsx`):**

```tsx
{/* Adjust to the actual HelpPopover usage shape; verify by reading help-popover.tsx:29 */}
<div className="mt-1.5">
  <HelpPopover glossaryKey="study.search_space" />
</div>
```

(Note: `HelpPopover` is currently used in `digest-panel.tsx` per PR #122 — read that file for the canonical placement pattern if `create-study-modal.tsx` doesn't already use it.)

**Pattern C: Inline alert role for client-side validation errors (from form-validation patterns in `create-study-modal.tsx`):**

```tsx
{searchSpaceError && (
  <p
    role="alert"
    aria-live="polite"
    className="text-sm text-destructive"
    data-testid="cs-search-space-error"
  >
    {searchSpaceError}
  </p>
)}
```

**Pattern D: Sonner toast with action (project-wide toast pattern — check `ui/src/lib/toast.ts` or callers of `toast(...)` in components):**

```tsx
import { toast } from 'sonner';

const handleTemplateChangeReplacement = (priorText: string, newText: string) => {
  form.setValue('search_space_text', newText);
  toast('Replaced your Step-4 content with defaults for the new template.', {
    duration: 10_000,
    action: {
      label: 'Undo',
      onClick: () => form.setValue('search_space_text', priorText),
    },
  });
};
```

**Pattern E: Conditional rendering based on metric tier (Step 5 refactor):**

Note on the `__clear__` sentinel: Radix `<SelectItem>` rejects empty string values (`Select.Item must have a value prop that is not an empty string`). Use a non-empty sentinel value (`__clear__`) for the "—" entry and translate to `undefined` in `onValueChange`.

```tsx
{(() => {
  const tier = kTier(metric);
  if (tier === 'ignored') {
    return (
      <div className="space-y-1.5">
        <p className="text-sm text-muted-foreground" data-testid="cs-k-ignored-caption">
          {metric.toUpperCase()} evaluates the full ranked list — no cutoff used.
        </p>
      </div>
    );
  }
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1">
        <Label htmlFor="cs-k">k</Label>
        <InfoTooltip glossaryKey="study.k" />
      </div>
      <Select
        value={values.k != null ? String(values.k) : undefined}
        onValueChange={(v) => {
          if (v === K_CLEAR_SENTINEL) {
            form.setValue('k', undefined);
          } else {
            form.setValue('k', Number(v) as ObjectiveK);
          }
        }}
      >
        <SelectTrigger id="cs-k">
          <SelectValue placeholder={tier === 'required' ? 'required' : 'select (optional)…'} />
        </SelectTrigger>
        <SelectContent>
          {tier === 'optional' && (
            <SelectItem key="clear" value={K_CLEAR_SENTINEL} data-testid="cs-k-clear">
              — (full recall)
            </SelectItem>
          )}
          {OBJECTIVE_K_VALUES.map((k) => (
            <SelectItem key={k} value={String(k)}>
              {k}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <p className="text-xs text-muted-foreground" data-testid="cs-k-sublabel">
        {tier === 'required'
          ? `Top-k cutoff (required for ${metric.toUpperCase()})`
          : `Top-k cutoff (optional — leave empty for full-recall ${metric.toUpperCase()})`}
      </p>
    </div>
  );
})()}
```

### Layout and structure

- Step 4 layout unchanged structurally — adds tooltip icon next to label, HelpPopover below textarea, inline alert below textarea on validation error.
- Step 5 k-field layout unchanged for required/optional tiers; for ignored tier the `<Select>` is replaced inline with a `<p>` — keeps the grid-column shape so the 3-column metric/k/direction layout doesn't shift.
- Responsive behavior unchanged.

### Confirmation/modal dialog pattern

No new modals or confirmation dialogs. The Undo flow uses an existing sonner toast pattern (Pattern D above).

### Visual consistency table

| New UI element | CSS class / pattern source |
|---|---|
| Step-4 `<InfoTooltip>` | `<InfoTooltip>` component (Radix-backed, from `feat_contextual_help` PR #122). No new CSS. |
| Step-4 `<HelpPopover>` | `<HelpPopover>` component (Radix popover + `react-markdown`, from same PR). No new CSS. |
| Step-4 inline alert | `text-sm text-destructive` (existing shadcn destructive palette; matches existing form error patterns). |
| Step-5 sub-label | `text-xs text-muted-foreground` (existing shadcn helper-text pattern). |
| Step-5 ignored-tier caption | `text-sm text-muted-foreground` (matches the Step-1 helper-text near the target input). |
| Sonner toast with Undo | Existing `toast()` + `action` API (sonner; in use elsewhere — search `toast(` for current callers). |

### Component composition

- All new UI is **inline** in `create-study-modal.tsx`. No new components extracted. Rationale: this chore is scoped to wizard polish; extraction (e.g., a per-param row component for a builder UI) belongs to `feat_create_study_search_space_builder`.

### Interaction behavior table

| User action | Frontend behavior | API call |
|---|---|---|
| Reach Step 3 (template select) | `useQueryTemplate(template_id)` fetch triggered; cached for modal session | `GET /api/v1/query-templates/{id}` |
| Click Next on Step 3 (template with ≥1 declared param) | Advance to Step 4; useEffect runs auto-fill into textarea | — |
| Click Next on Step 3 (template with 0 declared params) | Inline error on Next button; transition blocked | — |
| Reach Step 4 (textarea pre-filled) | No interaction | — |
| Change template at Step 3 (after editing Step 4) | Step 4 textarea replaced immediately; sonner toast with Undo action (10s) | `GET /api/v1/query-templates/{newId}` |
| Click Undo in toast | Restore prior textarea content; toast auto-dismisses | — |
| Click Next on Step 4 (valid content) | Advance to Step 5 | — |
| Click Next on Step 4 (invalid: unknown param) | Inline error renders below textarea; transition blocked | — |
| Click Next on Step 4 (invalid: missing declared param) | Inline error renders; transition blocked | — |
| Pick metric `ndcg` on Step 5 | k `<Select>` visible + required sub-label | — |
| Pick metric `map` on Step 5 | k `<Select>` visible + optional sub-label + "—" entry; k value preserved if previously set | — |
| Pick metric `mrr` on Step 5 | k `<Select>` removed from DOM; caption rendered; form state for k cleared to undefined | — |
| Submit Step 5 (form complete) | Existing POST `/api/v1/studies` flow with new backend validation | `POST /api/v1/studies` |

### Handler function patterns

```typescript
// ui/src/components/studies/create-study-modal.tsx (additions)

// Effect: auto-fill Step 4 when template body lands AND textarea is empty/signature
useEffect(() => {
  if (!templateBody?.declared_params) return;
  const declaredKeys = Object.keys(templateBody.declared_params);
  if (declaredKeys.length === 0) {
    setTemplateFetchError(null); // not a fetch error, but blocks transition
    return;
  }
  const auto = buildStarterSearchSpace(templateBody.declared_params);
  const autoJson = JSON.stringify(auto, null, 2);
  const current = form.getValues('search_space_text');
  const isEmpty = !current || current.trim() === '';
  const matchesPriorSignature = autoFillSignatures.has(current);
  if (isEmpty || matchesPriorSignature) {
    form.setValue('search_space_text', autoJson);
    setAutoFillSignatures((prev) => new Set(prev).add(autoJson));
  } else {
    // User edits exist; replace + toast with Undo
    const priorText = current;
    form.setValue('search_space_text', autoJson);
    setAutoFillSignatures((prev) => new Set(prev).add(autoJson));
    const timeoutId = window.setTimeout(() => setPendingUndo(null), 10_000);
    setPendingUndo({ priorText, timeoutId });
    toast('Replaced your Step-4 content with defaults for the new template.', {
      duration: 10_000,
      action: {
        label: 'Undo',
        onClick: () => {
          form.setValue('search_space_text', priorText);
          window.clearTimeout(timeoutId);
          setPendingUndo(null);
        },
      },
    });
  }
}, [templateBody, form, autoFillSignatures]);

// Handler: client-side validate on Step-4 Next-click
const handleStep4Next = () => {
  let parsed: SearchSpaceJson;
  try {
    parsed = JSON.parse(form.getValues('search_space_text') || '{}');
  } catch {
    setSearchSpaceError('Search space must be valid JSON');
    return;
  }
  if (!templateBody) {
    // Transient fetch failure — let server-side validation handle on submit
    setStep(4);
    return;
  }
  const declared = templateBody.declared_params;
  const submittedKeys = Object.keys(parsed.params || {});
  const declaredKeys = Object.keys(declared);
  const unknownKeys = submittedKeys.filter((k) => !(k in declared)).sort();
  if (unknownKeys.length > 0) {
    const k = unknownKeys[0];
    setSearchSpaceError(
      `Param '${k}' is not declared by template '${templateBody.name}'. Declared params: [${declaredKeys.sort().map(d => `'${d}'`).join(', ')}].`,
    );
    return;
  }
  const missingKeys = declaredKeys.filter((k) => !(k in (parsed.params || {}))).sort();
  if (missingKeys.length > 0) {
    const k = missingKeys[0];
    setSearchSpaceError(
      `Template '${templateBody.name}' declares param '${k}' but it is missing from the search space. Add it or remove from the template.`,
    );
    return;
  }
  setSearchSpaceError(null);
  setStep(4);
};

// Handler: metric change clears stale k for ignored-tier metrics
const handleMetricChange = (newMetric: ObjectiveMetric) => {
  form.setValue('metric', newMetric);
  if (K_IGNORED.has(newMetric)) {
    form.setValue('k', undefined);
  }
};
```

### Information architecture placement

- Spec §11 defines navigation placement: the create-study modal is reached from `/studies` page's "New study" button. Unchanged.
- New labels:
  - Step-4 InfoTooltip icon — adjacent to existing "Search space (JSON)" label.
  - Step-4 HelpPopover icon — below textarea.
  - Step-5 sub-labels — below k field for required/optional tiers.
  - Step-5 ignored-tier caption — replaces the k field.
- All new labels match the existing terminology (spec §11 wording).

### Tooltips and contextual help

Per spec §11 tooltip inventory:

| Element | Tooltip text source | Trigger | Placement | Markup pattern |
|---|---|---|---|---|
| Step-4 "Search space (JSON)" label | `study.search_space.short` from glossary | hover / focus | right of label | `<InfoTooltip glossaryKey="study.search_space" />` (Pattern A above) |
| Step-4 help popover | `study.search_space.long` from glossary | click | below textarea | `<HelpPopover glossaryKey="study.search_space" />` (Pattern B above) |
| Step-5 k label (required/optional tiers) | existing `study.k.short` — unchanged copy | hover / focus | right of label | Existing `<InfoTooltip glossaryKey="study.k" />` — no change |
| Step-5 metric option labels | existing `study.metric.<metric>.short` (extended per FR-6) | hover / focus | (unchanged surface) | Existing — text-only change to the `short` value |

### Visual consistency

- Use the existing `<InfoTooltip>` + `<HelpPopover>` components from PR #122. Do not introduce new tooltip/popover primitives.
- Sonner toast: use existing project pattern; do not introduce a new toast variant.
- Inline alert: `text-sm text-destructive` matches existing form error patterns elsewhere in the modal.

### Legacy behavior parity

**No legacy behavior parity table required.** No user-facing component >100 LOC is being deleted or migrated. The chore extends `create-study-modal.tsx` in place; the existing form behaviors (cluster select, query-set select, judgment-list select, template select, JSON textarea, metric/k/direction selects, max_trials, time_budget_min, parallelism, seed) all retain their current behavior except for the Step-4 / Step-5 changes explicitly enumerated in the UI element inventories.

### Client-side persistence

Not applicable. This chore introduces no `localStorage` or `sessionStorage` usage. The Undo state lives in React state only (`pendingUndo`); the 10-second timeout uses `window.setTimeout`.

---

## 3) Testing workstream

### 3.1 Unit tests

- Location: `backend/tests/unit/` + `ui/src/__tests__/`
- Scope: pure logic — domain validators, defaults heuristic, cardinality estimation, parity assertions
- Tasks:
  - [ ] `backend/tests/unit/domain/test_search_space_validation.py` — 4 cases (Story 1.1)
  - [ ] `backend/tests/unit/domain/test_search_space_cardinality_parity.py` — JSON-fixture-driven parity test (Story 2.1)
  - [ ] `backend/tests/unit/eval/test_scoring_metric_tokens.py` — 5 cases (Story 1.2)
  - [ ] `ui/src/__tests__/lib/search-space-defaults.test.ts` — heuristic cases + cap-fallback (Story 2.1)
  - [ ] `ui/src/__tests__/lib/search-space-defaults.cardinality.test.ts` — TS cardinality on shared fixture (Story 2.1)
  - [ ] `ui/src/__tests__/components/studies/k-required.test.ts` — K_REQUIRED membership (Story 3.2)
  - [ ] `ui/src/__tests__/components/studies/k-ignored.test.ts` — K_IGNORED membership (Story 3.2)
- DoD:
  - [ ] All branches covered; deterministic.
  - [ ] TS and Python cardinality tests share `backend/tests/_fixtures/search_space_cardinality_fixtures.json` so drift in either implementation surfaces in one of the two tests.

### 3.2 Integration tests

- Location: `backend/tests/integration/`
- Scope: DB-backed POST /api/v1/studies validation flow
- Tasks:
  - [ ] `backend/tests/integration/test_studies_create_template_validation.py` — 3 cases (unknown 400, missing 400, ordering) (Story 1.1)
- DoD:
  - [ ] No `studies` row inserted on validation failure (asserted via SELECT count).
  - [ ] Happy path (matching params) returns 201.

### 3.3 Contract tests

- Location: `backend/tests/contract/`
- Scope: response envelope shape for the two new error codes + K_REQUIRED tier matrix
- Tasks:
  - [ ] Extend `backend/tests/contract/test_studies_error_codes.py` with assertions for `SEARCH_SPACE_UNKNOWN_PARAM` (400) + `SEARCH_SPACE_MISSING_DECLARED_PARAM` (400) — both envelope shape match (`{"detail": {"error_code": "...", "message": "...", "retryable": false}}`); message includes template name. (Story 1.1)
  - [ ] New `backend/tests/contract/test_k_required_membership.py` — 12-cell tier matrix per AC-13 backend half. (Story 1.2)
- DoD:
  - [ ] Behavior-asserting contract test passes for both new codes. (Not OpenAPI enum-membership — see spec §14 contract test note.)
  - [ ] `test_k_required_membership.py` covers all 12 (metric × k-presence) cells.

### 3.4 Component tests

- Location: `ui/src/__tests__/components/`
- Scope: modal behavior changes — auto-fill, Undo, tri-state metric+k, validation, edge cases
- Tasks:
  - [ ] `create-study-modal.auto-fill.test.tsx` (Story 3.1)
  - [ ] `create-study-modal.auto-fill.undo.test.tsx` (Story 3.1)
  - [ ] `create-study-modal.client-validation.test.tsx` (Story 3.1)
  - [ ] `create-study-modal.zero-declared.test.tsx` (Story 3.1)
  - [ ] `create-study-modal.template-fetch-error.test.tsx` (Story 3.1)
  - [ ] `create-study-modal.metric-k.test.tsx` (Story 3.2)
- DoD:
  - [ ] All scenarios deterministically pass under jsdom + the shared `mockShadcnSelect` helper from `ui/src/__tests__/helpers/shadcn-select-mock.tsx` (PR #153).

### 3.5 E2E tests

- Location: `ui/tests/e2e/`
- Scope: real-backend hit for happy-path auto-fill assertion + client-side validation E2E
- Rule: Real browser interactions via Playwright's `page` object. `request` only for setup. No `page.route()` mocking.
- Tasks:
  - [ ] Extend `studies.spec.ts` happy-path to assert Step-4 auto-fill content (Story 4.1)
  - [ ] New `studies-create-validation.spec.ts` for client-side unknown-param validation surface (Story 4.1). Server-side path is contract-tested in `test_studies_error_codes.py`; E2E asserts the message format matches what the user would also see from the server.
- DoD:
  - [ ] Both specs pass against the local stack.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| [`ui/tests/e2e/studies.spec.ts`](../../../../ui/tests/e2e/studies.spec.ts) | `cs-search-space` Textarea fill | 1 | Extend happy-path with auto-fill assertion (Story 4.1) |
| [`ui/src/__tests__/components/studies/create-study-modal.test.tsx`](../../../../ui/src/__tests__/components/studies/create-study-modal.test.tsx) | Step-4 / Step-5 rendering | varies | Existing tests need updating where they assert on placeholder text or current k field rendering — update in the same commit as Story 3.1 / 3.2 to match new behavior. |
| `backend/tests/contract/test_studies_error_codes.py` | error code list | varies | Extend with new code assertions (Story 1.1) |
| `backend/tests/integration/test_studies_api.py` | POST /studies happy path | unknown | Verify no assertions on the existing pre-validation FK order break with the new validation insertion; spot-check after Story 1.1. |
| `ui/src/__tests__/lib/glossary.test.ts` | parity + length tests | 1 | No changes needed; existing length test auto-covers new entries (Story 2.2). |

### 3.6 CI gates

- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `cd ui && pnpm test`
- [ ] `cd ui && pnpm playwright test` (locally; CI smoke lane runs reduced subset)
- [ ] `make fmt && make lint && make typecheck`
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm exec prettier --check src package.json tsconfig.json eslint.config.mjs .prettierrc.json` (the prettier-check matches the PR #152 CI gate)

---

## 4) Documentation update workstream

### 4.0 Core context files

- **`state.md`** — update on PR merge (final story step):
  - [ ] "Just shipped" entry added with PR number + commit hash + the 4 key surfaces (auto-fill, validation, glossary, tri-state metric+k).
  - [ ] No Alembic head change (no migration).

- **`architecture.md`** — no update required. (No new architectural surfaces; the chore extends existing patterns.)

- **`CLAUDE.md`** — no update required. (No new conventions or absolute rules; the chore follows existing patterns.)

### 4.1 Architecture docs (`docs/01_architecture`)

- [ ] `ui-architecture.md` — extend "Glossary keys (canonical)" with 4 new `study.search_space.*` keys + dual-tooltip pattern note (Story 4.1).
- [ ] `api-conventions.md` — append two new error codes to catalog table (Story 4.1).

### 4.2 Product docs (`docs/02_product`)

- No user-facing doc updates beyond this spec.

### 4.3 Runbooks (`docs/03_runbooks`)

- N/A.

### 4.4 Security docs (`docs/04_security`)

- N/A.

### 4.5 Quality docs (`docs/05_quality`)

- N/A.

### 4.6 Guides (`docs/08_guides`)

- [ ] `tutorial-first-study.md` Step 7 — remove verbatim search-space paste block; replace with "the wizard auto-fills Step 4" instruction (Story 4.1).

### Documentation DoD

- [ ] `state.md` reflects PR merge.
- [ ] `ui-architecture.md`, `api-conventions.md`, `tutorial-first-study.md` all updated in the same PR as the code.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- None planned. The chore is additive (new function, new constant, new UI surfaces, new glossary entries). No existing code is removed.

### 5.2 Planned refactor tasks

- [ ] N/A.

### 5.3 Refactor guardrails

- [ ] N/A.

(Note: the Story 1.2 scoring-token mapper test may surface that the mapper is inlined in `run_trial`. If so, extracting it as a standalone function is part of Story 1.2's scope — minimum signature change, behavior preserved. Captured here in case the implementer needs to budget for it.)

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `<InfoTooltip>` component (PR #122) | Story 3.1 | Shipped 2026-05-15 | None |
| `<HelpPopover>` component (PR #122) | Story 3.1 | Shipped 2026-05-15 | None |
| `mockShadcnSelect` helper (PR #153) | Story 3.1 + 3.2 component tests | Shipped 2026-05-19 | None |
| `K_REQUIRED` constant | Story 3.2 | Existing, line 46 of `create-study-modal.tsx` | None |
| `_K_REQUIRED_METRICS` frozenset | Story 1.1 + 3.2 parity test | Existing, `schemas.py:474` | None |
| Existing `studies.spec.ts` + e2e helpers | Story 4.1 | Existing | None |
| `useQueryTemplate` hook or equivalent fetch | Story 3.1 | Existing pattern (verify location) | If missing, Story 3.1 must hand-roll a TanStack Query call (~10 LOC) |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `compute_default_params` dead-code observation leads to scope creep | M | L | Captured as separate `chore_template_defaults_dead_code` idea (spec §19); this chore does not touch `template_defaults.py`. |
| Scoring-token mapper is inlined in `run_trial` and requires extraction | M | M | Story 1.2 budgets for minimum-signature extraction; falls back to a test-only walking of the inlined logic if extraction is risky. |
| Auto-fill heuristic produces a `__placeholder__` ParamSpec for `string`-typed declared params that confuses users | L | L | The placeholder is degenerate (single-choice categorical, cardinality 1) — passes `SearchSpace.model_validate`; UX hint is added as an inline note in the textarea (deferred to implementation copy). Future visual builder (separate feat) will give per-row editing affordances. |
| Tri-state metric+k rendering regresses an existing test asserting placeholder text | L | L | Story 3.2 audits the existing `create-study-modal.test.tsx` for `'required'`/`'optional'` placeholder assertions and updates them to match new sub-label/caption structure. |
| Network-failure path lets a user submit a study against a missing template body, bypassing client-side declared-param validation | M | L | Server-side `validate_against_template` (Story 1.1) is the explicit safety net — guaranteed catch on POST. Spec §11 documents this tradeoff. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Template fetch 404 mid-modal | Template deleted between Step-3 select and Step-4 entry | Toast + bump user back to Step 3 with "template no longer available" message | Manual — user picks a different template |
| Template fetch 5xx / network error | Backend transiently down | Step 4 renders with empty textarea + Retry button; Next remains enabled | Retry button re-fires the fetch; server-side validation safety net catches typos on submit |
| Auto-fill produces invalid JSON (impossible per FR-1 — should always validate) | Bug in `buildStarterSearchSpace` | Step-4 client-side validator catches before Next-click | Manual — user reports bug; auto-fill defaults heuristic gets corrected |
| User edits auto-filled content, switches template, doesn't click Undo within 10s | Normal user behavior | Edited content is permanently replaced after 10s | Manual — user re-types if they need the prior content |
| `K_REQUIRED` or `K_IGNORED` drift between frontend and backend | Backend adds a new metric to `OBJECTIVE_METRIC_VALUES` without updating sets | Frontend parity tests (Story 3.2) fail in CI | Update the affected predicate in lockstep with the backend change |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1 (Backend)** — Stories 1.1 → 1.2 (sequential within epic; 1.1 changes search_space.py and POST handler, 1.2 only adds test coverage)
2. **Epic 2 (Frontend foundations)** — Stories 2.1 → 2.2 (sequential; defaults module first, glossary entries second; both can technically parallel but reviewability is better serial)
3. **Epic 3 (Wizard wiring)** — Stories 3.1 → 3.2 (sequential within epic; both touch the same `create-study-modal.tsx` file)
4. **Epic 4 (E2E + docs)** — Story 4.1 (single story)

**Cross-epic ordering:** Epic 1 → Epic 2 → Epic 3 → Epic 4. Epic 2 doesn't strictly depend on Epic 1 (defaults module + glossary entries are independent of backend validation), but landing Epic 1 first means Epic 2 lands with the backend already in place — which keeps a single-story partial deployment from being misleading to anyone reviewing intermediate commits.

### Parallelization opportunities

- **Within Story 1.1:** the unit test file and the integration test file can be written in parallel after the domain function is implemented (both depend on the function but not on each other).
- **Within Story 3.1:** the 5 new component test files can be written in parallel after the modal changes land.
- **Cross-story:** if two contributors work on the chore, Story 1.1 (backend) and Story 2.1 (frontend defaults module) have zero dependency overlap and can run in parallel.

For a solo contributor (the typical RelyLoop pattern), the suggested sequence above is the cleanest.

## 8) Rollout and cutover plan

- **Rollout:** single-step, no flag. Land the PR; the new behavior is active for all users on next deploy (or `make up` for local-only).
- **Feature flag:** none. The auto-fill behavior is strictly additive (empty textarea → pre-filled textarea); the validation is strictly tightening (rejects a class of inputs that previously failed on trial 1 — same outcome, just faster). No backward-compatibility shims needed.
- **Migration/cutover:** N/A — no schema changes, no data migration.
- **Reconciliation:** N/A — no external systems.

## 9) Execution tracker

### Current sprint

- [ ] Story 1.1 — `validate_against_template` + router wiring + tests
- [ ] Story 1.2 — Backend scoring-token unit test
- [x] Story 2.1 — `search-space-defaults.ts` module + tests
- [x] Story 2.2 — Glossary entries
- [x] Story 3.1 — Step-4 auto-fill + tooltips + validation + edges
- [x] Story 3.2 — Step-5 tri-state metric+k + parity tests
- [x] Story 4.1 — E2E specs + documentation updates

### Blocked items

- None at plan-creation time.

### Done this sprint

- (none yet)

## 10) Story-by-Story Verification Gate

Before marking any story complete:

- [ ] Files created/modified match the story's `New files` / `Modified files` tables.
- [ ] All FRs referenced by the story's traceability row are addressed.
- [ ] All ACs referenced by the story's DoD are observable in a test.
- [ ] Tests added/updated for the touched layers (unit/integration/contract/component/e2e).
- [ ] Commands executed and passed:
  - [ ] `make test-unit`
  - [ ] `make test-integration` (or targeted subset with reason)
  - [ ] `make test-contract`
  - [ ] `cd ui && pnpm test`
  - [ ] `cd ui && pnpm playwright test` if UI touched
- [ ] No migration (verify story isn't claiming one).
- [ ] Cross-references in `idea.md` / `pipeline_status.md` updated.

## 11) Plan consistency review

### 11.1 Spec ↔ plan endpoint count
Spec §8.1 lists 1 endpoint (`POST /api/v1/studies`). Plan covers it in Story 1.1. ✅

### 11.2 Spec ↔ plan error code coverage
Spec §8.5 lists 2 new codes (`SEARCH_SPACE_UNKNOWN_PARAM`, `SEARCH_SPACE_MISSING_DECLARED_PARAM`). Plan Story 1.1 covers both in the endpoint table + contract test task. ✅

### 11.3 Spec ↔ plan FR coverage
All 7 FRs from spec §7 mapped in §1 above. ✅

### 11.4 Story internal consistency
- Story 1.1: endpoint table + Pydantic schemas (none new) + DoD reference matching error codes. ✅
- Story 3.1 + 3.2: both modify `create-study-modal.tsx`. No file-ownership conflict (different sections + no overlapping line ranges per the insertion-point map in UI Guidance). ✅
- Story 2.1's defaults module is the sole owner of `search-space-defaults.ts`; Story 3.1 imports from it. ✅

### 11.5 Test file count

| Layer | Files | Stories |
|---|---|---|
| Backend unit | `test_search_space_validation.py`, `test_scoring_metric_tokens.py`, `test_search_space_cardinality_parity.py` | 1.1, 1.2, 2.1 |
| Backend integration | `test_studies_create_template_validation.py` | 1.1 |
| Backend contract | `test_k_required_membership.py` (new) + `test_studies_error_codes.py` (modified) | 1.2, 1.1 |
| Frontend unit | `search-space-defaults.test.ts`, `search-space-defaults.cardinality.test.ts`, `k-required.test.ts`, `k-ignored.test.ts` | 2.1, 2.1, 3.2, 3.2 |
| Frontend component | `auto-fill.test.tsx`, `auto-fill.undo.test.tsx`, `client-validation.test.tsx`, `zero-declared.test.tsx`, `template-fetch-error.test.tsx`, `metric-k.test.tsx` | 3.1, 3.1, 3.1, 3.1, 3.1, 3.2 |
| E2E | `studies-create-validation.spec.ts` (new) + `studies.spec.ts` (modified) | 4.1, 4.1 |

**Totals:** 5 new backend test files + 10 new frontend test files + 1 new E2E test file = **16 new test files**. Plus 2 modified existing test files (`test_studies_error_codes.py`, `studies.spec.ts`) and 1 spot-check (`test_studies_api.py`, no change expected). Every new test file is assigned to exactly one story's New files. ✅

### 11.6 Gate arithmetic
- Epic 1 gate: covers Stories 1.1 + 1.2 (matches).
- Epic 2 gate: covers Stories 2.1 + 2.2 (matches).
- Epic 3 gate: covers Stories 3.1 + 3.2 (matches).
- Epic 4 gate: covers Story 4.1 (matches).

### 11.7 Open questions resolved
Spec §19 lists 2 open questions (Q1: glossary copy text, Q2: toast wording). Both deferred to implementation (Story 2.2 + Story 3.1), not blocking plan readiness. ✅

### 11.8 Plan ↔ codebase verification

| Claim | Verified by | Status |
|---|---|---|
| Migration path is `migrations/versions/` | CLAUDE.md §"Migrations" + project root `alembic.ini` | Verified (no migration in this plan, but the path convention is noted for any future migration) |
| Alembic head `0013_search_vector_conversations` (state.md) | state.md line 15 | Verified — not modified by this chore |
| POST handler at `studies.py:185-250` | Read in spec-gen | Verified |
| `_err()` helper at `studies.py:68-72` | Read in spec-gen | Verified |
| `SearchSpace.model_validate` at `search_space.py` | Read in spec-gen | Verified |
| `K_REQUIRED` at `create-study-modal.tsx:46` | Read in spec-gen | Verified |
| `_K_REQUIRED_METRICS` at `schemas.py:474` | Read in spec-gen | Verified |
| `InfoTooltip` component at `info-tooltip.tsx` | Read in spec-gen | Verified |
| `HelpPopover` component at `help-popover.tsx` | Read in spec-gen | Verified |
| `mockShadcnSelect` helper at `helpers/shadcn-select-mock.tsx` | Confirmed by PR #153 reference in state.md | Verified |
| Existing E2E `studies.spec.ts` | `ls ui/tests/e2e/studies.spec.ts` | Verified |
| Existing contract test `test_studies_error_codes.py` | Confirmed during spec generation | Verified |
| Modal line ranges (Step 4 at 322-339; Step 5 at 340-468) | Read in spec-gen | Verified |

### 11.9 Frontend data plumbing verification
- `templateBody` (from `useQueryTemplate(template_id)`) flows from the modal's effect to the auto-fill writer and to `handleStep4Next`. Confirmed both consumers are in the same component scope. ✅
- `K_IGNORED` is module-local; no plumbing needed. ✅
- `K_REQUIRED` is module-local (existing). ✅

### 11.10 Persistence scope consistency
- No `localStorage` / `sessionStorage` introduced. `pendingUndo` lives in React state; 10s timeout via `window.setTimeout`. Task and DoD agree. ✅

### 11.11 Enumerated value contract audit
- All metric / k / K_REQUIRED / K_IGNORED option lists cite the backend source-of-truth file in the plan's §"UI element inventory" tables for the relevant stories.
- Story 3.2 explicitly adds the `// Source-of-truth: ...` comment above `K_IGNORED`.
- `OBJECTIVE_METRIC_VALUES` and `OBJECTIVE_K_VALUES` are unchanged from current state (existing SoT comments in `enums.ts` remain).
- ✅

### 11.12 Admin control audit
- N/A — RelyLoop has no admin/tenant model in MVP1.

### 11.13 Audit-event coverage audit
- N/A — `audit_log` activates at MVP2. No new mutation sites are added (the existing `POST /api/v1/studies` mutation is unchanged; only its rejection path adds new error codes).

---

## 12) Definition of plan done

- [ ] Every FR mapped to a story (✅ §1).
- [ ] Every story includes New files, Modified files, Endpoints (if API), Key interfaces, Tasks, DoD.
- [ ] Test layers explicitly scoped (✅ §3).
- [ ] Documentation updates planned and owned (✅ §4).
- [ ] Lean refactor scope explicit (✅ §5 — none planned).
- [ ] Epic gates measurable.
- [ ] Story-by-Story Verification Gate included (✅ §10).
- [ ] Plan consistency review performed (✅ §11) with no unresolved findings.
