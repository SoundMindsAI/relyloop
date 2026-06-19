# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for judgment-generation service helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import pytest
import structlog
from structlog.testing import capture_logs

from backend.app.db import repo
from backend.app.llm.budget_gate import BudgetExceededError
from backend.app.llm.cost_model import UnknownModelPricingError
from backend.app.services.judgment_generation import (
    _DOC_BODY_CHAR_LIMIT,
    _build_doc_inputs,
    fail_on_budget_or_pricing_error,
)


@dataclass
class _Hit:
    doc_id: str
    source: Any


def test_prefers_source_body() -> None:
    rows = _build_doc_inputs([_Hit(doc_id="d1", source={"body": "hello"})])
    assert rows == [{"doc_id": "d1", "body": "hello"}]


def test_truncates_long_body() -> None:
    long = "x" * (_DOC_BODY_CHAR_LIMIT + 100)
    rows = _build_doc_inputs([_Hit(doc_id="d1", source={"body": long})])
    assert len(rows[0]["body"]) == _DOC_BODY_CHAR_LIMIT


def test_json_dumps_fallback_when_no_body() -> None:
    rows = _build_doc_inputs([_Hit(doc_id="d1", source={"title": "t", "n": 1})])
    # No ``body`` key → stable JSON dump of the source.
    assert rows[0]["doc_id"] == "d1"
    assert '"title"' in rows[0]["body"]


def test_str_fallback_when_source_not_json_serializable() -> None:
    # The Gemini-flagged path: a source carrying a non-serializable value must
    # fall back to str() rather than raising TypeError and aborting the run.
    class _Weird:
        def __repr__(self) -> str:
            return "<weird>"

    rows = _build_doc_inputs([_Hit(doc_id="d1", source={"obj": _Weird()})])
    assert rows[0]["doc_id"] == "d1"
    assert "weird" in rows[0]["body"]


class _FakeDB:
    async def commit(self) -> None: ...


class _FakeFactory:
    """Minimal async_sessionmaker stand-in: callable → async context manager."""

    def __call__(self) -> _FakeFactory:
        return self

    async def __aenter__(self) -> _FakeDB:
        return _FakeDB()

    async def __aexit__(self, *exc: object) -> bool:
        return False


@pytest.mark.parametrize(
    ("exc", "prefix", "expected_reason", "expected_event"),
    [
        (
            BudgetExceededError("over"),
            "judgment",
            "OPENAI_BUDGET_EXCEEDED",
            "judgment_budget_exceeded",
        ),
        (BudgetExceededError("over"), "ubi", "OPENAI_BUDGET_EXCEEDED", "ubi_budget_exceeded"),
        (
            UnknownModelPricingError("?"),
            "judgment",
            "UNKNOWN_MODEL_PRICING",
            "judgment_unknown_pricing",
        ),
        (UnknownModelPricingError("?"), "ubi", "UNKNOWN_MODEL_PRICING", "ubi_unknown_pricing"),
    ],
)
async def test_fail_on_budget_or_pricing_error(
    monkeypatch: pytest.MonkeyPatch,
    exc: Exception,
    prefix: str,
    expected_reason: str,
    expected_event: str,
) -> None:
    """Maps exc → failed_reason and emits the per-worker operability event_type."""
    captured: dict[str, Any] = {}

    async def fake_update(
        db: Any, jid: str, *, status: str, failed_reason: str | None = None
    ) -> None:
        captured["status"] = status
        captured["reason"] = failed_reason

    monkeypatch.setattr(repo, "update_judgment_list_status", fake_update)

    with capture_logs() as logs:
        await fail_on_budget_or_pricing_error(
            cast(Any, _FakeFactory()),
            "jl-1",
            cast(Any, exc),
            logger=structlog.get_logger("test"),
            event_prefix=prefix,
        )

    assert captured == {"status": "failed", "reason": expected_reason}
    assert any(entry.get("event_type") == expected_event for entry in logs)
