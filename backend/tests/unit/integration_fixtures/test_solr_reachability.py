# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the Solr reachability probe (infra_solr_ci_readiness Story 1.1).

Exercises ``_solr_base_url``'s shape-checking with a mocked ``httpx.Client`` so
the test is hermetic (no real Solr required). Covers:

- 200 + valid Solr system-info body -> returns the base URL
- 200 + non-Solr body (no ``lucene`` block / non-zero status) -> ``""``
- non-200 -> ``""``
- transport error (ConnectError) -> ``""``
- fallback from localhost:8983 to solr:8983
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from backend.tests.integration.fixtures import solr_reachability


class _FakeResponse:
    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        return self._body


class _FakeClient:
    """Stand-in for ``httpx.Client`` driven by a per-URL response map.

    A mapping value may be a ``_FakeResponse`` (returned) or an ``Exception``
    instance (raised), letting a single test model "localhost errors, solr
    succeeds".
    """

    def __init__(self, responses: dict[str, Any]) -> None:
        self._responses = responses

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get(self, url: str) -> _FakeResponse:
        for prefix, result in self._responses.items():
            if url.startswith(prefix):
                if isinstance(result, Exception):
                    raise result
                return result
        raise AssertionError(f"unexpected probe URL: {url}")


_VALID_SOLR_BODY = {"responseHeader": {"status": 0}, "lucene": {"solr-spec-version": "10.0.0"}}


def _patch_client(monkeypatch: pytest.MonkeyPatch, responses: dict[str, Any]) -> None:
    # The fixture does `import httpx`, so `solr_reachability.httpx is httpx` —
    # patching the shared module's `Client` reroutes the fixture's probe.
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: _FakeClient(responses))


def test_valid_solr_on_localhost_returns_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(
        monkeypatch,
        {"http://localhost:8983": _FakeResponse(200, _VALID_SOLR_BODY)},
    )
    assert solr_reachability._solr_base_url() == "http://localhost:8983"


def test_non_solr_body_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    # 200 but the body is some other service (no `lucene`, no zero status).
    _patch_client(
        monkeypatch,
        {
            "http://localhost:8983": _FakeResponse(200, {"hello": "world"}),
            "http://solr:8983": _FakeResponse(200, {"hello": "world"}),
        },
    )
    assert solr_reachability._solr_base_url() == ""


def test_non_zero_response_header_status_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(
        monkeypatch,
        {
            "http://localhost:8983": _FakeResponse(
                200, {"responseHeader": {"status": 1}, "lucene": {}}
            ),
            "http://solr:8983": _FakeResponse(200, {"responseHeader": {"status": 1}, "lucene": {}}),
        },
    )
    assert solr_reachability._solr_base_url() == ""


def test_non_200_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(
        monkeypatch,
        {
            "http://localhost:8983": _FakeResponse(404, {}),
            "http://solr:8983": _FakeResponse(503, {}),
        },
    )
    assert solr_reachability._solr_base_url() == ""


def test_connect_error_is_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(
        monkeypatch,
        {
            "http://localhost:8983": httpx.ConnectError("nope"),
            "http://solr:8983": httpx.ConnectError("nope"),
        },
    )
    assert solr_reachability._solr_base_url() == ""


def test_falls_back_to_compose_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    # localhost errors, solr:8983 succeeds — the in-container path.
    _patch_client(
        monkeypatch,
        {
            "http://localhost:8983": httpx.ConnectError("host-only down"),
            "http://solr:8983": _FakeResponse(200, _VALID_SOLR_BODY),
        },
    )
    assert solr_reachability._solr_base_url() == "http://solr:8983"
