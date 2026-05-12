"""Tool registry (feat_chat_agent Story 2.1 — locks the per-tool pattern).

Three parallel data structures, one entry per tool:

* ``TOOLS`` — list of ``ChatCompletionToolParam`` dicts. This is the JSON-schema
  surface the OpenAI Chat Completions API sees in the ``tools=[]`` argument.
* ``TOOL_REGISTRY`` — name → impl callable. The orchestrator dispatches a tool
  call by looking the name up here and ``await``-ing the impl.
* ``TOOL_ARG_MODELS`` — name → Pydantic model class. The dispatcher calls
  ``TOOL_ARG_MODELS[name].model_validate_json(tool_call.arguments)`` BEFORE
  invoking the impl, so the runtime arg passed to the impl is always a fully
  validated Pydantic model of the correct concrete type.

A module-load assertion enforces the three data structures stay in sync — fail
fast on drift (e.g. a tool added to TOOLS without a registry entry, or a name
typo between the three).

Story 2.1 ships 5 read-only tools (3 cluster + 2 template). Stories 2.2–2.4
extend each list to the MVP1 total of 19.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from openai.types.chat import ChatCompletionToolParam
from pydantic import BaseModel

from backend.app.agent.context import ToolContext
from backend.app.agent.tools.clusters.get_cluster import (
    GET_CLUSTER_TOOL,
    GetClusterArgs,
    get_cluster_impl,
)
from backend.app.agent.tools.clusters.get_schema import (
    GET_SCHEMA_TOOL,
    GetSchemaArgs,
    get_schema_impl,
)
from backend.app.agent.tools.clusters.list_clusters import (
    LIST_CLUSTERS_TOOL,
    ListClustersArgs,
    list_clusters_impl,
)
from backend.app.agent.tools.templates.get_template import (
    GET_TEMPLATE_TOOL,
    GetTemplateArgs,
    get_template_impl,
)
from backend.app.agent.tools.templates.list_templates import (
    LIST_TEMPLATES_TOOL,
    ListTemplatesArgs,
    list_templates_impl,
)

# Type of every tool impl. Args is the validated Pydantic model (typed precisely
# at each impl site as the concrete BaseModel subclass — `GetClusterArgs`,
# `CreateStudyArgs`, etc.); ``ctx`` provides dependencies. Returns a JSON-
# serialisable dict that goes into the tool_result event.
#
# Variance note: Python callables are contravariant in their parameters, so
# ``Callable[[GetClusterArgs, ...], ...]`` is NOT a subtype of
# ``Callable[[BaseModel, ...], ...]`` under strict mypy. We type the registry
# with ``Any`` for the args parameter — the orchestrator's dispatcher calls
# ``TOOL_ARG_MODELS[name].model_validate_json(...)`` BEFORE invoking the impl,
# so the runtime arg IS the right Pydantic model by construction.
ToolImpl = Callable[[Any, ToolContext], Awaitable[dict[str, Any]]]


TOOLS: list[ChatCompletionToolParam] = [
    LIST_CLUSTERS_TOOL,
    GET_CLUSTER_TOOL,
    GET_SCHEMA_TOOL,
    LIST_TEMPLATES_TOOL,
    GET_TEMPLATE_TOOL,
    # Story 2.2 appends 6 more, Story 2.3 appends 3 more, Story 2.4 appends 5 more.
]

TOOL_REGISTRY: dict[str, ToolImpl] = {
    "list_clusters": list_clusters_impl,
    "get_cluster": get_cluster_impl,
    "get_schema": get_schema_impl,
    "list_templates": list_templates_impl,
    "get_template": get_template_impl,
}

TOOL_ARG_MODELS: dict[str, type[BaseModel]] = {
    "list_clusters": ListClustersArgs,
    "get_cluster": GetClusterArgs,
    "get_schema": GetSchemaArgs,
    "list_templates": ListTemplatesArgs,
    "get_template": GetTemplateArgs,
}


_tool_names = {t["function"]["name"] for t in TOOLS}
_registry_names = set(TOOL_REGISTRY.keys())
_arg_model_names = set(TOOL_ARG_MODELS.keys())
if not (_tool_names == _registry_names == _arg_model_names):
    raise RuntimeError(
        "TOOLS / TOOL_REGISTRY / TOOL_ARG_MODELS drift: "
        f"TOOLS={_tool_names}, REGISTRY={_registry_names}, ARG_MODELS={_arg_model_names}"
    )


__all__ = [
    "TOOLS",
    "TOOL_ARG_MODELS",
    "TOOL_REGISTRY",
    "ToolImpl",
]
