# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""CLI engine-tolerance contract for `seed_meaningful_demos.main()` (Story 1.3).

Pins the skip-on-unreachable behavior added by infra_solr_ci_readiness:
- A scenario whose engine is unreachable is SKIPPED (logged `[skip]`, recorded
  in the `skipped` summary), not failed — `make seed-demo` still seeds the
  reachable engines and exits 0 (AC-6).
- When NO engine is reachable, the CLI hard-fails with an explicit error and
  exits 1 (AC-6b), mirroring the orchestrator's AllEnginesUnreachableError.
- Exit-code order: real failures take precedence over the all-unreachable guard.

All I/O helpers are monkeypatched — pure control-flow test.
"""

from __future__ import annotations

import urllib.error
from collections.abc import Callable
from typing import Any

import pytest

from scripts import seed_meaningful_demos as sm

_SLUGS: list[str] = [str(s["slug"]) for s in sm.SCENARIOS]
_RICH_SLUG = "acme-products-rich-prod"


class _Calls:
    def __init__(self) -> None:
        self.scenarios: list[str] = []
        self.rich = 0
        self.truncate = 0
        self.renames = 0


@pytest.fixture
def patched_io(monkeypatch: pytest.MonkeyPatch) -> _Calls:
    calls = _Calls()
    monkeypatch.setattr(
        sm, "truncate_demo_state", lambda: calls.__setattr__("truncate", calls.truncate + 1)
    )
    monkeypatch.setattr(
        sm, "apply_study_renames", lambda _r: calls.__setattr__("renames", calls.renames + 1)
    )

    def _rich() -> dict[str, Any]:
        calls.rich += 1
        return {"slug": _RICH_SLUG, "study_id": "study-rich", "study_name": _RICH_SLUG}

    monkeypatch.setattr(sm, "seed_rich_scenario", _rich)
    # These tests exercise engine-reachability / failure handling, not the
    # OpenAI gate; treat OpenAI as configured so the rich scenario isn't skipped
    # for a missing key. (See test_seed_meaningful_demos_openai_skip.py.)
    monkeypatch.setattr(sm, "_openai_available", lambda: True)
    return calls


def _fake_seed_scenario(calls: _Calls) -> Callable[[dict[str, Any]], list[dict[str, Any]]]:
    def _seed(s: dict[str, Any]) -> list[dict[str, Any]]:
        slug = str(s["slug"])
        calls.scenarios.append(slug)
        return [{"slug": slug, "study_id": f"study-{slug}", "study_name": slug}]

    return _seed


def _reachable_except(*unreachable_engine_types: str) -> Callable[[str, str], bool]:
    """Build a `_engine_reachable` stub: every engine reachable except the named types."""

    def _probe(_host: str, engine_type: str) -> bool:
        return engine_type not in unreachable_engine_types

    return _probe


def test_solr_unreachable_is_skipped_exit_zero(
    monkeypatch: pytest.MonkeyPatch, patched_io: _Calls, capsys: pytest.CaptureFixture[str]
) -> None:
    """Solr down + ES/OS up -> Solr scenario skipped, the rest seed, exit 0 (AC-6)."""
    monkeypatch.setattr(sm, "seed_scenario", _fake_seed_scenario(patched_io))
    monkeypatch.setattr(sm, "_engine_reachable", _reachable_except("solr"))
    monkeypatch.setattr("sys.argv", ["seed_meaningful_demos.py", "--force"])

    rc = sm.main()

    err = capsys.readouterr().err
    # The Solr scenario is the only one keyed to engine_type "solr".
    solr_slugs = [str(s["slug"]) for s in sm.SCENARIOS if s["engine_type"] == "solr"]
    assert solr_slugs, "fixture expects at least one solr scenario in SCENARIOS"
    for slug in solr_slugs:
        assert slug not in patched_io.scenarios  # skipped before seed_scenario
        assert f"[skip] {slug}" in err
        assert slug in err  # also in the SKIPPED summary section
    assert "SKIPPED (engine unreachable)" in err
    # Reachable ES/OS scenarios + rich still seeded.
    assert patched_io.rich == 1
    assert rc == 0


def test_all_engines_unreachable_hard_fails_exit_one(
    monkeypatch: pytest.MonkeyPatch, patched_io: _Calls, capsys: pytest.CaptureFixture[str]
) -> None:
    """No engine reachable -> nothing seeds, explicit error, exit 1 (AC-6b)."""
    monkeypatch.setattr(sm, "seed_scenario", _fake_seed_scenario(patched_io))
    monkeypatch.setattr(
        sm, "_engine_reachable", _reachable_except("elasticsearch", "opensearch", "solr")
    )
    monkeypatch.setattr("sys.argv", ["seed_meaningful_demos.py", "--force"])

    rc = sm.main()

    err = capsys.readouterr().err
    # Every SCENARIOS slug + the rich slug skipped; seed_scenario never called.
    assert patched_io.scenarios == []
    assert patched_io.rich == 0
    for slug in (*_SLUGS, _RICH_SLUG):
        assert slug in err
    assert "all engines unreachable" in err
    assert rc == 1


def test_all_reachable_seeds_everything_exit_zero(
    monkeypatch: pytest.MonkeyPatch, patched_io: _Calls
) -> None:
    monkeypatch.setattr(sm, "seed_scenario", _fake_seed_scenario(patched_io))
    monkeypatch.setattr(sm, "_engine_reachable", _reachable_except())  # all reachable
    monkeypatch.setattr("sys.argv", ["seed_meaningful_demos.py", "--force"])

    rc = sm.main()

    assert patched_io.scenarios == _SLUGS
    assert patched_io.rich == 1
    assert rc == 0


def test_truncate_skips_engine_when_host_unreachable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A down engine (URLError on DELETE) is skipped, not propagated.

    Regression for the solr-only auto-seed crash: `RELYLOOP_ENGINES=solr make up`
    never starts ES/OpenSearch, so the pre-seed truncate's DELETE against the
    `elasticsearch` host raised `URLError` and killed the whole auto-seed before
    any data was seeded. The truncate must tolerate an absent engine and move on.
    """
    calls: list[str] = []

    def _fake_http(method: str, url: str, **_kw: Any) -> None:
        calls.append(url)
        raise urllib.error.URLError("[Errno -2] Name or service not known")

    monkeypatch.setattr(sm, "http", _fake_http)

    # Must not raise even with multiple indices to delete.
    sm._truncate_engine_indices("es", "http://elasticsearch:9200", ("a", "b"), ("idx1", "idx2"))

    # Bails after the first unreachable hit — no point retrying every index on a
    # host that isn't up.
    assert calls == ["http://elasticsearch:9200/idx1"]
    assert "es: not reachable" in capsys.readouterr().out


def test_truncate_tolerates_404_and_deletes_all_indices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 404 (index already gone) is fine; every listed index is still attempted."""
    calls: list[str] = []

    def _fake_http(method: str, url: str, **_kw: Any) -> None:
        calls.append(url)
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(sm, "http", _fake_http)

    sm._truncate_engine_indices("os", "http://opensearch:9200", ("a", "b"), ("x", "y"))

    assert calls == ["http://opensearch:9200/x", "http://opensearch:9200/y"]


def test_truncate_reraises_non_404_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real server error (non-404) must propagate — it is not engine-absence."""

    def _fake_http(method: str, url: str, **_kw: Any) -> None:
        raise urllib.error.HTTPError(url, 500, "Server Error", {}, None)  # type: ignore[arg-type]

    monkeypatch.setattr(sm, "http", _fake_http)

    with pytest.raises(urllib.error.HTTPError):
        sm._truncate_engine_indices("es", "http://elasticsearch:9200", ("a", "b"), ("idx",))


def test_rich_openai_skip_uses_separate_summary_not_engine_unreachable(
    monkeypatch: pytest.MonkeyPatch,
    patched_io: _Calls,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """OpenAI-skip of the rich scenario must NOT be reported as 'engine unreachable'."""
    monkeypatch.setattr(sm, "seed_scenario", _fake_seed_scenario(patched_io))
    monkeypatch.setattr(sm, "_engine_reachable", _reachable_except())  # all engines reachable
    monkeypatch.setattr(sm, "_openai_available", lambda: False)  # but no OpenAI key
    monkeypatch.setattr("sys.argv", ["seed_meaningful_demos.py", "--force"])

    rc = sm.main()

    err = capsys.readouterr().err
    # Rich scenario skipped (not seeded), reported under the OpenAI bucket...
    assert patched_io.rich == 0
    assert "SKIPPED (OpenAI not configured)" in err
    assert "acme-products-rich-prod" in err
    assert "openai_key" in err
    # ...and NOT mislabeled as engine-unreachable (engines were reachable).
    assert "SKIPPED (engine unreachable)" not in err
    # The small scenarios still seeded → clean exit, no rollback.
    assert patched_io.scenarios == _SLUGS
    assert rc == 0
