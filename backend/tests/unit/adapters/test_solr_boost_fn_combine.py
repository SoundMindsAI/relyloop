# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``SolrAdapter._render_boost_fn`` — combine="add" → bf vs combine="multiply" → boost.

This pivot is the canonical case where the SAME unified parameter renders
to a DIFFERENT Solr key depending on a sub-field. Solr's ``bf`` (additive)
and ``boost`` (multiplicative) compose differently with the main score:

* ``bf=recip(ms(NOW,date),3.16e-11,1,1)`` — adds the function-query value to score.
* ``boost=mul(if(field,1.5,1.0),query({!edismax v=$q}))`` — multiplies.

Templates author one unified ``boost_fn`` and choose the math via
``combine``. The pivot does the literal key swap; the template author
keeps a single mental model.
"""

from __future__ import annotations

import pytest

from backend.app.adapters.errors import InvalidQueryDSLError
from backend.app.adapters.solr import SolrAdapter


class TestCombineAdd:
    def test_simple(self) -> None:
        key, value = SolrAdapter._render_boost_fn(
            {"expr": "recip(ms(NOW,date),3.16e-11,1,1)", "combine": "add"}
        )
        assert key == "bf"
        assert value == "recip(ms(NOW,date),3.16e-11,1,1)"

    def test_passes_arbitrary_function_query(self) -> None:
        key, value = SolrAdapter._render_boost_fn({"expr": "log(popularity)", "combine": "add"})
        assert (key, value) == ("bf", "log(popularity)")


class TestCombineMultiply:
    def test_simple(self) -> None:
        key, value = SolrAdapter._render_boost_fn(
            {"expr": "mul(if(in_stock,1.5,1.0))", "combine": "multiply"}
        )
        assert key == "boost"
        assert value == "mul(if(in_stock,1.5,1.0))"


class TestRejects:
    def test_missing_combine(self) -> None:
        with pytest.raises(InvalidQueryDSLError, match="combine"):
            SolrAdapter._render_boost_fn({"expr": "log(x)"})

    def test_invalid_combine_value(self) -> None:
        with pytest.raises(InvalidQueryDSLError, match="combine"):
            SolrAdapter._render_boost_fn({"expr": "log(x)", "combine": "subtract"})

    def test_empty_expr(self) -> None:
        with pytest.raises(InvalidQueryDSLError, match="expr"):
            SolrAdapter._render_boost_fn({"expr": "", "combine": "add"})

    def test_non_string_expr(self) -> None:
        with pytest.raises(InvalidQueryDSLError, match="expr"):
            SolrAdapter._render_boost_fn({"expr": 123, "combine": "add"})

    def test_non_dict(self) -> None:
        with pytest.raises(InvalidQueryDSLError, match="must be a dict"):
            SolrAdapter._render_boost_fn("recip(...)")
