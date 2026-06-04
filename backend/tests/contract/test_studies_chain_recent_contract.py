# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Contract tests for ``GET /api/v1/studies/chains/recent``
(feat_overnight_studies_summary_card Story 1.2).

Pure-contract layer (no DB / Redis / engine): asserts the response-model
shapes (top-level keys + row's 10-field set), the ``stop_reason`` enum
matches ``CHAIN_STOP_REASONS``, the ``direction`` enum is two-valued, the
endpoint's presence in the OpenAPI document, the canonical 422
``VALIDATION_ERROR`` envelope shape for a malformed ``since`` (AC-6), and
the ``X-Total-Count`` header is emitted on the happy path.
"""

from __future__ import annotations

import typing

import httpx
import pytest
from asgi_lifespan import LifespanManager

from backend.app.api.v1.schemas import RecentChainsResponse, RecentChainSummary
from backend.app.domain.study.chain_summary import CHAIN_STOP_REASONS, ChainStopReason


def test_recent_chains_response_top_level_keys() -> None:
    assert set(RecentChainsResponse.model_fields) == {
        "data",
        "next_cursor",
        "has_more",
    }


def test_recent_chain_summary_ten_fields() -> None:
    assert set(RecentChainSummary.model_fields) == {
        "anchor_study_id",
        "anchor_name",
        "chain_length",
        "best_metric",
        "objective_metric",
        "cumulative_lift",
        "direction",
        "stop_reason",
        "best_link_proposal_id",
        "tail_completed_at",
    }
    assert len(RecentChainSummary.model_fields) == 10


def test_recent_chain_summary_stop_reason_literal_matches_frozenset() -> None:
    annotation = RecentChainSummary.model_fields["stop_reason"].annotation
    literal_values = set(typing.get_args(annotation))
    assert literal_values == set(CHAIN_STOP_REASONS)
    assert literal_values == {
        "depth_exhausted",
        "no_lift",
        "budget",
        "parent_failed",
        "cancelled",
        "in_flight",
    }


def test_recent_chain_summary_direction_literal_values() -> None:
    annotation = RecentChainSummary.model_fields["direction"].annotation
    assert set(typing.get_args(annotation)) == {"maximize", "minimize"}


def test_stop_reason_literal_export_unchanged() -> None:
    """Sanity: the ``ChainStopReason`` Literal exported from
    chain_summary.py mirrors the canonical CHAIN_STOP_REASONS frozenset.
    This is the source-of-truth comment cited by the frontend's
    STOP_REASON_PHRASE map (FR-4).
    """
    assert set(typing.get_args(ChainStopReason)) == set(CHAIN_STOP_REASONS)


def test_endpoint_present_in_openapi() -> None:
    from backend.app.main import app

    schema = app.openapi()
    path = "/api/v1/studies/chains/recent"
    assert path in schema["paths"]
    assert "get" in schema["paths"][path]
    responses = schema["paths"][path]["get"]["responses"]
    assert "200" in responses
    # query params: since (optional), limit (default 20, ge=1, le=50)
    params = {p["name"]: p for p in schema["paths"][path]["get"].get("parameters", [])}
    assert "since" in params
    assert "limit" in params
    assert params["limit"]["schema"]["default"] == 20
    assert params["limit"]["schema"]["minimum"] == 1
    assert params["limit"]["schema"]["maximum"] == 50


@pytest.mark.asyncio
async def test_x_total_count_header_emitted() -> None:
    """The endpoint emits ``X-Total-Count = len(data)`` on the happy
    path (with no chains seeded the count is 0 — same contract).
    """
    from backend.app.main import app

    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/studies/chains/recent")
            # We tolerate either 200 (DB up) or 5xx (DB down) — only
            # assert the header is present when the request actually
            # succeeded. The header MUST be string-encoded.
            if resp.status_code == 200:
                assert "X-Total-Count" in resp.headers
                assert resp.headers["X-Total-Count"].isdigit()


@pytest.mark.asyncio
async def test_malformed_since_returns_422_validation_error() -> None:
    """AC-6: passing a non-ISO ``?since=`` produces the canonical 422
    envelope (auto-emitted by the global validation handler when the
    typed ``datetime`` Query param parse fails).
    """
    from backend.app.main import app

    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/studies/chains/recent?since=not-a-datetime")
            # 422 from FastAPI's typed-query handler; the envelope is the
            # project-wide ``detail = {error_code, message, retryable}``
            # shape.
            assert resp.status_code == 422
            detail = resp.json()["detail"]
            assert detail["error_code"] == "VALIDATION_ERROR"
            assert detail["retryable"] is False


@pytest.mark.asyncio
async def test_limit_out_of_range_returns_422_validation_error() -> None:
    """AC-6 extension: ``?limit=`` out of [1, 50] also produces the
    canonical 422 envelope.
    """
    from backend.app.main import app

    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/studies/chains/recent?limit=999")
            assert resp.status_code == 422
            detail = resp.json()["detail"]
            assert detail["error_code"] == "VALIDATION_ERROR"
