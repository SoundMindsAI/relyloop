# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Idempotent seed of ``local-es`` and ``local-opensearch`` cluster rows (Story 4.1).

Operator convenience for first-run setup: registers two cluster rows
pointing at the local Compose containers using the credentials mounted in
``cluster_credentials.yaml``. Re-running is safe — existing rows trip
``ClusterNameTaken`` which we treat as success.

Run via::

    docker compose exec -T api python -m backend.app.scripts.seed_clusters

or the higher-level ``make seed-clusters`` target.

The mounted credentials YAML must contain ``local-es`` and ``local-opensearch``
keys; ``scripts/install.sh`` writes a synthesized default the first time
``make up`` runs.
"""

from __future__ import annotations

import asyncio

from redis.asyncio import Redis

from backend.app.core.settings import get_settings
from backend.app.db.session import get_session_factory
from backend.app.services.cluster import (
    ClusterNameTaken,
    ClusterUnreachable,
    register_cluster,
)

LOCAL_ES = dict(
    name="local-es",
    engine_type="elasticsearch",
    environment="dev",
    base_url="http://elasticsearch:9200",
    auth_kind="es_basic",
    credentials_ref="local-es",
    engine_config=None,
    notes="Local Elasticsearch container from infra_foundation Compose stack.",
)

LOCAL_OS = dict(
    name="local-opensearch",
    engine_type="opensearch",
    environment="dev",
    base_url="http://opensearch:9200",
    auth_kind="opensearch_basic",
    credentials_ref="local-opensearch",
    engine_config=None,
    notes="Local OpenSearch container from infra_foundation Compose stack.",
)

# infra_adapter_solr Story A10: register the local Apache Solr container too.
# Requires the bootstrap-security.sh script to have generated the admin
# credentials AND the seed_solr_products.py script to have created the
# `products` collection. When the credentials_ref isn't present in
# cluster_credentials.yaml the registration fails — captured as a single
# best-effort entry.
LOCAL_SOLR = dict(
    name="local-solr",
    engine_type="solr",
    environment="dev",
    base_url="http://solr:8983",
    auth_kind="solr_basic",
    credentials_ref="local-solr",
    engine_config=None,
    notes="Local Apache Solr container from infra_adapter_solr Compose stack.",
)


async def main() -> int:
    """Register both local clusters; return process exit code."""
    settings = get_settings()
    redis: Redis = Redis.from_url(settings.redis_url, decode_responses=False)
    factory = get_session_factory()
    failures = 0
    try:
        async with factory() as db:
            for spec in (LOCAL_ES, LOCAL_OS, LOCAL_SOLR):
                name = spec["name"]
                try:
                    await register_cluster(db, redis, **spec)  # type: ignore[arg-type]
                    print(f"Registered {name}")
                except ClusterNameTaken:
                    print(f"{name} already registered (idempotent skip)")
                except ClusterUnreachable as exc:
                    failures += 1
                    print(f"FAILED to register {name}: {exc}")
    finally:
        await redis.aclose()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
