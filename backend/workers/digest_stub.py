"""Idempotent digest-handoff acknowledger (feat_study_lifecycle Phase 2, Story 2.1).

The durable forward marker (a ``proposals`` row with ``status='pending'``)
is created inside :func:`backend.workers.orchestrator._stop` in the SAME
transaction as ``services.study_state.complete_study`` (C3-F1 atomicity
fix). The proposal therefore exists the moment the study is ``completed``,
regardless of whether this Arq job runs.

:func:`generate_digest` is consequently a no-op for the happy path: it
SELECTs the pending proposal for ``study_id``; if present, logs and
returns. If absent (extremely unlikely given the commit-then-enqueue
ordering — only possible if the orchestrator died after commit but before
enqueue, but the proposal row still exists), it INSERTs defensively.

When ``feat_digest_proposal`` lands it REPLACES this stub with a real
``generate_digest`` that:

- Consumes the pre-existing ``proposals WHERE status='pending'`` queue at
  boot time (so studies completed in the gap aren't dropped).
- Generates the digest narrative + populates ``config_diff`` /
  ``metric_delta`` on each pending row.
- Optionally enqueues ``open_pr`` for the GitHub PR worker.
"""

from __future__ import annotations

from typing import Any

import structlog
import uuid_utils
from sqlalchemy import select

from backend.app.db import repo
from backend.app.db.models import Proposal
from backend.app.db.session import get_session_factory

logger = structlog.get_logger(__name__)


async def generate_digest(ctx: dict[str, Any], study_id: str) -> None:
    """Stub digest job — idempotently ensures a pending proposal row exists.

    Safe to retry. Designed to be replaced wholesale by
    ``feat_digest_proposal``.
    """
    del ctx  # ctx not used by the stub
    session_factory = get_session_factory()
    async with session_factory() as db:
        existing = (
            await db.execute(
                select(Proposal)
                .where(Proposal.study_id == study_id)
                .where(Proposal.status == "pending")
                .limit(1)
            )
        ).scalar_one_or_none()
        if existing is not None:
            logger.info(
                "digest deferred — pending proposal already exists",
                event_type="digest_deferred",
                study_id=study_id,
                proposal_id=existing.id,
            )
            return

        # Defensive path — proposal row missing. Should not happen because
        # orchestrator._stop inserts the row in the same tx as complete_study.
        study = await repo.get_study(db, study_id)
        if study is None:
            logger.warning(
                "digest stub: study deleted before generate_digest ran",
                event_type="digest_skipped",
                study_id=study_id,
            )
            return
        await repo.create_proposal(
            db,
            id=str(uuid_utils.uuid7()),
            study_id=study_id,
            study_trial_id=study.best_trial_id,
            cluster_id=study.cluster_id,
            template_id=study.template_id,
            config_diff={},
            metric_delta=None,
            status="pending",
        )
        await db.commit()
        logger.info(
            "digest stub: defensive pending proposal insert",
            event_type="digest_inserted_defensively",
            study_id=study_id,
        )


__all__ = ["generate_digest"]
