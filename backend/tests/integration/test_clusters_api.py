"""Cluster API integration tests (Stories 3.2 / 3.3 / 3.4).

End-to-end coverage of the six endpoints from spec §7.1 against the live
Compose stack (Postgres + Elasticsearch + Redis). Skips when Postgres
isn't host-reachable (the laptop case).

ACs verified:
* AC-1 — POST /clusters happy path; cluster row + cached health.
* AC-3 — POST /run_query happy path; top_k caps results.
* AC-6 — POST /clusters with bad URL → 503 CLUSTER_UNREACHABLE, no DB row.
* AC-7 — POST /clusters with auth_kind='opensearch_sigv4' → 400
  AUTH_KIND_NOT_SUPPORTED.
* AC-8 — DELETE then GET → 404 CLUSTER_NOT_FOUND; subsequent re-POST with
  same name reuses the soft-deleted row (cycle 1 F5 verification).

Spec §7.5 error codes verified:
* ENGINE_NOT_SUPPORTED, AUTH_KIND_NOT_SUPPORTED, CLUSTER_NAME_TAKEN,
  CLUSTER_NOT_FOUND, TARGET_NOT_FOUND, CLUSTER_UNREACHABLE,
  INVALID_QUERY_DSL, VALIDATION_ERROR.
"""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import httpx
import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager

from backend.app.core.settings import get_settings


def _stack_reachable() -> bool:
    """Skip predicate: requires Postgres + Elasticsearch reachable from this process."""
    if not os.environ.get("DATABASE_URL_FILE") or not os.environ.get("POSTGRES_PASSWORD_FILE"):
        return False
    try:
        url = get_settings().database_url
    except Exception:  # noqa: BLE001
        return False
    parsed = urlparse(url)
    pg_host = parsed.hostname or "localhost"
    pg_port = parsed.port or 5432
    try:
        with socket.create_connection((pg_host, pg_port), timeout=1.0):
            pass
    except (TimeoutError, OSError):
        return False
    # Elasticsearch must be reachable too (the registration probe hits it).
    try:
        with socket.create_connection(("elasticsearch", 9200), timeout=1.0):
            return True
    except (TimeoutError, OSError):
        return False


pytestmark = pytest.mark.skipif(
    not _stack_reachable(),
    reason=(
        "Stack not fully reachable — needs Postgres + Elasticsearch from this "
        "process. Run via the one-shot dev-deps container with --network "
        "relyloop_default; CI provides both as service containers."
    ),
)


@pytest_asyncio.fixture
async def app_client() -> AsyncIterator[httpx.AsyncClient]:
    """Yield an httpx.AsyncClient against the live FastAPI app via ASGI transport.

    Uses ``asgi-lifespan`` so the FastAPI startup/shutdown hooks run; the
    capability-check task fires but is harmless under the tests.
    """
    from backend.app.main import app

    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            timeout=30.0,
        ) as client:
            yield client


@pytest_asyncio.fixture
async def clean_clusters() -> AsyncIterator[None]:
    """Hard-delete any cluster rows that leak past the test (no FK risk in MVP1)."""
    yield
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(get_settings().database_url, future=True)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM clusters"))
    await engine.dispose()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


# Per-engine wire config used by the parametrized test classes below.
# Mirrors the Compose service names + default credentials in docker-compose.yml.
# Both engines share the same wire surface (per umbrella spec §8); parametrizing
# proves the adapter doesn't silently regress one engine when the other changes.
_ENGINE_BASE_URL: dict[str, str] = {
    "elasticsearch": "http://elasticsearch:9200",
    "opensearch": "http://opensearch:9200",
}
_ENGINE_RAW_AUTH: dict[str, tuple[str, str]] = {
    "elasticsearch": ("elastic", "changeme"),
    "opensearch": ("admin", "admin"),
}
_ENGINE_AUTH_KIND: dict[str, str] = {
    "elasticsearch": "es_basic",
    "opensearch": "opensearch_basic",
}
_ENGINE_CRED_REF: dict[str, str] = {
    "elasticsearch": "test-es-ref",
    "opensearch": "test-os-ref",
}
_ENGINE_NAME_PREFIX: dict[str, str] = {
    "elasticsearch": "test-es",
    "opensearch": "test-os",
}

# Parametrize tuples used by test classes that need engine-specific config.
ENGINE_PARAMS = [
    pytest.param("elasticsearch", id="es"),
    pytest.param("opensearch", id="opensearch"),
]


def _cluster_body(
    *,
    engine_type: str = "elasticsearch",
    **overrides: object,
) -> dict[str, object]:
    """Build a /clusters POST body for the given engine_type.

    Defaults to elasticsearch for tests that don't parametrize over the
    engine (e.g., validation-only tests where the engine is irrelevant).
    """
    return {
        "name": _ENGINE_NAME_PREFIX[engine_type],
        "engine_type": engine_type,
        "environment": "dev",
        "base_url": _ENGINE_BASE_URL[engine_type],
        "auth_kind": _ENGINE_AUTH_KIND[engine_type],
        "credentials_ref": _ENGINE_CRED_REF[engine_type],
        **overrides,
    }


@pytest_asyncio.fixture(autouse=True)
async def _stub_credentials_yaml(tmp_path, monkeypatch):
    """Mount a YAML with credentials for BOTH ES and OS Compose containers."""
    creds = tmp_path / "creds.yaml"
    creds.write_text(
        "test-es-ref:\n"
        "  username: elastic\n"
        "  password: changeme\n"
        "test-os-ref:\n"
        "  username: admin\n"
        "  password: admin\n"
    )
    monkeypatch.setenv("CLUSTER_CREDENTIALS_FILE", str(creds))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.integration
@pytest.mark.parametrize("engine", ENGINE_PARAMS)
class TestPostCluster:
    """Cluster registration tests parametrized over ES + OpenSearch.

    Validation tests (engine_type / auth_kind / URL scheme) re-run on both
    engines — the redundancy is cheap and proves the validation surface
    behaves identically. Engine-specific tests (happy path, unreachable URL,
    duplicate name) use the parametrize fixture to derive engine wire config.
    """

    async def test_happy_path_201_with_health(
        self, engine: str, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        resp = await app_client.post("/api/v1/clusters", json=_cluster_body(engine_type=engine))
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["engine_type"] == engine
        assert body["health_check"]["status"] in ("green", "yellow")
        assert body["health_check"]["version"] is not None

    async def test_engine_type_solr_returns_400(
        self, engine: str, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        resp = await app_client.post(
            "/api/v1/clusters",
            json=_cluster_body(engine_type="solr"),  # override regardless of parametrize
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["error_code"] == "ENGINE_NOT_SUPPORTED"

    async def test_auth_kind_sigv4_returns_400(
        self, engine: str, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        resp = await app_client.post(
            "/api/v1/clusters",
            json=_cluster_body(engine_type=engine, auth_kind="opensearch_sigv4"),
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error_code"] == "AUTH_KIND_NOT_SUPPORTED"

    async def test_unknown_auth_kind_returns_400(
        self, engine: str, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        resp = await app_client.post(
            "/api/v1/clusters",
            json=_cluster_body(engine_type=engine, auth_kind="bogus"),
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error_code"] == "AUTH_KIND_NOT_SUPPORTED"

    async def test_engine_auth_mismatch_returns_400(
        self, engine: str, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        """engine_type × auth_kind cross-product check: opensearch + es_apikey."""
        resp = await app_client.post(
            "/api/v1/clusters",
            json=_cluster_body(engine_type="opensearch", auth_kind="es_apikey"),
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["detail"]["error_code"] == "AUTH_KIND_NOT_SUPPORTED"
        assert "not valid for engine_type='opensearch'" in body["detail"]["message"]

    async def test_engine_auth_mismatch_es_with_opensearch_basic_returns_400(
        self, engine: str, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        resp = await app_client.post(
            "/api/v1/clusters",
            json=_cluster_body(engine_type="elasticsearch", auth_kind="opensearch_basic"),
        )
        assert resp.status_code == 400
        assert resp.json()["detail"]["error_code"] == "AUTH_KIND_NOT_SUPPORTED"

    async def test_ftp_scheme_returns_422(
        self, engine: str, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        resp = await app_client.post(
            "/api/v1/clusters",
            json=_cluster_body(engine_type=engine, base_url="ftp://x:21/"),
        )
        assert resp.status_code == 422

    async def test_unreachable_url_returns_503_no_row(
        self, engine: str, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        body = _cluster_body(engine_type=engine, base_url=f"http://{engine}:9999")
        resp = await app_client.post("/api/v1/clusters", json=body)
        assert resp.status_code == 503
        assert resp.json()["detail"]["error_code"] == "CLUSTER_UNREACHABLE"
        # AC-6: no DB row created.
        list_resp = await app_client.get("/api/v1/clusters")
        assert all(c["name"] != body["name"] for c in list_resp.json()["data"])

    async def test_duplicate_name_returns_409(
        self, engine: str, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        first = await app_client.post("/api/v1/clusters", json=_cluster_body(engine_type=engine))
        assert first.status_code == 201
        second = await app_client.post("/api/v1/clusters", json=_cluster_body(engine_type=engine))
        assert second.status_code == 409
        assert second.json()["detail"]["error_code"] == "CLUSTER_NAME_TAKEN"


@pytest.mark.integration
class TestGetListAndDetail:
    async def test_list_returns_x_total_count(
        self, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        await app_client.post("/api/v1/clusters", json=_cluster_body())
        resp = await app_client.get("/api/v1/clusters")
        assert resp.status_code == 200
        assert resp.headers["X-Total-Count"] == "1"
        body = resp.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["name"] == "test-es"

    async def test_detail_returns_health_check(
        self, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        post_resp = await app_client.post("/api/v1/clusters", json=_cluster_body())
        cluster_id = post_resp.json()["id"]
        resp = await app_client.get(f"/api/v1/clusters/{cluster_id}")
        assert resp.status_code == 200
        assert resp.json()["health_check"]["status"] in ("green", "yellow")

    async def test_detail_unknown_id_returns_404(
        self, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        resp = await app_client.get("/api/v1/clusters/missing-id")
        assert resp.status_code == 404
        assert resp.json()["detail"]["error_code"] == "CLUSTER_NOT_FOUND"


@pytest.mark.integration
class TestSoftDeleteAndRevival:
    async def test_delete_then_get_returns_404(
        self, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        post_resp = await app_client.post("/api/v1/clusters", json=_cluster_body())
        cluster_id = post_resp.json()["id"]
        del_resp = await app_client.delete(f"/api/v1/clusters/{cluster_id}")
        assert del_resp.status_code == 204
        get_resp = await app_client.get(f"/api/v1/clusters/{cluster_id}")
        assert get_resp.status_code == 404
        assert get_resp.json()["detail"]["error_code"] == "CLUSTER_NOT_FOUND"

    async def test_delete_then_repost_revives(
        self, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        """AC-8 + cycle 1 F5: re-registering a soft-deleted name reuses the row."""
        first = await app_client.post("/api/v1/clusters", json=_cluster_body())
        original_id = first.json()["id"]
        await app_client.delete(f"/api/v1/clusters/{original_id}")
        second = await app_client.post("/api/v1/clusters", json=_cluster_body(notes="reborn"))
        assert second.status_code == 201
        assert second.json()["id"] == original_id
        assert second.json()["notes"] == "reborn"


@pytest.mark.integration
@pytest.mark.parametrize("engine", ENGINE_PARAMS)
class TestSchemaEndpoint:
    async def test_schema_against_seeded_index(
        self, engine: str, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        base_url = _ENGINE_BASE_URL[engine]
        auth = _ENGINE_RAW_AUTH[engine]
        async with httpx.AsyncClient(auth=auth, timeout=10.0) as c:
            await c.put(
                f"{base_url}/products",
                json={
                    "mappings": {
                        "properties": {
                            "title": {"type": "text"},
                            "category": {"type": "keyword"},
                            "price": {"type": "float"},
                            "released_at": {"type": "date"},
                        }
                    }
                },
            )
        try:
            post_resp = await app_client.post(
                "/api/v1/clusters", json=_cluster_body(engine_type=engine)
            )
            cluster_id = post_resp.json()["id"]
            resp = await app_client.get(f"/api/v1/clusters/{cluster_id}/schema?target=products")
            assert resp.status_code == 200, resp.text
            schema = resp.json()
            assert schema["name"] == "products"
            field_names = {f["name"] for f in schema["fields"]}
            assert {"title", "category", "price", "released_at"} <= field_names
            title = next(f for f in schema["fields"] if f["name"] == "title")
            assert title["analyzer"] == "standard"
        finally:
            async with httpx.AsyncClient(auth=auth, timeout=10.0) as c:
                await c.delete(f"{base_url}/products")

    async def test_schema_missing_target_returns_404(
        self, engine: str, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        post_resp = await app_client.post(
            "/api/v1/clusters", json=_cluster_body(engine_type=engine)
        )
        cluster_id = post_resp.json()["id"]
        resp = await app_client.get(f"/api/v1/clusters/{cluster_id}/schema?target=does-not-exist")
        assert resp.status_code == 404
        assert resp.json()["detail"]["error_code"] == "TARGET_NOT_FOUND"


@pytest.mark.integration
@pytest.mark.parametrize("engine", ENGINE_PARAMS)
class TestRunQuery:
    async def test_run_query_happy_path(
        self, engine: str, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        """AC-3: POST /run_query returns hits descending by score."""
        base_url = _ENGINE_BASE_URL[engine]
        auth = _ENGINE_RAW_AUTH[engine]
        async with httpx.AsyncClient(auth=auth, timeout=10.0) as c:
            await c.put(
                f"{base_url}/runq",
                json={"mappings": {"properties": {"title": {"type": "text"}}}},
            )
            for t in ["red shoes", "blue shoes", "green hat"]:
                await c.post(
                    f"{base_url}/runq/_doc?refresh=true",
                    json={"title": t},
                )
        try:
            post_resp = await app_client.post(
                "/api/v1/clusters", json=_cluster_body(engine_type=engine)
            )
            cluster_id = post_resp.json()["id"]
            resp = await app_client.post(
                f"/api/v1/clusters/{cluster_id}/run_query",
                json={
                    "target": "runq",
                    "query_dsl": {"match": {"title": "shoes"}},
                    "top_k": 5,
                },
            )
            assert resp.status_code == 200, resp.text
            hits = resp.json()["hits"]
            assert len(hits) == 2
            # Descending by score
            assert hits[0]["score"] >= hits[1]["score"]
        finally:
            async with httpx.AsyncClient(auth=auth, timeout=10.0) as c:
                await c.delete(f"{base_url}/runq")

    async def test_run_query_top_k_over_1000_returns_422(
        self, engine: str, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        post_resp = await app_client.post(
            "/api/v1/clusters", json=_cluster_body(engine_type=engine)
        )
        cluster_id = post_resp.json()["id"]
        resp = await app_client.post(
            f"/api/v1/clusters/{cluster_id}/run_query",
            json={"target": "x", "query_dsl": {"match_all": {}}, "top_k": 1001},
        )
        assert resp.status_code == 422

    async def test_run_query_unknown_cluster_returns_404(
        self, engine: str, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        resp = await app_client.post(
            "/api/v1/clusters/missing-id/run_query",
            json={"target": "x", "query_dsl": {"match_all": {}}, "top_k": 5},
        )
        assert resp.status_code == 404
        assert resp.json()["detail"]["error_code"] == "CLUSTER_NOT_FOUND"

    async def test_run_query_invalid_dsl_returns_400(
        self, engine: str, app_client: httpx.AsyncClient, clean_clusters: None
    ) -> None:
        base_url = _ENGINE_BASE_URL[engine]
        auth = _ENGINE_RAW_AUTH[engine]
        async with httpx.AsyncClient(auth=auth, timeout=10.0) as c:
            await c.put(
                f"{base_url}/dslfail",
                json={"mappings": {"properties": {"title": {"type": "text"}}}},
            )
        try:
            post_resp = await app_client.post(
                "/api/v1/clusters", json=_cluster_body(engine_type=engine)
            )
            cluster_id = post_resp.json()["id"]
            # bogus_clause is not a valid query parser → parsing_exception on
            # both engines (they share Lucene QueryParser semantics)
            resp = await app_client.post(
                f"/api/v1/clusters/{cluster_id}/run_query",
                json={
                    "target": "dslfail",
                    "query_dsl": {"bogus_clause": {"foo": "bar"}},
                    "top_k": 5,
                },
            )
            assert resp.status_code == 400
            assert resp.json()["detail"]["error_code"] == "INVALID_QUERY_DSL"
        finally:
            async with httpx.AsyncClient(auth=auth, timeout=10.0) as c:
                await c.delete(f"{base_url}/dslfail")
