# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``_SourceBreakdown`` evolution + UBI wire-Literal locks (feat_ubi_judgments
Story 2.3 / FR-9 + FR-10).

The cycle-2 F6 "click folds into human" contract was forward-compat
fiction — the moment UBI ships click rows (Story 3.3 worker), the UI
needs the three buckets surfaced separately. These tests lock the new
shape so a future refactor can't silently regress to two terms.
"""

from __future__ import annotations

import json

import pytest

from backend.app.api.v1.schemas import (
    JudgmentGenerationMethodWire,
    JudgmentSourceFilterWire,
    JudgmentSourceWire,
    UbiConverterKind,
    UbiMappingStrategyWire,
    UbiReadinessRungWire,
    _SourceBreakdown,
)


class TestSourceBreakdown:
    def test_three_buckets_field_access(self) -> None:
        sb = _SourceBreakdown(llm=10, human=5, click=20)
        assert sb.llm == 10
        assert sb.human == 5
        assert sb.click == 20

    def test_json_serialization_includes_all_three(self) -> None:
        sb = _SourceBreakdown(llm=10, human=5, click=20)
        payload = json.loads(sb.model_dump_json())
        assert payload == {"llm": 10, "human": 5, "click": 20}

    def test_click_is_required_no_silent_default(self) -> None:
        """If a future refactor drops ``click``, this test fails loudly."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _SourceBreakdown(llm=10, human=5)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Wire-value Literal locks (FR-9)
# ---------------------------------------------------------------------------


def _literal_values(literal_alias: object) -> set[str | int]:
    """Extract ``Literal[...]`` member values via __args__ (post-alias unwrap)."""
    from typing import get_args

    return set(get_args(literal_alias))


def test_judgment_source_filter_wire_includes_click() -> None:
    """FR-10 widening: ``?source=click`` MUST be accepted (was 422 in cycle 2)."""
    assert _literal_values(JudgmentSourceFilterWire) == {"llm", "human", "click"}


def test_judgment_source_wire_unchanged() -> None:
    """``JudgmentSourceWire`` already named ``click`` (Story 1.2 forward-compat)."""
    assert _literal_values(JudgmentSourceWire) == {"llm", "human", "click"}


def test_ubi_converter_kind_locks_three_values() -> None:
    assert _literal_values(UbiConverterKind) == {
        "ctr_threshold",
        "dwell_time",
        "hybrid_ubi_llm",
    }


def test_judgment_generation_method_wire_is_superset_of_converter_kind() -> None:
    """The frontend method picker adds ``llm`` to the converter set."""
    methods = _literal_values(JudgmentGenerationMethodWire)
    converters = _literal_values(UbiConverterKind)
    assert methods == converters | {"llm"}


def test_ubi_readiness_rung_wire_four_values() -> None:
    assert _literal_values(UbiReadinessRungWire) == {
        "rung_0",
        "rung_1",
        "rung_2",
        "rung_3",
    }


def test_ubi_mapping_strategy_wire_three_values() -> None:
    assert _literal_values(UbiMappingStrategyWire) == {
        "reject",
        "first_match",
        "most_recent",
    }
