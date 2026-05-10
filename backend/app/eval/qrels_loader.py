"""Qrels loader interface (infra_optuna_eval Story 2.2).

Single import point for the ``run_trial`` worker to fetch judgment ratings
(qrels) for scoring. In MVP1 this is a typed stub that raises
``JudgmentsTableMissing`` because the ``judgments`` child table is owned by
``feat_llm_judgments`` (per ``docs/01_architecture/data-model.md`` §"judgment_lists
and judgments") and has not shipped yet.

Why a stub, not a real ``SELECT``:

* Spec §9 explicitly forbids new tables in this feature.
* Spec §3 In/Out of scope: judgment generation is owned by
  ``feat_llm_judgments``; this feature does NOT generate or persist
  judgments.
* The only production callers of ``run_trial`` are
  ``feat_study_lifecycle`` Phase 2's orchestrator and (indirectly)
  ``feat_llm_judgments``'s runner — both deferred. There is no MVP1
  dispatch path that would hit this stub in production. Premature dispatch
  (e.g., an operator manually enqueueing ``run_trial`` against ``arq``)
  fails loud with a clear typed exception rather than a confusing
  ``UndefinedTable`` SQL error.

When ``feat_llm_judgments`` lands, that feature's plan replaces this
stub with a real ``SELECT`` against the ``judgments`` table::

    SELECT query_id, doc_id, rating
    FROM judgments
    WHERE judgment_list_id = :judgment_list_id

grouped by ``query_id``. Integration tests for THIS feature monkeypatch
``load_qrels`` to inject hand-built qrels (per spec AC-4).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.eval.scoring import Qrels


class JudgmentsTableMissing(RuntimeError):
    """Raised in MVP1 when ``run_trial`` attempts to load qrels.

    The ``judgments`` table is owned by ``feat_llm_judgments`` (per
    ``docs/01_architecture/data-model.md`` §"judgment_lists and judgments")
    and has not shipped yet. When ``feat_llm_judgments`` lands, ``load_qrels``
    is replaced with a real ``SELECT`` and this exception class becomes
    unreachable.

    Integration tests in ``backend/tests/integration/test_run_trial*.py``
    monkeypatch ``load_qrels`` to return hand-built qrels (per spec AC-4
    "hand-built judgment list"), so the stub does not block test coverage
    of the ``run_trial`` runtime contract.
    """


async def load_qrels(db: AsyncSession, judgment_list_id: str) -> Qrels:
    """Load qrels for a judgment list.

    MVP1: always raises ``JudgmentsTableMissing``. See module docstring for
    the rationale. When ``feat_llm_judgments`` lands, the implementation is:

        stmt = select(Judgment.query_id, Judgment.doc_id, Judgment.rating).where(
            Judgment.judgment_list_id == judgment_list_id
        )
        # GROUP BY query_id into {query_id: {doc_id: rating}}

    Args:
        db: Async SQLAlchemy session. Unused in the MVP1 stub; signature
            reserved for the real implementation.
        judgment_list_id: UUIDv7 string referencing the ``judgment_lists``
            parent row.

    Raises:
        JudgmentsTableMissing: always, in MVP1.
    """
    raise JudgmentsTableMissing(
        f"judgments table not yet shipped (feat_llm_judgments owns it); "
        f"judgment_list_id={judgment_list_id!r}. Integration tests must "
        f"monkeypatch load_qrels with hand-built qrels."
    )
