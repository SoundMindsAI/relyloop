# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration test for the ``generate_judgments_from_ubi`` agent tool
(feat_ubi_judgments Story 3.4 / FR-6).

Exercises the tool impl's arg-marshalling + dispatcher call against a real
ToolContext, with the dispatcher stubbed (its full preflight is covered by
``test_judgments_generate_from_ubi.py`` + the unit dispatcher suite). The
unique coverage here: the tool builds a valid
``UbiJudgmentGenerationRequest`` from its args and returns the
``{judgment_list_id, status}`` shape.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.app.agent.context import ToolContext
from backend.app.agent.tools.judgments.generate_judgments_from_ubi import (
    GenerateJudgmentsFromUbiArgs,
    generate_judgments_from_ubi_impl,
)
from backend.app.services.agent_judgments_dispatch import (
    JudgmentGenerationResult,
    UbiJudgmentGenerationRequest,
)

pytestmark = pytest.mark.integration


async def test_tool_marshals_args_and_returns_result(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def _stub_dispatch(*, db, redis, arq_pool, settings, req):  # noqa: ANN001
        captured["req"] = req
        return JudgmentGenerationResult(judgment_list_id="jl-123", status="generating")

    monkeypatch.setattr(
        "backend.app.agent.tools.judgments.generate_judgments_from_ubi."
        "start_ubi_judgment_generation",
        _stub_dispatch,
    )

    args = GenerateJudgmentsFromUbiArgs(
        name="ubi-tool-list",
        query_set_id=uuid.uuid4(),
        cluster_id=uuid.uuid4(),
        target="products",
        since=datetime(2026, 5, 1, tzinfo=UTC),
        converter="ctr_threshold",
    )
    ctx = ToolContext(
        db=None,  # type: ignore[arg-type]  # stubbed dispatcher never touches it
        conversation_id="conv-x",
        redis=None,  # type: ignore[arg-type]
        arq_pool=None,
        settings=None,  # type: ignore[arg-type]
    )

    result = await generate_judgments_from_ubi_impl(args, ctx)

    assert result == {"judgment_list_id": "jl-123", "status": "generating"}
    req = captured["req"]
    assert isinstance(req, UbiJudgmentGenerationRequest)
    assert req.converter == "ctr_threshold"
    assert req.target == "products"
    # UUIDs are stringified for the dataclass.
    assert isinstance(req.query_set_id, str)
    assert isinstance(req.cluster_id, str)
    assert req.current_template_id is None  # pure converter
    assert req.rubric is None


async def test_tool_hybrid_args_pass_template_and_rubric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _stub_dispatch(*, db, redis, arq_pool, settings, req):  # noqa: ANN001
        captured["req"] = req
        return JudgmentGenerationResult(judgment_list_id="jl-hy", status="generating")

    monkeypatch.setattr(
        "backend.app.agent.tools.judgments.generate_judgments_from_ubi."
        "start_ubi_judgment_generation",
        _stub_dispatch,
    )

    template_id = uuid.uuid4()
    args = GenerateJudgmentsFromUbiArgs(
        name="ubi-tool-hybrid",
        query_set_id=uuid.uuid4(),
        cluster_id=uuid.uuid4(),
        target="products",
        since=datetime(2026, 5, 1, tzinfo=UTC),
        converter="hybrid_ubi_llm",
        current_template_id=template_id,
        rubric="rate 0-3",
    )
    ctx = ToolContext(
        db=None,  # type: ignore[arg-type]
        conversation_id="conv-y",
        redis=None,  # type: ignore[arg-type]
        arq_pool=None,
        settings=None,  # type: ignore[arg-type]
    )

    result = await generate_judgments_from_ubi_impl(args, ctx)
    assert result["judgment_list_id"] == "jl-hy"
    req = captured["req"]
    assert req.converter == "hybrid_ubi_llm"
    assert req.current_template_id == str(template_id)
    assert req.rubric == "rate 0-3"
