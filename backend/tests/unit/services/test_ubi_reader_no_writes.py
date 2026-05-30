# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``UbiReader`` write-safety invariant (feat_ubi_judgments §10 threat #2).

Boots a real :class:`ElasticAdapter` against a recording
:class:`httpx.MockTransport`, runs :meth:`UbiReader.read_features`
end-to-end against canned ``_mapping`` + ``_msearch`` responses, and
asserts that ZERO requests with write-shaped methods (``PUT``,
``DELETE``, ``POST`` against write-only paths) or write-shaped paths
(``_bulk``, ``_update``, ``_doc``, ``_create``) ever escape the
reader's call boundary.

This is a *defense-in-depth* test — the unit test
:func:`test_ubi_reader.test_read_features_no_writes_in_search_body`
already asserts the reader builds no write-shaped Query DSL bodies, but
this transport-mounted test catches any future change that might bypass
the reader's body construction (e.g., a refactor that switches to a raw
``_request`` call, or a misconfigured adapter that re-routes a search
through a write endpoint). Spec §13 + spec §10 threat #2 both lock the
guarantee that RelyLoop NEVER writes to a UBI-bearing cluster.

Lives under ``backend/tests/unit/services/`` (not
``backend/tests/integration/services/`` as the plan §3.2 stated) —
mirrors the sibling ``test_elastic_get_document.py`` pattern
(``httpx.MockTransport`` against a real ``ElasticAdapter``; no DB /
Redis / engine container needed). The codebase reserves
``backend/tests/integration/`` for tests that genuinely hit a service
container.
"""

from __future__ import annotations

import httpx
import pytest

from backend.app.adapters.elastic import ElasticAdapter
from backend.app.core.settings import get_settings
from backend.app.services.ubi_reader import UbiReader

# ----------------------------------------------------------------------------
# Recording transport — captures every (method, path) the reader emits so we
# can assert the safety invariant.
# ----------------------------------------------------------------------------


WRITE_METHODS = frozenset({"PUT", "DELETE", "PATCH"})
WRITE_PATH_SEGMENTS = ("_bulk", "_update", "_create", "_doc")


class _RecordingTransport(httpx.MockTransport):
    """Mock transport that records every (method, path) and returns canned UBI responses.

    Two canned responses keyed by URL path:

    * ``/ubi_queries/_mapping`` → minimal mapping body (probe succeeds).
    * ``/_msearch`` → an NDJSON ``_msearch`` body with one shard of
      canned hits for both the queries scan and the events scan. The
      reader issues two ``_msearch`` calls (one per index); the
      transport returns the same shape both times for simplicity (the
      events-scan body has ``application_name`` events for query_id
      ``ubi-q-1``).
    """

    def __init__(self) -> None:
        super().__init__(self._handler)
        self.calls: list[tuple[str, str]] = []

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        path = request.url.path
        if path.endswith("/_mapping"):
            return httpx.Response(
                200,
                json={
                    "ubi_queries": {
                        "mappings": {
                            "properties": {
                                "query_id": {"type": "keyword"},
                                "user_query": {"type": "text"},
                                "application": {"type": "keyword"},
                                "timestamp": {"type": "date"},
                            }
                        }
                    }
                },
            )
        if path.endswith("/_settings"):
            return httpx.Response(
                200,
                json={
                    "ubi_queries": {
                        "settings": {"index": {"analysis": {"analyzer": {"default": {}}}}}
                    }
                },
            )
        if path == "/_msearch":
            # Two msearch calls fire in sequence; differentiate by ordinal so
            # the queries scan returns query hits and the events scan returns
            # event hits.
            msearch_count = sum(1 for m, p in self.calls if p == "/_msearch")
            if msearch_count == 1:
                return httpx.Response(
                    200,
                    json={
                        "responses": [
                            {
                                "hits": {
                                    "hits": [
                                        {
                                            "_id": "ubi-q-1",
                                            "_score": 1.0,
                                            "_source": {
                                                "query_id": "ubi-q-1",
                                                "user_query": "red shoes",
                                                "application": "products",
                                                "timestamp": "2026-05-20T10:00:00Z",
                                            },
                                        }
                                    ]
                                }
                            }
                        ]
                    },
                )
            return httpx.Response(
                200,
                json={
                    "responses": [
                        {
                            "hits": {
                                "hits": [
                                    {
                                        "_id": "evt-1",
                                        "_score": 0.0,
                                        "_source": {
                                            "query_id": "ubi-q-1",
                                            "action_name": "click",
                                            "object_id": "doc-a",
                                            "timestamp": "2026-05-20T10:01:00Z",
                                        },
                                    },
                                    {
                                        "_id": "evt-2",
                                        "_score": 0.0,
                                        "_source": {
                                            "query_id": "ubi-q-1",
                                            "action_name": "impression",
                                            "object_id": "doc-a",
                                            "position": 1,
                                            "timestamp": "2026-05-20T10:00:30Z",
                                        },
                                    },
                                ]
                            }
                        }
                    ]
                },
            )
        raise AssertionError(f"unexpected request to {request.method} {path}")


# ----------------------------------------------------------------------------
# Settings stub — ElasticAdapter resolves credentials via Settings; provide a
# minimal env so the adapter constructs cleanly without touching real secrets.
# ----------------------------------------------------------------------------


@pytest.fixture
def _stub_credentials(tmp_path, monkeypatch):
    creds = tmp_path / "creds.yaml"
    creds.write_text("ubi-test:\n  username: u\n  password: p\n")
    monkeypatch.setenv("DATABASE_URL_FILE", str(tmp_path / "db_url"))
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(tmp_path / "pg_pw"))
    monkeypatch.setenv("CLUSTER_CREDENTIALS_FILE", str(creds))
    (tmp_path / "db_url").write_text("postgresql+asyncpg://u:p@h/d")
    (tmp_path / "pg_pw").write_text("p")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _build_adapter(transport: _RecordingTransport) -> ElasticAdapter:
    return ElasticAdapter(
        cluster_id="ubi-test",
        engine_type="opensearch",
        base_url="http://opensearch:9200",
        auth_kind="opensearch_basic",
        credentials_ref="ubi-test",
        engine_config=None,
        client=httpx.AsyncClient(transport=transport),
    )


# ----------------------------------------------------------------------------
# The invariant: zero write-shaped requests escape the reader's call boundary.
# ----------------------------------------------------------------------------


async def test_read_features_issues_no_write_shaped_requests(
    _stub_credentials,  # noqa: ARG001  — autouse-like fixture
) -> None:
    """Full read pipeline → no write-shaped HTTP methods or paths."""
    from datetime import UTC, datetime

    transport = _RecordingTransport()
    adapter = _build_adapter(transport)
    try:
        reader = UbiReader(adapter)
        out = await reader.read_features(
            target="products",
            since=datetime(2026, 5, 1, tzinfo=UTC),
            until=datetime(2026, 5, 29, tzinfo=UTC),
        )
    finally:
        await adapter.aclose()

    # Sanity — the pipeline actually ran end-to-end.
    assert ("ubi-q-1", "doc-a") in out
    feat = out[("ubi-q-1", "doc-a")]
    assert feat.click_count == 1
    assert feat.impression_count == 1

    # Invariant: every recorded call is READ-shaped.
    for method, path in transport.calls:
        assert method.upper() not in WRITE_METHODS, (
            f"reader issued forbidden write method {method} {path}"
        )
        for forbidden_segment in WRITE_PATH_SEGMENTS:
            # `_doc` / `_bulk` / `_update` / `_create` are write endpoints in
            # ES/OpenSearch. Anywhere in the path is forbidden.
            assert forbidden_segment not in path.split("/"), (
                f"reader hit write-shaped path segment {forbidden_segment!r} in {path}"
            )

    # Exact expected call profile — one mapping probe, one settings lookup
    # (the adapter's get_schema also pulls _settings for analyzer derivation),
    # two _msearch calls (queries scan + events scan).
    methods_and_paths = transport.calls
    assert ("GET", "/ubi_queries/_mapping") in methods_and_paths
    assert ("GET", "/ubi_queries/_settings") in methods_and_paths
    msearch_calls = [c for c in methods_and_paths if c[1] == "/_msearch"]
    assert len(msearch_calls) == 2, methods_and_paths
    assert all(m == "POST" for m, _ in msearch_calls)


async def test_read_features_zero_writes_when_window_empty(
    _stub_credentials,  # noqa: ARG001
) -> None:
    """Even when the reader bails on empty queries, no writes leak."""
    from datetime import UTC, datetime

    class _EmptyTransport(_RecordingTransport):
        def _handler(self, request: httpx.Request) -> httpx.Response:
            self.calls.append((request.method, request.url.path))
            if request.url.path.endswith("/_mapping"):
                return httpx.Response(200, json={"ubi_queries": {"mappings": {"properties": {}}}})
            if request.url.path.endswith("/_settings"):
                return httpx.Response(200, json={"ubi_queries": {"settings": {"index": {}}}})
            if request.url.path == "/_msearch":
                # Empty hits — triggers the empty-window early return path.
                return httpx.Response(200, json={"responses": [{"hits": {"hits": []}}]})
            raise AssertionError(f"unexpected request to {request.method} {request.url.path}")

    transport = _EmptyTransport()
    adapter = _build_adapter(transport)
    try:
        out = await UbiReader(adapter).read_features(
            target="products", since=datetime(2026, 5, 1, tzinfo=UTC)
        )
    finally:
        await adapter.aclose()

    assert out == {}
    # The reader short-circuits after the empty queries scan; only one
    # _msearch fires, not two.
    msearch_calls = [c for c in transport.calls if c[1] == "/_msearch"]
    assert len(msearch_calls) == 1

    # Same invariant.
    for method, path in transport.calls:
        assert method.upper() not in WRITE_METHODS
        for forbidden_segment in WRITE_PATH_SEGMENTS:
            assert forbidden_segment not in path.split("/")
