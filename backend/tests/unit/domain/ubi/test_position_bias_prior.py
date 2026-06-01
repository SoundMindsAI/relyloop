# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``backend.app.domain.ubi.position_bias_prior``
(feat_ubi_judgments Story 1.2 / FR-11).

Asserts the loader's fallback behavior matches FR-11: missing file →
uninformed default ``{}``; malformed JSON → WARN log + uninformed
default (NEVER raises); valid prior parsed correctly with both string
and integer JSON keys.

The "WARN on bad input, return uninformed" semantics are critical —
the spec promises that a bad prior file degrades rating accuracy
gracefully without crashing the worker. A regression that "improves"
this by raising would surface as terminal-failed UBI jobs for any
operator with a malformed prior file.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog
from structlog.testing import LogCapture

from backend.app.domain.ubi.position_bias_prior import load_position_bias_prior


@pytest.fixture
def capture_logs() -> Iterator[LogCapture]:
    cap = LogCapture()
    # Mutate the configured processors list IN PLACE (and restore it the same
    # way) rather than swapping it via structlog.configure(processors=[cap]) +
    # reset_defaults(). Replacing the list instance leaves any module-level
    # logger that was bound (cached) against the prior instance pointing at a
    # stale list, so a *later* test's structlog.testing.capture_logs() — which
    # mutates the current instance — captures nothing. That cross-test poison
    # is bug_backend_suite_nondeterministic_caplog_isolation; here we mirror
    # structlog.testing.capture_logs()'s own "keep the list instance intact"
    # discipline so this fixture can't be a polluter.
    configured = structlog.get_config()["processors"]
    # structlog 25.5.0 returns a mutable list here (verified), so the in-place
    # path is the live one. Guard with isinstance anyway — mirroring the same
    # guard in backend.app.core.logging.configure_logging — so a future
    # structlog that hands back an immutable tuple falls back to a clean
    # configure/restore instead of raising AttributeError on .clear().
    if isinstance(configured, list):
        saved = list(configured)
        configured.clear()
        configured.append(cap)
        structlog.configure(processors=configured)
        try:
            yield cap
        finally:
            configured.clear()
            configured.extend(saved)
            structlog.configure(processors=configured)
    else:
        structlog.configure(processors=[cap])
        try:
            yield cap
        finally:
            structlog.configure(processors=configured)


class TestLoaderTrivialFallbacks:
    def test_none_path_returns_empty_silently(self, capture_logs: LogCapture) -> None:
        assert load_position_bias_prior(None) == {}
        # No WARN log — None is the documented uninformed default.
        assert all(e["log_level"] != "warning" for e in capture_logs.entries)

    def test_missing_file_returns_empty_silently(
        self, tmp_path: Path, capture_logs: LogCapture
    ) -> None:
        nonexistent = tmp_path / "absent.json"
        assert not nonexistent.exists()
        assert load_position_bias_prior(nonexistent) == {}
        # No WARN log — the file simply doesn't exist; uninformed default.
        assert all(e["log_level"] != "warning" for e in capture_logs.entries)

    def test_empty_file_returns_empty_silently(
        self, tmp_path: Path, capture_logs: LogCapture
    ) -> None:
        empty = tmp_path / "empty.json"
        empty.write_text("")
        assert load_position_bias_prior(empty) == {}
        assert all(e["log_level"] != "warning" for e in capture_logs.entries)

    def test_whitespace_only_file_returns_empty_silently(
        self, tmp_path: Path, capture_logs: LogCapture
    ) -> None:
        ws = tmp_path / "whitespace.json"
        ws.write_text("   \n\n  ")
        assert load_position_bias_prior(ws) == {}
        assert all(e["log_level"] != "warning" for e in capture_logs.entries)


class TestLoaderMalformedFallbacks:
    def test_invalid_json_returns_empty_with_warn(
        self, tmp_path: Path, capture_logs: LogCapture
    ) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json {{")
        assert load_position_bias_prior(bad) == {}
        warns = [e for e in capture_logs.entries if e["log_level"] == "warning"]
        assert len(warns) == 1
        assert warns[0]["event_type"] == "ubi_position_bias_prior_malformed"
        assert warns[0]["cause"] == "invalid_json"

    def test_top_level_not_object_returns_empty_with_warn(
        self, tmp_path: Path, capture_logs: LogCapture
    ) -> None:
        arr = tmp_path / "array.json"
        arr.write_text("[1, 2, 3]")
        assert load_position_bias_prior(arr) == {}
        warns = [e for e in capture_logs.entries if e["log_level"] == "warning"]
        assert len(warns) == 1
        assert warns[0]["cause"] == "not_an_object"

    def test_positions_missing_returns_empty_with_warn(
        self, tmp_path: Path, capture_logs: LogCapture
    ) -> None:
        no_positions = tmp_path / "no_positions.json"
        no_positions.write_text(json.dumps({"unrelated_key": "value"}))
        assert load_position_bias_prior(no_positions) == {}
        warns = [e for e in capture_logs.entries if e["log_level"] == "warning"]
        assert len(warns) == 1
        assert warns[0]["cause"] == "positions_not_an_object"

    def test_positions_not_object_returns_empty_with_warn(
        self, tmp_path: Path, capture_logs: LogCapture
    ) -> None:
        bad = tmp_path / "positions_array.json"
        bad.write_text(json.dumps({"positions": [1.0, 0.5, 0.25]}))
        assert load_position_bias_prior(bad) == {}
        warns = [e for e in capture_logs.entries if e["log_level"] == "warning"]
        assert len(warns) == 1
        assert warns[0]["cause"] == "positions_not_an_object"

    def test_non_numeric_value_returns_empty_with_warn(
        self, tmp_path: Path, capture_logs: LogCapture
    ) -> None:
        bad = tmp_path / "non_numeric.json"
        bad.write_text(json.dumps({"positions": {"1": "heavy", "2": 0.5}}))
        assert load_position_bias_prior(bad) == {}
        warns = [e for e in capture_logs.entries if e["log_level"] == "warning"]
        assert len(warns) == 1
        assert warns[0]["cause"] == "non_numeric_entry"

    def test_rank_zero_returns_empty_with_warn(
        self, tmp_path: Path, capture_logs: LogCapture
    ) -> None:
        bad = tmp_path / "rank_zero.json"
        bad.write_text(json.dumps({"positions": {"0": 1.0, "1": 0.5}}))
        assert load_position_bias_prior(bad) == {}
        warns = [e for e in capture_logs.entries if e["log_level"] == "warning"]
        assert len(warns) == 1
        assert warns[0]["cause"] == "rank_below_one"

    def test_negative_weight_returns_empty_with_warn(
        self, tmp_path: Path, capture_logs: LogCapture
    ) -> None:
        bad = tmp_path / "negative_weight.json"
        bad.write_text(json.dumps({"positions": {"1": 1.0, "2": -0.5}}))
        assert load_position_bias_prior(bad) == {}
        warns = [e for e in capture_logs.entries if e["log_level"] == "warning"]
        assert len(warns) == 1
        assert warns[0]["cause"] == "negative_weight"


class TestLoaderValidInput:
    def test_string_keys_normalized_to_ints(self, tmp_path: Path) -> None:
        valid = tmp_path / "valid.json"
        valid.write_text(json.dumps({"positions": {"1": 1.0, "2": 0.65, "3": 0.45}}))
        out = load_position_bias_prior(valid)
        assert out == {1: 1.0, 2: 0.65, 3: 0.45}

    def test_integer_values_accepted(self, tmp_path: Path) -> None:
        # JSON spec allows numeric values without decimal; loader normalizes
        # both ints and floats to float.
        valid = tmp_path / "int_values.json"
        valid.write_text(json.dumps({"positions": {"1": 1, "2": 0.5}}))
        out = load_position_bias_prior(valid)
        assert out == {1: 1.0, 2: 0.5}
        assert isinstance(out[1], float)
        assert isinstance(out[2], float)

    def test_full_decay_table_round_trips(self, tmp_path: Path) -> None:
        # A realistic prior covering 10 positions.
        prior = {str(rank): 1.0 / rank for rank in range(1, 11)}  # 1/r decay
        valid = tmp_path / "decay.json"
        valid.write_text(json.dumps({"positions": prior}))
        out = load_position_bias_prior(valid)
        for rank in range(1, 11):
            assert out[rank] == pytest.approx(1.0 / rank, abs=1e-6)
        assert len(out) == 10

    def test_empty_positions_dict_returns_empty(self, tmp_path: Path) -> None:
        # Operator wrote `{"positions": {}}` — technically valid but conveys
        # no information. Loader returns {} (which the aggregator treats as
        # uninformed). No WARN — the file structure was valid; the operator
        # just supplied no entries.
        valid = tmp_path / "empty_positions.json"
        valid.write_text(json.dumps({"positions": {}}))
        out = load_position_bias_prior(valid)
        assert out == {}
