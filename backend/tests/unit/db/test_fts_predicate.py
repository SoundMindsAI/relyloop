# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``backend.app.db.repo._fts.fts_predicate``.

The FTS helper is the shared building block for every list/count repo
function that exposes a ``?q=`` parameter. These tests cover the small
contract:

- ``fts_predicate(None)`` returns ``None`` (no clause added).
- ``fts_predicate("")`` returns ``None`` (empty string treated as absent).
- ``fts_predicate("foo")`` returns a ``TextClause`` bound to the
  injection-safe ``plainto_tsquery('english', :q)`` shape.
- The compiled SQL string matches the literal source contract.
- The bound parameter is exactly the input string (no normalization,
  trimming, lowercasing — those are Pydantic's job upstream).
"""

from __future__ import annotations

import pytest
from sqlalchemy.sql.elements import TextClause

from backend.app.db.repo._fts import fts_predicate


def test_returns_none_for_none_input() -> None:
    assert fts_predicate(None) is None


def test_returns_none_for_empty_string() -> None:
    assert fts_predicate("") is None


@pytest.mark.parametrize("q", ["foo", "two words", "prod-es", "an entire sentence."])
def test_returns_text_clause_for_non_empty_input(q: str) -> None:
    clause = fts_predicate(q)
    assert clause is not None
    assert isinstance(clause, TextClause)


def test_clause_text_uses_plainto_tsquery_english() -> None:
    clause = fts_predicate("foo")
    assert clause is not None
    # plainto_tsquery does not parse operator characters — it's the
    # injection-safe variant by design (spec FR-1 + §10).
    assert "plainto_tsquery('english', :q)" in str(clause)
    assert "search_vector @@" in str(clause)


def test_bound_parameter_is_input_value_unchanged() -> None:
    q = "any string we want to pass; including punctuation & 'quotes'"
    clause = fts_predicate(q)
    assert clause is not None
    # The .compile()'d params dict carries the bound :q without
    # any normalization (trimming, casefolding, etc.) — Pydantic
    # at the router boundary is the only validator.
    compiled = clause.compile(compile_kwargs={"literal_binds": False})
    assert compiled.params == {"q": q}


def test_unicode_input_passes_through_unmodified() -> None:
    q = "café search 漢字"
    clause = fts_predicate(q)
    assert clause is not None
    assert clause.compile().params == {"q": q}
