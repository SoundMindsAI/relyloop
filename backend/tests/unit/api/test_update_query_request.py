"""Unit tests for ``UpdateQueryRequest`` Pydantic validation (feat_query_inline_crud Story 2.2).

Pure-Pydantic validation; no DB. Covers:

* ``extra="forbid"`` rejects unknown keys (AC-10).
* ``min_length=1`` rejects empty ``query_text`` (AC-9).
* ``max_length=4000`` rejects long ``query_text``.
* ``@model_validator`` rejects explicit-null ``query_text`` (NOT NULL column;
  cycle-1 GPT-5.5 F1).
* Empty body ``{}`` validates cleanly (AC-28 no-op).
* ``model_dump(exclude_unset=True)`` differentiates omitted vs present-null
  (AC-7 vs AC-8).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.api.v1.schemas import UpdateQueryRequest


def test_empty_body_validates_as_no_op() -> None:
    req = UpdateQueryRequest()
    assert req.model_dump(exclude_unset=True) == {}


def test_extra_field_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        UpdateQueryRequest.model_validate({"id": "some-uuid"})
    assert "extra" in str(exc.value).lower() or "forbidden" in str(exc.value).lower()


def test_empty_query_text_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        UpdateQueryRequest.model_validate({"query_text": ""})
    assert "at least 1" in str(exc.value).lower() or "min_length" in str(exc.value).lower()


def test_too_long_query_text_rejected() -> None:
    with pytest.raises(ValidationError) as exc:
        UpdateQueryRequest.model_validate({"query_text": "x" * 4001})
    assert "at most 4000" in str(exc.value).lower() or "max_length" in str(exc.value).lower()


def test_explicit_null_query_text_rejected() -> None:
    """``query_text`` is NOT NULL on the underlying table — explicit null is 422."""
    with pytest.raises(ValidationError) as exc:
        UpdateQueryRequest.model_validate({"query_text": None})
    assert "cannot be null" in str(exc.value).lower()


def test_omitted_query_text_allowed() -> None:
    """Omitted key (no key in body) is fine — means 'no change'."""
    req = UpdateQueryRequest.model_validate({"reference_answer": "x"})
    assert "query_text" not in req.model_fields_set
    assert req.model_dump(exclude_unset=True) == {"reference_answer": "x"}


def test_explicit_null_reference_answer_allowed() -> None:
    """``reference_answer`` IS nullable — explicit null means 'clear the column'."""
    req = UpdateQueryRequest.model_validate({"reference_answer": None})
    assert "reference_answer" in req.model_fields_set
    assert req.model_dump(exclude_unset=True) == {"reference_answer": None}


def test_explicit_null_query_metadata_allowed() -> None:
    """``query_metadata`` IS nullable — explicit null means 'clear the column'."""
    req = UpdateQueryRequest.model_validate({"query_metadata": None})
    assert "query_metadata" in req.model_fields_set
    assert req.model_dump(exclude_unset=True) == {"query_metadata": None}


def test_query_metadata_object_replaces_whole() -> None:
    """Whole-object replace — not deep-merge."""
    req = UpdateQueryRequest.model_validate({"query_metadata": {"intent": "info"}})
    assert req.model_dump(exclude_unset=True) == {"query_metadata": {"intent": "info"}}


def test_all_three_fields_present() -> None:
    req = UpdateQueryRequest.model_validate(
        {
            "query_text": "new text",
            "reference_answer": "new ref",
            "query_metadata": {"k": "v"},
        }
    )
    dumped = req.model_dump(exclude_unset=True)
    assert dumped == {
        "query_text": "new text",
        "reference_answer": "new ref",
        "query_metadata": {"k": "v"},
    }


def test_minimum_query_text_length_one() -> None:
    """Boundary: 1-char ``query_text`` is the minimum allowed."""
    req = UpdateQueryRequest.model_validate({"query_text": "x"})
    assert req.query_text == "x"


def test_maximum_query_text_length_4000() -> None:
    """Boundary: 4000-char ``query_text`` is the maximum allowed."""
    text = "x" * 4000
    req = UpdateQueryRequest.model_validate({"query_text": text})
    assert req.query_text == text
