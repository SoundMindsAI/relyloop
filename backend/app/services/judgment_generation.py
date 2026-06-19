# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Judgment-generation service layer.

Composition logic for turning a ``judgment_lists`` row into persisted
``judgments`` — shared by the LLM judge worker (``workers.judgments``) and
the UBI worker (``workers.judgments_ubi``). The workers own orchestration
(load the row, build clients, loop queries, flip terminal status, clean up);
this module owns the per-list/per-query composition of repos + adapter + LLM
+ budget so that logic lives in the service layer rather than the worker.
"""

from __future__ import annotations

from typing import Any

from backend.app.db import repo


async def fail_judgment_list(db: Any, judgment_list_id: str, failed_reason: str) -> None:
    """Flip a judgment list to ``status='failed'`` with a structured reason.

    Commits in the caller's session. Shared by both judgment workers — the
    terminal-failure transition is identical regardless of which generation
    path (LLM or UBI) hit the failure.
    """
    await repo.update_judgment_list_status(
        db, judgment_list_id, status="failed", failed_reason=failed_reason
    )
    await db.commit()
