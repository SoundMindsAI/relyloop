# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for ``generate_judgments_from_ubi`` helpers
(feat_ubi_judgments Story 3.3 / FR-5).

Full end-to-end DB-backed worker tests live at
``backend/tests/integration/test_generate_judgments_from_ubi.py`` (covers
the clean loop / hybrid / resume-skip / ambiguous-skip / race-fallback
paths against a stub adapter + the test Postgres). This unit-layer
suite covers the pure logic that doesn't need a DB.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.workers.judgments_ubi import _apply_mapping_strategy


@dataclass
class _FakeQueryRow:
    id: str
    query_text: str
    created_at: datetime


def _row(id_: str, text: str, created_at: datetime | None = None) -> _FakeQueryRow:
    return _FakeQueryRow(
        id=id_,
        query_text=text,
        created_at=created_at or datetime(2026, 5, 1, tzinfo=UTC),
    )


# ----------------------------------------------------------------------------
# _apply_mapping_strategy
# ----------------------------------------------------------------------------


class TestUniqueMatch:
    def test_one_to_one_match_resolves_cleanly(self) -> None:
        ubi_map = {"ubi-1": "red shoes", "ubi-2": "blue shirt"}
        rows = [_row("q-red", "red shoes"), _row("q-blue", "blue shirt")]
        mapping, ambiguous = _apply_mapping_strategy(
            ubi_query_to_user_query=ubi_map,
            query_set_rows=rows,
            mapping_strategy="reject",
        )
        assert mapping == {"ubi-1": "q-red", "ubi-2": "q-blue"}
        assert ambiguous == 0

    def test_unmatched_ubi_query_silently_dropped(self) -> None:
        """UBI captured a query not in the operator's query set — drop, not skip."""
        ubi_map = {"ubi-1": "red shoes", "ubi-orphan": "purple hat"}
        rows = [_row("q-red", "red shoes")]
        mapping, ambiguous = _apply_mapping_strategy(
            ubi_query_to_user_query=ubi_map,
            query_set_rows=rows,
            mapping_strategy="reject",
        )
        assert mapping == {"ubi-1": "q-red"}
        # No-match is NOT counted as ambiguous (FR-5 contract).
        assert ambiguous == 0


class TestAmbiguous:
    def test_reject_strategy_skips_and_counts_ambiguous(self) -> None:
        ubi_map = {"ubi-1": "shoes"}
        rows = [
            _row("q-a", "shoes", datetime(2026, 5, 1, tzinfo=UTC)),
            _row("q-b", "shoes", datetime(2026, 5, 5, tzinfo=UTC)),
        ]
        mapping, ambiguous = _apply_mapping_strategy(
            ubi_query_to_user_query=ubi_map,
            query_set_rows=rows,
            mapping_strategy="reject",
        )
        assert mapping == {}  # both candidates skipped
        assert ambiguous == 1

    def test_first_match_strategy_picks_lowest_id(self) -> None:
        ubi_map = {"ubi-1": "shoes"}
        rows = [
            _row("q-b", "shoes", datetime(2026, 5, 5, tzinfo=UTC)),
            _row("q-a", "shoes", datetime(2026, 5, 1, tzinfo=UTC)),
        ]
        mapping, ambiguous = _apply_mapping_strategy(
            ubi_query_to_user_query=ubi_map,
            query_set_rows=rows,
            mapping_strategy="first_match",
        )
        assert mapping == {"ubi-1": "q-a"}  # lexicographic sort on id
        assert ambiguous == 0

    def test_most_recent_strategy_picks_highest_created_at(self) -> None:
        ubi_map = {"ubi-1": "shoes"}
        rows = [
            _row("q-a", "shoes", datetime(2026, 5, 1, tzinfo=UTC)),
            _row("q-b", "shoes", datetime(2026, 5, 20, tzinfo=UTC)),
        ]
        mapping, ambiguous = _apply_mapping_strategy(
            ubi_query_to_user_query=ubi_map,
            query_set_rows=rows,
            mapping_strategy="most_recent",
        )
        assert mapping == {"ubi-1": "q-b"}
        assert ambiguous == 0

    def test_unknown_strategy_treated_as_reject(self) -> None:
        ubi_map = {"ubi-1": "shoes"}
        rows = [_row("q-a", "shoes"), _row("q-b", "shoes")]
        mapping, ambiguous = _apply_mapping_strategy(
            ubi_query_to_user_query=ubi_map,
            query_set_rows=rows,
            mapping_strategy="unknown",  # defensive — wire allowlist filters earlier
        )
        assert mapping == {}
        assert ambiguous == 1


class TestEmpty:
    def test_empty_ubi_map_returns_empty(self) -> None:
        mapping, ambiguous = _apply_mapping_strategy(
            ubi_query_to_user_query={},
            query_set_rows=[_row("q-a", "shoes")],
            mapping_strategy="reject",
        )
        assert mapping == {}
        assert ambiguous == 0

    def test_empty_query_set_returns_empty(self) -> None:
        mapping, ambiguous = _apply_mapping_strategy(
            ubi_query_to_user_query={"ubi-1": "shoes"},
            query_set_rows=[],
            mapping_strategy="reject",
        )
        assert mapping == {}
        assert ambiguous == 0


# ----------------------------------------------------------------------------
# Module surface sanity (worker entry point + helpers importable)
# ----------------------------------------------------------------------------


def test_worker_exports() -> None:
    from backend.workers import judgments_ubi

    assert callable(judgments_ubi.generate_judgments_from_ubi)
    assert callable(judgments_ubi._apply_mapping_strategy)


def test_hybrid_rate_callback_factory_lives_in_service() -> None:
    """The hybrid LLM-fill callback factory moved to the service layer."""
    from backend.app.services.judgment_generation import make_hybrid_llm_rate_callback

    assert callable(make_hybrid_llm_rate_callback)


def test_worker_registered_in_worker_settings() -> None:
    """The boot-time WorkerSettings.functions list MUST include the UBI job
    so Arq dispatches it to the worker process (FR-5 step 3).

    Source-scan rather than import: WorkerSettings construction calls
    ``get_settings()`` (via the cron_jobs cadence resolvers) which
    requires the secret-file env vars — out of scope for a unit test.
    The source-scan asserts the registration line exists; the actual
    Arq dispatch is covered by the integration smoke at first stack
    boot.
    """
    from pathlib import Path

    source = Path("backend/workers/all.py").read_text()
    assert "func(generate_judgments_from_ubi" in source, (
        "WorkerSettings.functions missing generate_judgments_from_ubi registration"
    )


def test_worker_no_direct_openai_construction_outside_callback_factory() -> None:
    """CLAUDE.md Absolute Rule #3: only the callback factory may construct AsyncOpenAI."""
    import ast
    from pathlib import Path

    source = Path("backend/workers/judgments_ubi.py").read_text()
    tree = ast.parse(source)
    # Walk top-level definitions; the only AsyncOpenAI(...) call we permit is
    # inside _build_converter (which constructs the client and passes it to
    # the service-layer hybrid callback factory). Other code paths must NOT
    # instantiate the client.
    forbidden_paths: list[str] = []

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self._current_fn: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._current_fn.append(node.name)
            self.generic_visit(node)
            self._current_fn.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self._current_fn.append(node.name)
            self.generic_visit(node)
            self._current_fn.pop()

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            if isinstance(func, ast.Name) and func.id == "AsyncOpenAI":
                if not self._current_fn or self._current_fn[-1] not in {
                    "_build_converter",
                }:
                    where = ".".join(self._current_fn) or "<module>"
                    forbidden_paths.append(where)
            self.generic_visit(node)

    _Visitor().visit(tree)
    assert forbidden_paths == [], (
        f"AsyncOpenAI(...) instantiated outside the callback factory: {forbidden_paths}"
    )


_ = Any  # silence unused-import for the ast type
