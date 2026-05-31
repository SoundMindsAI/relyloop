# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``SolrAdapter._render_mm`` — min_should_match syntax (infra_adapter_solr Story A2).

Solr's ``mm`` is the most syntax-heavy field on the parameter map: it
accepts plain ints (``"2"``), percentages (``"75%"``), arithmetic
specs (``"2<-25% 9<-3"``), and bool combinations. The pivot just passes
strings through verbatim — but the test surface here pins that contract
so a future helper-rewrite (e.g., URL-escaping) can't silently break the
arithmetic form Solr templates depend on.
"""

from __future__ import annotations

import pytest

from backend.app.adapters.errors import InvalidQueryDSLError
from backend.app.adapters.solr import SolrAdapter


class TestMmIntInput:
    def test_int(self) -> None:
        assert SolrAdapter._render_mm(2) == ("mm", "2")

    def test_zero(self) -> None:
        # mm=0 means "no clause required" — valid Solr but rare.
        assert SolrAdapter._render_mm(0) == ("mm", "0")


class TestMmFloatInput:
    def test_float(self) -> None:
        # Solr doesn't have a "float mm" but Python templates may render
        # one via the search-space dimension. Convert it to the repr form
        # (Solr will treat it as the integer floor).
        assert SolrAdapter._render_mm(0.75) == ("mm", "0.75")


class TestMmStringInput:
    @pytest.mark.parametrize(
        "spec",
        [
            "75%",
            "100%",
            "50%",
            "2<-25% 9<-3",  # arithmetic — the canonical edismax pattern
            "3<90%",
            "1<-1 2<-2",
            "2<2 3<-1 4<50%",
            "2",  # ints-as-strings stay verbatim
        ],
    )
    def test_passes_through(self, spec: str) -> None:
        key, value = SolrAdapter._render_mm(spec)
        assert (key, value) == ("mm", spec)


class TestMmRejects:
    def test_none_rejected(self) -> None:
        with pytest.raises(InvalidQueryDSLError, match="int|float|str"):
            SolrAdapter._render_mm(None)

    def test_dict_rejected(self) -> None:
        with pytest.raises(InvalidQueryDSLError, match="int|float|str"):
            SolrAdapter._render_mm({"75": "%"})

    def test_list_rejected(self) -> None:
        with pytest.raises(InvalidQueryDSLError, match="int|float|str"):
            SolrAdapter._render_mm(["75%"])
