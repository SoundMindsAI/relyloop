# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Digest repository (feat_digest_proposal Story 1.2).

Two functions:

* :func:`create_digest` — stage a new ``Digest`` row; caller commits.
* :func:`get_digest_for_study` — fetch by ``study_id`` (UNIQUE), returns
  ``None`` if no digest has been written yet. Consumed by the FR-3 fetch
  endpoint and by the worker's pre-LLM idempotency guard (cycle-1 F6).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.models import Digest


async def create_digest(db: AsyncSession, **fields: object) -> Digest:
    """Stage a new ``Digest`` row. Caller commits."""
    digest = Digest(**fields)
    db.add(digest)
    await db.flush()
    await db.refresh(digest)
    return digest


async def get_digest_for_study(db: AsyncSession, study_id: str) -> Digest | None:
    """Fetch the digest for a study (UNIQUE on ``study_id``); None if absent.

    Used by:
    - ``GET /api/v1/studies/{id}/digest`` (FR-3) — 404 DIGEST_NOT_READY on None.
    - ``backend/workers/digest.py:generate_digest`` — pre-LLM idempotency
      guard (cycle-1 F6) so a duplicate enqueue cannot pay for a second
      LLM call before the UNIQUE fires.
    """
    stmt = select(Digest).where(Digest.study_id == study_id)
    return (await db.execute(stmt)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# chore_e2e_test_rows_isolation Story 1.1 — hard-delete for test-only cleanup
# ---------------------------------------------------------------------------


async def hard_delete_digest(db: AsyncSession, digest_id: str) -> bool:
    """Hard-delete the digest row.

    Returns ``True`` if a row was deleted, ``False`` if no row existed.
    Caller commits. Used ONLY by the test-only `DELETE /api/v1/_test/
    digests/{id}` endpoint per ``chore_e2e_test_rows_isolation`` FR-2.
    Digests have no FK children. The 1:1 UNIQUE constraint with studies
    means the digest must be deleted BEFORE its parent study (caller's
    responsibility — the cleanup script's drain order enforces this).
    """
    existing = await db.get(Digest, digest_id)
    if existing is None:
        return False
    await db.delete(existing)
    await db.flush()
    return True
