"""Unit tests for agent_judgments_dispatch (feat_chat_agent Story 2.2)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from backend.app.llm.capability_models import CapabilityResult
from backend.app.services import agent_judgments_dispatch as dispatch
from backend.app.services.agent_judgments_dispatch import JudgmentGenerationRequest


def _settings(
    *,
    openai_api_key: str | None = "test-key",
    openai_model: str = "gpt-4o-mini-2024-07-18",
    openai_base_url: str = "https://api.openai.com/v1",
    openai_daily_budget_usd: float = 0.0,
) -> MagicMock:
    s = MagicMock()
    s.openai_api_key = openai_api_key
    s.openai_model = openai_model
    s.openai_base_url = openai_base_url
    s.openai_daily_budget_usd = openai_daily_budget_usd
    return s


def _cap(
    function_calling: str = "ok",
    structured_output: str = "ok",
    model: str = "gpt-4o-mini-2024-07-18",
) -> CapabilityResult:
    return CapabilityResult(
        base_url="https://api.openai.com/v1",
        model=model,
        models_endpoint="ok",
        chat_completion="ok",
        function_calling=function_calling,
        structured_output=structured_output,
        tested_at=datetime.now(UTC),
    )


def _req() -> JudgmentGenerationRequest:
    return JudgmentGenerationRequest(
        name="judgments-1",
        description=None,
        query_set_id="qs_1",
        cluster_id="clu_1",
        target="products",
        current_template_id="tmpl_1",
        rubric="rate 0-3",
    )


def _detail(exc: HTTPException) -> dict[str, Any]:
    return cast(dict[str, Any], exc.detail)


def _patch_cap(monkeypatch: pytest.MonkeyPatch, value: Any) -> None:
    monkeypatch.setattr(
        "backend.app.services.agent_judgments_dispatch.read_capability_result",
        AsyncMock(return_value=value),
    )


def _patch_repo(monkeypatch: pytest.MonkeyPatch, name: str, value: Any) -> None:
    monkeypatch.setattr(
        f"backend.app.services.agent_judgments_dispatch.repo.{name}",
        AsyncMock(return_value=value),
    )


@pytest.mark.asyncio
async def test_openai_not_configured_when_key_missing() -> None:
    settings = _settings(openai_api_key=None)
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_judgment_generation(
            db=AsyncMock(), redis=AsyncMock(), arq_pool=None, settings=settings, req=_req()
        )
    assert ei.value.status_code == 503
    assert _detail(ei.value)["error_code"] == "OPENAI_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_llm_provider_incapable_on_cache_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cap(monkeypatch, None)
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(),
            req=_req(),
        )
    assert ei.value.status_code == 503
    assert _detail(ei.value)["error_code"] == "LLM_PROVIDER_INCAPABLE"
    assert "cache miss" in _detail(ei.value)["message"]


@pytest.mark.asyncio
async def test_llm_provider_incapable_on_model_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cap(monkeypatch, _cap(model="gpt-4o-2024-08-06"))
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(openai_model="gpt-4o-mini-2024-07-18"),
            req=_req(),
        )
    assert _detail(ei.value)["error_code"] == "LLM_PROVIDER_INCAPABLE"
    assert "cached probe model" in _detail(ei.value)["message"]


@pytest.mark.asyncio
async def test_llm_provider_incapable_on_structured_output_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cap(monkeypatch, _cap(structured_output="fail"))
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(),
            req=_req(),
        )
    assert _detail(ei.value)["error_code"] == "LLM_PROVIDER_INCAPABLE"


@pytest.mark.asyncio
async def test_unknown_model_pricing(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cap(monkeypatch, _cap(model="bogus-model"))
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(openai_model="bogus-model"),
            req=_req(),
        )
    assert _detail(ei.value)["error_code"] == "UNKNOWN_MODEL_PRICING"


@pytest.mark.asyncio
async def test_openai_budget_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cap(monkeypatch, _cap())
    monkeypatch.setattr(
        "backend.app.services.agent_judgments_dispatch.peek_daily_total",
        AsyncMock(return_value=10.0),
    )
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(openai_daily_budget_usd=5.0),
            req=_req(),
        )
    assert _detail(ei.value)["error_code"] == "OPENAI_BUDGET_EXCEEDED"


@pytest.mark.asyncio
async def test_cluster_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cap(monkeypatch, _cap())
    _patch_repo(monkeypatch, "get_cluster", None)
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(),
            req=_req(),
        )
    assert _detail(ei.value)["error_code"] == "CLUSTER_NOT_FOUND"


@pytest.mark.asyncio
async def test_template_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cap(monkeypatch, _cap())
    _patch_repo(monkeypatch, "get_cluster", MagicMock(engine_type="elasticsearch"))
    _patch_repo(monkeypatch, "get_query_template", None)
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(),
            req=_req(),
        )
    assert _detail(ei.value)["error_code"] == "TEMPLATE_NOT_FOUND"


@pytest.mark.asyncio
async def test_query_set_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cap(monkeypatch, _cap())
    _patch_repo(monkeypatch, "get_cluster", MagicMock(engine_type="elasticsearch"))
    _patch_repo(monkeypatch, "get_query_template", MagicMock(engine_type="elasticsearch"))
    _patch_repo(monkeypatch, "get_query_set", None)
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(),
            req=_req(),
        )
    assert _detail(ei.value)["error_code"] == "QUERY_SET_NOT_FOUND"


@pytest.mark.asyncio
async def test_cluster_query_set_mismatch_raises_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cap(monkeypatch, _cap())
    _patch_repo(monkeypatch, "get_cluster", MagicMock(engine_type="elasticsearch"))
    _patch_repo(monkeypatch, "get_query_template", MagicMock(engine_type="elasticsearch"))
    _patch_repo(monkeypatch, "get_query_set", MagicMock(cluster_id="different_cluster"))
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(),
            req=_req(),
        )
    assert ei.value.status_code == 422
    assert _detail(ei.value)["error_code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_engine_mismatch_raises_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cap(monkeypatch, _cap())
    _patch_repo(monkeypatch, "get_cluster", MagicMock(engine_type="elasticsearch"))
    _patch_repo(monkeypatch, "get_query_template", MagicMock(engine_type="opensearch"))
    _patch_repo(monkeypatch, "get_query_set", MagicMock(cluster_id="clu_1"))
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(),
            req=_req(),
        )
    assert ei.value.status_code == 422
    assert "engine_type" in _detail(ei.value)["message"]


@pytest.mark.asyncio
async def test_oversized_query_set_raises_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_cap(monkeypatch, _cap())
    _patch_repo(monkeypatch, "get_cluster", MagicMock(engine_type="elasticsearch"))
    _patch_repo(monkeypatch, "get_query_template", MagicMock(engine_type="elasticsearch"))
    _patch_repo(monkeypatch, "get_query_set", MagicMock(cluster_id="clu_1"))
    _patch_repo(monkeypatch, "count_queries_in_set", 10_001)
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(),
            req=_req(),
        )
    assert ei.value.status_code == 422
    assert "max 10000" in _detail(ei.value)["message"]
