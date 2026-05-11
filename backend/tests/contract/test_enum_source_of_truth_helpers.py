"""Helper used by ``scripts/ci/verify_enum_source_of_truth.sh`` to resolve a
backend symbol (a ``typing.Literal[...]`` annotation OR a module-level
``frozenset``/``set``/``tuple``/``list`` constant) to its wire values.

When invoked as ``python -m backend.tests.contract.test_enum_source_of_truth_helpers
<module> <symbol>``, prints a ``|``-separated list of repr-quoted values to stdout.

It also doubles as a pytest contract test that verifies a sampling of the
canonical enums.ts ↔ backend symbol pairs match. The pytest body is small and
deterministic; the CI grep gate is the comprehensive scan.
"""

from __future__ import annotations

import importlib
import sys
import typing
from typing import Any


def resolve_values(module_path: str, symbol_name: str) -> list[Any]:
    """Return the wire values declared by ``module_path.symbol_name``.

    Supports two shapes:

    * ``typing.Literal[...]`` (the canonical wire enum shape used in
      ``backend/app/api/v1/schemas.py``).
    * Module-level ``frozenset``/``set``/``tuple``/``list`` constants (used
      under ``backend/app/eval/scoring.py`` for ``SUPPORTED_METRICS`` etc.).
    """
    module = importlib.import_module(module_path)
    obj = getattr(module, symbol_name)

    # typing.Literal[...] — read the type-arg tuple.
    args = typing.get_args(obj)
    if args:
        return list(args)

    # frozenset / set / tuple / list — read membership directly.
    if isinstance(obj, (frozenset, set, tuple, list)):
        return list(obj)

    raise TypeError(
        f"{module_path}.{symbol_name} is not a Literal[...] or a "
        f"frozenset/set/tuple/list — got {type(obj).__name__}"
    )


def _format_for_shell(values: list[Any]) -> str:
    """Format as a ``|``-separated repr() list — matches the shell consumer's
    expectation in ``verify_enum_source_of_truth.sh``."""
    return "|".join(repr(v) for v in values)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(
            "usage: python -m backend.tests.contract.test_enum_source_of_truth_helpers "
            "<module.path> <SymbolName>",
            file=sys.stderr,
        )
        return 2
    module_path, symbol = argv[1], argv[2]
    try:
        values = resolve_values(module_path, symbol)
    except Exception as exc:  # noqa: BLE001 — emit to stderr + exit non-zero
        print(f"resolve_values failed: {exc}", file=sys.stderr)
        return 1
    print(_format_for_shell(values))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))


# ---------------------------------------------------------------------------
# Pytest sanity — verifies the helper resolves a handful of canonical symbols.
# The full enums.ts ↔ backend audit lives in the CI grep gate (which calls
# `resolve_values` per cited comment, then diffs against the TS array).
# ---------------------------------------------------------------------------


def test_resolve_literal_returns_args() -> None:
    values = resolve_values("backend.app.api.v1.schemas", "StudyStatusWire")
    assert set(values) == {"queued", "running", "completed", "cancelled", "failed"}


def test_resolve_literal_int_args() -> None:
    values = resolve_values("backend.app.api.v1.schemas", "ObjectiveK")
    assert set(values) == {1, 3, 5, 10, 20, 50, 100}


def test_resolve_engine_type_wire() -> None:
    values = resolve_values("backend.app.api.v1.schemas", "EngineTypeWire")
    assert set(values) == {"elasticsearch", "opensearch"}


def test_resolve_unknown_symbol_raises() -> None:
    import pytest

    with pytest.raises(AttributeError):
        resolve_values("backend.app.api.v1.schemas", "ThisSymbolDoesNotExist")
