"""Engine-branch completeness tests (Story 2.7 / spec §14).

Verifies the small set of ``engine_type``-aware code paths behaves correctly
for both Elasticsearch and OpenSearch. Mostly a guard against future
contributors accidentally collapsing a branch.

Cases:
* ``_enforce_min_version`` thresholds: ES 8.10 < 8.11 raises; OpenSearch
  1.3 < 2.0 raises; ES 9.0 + OpenSearch 2.18 are accepted.
* ``GET /`` body shape divergence: ES exposes ``version.number``;
  OpenSearch additionally returns ``version.distribution: opensearch``.
  Both engines report the same ``version.number`` location, which is what
  ``health_check`` reads — so the adapter Just Works without engine-specific
  parsing. This test asserts that both shapes succeed via health_check.
"""

from __future__ import annotations

import httpx
import pytest

from backend.app.adapters.elastic import ElasticAdapter
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


def _build_adapter(handler, engine: str, auth: str = "es_basic") -> ElasticAdapter:
    return ElasticAdapter(
        cluster_id="id",
        engine_type=engine,  # type: ignore[arg-type]
        base_url="http://es:9200",
        auth_kind=auth if engine == "elasticsearch" else "opensearch_basic",
        credentials_ref="ref",
        engine_config=None,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


class TestEnforceMinVersionThresholds:
    @pytest.mark.parametrize(
        ("engine", "version", "expect_unreachable"),
        [
            ("elasticsearch", "8.10.4", True),  # below 8.11 → unreachable
            ("elasticsearch", "8.11.0", False),  # at floor → ok
            ("elasticsearch", "9.4.0", False),
            ("opensearch", "1.3.0", True),  # below 2.0 → unreachable
            ("opensearch", "2.0.0", False),
            ("opensearch", "2.18.0", False),
        ],
    )
    async def test_thresholds(self, engine: str, version: str, expect_unreachable: bool) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/_cluster/health":
                return httpx.Response(200, json={"status": "green"})
            return httpx.Response(200, json={"version": {"number": version}})

        adapter = _build_adapter(handler, engine)
        try:
            status = await adapter.health_check()
        finally:
            await adapter.aclose()
        if expect_unreachable:
            assert status.status == "unreachable"
            assert status.error is not None
            assert "below minimum" in status.error
        else:
            assert status.status == "green"


class TestVersionShapeDivergence:
    async def test_opensearch_distribution_field_doesnt_break(self) -> None:
        """OpenSearch's GET / adds version.distribution; we only read version.number."""

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/_cluster/health":
                return httpx.Response(200, json={"status": "green"})
            # OpenSearch shape: number + distribution
            return httpx.Response(
                200,
                json={
                    "name": "opensearch-node1",
                    "cluster_name": "docker-cluster",
                    "version": {
                        "number": "2.18.0",
                        "distribution": "opensearch",
                        "build_type": "tar",
                    },
                },
            )

        adapter = _build_adapter(handler, "opensearch")
        try:
            status = await adapter.health_check()
        finally:
            await adapter.aclose()
        assert status.status == "green"
        assert status.version == "2.18.0"

    async def test_elasticsearch_no_distribution_field(self) -> None:
        """ES's GET / has version.number but not version.distribution; both work."""

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == "/_cluster/health":
                return httpx.Response(200, json={"status": "green"})
            return httpx.Response(
                200,
                json={
                    "name": "es-node1",
                    "cluster_name": "docker-cluster",
                    "version": {"number": "9.4.0", "build_flavor": "default"},
                },
            )

        adapter = _build_adapter(handler, "elasticsearch")
        try:
            status = await adapter.health_check()
        finally:
            await adapter.aclose()
        assert status.status == "green"
        assert status.version == "9.4.0"
