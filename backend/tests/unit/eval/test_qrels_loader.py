"""Unit tests for backend.app.eval.qrels_loader (MVP1 stub).

Confirms the stub raises ``JudgmentsTableMissing`` with a diagnosable
message. The real implementation lands with ``feat_llm_judgments``; until
then integration tests monkeypatch ``load_qrels``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.app.eval.qrels_loader import JudgmentsTableMissing, load_qrels


async def test_load_qrels_raises_judgments_table_missing():
    """MVP1 stub always raises ``JudgmentsTableMissing``."""
    db = AsyncMock()  # session shape not exercised by the stub
    with pytest.raises(JudgmentsTableMissing):
        await load_qrels(db, "any-judgment-list-id")


def test_judgments_table_missing_inherits_from_runtime_error():
    """The exception is a RuntimeError subclass so generic ``except`` paths catch it."""
    assert issubclass(JudgmentsTableMissing, RuntimeError)


async def test_load_qrels_exception_message_contains_judgment_list_id():
    """Diagnosability: traceback should include the judgment_list_id passed in."""
    db = AsyncMock()
    judgment_list_id = "01HXYZ-12345"
    with pytest.raises(JudgmentsTableMissing) as excinfo:
        await load_qrels(db, judgment_list_id)
    assert judgment_list_id in str(excinfo.value)


async def test_load_qrels_exception_message_cites_feat_llm_judgments():
    """The message points the operator at the owning feature for the swap-in."""
    db = AsyncMock()
    with pytest.raises(JudgmentsTableMissing) as excinfo:
        await load_qrels(db, "any")
    assert "feat_llm_judgments" in str(excinfo.value)
