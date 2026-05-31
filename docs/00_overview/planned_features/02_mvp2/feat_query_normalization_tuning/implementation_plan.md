# Implementation Plan — Query normalization as a tunable, opt-in query-time parameter

**Date:** 2026-05-31
**Status:** Approved
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy source(s):**
- [`CLAUDE.md`](../../../../../CLAUDE.md) (Absolute Rule #4 — engine adapter Protocol confinement)
- [`docs/01_architecture/adapters.md`](../../../../01_architecture/adapters.md) (SearchAdapter Protocol shape)
- [`docs/01_architecture/optimization.md`](../../../../01_architecture/optimization.md) (where the loop fits in the relevance pipeline)

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs.
- Epic gates are hard stops.
- Fail-loud tests: assert explicit error codes, exact HTTP status, exact rendered strings.
- The adapter pre-render hook is the **only consumption site** for `query_normalizer` (invariant I-2 of the spec). Caller-side workers (`trials.py`, `baseline.py`, `judgments.py`) remain unchanged.
- Defense-in-depth: the FR-1 `compute_default_params` extension AND the adapter hook fallback both default to `DEFAULT_NORMALIZER` ("none") when the key is absent — either alone would close the FR-1 bug, but the spec requires both for resilience against future callers that bypass `compute_default_params`.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (normalizer library + `compute_default_params` extension + adapter fallback) | Epic 1 / Stories 1.1 + 1.2 | 1.1 = library + 30-entry contractions + `_PR_BODY_NORMALIZER_SNIPPETS`. **1.2 = the `compute_default_params` story flagged by spec cycle-2 as a load-bearing detail** — has its own verification gate. |
| FR-2 (reserved-key reservation + template-validator extension) | Epic 1 / Story 1.3 + Epic 2 / Story 2.1 | 1.3 = pure-domain `validate_normalizer_reservation` + `_RESERVED_NONRENDER_PARAMS` + new exception classes. 2.1 = router wiring at `POST /api/v1/studies` AND `POST /api/v1/query-templates`. |
| FR-3 (ES/OpenSearch pre-render hook) | Epic 2 / Story 2.2 | One hook implementation in `ElasticAdapter.render`. Covers both ES and OpenSearch (shared adapter per CLAUDE.md "Stack"). |
| FR-4 (Solr pre-render hook) | Epic 2 / Story 2.3 | Identical algorithm in `SolrAdapter.render` — cross-engine portability proof point. |
| FR-5 (PR-body "Operator-side requirement" section) | Epic 3 / Story 3.1 | `_render_pr_body_study_backed` only; `_render_pr_body_manual` explicitly excluded per invariant I-3. |
| FR-6 (digest-panel analyzer-redundancy advisory) | Epic 4 / Story 4.1 | ES/OpenSearch only in MVP2 (Solr has no per-field analyzer in `get_schema`). Reuses existing `useClusterSchema` hook + existing `useCluster` hook. |
| FR-7 (frontend enumerated value contract) | Epic 4 / Story 4.2 | `NORMALIZER_VALUES` + `NORMALIZER_GLOSSARY_KEYS` map + `row-categorical.tsx` conditional rendering. Six new glossary keys. |
| FR-8 (documentation updates) | Epic 5 / Story 5.1 | Three doc files. Single doc-sweep story. |
| — (AC-13 end-to-end) | Epic 6 / Story 6.1 | Real-backend Playwright spec. |

**Deferred phase tracking:** Phase 2 + Phase 3 were carved out and relocated to their own planned-features folders 2026-05-31 — [`feat_query_normalizer_typed_pipeline`](../feat_query_normalizer_typed_pipeline/idea.md) (was `phase2_idea.md`) and [`feat_apply_path_normalizer_declaration`](../feat_apply_path_normalizer_declaration/idea.md) (was `phase3_idea.md`). **Do not modify** them during this plan's Phase-1 execution.

## 2) Delivery structure

Epic → Story → Tasks → DoD.

### Conventions (this codebase)

- All domain modules pure: no async, no DB, no httpx, no `openai` import. (`backend/app/domain/study/normalizers.py` is brand-new and must be pure.)
- Adapter pre-render hook MUST NOT mutate the caller's `params` dict — copy into a local first (spec anti-pattern §4).
- New domain ValueError subclasses get caught **by name** at the router and mapped via the existing `_err(400, "<CODE>", str(exc), False)` pattern at `backend/app/api/v1/studies.py:213-266` (mirrors `UnknownSearchSpaceParamError` → `SEARCH_SPACE_UNKNOWN_PARAM` at L263-266).
- Frontend wire-value arrays land in `ui/src/lib/enums.ts` with the canonical `// Values must match <backend/path.py> <Symbol>` source-of-truth comment. The Story 2.13 lint guard (CLAUDE.md "Enumerated Value Contract Discipline") and the form-select-discipline test enforce.
- Glossary copy lives in `ui/src/lib/glossary.ts`. Length lints in `ui/src/__tests__/lib/glossary.test.ts` apply.
- All new test files follow the four-layer convention (`backend/tests/unit/`, `backend/tests/integration/`, `backend/tests/contract/`, `ui/tests/e2e/`).
- Conventional Commits + `git commit -s` for DCO sign-off (CLAUDE.md Absolute Rule #7).

### AI Agent Execution Protocol

0. Load `architecture.md` + `state.md` before Story 1.1.
1. Read scope: story outcome + endpoints + interfaces + DoD.
2. Backend first: domain → adapters → router → schemas → contract tests.
3. Run backend tests (unit + contract subset for touched endpoints).
4. Frontend (Epic 4).
5. E2E (Epic 6).
6. Docs sweep (Epic 5).
7. No migration in this feature — round-trip check skipped.
8. Attach evidence in PR description.

---

## Epic 1 — Pure-domain normalizer library + defaults wiring

Goal: ship the engine-neutral normalizer module + the `compute_default_params` extension that prevents baseline/judgment runs from crashing on normalizer-aware templates.

### Story 1.1 — Normalizer module + contraction dictionary + snippet table
**Outcome:** A pure-domain `backend/app/domain/study/normalizers.py` exposes the four-choice allowlist, the `normalize()` function, the 30-entry frozen contraction dictionary, and the `_PR_BODY_NORMALIZER_SNIPPETS` dict used by FR-5. No external code consumes it yet.

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/study/normalizers.py` | Library module — `NORMALIZER_CHOICES`, `DEFAULT_NORMALIZER`, `_CONTRACTIONS` (frozen via `types.MappingProxyType`), `_CONTRACTION_PATTERN` (compiled once at import), `normalize()`, `_PR_BODY_NORMALIZER_SNIPPETS`. Pure functions, no I/O. SPDX header per repo convention. |
| `backend/tests/unit/domain/study/test_normalizers.py` | Unit tests over `normalize()` × choices × representative inputs (AC-1). |
| `backend/tests/unit/domain/study/test_normalizers_pr_snippets.py` | Semantic-equality test (I-4 + AC-12) — `exec()` snippet into sandboxed namespace, compare against runtime `normalize(..., "lowercase+trim+expand_contractions")` on the curated 10-element fixture corpus listed in spec §AC-12. Parametrized over `NORMALIZER_CHOICES` so `lowercase` and `lowercase+trim` snippets also round-trip. |

**Modified files**

| File | Change |
|---|---|
| _none_ | The module is freestanding; no `__init__.py` re-exports needed in MVP2. |

**Key interfaces**

```python
# backend/app/domain/study/normalizers.py
NORMALIZER_CHOICES: Final[tuple[str, str, str, str]] = (
    "none", "lowercase", "lowercase+trim", "lowercase+trim+expand_contractions",
)
DEFAULT_NORMALIZER: Final[str] = "none"

def normalize(query_text: str, choice: str) -> str: ...  # raises ValueError on unknown choice

_CONTRACTIONS: Mapping[str, str]    # MappingProxyType wrapping the 30 entries from spec §9
_CONTRACTION_PATTERN: re.Pattern    # built at import — sorted by length-desc to prefer longest match
_PR_BODY_NORMALIZER_SNIPPETS: Mapping[str, str]   # keys = NORMALIZER_CHOICES; "none" key absent (FR-5 short-circuit)
```

**Tasks**

1. Create `backend/app/domain/study/normalizers.py` with SPDX header.
2. Define the 30-entry `_CONTRACTIONS` dict verbatim from spec §9 ("Built-in contraction dictionary").
3. Wrap with `types.MappingProxyType` and store as `_CONTRACTIONS: Mapping[str, str]`.
4. Build the compiled regex at module scope: `_CONTRACTION_PATTERN = re.compile(r"\b(" + "|".join(map(re.escape, sorted(_CONTRACTIONS, key=len, reverse=True))) + r")\b")`.
5. Implement `normalize(query_text, choice)` with explicit branches for the four choices; raise `ValueError(f"unknown normalizer: {choice}")` on miss. Order: lowercase → strip → contraction sub.
6. Define `_PR_BODY_NORMALIZER_SNIPPETS` keyed on the three non-`none` choices, with snippet bodies verbatim from spec §9 "Python snippet templates". The `lowercase+trim+expand_contractions` snippet MUST inline the 30-entry dictionary literal (single source kept in sync by Story 1.1's snippet test).
7. Write `test_normalizers.py` asserting:
   - `normalize("Hello World ", "lowercase+trim") == "hello world"` (AC-1).
   - `normalize("WHAT'S the deal?", "lowercase+trim+expand_contractions") == "what is the deal?"` (AC-1).
   - `normalize("whatsoever", "lowercase+trim+expand_contractions") == "whatsoever"` (word-boundary, AC-1).
   - `normalize("swhat's", "lowercase+trim+expand_contractions") == "swhat's"` (left-boundary, AC-1).
   - `normalize("anything", "stem")` raises `ValueError` with message containing `'stem'` (AC-1).
   - Parametrized over the Cartesian product of {4 choices} × {bank of inputs incl. mixed-case, empty string, single-char, smart-quote `"what’s"` which MUST round-trip unchanged per spec D-7}.
8. Write `test_normalizers_pr_snippets.py` (AC-12):
   - Parametrize over the three non-`none` `NORMALIZER_CHOICES`.
   - For each: `exec()` the snippet into a fresh dict namespace; pull out `normalize_query`; call both `normalize_query(s)` and `normalize(s, choice)` over the 10-element corpus (spec §AC-12 lists the entries); assert per-entry equality.

**Definition of Done (DoD)**
- `make test-unit` green; both new test files pass.
- `mypy --strict` green on the new module.
- `ruff check` + `ruff format` clean.
- `_CONTRACTIONS` length is exactly 30 (assert in `test_normalizers.py`).
- AC-1 + AC-12 verified.

### Story 1.2 — `compute_default_params` extension for `query_normalizer` (FR-1 load-bearing detail; cycle-2 fix)

**Outcome:** When a template's `declared_params` contains `"query_normalizer"` (either simple-form `"string"` or rich-form `{"type": "categorical", ...}`), `compute_default_params` returns `"none"` (the `DEFAULT_NORMALIZER` constant), NOT the simple-form fallback `""` and NOT the categorical first-value. This guarantees baseline trials (`backend/workers/baseline.py:194`) and LLM-judgment generation (`backend/workers/judgments.py:195`) — both of which call `compute_default_params` to build the params dict passed to `adapter.render` — never push an invalid choice to the adapter.

**Why this story exists separately:** The spec cycle-2 review caught that without this extension, a normalizer-aware template would crash inside the adapter with `ValueError("unknown normalizer: ")` on the very first baseline trial or LLM-judgment hit. The adapter hook fallback (Story 2.2 / 2.3) is defense-in-depth — Story 1.2 is the actual fix. Both must ship.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/domain/study/test_template_defaults_normalizer.py` | Regression guard for the FR-1 extension. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/domain/study/template_defaults.py` | Add `query_normalizer` special case at the top of the loop in `compute_default_params` (covers both simple-form and rich-form declarations). Import `DEFAULT_NORMALIZER` from the new normalizers module. |

**Key interfaces**

```python
# backend/app/domain/study/template_defaults.py — modified
from backend.app.domain.study.normalizers import DEFAULT_NORMALIZER

def compute_default_params(template_row: Any) -> dict[str, Any]:
    declared: dict[str, Any] = cast(dict[str, Any], template_row.declared_params) or {}
    params: dict[str, Any] = {}
    for name, schema in declared.items():
        # FR-1: reserved-key short-circuit — applies regardless of declaration shape.
        # Baseline + LLM-judgment runs pass the result to adapter.render which
        # forwards it to normalize(); DEFAULT_NORMALIZER is the only safe default
        # for a key the operator hasn't otherwise pinned.
        if name == "query_normalizer":
            params[name] = DEFAULT_NORMALIZER
            continue
        # ...existing simple-form / rich-form branches unchanged...
```

**Tasks**

1. Add `from backend.app.domain.study.normalizers import DEFAULT_NORMALIZER` to `template_defaults.py`.
2. Insert the `query_normalizer` short-circuit at the top of the loop in `compute_default_params`, BEFORE the simple-form / rich-form branches so it covers both shapes.
3. Write `test_template_defaults_normalizer.py` with cases:
   - **Simple form:** `declared_params = {"query_normalizer": "string", "title_boost": "float"}` (no min/max on `title_boost` — exercises the simple-form path for both keys). Construct a fake `template_row` (a `SimpleNamespace` exposing `.declared_params`). Expected: `{"query_normalizer": "none", "title_boost": 1.0}` (NOT `{"query_normalizer": "", ...}`).
   - **Rich form:** `declared_params = {"query_normalizer": {"type": "categorical", "values": ["lowercase", "lowercase+trim"]}, "title_boost": {"type": "float", "min": 0.5, "max": 2.5}}`. Expected: `{"query_normalizer": "none", "title_boost": 1.5}` (NOT `{"query_normalizer": "lowercase", ...}` — even though `lowercase` is the first categorical value, the reserved key overrides to `DEFAULT_NORMALIZER`).
   - **Absent:** `declared_params = {"title_boost": "float"}` — no key collision; assert `"query_normalizer"` not in returned dict.
4. Assert the imported `DEFAULT_NORMALIZER` is literally `"none"` (value-lock test, mirrors the `STUDIES_TPE_WARMUP_FLOOR` discipline established in `feat_study_sub_warmup_guard`).

**Definition of Done (DoD)**
- `make test-unit` green; new test passes.
- Existing `compute_default_params` tests (unmodified) still pass.
- AC-1's regression scope (the bug spec cycle-2 caught) is locked behind this test.

**Verification gate (hard stop before Epic 2)** — the spec author flagged this story as easy to miss. Before starting Story 1.3:

- [ ] `test_template_defaults_normalizer.py` exists and passes.
- [ ] `compute_default_params` imports `DEFAULT_NORMALIZER` from `normalizers.py` (grep evidence).
- [ ] Both simple-form and rich-form regression cases assert the reserved short-circuit wins over the default branches.
- [ ] The value-lock assertion (`DEFAULT_NORMALIZER == "none"`) is present.

### Story 1.3 — `validate_normalizer_reservation` + new exception classes + template-validator extension

**Outcome:** Pure-domain validators and exception types exist; router wiring follows in Epic 2. Three new ValueError subclasses (`NormalizerChoiceInvalidError`, `NormalizerParamShapeError`, `ReservedParamReferenced`) and one new constant (`_RESERVED_NONRENDER_PARAMS`).

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/domain/study/test_search_space_normalizer_reservation.py` | Tests `validate_normalizer_reservation` directly (construct `SearchSpace` via `model_validate`, then call the validator over good/bad cases). |
| `backend/tests/unit/domain/study/test_template_validator_reserved_param.py` | Tests `_RESERVED_NONRENDER_PARAMS` exemption (declared-but-unreferenced passes) AND the `ReservedParamReferenced` raise (body references reserved key → raises). |

**Modified files**

| File | Change |
|---|---|
| `backend/app/domain/study/normalizers.py` | Add `NormalizerChoiceInvalidError`, `NormalizerParamShapeError`, and `validate_normalizer_reservation(space: SearchSpace) -> None`. |
| `backend/app/domain/study/template_validator.py` | Add `_RESERVED_NONRENDER_PARAMS: frozenset[str] = frozenset({"query_normalizer"})` and `ReservedParamReferenced(ValueError)`. Modify `validate_template_body` to (a) exclude `_RESERVED_NONRENDER_PARAMS` from `unused_declarations` before the `DeclaredParamUnused` raise; (b) compute `referenced ∩ _RESERVED_NONRENDER_PARAMS` after step 3 and raise `ReservedParamReferenced` if non-empty. |

**Key interfaces**

```python
# backend/app/domain/study/normalizers.py (added)
class NormalizerChoiceInvalidError(ValueError): ...
class NormalizerParamShapeError(ValueError): ...

def validate_normalizer_reservation(space: SearchSpace) -> None:
    """Enforces I-1: query_normalizer (if present) is a CategoricalParam
    whose choices is a non-empty subset of NORMALIZER_CHOICES.

    No-op when 'query_normalizer' not in space.params. Raises
    NormalizerParamShapeError when the param is not a CategoricalParam.
    Raises NormalizerChoiceInvalidError when any choice is not in
    NORMALIZER_CHOICES (message names the first offender, exact format
    per spec FR-2)."""

# backend/app/domain/study/template_validator.py (added)
_RESERVED_NONRENDER_PARAMS: frozenset[str] = frozenset({"query_normalizer"})
class ReservedParamReferenced(ValueError): ...
```

**Tasks**

1. In `normalizers.py`, add the two ValueError subclasses with one-line docstrings stating their router mapping (`NORMALIZER_CHOICE_INVALID` / `NORMALIZER_PARAM_SHAPE`).
2. Implement `validate_normalizer_reservation`: check `"query_normalizer" not in space.params` → return early. Otherwise check `isinstance(space.params["query_normalizer"], CategoricalParam)` — raise `NormalizerParamShapeError` with message `f"query_normalizer must be CategoricalParam (got {type(space.params['query_normalizer']).__name__})"` otherwise. Iterate choices; on first miss, raise `NormalizerChoiceInvalidError` with the spec-mandated exact message format.
3. In `template_validator.py`, add the new constant + exception class above `validate_template_body`.
4. Modify `validate_template_body`:
   - After the `referenced - declared` undeclared-uses check (L121-125), compute `reserved_referenced = referenced & _RESERVED_NONRENDER_PARAMS` and raise `ReservedParamReferenced(f"template body references reserved non-render param(s): {sorted(reserved_referenced)}; these are consumed by the adapter and MUST NOT appear in the template body")` if non-empty.
   - Modify the `unused_declarations = set(declared_params) - referenced` line to `unused_declarations = set(declared_params) - referenced - _RESERVED_NONRENDER_PARAMS` so a template declaring `query_normalizer` without using it in the body parses cleanly.
5. Write `test_search_space_normalizer_reservation.py`:
   - Good case: `space.params["query_normalizer"]` = `CategoricalParam(type="categorical", choices=["none", "lowercase+trim"])` → returns `None`.
   - Bad choice: `choices=["none", "stem"]` → raises `NormalizerChoiceInvalidError`; message contains `'stem'` and the allowed-set list verbatim per spec.
   - Bad shape: replace `space.params["query_normalizer"]` with a `FloatParam` → raises `NormalizerParamShapeError`; message contains `"FloatParam"`.
   - Absent: `"query_normalizer" not in space.params` → returns `None` (no-op).
   - **Document** in the test docstring why we don't test via `SearchSpace.model_validate` alone: per spec §3 in-scope bullets, direct calls to `model_validate` do NOT enforce the reservation; only `validate_normalizer_reservation` does. This is by design.
6. Write `test_template_validator_reserved_param.py`:
   - (a) body `'{"q": "{{ query_text }}"}'` + `declared_params = {"query_normalizer": "string"}` → no raise; the `_RESERVED_NONRENDER_PARAMS` exemption keeps `DeclaredParamUnused` quiet.
   - (b) body `'{"q": "{{ query_normalizer }}"}'` + `declared_params = {"query_normalizer": "string"}` → raises `ReservedParamReferenced`; message contains `'query_normalizer'`.
   - (c) Mixed: body `'{"q": "{{ query_text }}", "boost": "{{ title_boost }}"}'` + `declared_params = {"query_normalizer": "string", "title_boost": "float"}` → no raise (the reserved key is exempt; `title_boost` IS referenced so the unused-check passes).

**Definition of Done (DoD)**
- `make test-unit` green; both new test files pass.
- `mypy --strict` clean on both modified modules.
- The four spec error codes (`NORMALIZER_CHOICE_INVALID`, `NORMALIZER_PARAM_SHAPE`, `RESERVED_PARAM_REFERENCED`, and the already-existing `INVALID_SEARCH_SPACE` precedence preserved) are reachable as Python-level raises (router wiring lands in Epic 2).

**Epic 1 gate** — pure-domain layer complete:
- [ ] Stories 1.1, 1.2, 1.3 DoDs satisfied.
- [ ] Story 1.2 verification gate (hard stop) passed.
- [ ] No production caller imports the new module yet (verified by grep — only test files import it).

---

## Epic 2 — Adapter pre-render hook + router wiring

Goal: make `query_normalizer` actually do something. After Epic 2, the loop can run a normalizer-tuning study end-to-end (no UI yet).

### Story 2.1 — Router wiring at `POST /api/v1/studies` + `POST /api/v1/query-templates`

**Outcome:** Both endpoints surface the three new error codes from Epic 1 with the spec-mandated envelope.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/studies.py` | After `validate_against_template` at L257-266, add a third `try/except` block calling `validate_normalizer_reservation(SearchSpace.model_validate(body.search_space))`. Catch `NormalizerChoiceInvalidError` → `_err(400, "NORMALIZER_CHOICE_INVALID", str(exc), False)`; catch `NormalizerParamShapeError` → `_err(400, "NORMALIZER_PARAM_SHAPE", str(exc), False)`. |
| `backend/app/api/v1/query_templates.py` | In `create_query_template` at L135-142, add a fourth `except` after `DeclaredParamUnused`: catch `ReservedParamReferenced` → `_err(400, "RESERVED_PARAM_REFERENCED", str(exc), False)`. |
| `backend/app/api/errors.py` | Add the three new error codes to whichever catalog the project uses for OpenAPI-emission purposes (verify pattern by reading the file — likely no edit needed if codes are string literals; confirm contract test catches drift). |

**Endpoints**

| Method | Path | Affected behavior | New error codes | Existing error envelope |
|---|---|---|---|---|
| `POST` | `/api/v1/studies` | Invokes `validate_normalizer_reservation` after `validate_against_template`. | `NORMALIZER_CHOICE_INVALID` (400), `NORMALIZER_PARAM_SHAPE` (400) | `{"detail": {"error_code": <CODE>, "message": <str>, "retryable": false}}` per spec §8.3 |
| `POST` | `/api/v1/query-templates` | Rejects bodies referencing `{{ query_normalizer }}`; accepts bodies declaring it without referencing it. | `RESERVED_PARAM_REFERENCED` (400) | Same envelope. |

**Tasks**

1. Read `backend/app/api/v1/studies.py:213-266` end-to-end to confirm the `_err` pattern and `try/except` chain order before edit.
2. Add the new validate call after the `validate_against_template` block but BEFORE the `query_set = await repo.get_query_set(...)` lookup at L268-270 — the reservation check is a pure-domain operation and shouldn't block on FK lookups.
3. Import `validate_normalizer_reservation`, `NormalizerChoiceInvalidError`, `NormalizerParamShapeError` from `backend.app.domain.study.normalizers`.
4. Add the second `SearchSpace.model_validate(body.search_space)` call (already invoked at L213; pass the result through a local variable to avoid double-validation). **Cleanup note:** the existing L259 also re-validates — leave it as-is in this story to keep the diff narrow; consider consolidating to one call in a follow-up refactor story if it becomes noisy.
5. Repeat for `query_templates.py` — add `from backend.app.domain.study.template_validator import ReservedParamReferenced` and the new `except` clause.
6. Verify spec precedence: `INVALID_SEARCH_SPACE` (Pydantic ValidationError at L214) fires BEFORE `NORMALIZER_CHOICE_INVALID` / `NORMALIZER_PARAM_SHAPE` (only run on validated `SearchSpace`). Add a test case in 2.1's DoD asserting both paths.

**Definition of Done (DoD)**
- `make test-contract` green; the new contract test (Story 7's `test_studies_normalizer_reservation_contract.py`) lands in §3.3 and exercises the three new envelopes.
- A manual `curl` (or HTTPX test) against a running stack produces the spec §8.3 envelope verbatim for each new code.
- Spec AC-2 verified (`POST /studies` returns 400 `NORMALIZER_CHOICE_INVALID` when a choice is outside the allowlist).

### Story 2.2 — `ElasticAdapter.render` pre-render hook (FR-3)

**Outcome:** When `params["query_normalizer"]` is present, `query_text` enters the Jinja context normalized. When absent, behavior is identical to today. Covers both Elasticsearch and OpenSearch (same adapter).

**Modified files**

| File | Change |
|---|---|
| `backend/app/adapters/elastic.py` | At the top of `render` (after the `from jinja2 import UndefinedError` block at L539-541, before the missing-params check at L543), insert the pre-render hook: copy `params` to `local_params`, pop `"query_normalizer"` defaulting to `DEFAULT_NORMALIZER`, apply `normalize(query_text, choice)` → `normalized`, build context as `{**local_params, "query_text": normalized}`. The missing-params check at L543-545 MUST run against `local_params` (post-pop). |

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/adapters/test_elastic_render_normalizer.py` | Covers AC-3 + invariant that caller's `params` dict is unmutated. |

**Key interfaces**

```python
# backend/app/adapters/elastic.py — modified render()
from backend.app.domain.study.normalizers import DEFAULT_NORMALIZER, normalize

def render(self, template, params, query_text):
    local_params = dict(params)   # copy — never mutate the caller's dict
    choice = local_params.pop("query_normalizer", DEFAULT_NORMALIZER)
    normalized = normalize(query_text, choice)   # raises ValueError on bad choice → existing render-failure path
    missing = set(template.declared_params) - set(local_params.keys())
    if missing:
        raise ValueError(f"render: missing required template params: {sorted(missing)}")
    context = {**local_params, "query_text": normalized}
    # ...existing Jinja render + NativeQuery construction unchanged...
```

**Tasks**

1. Add the two imports (`DEFAULT_NORMALIZER`, `normalize`) to `elastic.py`.
2. Rewrite the top of `render()` per the key-interfaces snippet above. The missing-params check now reads `local_params`, not `params`.
3. Important: `template.declared_params` still contains `"query_normalizer"` when the template declares it; the spec contract is that the adapter pops the key before computing `missing`, so the declared-vs-supplied check uses `local_params` AFTER the pop. **Re-verify** by re-reading the diff: missing = `set(declared) - set(local_params)`. `query_normalizer` is in declared but NOT in local_params (popped) — so it would falsely appear missing. **Correction needed:** also strip `"query_normalizer"` from the declared set before the diff: `missing = set(template.declared_params) - set(local_params.keys()) - {"query_normalizer"}`. The simpler equivalent: subtract `{"query_normalizer"}` from declared OR add it back to local_params for the check only. Use the explicit subtraction form for clarity.
4. Write `test_elastic_render_normalizer.py` with cases:
   - **Absent:** `params={}`, `query_text="HELLO"` → rendered body contains `"HELLO"` verbatim. (Backward-compat — existing templates unaffected.)
   - **Present, lowercase:** `params={"query_normalizer": "lowercase"}`, `query_text="HELLO"` → rendered body contains `"hello"`.
   - **Present, full bundle:** spec AC-3 verbatim — template body `'{"query": {"match": {"title": "{{ query_text }}"}}}'`, declared_params `{"query_normalizer": "string"}`, params `{"query_normalizer": "lowercase+trim+expand_contractions"}`, query_text `"What\'s the BEST policy?"` → `NativeQuery.body["query"]["match"]["title"] == "what is the best policy?"`.
   - **Invariant — caller's params unmutated:** AC-3's second clause. Pass `params = {"query_normalizer": "lowercase", "title_boost": 2.0}`; capture identity; call render; assert the SAME dict still contains both keys after.
   - **Defense-in-depth fallback (FR-1 second clause):** simulate a caller that bypasses `compute_default_params` by calling render with `params={}` against a template whose `declared_params = {"query_normalizer": "string", "title_boost": "float"}` and `query_text="HELLO"`. The hook MUST default to `DEFAULT_NORMALIZER="none"` (return value `"HELLO"` unchanged) — and the `missing` check correctly flags `"title_boost"` (not `"query_normalizer"`) as missing.
   - **Invalid value:** `params={"query_normalizer": "stem"}` → `ValueError` from `normalize`; trial-runtime failure path subsumed under existing render-failure handling.

**Definition of Done (DoD)**
- `make test-unit` green; new test file passes.
- All existing `test_elastic_render.py` tests still pass (backward compatibility — the hook is a no-op when the key is absent).
- AC-3 verified.

### Story 2.3 — `SolrAdapter.render` pre-render hook (FR-4)

**Outcome:** Identical algorithm to Story 2.2 applied to `SolrAdapter.render`. Cross-engine behavioral parity proof point.

**Modified files**

| File | Change |
|---|---|
| `backend/app/adapters/solr.py` | At `render` L1099-1108, insert the same pre-render hook from Story 2.2. The LTR pre-flight (`_check_ltr_model_available` at L1122-1124) and `_pivot_to_solr_params` (L1126) both run AFTER the rendered dict is built, so they're downstream of `query_text` substitution and independent of normalization. |

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/adapters/test_solr_render_normalizer.py` | Mirrors `test_elastic_render_normalizer.py` against `SolrAdapter`. |

**Tasks**

1. Add the two imports to `solr.py`.
2. Apply the same edit pattern as Story 2.2 at L1099-1108, with the same explicit `{"query_normalizer"}` subtraction from declared.
3. Write `test_solr_render_normalizer.py` mirroring the Elastic test cases:
   - **Absent:** AC-4 negative case (params={}, query_text passes through).
   - **Present, lowercase:** AC-4 verbatim — body `'{"defType": "edismax", "q": "{{ query_text }}", "qf": "title"}'`, params `{"query_normalizer": "lowercase"}`, query_text `"HELLO"` → returned `NativeQuery.body["q"] == "hello"`.
   - **Present, expand_contractions** + invariant immutability of caller's params dict.
   - **Defense-in-depth fallback** (identical to Story 2.2).
   - **Invalid value** raises `ValueError`.
4. **Cross-engine portability proof point** (added per parent prompt): write a single parametrized `pytest` test at `backend/tests/unit/adapters/test_render_normalizer_cross_engine.py` that takes a list `[ElasticAdapter, SolrAdapter]`, runs `query_text="What\'s GOOD?"` with `query_normalizer="lowercase+trim+expand_contractions"` through each, and asserts both produce a rendered body whose `query_text` substitution slot equals `"what is good?"`. This locks the FR-4 cross-engine invariant (spec: "Behavior MUST be observable as identical across ES + OpenSearch and Solr").

**Definition of Done (DoD)**
- `make test-unit` green; both new test files pass.
- Existing Solr render/explain/get_document tests still pass.
- AC-4 + the new cross-engine parametrized test verified.

**Epic 2 gate** — loop can run a normalizer study end-to-end backend-only:
- [ ] Stories 2.1, 2.2, 2.3 DoDs satisfied.
- [ ] Integration test from §3.2 (`test_trial_runner_normalizer.py`) green.
- [ ] Adversarial grep per spec §16 release gate: `grep -rn "query_normalizer" backend/app/services backend/app/agent backend/workers/trials.py backend/workers/baseline.py backend/workers/judgments.py backend/workers/orchestrator.py` returns ZERO non-pass-through hits (consumption-only invariant I-2).

---

## Epic 3 — PR-body "Operator-side requirement" section

### Story 3.1 — `_render_pr_body_study_backed` extension (FR-5)

**Outcome:** When `config_diff["query_normalizer"]` exists, the PR markdown body grows a new `## Operator-side requirement` section between `## Config diff` and `## Suggested follow-ups`. The chosen normalizer is named in inline code; a Python snippet from `_PR_BODY_NORMALIZER_SNIPPETS` is embedded for the three non-`none` choices; the `none` case renders an explanatory line with no snippet. `_render_pr_body_manual` is NOT modified (invariant I-3).

**Modified files**

| File | Change |
|---|---|
| `backend/workers/git_pr.py` | Insert the conditional section in `_render_pr_body_study_backed` between L580 (end of `## Config diff` block, after the trailing `lines.append("")`) and L581 (`if digest is not None and digest.suggested_followups`). |

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/workers/test_git_pr_body_normalizer.py` | Covers AC-5, AC-6, AC-7 + defense-in-depth invalid-value fallthrough. |

**Key interfaces**

```python
# backend/workers/git_pr.py — added inside _render_pr_body_study_backed
from backend.app.domain.study.normalizers import (
    NORMALIZER_CHOICES, _PR_BODY_NORMALIZER_SNIPPETS,
)

# ... after the existing "## Config diff" block ...
if "query_normalizer" in config_diff:
    choice = config_diff["query_normalizer"]["to"]
    lines.append("## Operator-side requirement")
    lines.append("")
    if choice not in NORMALIZER_CHOICES:
        logger.warning("pr_body: unknown normalizer in config_diff: %r — falling through to 'none'", choice)
        choice = "none"
    if choice == "none":
        lines.append(
            "**Chosen normalizer:** `none`. No production-side change is "
            "required — the loop confirmed the un-normalized query already wins."
        )
        lines.append("")
    else:
        lines.append(
            "RelyLoop measured the gain above against a query-time normalizer "
            "it applied before the query reached the engine. To reproduce the "
            "gain in production, your query-serving layer **MUST** apply the "
            "same normalizer to incoming queries before they hit the engine."
        )
        lines.append("")
        lines.append(f"**Chosen normalizer:** `{choice}`")
        lines.append("")
        lines.append("Reference implementation (Python — adapt to your language as needed):")
        lines.append("")
        lines.append("```python")
        lines.append(_PR_BODY_NORMALIZER_SNIPPETS[choice])
        lines.append("```")
        lines.append("")
```

**Tasks**

1. Add the imports to the top of `git_pr.py`.
2. Insert the conditional block at the location named above (between current L580 and L581 — the exact line number may drift; anchor by "after `## Config diff` block, before `## Suggested follow-ups`").
3. Write `test_git_pr_body_normalizer.py`:
   - **AC-5:** `config_diff = {"query_normalizer": {"from": "none", "to": "lowercase+trim+expand_contractions"}, "title_boost": {"from": 1.0, "to": 1.5}}` → output contains literal `## Operator-side requirement`, the line `` **Chosen normalizer:** `lowercase+trim+expand_contractions` ``, AND a fenced ` ```python ` block whose interior is **byte-equal** to `_PR_BODY_NORMALIZER_SNIPPETS["lowercase+trim+expand_contractions"]`.
   - **AC-6:** `config_diff = {"title_boost": {"from": 1.0, "to": 1.5}}` → output does NOT contain `## Operator-side requirement`.
   - **AC-7:** `config_diff = {"query_normalizer": {"from": "lowercase", "to": "none"}}` → output contains `## Operator-side requirement` AND the explanatory line for `none` AND NO fenced Python code block in that section.
   - **Defense-in-depth (FR-5 unreachable path):** `config_diff = {"query_normalizer": {"from": "none", "to": "stem"}}` → output renders the `none` branch (fall-through per spec FR-5) AND a logged warning is captured by caplog.
   - **I-3 invariant check:** assert `_render_pr_body_manual` ignores `query_normalizer` (passes `config_diff` containing it; output does NOT contain `## Operator-side requirement`).

**Definition of Done (DoD)**
- `make test-unit` green; new test passes.
- AC-5 + AC-6 + AC-7 verified.
- Existing `test_pr_body_render.py` + `test_pr_body_confidence_section.py` still pass (section is purely additive).

**Epic 3 gate:**
- [ ] Story 3.1 DoD satisfied.
- [ ] PR body for a normalizer-tuning study renders the section in the proposal-detail preview (visual spot-check after Epic 4 ships the UI; no blocking).

---

## Epic 4 — Frontend wiring (Categorical row + glossary + digest advisory)

### Story 4.1 — Digest panel analyzer-redundancy advisory (FR-6)

**Outcome:** When (i) `recommended_config.query_normalizer` ∈ {`lowercase`, `lowercase+trim`, `lowercase+trim+expand_contractions`} AND (ii) engine is ES or OpenSearch AND (iii) schema has at least one `text` field with `analyzer ∈ {"standard", "english", "simple"}` OR `"lowercase"` substring (note: `whitespace` excluded per spec), an informational line renders above the `recommended_config` JSON block. Hidden in every other case (Solr, `none` choice, schema loading/error/404, predicate-false).

**UI element inventory**

This story modifies an existing component (`digest-panel.tsx`) and adds two new TanStack Query hook calls at the parent page (`ui/src/app/studies/[id]/page.tsx`). All visual additions are inside the existing `Recommended config` section's `<div>`.

| Element | Type | Data source | Conditional |
|---|---|---|---|
| Advisory line | `<p>` with `text-sm text-muted-foreground` + `InfoTooltip` | Glossary key `digest.normalizer_advisory` (NEW) | All three predicate conjuncts must hold (see FR-6) |
| Wrapping inline structure | `<p>` + `<InfoTooltip>` mirror of the existing tooltip patterns in `digest-panel.tsx` (`digest.recommended_config`, `digest.metric_delta`, etc.) | — | Same conditional |

**State dependency analysis**

Two new props on `DigestPanel`:
- `engineType?: EngineType | undefined` — passed from parent; sourced from `useCluster(study.cluster_id).data?.engine_type`.
- `schema?: Schema | undefined` — passed from parent; sourced from `useClusterSchema(study.cluster_id, study.target)`.

Both are optional. The advisory predicate evaluates `false` when either is undefined (loading / error / pre-fetch).

**Frontend data plumbing verification** (per plan §11.9 — verified against current code):
- `study.cluster_id` — exists on `StudyDetail` (already consumed by `StudyHeaderWithSyntheticChip` at `page.tsx:208`).
- `study.target` — exists on `StudyDetail` (column in `studies` table; verified in `backend/app/db/models/study.py`).
- `useCluster` hook — already exists at `ui/src/lib/api/clusters.ts:83` and already returns `engine_type`.
- `useClusterSchema(id, target)` hook — already exists at `ui/src/lib/api/clusters.ts:130-141` (with `target` as a query param against `GET /api/v1/clusters/{id}/schema?target=...`). **Spec correction note:** the spec's FR-6 references "the existing `GET /api/v1/clusters/{id}/targets/{target}/schema` endpoint" — the actual route is `GET /api/v1/clusters/{id}/schema?target=<target>` (verified at `backend/app/api/v1/clusters.py:385-393`). Functionally equivalent; the hook is already abstracted. No backend route change needed. **Patch the spec post-implementation** to remove the incorrect path shape (capture as a Low-severity finding for the spec author).

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/studies/digest-panel.tsx` | Add `engineType?: EngineType` + `schema?: Schema` to `DigestPanelProps`. Add a `shouldShowAdvisory(...)` pure helper (declared at module top — easier to unit-test). Render the `<p>` advisory inside the existing `<div>` containing the "Recommended config" title + `<pre>` (insertion point: between L84-86 "Recommended config" tooltip block and L87 `<pre>`). |
| `ui/src/app/studies/[id]/page.tsx` | Import `useClusterSchema`. Add `clusterQ = useCluster(study.cluster_id)` and `schemaQ = useClusterSchema(study.cluster_id, study.target)` to `StudyDetailView` (inside the `<DetailPageShell>` render-prop where `study` is in scope — anchor: the existing `<DigestPanel>` call at L112-118). Pass `engineType={clusterQ.data?.engine_type}` and `schema={schemaQ.data}` to `<DigestPanel>`. |
| `ui/src/lib/glossary.ts` | Add the six new keys per spec §11 "Tooltips and contextual help" table. |

**New files**

| File | Purpose |
|---|---|
| `ui/src/__tests__/components/studies/digest-panel.normalizer-advisory.test.tsx` | Covers AC-8, AC-9, AC-10. |

**Key interfaces**

```ts
// ui/src/components/studies/digest-panel.tsx (added)
import type { EngineType } from '@/lib/enums';
import type { Schema } from '@/lib/api/clusters';

const LOWERCASE_APPLYING_ANALYZERS = new Set(['standard', 'english', 'simple']);

export function shouldShowNormalizerAdvisory(
  recommendedConfig: Record<string, unknown> | null | undefined,
  engineType: EngineType | undefined,
  schema: Schema | undefined,
): boolean {
  if (!engineType || !schema) return false;
  if (engineType === 'solr') return false;
  const choice = recommendedConfig?.query_normalizer;
  if (typeof choice !== 'string') return false;
  if (choice === 'none') return false;
  // Conjunct 2: at least one text-typed field with an overlapping analyzer.
  return schema.fields.some((f) => {
    if (f.type !== 'text') return false;
    const a = f.analyzer;
    if (!a) return false;
    return LOWERCASE_APPLYING_ANALYZERS.has(a) || a.includes('lowercase');
  });
}
```

**Analogous markup pattern — from existing digest-panel.tsx:83-89:**

```tsx
{/* Existing "Recommended config" block, line 82-90 */}
<div>
  <p className="flex items-center gap-1 text-xs uppercase text-muted-foreground">
    Recommended config
    <InfoTooltip glossaryKey="digest.recommended_config" />
  </p>
  {/* NEW: advisory line inserted here (between the title <p> and the <pre>) */}
  {shouldShowNormalizerAdvisory(digest.recommended_config, engineType, schema) && (
    <p
      className="mt-1 flex items-center gap-1 text-sm text-muted-foreground"
      data-testid="digest-normalizer-advisory"
    >
      The winning normalizer applies lowercasing, which your field analyzer
      already does. The loop still found a measurable gain — the duplication
      is harmless. Production parity is required for the gain to reproduce.
      <InfoTooltip glossaryKey="digest.normalizer_advisory" />
    </p>
  )}
  <pre className="mt-1 max-h-48 overflow-auto rounded-md border bg-muted/40 p-2 text-xs">
    {JSON.stringify(digest.recommended_config, null, 2)}
  </pre>
</div>
```

The advisory text itself is sourced from the new `digest.normalizer_advisory` glossary key — Story 4.1 ships the glossary entry; the rendered `<p>` reads from the glossary via a small helper OR inlines the text matching the glossary entry verbatim (the same pattern as `digest.recommended_config`'s tooltip-only model — recommend inlining the text in the JSX and asserting in a test that it equals the glossary entry, so the lint guard at `ui/src/__tests__/lib/glossary.test.ts` catches drift).

**Failure / loading behavior** (FR-6 explicit):
- `schemaQ.isLoading` → `schemaQ.data === undefined` → predicate returns false → advisory hidden.
- `schemaQ.error` (any HTTP failure incl. 404 / 503) → `schemaQ.data === undefined` → advisory hidden.
- `clusterQ` likewise.

No spinner, no error message. The advisory is purely informational — silent hide on any uncertainty.

**Tasks**

1. Read current `digest-panel.tsx` end-to-end (143 lines verified).
2. Add the props + the pure helper at module top.
3. Insert the JSX per the analogous pattern above.
4. Modify `page.tsx` to fetch and pass both new props.
5. Add the six glossary keys to `ui/src/lib/glossary.ts` per the spec §11 tooltip-inventory table (use the canonical key spellings — note `+` → `_` sanitization for the choice keys).
6. Write `digest-panel.normalizer-advisory.test.tsx`:
   - **AC-8 visible:** recommended_config `{"query_normalizer": "lowercase+trim"}`, engineType `"elasticsearch"`, schema `{fields: [{name: "title", type: "text", analyzer: "standard"}, ...]}` → `data-testid="digest-normalizer-advisory"` is present; its text matches the glossary entry.
   - **AC-9 hidden Solr:** same recommended_config + engineType `"solr"` → testid NOT present.
   - **AC-10 hidden none:** `query_normalizer = "none"` + engineType `"elasticsearch"` + permissive schema → testid NOT present.
   - **Hidden loading:** schema `undefined` → testid NOT present.
   - **Hidden whitespace analyzer (spec false-positive guard):** analyzer `"whitespace"` only → testid NOT present.
   - **Visible lowercase-containing analyzer:** custom analyzer named `"my_custom_lowercase_pipe"` → testid present.

**Definition of Done (DoD)**
- `pnpm test` green; new test passes.
- `pnpm typecheck` clean.
- `pnpm build` clean.
- Existing `digest-panel` tests still pass.
- AC-8 + AC-9 + AC-10 verified.

### Story 4.2 — Frontend enum source-of-truth + glossary keys + categorical row conditional rendering (FR-7)

**Outcome:** `NORMALIZER_VALUES` + `NORMALIZER_GLOSSARY_KEYS` exported from `enums.ts` with discipline comment. The `row-categorical.tsx` chip-input renders normally for non-reserved Categorical params, AND treats `param.choices` as the canonical subset (NOT `NORMALIZER_VALUES` as universe) when `paramName === "query_normalizer"`, using glossary keys for labels.

**Spec-vs-codebase note:** `row-categorical.tsx` is currently a **chip-input pattern** (operator types comma-separated values into an `<Input>`, chips render via `<Badge>`). The spec's FR-7 references a `<Select>`-based UI with `<SelectItem>` elements. This is a **semantic mismatch** with the existing component shape — the existing component lets operators type **arbitrary categorical values** (used for boost choices, operator strings, etc.). For `query_normalizer`, the spec requires constraining to four allowed values from a `<Select>` rather than allowing free-form chip entry.

**Resolution (decision applied at plan time per pre-approval):** Branch the rendering inside `row-categorical.tsx` based on `paramName`. For `query_normalizer`, render a `<Select>` whose `<SelectItem>` list is `param.choices.map(...)` (NOT the full `NORMALIZER_VALUES` — operator's declared subset is honored per FR-7) with labels resolved via `NORMALIZER_GLOSSARY_KEYS`. The chip-input fallback continues to serve all other Categorical params unchanged. This preserves backward compatibility for existing templates and lands the spec's FR-7 contract for the reserved key.

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/enums.ts` | Add `NORMALIZER_VALUES` (with discipline comment pointing at `backend/app/domain/study/normalizers.py NORMALIZER_CHOICES`) + `NormalizerValue` type + `NORMALIZER_GLOSSARY_KEYS` map. |
| `ui/src/lib/glossary.ts` | Add the six new keys (already on Story 4.1's task list — claim that one if Epic 4 stories ship in 4.1→4.2 order; otherwise this story ships them). Either way, ONE story owns the addition. **Owner: Story 4.1** for the digest.normalizer_advisory key, **Story 4.2** for the five `search_space.query_normalizer.*` keys. |
| `ui/src/components/studies/search-space-builder/row-categorical.tsx` | Branch on `paramName === "query_normalizer"`. New branch renders `<Select>` with `param.choices.filter(c => NORMALIZER_VALUES.includes(c))` (defense-in-depth filter + console.warn on stray) wrapped through a label map. |

**New files**

| File | Purpose |
|---|---|
| `ui/src/__tests__/components/studies/row-categorical.normalizer-source-of-truth.test.tsx` | Covers AC-11. |

**Key interfaces**

```ts
// ui/src/lib/enums.ts (added)
// Values must match backend/app/domain/study/normalizers.py NORMALIZER_CHOICES
export const NORMALIZER_VALUES = [
  'none',
  'lowercase',
  'lowercase+trim',
  'lowercase+trim+expand_contractions',
] as const;
export type NormalizerValue = (typeof NORMALIZER_VALUES)[number];

export const NORMALIZER_GLOSSARY_KEYS: Record<NormalizerValue, GlossaryKey> = {
  'none': 'search_space.query_normalizer.choice.none',
  'lowercase': 'search_space.query_normalizer.choice.lowercase',
  'lowercase+trim': 'search_space.query_normalizer.choice.lowercase_trim',
  'lowercase+trim+expand_contractions':
    'search_space.query_normalizer.choice.lowercase_trim_expand_contractions',
};
```

**Tasks**

1. Add `NORMALIZER_VALUES`, `NormalizerValue`, and `NORMALIZER_GLOSSARY_KEYS` to `enums.ts` with the discipline comment.
2. Add the five `search_space.query_normalizer.*` glossary keys to `glossary.ts` per spec §11 table (the `digest.normalizer_advisory` key was added in Story 4.1).
3. In `row-categorical.tsx`, branch on `paramName === "query_normalizer"`. New branch:
   - Validate `param.choices ⊆ NORMALIZER_VALUES` at render time; `console.warn` and filter strays (defense-in-depth — FR-2 already guarantees this server-side).
   - Render `<Select>` (shadcn/ui primitive — check `ui/src/components/ui/select.tsx` for the existing wrapper) with one `<SelectItem>` per `valid_choice` in the filtered subset, label resolved via `glossary[NORMALIZER_GLOSSARY_KEYS[valid_choice]]`.
   - Wire `onChange` to the existing `onChange(next: Choice[])` callback so the param flows back into the search-space state machine. (The reserved-key reservation is a single-select, so `onChange([value])` on each pick.) Note: the spec's FR-7 implies `onChange` semantics matching the existing chip-input — i.e. the parent expects an array. For a single-select reserved key, the array carries one element.
4. Source-of-truth comment: above the new `<Select>` block, add `// Values must match backend/app/domain/study/normalizers.py NORMALIZER_CHOICES (via NORMALIZER_VALUES re-export)`.
5. Write `row-categorical.normalizer-source-of-truth.test.tsx`:
   - **AC-11 a:** non-reserved Categorical (`paramName="operator"`, `choices=["AND", "OR"]`) → renders the existing chip-input shape (verify by checking for `cs-row-operator-choices-input` testid).
   - **AC-11 b:** `paramName="query_normalizer"`, `choices=["none", "lowercase+trim"]` → renders a `<Select>` with EXACTLY two `<SelectItem>` elements; values `"none"` and `"lowercase+trim"`; labels match the glossary lookups.
   - **AC-11 c:** submitted payload (assert `onChange` was called with `["lowercase+trim"]` after a click on the second option, not the full four-value universe).
   - **AC-11 d (defense-in-depth):** `choices=["none", "stem"]` (stray) → only one `<SelectItem>` renders (for `"none"`); `console.warn` is called.
   - **Form-select-discipline lint:** the new `<Select>` branch uses `param.choices.map(...)` (NOT inline `<SelectItem value="none">` literals). The vitest lint guard at `ui/src/__tests__/components/common/form-select-discipline.test.tsx` should auto-detect compliance; verify by running it.

**Definition of Done (DoD)**
- `pnpm test` + `pnpm typecheck` + `pnpm build` green.
- `ui/src/__tests__/components/common/form-select-discipline.test.tsx` still passes (no inline `<SelectItem value="<wire>">` for normalizer values).
- `ui/src/__tests__/lib/glossary.test.ts` (length/jargon lint) passes on the six new keys.
- AC-11 verified.

**Epic 4 gate:**
- [ ] Stories 4.1 + 4.2 DoDs satisfied.
- [ ] Visual spot-check: create a normalizer-aware study against a local stack, confirm Categorical row renders correctly and digest advisory appears.

---

## Epic 5 — Documentation sweep

### Story 5.1 — Three doc updates (FR-8)

**Outcome:** Spec FR-8 docs land.

**Modified files**

| File | Change |
|---|---|
| `docs/01_architecture/optimization.md` | New sub-section under "Where RelyLoop fits in your relevance pipeline" titled "Normalizer tuning (MVP2)" linking back to this feature's `feature_spec.md` and naming the reserved key. |
| `docs/01_architecture/adapters.md` | New paragraph in the `SearchAdapter.render` section per spec FR-8: "The `render()` implementation is permitted to apply a deterministic pure-function transform to `query_text` before injecting it into the Jinja context, provided the transform is recorded in the trial's `params` JSONB as a Categorical search-space value the operator declared. The `query_normalizer` key is the reserved canonical instance." |
| `docs/03_runbooks/local-dev.md` | New section "Opting a template into normalizer tuning" with the exact `declared_params` + `search_space.params` diff (sample template + `POST /api/v1/query-templates` body). |
| `state.md` | Add the merge one-liner; archive longer narrative to `state_history.md`. |

**Tasks**

1. Read each target doc to confirm insertion points.
2. Write each section per spec FR-8 verbatim where the spec gives wording (adapters.md paragraph is mandated word-for-word).
3. Verify no `docs/04_security/llm-data-flow.md` change is needed (FR-8 explicitly says NO change — no LLM call introduced).
4. Update `state.md` per CLAUDE.md "state.md is a one-page snapshot, not a log" rule — prepend the merge one-liner, drop the 6th row; reasoning narrative goes to `state_history.md`.

**Definition of Done (DoD)**
- All three docs land in the same PR as the implementation.
- `state.md` + `state_history.md` updated.
- The 60 KB `state.md` size-gate pre-commit hook passes.

---

## Epic 6 — End-to-end verification

### Story 6.1 — Real-backend Playwright spec (AC-13)

**Outcome:** A single E2E spec exercises the operator's full path end-to-end against a live stack.

**New files**

| File | Purpose |
|---|---|
| `ui/tests/e2e/query-normalization.spec.ts` | Real-backend Playwright spec per CLAUDE.md "E2E Testing Rules". |

**Tasks**

Spec scope (verbatim from spec AC-13):
1. **Setup via API helpers** (acceptable per E2E rules):
   - Register a test ES cluster (use existing helpers from `signup_flow.spec.ts` or equivalent).
   - `POST /api/v1/query-templates` with `declared_params = {"query_normalizer": "string", "title_boost": "float"}` and a body that references `{{ title_boost }}` and `{{ query_text }}` but NOT `{{ query_normalizer }}`.
   - Create a query set + judgment list via API helpers.
2. **Real browser interaction** (mandatory per E2E rules — no `page.route()` mocking):
   - `page.goto(/studies/new)` → open create-study modal.
   - Fill template + cluster + query set selectors.
   - In the search-space builder, locate the `query_normalizer` row (testid pattern matches Story 4.2's component).
   - Submit via the modal's Create button → `POST /api/v1/studies` fires; redirected to the new study detail page.
3. **Wait for trials to complete:** `page.waitForSelector('[data-testid="study-page-summary"]')` and poll until study.status = `completed` (use existing trial-runner E2E patterns).
4. **Assert observable behavior:**
   - Trials table renders each trial's chosen `query_normalizer` (verify via `params` column cell text contains one of the four values).
   - Digest panel renders. If the cluster's `title` field uses the `standard` analyzer (the test fixture should configure this), the advisory line (testid `digest-normalizer-advisory`) is visible.
   - Navigate to the proposal preview page (proposal-detail UI) and assert the PR body markdown contains `## Operator-side requirement` AND `**Chosen normalizer:**` AND a fenced `python` block.
5. **No engine-log introspection** — AC-13 explicitly scopes to UI-observable behavior. Native-query normalization correctness at the engine boundary is covered by AC-3 / AC-4 + the §3.2 integration test.

**Definition of Done (DoD)**
- `cd ui && pnpm playwright test query-normalization.spec.ts` green against `make up` local stack.
- AC-13 verified.

**Epic 6 gate (release gate per spec §16):**
- [ ] All AC-1 through AC-13 pass.
- [ ] 80% backend coverage gate green.
- [ ] Frontend ESLint + tsc + vitest + Next build green.
- [ ] Glossary length lints green.
- [ ] Adversarial grep returns zero non-pass-through hits.

---

## 3) Testing workstream

Mapping every new/modified test to its story for ownership clarity (per Step 4 §5 of `/impl-plan-gen`).

### 3.1 Unit tests (8 new files)

Location: `backend/tests/unit/`.

| Test file | Story | Coverage |
|---|---|---|
| `domain/study/test_normalizers.py` | 1.1 | AC-1 |
| `domain/study/test_normalizers_pr_snippets.py` | 1.1 | AC-12 + I-4 |
| `domain/study/test_template_defaults_normalizer.py` | 1.2 | FR-1 regression guard (the spec cycle-2 fix) |
| `domain/study/test_search_space_normalizer_reservation.py` | 1.3 | FR-2 pure-domain |
| `domain/study/test_template_validator_reserved_param.py` | 1.3 | FR-2 template-validator extension |
| `adapters/test_elastic_render_normalizer.py` | 2.2 | AC-3 + adapter fallback (FR-1 second clause) |
| `adapters/test_solr_render_normalizer.py` | 2.3 | AC-4 + adapter fallback |
| `adapters/test_render_normalizer_cross_engine.py` | 2.3 | Cross-engine portability proof (FR-3 ≡ FR-4) |
| `workers/test_git_pr_body_normalizer.py` | 3.1 | AC-5, AC-6, AC-7, defense-in-depth |

**DoD:** Critical branches covered; deterministic.

### 3.2 Integration tests (1 new file)

Location: `backend/tests/integration/`.

| Test file | Story | Coverage |
|---|---|---|
| `workers/test_trial_runner_normalizer.py` | 2.2 + 2.3 (cross-story) — assigned to **Story 2.3** as the last story that completes the testable surface | I-2 invariant: seed a template + study with the four-choice reservation; run the trial runner; assert each trial's `params` JSONB records a value from `NORMALIZER_CHOICES` AND each native query body reflects normalization. |

**DoD:** Happy path + critical failure paths covered.

### 3.3 Contract tests (1 new file)

Location: `backend/tests/contract/`.

| Test file | Story | Coverage |
|---|---|---|
| `test_studies_normalizer_reservation_contract.py` | 2.1 | Asserts `POST /api/v1/studies` returns the spec §8.3 envelope verbatim for `NORMALIZER_CHOICE_INVALID` and `NORMALIZER_PARAM_SHAPE`. Also asserts `POST /api/v1/query-templates` returns the envelope for `RESERVED_PARAM_REFERENCED`. Three error codes × one envelope-shape assertion each. |

**DoD:** Every new error code from spec §8.5 has at least one contract-test assertion.

### 3.4 E2E tests (1 new file)

Location: `ui/tests/e2e/`.

| Test file | Story | Coverage |
|---|---|---|
| `query-normalization.spec.ts` | 6.1 | AC-13 — UI-observable end-to-end flow. |

**Rule:** Real-backend per CLAUDE.md "E2E Testing Rules". No `page.route()`. Setup via API helpers; assertions via `page` object.

**DoD:** Stable profile pass; tests use `page` for browser interactions, not just `request`.

### 3.5 Frontend vitest (2 new files)

Location: `ui/src/__tests__/`.

| Test file | Story | Coverage |
|---|---|---|
| `components/studies/digest-panel.normalizer-advisory.test.tsx` | 4.1 | AC-8, AC-9, AC-10 |
| `components/studies/row-categorical.normalizer-source-of-truth.test.tsx` | 4.2 | AC-11 + form-select-discipline parity |

### 3.6 Existing test impact

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/unit/adapters/test_elastic_render.py` | `render()` shape assertions | unchanged | No change — existing tests assert behavior when `query_normalizer` is absent; the hook is a no-op in that path. **Verify** by running this test file after Story 2.2 with no edits. |
| `backend/tests/unit/domain/study/test_template_validator.py` | `_IMPLICIT_PARAMS` cross-check | unchanged | No change — `query_normalizer` is declared, not implicit. **Verify** by running. |
| `backend/tests/unit/domain/study/test_search_space.py` | `CategoricalParam` / `apply_search_space` | unchanged | No change — reuses existing Categorical path. |
| `backend/tests/unit/workers/test_pr_body_render.py` | PR markdown body shape | unchanged | No change — Section 3.1 is additive. The new section renders ONLY when `query_normalizer in config_diff`; existing tests don't seed that key. **Verify.** |
| `ui/src/__tests__/components/common/form-select-discipline.test.tsx` | Scan for inline `<SelectItem value="<literal>">` for wire values in `enums.ts` | augmented automatically | The new `<Select>` in `row-categorical.tsx` uses `.map()` — the lint guard verifies. |
| `ui/src/__tests__/lib/glossary.test.ts` | Length / jargon lint | augmented automatically | Six new keys go through the same lint; no test code changes. |

### 3.7 Migration verification

**N/A — no migration ships with this feature.** The Alembic head stays at `0022_solr_engine_auth_check`. Skip §3.5 migration round-trip; document explicitly so the verification gate doesn't ask for evidence.

### 3.8 CI gates

- [ ] `make test-unit`
- [ ] `make test-integration` (runs the new trial-runner test against service-container ES)
- [ ] `make test-contract`
- [ ] `cd ui && pnpm test`
- [ ] `cd ui && pnpm playwright test query-normalization.spec.ts` (against `make up` stack)
- [ ] 80% backend coverage gate
- [ ] Glossary length lints
- [ ] Form-select-discipline lint

---

## 4) Documentation update workstream

### 4.0 Core context files

**`state.md`** — update at finalization:
- [ ] "Last 5 merges" prepended with the one-liner.
- [ ] If this lands as feature 2 of the multi-feature `feature/mvp2-top5-plans` batch, the parent pipeline aggregates merges; otherwise this story owns the line.
- [ ] Alembic head NOT moved (no migration).

**`architecture.md`** — update if:
- [ ] The new `_RESERVED_NONRENDER_PARAMS` discipline is worth capturing as a system-level invariant (recommendation: yes — one bullet under the search-space discipline section, pointing at the spec and the normalizers module).

**`CLAUDE.md`** — update if:
- [ ] No new absolute rule; no new env var; no build-command change. **No update.**

### 4.1 Architecture docs (`docs/01_architecture/`)

- [ ] `optimization.md` — see Story 5.1.
- [ ] `adapters.md` — see Story 5.1.

### 4.2 Product docs (`docs/02_product/`)

No update — operator-facing capability is documented via the runbook + the PR body itself.

### 4.3 Runbooks (`docs/03_runbooks/`)

- [ ] `local-dev.md` — see Story 5.1.

### 4.4 Security docs (`docs/04_security/`)

No update — no new data flow, no new credentials, no LLM call.

### 4.5 Quality docs (`docs/05_quality/`)

No update — testing convention covers the new test layers.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- Avoid double `SearchSpace.model_validate` calls in the studies router (currently L213 + L259). Consolidate to one call passing the result through a local variable.

### 5.2 Planned refactor tasks

- [ ] **Out-of-scope for this feature.** Captured as a tangential observation: the studies router calls `SearchSpace.model_validate(body.search_space)` twice — once at L213 (top-level INVALID_SEARCH_SPACE check) and again at L259 (inside the `validate_against_template` call). Story 2.1's wiring adds a third call indirectly. If the refactor is ≤50 LOC and doesn't introduce new tests, do it inline in Story 2.1; otherwise capture as a separate `chore_studies_router_validate_consolidation` idea file under `docs/00_overview/planned_features/00_unsure/`.

**Per CLAUDE.md "Inline-fix vs idea-file rubric":** The two-call collapse is ≤20 LOC, no new tests, work-type matches (backend → backend). **Recommendation: inline in Story 2.1's commit OR an adjacent commit on the same branch.** Not an idea file.

### 5.3 Refactor guardrails

- Behavioral parity proven by existing contract tests + the new Story 2.1 contract test.
- Lint/typecheck remain green.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `ElasticAdapter.render` exists at `backend/app/adapters/elastic.py:521` | Story 2.2 | Implemented (MVP1, PR #16) | None — shipped. |
| `SolrAdapter.render` exists at `backend/app/adapters/solr.py:1071` | Story 2.3 | Implemented (MVP2, PR #336, 2026-05-31) | None — shipped. |
| `compute_default_params` exists at `backend/app/domain/study/template_defaults.py:59` | Story 1.2 | Implemented (`feat_digest_proposal`) | None. |
| `validate_template_body` exists at `backend/app/domain/study/template_validator.py:64` | Story 1.3 | Implemented (`feat_study_lifecycle`) | None. |
| `_render_pr_body_study_backed` exists at `backend/workers/git_pr.py:540` | Story 3.1 | Implemented (`feat_github_pr_worker`) | None. |
| `useClusterSchema` + `useCluster` hooks exist at `ui/src/lib/api/clusters.ts:83 / :130` | Story 4.1 | Implemented | None — verified. |
| `<DigestPanel>` + `<InfoTooltip>` exist | Story 4.1 | Implemented | None. |
| `<Select>` shadcn primitive | Story 4.2 | Implemented at `ui/src/components/ui/select.tsx` (verified by glob) | None. |
| `_RESERVED_NONRENDER_PARAMS` does NOT currently exist | Story 1.3 | Net-new (added by 1.3) | N/A. |
| Phase 2 + Phase 3 deferred-work tracked | Spec §3 deferred-phase tracking | Relocated 2026-05-31 to sibling folders `feat_query_normalizer_typed_pipeline` + `feat_apply_path_normalizer_declaration` | Plan execution MUST NOT touch them. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Adapter hook breaks existing templates that don't declare `query_normalizer` | L | H | Hook short-circuits to `DEFAULT_NORMALIZER` when key absent; `normalize(qt, "none")` returns `qt` verbatim. Backward-compat test in Story 2.2 / 2.3 locks this. |
| `compute_default_params` extension misses a third declaration shape | L | M | Story 1.2 tests both simple-form (`"string"`) and rich-form (`{"type": "categorical", ...}`); a third shape would be a Pydantic violation rejected upstream. |
| Frontend `<Select>` branch breaks chip-input behavior for non-reserved Categoricals | L | M | Story 4.2 DoD includes the AC-11 (a) test asserting the chip-input still renders for `paramName="operator"`. |
| PR-body `none` branch unreadable to operators | L | L | Spec FR-5 mandates a specific copy; assertion in Story 3.1's AC-7 test. |
| Adversarial grep finds non-pass-through references after Epic 2 | L | H | The release gate in spec §16 names the exact grep command. Verify before merging Epic 2. Authoring sites (validator, PR-body, frontend, glossary, tests, docs) are EXEMPT per invariant I-2 — only `services/`, `agent/`, and the four named worker files are scoped to consumption-only. |
| Spec's FR-6 schema-endpoint path (`/targets/{target}/schema`) doesn't match actual route (`/clusters/{id}/schema?target=<target>`) | Realized | L | Story 4.1 plan notes the discrepancy; `useClusterSchema` already abstracts. Post-implementation, file a Low-severity finding to patch the spec (one-liner edit). |
| Smart-quote contractions silently fail (`"what’s"`) | Acknowledged | L (per spec D-7) | Test in Story 1.1 explicitly asserts smart-quote inputs round-trip unchanged. P3 deferred to `phase2_idea.md`. |

### Failure mode catalog

| Failure mode | Trigger | Expected behavior | Recovery |
|---|---|---|---|
| Trial-time invalid `query_normalizer` value | Direct DB mutation bypassing FR-2 reservation | `adapter.render` raises `ValueError` → existing render-failure path in `trials.py` records trial failure | Study continues with remaining trials; operator inspects failed trial's params |
| Schema endpoint 404 / 503 mid-render | Cluster removed / unreachable while study detail page is open | `useClusterSchema` returns `data: undefined`; advisory predicate evaluates false; advisory silently hidden | Re-fetch on cluster recovery; no operator action needed |
| Glossary key missing for an advisory | Story 4.1 ships without `digest.normalizer_advisory` | `InfoTooltip` renders nothing OR throws — depends on existing helper behavior | Length lint at `glossary.test.ts` MUST be augmented to include the new key (Story 4.1 task) |
| PR-body section renders with stale snippet drift | Spec I-4 round-trip test silently disabled | Story 1.1's snippet test asserts semantic equality on a 10-element corpus on every CI run | Test must be in `backend/tests/unit/`; failures block merge |

## 7) Sequencing and parallelization

### Suggested sequence (strict)

1. **Epic 1 — pure-domain layer** (Stories 1.1 → 1.2 → 1.3). Hard verification gate after 1.2.
2. **Epic 2 — adapter hook + router wiring** (Stories 2.1 → 2.2 → 2.3). Stories 2.2 and 2.3 can run in parallel within the same branch.
3. **Epic 3 — PR body** (Story 3.1).
4. **Epic 4 — frontend** (Stories 4.1, 4.2). Can run in parallel.
5. **Epic 5 — docs sweep** (Story 5.1).
6. **Epic 6 — E2E** (Story 6.1). Last because it needs the full backend + frontend wiring.

### Parallelization opportunities

- Within Epic 2: Stories 2.2 (Elastic) and 2.3 (Solr) are file-independent.
- Within Epic 4: Stories 4.1 and 4.2 touch different files (`digest-panel.tsx` vs `row-categorical.tsx`); both modify `glossary.ts` but for disjoint keys.
- Epic 5 (docs) can start as soon as Epic 1 lands — the docs reference shipped behavior abstractly and don't depend on UI.

## 8) Rollout and cutover plan

- **Rollout stages:** Single — feature ships in one PR. No feature flag.
- **Adoption:** Per spec §11 "Operator adoption mechanism" — operator opts in by POSTing a new template with `declared_params` containing `"query_normalizer": "string"`. No demo-seed template change ships.
- **Cutover:** None — no schema change, no in-flight state migration.
- **Reconciliation:** N/A.

## 9) Execution tracker (copy/paste)

### Current sprint
- [ ] Story 1.1 — normalizer module + contractions + snippets
- [ ] Story 1.2 — `compute_default_params` extension (verification gate)
- [ ] Story 1.3 — `validate_normalizer_reservation` + template-validator extension
- [ ] Story 2.1 — router wiring
- [ ] Story 2.2 — `ElasticAdapter.render` hook
- [ ] Story 2.3 — `SolrAdapter.render` hook + cross-engine parametrized test
- [ ] Story 3.1 — PR-body section
- [ ] Story 4.1 — digest advisory
- [ ] Story 4.2 — enum + glossary + row-categorical conditional rendering
- [ ] Story 5.1 — docs sweep
- [ ] Story 6.1 — E2E spec

### Blocked items
- _None._

### Done this sprint
- _None yet._

## 10) Story-by-Story Verification Gate

Before marking each story complete, attach evidence for:

- [ ] Files created/modified match the story's `New files` / `Modified files` tables.
- [ ] Endpoint contracts implemented exactly as documented (where applicable).
- [ ] Key interfaces match the signatures in the story.
- [ ] Tests for the relevant layers added and passing.
- [ ] `make test-unit`
- [ ] `make test-integration` (Epic 2 stories)
- [ ] `make test-contract` (Story 2.1)
- [ ] `cd ui && pnpm test` (Epic 4 stories)
- [ ] `cd ui && pnpm playwright test query-normalization.spec.ts` (Story 6.1)
- [ ] **Story 1.2 verification gate** — the hard stop before Epic 2. Cannot proceed without `test_template_defaults_normalizer.py` green AND the value-lock assertion in place.
- [ ] No migration round-trip needed (no schema change).
- [ ] Doc updates landed in same PR (Epic 5).

## 11) Plan consistency review

Performed at plan generation. Findings ledger below.

### Verification ledger

| Claim | Verified by | Status |
|---|---|---|
| Migration head is `0022_solr_engine_auth_check` | `ls migrations/versions/ \| sort \| tail -1` | Verified — no new migration needed |
| `ElasticAdapter.render` at `backend/app/adapters/elastic.py:521` builds context at L547 | Read elastic.py:510-554 | Verified |
| `SolrAdapter.render` at `backend/app/adapters/solr.py:1071` builds context at L1108 | Read solr.py:1060-1127 | Verified |
| `_render_pr_body_study_backed` at `backend/workers/git_pr.py:540` | Read git_pr.py:520-613 | Verified |
| `compute_default_params` at `backend/app/domain/study/template_defaults.py:59` | Read template_defaults.py end-to-end | Verified |
| `validate_template_body` at `backend/app/domain/study/template_validator.py:64` with `_IMPLICIT_PARAMS` at L57 | Read template_validator.py | Verified |
| `POST /api/v1/studies` router invokes `SearchSpace.model_validate` at L213 + `validate_against_template` at L257 | Read studies.py:200-280 | Verified |
| `POST /api/v1/query-templates` validates body via `validate_template_body` at L136 | Read query_templates.py:118-164 | Verified |
| `useClusterSchema(id, target)` hook exists at `ui/src/lib/api/clusters.ts:130` and calls `GET /api/v1/clusters/{id}/schema?target=<target>` | Read clusters.ts:130-141 | Verified |
| `useCluster` hook returns `engine_type` | Read clusters.ts:83 + verified `EngineType` import in studies page | Verified |
| `<DigestPanel>` props are passed from `ui/src/app/studies/[id]/page.tsx` at L112-118; `study.cluster_id` + `study.target` are in scope | Read page.tsx:1-125 | Verified |
| `<InfoTooltip glossaryKey="...">` is the canonical tooltip primitive | Found at `ui/src/components/common/info-tooltip.tsx:12` and consumed throughout `digest-panel.tsx` | Verified |
| `row-categorical.tsx` is a 138-line chip-input component (not a `<Select>`) | Read full file | **Spec discrepancy noted** — plan Story 4.2 adds a `<Select>` branch for the reserved key |
| FR-6 schema endpoint path | Spec says `/clusters/{id}/targets/{target}/schema`; actual is `/clusters/{id}/schema?target=<target>` | **Spec correction noted** — file Low-severity finding to patch post-impl; `useClusterSchema` already abstracts; no runtime impact |
| Phase 2 + Phase 3 deferred ideas relocated to sibling folders | `ls docs/00_overview/planned_features/02_mvp2/` → `feat_query_normalizer_typed_pipeline/`, `feat_apply_path_normalizer_declaration/` | Verified (moved 2026-05-31) |
| Alembic head | `ls migrations/versions/ \| sort \| tail -1` → `0022_solr_engine_auth_check` | Verified |

### Spec ↔ plan endpoint count

Spec §8.1 lists 5 affected endpoints, 0 new endpoints. Plan covers:
- `POST /api/v1/query-templates` — Story 2.1 wires `RESERVED_PARAM_REFERENCED`.
- `POST /api/v1/studies` — Story 2.1 wires `NORMALIZER_CHOICE_INVALID` + `NORMALIZER_PARAM_SHAPE`.
- `GET /api/v1/studies/{id}` — Story 4.1 reads `search_space.params.query_normalizer` from the study fetch.
- `GET /api/v1/studies/{id}/digest` — Story 4.1 reads `recommended_config.query_normalizer`.
- `GET /api/v1/proposals/{id}` — Story 3.1's PR-body change surfaces in this endpoint's response.

✅ All 5 endpoints covered.

### Spec ↔ plan error code coverage

Spec §8.5 lists 3 new error codes. Plan's contract test (Story 2.1's `test_studies_normalizer_reservation_contract.py`) covers all 3. ✅

### Spec ↔ plan FR coverage

All 8 FRs (FR-1 through FR-8) have rows in §1 and at least one story assigned. ✅

### Story internal consistency

- Stories 1.1 + 1.2 + 1.3 all touch `backend/app/domain/study/normalizers.py` but on different concerns (1.1 = core funcs + snippets; 1.3 = validator + exceptions). Stories add to the same file in sequence — no ownership conflict.
- Story 4.1 and 4.2 both modify `ui/src/lib/glossary.ts` but for disjoint keys (4.1 = `digest.normalizer_advisory`; 4.2 = five `search_space.query_normalizer.*` keys). Explicit ownership documented.
- All modified files referenced exist in the codebase (verified by glob).

### Test file count vs §3 inventory

§3 inventory: 8 unit + 1 integration + 1 contract + 1 E2E + 2 vitest = 13 new test files.
Story assignment confirms 13 distinct test files, each assigned to exactly one owning story. ✅

### Gate arithmetic

- Epic 1 gate: 3 stories' DoDs. ✅
- Epic 2 gate: 3 stories' DoDs + integration test + adversarial grep. ✅
- Epic 3 gate: 1 story. ✅
- Epic 4 gate: 2 stories. ✅
- Epic 6 release gate: matches spec §16 verbatim. ✅

### Open questions resolved

Spec §19: "_None._" All 4 idea-stage opens resolved into D-1..D-8. ✅

### Plan-level UI Guidance

Frontend stories (4.1 + 4.2) provided with:
- Insertion points: digest-panel.tsx L83-89; row-categorical.tsx file-level branching.
- Analogous markup patterns: existing `Recommended config` block JSX copied verbatim.
- Layout and structure: inline `<p>` inside existing `<div>` for advisory; `<Select>` shadcn primitive for reserved-key categorical row.
- Component composition: rendered inline within existing components (no new component extraction).
- Interaction behavior: digest-panel is read-only; row-categorical passes `onChange([value])` for the reserved-key single-select.
- Information architecture placement: spec §11 verbatim — Categorical row in create-study modal Step 4; advisory above recommended-config JSON; PR section between Config diff and Suggested follow-ups.
- Tooltips: six new glossary keys with sanitized identifiers. `InfoTooltip glossaryKey="..."` pattern used.
- Visual consistency table: covered in the analogous-markup snippet.

### Legacy behavior parity table

**Not required.** No story deletes or replaces a user-facing component >100 LOC. `digest-panel.tsx` (143 LOC) and `row-categorical.tsx` (138 LOC) are modified additively — no rewrite, no deletion. The chip-input default path stays; the `<Select>` branch is purely conditional on `paramName === "query_normalizer"`.

### Enumerated value contract verification

Spec §8.4 lists `NORMALIZER_CHOICES` as the backend allowlist. Frontend story 4.2 mirrors via `NORMALIZER_VALUES` with the `// Values must match` discipline comment. AC-11 enforces character-for-character parity. ✅

### Audit-event coverage

**N/A — audit_log lands at MVP3.** Spec §6 explicitly states "audit_log lands at MVP3" and lists no audit-event matrix. The state-mutating endpoint (`POST /api/v1/studies`) is unchanged from a mutation-recording perspective — only validation order changes. No audit-event gap.

### Cross-model review

**Skipped per operator decision** (parent prompt). The spec already ran 3 GPT-5.5 convergence cycles (recorded in `pipeline_status.md`), and the operator authorized Opus-only internal review for the plan. The two Opus passes (plan-internal + codebase-accuracy) recorded above completed cleanly — every spec finding mapped to a verified codebase claim or a tracked discrepancy (the FR-6 schema-endpoint path correction is the only Low-severity finding to file post-implementation).

### Hard blockers

**None.**

---

## 12) Definition of plan done

- [x] Every FR is mapped to stories/tasks/tests/docs updates.
- [x] Every story includes New files, Modified files, Key interfaces, Tasks, and DoD.
- [x] Test layers (unit/integration/contract/e2e/vitest) are explicitly scoped.
- [x] Documentation updates across docs/01-05 are planned and owned.
- [x] Lean refactor scope and guardrails are explicit (inline-fix recommended for the double `model_validate` call).
- [x] Phase/epic gates are measurable.
- [x] Story-by-Story Verification Gate included with the Story 1.2 hard stop.
- [x] Plan consistency review (§11) performed.

**Review log:**
- Mode: Generate.
- Source spec: `docs/00_overview/planned_features/02_mvp2/feat_query_normalization_tuning/feature_spec.md` (761 lines).
- Internal passes: 2 (plan-internal consistency + codebase accuracy).
- Cross-model review: Skipped per operator decision (spec already passed 3 GPT-5.5 convergence cycles).
- Spec-plan alignment status: All 8 FRs covered, all 13 ACs mapped, all 3 new error codes contract-tested.
- Open questions for user: **None — no hard blockers.**
- Findings to file post-implementation (Low severity, non-blocking): one spec edit to correct FR-6's schema-endpoint path from `/clusters/{id}/targets/{target}/schema` to `/clusters/{id}/schema?target=<target>`; functionally equivalent because `useClusterSchema` already abstracts.
- Proposed doc updates at finalization: `state.md` one-liner + `architecture.md` bullet on the `_RESERVED_NONRENDER_PARAMS` discipline.
