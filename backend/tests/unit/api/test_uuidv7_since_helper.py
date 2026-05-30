# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the UUIDv7 lower-bound helper (feat_query_inline_crud Story 1.1).

``_uuidv7_lower_bound_from_iso(datetime)`` returns a UUIDv7-shaped string
whose first 48 bits encode the input timestamp in milliseconds. Lexical
comparison of two such strings is identical to numeric comparison of
their underlying 128-bit values, which is what makes the ``?since``
filter on the queries listing endpoint correct.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from backend.app.api.v1.query_sets import _UUID_HEX_RE, _uuidv7_lower_bound_from_iso


def test_returned_value_is_valid_uuidv7_shape() -> None:
    result = _uuidv7_lower_bound_from_iso(datetime(2026, 5, 13, 12, 34, 56, tzinfo=UTC))
    assert _UUID_HEX_RE.match(result), f"not a UUIDv7-shaped string: {result}"


def test_version_nibble_is_7() -> None:
    """RFC 9562 — third group's first hex digit must be `7` for UUIDv7."""
    result = _uuidv7_lower_bound_from_iso(datetime(2026, 5, 13, tzinfo=UTC))
    # Format: XXXXXXXX-XXXX-7XXX-...
    parts = result.split("-")
    assert parts[2][0] == "7", f"version nibble should be 7, got {parts[2][0]!r}"


def test_variant_nibble_is_8() -> None:
    """RFC 9562 — fourth group's first hex digit must be `8`, `9`, `a`, or `b`."""
    result = _uuidv7_lower_bound_from_iso(datetime(2026, 5, 13, tzinfo=UTC))
    parts = result.split("-")
    assert parts[3][0] in "89ab", f"variant nibble should be 8/9/a/b, got {parts[3][0]!r}"


def test_zero_randomness() -> None:
    """Lower-bound: all rand_a + rand_b bits are zero."""
    result = _uuidv7_lower_bound_from_iso(datetime(2026, 5, 13, tzinfo=UTC))
    parts = result.split("-")
    # parts[2] is `7XXX` where XXX is rand_a (must be zero)
    assert parts[2][1:] == "000", f"rand_a must be zero, got {parts[2][1:]!r}"
    # parts[3] is `8XXX` where XXX is clock_seq high (must be zero)
    assert parts[3][1:] == "000", f"clock-seq must be zero, got {parts[3][1:]!r}"
    # parts[4] is the 62-bit rand_b (must be zero)
    assert parts[4] == "000000000000", f"rand_b must be zero, got {parts[4]!r}"


def test_timestamp_encoded_in_first_48_bits() -> None:
    """The first 48 bits of the UUIDv7 should match `int(ts.timestamp() * 1000)`."""
    ts = datetime(2026, 5, 13, 12, 34, 56, 789000, tzinfo=UTC)
    expected_ms = int(ts.timestamp() * 1000)
    result = _uuidv7_lower_bound_from_iso(ts)

    # Reconstruct the 48-bit ts from the first two groups.
    parts = result.split("-")
    high = int(parts[0], 16)
    mid = int(parts[1], 16)
    reconstructed_ms = (high << 16) | mid
    assert reconstructed_ms == expected_ms


def test_monotonic_property() -> None:
    """Later timestamps must produce lexically-larger UUIDv7 lower bounds."""
    t1 = datetime(2026, 5, 13, 12, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 5, 13, 12, 0, 0, 1000, tzinfo=UTC)  # +1 ms
    t3 = datetime(2026, 5, 13, 12, 0, 1, tzinfo=UTC)  # +1 second

    assert _uuidv7_lower_bound_from_iso(t1) < _uuidv7_lower_bound_from_iso(t2)
    assert _uuidv7_lower_bound_from_iso(t2) < _uuidv7_lower_bound_from_iso(t3)


def test_unix_epoch_yields_all_zero_timestamp() -> None:
    result = _uuidv7_lower_bound_from_iso(datetime(1970, 1, 1, tzinfo=UTC))
    parts = result.split("-")
    # ts_ms = 0 → first 48 bits are all zero
    assert parts[0] == "00000000"
    assert parts[1] == "0000"


@pytest.mark.parametrize(
    "ts",
    [
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2026, 5, 13, 12, 34, 56, tzinfo=UTC),
        datetime(2030, 12, 31, 23, 59, 59, tzinfo=UTC),
    ],
)
def test_format_matches_canonical_uuid_regex_for_various_timestamps(ts: datetime) -> None:
    result = _uuidv7_lower_bound_from_iso(ts)
    canonical = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-8[0-9a-f]{3}-[0-9a-f]{12}$")
    assert canonical.match(result)


def test_naive_datetime_treated_as_utc() -> None:
    """Gemini PR #101 G1: naive datetime must be treated as UTC, not local time.

    Without the explicit ``replace(tzinfo=UTC)``, ``datetime.timestamp()`` on a
    naive value uses the system's local tz, which would produce different
    lower-bound IDs across deployments. Compare a naive UTC datetime to the
    explicit UTC-aware equivalent — they must produce the same UUIDv7 bound.
    """
    naive = datetime(2026, 5, 13, 12, 34, 56)
    aware = datetime(2026, 5, 13, 12, 34, 56, tzinfo=UTC)
    assert _uuidv7_lower_bound_from_iso(naive) == _uuidv7_lower_bound_from_iso(aware)
