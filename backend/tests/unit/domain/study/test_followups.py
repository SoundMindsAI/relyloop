"""Unit tests for the ``FollowupItem`` discriminated union (Story 1.1).

Pure tests — no DB, no I/O. Covers:

- Per-kind round-trip serialization through ``model_dump`` / ``model_validate``.
- Rejection of unknown ``kind``.
- Rejection of ``narrow``/``widen`` with null ``search_space``.
- Rejection of ``text`` with non-null ``search_space``.
- ``extra="forbid"`` enforcement.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.app.domain.study.followups import (
    FOLLOWUP_KIND_VALUES,
    FollowupItemAdapter,
    FollowupListAdapter,
    NarrowFollowup,
    SwapTemplateFollowup,
    TextFollowup,
    WidenFollowup,
    serialize_followup_list,
)
from backend.app.domain.study.search_space import SearchSpace

# Reusable small search-space fixture — 2 floats * 1 int = 2 * 5 = bounded cardinality.
VALID_SEARCH_SPACE_DICT = {
    "params": {
        "title_boost": {"type": "float", "low": 0.5, "high": 2.0},
        "tie_breaker": {"type": "int", "low": 1, "high": 5},
    }
}


def _make_narrow() -> dict[str, object]:
    return {
        "kind": "narrow",
        "rationale": "narrow around the winner",
        "search_space": VALID_SEARCH_SPACE_DICT,
    }


def _make_widen() -> dict[str, object]:
    return {
        "kind": "widen",
        "rationale": "widen because winner hit edge",
        "search_space": VALID_SEARCH_SPACE_DICT,
    }


def _make_text() -> dict[str, object]:
    return {
        "kind": "text",
        "rationale": "try a different analyzer",
        "search_space": None,
    }


# 36-char UUIDv7-shaped fixture string (matches the SwapTemplateFollowup
# template_id min/max length constraint).
VALID_TEMPLATE_ID = "01931e8a-1234-7890-abcd-ef0123456789"


def _make_swap_template() -> dict[str, object]:
    return {
        "kind": "swap_template",
        "rationale": "swap to template B because phrase params dominate",
        "template_id": VALID_TEMPLATE_ID,
        "search_space": VALID_SEARCH_SPACE_DICT,
    }


class TestNarrowFollowup:
    def test_round_trip(self) -> None:
        raw = _make_narrow()
        parsed = FollowupItemAdapter.validate_python(raw)
        assert isinstance(parsed, NarrowFollowup)
        # Dump + re-parse should produce an equivalent object.
        dumped = parsed.model_dump(mode="json")
        assert dumped["kind"] == "narrow"
        assert dumped["rationale"] == "narrow around the winner"
        assert isinstance(dumped["search_space"], dict)
        re_parsed = FollowupItemAdapter.validate_python(dumped)
        assert isinstance(re_parsed, NarrowFollowup)

    def test_rejects_null_search_space(self) -> None:
        raw = _make_narrow()
        raw["search_space"] = None
        with pytest.raises(ValidationError):
            FollowupItemAdapter.validate_python(raw)

    def test_rejects_extra_field(self) -> None:
        raw = _make_narrow()
        raw["extra_field"] = "nope"
        with pytest.raises(ValidationError):
            FollowupItemAdapter.validate_python(raw)


class TestWidenFollowup:
    def test_round_trip(self) -> None:
        raw = _make_widen()
        parsed = FollowupItemAdapter.validate_python(raw)
        assert isinstance(parsed, WidenFollowup)
        dumped = parsed.model_dump(mode="json")
        assert dumped["kind"] == "widen"

    def test_rejects_null_search_space(self) -> None:
        raw = _make_widen()
        raw["search_space"] = None
        with pytest.raises(ValidationError):
            FollowupItemAdapter.validate_python(raw)


class TestTextFollowup:
    def test_round_trip(self) -> None:
        raw = _make_text()
        parsed = FollowupItemAdapter.validate_python(raw)
        assert isinstance(parsed, TextFollowup)
        dumped = parsed.model_dump(mode="json")
        assert dumped["kind"] == "text"
        assert dumped["search_space"] is None

    def test_rejects_non_null_search_space(self) -> None:
        raw = _make_text()
        raw["search_space"] = VALID_SEARCH_SPACE_DICT
        with pytest.raises(ValidationError):
            FollowupItemAdapter.validate_python(raw)

    def test_rejects_extra_field(self) -> None:
        raw = _make_text()
        raw["extra_field"] = "nope"
        with pytest.raises(ValidationError):
            FollowupItemAdapter.validate_python(raw)


class TestSwapTemplateFollowup:
    def test_round_trip(self) -> None:
        raw = _make_swap_template()
        parsed = FollowupItemAdapter.validate_python(raw)
        assert isinstance(parsed, SwapTemplateFollowup)
        dumped = parsed.model_dump(mode="json")
        assert dumped["kind"] == "swap_template"
        assert dumped["template_id"] == VALID_TEMPLATE_ID
        assert isinstance(dumped["search_space"], dict)
        re_parsed = FollowupItemAdapter.validate_python(dumped)
        assert isinstance(re_parsed, SwapTemplateFollowup)

    def test_rejects_short_template_id(self) -> None:
        raw = _make_swap_template()
        raw["template_id"] = "too-short"
        with pytest.raises(ValidationError):
            FollowupItemAdapter.validate_python(raw)

    def test_rejects_long_template_id(self) -> None:
        raw = _make_swap_template()
        raw["template_id"] = "0" * 50
        with pytest.raises(ValidationError):
            FollowupItemAdapter.validate_python(raw)

    def test_rejects_null_search_space(self) -> None:
        raw = _make_swap_template()
        raw["search_space"] = None
        with pytest.raises(ValidationError):
            FollowupItemAdapter.validate_python(raw)

    def test_rejects_extra_field(self) -> None:
        raw = _make_swap_template()
        raw["extra_field"] = "nope"
        with pytest.raises(ValidationError):
            FollowupItemAdapter.validate_python(raw)


class TestFollowupKindValues:
    def test_tuple_length_and_tail(self) -> None:
        # Source-of-truth tuple is locked at 4 entries; swap_template appended
        # at the tail per feat_digest_executable_followups_swap_template AC-14.
        assert len(FOLLOWUP_KIND_VALUES) == 4
        assert FOLLOWUP_KIND_VALUES[-1] == "swap_template"
        assert FOLLOWUP_KIND_VALUES == ("narrow", "widen", "text", "swap_template")


class TestDiscriminator:
    def test_rejects_unknown_kind(self) -> None:
        with pytest.raises(ValidationError):
            FollowupItemAdapter.validate_python(
                {"kind": "bogus", "rationale": "x", "search_space": None}
            )

    def test_rejects_missing_kind(self) -> None:
        with pytest.raises(ValidationError):
            FollowupItemAdapter.validate_python({"rationale": "x", "search_space": None})


class TestListAdapter:
    def test_empty_list(self) -> None:
        assert FollowupListAdapter.validate_python([]) == []

    def test_mixed_kinds(self) -> None:
        parsed = FollowupListAdapter.validate_python([_make_narrow(), _make_widen(), _make_text()])
        assert len(parsed) == 3
        assert isinstance(parsed[0], NarrowFollowup)
        assert isinstance(parsed[1], WidenFollowup)
        assert isinstance(parsed[2], TextFollowup)


class TestSerializeFollowupList:
    def test_round_trip_via_serialize(self) -> None:
        # Mixed-kind list — annotate explicitly so mypy widens to the
        # discriminated-union element type rather than the join (BaseModel).
        items: list[NarrowFollowup | WidenFollowup | TextFollowup | SwapTemplateFollowup] = [
            NarrowFollowup(
                kind="narrow",
                rationale="narrow",
                search_space=SearchSpace.model_validate(VALID_SEARCH_SPACE_DICT),
            ),
            TextFollowup(kind="text", rationale="text", search_space=None),
        ]
        serialized = serialize_followup_list(items)
        assert serialized[0]["kind"] == "narrow"
        assert serialized[0]["search_space"]["params"]["title_boost"]["type"] == "float"
        assert serialized[1]["kind"] == "text"
        assert serialized[1]["search_space"] is None
        # Should re-parse cleanly.
        re_parsed = FollowupListAdapter.validate_python(serialized)
        assert len(re_parsed) == 2

    def test_empty_list(self) -> None:
        assert serialize_followup_list([]) == []
