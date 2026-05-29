"""Lock the bulk-retry behavior in ``backend.app.scripts.seed_es``.

Covers the fix for ``bug_smoke_seed_es_unavailable_shards_race`` — the seed
step intermittently hit ``unavailable_shards_exception`` on cold GHA runners
when the primary shard hadn't finished INITIALIZING by the time the bulk
POST landed. ES bulk semantics put the error in the response body with HTTP
200, so the previous code (one-shot ``if payload.get("errors"): return 1``)
turned a 60–90s transient into a CI failure.

This file exercises ``_bulk_with_retry`` directly with mocked httpx — no
real ES required. Three flavors of coverage:

* The retryable error type clears on attempt N → return True (success).
* The retryable error type persists through all attempts → return False.
* A non-retryable error type fails immediately on attempt 1 — no sleep,
  no retry — so mapping bugs / schema mismatches stay loud.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest

from backend.app.scripts.seed_es import (
    BULK_RETRY_ATTEMPTS,
    BULK_RETRY_SLEEP_SECS,
    _bulk_with_retry,
    _first_bulk_error,
)


class _FakeBulkResponse:
    """Mimics the subset of httpx.Response that _bulk_with_retry uses."""

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:  # ES bulk always returns 200
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _FakeClient:
    """Records each /_bulk POST and returns the next queued response."""

    def __init__(self, responses: list[dict[str, object]]) -> None:
        self._responses = list(responses)
        self.calls: list[bytes] = []

    async def post(
        self,
        url: str,
        *,
        content: bytes,
        headers: dict[str, str],  # noqa: ARG002 — required for shape parity
    ) -> _FakeBulkResponse:
        assert url == "/_bulk"
        self.calls.append(content)
        return _FakeBulkResponse(self._responses.pop(0))


# Compact ES bulk response builders -------------------------------------------------


def _ok() -> dict[str, object]:
    return {"errors": False, "items": [{"index": {"status": 201}}]}


def _unavailable_shards() -> dict[str, object]:
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
                        "reason": ("[products][0] primary shard is not active Timeout: [1m]"),
                    },
                }
            }
        ],
    }


def _mapper_parsing_error() -> dict[str, object]:
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
                        "reason": ("failed to parse field [title] of type [text]"),
                    },
                }
            }
        ],
    }


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Don't actually sleep BULK_RETRY_SLEEP_SECS × N in unit tests."""

    async def _instant(_secs: float) -> None:
        return None

    monkeypatch.setattr("backend.app.scripts.seed_es.asyncio.sleep", _instant)
    yield


class TestBulkRetry:
    async def test_succeeds_after_one_transient_failure(self) -> None:
        """The exact CI failure mode: shard not ready on attempt 1, ready on attempt 2."""
        client = _FakeClient([_unavailable_shards(), _ok()])
        body = json.dumps({}).encode()
        assert await _bulk_with_retry(client, body) is True  # type: ignore[arg-type]
        assert len(client.calls) == 2

    async def test_succeeds_after_two_transient_failures(self) -> None:
        """Two retries, then success — exercises the retry path without exhausting the budget."""
        client = _FakeClient([_unavailable_shards(), _unavailable_shards(), _ok()])
        body = json.dumps({}).encode()
        assert await _bulk_with_retry(client, body) is True  # type: ignore[arg-type]
        assert len(client.calls) == 3  # 2 failures + 1 success

    async def test_succeeds_at_retry_boundary(self) -> None:
        """Succeed on the last allowed attempt — exhausts BULK_RETRY_ATTEMPTS - 1 failures first."""
        responses = [_unavailable_shards()] * (BULK_RETRY_ATTEMPTS - 1) + [_ok()]
        client = _FakeClient(responses)
        body = json.dumps({}).encode()
        assert await _bulk_with_retry(client, body) is True  # type: ignore[arg-type]
        assert len(client.calls) == BULK_RETRY_ATTEMPTS

    async def test_returns_false_after_exhausting_retries(self) -> None:
        """If the shard never becomes available, fail loudly so the operator sees CI red."""
        # Cap responses at BULK_RETRY_ATTEMPTS — _FakeClient.pop(0) would
        # IndexError otherwise if the helper made an extra call.
        client = _FakeClient([_unavailable_shards()] * BULK_RETRY_ATTEMPTS)
        body = json.dumps({}).encode()
        assert await _bulk_with_retry(client, body) is False  # type: ignore[arg-type]
        assert len(client.calls) == BULK_RETRY_ATTEMPTS

    async def test_non_retryable_error_fails_immediately(self) -> None:
        """Mapping bugs must NOT be masked by retry — they're deterministic and load-bearing."""
        client = _FakeClient([_mapper_parsing_error()])
        body = json.dumps({}).encode()
        assert await _bulk_with_retry(client, body) is False  # type: ignore[arg-type]
        assert len(client.calls) == 1  # exactly one attempt, no retry

    async def test_happy_path_no_retries(self) -> None:
        """Cold-start fast path: bulk succeeds first try, no warning log noise."""
        client = _FakeClient([_ok()])
        body = json.dumps({}).encode()
        assert await _bulk_with_retry(client, body) is True  # type: ignore[arg-type]
        assert len(client.calls) == 1


class TestFirstBulkError:
    """``_first_bulk_error`` is the helper that surfaces the retry decision."""

    def test_returns_first_error_when_present(self) -> None:
        payload = _unavailable_shards()
        err = _first_bulk_error(payload)
        assert err is not None
        assert err["type"] == "unavailable_shards_exception"

    def test_returns_none_on_success_payload(self) -> None:
        assert _first_bulk_error(_ok()) is None

    def test_returns_none_on_empty_items(self) -> None:
        assert _first_bulk_error({"errors": True, "items": []}) is None

    def test_skips_items_without_error_key(self) -> None:
        payload = {
            "errors": True,
            "items": [
                {"index": {"_index": "x", "_id": "1", "status": 201}},
                {
                    "index": {
                        "_index": "x",
                        "_id": "2",
                        "status": 503,
                        "error": {"type": "unavailable_shards_exception"},
                    }
                },
            ],
        }
        err = _first_bulk_error(payload)
        assert err is not None
        assert err["type"] == "unavailable_shards_exception"


class TestConstants:
    """Pin the design-locked constants so a future edit can't silently flip them."""

    def test_retry_attempts_is_three(self) -> None:
        # The heavy lifting is done by _cluster/health?wait_for_status=yellow
        # right after the index create (synchronizes with ES's allocation
        # state machine). The retry loop is the safety net for residual
        # transients after the health probe returns, so 3 is enough.
        assert BULK_RETRY_ATTEMPTS == 3

    def test_retry_sleep_is_two_seconds(self) -> None:
        # The sleep between attempts is intentionally small — the long wait
        # happens INSIDE each bulk attempt (ES's 60s internal timeout), so
        # additional sleep would only add to total wall time.
        assert BULK_RETRY_SLEEP_SECS == 2.0
