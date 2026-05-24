"""Unit tests for ``parse_followup_list`` decision table (Story 1.1).

Covers every row in FR-4's decision table for the defensive ingest helper.
Never raises — invalid items either downgrade to ``text`` or are dropped,
both with structlog WARN events.
"""

from __future__ import annotations

import logging

import pytest

from backend.app.domain.study.followups import (
    NarrowFollowup,
    TextFollowup,
    parse_followup_list,
)

# Logger name used by ``backend.app.domain.study.followups`` — must match
# what ``structlog.get_logger(__name__)`` produces inside the module so
# ``caplog.set_level(..., logger=_FOLLOWUPS_LOGGER)`` scopes correctly.
_FOLLOWUPS_LOGGER = "backend.app.domain.study.followups"


@pytest.fixture
def followups_caplog(caplog: pytest.LogCaptureFixture) -> pytest.LogCaptureFixture:
    """Scope ``caplog`` to the followups logger so structlog WARN events are captured."""
    caplog.set_level(logging.WARNING, logger=_FOLLOWUPS_LOGGER)
    return caplog


def _event_types(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Extract structlog ``event_type`` field from captured records."""
    types: list[str] = []
    for record in caplog.records:
        # structlog routes through stdlib logging; the event_type is
        # attached as an attribute on the LogRecord.
        et = getattr(record, "event_type", None)
        if et is not None:
            types.append(str(et))
    return types


VALID_SEARCH_SPACE_DICT = {
    "params": {
        "title_boost": {"type": "float", "low": 0.5, "high": 2.0},
    }
}


# A search space that violates the 10^6 cardinality cap (100^12 > 10^6),
# per the empirically-mapped case cited in AC-4.
CARDINALITY_BUSTING_SEARCH_SPACE = {
    "params": {f"f{i}": {"type": "float", "low": 0.0, "high": 1.0} for i in range(12)}
}


class TestTopLevelMalformed:
    def test_none_returns_empty_no_warn(self, followups_caplog: pytest.LogCaptureFixture) -> None:
        result = parse_followup_list(None)
        assert result == []
        # None is the "fresh empty" path — no WARN.
        assert "digest_followups_top_level_malformed" not in _event_types(followups_caplog)

    def test_dict_returns_empty_with_warn(self, followups_caplog: pytest.LogCaptureFixture) -> None:
        result = parse_followup_list({"unexpected": "shape"})
        assert result == []
        assert "digest_followups_top_level_malformed" in _event_types(followups_caplog)

    def test_scalar_returns_empty_with_warn(
        self, followups_caplog: pytest.LogCaptureFixture
    ) -> None:
        result = parse_followup_list(42)
        assert result == []
        assert "digest_followups_top_level_malformed" in _event_types(followups_caplog)


class TestLegacyListOfStrings:
    def test_strings_wrapped_as_text_items(self) -> None:
        result = parse_followup_list(["try wider boost", "investigate stopwords"])
        assert len(result) == 2
        assert all(isinstance(r, TextFollowup) for r in result)
        assert result[0].rationale == "try wider boost"
        assert result[1].rationale == "investigate stopwords"

    def test_empty_string_wrapped_as_text(self) -> None:
        # Empty strings are still legal text items per the legacy contract —
        # the worker never emitted these but we shouldn't silently drop them.
        result = parse_followup_list([""])
        assert len(result) == 1
        assert isinstance(result[0], TextFollowup)
        assert result[0].rationale == ""


class TestValidStructuredItems:
    def test_valid_narrow_passes_through(self) -> None:
        result = parse_followup_list(
            [
                {
                    "kind": "narrow",
                    "rationale": "narrow around the winner",
                    "search_space": VALID_SEARCH_SPACE_DICT,
                }
            ]
        )
        assert len(result) == 1
        assert isinstance(result[0], NarrowFollowup)

    def test_valid_text_passes_through(self) -> None:
        result = parse_followup_list([{"kind": "text", "rationale": "try X", "search_space": None}])
        assert len(result) == 1
        assert isinstance(result[0], TextFollowup)

    def test_mixed_valid_items(self) -> None:
        result = parse_followup_list(
            [
                {
                    "kind": "narrow",
                    "rationale": "narrow",
                    "search_space": VALID_SEARCH_SPACE_DICT,
                },
                {"kind": "text", "rationale": "text", "search_space": None},
            ]
        )
        assert len(result) == 2
        assert isinstance(result[0], NarrowFollowup)
        assert isinstance(result[1], TextFollowup)


class TestSearchSpaceCardinalityDowngrade:
    """The empirically-mapped 100^12 > 10^6 cardinality case (AC-4)."""

    def test_cardinality_busting_narrow_downgrades_to_text(
        self, followups_caplog: pytest.LogCaptureFixture
    ) -> None:
        result = parse_followup_list(
            [
                {
                    "kind": "narrow",
                    "rationale": "narrow with too many floats",
                    "search_space": CARDINALITY_BUSTING_SEARCH_SPACE,
                }
            ],
            study_id="study-1",
            proposal_id="proposal-1",
        )
        assert len(result) == 1
        assert isinstance(result[0], TextFollowup)
        assert result[0].rationale.startswith("[validation failed: "), (
            f"unexpected: {result[0].rationale!r}"
        )
        assert "search-space cardinality" in result[0].rationale
        assert "narrow with too many floats" in result[0].rationale
        assert "digest_followup_validation_downgraded" in _event_types(followups_caplog)


class TestValidationFailDowngradeWithRationale:
    def test_narrow_with_invalid_search_space_downgrades_to_text(
        self, followups_caplog: pytest.LogCaptureFixture
    ) -> None:
        # Invalid search_space (low > high on a float param).
        bad = {
            "params": {
                "x": {"type": "float", "low": 5.0, "high": 1.0},
            }
        }
        result = parse_followup_list(
            [
                {
                    "kind": "narrow",
                    "rationale": "the rationale survives",
                    "search_space": bad,
                }
            ],
        )
        assert len(result) == 1
        assert isinstance(result[0], TextFollowup)
        assert "the rationale survives" in result[0].rationale
        assert "digest_followup_validation_downgraded" in _event_types(followups_caplog)

    def test_unknown_kind_with_rationale_downgrades_to_text(
        self, followups_caplog: pytest.LogCaptureFixture
    ) -> None:
        result = parse_followup_list(
            [
                {
                    "kind": "experimental_kind",
                    "rationale": "salvageable text",
                    "search_space": None,
                }
            ],
        )
        assert len(result) == 1
        assert isinstance(result[0], TextFollowup)
        assert "salvageable text" in result[0].rationale


class TestDropPaths:
    def test_dict_with_no_rationale_dropped(
        self, followups_caplog: pytest.LogCaptureFixture
    ) -> None:
        result = parse_followup_list(
            [{"kind": "bogus", "search_space": None}],
        )
        assert result == []
        assert "digest_followup_dropped" in _event_types(followups_caplog)

    def test_dict_with_empty_rationale_dropped(
        self, followups_caplog: pytest.LogCaptureFixture
    ) -> None:
        result = parse_followup_list(
            [{"kind": "bogus", "rationale": "   ", "search_space": None}],
        )
        assert result == []
        assert "digest_followup_dropped" in _event_types(followups_caplog)

    def test_non_dict_array_element_dropped(
        self, followups_caplog: pytest.LogCaptureFixture
    ) -> None:
        result = parse_followup_list(
            [42, ["nested"], {"kind": "text", "rationale": "ok", "search_space": None}]
        )
        # Two items dropped, one passes.
        assert len(result) == 1
        assert isinstance(result[0], TextFollowup)
        types = _event_types(followups_caplog)
        assert types.count("digest_followup_dropped") == 2


class TestTextItemMalformedExtras:
    def test_text_with_extra_field_downgrade_or_drop(
        self, followups_caplog: pytest.LogCaptureFixture
    ) -> None:
        # extra fields are rejected by ``extra='forbid'``; rationale is
        # salvageable so it downgrades.
        result = parse_followup_list(
            [
                {
                    "kind": "text",
                    "rationale": "rationale",
                    "search_space": None,
                    "stray": "unwanted",
                }
            ]
        )
        assert len(result) == 1
        assert isinstance(result[0], TextFollowup)
        assert "rationale" in result[0].rationale


class TestMixedValidAndInvalid:
    def test_valid_passes_through_invalid_dropped(
        self, followups_caplog: pytest.LogCaptureFixture
    ) -> None:
        result = parse_followup_list(
            [
                {
                    "kind": "narrow",
                    "rationale": "valid narrow",
                    "search_space": VALID_SEARCH_SPACE_DICT,
                },
                {"kind": "bogus", "search_space": None},  # dropped
                "legacy string",
                {"kind": "text", "rationale": "valid text", "search_space": None},
            ]
        )
        assert len(result) == 3
        assert isinstance(result[0], NarrowFollowup)
        assert isinstance(result[1], TextFollowup)
        assert result[1].rationale == "legacy string"
        assert isinstance(result[2], TextFollowup)


class TestStudyAndProposalIdInLogs:
    def test_warn_includes_study_and_proposal_ids(
        self, followups_caplog: pytest.LogCaptureFixture
    ) -> None:
        parse_followup_list(
            [{"kind": "bogus", "search_space": None}],
            study_id="study-XYZ",
            proposal_id="proposal-ABC",
        )
        # structlog attaches the keyword args as LogRecord attributes.
        records = [r for r in followups_caplog.records if getattr(r, "event_type", None)]
        assert len(records) == 1
        assert getattr(records[0], "study_id", None) == "study-XYZ"
        assert getattr(records[0], "proposal_id", None) == "proposal-ABC"
