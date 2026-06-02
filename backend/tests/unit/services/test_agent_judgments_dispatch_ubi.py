# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``start_ubi_judgment_generation`` (feat_ubi_judgments
Story 2.2 / FR-4).

Mirrors :mod:`test_agent_judgments_dispatch` (LLM-side dispatcher) so the
two preflight chains read side-by-side. Mocks adapter + Redis via
``monkeypatch.setattr`` at module-level attribute paths
(``read_or_recompute_capability_result``, ``peek_daily_total``, ``repo.<fn>``,
``build_adapter``, ``count_ubi_events_in_window``).

Lives in ``backend/tests/unit/services/`` (matches the layer convention
for no-DB service tests; see test_ubi_reader.py docstring for the
rationale).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from backend.app.llm.capability_models import CapabilityResult
from backend.app.services import agent_judgments_dispatch as dispatch
from backend.app.services.agent_judgments_dispatch import UbiJudgmentGenerationRequest
from backend.app.services.ubi_errors import UbiNotEnabledError


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


def _cap() -> CapabilityResult:
    return CapabilityResult(
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini-2024-07-18",
        models_endpoint="ok",
        chat_completion="ok",
        function_calling="ok",
        structured_output="ok",
        tested_at=datetime.now(UTC),
    )


def _ubi_req(
    *,
    converter: str = "ctr_threshold",
    current_template_id: str | None = None,
    rubric: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    min_impressions_threshold: int | None = 100,
) -> UbiJudgmentGenerationRequest:
    return UbiJudgmentGenerationRequest(
        name="ubi-judgments-1",
        description=None,
        query_set_id="qs_1",
        cluster_id="clu_1",
        target="products",
        since=since or datetime(2026, 5, 1, tzinfo=UTC),
        until=until or datetime(2026, 5, 29, tzinfo=UTC),
        converter=cast(Any, converter),
        converter_config=None,
        llm_fill_threshold=20 if converter == "hybrid_ubi_llm" else None,
        min_impressions_threshold=min_impressions_threshold,
        mapping_strategy="reject",
        current_template_id=current_template_id,
        rubric=rubric,
    )


def _detail(exc: HTTPException) -> dict[str, Any]:
    return cast(dict[str, Any], exc.detail)


def _patch_repo(monkeypatch: pytest.MonkeyPatch, name: str, value: Any) -> None:
    """Wrap ``value`` in :class:`AsyncMock(return_value=value)` so
    ``await repo.<name>(...)`` resolves to ``value``. Always wraps —
    MagicMock instances are themselves callable but not awaitable, so
    skipping the wrap on callables (the prior heuristic) silently broke
    the await chain."""
    monkeypatch.setattr(
        f"backend.app.services.agent_judgments_dispatch.repo.{name}",
        AsyncMock(return_value=value),
    )


def _patch_adapter(monkeypatch: pytest.MonkeyPatch, **stubbed: Any) -> MagicMock:
    """Patch build_adapter to return a MagicMock whose async methods can be scripted."""
    adapter = MagicMock()
    adapter.engine_type = stubbed.get("engine_type", "opensearch")
    adapter.aclose = AsyncMock()
    # UbiReader._probe_enabled calls adapter.get_schema('ubi_queries').
    if "schema_raises" in stubbed:
        adapter.get_schema = AsyncMock(side_effect=stubbed["schema_raises"])
    else:
        from backend.app.adapters.protocol import Schema

        adapter.get_schema = AsyncMock(return_value=Schema(name="ubi_queries", fields=[]))
    monkeypatch.setattr(
        "backend.app.services.agent_judgments_dispatch.build_adapter",
        lambda c: adapter,
    )
    return adapter


def _patch_count(monkeypatch: pytest.MonkeyPatch, observed: int) -> None:
    monkeypatch.setattr(
        "backend.app.services.agent_judgments_dispatch.count_ubi_events_in_window",
        AsyncMock(return_value=observed),
    )


def _patch_cap(monkeypatch: pytest.MonkeyPatch, value: Any = None) -> None:
    # bug_llm_capability_cache_no_refresh swapped read_capability_result →
    # read_or_recompute_capability_result at the dispatch import site;
    # patching the new symbol so monkeypatch actually intercepts the call.
    monkeypatch.setattr(
        "backend.app.services.agent_judgments_dispatch.read_or_recompute_capability_result",
        AsyncMock(return_value=value if value is not None else _cap()),
    )


# ----------------------------------------------------------------------------
# U-A: FK resolution
# ----------------------------------------------------------------------------


async def test_cluster_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_repo(monkeypatch, "get_cluster", None)
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_ubi_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(),
            req=_ubi_req(),
        )
    assert _detail(ei.value)["error_code"] == "CLUSTER_NOT_FOUND"


async def test_query_set_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_repo(monkeypatch, "get_cluster", MagicMock(engine_type="opensearch"))
    _patch_repo(monkeypatch, "get_query_set", None)
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_ubi_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(),
            req=_ubi_req(),
        )
    assert _detail(ei.value)["error_code"] == "QUERY_SET_NOT_FOUND"


async def test_hybrid_template_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_repo(monkeypatch, "get_cluster", MagicMock(engine_type="opensearch"))
    _patch_repo(monkeypatch, "get_query_template", None)
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_ubi_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(),
            req=_ubi_req(
                converter="hybrid_ubi_llm",
                current_template_id="t1",
                rubric="rate 0-3",
            ),
        )
    assert _detail(ei.value)["error_code"] == "TEMPLATE_NOT_FOUND"


# ----------------------------------------------------------------------------
# U-B: Consistency
# ----------------------------------------------------------------------------


async def test_cluster_query_set_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_repo(monkeypatch, "get_cluster", MagicMock(engine_type="opensearch"))
    _patch_repo(monkeypatch, "get_query_set", MagicMock(cluster_id="other"))
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_ubi_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(),
            req=_ubi_req(),
        )
    assert ei.value.status_code == 422
    assert _detail(ei.value)["error_code"] == "VALIDATION_ERROR"


# ----------------------------------------------------------------------------
# U-C: UBI not enabled
# ----------------------------------------------------------------------------


async def test_ubi_not_enabled_raises_412(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_repo(monkeypatch, "get_cluster", MagicMock(engine_type="opensearch"))
    _patch_repo(monkeypatch, "get_query_set", MagicMock(cluster_id="clu_1"))
    _patch_adapter(monkeypatch, schema_raises=UbiNotEnabledError("missing"))
    # The UbiReader probe wraps TargetNotFoundError → UbiNotEnabledError,
    # but if the adapter raises UbiNotEnabledError directly the dispatcher
    # also handles it. The adapter's get_schema is what UbiReader._probe_enabled
    # calls; here we wire it to raise TargetNotFoundError to exercise the real path.
    from backend.app.adapters.errors import TargetNotFoundError as _TNF

    _patch_adapter(monkeypatch, schema_raises=_TNF("ubi_queries"))
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_ubi_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(),
            req=_ubi_req(),
        )
    assert ei.value.status_code == 412
    assert _detail(ei.value)["error_code"] == "UBI_NOT_ENABLED"


# ----------------------------------------------------------------------------
# U-D: Window validity + 90-day cap
# ----------------------------------------------------------------------------


async def test_window_too_large_raises_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_repo(monkeypatch, "get_cluster", MagicMock(engine_type="opensearch"))
    _patch_repo(monkeypatch, "get_query_set", MagicMock(cluster_id="clu_1"))
    _patch_adapter(monkeypatch)
    since = datetime(2026, 1, 1, tzinfo=UTC)
    until = since + timedelta(days=120)
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_ubi_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(),
            req=_ubi_req(since=since, until=until),
        )
    assert _detail(ei.value)["error_code"] == "UBI_WINDOW_TOO_LARGE"


async def test_since_not_before_until_raises_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_repo(monkeypatch, "get_cluster", MagicMock(engine_type="opensearch"))
    _patch_repo(monkeypatch, "get_query_set", MagicMock(cluster_id="clu_1"))
    _patch_adapter(monkeypatch)
    same = datetime(2026, 5, 1, tzinfo=UTC)
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_ubi_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(),
            req=_ubi_req(since=same, until=same),
        )
    assert _detail(ei.value)["error_code"] == "VALIDATION_ERROR"


async def test_naive_datetimes_do_not_crash_window_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for Gemini PR #317 finding #1.

    A naive ``since`` (no tzinfo — what Pydantic produces from an ISO-8601
    string without an offset) must NOT raise TypeError when compared with
    the aware ``datetime.now(UTC)`` inside the window check. The dispatcher
    normalizes naive inputs to UTC up front. We push past U-C/U-D into the
    sync count gate to prove the comparison didn't crash — the request has a
    valid 28-day window, so it should reach U-D2 and reject with
    UBI_INSUFFICIENT_DATA (observed < threshold), not TypeError.
    """
    _patch_repo(monkeypatch, "get_cluster", MagicMock(engine_type="opensearch"))
    _patch_repo(monkeypatch, "get_query_set", MagicMock(cluster_id="clu_1"))
    _patch_adapter(monkeypatch)
    _patch_count(monkeypatch, observed=0)
    naive_since = datetime(2026, 5, 1)  # noqa: DTZ001 — intentionally naive
    naive_until = datetime(2026, 5, 28)  # noqa: DTZ001 — intentionally naive
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_ubi_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(),
            req=_ubi_req(since=naive_since, until=naive_until),
        )
    # Reached U-D2 without a TypeError crash on the window comparison.
    assert _detail(ei.value)["error_code"] == "UBI_INSUFFICIENT_DATA"


async def test_naive_since_with_none_until_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Naive ``since`` + ``until=None`` (defaults to now) must not crash either."""
    _patch_repo(monkeypatch, "get_cluster", MagicMock(engine_type="opensearch"))
    _patch_repo(monkeypatch, "get_query_set", MagicMock(cluster_id="clu_1"))
    _patch_adapter(monkeypatch)
    _patch_count(monkeypatch, observed=0)
    naive_since = datetime.now().replace(microsecond=0) - timedelta(days=7)  # noqa: DTZ005
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_ubi_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(),
            req=_ubi_req(since=naive_since, until=None),
        )
    assert _detail(ei.value)["error_code"] == "UBI_INSUFFICIENT_DATA"


# ----------------------------------------------------------------------------
# U-D2: Sync UBI_INSUFFICIENT_DATA gate
# ----------------------------------------------------------------------------


async def test_insufficient_data_pure_converter_hints_hybrid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_repo(monkeypatch, "get_cluster", MagicMock(engine_type="opensearch"))
    _patch_repo(monkeypatch, "get_query_set", MagicMock(cluster_id="clu_1"))
    _patch_adapter(monkeypatch)
    _patch_count(monkeypatch, observed=23)  # < default threshold 100
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_ubi_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(),
            req=_ubi_req(converter="ctr_threshold"),
        )
    assert _detail(ei.value)["error_code"] == "UBI_INSUFFICIENT_DATA"
    assert "hybrid_ubi_llm" in _detail(ei.value)["message"]
    assert "23" in _detail(ei.value)["message"]


async def test_insufficient_data_hybrid_hints_window_widening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_repo(monkeypatch, "get_cluster", MagicMock(engine_type="opensearch"))
    _patch_repo(monkeypatch, "get_query_set", MagicMock(cluster_id="clu_1"))
    _patch_repo(monkeypatch, "get_query_template", MagicMock(engine_type="opensearch"))
    _patch_adapter(monkeypatch)
    _patch_count(monkeypatch, observed=5)
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_ubi_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(),
            req=_ubi_req(
                converter="hybrid_ubi_llm",
                current_template_id="t1",
                rubric="rate 0-3",
            ),
        )
    assert _detail(ei.value)["error_code"] == "UBI_INSUFFICIENT_DATA"
    msg = _detail(ei.value)["message"]
    assert "widen" in msg.lower()
    assert "hybrid_ubi_llm" not in msg


# ----------------------------------------------------------------------------
# U-E: Hybrid mode runs LLM preflight
# ----------------------------------------------------------------------------


async def test_hybrid_mode_runs_llm_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_repo(monkeypatch, "get_cluster", MagicMock(engine_type="opensearch"))
    _patch_repo(monkeypatch, "get_query_set", MagicMock(cluster_id="clu_1"))
    _patch_repo(monkeypatch, "get_query_template", MagicMock(engine_type="opensearch"))
    _patch_adapter(monkeypatch)
    _patch_count(monkeypatch, observed=1000)
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_ubi_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(openai_api_key=None),  # forces OPENAI_NOT_CONFIGURED
            req=_ubi_req(
                converter="hybrid_ubi_llm",
                current_template_id="t1",
                rubric="rate 0-3",
            ),
        )
    assert _detail(ei.value)["error_code"] == "OPENAI_NOT_CONFIGURED"


async def test_pure_converter_skips_llm_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pure UBI never hits the LLM preflight — bad key shouldn't matter."""
    _patch_repo(monkeypatch, "get_cluster", MagicMock(engine_type="opensearch"))
    _patch_repo(monkeypatch, "get_query_set", MagicMock(cluster_id="clu_1"))
    _patch_adapter(monkeypatch)
    _patch_count(monkeypatch, observed=1000)
    _patch_repo(monkeypatch, "count_queries_in_set", 100)
    inserted: dict[str, Any] = {}

    async def _capture_create(db: Any, **fields: Any) -> Any:
        inserted.update(fields)
        return MagicMock()

    monkeypatch.setattr(
        "backend.app.services.agent_judgments_dispatch.repo.create_judgment_list",
        _capture_create,
    )
    db = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    result = await dispatch.start_ubi_judgment_generation(
        db=db,
        redis=AsyncMock(),
        arq_pool=None,
        settings=_settings(openai_api_key=None),  # would fail LLM preflight; pure skips
        req=_ubi_req(converter="ctr_threshold"),
    )
    assert result.status == "generating"
    # generation_params discriminator persisted server-side.
    assert inserted["generation_params"]["generation_kind"] == "ubi"
    assert inserted["generation_params"]["converter"] == "ctr_threshold"


# ----------------------------------------------------------------------------
# U-F: oversized query set
# ----------------------------------------------------------------------------


async def test_oversized_query_set_raises_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_repo(monkeypatch, "get_cluster", MagicMock(engine_type="opensearch"))
    _patch_repo(monkeypatch, "get_query_set", MagicMock(cluster_id="clu_1"))
    _patch_adapter(monkeypatch)
    _patch_count(monkeypatch, observed=1000)
    _patch_repo(monkeypatch, "count_queries_in_set", 20_000)
    with pytest.raises(HTTPException) as ei:
        await dispatch.start_ubi_judgment_generation(
            db=AsyncMock(),
            redis=AsyncMock(),
            arq_pool=None,
            settings=_settings(),
            req=_ubi_req(),
        )
    assert _detail(ei.value)["error_code"] == "VALIDATION_ERROR"
    assert "max 10000" in _detail(ei.value)["message"]


# ----------------------------------------------------------------------------
# Happy path — generation_params discriminator + insert + enqueue
# ----------------------------------------------------------------------------


async def test_happy_path_pure_converter_inserts_generation_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_repo(monkeypatch, "get_cluster", MagicMock(engine_type="opensearch"))
    _patch_repo(monkeypatch, "get_query_set", MagicMock(cluster_id="clu_1"))
    _patch_adapter(monkeypatch)
    _patch_count(monkeypatch, observed=500)
    _patch_repo(monkeypatch, "count_queries_in_set", 50)
    inserted: dict[str, Any] = {}

    async def _capture_create(db: Any, **fields: Any) -> Any:
        inserted.update(fields)
        return MagicMock()

    monkeypatch.setattr(
        "backend.app.services.agent_judgments_dispatch.repo.create_judgment_list",
        _capture_create,
    )
    db = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    enqueued: list[dict[str, Any]] = []

    arq_pool = MagicMock()

    async def _enqueue(name: str, *args: Any, **kw: Any) -> None:
        enqueued.append({"name": name, "args": args, "kw": kw})

    arq_pool.enqueue_job = _enqueue

    result = await dispatch.start_ubi_judgment_generation(
        db=db,
        redis=AsyncMock(),
        arq_pool=arq_pool,
        settings=_settings(),
        req=_ubi_req(converter="dwell_time"),
    )

    assert result.status == "generating"
    # Persisted shape.
    assert inserted["target"] == "products"
    assert inserted["current_template_id"] is None  # pure
    assert inserted["rubric"] == "UBI converter: dwell_time"
    assert inserted["generation_params"]["generation_kind"] == "ubi"
    assert inserted["generation_params"]["converter"] == "dwell_time"
    assert inserted["generation_params"]["mapping_strategy"] == "reject"
    # Enqueued the UBI worker.
    assert enqueued == [
        {
            "name": "generate_judgments_from_ubi",
            "args": (result.judgment_list_id,),
            "kw": {"_job_id": f"generate_judgments_from_ubi:{result.judgment_list_id}"},
        }
    ]


async def test_happy_path_hybrid_uses_operator_rubric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_repo(monkeypatch, "get_cluster", MagicMock(engine_type="opensearch"))
    _patch_repo(monkeypatch, "get_query_set", MagicMock(cluster_id="clu_1"))
    _patch_repo(monkeypatch, "get_query_template", MagicMock(engine_type="opensearch"))
    _patch_adapter(monkeypatch)
    _patch_count(monkeypatch, observed=500)
    _patch_repo(monkeypatch, "count_queries_in_set", 50)
    _patch_cap(monkeypatch)
    monkeypatch.setattr(
        "backend.app.services.agent_judgments_dispatch.peek_daily_total",
        AsyncMock(return_value=0.0),
    )

    inserted: dict[str, Any] = {}

    async def _capture_create(db: Any, **fields: Any) -> Any:
        inserted.update(fields)
        return MagicMock()

    monkeypatch.setattr(
        "backend.app.services.agent_judgments_dispatch.repo.create_judgment_list",
        _capture_create,
    )
    db = MagicMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()

    result = await dispatch.start_ubi_judgment_generation(
        db=db,
        redis=AsyncMock(),
        arq_pool=None,
        settings=_settings(),
        req=_ubi_req(
            converter="hybrid_ubi_llm",
            current_template_id="t1",
            rubric="hand-written rubric",
        ),
    )
    assert result.status == "generating"
    assert inserted["rubric"] == "hand-written rubric"
    assert inserted["current_template_id"] == "t1"
    assert inserted["generation_params"]["generation_kind"] == "ubi"
    assert inserted["generation_params"]["converter"] == "hybrid_ubi_llm"
    assert inserted["generation_params"]["rubric"] == "hand-written rubric"
    assert inserted["generation_params"]["current_template_id"] == "t1"
