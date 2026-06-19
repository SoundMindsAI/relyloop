# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Postgres transaction-scoped advisory locks for worker serialization."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@asynccontextmanager
async def acquire_advisory_xact_lock(
    db: AsyncSession,
    *,
    key: str,
    prefix: str = "",
) -> AsyncIterator[bool]:
    """Try to acquire a Postgres xact-scoped advisory lock keyed by ``key``.

    The lock id is the first 8 bytes of ``blake2b(f"{prefix}{key}")``
    interpreted as a signed 64-bit integer (``pg_try_advisory_xact_lock``
    takes a bigint). ``prefix`` partitions the lock space so distinct
    concerns on the same id never collide — e.g. the orchestrator's replenish
    lock (no prefix) and the digest worker's ``digest:`` lock can both be held
    for the same study at once.

    Transaction-scoped: ``COMMIT`` / ``ROLLBACK`` releases automatically — no
    explicit ``pg_advisory_unlock``. Yields ``True`` when the lock was
    acquired this tick, ``False`` when another holder owns it.
    """
    lock_key = int.from_bytes(
        hashlib.blake2b(f"{prefix}{key}".encode(), digest_size=8).digest(),
        byteorder="big",
        signed=True,
    )
    acquired = (
        await db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": lock_key})
    ).scalar_one()
    yield bool(acquired)
