# bug_judgment_template_default_params_contract

## Status

Idea — captured during `chore_tutorial_polish` Story 3.1 operator-path
verification (PR pending). Pre-existing platform issue, not a regression
introduced by chore_tutorial_polish.

## Origin

Surfaced 2026-05-12 while running
[`backend/tests/smoke/test_tutorial_path.py`](../../../../backend/tests/smoke/test_tutorial_path.py)
end-to-end against `make up`. Judgment generation always failed with
`PARTIAL_LLM_FAILURE: 5 queries unrated` for any query template that
declared optimization params, regardless of which params or values were
declared.

## Problem

The `query_templates` API endpoint stores `declared_params` as
`dict[str, str]` (per
[`backend/app/api/v1/schemas.py:202`](../../../../backend/app/api/v1/schemas.py)
— `declared_params: dict[str, str] = Field(default_factory=dict)`).
Each value is a type-name string like `"float"`, `"int"`, `"string"`.

The judgment-generation worker at
[`backend/workers/judgments.py:189`](../../../../backend/workers/judgments.py)
calls
[`compute_default_params(template_row)`](../../../../backend/app/domain/study/template_defaults.py)
to fill in default values for the template's declared params before issuing
a candidate-search call. But `compute_default_params` expects each entry to
be a **rich-form dict** like `{"type": "float", "min": 0.5, "max": 5.0}` so
it can compute the midpoint:

```python
elif kind == "float":
    lo = schema.get("min")
    hi = schema.get("max")
    if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
        params[name] = (float(lo) + float(hi)) / 2.0
```

Against an API-stored simple-form schema, `schema.get("min")` returns
`None`, the `isinstance` check fails, and the param is silently omitted.
`default_params` ends up `{}`.

Then
[`adapter.render`](../../../../backend/app/adapters/elastic.py)
at line 493:

```python
missing = set(template.declared_params) - set(params.keys())
if missing:
    raise ValueError(f"render: missing required template params: {sorted(missing)}")
```

…raises `ValueError: render: missing required template params: [...]`,
the worker logs `judgment_search_failed`, every query gets skipped, and
the judgment list is marked `failed PARTIAL_LLM_FAILURE`.

Net effect: **every query template created via the API that declares any
optimization params is unusable for judgment generation.** Existing
integration tests skirt this by creating templates with `declared_params={}`
(see
[`backend/tests/integration/test_judgment_generate.py`](../../../../backend/tests/integration/test_judgment_generate.py)).

## Why deferred

`chore_tutorial_polish` is documentation + release polish — it MUST NOT
introduce schema changes per its own plan §0 line 5. Fixing this requires
either:

- Schema change: change `declared_params: dict[str, str]` →
  `declared_params: dict[str, ParamSchema]` where `ParamSchema` is the
  rich form. Migration to convert existing rows. Frontend impact.
- OR: extend `compute_default_params` to handle the simple-form schema with
  a default-value heuristic per type (e.g. `float → 1.0`, `int → 1`,
  `string → ""`, `bool → False`). Less faithful, but no schema impact.
- OR: make `adapter.render` tolerant: if a declared param isn't passed,
  use a per-type fallback. This loosens the contract though.

`chore_tutorial_polish` worked around the bug by using two templates in
the smoke test (a minimal `{{ query_text }}`-only template for judgment
generation, plus the full parameterized template for the study). The
operator tutorial inherits the same workaround.

## How to verify the fix

1. Create a query template with `declared_params={"foo": "float"}` via
   `POST /api/v1/query-templates`.
2. Call `POST /api/v1/judgments/generate` against a query set + cluster
   using that template as `current_template_id`.
3. Worker must complete without `judgment_search_failed` events.
4. Assert no orphan code paths break: re-run
   `pytest backend/tests/integration/test_judgment_generate.py`.

## Scope estimate

Small — one of the three fix options above plus the regression test.
Likely 1–2 stories under a `bug_` pipeline.

## Related

- [`chore_tutorial_polish/feature_spec.md`](../chore_tutorial_polish/feature_spec.md) — the consumer that surfaced it
- [`feat_llm_judgments`](../../../00_overview/implemented_features/2026_05_11_feat_llm_judgments/) — owns the judgment-gen worker
- [`feat_study_lifecycle`](../../../00_overview/implemented_features/2026_05_10_feat_study_lifecycle/) — owns query-template schema
