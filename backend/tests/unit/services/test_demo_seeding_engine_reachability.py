# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the engine-reachability probe + snapshot (Story 1.2 / FR-2).

Hermetic — ``is_engine_reachable`` is driven by a fake ``httpx.AsyncClient`` and
``snapshot_engine_reachability`` monkeypatches the probe + URL resolver. No real
engine required. Covers AC-9 (probe is total — never raises).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from backend.app.services import demo_seeding
from backend.app.services.demo_seeding import (
    _RICH_SCENARIO_SLUG,
    is_engine_reachable,
    snapshot_engine_reachability,
)


class _FakeResponse:
    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        return self._body


class _FakeAsyncClient:
    """Async stand-in for ``httpx.AsyncClient``; one response or one raise."""

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


_SOLR_OK = {"responseHeader": {"status": 0}, "lucene": {"solr-spec-version": "10.0.0"}}
_ES_OK = {"version": {"number": "9.4.1"}}


@pytest.mark.asyncio
async def test_solr_valid_body_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_async_client(monkeypatch, _FakeResponse(200, _SOLR_OK))
    assert await is_engine_reachable("http://solr:8983", "solr") is True


@pytest.mark.asyncio
async def test_solr_invalid_body_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_async_client(monkeypatch, _FakeResponse(200, {"not": "solr"}))
    assert await is_engine_reachable("http://solr:8983", "solr") is False


@pytest.mark.asyncio
async def test_es_valid_body_reachable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_async_client(monkeypatch, _FakeResponse(200, _ES_OK))
    assert await is_engine_reachable("http://elasticsearch:9200", "elasticsearch") is True


@pytest.mark.asyncio
async def test_os_missing_version_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_async_client(monkeypatch, _FakeResponse(200, {"tagline": "you know, for search"}))
    assert await is_engine_reachable("http://opensearch:9200", "opensearch") is False


@pytest.mark.asyncio
async def test_non_200_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_async_client(monkeypatch, _FakeResponse(503, {}))
    assert await is_engine_reachable("http://solr:8983", "solr") is False


@pytest.mark.asyncio
async def test_connect_error_is_total(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_async_client(monkeypatch, httpx.ConnectError("refused"))
    assert await is_engine_reachable("http://solr:8983", "solr") is False


@pytest.mark.asyncio
async def test_timeout_is_total(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_async_client(monkeypatch, httpx.TimeoutException("slow"))
    assert await is_engine_reachable("http://elasticsearch:9200", "elasticsearch") is False


@pytest.mark.asyncio
async def test_unexpected_exception_is_total_and_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # AC-9: an unexpected exception (e.g. socket.gaierror) is swallowed +
    # logged at WARN; the probe returns False and never propagates.
    _patch_async_client(monkeypatch, RuntimeError("dns gremlin"))
    with caplog.at_level("WARNING"):
        assert await is_engine_reachable("http://solr:8983", "solr") is False
    assert any("demo_reseed_engine_probe_failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_snapshot_is_slug_keyed_and_includes_rich(monkeypatch: pytest.MonkeyPatch) -> None:
    # Make every engine reachable except solr; assert the snapshot is keyed by
    # scenario slug, has one entry per scenario PLUS the rich ESCI scenario.
    async def fake_reachable(_url: str, engine_type: str, **_kw: Any) -> bool:
        return engine_type != "solr"

    monkeypatch.setattr(demo_seeding, "is_engine_reachable", fake_reachable)
    monkeypatch.setattr(demo_seeding, "_resolve_engine_base_url", lambda host: host)

    scenarios: list[dict[str, Any]] = [
        {"slug": "es-one", "engine_type": "elasticsearch", "host_base_url": "http://es"},
        {"slug": "os-one", "engine_type": "opensearch", "host_base_url": "http://os"},
        {"slug": "solr-one", "engine_type": "solr", "host_base_url": "http://solr"},
    ]
    snap = await snapshot_engine_reachability(scenarios)

    assert snap == {
        "es-one": True,
        "os-one": True,
        "solr-one": False,
        _RICH_SCENARIO_SLUG: True,  # rich is ES — injected by the helper
    }
