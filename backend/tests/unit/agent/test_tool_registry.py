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

EXPECTED_TOOL_COUNT_AFTER_STORY_2_2 = 11


def test_tool_registry_count_after_story_2_2() -> None:
    """Story 2.2 brings the registry to 11 tools (5 from 2.1 + 6 new). Updated by 2.3, 2.4."""
    assert len(TOOLS) == EXPECTED_TOOL_COUNT_AFTER_STORY_2_2
    assert len(TOOL_REGISTRY) == EXPECTED_TOOL_COUNT_AFTER_STORY_2_2
    assert len(TOOL_ARG_MODELS) == EXPECTED_TOOL_COUNT_AFTER_STORY_2_2


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
