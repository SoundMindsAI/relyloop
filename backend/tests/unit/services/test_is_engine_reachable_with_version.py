# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for is_engine_reachable_with_version (FR-6 / AC-7 / AC-11).

Companion to test_demo_seeding_engine_reachability.py for the new sibling
probe added by feat_engine_version_selection. Tests are hermetic — driven
by a fake httpx.AsyncClient; no real engine required.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from backend.app.services.demo_seeding import is_engine_reachable_with_version


class _FakeResponse:
    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        return self._body


class _FakeAsyncClient:
    """Async stand-in for ``httpx.AsyncClient``; returns one response or raises."""

    def __init__(self, result: Any) -> None:
        self._result = result

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get(self, _url: str) -> _FakeResponse:
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def _patch_async_client(monkeypatch: pytest.MonkeyPatch, result: Any) -> None:
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _FakeAsyncClient(result))


# Engine-specific reachable-body fixtures, mirroring the canonical Solr +
# ES/OS response shapes used by test_demo_seeding_engine_reachability.
_SOLR_OK = {"responseHeader": {"status": 0}, "lucene": {"solr-spec-version": "10.0.0"}}
_ES_OK = {"version": {"number": "9.4.1"}}
_OS_OK = {"version": {"number": "3.6.0"}}


@pytest.mark.asyncio
async def test_es_happy_path_returns_version(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_async_client(monkeypatch, _FakeResponse(200, _ES_OK))
    ok, version = await is_engine_reachable_with_version(
        "http://elasticsearch:9200", "elasticsearch"
    )
    assert ok is True
    assert version == "9.4.1"


@pytest.mark.asyncio
async def test_os_happy_path_returns_version(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_async_client(monkeypatch, _FakeResponse(200, _OS_OK))
    ok, version = await is_engine_reachable_with_version("http://opensearch:9201", "opensearch")
    assert ok is True
    assert version == "3.6.0"


@pytest.mark.asyncio
async def test_solr_happy_path_returns_version(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_async_client(monkeypatch, _FakeResponse(200, _SOLR_OK))
    ok, version = await is_engine_reachable_with_version("http://solr:8983", "solr")
    assert ok is True
    assert version == "10.0.0"


@pytest.mark.asyncio
async def test_es_reachable_version_block_missing_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No `version` field at all → unreachable.

    Matches is_engine_reachable's strictness: a missing `version` key is
    the engine's reachability gate, not just an absent version annotation.
    """
    _patch_async_client(monkeypatch, _FakeResponse(200, {"tagline": "you know, for search"}))
    ok, version = await is_engine_reachable_with_version(
        "http://elasticsearch:9200", "elasticsearch"
    )
    assert ok is False
    assert version is None


@pytest.mark.asyncio
async def test_es_reachable_version_not_dict(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """`version` exists but isn't a dict → reachable, version None, WARN log."""
    _patch_async_client(monkeypatch, _FakeResponse(200, {"version": "9.4.1"}))
    with caplog.at_level("WARNING"):
        ok, version = await is_engine_reachable_with_version(
            "http://elasticsearch:9200", "elasticsearch"
        )
    assert ok is True
    assert version is None
    assert any("demo_reseed_engine_probe_failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_es_reachable_version_number_missing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """AC-7: reachable but version.number missing → (True, None) + WARN."""
    _patch_async_client(monkeypatch, _FakeResponse(200, {"version": {"build_flavor": "default"}}))
    with caplog.at_level("WARNING"):
        ok, version = await is_engine_reachable_with_version(
            "http://elasticsearch:9200", "elasticsearch"
        )
    assert ok is True
    assert version is None
    assert any("demo_reseed_engine_probe_failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_es_reachable_version_number_not_str(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """version.number numeric (not str) → (True, None) + WARN."""
    _patch_async_client(monkeypatch, _FakeResponse(200, {"version": {"number": 9.4}}))
    with caplog.at_level("WARNING"):
        ok, version = await is_engine_reachable_with_version(
            "http://elasticsearch:9200", "elasticsearch"
        )
    assert ok is True
    assert version is None
    assert any("demo_reseed_engine_probe_failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_solr_reachable_lucene_missing_version(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Solr lucene block present but no solr-spec-version → (True, None) + WARN."""
    body = {"responseHeader": {"status": 0}, "lucene": {"foo": "bar"}}
    _patch_async_client(monkeypatch, _FakeResponse(200, body))
    with caplog.at_level("WARNING"):
        ok, version = await is_engine_reachable_with_version("http://solr:8983", "solr")
    assert ok is True
    assert version is None
    assert any("demo_reseed_engine_probe_failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_http_500_is_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_async_client(monkeypatch, _FakeResponse(500, {}))
    ok, version = await is_engine_reachable_with_version(
        "http://elasticsearch:9200", "elasticsearch"
    )
    assert ok is False
    assert version is None


@pytest.mark.asyncio
async def test_body_not_dict_is_unreachable_without_spurious_warn(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A 200 with a non-dict JSON body (list/null/scalar) → (False, None).

    Gemini review #1: the isinstance(body, dict) guard returns a clean
    "unreachable" instead of letting a list/null body AttributeError into
    the broad except (which would log a misleading error_type:AttributeError
    WARN). No WARN should be emitted on this path — it's an honest
    unreachable, not a probe failure.
    """
    malformed_bodies: list[Any] = [[], None, "just a string", 42]
    for malformed in malformed_bodies:
        _patch_async_client(monkeypatch, _FakeResponse(200, malformed))
        with caplog.at_level("WARNING"):
            caplog.clear()
            ok, version = await is_engine_reachable_with_version(
                "http://elasticsearch:9200", "elasticsearch"
            )
        assert ok is False, f"malformed body {malformed!r} should be unreachable"
        assert version is None
        assert not any("demo_reseed_engine_probe_failed" in r.message for r in caplog.records), (
            f"non-dict body {malformed!r} should NOT emit a probe-failed WARN"
        )


@pytest.mark.asyncio
async def test_solr_response_header_not_dict_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Solr body where responseHeader is a non-dict → (False, None).

    Gemini review #1: guards `response_header.get("status")` against a
    responseHeader that's a list/scalar.
    """
    body = {"responseHeader": ["not", "a", "dict"], "lucene": {"solr-spec-version": "10.0.0"}}
    _patch_async_client(monkeypatch, _FakeResponse(200, body))
    ok, version = await is_engine_reachable_with_version("http://solr:8983", "solr")
    assert ok is False
    assert version is None


@pytest.mark.asyncio
async def test_timeout_is_total_returns_false_none(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _patch_async_client(monkeypatch, httpx.TimeoutException("slow"))
    with caplog.at_level("WARNING"):
        ok, version = await is_engine_reachable_with_version(
            "http://elasticsearch:9200", "elasticsearch"
        )
    assert ok is False
    assert version is None
    assert any("demo_reseed_engine_probe_failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_connect_error_is_total_returns_false_none(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    _patch_async_client(monkeypatch, httpx.ConnectError("refused"))
    with caplog.at_level("WARNING"):
        ok, version = await is_engine_reachable_with_version("http://solr:8983", "solr")
    assert ok is False
    assert version is None
    assert any("demo_reseed_engine_probe_failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_unexpected_exception_is_total(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Any unexpected exception is swallowed + logged at WARN.

    Matches is_engine_reachable's totality contract (its
    test_unexpected_exception_is_total_and_logged).
    """
    _patch_async_client(monkeypatch, RuntimeError("dns gremlin"))
    with caplog.at_level("WARNING"):
        ok, version = await is_engine_reachable_with_version("http://solr:8983", "solr")
    assert ok is False
    assert version is None
    # Verify the WARN log carries the probe-disambiguator extra so operator
    # grep can tell which probe failed.
    matching = [r for r in caplog.records if "demo_reseed_engine_probe_failed" in r.message]
    assert matching, "expected WARN log was not emitted"
