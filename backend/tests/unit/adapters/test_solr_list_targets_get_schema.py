# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``SolrAdapter.list_targets`` + ``get_schema`` unit tests via
``httpx.MockTransport`` (infra_adapter_solr Story A4, FR-6 + FR-7).

* list_targets mode dispatch (cloud → /admin/collections, standalone →
  /admin/cores).
* Target glob filter (matches ElasticAdapter contract: system-exclusion
  FIRST, then fnmatch.fnmatchcase).
* Doc-count derivation (cloud: per-target /select?rows=0; standalone:
  status.<core>.index.numDocs).
* 401/403 → TargetsForbiddenError (distinct from ClusterUnreachableError so
  the frontend can route ACL-restricted clusters to manual mode).
* 5xx → ClusterUnreachableError.
* get_schema: /schema/fields → Schema; 404 → TargetNotFoundError.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from backend.app.adapters.errors import (
    ClusterUnreachableError,
    TargetNotFoundError,
    TargetsForbiddenError,
)
from backend.app.adapters.solr import SolrAdapter
from backend.app.core.settings import get_settings


@pytest.fixture(autouse=True)
def _stub_credentials(tmp_path, monkeypatch):
    creds = tmp_path / "creds.yaml"
    creds.write_text("ref:\n  username: u\n  password: p\n")
    monkeypatch.setenv("DATABASE_URL_FILE", str(tmp_path / "db_url"))
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(tmp_path / "pg_pw"))
    monkeypatch.setenv("CLUSTER_CREDENTIALS_FILE", str(creds))
    (tmp_path / "db_url").write_text("postgresql+asyncpg://u:p@h/d")
    (tmp_path / "pg_pw").write_text("p")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _build(
    handler: Callable[[httpx.Request], httpx.Response], *, mode: str | None = None
) -> SolrAdapter:
    cfg: dict[str, object] | None = {"mode": mode} if mode else None
    return SolrAdapter(
        cluster_id="id",
        engine_type="solr",
        base_url="http://solr:8983",
        auth_kind="solr_basic",
        credentials_ref="ref",
        engine_config=cfg,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


# ---------------------------------------------------------------------------
# list_targets — cloud path.
# ---------------------------------------------------------------------------


class TestListTargetsCloud:
    async def test_cloud_returns_collections_with_counts(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            path = req.url.path
            if path == "/solr/admin/collections":
                return httpx.Response(
                    200,
                    json={"collections": ["products", "orders", ".system"]},
                )
            if path.endswith("/select"):
                # Doc count probe.
                name = path.split("/")[2]
                counts = {"products": 100, "orders": 50}
                return httpx.Response(
                    200, json={"response": {"numFound": counts.get(name, 0), "docs": []}}
                )
            return httpx.Response(404)

        adapter = _build(handler, mode="cloud")
        try:
            targets = await adapter.list_targets()
        finally:
            await adapter.aclose()
        # .system excluded; doc_counts preserved.
        by_name = {t.name: t.doc_count for t in targets}
        assert by_name == {"products": 100, "orders": 50}

    async def test_target_filter_glob(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            path = req.url.path
            if path == "/solr/admin/collections":
                return httpx.Response(
                    200,
                    json={"collections": ["products", "prod_archive", "orders"]},
                )
            return httpx.Response(200, json={"response": {"numFound": 0, "docs": []}})

        adapter = _build(handler, mode="cloud")
        try:
            targets = await adapter.list_targets(target_filter="prod*")
        finally:
            await adapter.aclose()
        assert sorted(t.name for t in targets) == ["prod_archive", "products"]

    async def test_403_raises_targets_forbidden(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(403, text="denied")

        adapter = _build(handler, mode="cloud")
        try:
            with pytest.raises(TargetsForbiddenError, match="cluster denied"):
                await adapter.list_targets()
        finally:
            await adapter.aclose()

    async def test_5xx_raises_cluster_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        adapter = _build(handler, mode="cloud")
        try:
            with pytest.raises(ClusterUnreachableError, match="HTTP 503"):
                await adapter.list_targets()
        finally:
            await adapter.aclose()


# ---------------------------------------------------------------------------
# list_targets — standalone path.
# ---------------------------------------------------------------------------


class TestListTargetsStandalone:
    async def test_standalone_returns_cores_with_numdocs(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "status": {
                        "products": {"name": "products", "index": {"numDocs": 42}},
                        "orders": {"name": "orders", "index": {"numDocs": 12}},
                        ".system": {"name": ".system", "index": {"numDocs": 0}},
                        "_default": {"name": "_default", "index": {}},
                    }
                },
            )

        adapter = _build(handler, mode="standalone")
        try:
            targets = await adapter.list_targets()
        finally:
            await adapter.aclose()
        by_name = {t.name: t.doc_count for t in targets}
        assert by_name == {"products": 42, "orders": 12}


# ---------------------------------------------------------------------------
# list_targets — mode-not-in-engine_config auto-detect.
# ---------------------------------------------------------------------------


class TestModeAutoDetect:
    async def test_auto_detects_cloud_when_mode_absent(self) -> None:
        seen_paths: list[str] = []

        def handler(req: httpx.Request) -> httpx.Response:
            seen_paths.append(req.url.path)
            if req.url.path == "/solr/admin/zookeeper/status":
                return httpx.Response(200, json={"zkStatus": {}})
            if req.url.path == "/solr/admin/collections":
                return httpx.Response(200, json={"collections": ["products"]})
            return httpx.Response(200, json={"response": {"numFound": 7, "docs": []}})

        adapter = _build(handler)  # no mode in engine_config
        try:
            targets = await adapter.list_targets()
        finally:
            await adapter.aclose()
        assert "/solr/admin/zookeeper/status" in seen_paths
        assert "/solr/admin/collections" in seen_paths
        assert [t.name for t in targets] == ["products"]


# ---------------------------------------------------------------------------
# get_schema — happy path + 404 + auth.
# ---------------------------------------------------------------------------


class TestGetSchema:
    async def test_happy_path(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "fields": [
                        {"name": "id", "type": "string"},
                        {"name": "title", "type": "text_general"},
                        {"name": "price", "type": "pfloat"},
                    ]
                },
            )

        adapter = _build(handler)
        try:
            schema = await adapter.get_schema("products")
        finally:
            await adapter.aclose()
        assert schema.name == "products"
        assert {f.name for f in schema.fields} == {"id", "title", "price"}

    async def test_404_raises_target_not_found(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        adapter = _build(handler)
        try:
            with pytest.raises(TargetNotFoundError) as exc:
                await adapter.get_schema("missing")
        finally:
            await adapter.aclose()
        assert exc.value.target == "missing"

    async def test_401_raises_cluster_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(401)

        adapter = _build(handler)
        try:
            with pytest.raises(ClusterUnreachableError, match="Authentication"):
                await adapter.get_schema("products")
        finally:
            await adapter.aclose()

    async def test_5xx_raises_cluster_unreachable(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        adapter = _build(handler)
        try:
            with pytest.raises(ClusterUnreachableError, match="HTTP 503"):
                await adapter.get_schema("products")
        finally:
            await adapter.aclose()

    async def test_malformed_field_entries_skipped(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "fields": [
                        {"name": "id", "type": "string"},
                        "not-a-dict",
                        {"type": "no-name"},  # missing name
                        {"name": "title", "type": "text"},
                    ]
                },
            )

        adapter = _build(handler)
        try:
            schema = await adapter.get_schema("products")
        finally:
            await adapter.aclose()
        assert {f.name for f in schema.fields} == {"id", "title"}
