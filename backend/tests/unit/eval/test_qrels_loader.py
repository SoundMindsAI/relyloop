"""Unit tests for :mod:`backend.app.eval.qrels_loader` (feat_llm_judgments
Story 1.6).

Story 1.6 replaced the MVP1 stub with a real ``SELECT`` against the
``judgments`` table. These unit tests stay at the seam between the loader
and the DB — they mock ``AsyncSession.execute`` so no Postgres is required.
DB-backed integration coverage lives in
``backend/tests/integration/test_qrels_loader.py``.

The legacy :class:`JudgmentsTableMissing` symbol is retained for import
compat; we still confirm it can be imported (some callers may have
``except JudgmentsTableMissing`` blocks the migration didn't remove).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from backend.app.eval.qrels_loader import JudgmentsTableMissing, load_qrels


def test_judgments_table_missing_remains_importable() -> None:
    """Legacy symbol still importable so ``infra_optuna_eval`` test contracts
    that pin it as a monkeypatch target don't blow up at import time."""
    assert issubclass(JudgmentsTableMissing, RuntimeError)


async def test_load_qrels_groups_rows_by_query_id() -> None:
    """SELECT returns flat rows; loader groups them into the qrels dict."""
    db = MagicMock()
    db.execute = AsyncMock()
    result = MagicMock()
    result.all.return_value = [
        ("q1", "docA", 3),
        ("q1", "docB", 0),
        ("q2", "docA", 2),
        ("q2", "docC", 1),
    ]
    db.execute.return_value = result

    qrels = await load_qrels(db, "any-judgment-list-id")
    assert qrels == {
        "q1": {"docA": 3, "docB": 0},
        "q2": {"docA": 2, "docC": 1},
    }


async def test_load_qrels_empty_result_returns_empty_dict() -> None:
    """An unknown judgment_list_id yields no rows → ``{}`` (caller handles).

    The MVP1 stub raised :class:`JudgmentsTableMissing`; the real loader
    returns an empty mapping. ``run_trial`` handles the empty case by
    scoring across 0 queries (pytrec_eval no-op) instead of raising.
    """
    db = MagicMock()
    db.execute = AsyncMock()
    result = MagicMock()
    result.all.return_value = []
    db.execute.return_value = result

    qrels = await load_qrels(db, "unknown-id")
    assert qrels == {}


async def test_load_qrels_coerces_rating_to_int() -> None:
    """SmallInteger comes back as int; verify the loader doesn't smuggle
    Decimal/Numeric. The defensive ``int(rating)`` cast guards against ORM
    column-type drift."""
    db = MagicMock()
    db.execute = AsyncMock()
    result = MagicMock()
    result.all.return_value = [("q1", "doc1", 3)]
    db.execute.return_value = result

    qrels = await load_qrels(db, "x")
    assert qrels["q1"]["doc1"] == 3
    assert isinstance(qrels["q1"]["doc1"], int)
