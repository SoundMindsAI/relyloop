# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Integration coverage for the cluster base_url SSRF guard (FR-2).

bug_cluster_url_ssrf_hostname_bypass. Exercises the full HTTP → service path
against the real DB + real resolver (CI provides Postgres + the ``elasticsearch``
service container, whose hostname resolves to a private Docker IP):

* AC-4 — with the shipped default (RELYLOOP_ALLOW_PRIVATE_CLUSTERS=True) the
  guard is a no-op and an internal Docker hostname registers normally.
* AC-2 — in the hardened posture (False) the same internal hostname resolves
  to a private IP and is rejected 400 CLUSTER_URL_BLOCKED via the **real**
  resolver (not a stub) — proving the hostname path, not just literal IPs.
"""

from __future__ import annotations

import os
import socket
from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio

from backend.app.core.settings import get_settings


def _stack_reachable() -> bool:
    if not os.environ.get("DATABASE_URL_FILE") or not os.environ.get("POSTGRES_PASSWORD_FILE"):
        return False
    for host, port in (("elasticsearch", 9200),):
        try:
            with socket.create_connection((host, port), timeout=1.0):
                pass
        except OSError:
            return False
    return True


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not _stack_reachable(),
        reason="Stack not reachable — needs Postgres + Elasticsearch (CI provides both).",
    ),
]


@pytest_asyncio.fixture(autouse=True)
async def _stub_credentials_yaml(tmp_path, monkeypatch):
    creds = tmp_path / "creds.yaml"
    creds.write_text("test-ref:\n  username: elastic\n  password: changeme\n")
    monkeypatch.setenv("CLUSTER_CREDENTIALS_FILE", str(creds))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def app_client() -> AsyncIterator[httpx.AsyncClient]:
    from backend.app.main import app
    from backend.tests.conftest import _apply_migrations_if_needed

    _apply_migrations_if_needed()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        timeout=30.0,
    ) as client:
        yield client


@pytest_asyncio.fixture
async def clean_clusters() -> AsyncIterator[None]:
    yield
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(get_settings().database_url, future=True)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM clusters"))
    await engine.dispose()


def _body(**overrides: object) -> dict[str, object]:
    return {
        "name": "ssrf-int",
        "engine_type": "elasticsearch",
        "environment": "dev",
        "base_url": "http://elasticsearch:9200",
        "auth_kind": "es_basic",
        "credentials_ref": "test-ref",
        **overrides,
    }


async def test_flag_true_allows_internal_host(
    app_client: httpx.AsyncClient, clean_clusters: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-4: default posture — internal Docker hostname registers (no policy)."""
    monkeypatch.setenv("RELYLOOP_ALLOW_PRIVATE_CLUSTERS", "true")
    get_settings.cache_clear()
    resp = await app_client.post("/api/v1/clusters", json=_body())
    assert resp.status_code == 201, resp.text


async def test_flag_false_blocks_resolved_private_host(
    app_client: httpx.AsyncClient, clean_clusters: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-2: hardened posture — the same hostname resolves (real DNS) to a
    private Docker IP and is rejected before any probe."""
    monkeypatch.setenv("RELYLOOP_ALLOW_PRIVATE_CLUSTERS", "false")
    get_settings.cache_clear()
    resp = await app_client.post("/api/v1/clusters", json=_body())
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["error_code"] == "CLUSTER_URL_BLOCKED"
