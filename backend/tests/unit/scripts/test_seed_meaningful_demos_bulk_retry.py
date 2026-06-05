# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Lock the bulk-index retry behavior in ``scripts.seed_meaningful_demos``.

Covers bug_seed_meaningful_demos_silent_bulk_errors — the ESCI rich-scenario
bulk loop read and DISCARDED the ``/_bulk`` response, so an
``unavailable_shards_exception`` on a cold ES (or any mapping bug) silently
produced a partial/empty index while ``make seed-demo`` looked successful. ES
bulk semantics put the error in the response body with HTTP 200.

This is the urllib-flavored sibling of ``test_seed_es_retry.py`` (which covers
the httpx-based ``backend.app.scripts.seed_es``). ``_bulk_index_with_retry``
takes injectable ``send`` / ``sleep`` so the retry logic runs with no real ES:

* The retryable error type clears on attempt N → returns (success), no raise.
* The retryable error type persists through every attempt → raises loud.
* A non-retryable error type raises immediately on attempt 1 — no sleep, no
  retry — so mapping bugs / schema mismatches stay loud.
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts.seed_meaningful_demos import (
    _BULK_RETRY_ATTEMPTS,
    _bulk_index_with_retry,
    _first_bulk_error,
)

# Compact ES bulk response builders -------------------------------------------


def _ok() -> dict[str, Any]:
    return {"errors": False, "items": [{"index": {"status": 201}}]}


def _unavailable_shards() -> dict[str, Any]:
    return {
        "errors": True,
        "items": [
            {
                "index": {
                    "_index": "products",
                    "_id": "1",
                    "status": 503,
                    "error": {
                        "type": "unavailable_shards_exception",
                        "reason": "[products][0] primary shard is not active Timeout: [1m]",
                    },
                }
            }
        ],
    }


def _mapper_parsing_error() -> dict[str, Any]:
    return {
        "errors": True,
        "items": [
            {
                "index": {
                    "_index": "products",
                    "_id": "1",
                    "status": 400,
                    "error": {
                        "type": "mapper_parsing_exception",
                        "reason": "failed to parse field [title] of type [text]",
                    },
                }
            }
        ],
    }


class _FakeSender:
    """Records each body sent and returns the next queued bulk response."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.calls: list[bytes] = []

    def __call__(self, body: bytes) -> dict[str, Any]:
        self.calls.append(body)
        return self._responses.pop(0)


class _RecordingSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, secs: float) -> None:
        self.calls.append(secs)


_BODY = b'{"index":{}}\n{"title":"x"}\n'


def test_succeeds_after_one_transient_failure() -> None:
    """The exact failure mode: shard not ready on attempt 1, ready on attempt 2."""
    send = _FakeSender([_unavailable_shards(), _ok()])
    sleep = _RecordingSleep()
    _bulk_index_with_retry(_BODY, send=send, sleep=sleep)  # no raise
    assert len(send.calls) == 2
    assert len(sleep.calls) == 1  # one retry backoff


def test_succeeds_at_retry_boundary() -> None:
    """Succeed on the last allowed attempt."""
    send = _FakeSender([_unavailable_shards()] * (_BULK_RETRY_ATTEMPTS - 1) + [_ok()])
    sleep = _RecordingSleep()
    _bulk_index_with_retry(_BODY, send=send, sleep=sleep)
    assert len(send.calls) == _BULK_RETRY_ATTEMPTS


def test_raises_after_exhausting_retries() -> None:
    """If the shard never becomes available, fail loudly — never a silent partial index."""
    send = _FakeSender([_unavailable_shards()] * _BULK_RETRY_ATTEMPTS)
    sleep = _RecordingSleep()
    with pytest.raises(RuntimeError, match="unavailable_shards_exception"):
        _bulk_index_with_retry(_BODY, send=send, sleep=sleep)
    assert len(send.calls) == _BULK_RETRY_ATTEMPTS
    assert len(sleep.calls) == _BULK_RETRY_ATTEMPTS - 1  # no sleep after the final attempt


def test_non_retryable_error_fails_immediately() -> None:
    """Mapping bugs must NOT be masked by retry — deterministic + load-bearing."""
    send = _FakeSender([_mapper_parsing_error()])
    sleep = _RecordingSleep()
    with pytest.raises(RuntimeError, match="mapper_parsing_exception"):
        _bulk_index_with_retry(_BODY, send=send, sleep=sleep)
    assert len(send.calls) == 1  # no retry
    assert sleep.calls == []  # no backoff


def test_clean_success_indexes_once() -> None:
    """A healthy bulk response returns immediately with no retry/sleep."""
    send = _FakeSender([_ok()])
    sleep = _RecordingSleep()
    _bulk_index_with_retry(_BODY, send=send, sleep=sleep)
    assert len(send.calls) == 1
    assert sleep.calls == []


def test_first_bulk_error_extracts_or_none() -> None:
    """_first_bulk_error returns None on a clean response, the error dict otherwise."""
    assert _first_bulk_error(_ok()) is None
    err = _first_bulk_error(_unavailable_shards())
    assert err is not None
    assert err["type"] == "unavailable_shards_exception"
