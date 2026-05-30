"""Regression guard: `seed_meaningful_demos.main()` failure semantics.

Pins the continue-on-failure contract introduced after the
"I only got 2 of 5 studies" incident: a single small scenario failing in
explicit `--force` mode (e.g. one engine hits its disk flood-stage watermark
and 403s on create-index) must NOT abort the whole seed. The old code did
`return 1` on the first failure, silently skipping every scenario after it.

Two modes, two contracts:
- `--force` (explicit `make seed-demo`): continue past a failed scenario,
  seed the rest, run the rich scenario, then exit non-zero with a summary.
- `--if-empty` (auto-seed from `make up`): a failure rolls back the partial
  state and bails immediately so the next boot retries cleanly (unchanged).

All I/O helpers are monkeypatched — this is a pure control-flow test.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from scripts import seed_meaningful_demos as sm

_SLUGS: list[str] = [str(s["slug"]) for s in sm.SCENARIOS]


class _Calls:
    """Records which side-effecting helpers main() invoked, and how often."""

    def __init__(self) -> None:
        self.scenarios: list[str] = []
        self.rich = 0
        self.truncate = 0
        self.renames = 0


@pytest.fixture
def patched_io(monkeypatch: pytest.MonkeyPatch) -> _Calls:
    """Stub every side-effecting helper main() touches; record what ran."""
    calls = _Calls()

    def _truncate() -> None:
        calls.truncate += 1

    def _renames(_results: list[dict[str, Any]]) -> None:
        calls.renames += 1

    def _rich() -> dict[str, Any]:
        calls.rich += 1
        return {}

    monkeypatch.setattr(sm, "truncate_demo_state", _truncate)
    monkeypatch.setattr(sm, "apply_study_renames", _renames)
    monkeypatch.setattr(sm, "seed_rich_scenario", _rich)
    return calls


def _fake_seed_scenario(
    calls: _Calls, *, fail_slug: str | None
) -> Callable[[dict[str, Any]], list[dict[str, Any]]]:
    """Stub for ``seed_scenario`` — returns a list to match Story 2.5 / FR-9.

    The real ``seed_scenario`` returns 1 entry for non-UBI scenarios and
    2 entries for UBI-enabled (LLM + UBI studies). For the failure-mode
    test we only care that the loop iterates every scenario; returning a
    single-entry list per call mirrors the simplest happy-path shape
    without needing per-scenario UBI awareness.
    """

    def _seed(s: dict[str, Any]) -> list[dict[str, Any]]:
        slug = str(s["slug"])
        calls.scenarios.append(slug)
        if slug == fail_slug:
            raise RuntimeError(
                "HTTP 403 index_create_block_exception: "
                "FORBIDDEN/10/cluster create-index blocked (api)"
            )
        return [{"slug": slug, "study_id": f"study-{slug}", "study_name": slug}]

    return _seed


def test_force_mode_continues_past_failed_scenario(
    monkeypatch: pytest.MonkeyPatch, patched_io: _Calls
) -> None:
    """A 3rd-scenario failure must not stop scenarios 4+ from seeding."""
    fail = _SLUGS[2]  # news-search-staging (the OpenSearch one in the real incident)
    monkeypatch.setattr(sm, "seed_scenario", _fake_seed_scenario(patched_io, fail_slug=fail))
    monkeypatch.setattr("sys.argv", ["seed_meaningful_demos.py", "--force"])

    rc = sm.main()

    # Every scenario was attempted — the loop did NOT short-circuit on the failure.
    assert patched_io.scenarios == _SLUGS, (
        "seed loop must attempt every scenario in --force mode even after one "
        f"fails; attempted {patched_io.scenarios!r}"
    )
    # The rich scenario still ran (it lives after the loop).
    assert patched_io.rich == 1
    # Demo is incomplete → non-zero exit so the operator/caller sees the failure.
    assert rc == 1
    # No rollback in explicit mode — partial state is preserved for inspection.
    assert patched_io.truncate == 1  # the initial pre-seed truncate only


def test_force_mode_all_success_returns_zero(
    monkeypatch: pytest.MonkeyPatch, patched_io: _Calls
) -> None:
    monkeypatch.setattr(sm, "seed_scenario", _fake_seed_scenario(patched_io, fail_slug=None))
    monkeypatch.setattr("sys.argv", ["seed_meaningful_demos.py", "--force"])

    rc = sm.main()

    assert patched_io.scenarios == _SLUGS
    assert patched_io.rich == 1
    assert rc == 0


def test_if_empty_mode_rolls_back_and_bails_on_first_failure(
    monkeypatch: pytest.MonkeyPatch, patched_io: _Calls
) -> None:
    """--if-empty contract is unchanged: roll back + bail on first failure."""
    monkeypatch.setattr(sm, "count_existing_clusters", lambda **_: 0)
    fail = _SLUGS[0]  # first scenario fails
    monkeypatch.setattr(sm, "seed_scenario", _fake_seed_scenario(patched_io, fail_slug=fail))
    monkeypatch.setattr("sys.argv", ["seed_meaningful_demos.py", "--if-empty"])

    rc = sm.main()

    # Bailed immediately — later scenarios were NOT attempted.
    assert patched_io.scenarios == [_SLUGS[0]], (
        "--if-empty must bail on the first failure, not continue; "
        f"attempted {patched_io.scenarios!r}"
    )
    # The rich scenario never ran (we returned before it).
    assert patched_io.rich == 0
    # Rolled back: the initial pre-seed truncate + the failure-rollback truncate.
    assert patched_io.truncate == 2
    assert rc == 1
