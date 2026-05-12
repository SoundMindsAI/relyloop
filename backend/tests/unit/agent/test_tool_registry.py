"""Tool registry sanity tests (feat_chat_agent Story 2.1).

Asserts the three parallel data structures (``TOOLS``, ``TOOL_REGISTRY``,
``TOOL_ARG_MODELS``) stay aligned and that every tool definition is
well-formed for the OpenAI Chat Completions API.

This file grows in lock-step with Stories 2.2–2.4 — the expected count is
5 after this story and reaches 19 by the end of Story 2.4.
"""

from __future__ import annotations

import importlib

import pytest

from backend.app.agent.tools import (
    TOOL_ARG_MODELS,
    TOOL_REGISTRY,
    TOOLS,
)

EXPECTED_TOOL_COUNT_MVP1 = 19


# Canonical MVP1 inventory — kept verbatim with `docs/01_architecture/agent-tools.md`
# §"MVP1 tool inventory". Any rename / drop / addition MUST update BOTH.
CANONICAL_MVP1_TOOL_NAMES: frozenset[str] = frozenset(
    {
        # Cluster & schema
        "list_clusters",
        "get_cluster",
        "get_schema",
        # Templates
        "list_templates",
        "get_template",
        # Query sets & judgments
        "list_query_sets",
        "create_query_set",
        "import_queries_from_csv",
        "generate_judgments_llm",
        "get_calibration",
        # Quick experiments
        "run_query",
        # Studies
        "create_study",
        "get_study",
        "cancel_study",
        # Proposals & PRs
        "list_proposals",
        "get_proposal",
        "create_proposal_from_study",
        "create_proposal_manual",
        "open_pr",
    }
)


def test_tool_registry_count_at_mvp1_complete() -> None:
    """Story 2.4 brings the registry to the full 19-tool MVP1 surface."""
    assert len(TOOLS) == EXPECTED_TOOL_COUNT_MVP1
    assert len(TOOL_REGISTRY) == EXPECTED_TOOL_COUNT_MVP1
    assert len(TOOL_ARG_MODELS) == EXPECTED_TOOL_COUNT_MVP1


def test_tool_inventory_matches_agent_tools_md() -> None:
    """The 19 tool names must match the canonical inventory in agent-tools.md.

    Drift here (typo, dropped tool, renamed tool) is caught at unit-test time
    so the orchestrator's confirmation guard list (Story 2.5) and the system
    prompt's tool enumeration stay in lockstep with the implementation.
    """
    registered = {t["function"]["name"] for t in TOOLS}
    assert registered == CANONICAL_MVP1_TOOL_NAMES, (
        f"missing from registry: {CANONICAL_MVP1_TOOL_NAMES - registered}; "
        f"extra in registry: {registered - CANONICAL_MVP1_TOOL_NAMES}"
    )


def test_tool_definitions_are_well_formed() -> None:
    """Every TOOLS entry obeys the OpenAI ChatCompletionToolParam shape."""
    for entry in TOOLS:
        assert entry["type"] == "function"
        function = entry["function"]
        name = function["name"]
        assert isinstance(name, str) and name, "tool name must be a non-empty string"
        description = function["description"]
        assert isinstance(description, str) and description.strip(), (
            f"tool {name!r} missing description"
        )
        params = function["parameters"]
        assert isinstance(params, dict)
        assert params["type"] == "object", f"tool {name!r} parameters must be a JSON object schema"


def test_tool_names_align_across_three_data_structures() -> None:
    """No drift — every name appears in TOOLS, TOOL_REGISTRY, TOOL_ARG_MODELS."""
    tool_names = {t["function"]["name"] for t in TOOLS}
    registry_names = set(TOOL_REGISTRY.keys())
    arg_model_names = set(TOOL_ARG_MODELS.keys())
    assert tool_names == registry_names == arg_model_names, (
        f"drift detected: TOOLS={tool_names}, "
        f"REGISTRY={registry_names}, ARG_MODELS={arg_model_names}"
    )


def test_arg_model_schema_matches_tool_parameters() -> None:
    """The JSON schema OpenAI sees must equal what the dispatcher validates against."""
    for entry in TOOLS:
        name = entry["function"]["name"]
        tool_params = entry["function"]["parameters"]
        model_schema = TOOL_ARG_MODELS[name].model_json_schema()
        assert tool_params == model_schema, (
            f"tool {name!r}: TOOLS parameters drift from "
            f"TOOL_ARG_MODELS[{name!r}].model_json_schema()"
        )


def test_registry_module_imports_cleanly() -> None:
    """Re-importing must not raise — the module-load drift assertion only fires on real drift."""
    importlib.reload(importlib.import_module("backend.app.agent.tools"))


@pytest.mark.parametrize("name", sorted(TOOL_REGISTRY.keys()))
def test_every_registered_impl_is_an_async_callable(name: str) -> None:
    """Each impl must be an async function (so the orchestrator can await it)."""
    impl = TOOL_REGISTRY[name]
    import inspect

    assert callable(impl)
    assert inspect.iscoroutinefunction(impl), (
        f"tool {name!r} impl must be `async def` so the orchestrator can await it"
    )
