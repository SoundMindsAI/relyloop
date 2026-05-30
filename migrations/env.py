# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Alembic env (infra_foundation Story 2.2).

Reads ``DATABASE_URL`` from RelyLoop's ``Settings`` (which resolves
``DATABASE_URL_FILE`` per FR-3) at runtime — never from ``alembic.ini``.

Supports both online (DB-connected) and offline (--sql) modes, async via
``asyncio.run`` per Alembic's documented async pattern.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Import Base so target_metadata picks up every ORM model declared by features.
from backend.app.core.settings import get_settings

# Force-load every ORM model module so its classes register with Base.metadata
# before --autogenerate runs. The noqa is intentional — this is a side-effect
# import; the symbols are not referenced by name in this module.
from backend.app.db import models  # noqa: F401
from backend.app.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the runtime DATABASE_URL into Alembic's config dict (env-var-style)
# so SQLAlchemy uses it for online mode + autogenerate.
config.set_main_option("sqlalchemy.url", get_settings().database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout, no DB connect)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Synchronous migration runner; called via run_sync from async wrapper."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode against the configured async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
