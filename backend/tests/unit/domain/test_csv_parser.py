"""Unit tests for ``parse_queries_csv`` (Story 3.2, FR-3)."""

from __future__ import annotations

import pytest

from backend.app.domain.study.csv_parser import InvalidCsvError, parse_queries_csv


def test_happy_path_with_optional_columns() -> None:
    body = (
        b"query_text,reference_answer\n"
        b"how do i reset my password,visit settings\n"
        b"what is the refund policy,30-day refund\n"
    )
    rows = parse_queries_csv(body)
    assert len(rows) == 2
    assert rows[0] == {
        "query_text": "how do i reset my password",
        "reference_answer": "visit settings",
        "query_metadata": None,
    }
    assert rows[1]["query_text"] == "what is the refund policy"


def test_extra_columns_become_metadata() -> None:
    body = b"query_text,topic,intent\nhello world,greeting,informational\n"
    rows = parse_queries_csv(body)
    assert len(rows) == 1
    assert rows[0]["query_metadata"] == {"topic": "greeting", "intent": "informational"}


def test_missing_required_column_rejected() -> None:
    body = b"reference_answer\nfoo\n"  # no query_text column
    with pytest.raises(InvalidCsvError, match="missing required column"):
        parse_queries_csv(body)


def test_blank_query_text_rejected() -> None:
    # Two-column row with the query_text cell empty (not a blank line —
    # csv.DictReader skips those).
    body = b"query_text,reference_answer\n,foo\n"
    with pytest.raises(InvalidCsvError, match="empty `query_text`"):
        parse_queries_csv(body)


def test_no_header_row_rejected() -> None:
    body = b""
    with pytest.raises(InvalidCsvError, match="no header row"):
        parse_queries_csv(body)


def test_non_utf8_body_rejected() -> None:
    body = b"\xff\xfe\xff\xfe"  # invalid UTF-8
    with pytest.raises(InvalidCsvError, match="not valid UTF-8"):
        parse_queries_csv(body)


def test_row_count_cap_enforced() -> None:
    rows = [f"row {i}" for i in range(10_001)]
    body = ("query_text\n" + "\n".join(rows) + "\n").encode("utf-8")
    with pytest.raises(InvalidCsvError, match="exceeds max row count"):
        parse_queries_csv(body)
