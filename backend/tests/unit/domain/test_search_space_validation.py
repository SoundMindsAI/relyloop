"""Unit tests for ``validate_against_template`` (chore_create_study_wizard_polish Story 1.1).

Covers the four behavioral cases from the implementation plan:

  1. Unknown param → ``UnknownSearchSpaceParamError`` with spec-exact message.
  2. Missing declared param → ``MissingDeclaredParamError`` with spec-exact message.
  3. Both conditions present → unknown-param raised first (AC-7 ordering rule).
  4. Happy path (keys match) → returns ``None``.

Source-of-truth for message text: chore_create_study_wizard_polish/feature_spec.md FR-2 + FR-3.
"""

from __future__ import annotations

import pytest

from backend.app.domain.study.search_space import (
    MissingDeclaredParamError,
    SearchSpace,
    UnknownSearchSpaceParamError,
    validate_against_template,
)


def _space(**params: dict[str, object]) -> SearchSpace:
    """Build a SearchSpace from kwargs (``boost_title={"type": "float", "low": 0, "high": 1}``)."""
    return SearchSpace.model_validate({"params": dict(params)})


def test_unknown_param_raises_with_spec_exact_message() -> None:
    space = _space(boos_title={"type": "float", "low": 0.5, "high": 10.0, "log": True})
    declared = {"boost_title": "float", "fuzziness": "string"}
    with pytest.raises(UnknownSearchSpaceParamError) as excinfo:
        validate_against_template(space, declared, "product_search v1")
    msg = str(excinfo.value)
    assert "Param 'boos_title' is not declared by template 'product_search v1'" in msg
    # Declared params list is sorted; both names appear.
    assert "'boost_title'" in msg
    assert "'fuzziness'" in msg


def test_unknown_param_picks_lexicographically_smallest() -> None:
    space = _space(
        zzz_typo={"type": "float", "low": 0, "high": 1},
        aaa_typo={"type": "float", "low": 0, "high": 1},
    )
    declared = {"boost_title": "float"}
    with pytest.raises(UnknownSearchSpaceParamError) as excinfo:
        validate_against_template(space, declared, "T1")
    assert "Param 'aaa_typo'" in str(excinfo.value)


def test_missing_declared_param_raises_with_spec_exact_message() -> None:
    space = _space(boost_title={"type": "float", "low": 0.5, "high": 10.0, "log": True})
    declared = {"boost_title": "float", "fuzziness": "string"}
    with pytest.raises(MissingDeclaredParamError) as excinfo:
        validate_against_template(space, declared, "product_search v1")
    msg = str(excinfo.value)
    assert (
        "Template 'product_search v1' declares param 'fuzziness' but it is missing "
        "from the search space. Add it or remove from the template." in msg
    )


def test_missing_declared_picks_lexicographically_smallest() -> None:
    space = _space(boost_title={"type": "float", "low": 0.5, "high": 10.0, "log": True})
    declared = {"boost_title": "float", "zzz": "string", "aaa": "string"}
    with pytest.raises(MissingDeclaredParamError) as excinfo:
        validate_against_template(space, declared, "T1")
    assert "declares param 'aaa'" in str(excinfo.value)


def test_unknown_wins_over_missing_when_both_apply() -> None:
    """AC-7: unknown-param wins over missing-declared-param when both apply."""
    space = _space(
        boos_title={"type": "float", "low": 0.5, "high": 10.0, "log": True},
    )
    declared = {"boost_title": "float", "fuzziness": "string"}
    with pytest.raises(UnknownSearchSpaceParamError):
        validate_against_template(space, declared, "T1")


def test_happy_path_does_not_raise() -> None:
    """When keys match exactly, validate_against_template returns without raising."""
    space = _space(
        boost_title={"type": "float", "low": 0.5, "high": 10.0, "log": True},
        fuzziness={"type": "categorical", "choices": ["AUTO", "0", "1", "2"]},
    )
    declared = {"boost_title": "float", "fuzziness": "string"}
    # mypy: function returns None; we can't ``assert ... is None`` without a
    # `[func-returns-value]` complaint. Calling unwrapped is the assertion.
    validate_against_template(space, declared, "T1")
