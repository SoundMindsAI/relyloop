# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Backend half of the build_starter_search_space TS↔Python parity test.

Consumes ``backend/tests/_fixtures/search_space_defaults_parity.json`` —
the same file iterated by
``ui/src/__tests__/lib/search-space-defaults.parity.test.ts``. Drift between
``backend/app/domain/study/search_space_defaults.py:build_starter_search_space``
and ``ui/src/lib/search-space-defaults.ts:buildStarterSearchSpace`` surfaces
in one of the two tests.

feat_agent_propose_search_space Story 1.3 — FR-7, AC-10, AC-13.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.app.domain.study.search_space import InvalidSearchSpaceError
from backend.app.domain.study.search_space_defaults import build_starter_search_space

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "_fixtures" / "search_space_defaults_parity.json"
)


def _load_fixtures() -> list[dict[str, Any]]:
    with _FIXTURE_PATH.open() as fh:
        data = json.load(fh)
    cases: list[dict[str, Any]] = data["fixtures"]
    return cases


_FIXTURES = _load_fixtures()
_HAPPY_FIXTURES = [f for f in _FIXTURES if "expected_search_space" in f]
_ERROR_FIXTURES = [f for f in _FIXTURES if "expected_error" in f]


def test_fixture_row_count() -> None:
    """Lock the fixture size so adding/removing rows is intentional."""
    assert len(_FIXTURES) >= 15
    assert len(_HAPPY_FIXTURES) >= 13
    assert len(_ERROR_FIXTURES) == 2


def _strip_default_log(space_dict: dict[str, Any]) -> dict[str, Any]:
    """Drop ``log: False`` from FloatParams so wire-format fixtures still match.

    Pydantic always emits ``log`` (default False) on FloatParam dumps, while the
    TS wire-format treats ``log`` as optional (omitted = False). Normalize the
    Python side before comparing against the shared JSON fixtures.
    """
    result: dict[str, Any] = {"params": {}}
    for name, param in space_dict["params"].items():
        copy = dict(param)
        if copy.get("type") == "float" and copy.get("log") is False:
            copy.pop("log", None)
        result["params"][name] = copy
    return result


@pytest.mark.parametrize("fixture", _HAPPY_FIXTURES, ids=lambda f: f["name"])
def test_happy_row_matches_expected(fixture: dict[str, Any]) -> None:
    """Every happy fixture: ``build_starter_search_space(declared) → expected``."""
    result = build_starter_search_space(fixture["declared_params"])
    actual_norm = json.loads(json.dumps(_strip_default_log(result.space.model_dump())))
    expected_norm = json.loads(json.dumps(fixture["expected_search_space"]))
    assert actual_norm == expected_norm, (
        f"parity drift for fixture '{fixture['name']}':\n"
        f"  expected: {expected_norm}\n"
        f"  actual:   {actual_norm}"
    )
    assert (
        result.cap_aware_fallback_param_names == fixture["expected_cap_aware_fallback_param_names"]
    ), f"cap_aware_fallback_param_names drift for fixture '{fixture['name']}'"


@pytest.mark.parametrize("fixture", _ERROR_FIXTURES, ids=lambda f: f["name"])
def test_error_row_raises(fixture: dict[str, Any]) -> None:
    """Every error fixture: helper raises InvalidSearchSpaceError matching the substring."""
    expected_substring = fixture["expected_error"]["message_substring"]
    with pytest.raises(InvalidSearchSpaceError, match=expected_substring):
        build_starter_search_space(fixture["declared_params"])
