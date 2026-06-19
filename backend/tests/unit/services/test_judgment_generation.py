# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for judgment-generation service helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.app.services.judgment_generation import _DOC_BODY_CHAR_LIMIT, _build_doc_inputs


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
