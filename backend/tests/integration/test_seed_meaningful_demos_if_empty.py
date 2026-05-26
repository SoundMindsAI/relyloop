"""Integration test for the auto-seed-on-empty SQL contract.

Pins `scripts/seed_meaningful_demos._COUNT_LIVE_CLUSTERS_SQL` so a single
E2E test that soft-deletes its cluster fixtures cannot permanently
disable the auto-seed-on-empty path at `scripts/install.sh:95`. The bug
(`bug_seed_demo_if_empty_counts_soft_deleted`) was: the SQL was
`SELECT COUNT(*) FROM clusters` with no `WHERE deleted_at IS NULL`
filter, so soft-deleted tombstones counted as "exists" and the
`--if-empty` branch false-skipped.

All DB writes run inside a transaction that's rolled back at the end —
so a local-dev run cannot wipe operator data even if the test DB is
shared with a working stack (per GPT-5.5 round 1 finding on PR #268).

Skips when Postgres isn't reachable (matches the pattern in
`test_seed_clusters_idempotent.py`).
"""

from __future__ import annotations

import os
import socket
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.app.core.settings import get_settings
from scripts.seed_meaningful_demos import _COUNT_LIVE_CLUSTERS_SQL


def _postgres_reachable() -> bool:
    if not os.environ.get("DATABASE_URL_FILE") or not os.environ.get("POSTGRES_PASSWORD_FILE"):
        return False
    try:
        url = get_settings().database_url
    except Exception:  # noqa: BLE001
        return False
    parsed = urlparse(url)
    pg_host = parsed.hostname or "localhost"
    pg_port = parsed.port or 5432
    try:
        with socket.create_connection((pg_host, pg_port), timeout=1.0):
            return True
    except (TimeoutError, OSError):
        return False


pytestmark = pytest.mark.skipif(
    not _postgres_reachable(),
    reason="Postgres not reachable — see docs/03_runbooks/local-dev.md.",
)


def _insert_cluster_sql(*, soft_deleted: bool) -> tuple[str, dict[str, object]]:
    """Build INSERT SQL + bound params for one cluster row.

    ``soft_deleted=True`` populates ``deleted_at``; otherwise leaves it
    NULL. The unique fixture ID + ts-suffixed name make repeated inserts
    in the same transaction non-colliding.
    """
    now = datetime.now(UTC)
    cluster_id = str(uuid.uuid4())
    params: dict[str, object] = {
        "id": cluster_id,
        "name": f"sd-fixture-{cluster_id[:8]}",
        "created_at": now,
        "updated_at": now,
        "deleted_at": now if soft_deleted else None,
    }
    sql = (
        "INSERT INTO clusters "
        "(id, name, engine_type, environment, base_url, auth_kind, "
        "credentials_ref, created_at, updated_at, deleted_at) "
        "VALUES (:id, :name, 'elasticsearch', 'dev', "
        "'http://stub:9200', 'es_basic', 'stub-ref', "
        ":created_at, :updated_at, :deleted_at)"
    )
    return sql, params


@pytest.mark.integration
async def test_count_live_clusters_sql_excludes_soft_deleted_row() -> None:
    """Inserting one soft-deleted cluster row must NOT increment the live count.

    Pre-fix SQL (`SELECT COUNT(*) FROM clusters;`) would increment by 1
    (the soft-deleted row counts), causing `--if-empty` to false-skip.
    Post-fix SQL (with `WHERE deleted_at IS NULL`) increments by 0,
    allowing the auto-seed to fire correctly.

    Snapshots the baseline live-count before insert so the test is
    isolated from existing operator data (e.g. 4 demo clusters from
    `make seed-demo`). Wraps in transaction rollback so the test
    fixture row never persists past the test run.
    """
    engine = create_async_engine(get_settings().database_url, future=True)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                # Snapshot baseline live count BEFORE any fixture inserts.
                baseline = (await conn.execute(text(_COUNT_LIVE_CLUSTERS_SQL))).scalar_one()

                # Seed one soft-deleted cluster row inside the transaction.
                sql, params = _insert_cluster_sql(soft_deleted=True)
                await conn.execute(text(sql), params)

                # Read back the constant's SQL on the same connection.
                after = (await conn.execute(text(_COUNT_LIVE_CLUSTERS_SQL))).scalar_one()

                delta = after - baseline
                assert delta == 0, (
                    f"_COUNT_LIVE_CLUSTERS_SQL went from {baseline} → {after} "
                    f"(delta={delta}) after inserting a SOFT-DELETED cluster "
                    "row. Expected delta=0 (soft-deleted rows must not count). "
                    "The --if-empty auto-seed would false-skip on every "
                    "`make up` after any E2E test that soft-deletes its "
                    "cluster fixtures. See bug_seed_demo_if_empty_counts_soft_deleted."
                )
            finally:
                # Rollback discards fixture rows; no commit ever happens →
                # operator data preserved even if the test DB is shared with
                # a working stack.
                await trans.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_count_live_clusters_sql_counts_live_excludes_deleted_mixed() -> None:
    """One live + one soft-deleted cluster → live count goes UP by 1, not 2.

    Pins BOTH halves of the contract:
    - excludes deleted rows (the deleted row contributes 0 to the delta)
    - counts live rows (the live row contributes 1 to the delta)

    Catches the over-restrictive failure mode where someone "fixes" the
    SQL into something like `WHERE deleted_at IS NOT NULL` (which would
    push the delta to 0 — passing the negative-only test above but breaking
    the auto-seed on a populated stack).

    Per GPT-5.5 round 1 finding #2 on PR #268. Same baseline-snapshot +
    transaction-rollback pattern as the negative test above.
    """
    engine = create_async_engine(get_settings().database_url, future=True)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                baseline = (await conn.execute(text(_COUNT_LIVE_CLUSTERS_SQL))).scalar_one()

                # Seed one LIVE + one SOFT-DELETED row.
                live_sql, live_params = _insert_cluster_sql(soft_deleted=False)
                await conn.execute(text(live_sql), live_params)
                deleted_sql, deleted_params = _insert_cluster_sql(soft_deleted=True)
                await conn.execute(text(deleted_sql), deleted_params)

                after = (await conn.execute(text(_COUNT_LIVE_CLUSTERS_SQL))).scalar_one()

                delta = after - baseline
                assert delta == 1, (
                    f"_COUNT_LIVE_CLUSTERS_SQL went from {baseline} → {after} "
                    f"(delta={delta}) after inserting 1 live + 1 soft-deleted "
                    "cluster row. Expected delta=1 (live row counts, deleted "
                    "row doesn't). The SQL must EXCLUDE soft-deleted rows AND "
                    "COUNT live rows — both halves of the contract."
                )
            finally:
                await trans.rollback()
    finally:
        await engine.dispose()
