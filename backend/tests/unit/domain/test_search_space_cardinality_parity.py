"""Backend half of the cardinality parity test (chore_create_study_wizard_polish Story 2.1).

Consumes the same JSON fixture as
``ui/src/__tests__/lib/search-space-defaults.cardinality.test.ts`` so any drift
between the TypeScript port at ``ui/src/lib/search-space-defaults.ts`` and the
Python source-of-truth at ``backend/app/domain/study/search_space.py`` surfaces
in one of the two tests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.domain.study.search_space import SearchSpace, estimate_cardinality

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "_fixtures" / "search_space_cardinality_fixtures.json"
)


def _load_fixtures() -> list[dict[str, object]]:
    with _FIXTURE_PATH.open() as fh:
        data = json.load(fh)
    cases: list[dict[str, object]] = data["fixtures"]
    return cases


def test_fixture_file_has_at_least_eight_cases() -> None:
    """Guard against accidental fixture truncation breaking the parity gate."""
    assert len(_load_fixtures()) >= 8


@pytest.mark.parametrize("fixture", _load_fixtures(), ids=lambda f: f["name"])
def test_python_estimate_matches_fixture_expected(fixture: dict[str, object]) -> None:
    """Each fixture row's ``space`` must produce the documented ``expected`` value."""
    space = SearchSpace.model_validate(fixture["space"])
    assert estimate_cardinality(space) == fixture["expected"]
