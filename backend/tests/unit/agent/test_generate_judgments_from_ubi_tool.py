# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the ``generate_judgments_from_ubi`` agent tool
(feat_ubi_judgments Story 3.4 / FR-6)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.agent.tools import TOOL_ARG_MODELS, TOOL_REGISTRY, TOOLS
from backend.app.agent.tools.judgments.generate_judgments_from_ubi import (
    GENERATE_JUDGMENTS_FROM_UBI_TOOL,
    GenerateJudgmentsFromUbiArgs,
    generate_judgments_from_ubi_impl,
)


def test_tool_definition_shape() -> None:
    assert GENERATE_JUDGMENTS_FROM_UBI_TOOL["type"] == "function"
    assert GENERATE_JUDGMENTS_FROM_UBI_TOOL["function"]["name"] == "generate_judgments_from_ubi"
    schema = GENERATE_JUDGMENTS_FROM_UBI_TOOL["function"]["parameters"]
    assert isinstance(schema, dict)
    assert "properties" in schema
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert "converter" in properties


def test_registered_in_triad() -> None:
    """All three module-level data structures must include the tool."""
    tool_names = {t["function"]["name"] for t in TOOLS}
    assert "generate_judgments_from_ubi" in tool_names
    assert "generate_judgments_from_ubi" in TOOL_REGISTRY
    assert "generate_judgments_from_ubi" in TOOL_ARG_MODELS
    assert TOOL_REGISTRY["generate_judgments_from_ubi"] is generate_judgments_from_ubi_impl
    assert TOOL_ARG_MODELS["generate_judgments_from_ubi"] is GenerateJudgmentsFromUbiArgs


class TestArgsConditional:
    def test_pure_converter_minimal_args_accepted(self) -> None:
        args = GenerateJudgmentsFromUbiArgs(
            name="ubi-1",
            query_set_id=uuid4(),
            cluster_id=uuid4(),
            target="products",
            since=datetime(2026, 5, 1, tzinfo=UTC),
            converter="ctr_threshold",
        )
        assert args.converter == "ctr_threshold"
        assert args.current_template_id is None
        assert args.rubric is None

    def test_hybrid_requires_template_and_rubric(self) -> None:
        with pytest.raises(ValidationError):
            GenerateJudgmentsFromUbiArgs(
                name="ubi-1",
                query_set_id=uuid4(),
                cluster_id=uuid4(),
                target="products",
                since=datetime(2026, 5, 1, tzinfo=UTC),
                converter="hybrid_ubi_llm",
            )

    def test_pure_converter_with_template_rejected(self) -> None:
        with pytest.raises(ValidationError):
            GenerateJudgmentsFromUbiArgs(
                name="ubi-1",
                query_set_id=uuid4(),
                cluster_id=uuid4(),
                target="products",
                since=datetime(2026, 5, 1, tzinfo=UTC),
                converter="ctr_threshold",
                current_template_id=uuid4(),
            )

    def test_hybrid_with_template_and_rubric_accepted(self) -> None:
        args = GenerateJudgmentsFromUbiArgs(
            name="ubi-1",
            query_set_id=uuid4(),
            cluster_id=uuid4(),
            target="products",
            since=datetime(2026, 5, 1, tzinfo=UTC),
            converter="hybrid_ubi_llm",
            current_template_id=uuid4(),
            rubric="rate 0-3",
        )
        assert args.converter == "hybrid_ubi_llm"


def test_orchestrator_prompt_references_both_judgment_tools() -> None:
    """The system prompt MUST mention both LLM and UBI tools so the model can choose."""
    from pathlib import Path

    prompt = Path("prompts/orchestrator.system.md").read_text()
    assert "generate_judgments_llm" in prompt
    assert "generate_judgments_from_ubi" in prompt
    # Choosing-section header present.
    assert "Choosing between LLM and UBI" in prompt
