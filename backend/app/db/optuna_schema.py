# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Optuna RDB schema initializer (infra_foundation Story 2.2).

Optuna's ``RDBStorage`` (used by ``infra_optuna_eval`` and ``feat_study_lifecycle``)
points at the same Postgres as RelyLoop's app state but uses an isolated schema
namespace ``optuna.*`` to avoid colliding with RelyLoop's ``public.*`` tables.

This module provides ``init_optuna_schema()`` — invoked by ``make migrate`` after
``alembic upgrade head`` — which idempotently ensures the ``optuna`` schema
exists. Optuna's ``create_study(storage=...)`` then creates its tables on first
use (no-op on subsequent runs).

In MVP1 this prepares the schema namespace; ``infra_optuna_eval``'s worker
boot triggers Optuna's lazy table creation on first ``RDBStorage`` use.
``WorkerSettings.on_startup`` constructs the ``RDBStorage`` once per worker
(spec FR-1); the schema must already exist at that point.
"""

import logging
from urllib.parse import urlparse

from sqlalchemy import create_engine, text

logger = logging.getLogger(__name__)


def init_optuna_schema(database_url: str) -> None:
    """Create the ``optuna`` schema in Postgres if missing. Idempotent.

    Args:
        database_url: SQLAlchemy URL for the same Postgres that RelyLoop uses.
            Read from ``Settings.database_url`` at the call site.

    Notes:
        - Uses a synchronous engine (one-shot DDL; no need for async overhead).
        - ``CREATE SCHEMA IF NOT EXISTS`` is the canonical idempotent form.
        - Optuna's tables themselves are created by Optuna's own ``RDBStorage``
          on first ``create_study()`` call — not by this function.
    """
    # Convert async URL (postgresql+asyncpg://) to sync (postgresql+psycopg2://
    # or vanilla postgresql://) for the one-shot DDL connection. If the URL
    # already lacks a + prefix, leave it alone.
    sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(sync_url)

    engine = create_engine(sync_url, future=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE SCHEMA IF NOT EXISTS optuna"))
            conn.commit()
        logger.info("optuna schema ensured at %s/%s", parsed.hostname, parsed.path.lstrip("/"))
    finally:
        engine.dispose()


if __name__ == "__main__":
    # Allow `python -m backend.app.db.optuna_schema` invocation from the
    # `make migrate` Makefile target.
    from backend.app.core.settings import get_settings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    init_optuna_schema(get_settings().database_url)
