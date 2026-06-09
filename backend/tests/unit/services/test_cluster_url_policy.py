# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the async cluster-URL SSRF orchestrator (FR-1/FR-2).

Covers ``bug_cluster_url_ssrf_hostname_bypass`` AC-1..AC-7 at the service
layer with a monkeypatched resolver — no DB, no real DNS.
"""

from __future__ import annotations

import socket
from collections.abc import Callable
from typing import Any

import pytest

from backend.app.services.cluster_url_policy import (
    ClusterUrlBlocked,
    assert_base_url_allowed,
)


class _FakeSettings:
    def __init__(self, allow_private: bool) -> None:
        self.relyloop_allow_private_clusters = allow_private


def _patch_flag(monkeypatch: pytest.MonkeyPatch, allow_private: bool) -> None:
    """Patch get_settings in the policy module so tests don't need mounted secrets."""
    monkeypatch.setattr(
        "backend.app.services.cluster_url_policy.get_settings",
        lambda: _FakeSettings(allow_private),
    )


@pytest.fixture
def hardened(monkeypatch: pytest.MonkeyPatch) -> None:
    """RELYLOOP_ALLOW_PRIVATE_CLUSTERS=False — the posture the guard protects."""
    _patch_flag(monkeypatch, allow_private=False)


def _resolver(*ips: str) -> Callable[..., list[tuple[Any, ...]]]:
    """Build a fake socket.getaddrinfo returning the given IPs as 5-tuples."""

    def fake(host: str, port: Any, *args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)) for ip in ips]

    return fake


def _raising_resolver(*_a: Any, **_k: Any) -> list[tuple[Any, ...]]:
    raise socket.gaierror("Name or service not known")


# --- AC-4: no-op when private clusters are allowed (shipped default) ---------


async def test_noop_when_private_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_flag(monkeypatch, allow_private=True)
    # Even though this host would resolve to a private IP, the flag is True so
    # no policy applies and the resolver is never consulted.
    monkeypatch.setattr(socket, "getaddrinfo", _resolver("10.0.0.1"))
    await assert_base_url_allowed("http://internal.test:9200")  # no raise


# --- AC-1: metadata hostname blocked (no DNS needed) -------------------------


async def test_metadata_hostname_blocked(hardened: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # Resolver should NOT be needed — the metadata name short-circuits.
    monkeypatch.setattr(socket, "getaddrinfo", _raising_resolver)
    with pytest.raises(ClusterUrlBlocked, match="cloud-metadata"):
        await assert_base_url_allowed("http://metadata.google.internal/")


# --- AC-5: literal blocked IP (no DNS) ---------------------------------------


async def test_literal_loopback_blocked(hardened: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _raising_resolver)  # must not be called
    with pytest.raises(ClusterUrlBlocked, match="blocked-range"):
        await assert_base_url_allowed("http://127.0.0.1:9200")


async def test_literal_public_ip_allowed(hardened: None) -> None:
    await assert_base_url_allowed("http://93.184.216.34:9200")  # no raise


# --- AC-2: hostname resolving to a private IP blocked ------------------------


async def test_hostname_resolving_private_blocked(
    hardened: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _resolver("10.1.2.3"))
    with pytest.raises(ClusterUrlBlocked, match="resolves to a blocked-range"):
        await assert_base_url_allowed("http://internal.test:9200")


# --- AC-3: hostname resolving to a public IP allowed -------------------------


async def test_hostname_resolving_public_allowed(
    hardened: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _resolver("93.184.216.34"))
    await assert_base_url_allowed("http://search.example.com:9200")  # no raise


async def test_mixed_resolution_blocks(hardened: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # Any blocked address in the resolved set fails the URL (fail-safe).
    monkeypatch.setattr(socket, "getaddrinfo", _resolver("93.184.216.34", "10.0.0.5"))
    with pytest.raises(ClusterUrlBlocked, match="resolves to a blocked-range"):
        await assert_base_url_allowed("http://rebind.test:9200")


# --- AC-7: unresolvable host falls through (not an SSRF hit) -----------------


async def test_unresolvable_host_passes(hardened: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _raising_resolver)
    await assert_base_url_allowed("http://does-not-resolve.invalid:9200")  # no raise


async def test_dns_timeout_falls_through(hardened: None, monkeypatch: pytest.MonkeyPatch) -> None:
    """A slow resolver that trips the timeout is treated as 'not an SSRF hit'
    (Gemini review #1) — no raise, the probe surfaces unreachability."""
    import asyncio
    from collections.abc import Coroutine

    async def _slow_wait_for(coro: Coroutine[Any, Any, Any], *_a: Any, **_k: Any) -> Any:
        coro.close()  # close the un-awaited getaddrinfo coroutine to avoid a warning
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", _slow_wait_for)
    await assert_base_url_allowed("http://slow.example.com:9200")  # no raise


# --- FR-2: enforcement fires before any DB use or adapter build --------------


async def test_register_cluster_blocks_before_db_and_probe(
    hardened: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-1 'no probe issued': the guard rejects before _build_adapter_from_args
    and before any repo/DB call in register_cluster."""
    from unittest.mock import MagicMock

    from backend.app.services import cluster as cluster_svc

    def _no_adapter(*_a: Any, **_k: Any) -> None:
        raise AssertionError("adapter build must not run on a blocked URL")

    monkeypatch.setattr(cluster_svc, "_build_adapter_from_args", _no_adapter)
    db = MagicMock(name="db-must-not-be-used")
    redis = MagicMock(name="redis-must-not-be-used")

    with pytest.raises(ClusterUrlBlocked):
        await cluster_svc.register_cluster(
            db,
            redis,
            name="c",
            engine_type="elasticsearch",
            environment="dev",
            base_url="http://metadata.google.internal/",
            auth_kind="es_basic",
            credentials_ref="ref",
            engine_config=None,
            notes=None,
        )


async def test_test_connection_blocks_before_probe(
    hardened: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same pre-probe rejection on the diagnostic test-connection path."""
    from backend.app.services import cluster as cluster_svc

    def _no_adapter(*_a: Any, **_k: Any) -> None:
        raise AssertionError("adapter build must not run on a blocked URL")

    monkeypatch.setattr(cluster_svc, "_build_adapter_from_args", _no_adapter)

    with pytest.raises(ClusterUrlBlocked):
        await cluster_svc.test_cluster_connection(
            engine_type="elasticsearch",
            base_url="http://127.0.0.1:9200",
            auth_kind="es_basic",
            credentials_ref="ref",
            engine_config=None,
        )
