"""Qrels loader (feat_llm_judgments Story 1.6).

Real ``SELECT`` against the ``judgments`` table (introduced by the
``0004_judgments`` migration). Returns ``Qrels`` keyed by ``query_id``,
suitable for direct consumption by :func:`backend.app.eval.scoring.score`.

The loader is the only public surface — :func:`load_qrels`. The legacy
:class:`JudgmentsTableMissing` exception class is retained as a no-op
import compat shim for any code still expecting it (e.g.,
``infra_optuna_eval``'s integration-test monkeypatch contract that imports
the symbol). New code never raises it.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Judgment
from backend.app.eval.scoring import Qrels


class JudgmentsTableMissing(RuntimeError):
    """Legacy symbol retained for backward import compatibility.

    The ``infra_optuna_eval`` integration tests imported this class to
    monkeypatch the MVP1 stub. The class itself is now never raised by
    :func:`load_qrels` — the real ``SELECT`` returns ``{}`` for an
    unknown ``judgment_list_id`` (the caller decides how to handle "no
    qrels found", typically "score=0 over no queries").
    """


async def load_qrels(db: AsyncSession, judgment_list_id: str) -> Qrels:
    """Return qrels for a judgment list, grouped by query.

    Args:
        db: Async SQLAlchemy session.
        judgment_list_id: UUIDv7 string referencing ``judgment_lists.id``.

    Returns:
        ``{query_id: {doc_id: rating}}``. An unknown ``judgment_list_id``
        (no rows) returns an empty dict — callers must handle the empty
        case (``run_trial`` does so by scoring 0 across 0 queries, which
        ``pytrec_eval`` treats as a no-op).

    The loader takes both ``llm`` and ``human`` rated rows. A human-override
    UPSERT replaces the LLM row in place (per the UNIQUE constraint), so
    there is at most one row per ``(query_id, doc_id)`` and the loader does
    not need to disambiguate.
    """
    stmt = select(Judgment.query_id, Judgment.doc_id, Judgment.rating).where(
        Judgment.judgment_list_id == judgment_list_id
    )
    rows = (await db.execute(stmt)).all()
    qrels: Qrels = {}
    for query_id, doc_id, rating in rows:
        qrels.setdefault(str(query_id), {})[str(doc_id)] = int(rating)
    return qrels
