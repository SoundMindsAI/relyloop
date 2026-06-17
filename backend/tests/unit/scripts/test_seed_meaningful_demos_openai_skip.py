# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""`_openai_available` — graceful skip of LLM demo steps when no OpenAI key.

The OpenAI key is an OPTIONAL secret (a keyless install is fully supported), so
the demo seed must SKIP its LLM-dependent steps — hybrid UBI+LLM judgment
generation, the rich scenario's `/judgments/generate`, and digest narratives —
rather than 503-hard-failing the scenario. (A hard failure in `--if-empty`
auto-seed mode rolls the whole demo back to empty, so a keyless `make up` would
leave the operator with NO demo data.)

`_openai_available()` is the gate: it reads `/healthz` `subsystems.openai`
(`configured | missing_key | incapable`) and only `configured` enables the LLM
steps. These tests pin that logic + the once-and-cached behavior.
"""

from __future__ import annotations

from typing import Any

import pytest

import scripts.seed_meaningful_demos as seed


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    # _openai_available caches in a module global; reset before each test.
    monkeypatch.setattr(seed, "_OPENAI_AVAILABLE", None)


def _health(state: str) -> Any:
    def _fake_http(_method: str, _url: str, *_a: object, **_k: object) -> dict[str, Any]:
        return {"subsystems": {"openai": state}}

    return _fake_http


def test_available_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "http", _health("configured"))
    assert seed._openai_available() is True


@pytest.mark.parametrize("state", ["missing_key", "incapable"])
def test_unavailable_when_not_configured(monkeypatch: pytest.MonkeyPatch, state: str) -> None:
    monkeypatch.setattr(seed, "http", _health(state))
    assert seed._openai_available() is False


def test_unavailable_on_probe_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: object, **_k: object) -> dict[str, Any]:
        raise RuntimeError("healthz unreachable")

    monkeypatch.setattr(seed, "http", _boom)
    # The probe must never be what fails the seed — errors => unavailable (skip).
    assert seed._openai_available() is False


def test_probed_once_then_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def _counting(_method: str, _url: str, *_a: object, **_k: object) -> dict[str, Any]:
        calls["n"] += 1
        return {"subsystems": {"openai": "configured"}}

    monkeypatch.setattr(seed, "http", _counting)
    assert seed._openai_available() is True
    assert seed._openai_available() is True
    assert calls["n"] == 1  # cached after the first probe


def test_probe_targets_healthz_not_api_v1(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def _capture(_method: str, url: str, *_a: object, **_k: object) -> dict[str, Any]:
        captured["url"] = url
        return {"subsystems": {"openai": "configured"}}

    monkeypatch.setattr(seed, "http", _capture)
    seed._openai_available()
    # /healthz is unversioned (root), NOT under /api/v1.
    assert captured["url"].endswith("/healthz")
    assert "/api/v1" not in captured["url"]
