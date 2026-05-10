"""ElasticAdapter constructor + auth_kind handling (Story 2.1, FR-2 + AC-7).

Asserts the ``auth_kind`` allowlist matches the spec § enum + plan §0
``SUPPORTED`` / ``RESERVED`` frozensets:

* ``opensearch_sigv4`` is RESERVED (passes the DB CHECK constraint, but
  unimplemented in MVP1) → constructor raises ``NotImplementedError``.
* ``es_apikey`` / ``es_basic`` / ``opensearch_basic`` construct successfully
  with appropriately shaped credentials in the mounted YAML.
* Unknown ``auth_kind`` → ``ValueError`` (defensive — service-layer rejects
  before reaching the adapter, but the adapter must fail loud).
"""

from __future__ import annotations

import pytest

from backend.app.adapters.elastic import ElasticAdapter
from backend.app.core.settings import get_settings


@pytest.fixture(autouse=True)
def _stub_credentials(tmp_path, monkeypatch):
    """Mount a synthetic cluster_credentials YAML for every test in this module."""
    creds = tmp_path / "creds.yaml"
    creds.write_text(
        "ref-apikey:\n"
        "  api_key: synthetic-apikey-value\n"
        "ref-basic:\n"
        "  username: u\n"
        "  password: p\n"
        "ref-os-basic:\n"
        "  username: ou\n"
        "  password: op\n"
    )
    monkeypatch.setenv("DATABASE_URL_FILE", str(tmp_path / "db_url"))
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(tmp_path / "pg_pw"))
    monkeypatch.setenv("CLUSTER_CREDENTIALS_FILE", str(creds))
    (tmp_path / "db_url").write_text("postgresql+asyncpg://u:p@h/d")
    (tmp_path / "pg_pw").write_text("p")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestReservedAuthKind:
    def test_opensearch_sigv4_raises_not_implemented(self) -> None:
        """AC-7: ``opensearch_sigv4`` is reserved but explicitly unimplemented."""
        with pytest.raises(NotImplementedError, match="opensearch_sigv4"):
            ElasticAdapter(
                cluster_id="id",
                engine_type="opensearch",
                base_url="http://opensearch:9200",
                auth_kind="opensearch_sigv4",
                credentials_ref="ref-os-basic",
                engine_config=None,
            )


class TestSupportedAuthKinds:
    def test_es_apikey_constructs(self) -> None:
        adapter = ElasticAdapter(
            cluster_id="id",
            engine_type="elasticsearch",
            base_url="http://elasticsearch:9200",
            auth_kind="es_apikey",
            credentials_ref="ref-apikey",
            engine_config=None,
        )
        assert adapter._auth_headers["Authorization"].startswith("ApiKey ")

    def test_es_basic_constructs(self) -> None:
        adapter = ElasticAdapter(
            cluster_id="id",
            engine_type="elasticsearch",
            base_url="http://elasticsearch:9200",
            auth_kind="es_basic",
            credentials_ref="ref-basic",
            engine_config=None,
        )
        assert adapter._auth_headers["Authorization"].startswith("Basic ")

    def test_opensearch_basic_constructs(self) -> None:
        adapter = ElasticAdapter(
            cluster_id="id",
            engine_type="opensearch",
            base_url="http://opensearch:9200",
            auth_kind="opensearch_basic",
            credentials_ref="ref-os-basic",
            engine_config=None,
        )
        assert adapter._auth_headers["Authorization"].startswith("Basic ")


class TestUnknownAuthKind:
    def test_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="unknown auth_kind"):
            ElasticAdapter(
                cluster_id="id",
                engine_type="elasticsearch",
                base_url="http://elasticsearch:9200",
                auth_kind="bogus",
                credentials_ref="ref-basic",
                engine_config=None,
            )


class TestBaseUrlNormalization:
    def test_trailing_slash_stripped(self) -> None:
        adapter = ElasticAdapter(
            cluster_id="id",
            engine_type="elasticsearch",
            base_url="http://elasticsearch:9200/",
            auth_kind="es_basic",
            credentials_ref="ref-basic",
            engine_config=None,
        )
        assert adapter.base_url == "http://elasticsearch:9200"
