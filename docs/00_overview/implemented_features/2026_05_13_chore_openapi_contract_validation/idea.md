# chore — strict OpenAPI-schema validation in contract tests

**Date:** 2026-05-10
**Status:** Idea (deferred from `feat_study_lifecycle` Phase 2 / PR #25 final GPT-5.5 review)
**Origin:** GPT-5.5 final-review finding #6 — Story 3.5's
`test_studies_api_contract.py` checks Pydantic schema importability +
field validators, but does not iterate every documented endpoint and
validate the response against `app.openapi()` as Story 3.5 task 1
described.

## Why deferred

The functional surface IS covered:

* Integration tests (`test_studies_api.py`, `test_query_templates_api.py`,
  `test_csv_upload.py`) exercise every endpoint with valid payloads and
  the Pydantic response_model parses the returned JSON — so any wire-shape
  drift would surface as a parse error.
* Contract tests cover Pydantic-shape contracts and the spec §7.5 error
  envelope.

What's missing is the explicit OpenAPI-schema-validates-response loop the
plan called for. Adding it requires:

1. `jsonschema` or `openapi-spec-validator` dependency.
2. A helper that pulls the response schema from `app.openapi()` by
   `(method, path)` and asserts the response JSON satisfies it.
3. 12 dedicated cases, one per endpoint, parameterized.

## Proposed fix

Add `backend/tests/contract/test_studies_openapi_contract.py` with:

```python
@pytest.mark.parametrize("method,path,fixture", [...])
async def test_endpoint_response_matches_openapi_schema(...):
    response = await async_client.request(method, path, ...)
    schema = app.openapi()["paths"][path][method.lower()]["responses"][...]
    jsonschema.validate(response.json(), schema)
```

## Scope signals

* Backend: yes (contract-test layer only).
* Frontend: no.
* Migration: no.
* Config: no.

## Why this isn't a blocker today

The integration-layer Pydantic round-trip is a strictly stronger contract
than OpenAPI validation in practice — if `StudyDetail.model_validate(...)`
accepts the response, the response satisfies the OpenAPI schema FastAPI
generated from that same Pydantic model. The proposed strict-validation
test would catch hand-coded schema overrides or FastAPI's response_model
bypass, but neither pattern exists in Phase 2.
