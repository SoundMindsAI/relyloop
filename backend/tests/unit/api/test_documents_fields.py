"""Unit tests for ``backend/app/api/v1/_documents_fields.py``.

Per ``feat_index_document_browser`` Story 2.1 (cycle-2 F2 / cycle-3 F3).
Covers whitespace trim, dedup, dotted paths, wildcard rejection, and the
empty-after-trim → None case.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.app.api.v1._documents_fields import parse_fields_csv


def test_none_returns_none() -> None:
    assert parse_fields_csv(None) is None


def test_empty_string_returns_none() -> None:
    assert parse_fields_csv("") is None


def test_all_commas_returns_none() -> None:
    assert parse_fields_csv(",,,") is None


def test_whitespace_only_returns_none() -> None:
    assert parse_fields_csv("   ") is None


def test_simple_csv() -> None:
    assert parse_fields_csv("title,brand") == ["title", "brand"]


def test_whitespace_trim() -> None:
    assert parse_fields_csv(" a , b ") == ["a", "b"]


def test_dedup_preserving_order() -> None:
    assert parse_fields_csv("a,b,a,c,b") == ["a", "b", "c"]


def test_dotted_paths() -> None:
    assert parse_fields_csv("title.keyword,brand.raw") == ["title.keyword", "brand.raw"]


def test_wildcard_bare_rejected() -> None:
    with pytest.raises(HTTPException) as exc_info:
        parse_fields_csv("*")
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["error_code"] == "VALIDATION_ERROR"  # type: ignore[index]


def test_wildcard_prefix_rejected() -> None:
    with pytest.raises(HTTPException) as exc_info:
        parse_fields_csv("title*")
    assert exc_info.value.status_code == 422


def test_wildcard_in_dotted_rejected() -> None:
    with pytest.raises(HTTPException) as exc_info:
        parse_fields_csv("title.*")
    assert exc_info.value.status_code == 422


def test_mix_valid_and_wildcard_rejected() -> None:
    with pytest.raises(HTTPException):
        parse_fields_csv("title,brand,*")
