# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Contract test: assert the OpenAPI surface declares every documented endpoint.

Per `chore_openapi_contract_validation` (originally proposed strict
JSON-Schema validation of every response against `app.openapi()`).
The cheaper, dep-free version landed here catches the two failure modes
the original idea targeted:

1. **Endpoint deletion regression** — an endpoint disappears from a
   router (e.g., commented-out @router.get) but tests pass because no
   integration test exercises it. This file maintains the canonical list
   of every endpoint and fails if any is missing from app.openapi().
2. **response_model bypass** — an endpoint returns a Response or dict
   directly without a Pydantic response_model, so the OpenAPI spec lists
   the path but has no `content` schema. This file asserts every
   documented endpoint declares a content schema for its primary 2xx
   response.

What this file does NOT catch (and the integration-layer Pydantic
round-trip already does): wire-shape drift inside a response_model. If
`StudyDetail.model_validate(...)` accepts the response, the response
satisfies the OpenAPI schema FastAPI generated from that same model.

Per the original idea spec, strict json-schema response validation
remains a "if we ever bypass response_model" defensive layer; this file
is sufficient until that pattern emerges.
"""

from __future__ import annotations

from typing import Any

import pytest

# (method, path, primary_2xx_status_code). One entry per @router.* decorator
# in backend/app/api/v1/*.py + the unversioned /healthz + webhook routes.
# Add new entries when adding endpoints; the test fails on missing entries.
EXPECTED_ENDPOINTS: list[tuple[str, str, str]] = [
    # ----- /healthz (unversioned, operator probe) -----
    ("get", "/healthz", "200"),
    # ----- /webhooks -----
    ("post", "/webhooks/github", "200"),
    # ----- /api/v1/clusters -----
    ("post", "/api/v1/clusters", "201"),
    ("get", "/api/v1/clusters", "200"),
    ("get", "/api/v1/clusters/{cluster_id}", "200"),
    ("delete", "/api/v1/clusters/{cluster_id}", "204"),
    ("get", "/api/v1/clusters/{cluster_id}/schema", "200"),
    ("get", "/api/v1/clusters/{cluster_id}/targets", "200"),
    # feat_ubi_judgments (PR #317) — UBI readiness probe.
    ("get", "/api/v1/clusters/{cluster_id}/ubi-readiness", "200"),
    # infra_adapter_solr Story A8 (PR #336) — connection test + capability reprobe.
    ("post", "/api/v1/clusters/test-connection", "200"),
    ("post", "/api/v1/clusters/{cluster_id}/reprobe", "202"),
    # feat_index_document_browser FR-3 / FR-4 — documents browse.
    ("get", "/api/v1/clusters/{cluster_id}/targets/{target}/documents", "200"),
    ("get", "/api/v1/clusters/{cluster_id}/targets/{target}/documents/{doc_id}", "200"),
    ("post", "/api/v1/clusters/{cluster_id}/run_query", "200"),
    # ----- /api/v1/config-repos -----
    ("post", "/api/v1/config-repos", "201"),
    ("get", "/api/v1/config-repos", "200"),
    ("get", "/api/v1/config-repos/{config_repo_id}", "200"),
    # ----- /api/v1/query-templates -----
    ("post", "/api/v1/query-templates", "201"),
    ("get", "/api/v1/query-templates", "200"),
    ("get", "/api/v1/query-templates/{template_id}", "200"),
    # ----- /api/v1/query-sets -----
    ("post", "/api/v1/query-sets", "201"),
    ("get", "/api/v1/query-sets", "200"),
    ("get", "/api/v1/query-sets/{query_set_id}", "200"),
    ("post", "/api/v1/query-sets/{query_set_id}/queries", "201"),
    # feat_query_inline_crud — per-query CRUD
    ("get", "/api/v1/query-sets/{query_set_id}/queries", "200"),
    ("patch", "/api/v1/query-sets/{query_set_id}/queries/{query_id}", "200"),
    ("delete", "/api/v1/query-sets/{query_set_id}/queries/{query_id}", "204"),
    # ----- /api/v1/judgments + /api/v1/judgment-lists -----
    ("post", "/api/v1/judgments/generate", "202"),
    # feat_ubi_judgments (PR #317) — generate judgments from UBI events.
    ("post", "/api/v1/judgments/generate-from-ubi", "202"),
    ("post", "/api/v1/judgment-lists/import", "201"),
    ("get", "/api/v1/judgment-lists", "200"),
    ("get", "/api/v1/judgment-lists/{judgment_list_id}", "200"),
    # feat_ubi_llm_study_comparison (this PR) — list→completed-study resolver.
    ("get", "/api/v1/judgment-lists/{judgment_list_id}/study", "200"),
    ("get", "/api/v1/judgment-lists/{judgment_list_id}/judgments", "200"),
    ("patch", "/api/v1/judgment-lists/{judgment_list_id}/judgments/{judgment_id}", "200"),
    ("post", "/api/v1/judgment-lists/{judgment_list_id}/calibration", "200"),
    # ----- /api/v1/studies -----
    ("post", "/api/v1/studies", "201"),
    ("get", "/api/v1/studies", "200"),
    # feat_ubi_llm_study_comparison (this PR) — LLM-vs-UBI compare surface.
    # `compare` + `{id}/pair` are declared ABOVE `/studies/{study_id}`.
    ("get", "/api/v1/studies/compare", "200"),
    ("get", "/api/v1/studies/{study_id}/pair", "200"),
    ("get", "/api/v1/studies/{study_id}", "200"),
    ("post", "/api/v1/studies/{study_id}/cancel", "200"),
    ("get", "/api/v1/studies/{study_id}/children", "200"),
    ("get", "/api/v1/studies/{study_id}/trials", "200"),
    # feat_overnight_autopilot (PR #343) — auto-followup chain rollup.
    ("get", "/api/v1/studies/{study_id}/chain", "200"),
    # feat_overnight_studies_summary_card (this PR) — recent-chains discovery
    # feeding the "Ran while you were away" card on /studies.
    ("get", "/api/v1/studies/chains/recent", "200"),
    # ----- /api/v1/proposals (feat_digest_proposal + feat_github_pr_worker) -----
    ("get", "/api/v1/studies/{study_id}/digest", "200"),
    ("post", "/api/v1/proposals", "201"),
    ("get", "/api/v1/proposals", "200"),
    ("get", "/api/v1/proposals/{proposal_id}", "200"),
    ("post", "/api/v1/proposals/{proposal_id}/reject", "200"),
    ("post", "/api/v1/proposals/{proposal_id}/open_pr", "202"),
    ("post", "/api/v1/proposals/{proposal_id}/reinstate", "200"),
    # ----- /api/v1/conversations (feat_chat_agent) -----
    ("post", "/api/v1/conversations", "201"),
    ("get", "/api/v1/conversations", "200"),
    ("get", "/api/v1/conversations/{conversation_id}", "200"),
    ("delete", "/api/v1/conversations/{conversation_id}", "204"),
    ("post", "/api/v1/conversations/{conversation_id}/messages", "200"),
    # ----- /api/v1/_test (infra_e2e_seed_completed_study; dev-only — 404 outside) -----
    ("post", "/api/v1/_test/studies/seed-completed", "201"),
    # chore_auto_followup_e2e_chain_seed_helper — dev-only chain seeder.
    ("post", "/api/v1/_test/auto-followup/seed-chain", "201"),
    # chore_e2e_test_rows_isolation Story 1.1 — six new test-only DELETE endpoints.
    ("delete", "/api/v1/_test/proposals/{proposal_id}", "204"),
    ("delete", "/api/v1/_test/digests/{digest_id}", "204"),
    ("delete", "/api/v1/_test/studies/{study_id}", "204"),
    ("delete", "/api/v1/_test/judgment-lists/{judgment_list_id}", "204"),
    ("delete", "/api/v1/_test/query-sets/{query_set_id}", "204"),
    ("delete", "/api/v1/_test/query-templates/{template_id}", "204"),
    # feat_home_demo_reseed_endpoint Story 1.2 — demo-state reseed endpoint.
    # bug_demo_reseed_fake_metric_regression — POST now enqueues an Arq job
    # and returns 202; GET polls the Redis-backed status.
    ("post", "/api/v1/_test/demo/reseed", "202"),
    ("get", "/api/v1/_test/demo/reseed/status", "200"),
    # feat_selective_engine_startup_and_demo Story 2.1 — engine reachability
    # probe powering the reset-modal checkbox group (FR-7).
    ("get", "/api/v1/_test/demo/engines", "200"),
]


@pytest.fixture(scope="module", autouse=True)
def _settings_env(
    tmp_path_factory: pytest.TempPathFactory,
) -> Any:
    """Stub required Settings inputs so ``backend.app.main`` imports locally.

    CI provides ``DATABASE_URL_FILE`` + ``POSTGRES_PASSWORD_FILE``; laptop
    developers running ``pytest backend/tests/contract/test_openapi_surface.py``
    would otherwise hit ``pydantic_core.ValidationError`` at module import.
    Module-scoped so it runs before the ``openapi_spec`` module fixture.
    Mirrors the pattern in ``backend/tests/unit/test_smoke.py``.
    """
    tmp = tmp_path_factory.mktemp("openapi_surface_env")
    db_url_file = tmp / "db_url"
    db_url_file.write_text("postgresql+asyncpg://x:y@localhost/test")
    pw_file = tmp / "pw"
    pw_file.write_text("test")
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("DATABASE_URL_FILE", str(db_url_file))
        mp.setenv("POSTGRES_PASSWORD_FILE", str(pw_file))
        mp.setenv("REDIS_URL", "redis://redis:6379/0")
        from backend.app.core.settings import get_settings

        get_settings.cache_clear()
        yield
        get_settings.cache_clear()


@pytest.fixture(scope="module")
def openapi_spec() -> dict[str, Any]:
    from backend.app.main import app

    return app.openapi()


@pytest.mark.parametrize("method, path, status", EXPECTED_ENDPOINTS)
def test_endpoint_declared_in_openapi(
    openapi_spec: dict[str, Any], method: str, path: str, status: str
) -> None:
    """Every documented endpoint appears in app.openapi() with the expected status."""
    paths = openapi_spec.get("paths", {})
    assert path in paths, (
        f"Endpoint {method.upper()} {path} missing from OpenAPI spec. "
        f"Either the route was deleted or this test's EXPECTED_ENDPOINTS "
        f"list is stale."
    )
    methods = paths[path]
    assert method in methods, f"Method {method.upper()} not declared for {path} in OpenAPI spec."
    responses = methods[method].get("responses", {})
    assert status in responses, (
        f"{method.upper()} {path} declares responses {list(responses.keys())} "
        f"but EXPECTED_ENDPOINTS expects {status}. Either the endpoint's "
        f"status_code argument changed or this test's list is stale."
    )


@pytest.mark.parametrize("method, path, status", EXPECTED_ENDPOINTS)
def test_endpoint_response_model_declared(
    openapi_spec: dict[str, Any], method: str, path: str, status: str
) -> None:
    """Every 2xx response declares a content schema (proves response_model wasn't bypassed).

    204 No Content is the explicit exception — by HTTP semantics it has
    no body. We don't enforce a content schema for that status.
    """
    if status == "204":
        return
    response_spec = openapi_spec["paths"][path][method]["responses"][status]
    # FastAPI emits "content" with at least application/json when response_model
    # is declared. Endpoints that return Response(...) directly without a
    # response_model produce an empty response (no "content" key).
    assert "content" in response_spec, (
        f"{method.upper()} {path} {status} has no content schema — likely "
        f"the endpoint returns a bare Response without a response_model. "
        f"Add response_model=<YourModel> to the @router decorator."
    )


_HTTP_METHODS = frozenset({"get", "post", "put", "delete", "patch", "options", "head", "trace"})


def test_openapi_has_no_orphan_endpoints(openapi_spec: dict[str, Any]) -> None:
    """Every (method, path) in app.openapi() is on the EXPECTED_ENDPOINTS list.

    Failure means a new endpoint (or a new method on an existing path)
    shipped without an entry in this test — add it to EXPECTED_ENDPOINTS
    so the surface stays canonically tracked. Per Gemini suggestion on
    PR #84: catches method-addition regressions, not just path-addition.
    """
    expected = {(m.lower(), p) for m, p, _ in EXPECTED_ENDPOINTS}
    actual: set[tuple[str, str]] = set()
    for path, path_item in openapi_spec.get("paths", {}).items():
        for key in path_item:
            if key.lower() in _HTTP_METHODS:
                actual.add((key.lower(), path))
    orphans = actual - expected
    assert not orphans, (
        f"OpenAPI endpoints (method, path) missing from EXPECTED_ENDPOINTS: "
        f"{sorted(orphans)}. Add entries to keep the surface canonically tracked."
    )


# ---------------------------------------------------------------------------
# ReseedStatusResponse contract (infra_solr_ci_readiness Story 1.5 / FR-5).
# Guards the additive `scenarios_skipped` field + the UNCHANGED status enum.
# ---------------------------------------------------------------------------


def _reseed_status_schema(openapi_spec: dict[str, Any]) -> dict[str, Any]:
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    assert "ReseedStatusResponse" in schemas, (
        "ReseedStatusResponse missing from OpenAPI components — the reseed "
        "status endpoint's response_model is not wired."
    )
    return schemas["ReseedStatusResponse"]


def test_reseed_status_has_scenarios_skipped_optional_string_array(
    openapi_spec: dict[str, Any],
) -> None:
    """`scenarios_skipped` is an optional array<string> (default_factory -> not required).

    Pydantic v2's `Field(default_factory=list)` makes the field optional (absent
    from `required`) but does NOT emit a JSON-Schema `default: []` — so we assert
    presence + type + non-required, NOT a schema default. The runtime `[]` default
    is verified by the model unit tests.
    """
    schema = _reseed_status_schema(openapi_spec)
    props = schema.get("properties", {})
    assert "scenarios_skipped" in props, (
        "ReseedStatusResponse.scenarios_skipped missing from schema"
    )
    field = props["scenarios_skipped"]
    assert field.get("type") == "array", f"scenarios_skipped should be array, got {field!r}"
    assert field.get("items", {}).get("type") == "string", (
        f"scenarios_skipped items should be string, got {field.get('items')!r}"
    )
    assert "scenarios_skipped" not in schema.get("required", []), (
        "scenarios_skipped has a default_factory — it must NOT be in `required`."
    )


def test_reseed_status_has_scenarios_manifest_array(
    openapi_spec: dict[str, Any],
) -> None:
    """`scenarios` is an optional array of ScenarioProgress (default_factory=list).

    feat_reseed_scenario_manifest_live_state FR-2 — additive + defaulted, so it
    is present + array-typed but NOT in `required` (a legacy Redis blob without
    it still deserializes; the runtime `[]` default is unit-tested).
    """
    schema = _reseed_status_schema(openapi_spec)
    props = schema.get("properties", {})
    assert "scenarios" in props, "ReseedStatusResponse.scenarios missing from schema"
    field = props["scenarios"]
    assert field.get("type") == "array", f"scenarios should be array, got {field!r}"
    item_ref = field.get("items", {}).get("$ref", "")
    assert item_ref.endswith("/ScenarioProgress"), (
        f"scenarios items should $ref ScenarioProgress, got {field.get('items')!r}"
    )
    assert "scenarios" not in schema.get("required", []), (
        "scenarios has a default_factory — it must NOT be in `required`."
    )


def test_scenario_progress_schema_shape(openapi_spec: dict[str, Any]) -> None:
    """ScenarioProgress carries slug/label/description/engine/state + optional
    skip_reason, with state restricted to the four-value Literal (FR-1 / §7.4)."""
    schemas = openapi_spec["components"]["schemas"]
    assert "ScenarioProgress" in schemas, "ScenarioProgress missing from OpenAPI components"
    sp = schemas["ScenarioProgress"]
    props = sp.get("properties", {})
    for required_field in ("slug", "label", "description", "engine", "state"):
        assert required_field in props, f"ScenarioProgress.{required_field} missing"
        assert required_field in sp.get("required", []), (
            f"ScenarioProgress.{required_field} should be required"
        )
    # skip_reason is optional (defaults None).
    assert "skip_reason" in props
    assert "skip_reason" not in sp.get("required", [])
    # state Literal — resolve inline `enum` or a referenced enum schema.
    state_prop = props["state"]
    enum_values = state_prop.get("enum")
    if enum_values is None and "allOf" in state_prop:
        ref_name = state_prop["allOf"][0].get("$ref", "").rsplit("/", 1)[-1]
        enum_values = schemas.get(ref_name, {}).get("enum")
    assert enum_values is not None, (
        f"could not resolve ScenarioProgress.state enum from {state_prop!r}"
    )
    assert set(enum_values) == {"pending", "active", "done", "skipped"}, (
        f"ScenarioState drifted: {sorted(enum_values)}"
    )


def test_reseed_status_enum_is_unchanged_four_values(openapi_spec: dict[str, Any]) -> None:
    """ReseedStatusLiteral stays exactly {idle, running, complete, failed}.

    Guards against accidental enum expansion (the dropped `succeeded_partial`
    idea — partial completion is encoded via scenarios_skipped, not a new status).
    """
    schema = _reseed_status_schema(openapi_spec)
    status_prop = schema.get("properties", {}).get("status", {})
    # The Literal may be inlined as `enum` or referenced; resolve both shapes.
    enum_values = status_prop.get("enum")
    if enum_values is None and "allOf" in status_prop:
        ref = status_prop["allOf"][0].get("$ref", "")
        ref_name = ref.rsplit("/", 1)[-1]
        enum_values = openapi_spec["components"]["schemas"].get(ref_name, {}).get("enum")
    assert enum_values is not None, f"could not resolve status enum from {status_prop!r}"
    assert set(enum_values) == {"idle", "running", "complete", "failed"}, (
        f"ReseedStatusLiteral drifted: {sorted(enum_values)}"
    )


# ---------------------------------------------------------------------------
# feat_selective_engine_startup_and_demo Story 2.1.
# Guards the additive `scenarios_skipped_reasons` field on
# ReseedStatusResponse and the new `DemoEnginesResponse` shape powering the
# reset-modal checkbox group (FR-6, FR-7).
# ---------------------------------------------------------------------------


def test_reseed_status_has_scenarios_skipped_reasons_dict(
    openapi_spec: dict[str, Any],
) -> None:
    """`scenarios_skipped_reasons` is an optional dict<string, "user_excluded"|"unreachable">.

    Additive sibling to `scenarios_skipped` (FR-6). Like
    `scenarios_skipped`, Pydantic's `default_factory=dict` makes it
    absent from `required`. The Literal values discriminate the two skip
    reasons the orchestrator records — must stay exactly
    {user_excluded, unreachable}.
    """
    schema = _reseed_status_schema(openapi_spec)
    props = schema.get("properties", {})
    assert "scenarios_skipped_reasons" in props, (
        "ReseedStatusResponse.scenarios_skipped_reasons missing from schema "
        "— feat_selective_engine_startup_and_demo FR-6"
    )
    field = props["scenarios_skipped_reasons"]
    assert field.get("type") == "object", (
        f"scenarios_skipped_reasons should be object (JSON-Schema dict), got {field!r}"
    )
    additional = field.get("additionalProperties", {})
    # Pydantic emits the value Literal as either an inline enum or a $ref.
    enum_values = additional.get("enum") if isinstance(additional, dict) else None
    if enum_values is None and isinstance(additional, dict) and "$ref" in additional:
        ref_name = additional["$ref"].rsplit("/", 1)[-1]
        enum_values = openapi_spec["components"]["schemas"].get(ref_name, {}).get("enum")
    assert enum_values is not None, (
        f"could not resolve scenarios_skipped_reasons value enum from {additional!r}"
    )
    assert set(enum_values) == {"user_excluded", "unreachable"}, (
        f"_SkipReason drifted: {sorted(enum_values)}"
    )
    assert "scenarios_skipped_reasons" not in schema.get("required", []), (
        "scenarios_skipped_reasons has a default_factory — it must NOT be in `required`."
    )


def test_reseed_request_body_shape(openapi_spec: dict[str, Any]) -> None:
    """ReseedRequest is `{engines: list[EngineTypeWire]|null}` with min_length=1.

    Guards the new POST body model:
    - `engines` is optional (not in required) — null and missing both
      use the back-compat "reseed every reachable engine" path.
    - When provided, the inner list is validated against EngineTypeWire.
    - `min_length=1` rejects empty list at the OpenAPI schema (D-7).
    """
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    assert "ReseedRequest" in schemas, (
        "ReseedRequest missing from OpenAPI components — the POST body model is not wired."
    )
    schema = schemas["ReseedRequest"]
    props = schema.get("properties", {})
    assert "engines" in props
    assert "engines" not in schema.get("required", []), (
        "engines has default=None — it must NOT be in `required`."
    )
    field = props["engines"]
    # Pydantic emits ``list[X] | None`` as anyOf of [array, null]; resolve
    # the array branch and assert min_length=1 + items match EngineTypeWire.
    anyof = field.get("anyOf") or []
    array_branch = next(
        (b for b in anyof if isinstance(b, dict) and b.get("type") == "array"),
        None,
    )
    if array_branch is None:
        # Pydantic may also inline the non-null shape directly when the
        # default + Optional gymnastics resolve. Accept either form.
        if field.get("type") == "array":
            array_branch = field
    assert array_branch is not None, f"engines anyOf has no array branch: {field!r}"
    assert array_branch.get("minItems") == 1, (
        f"engines.minItems should be 1 (D-7: empty list rejected), got "
        f"{array_branch.get('minItems')!r}"
    )
    items = array_branch.get("items", {})
    enum_values = items.get("enum")
    if enum_values is None and "$ref" in items:
        ref_name = items["$ref"].rsplit("/", 1)[-1]
        enum_values = schemas.get(ref_name, {}).get("enum")
    assert enum_values is not None, f"could not resolve engines items enum from {items!r}"
    assert set(enum_values) == {"elasticsearch", "opensearch", "solr"}


def test_demo_engines_response_shape(openapi_spec: dict[str, Any]) -> None:
    """DemoEnginesResponse is `{engines: list[DemoEngineStatus]}` with EngineTypeWire."""
    schemas = openapi_spec.get("components", {}).get("schemas", {})
    assert "DemoEnginesResponse" in schemas, (
        "DemoEnginesResponse missing from OpenAPI components — the new "
        "GET /api/v1/_test/demo/engines response_model is not wired."
    )
    assert "DemoEngineStatus" in schemas, (
        "DemoEngineStatus missing from OpenAPI components — the per-engine row type is not wired."
    )
    resp_props = schemas["DemoEnginesResponse"].get("properties", {})
    assert "engines" in resp_props, "DemoEnginesResponse.engines missing"
    assert resp_props["engines"].get("type") == "array", (
        f"DemoEnginesResponse.engines should be array, got {resp_props['engines']!r}"
    )
    row_props = schemas["DemoEngineStatus"].get("properties", {})
    assert "engine_type" in row_props and "reachable" in row_props, (
        f"DemoEngineStatus missing required fields engine_type / reachable: "
        f"{list(row_props.keys())}"
    )
    # engine_type uses EngineTypeWire — the same allowlist the reseed
    # POST body validates against (the source-of-truth discipline).
    engine_type_prop = row_props["engine_type"]
    enum_values = engine_type_prop.get("enum")
    if enum_values is None and "allOf" in engine_type_prop:
        ref = engine_type_prop["allOf"][0].get("$ref", "")
        ref_name = ref.rsplit("/", 1)[-1]
        enum_values = schemas.get(ref_name, {}).get("enum")
    assert enum_values is not None, f"could not resolve engine_type enum from {engine_type_prop!r}"
    assert set(enum_values) == {"elasticsearch", "opensearch", "solr"}, (
        f"DemoEngineStatus.engine_type drifted from EngineTypeWire: {sorted(enum_values)}"
    )

    # feat_engine_version_selection FR-7 / AC-15: DemoEngineStatus.version
    # is a nullable string. FastAPI emits Optional[str] either as
    # anyOf:[{type:'string'}, {type:'null'}] (newer) or as `type:'string'`
    # with `nullable: true` (older). Tolerate both shapes.
    assert "version" in row_props, (
        "DemoEngineStatus.version missing from OpenAPI schema — "
        "regenerate ui/openapi.json after extending the model."
    )
    version_prop = row_props["version"]
    is_nullable_string = (
        version_prop.get("type") == "string" and version_prop.get("nullable") is True
    ) or any(t.get("type") in ("string", "null") for t in version_prop.get("anyOf", []))
    assert is_nullable_string, f"DemoEngineStatus.version is not nullable-string: {version_prop!r}"
