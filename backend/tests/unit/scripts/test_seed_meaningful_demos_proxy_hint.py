# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""`_proxy_no_proxy_hint` — corp-proxy diagnosis for engine-unreachable.

When the seed runs inside the api container behind a corporate proxy, the
reachability probe (httpx, trust_env=True) routes in-network engine calls to the
proxy unless the Compose service names are in `no_proxy`. Healthy engines then
read as "unreachable", and the generic "start the engine(s)" advice sends corp
operators down the wrong path. These tests pin the proxy-aware hint that fires
only when a proxy is set AND an engine host is missing from `no_proxy`.
"""

from __future__ import annotations

import pytest

import scripts.seed_meaningful_demos as seed


def _set_container_engine_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "ES", "http://elasticsearch:9200")
    monkeypatch.setattr(seed, "OS", "http://opensearch:9200")
    monkeypatch.setattr(seed, "SOLR", "http://solr:8983")


def test_no_hint_without_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    _set_container_engine_urls(monkeypatch)
    assert seed._proxy_no_proxy_hint() is None


def test_hint_when_engine_hosts_not_exempt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("http_proxy", "http://http.proxy.REDACTED:8000")
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1")  # missing engine names
    _set_container_engine_urls(monkeypatch)

    hint = seed._proxy_no_proxy_hint()

    assert hint is not None
    assert "no_proxy" in hint
    # Names the actual missing hosts and points at the recreate step.
    assert "elasticsearch" in hint and "opensearch" in hint and "solr" in hint
    assert "force-recreate" in hint


def test_no_hint_when_engine_hosts_exempt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("http_proxy", "http://http.proxy.REDACTED:8000")
    monkeypatch.setenv("no_proxy", "localhost,elasticsearch,opensearch,solr")
    _set_container_engine_urls(monkeypatch)
    assert seed._proxy_no_proxy_hint() is None


def test_hint_honors_uppercase_proxy_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://http.proxy.REDACTED:8000")
    monkeypatch.setenv("NO_PROXY", "localhost")  # missing engine names
    _set_container_engine_urls(monkeypatch)
    assert seed._proxy_no_proxy_hint() is not None


def test_no_hint_when_no_proxy_is_wildcard(monkeypatch: pytest.MonkeyPatch) -> None:
    """`no_proxy=*` bypasses the proxy for all hosts → no proxy hint."""
    monkeypatch.setenv("http_proxy", "http://http.proxy.REDACTED:8000")
    monkeypatch.setenv("no_proxy", "*")
    _set_container_engine_urls(monkeypatch)
    assert seed._proxy_no_proxy_hint() is None


def test_no_hint_case_insensitive_exemption(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exemption matches regardless of case (hostnames are case-insensitive)."""
    monkeypatch.setenv("http_proxy", "http://http.proxy.REDACTED:8000")
    monkeypatch.setenv("no_proxy", "ELASTICSEARCH,OpenSearch,Solr")
    _set_container_engine_urls(monkeypatch)
    assert seed._proxy_no_proxy_hint() is None


def test_no_hint_leading_dot_exemption(monkeypatch: pytest.MonkeyPatch) -> None:
    """Leading-dot patterns (`.elasticsearch`) exempt the bare host."""
    monkeypatch.setenv("http_proxy", "http://http.proxy.REDACTED:8000")
    monkeypatch.setenv("no_proxy", ".elasticsearch,.opensearch,.solr")
    _set_container_engine_urls(monkeypatch)
    assert seed._proxy_no_proxy_hint() is None
