"""Idempotent seed script — populates ``local-es:products`` from ``samples/products.json``.

Invocation::

    docker compose exec -T api python -m backend.app.scripts.seed_es

or the higher-level ``make seed-es`` target.

Resolves the cluster via :func:`backend.app.db.repo.get_active_cluster_by_name`
called with ``"local-es"`` — assumes ``make seed-clusters`` (Story 4.1 of
``infra_adapter_elastic``) has already run. DELETE+recreates the ``products``
index every run so judgments stay aligned with the documented sample data
(re-running after a sample-data change cleans up orphans deterministically).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from backend.app.core.logging import get_logger
from backend.app.db import repo
from backend.app.db.session import get_session_factory

logger = get_logger(__name__)

# parents[3]: backend/app/scripts/seed_es.py → backend/app/scripts → backend/app → backend → repo
SAMPLES_PRODUCTS = Path(__file__).resolve().parents[3] / "samples" / "products.json"
INDEX_NAME = "products"
BULK_CHUNK = 500


async def main() -> int:
    """Resolve local-es, DELETE+recreate ``products``, bulk-index from samples."""
    factory = get_session_factory()
    async with factory() as db:
        cluster = await repo.get_active_cluster_by_name(db, "local-es")
    if cluster is None:
        logger.error("seed_es: local-es cluster not registered. Run `make seed-clusters` first.")
        return 1

    products = json.loads(SAMPLES_PRODUCTS.read_text())
    logger.info("seed_es: loaded %d products from %s", len(products), SAMPLES_PRODUCTS)

    # timeout=90 (was 30): ES 9.4.1 single-node on a cold GHA runner can take
    # >30s to respond to the first index-create PUT after `docker compose up
    # --wait` returns. Observed in PR #291's 6th + 7th smoke runs after the
    # fast stack-up (compose-up went from 10min → 21s, eliminating the
    # ambient ES warmup time that previously masked this). The compose
    # healthcheck waits for `_cluster/health?wait_for_status=yellow` which
    # passes early on single-node ES (no shards to wait on), so ES is
    # "healthy" but its write path needs more warmup. 90s gives headroom
    # without making real failure modes invisible.
    async with httpx.AsyncClient(base_url=cluster.base_url, timeout=90.0) as client:
        # DELETE existing index (idempotent — 404 is fine, that just means it didn't exist).
        delete_resp = await client.delete(f"/{INDEX_NAME}")
        if delete_resp.status_code not in (200, 404):
            logger.error(
                "seed_es: DELETE /%s returned %d: %s",
                INDEX_NAME,
                delete_resp.status_code,
                delete_resp.text[:200],
            )
            return 1

        # Create with mapping derived from the products schema.
        #
        # number_of_replicas=0 is required for single-node ES (local dev +
        # CI). The default (1) tries to allocate a replica that can never
        # bind on a one-node cluster, leaving the primary itself in an
        # INITIALIZING → STARTED race that surfaces as an
        # `unavailable_shards_exception` on the immediately-following
        # bulk-index. Visible in PR #291 CI run after the faster stack-up
        # (~3min vs ~10min) stopped masking the race with implicit warmup
        # time. See chore_ci_perf_buildx_artifact_image_cache_xdist/idea.md.
        create_resp = await client.put(
            f"/{INDEX_NAME}",
            json={
                "settings": {"number_of_replicas": 0},
                "mappings": {
                    "properties": {
                        "title": {"type": "text"},
                        "description": {"type": "text"},
                        "brand": {"type": "keyword"},
                        "color": {"type": "keyword"},
                        "bullet_points": {"type": "text"},
                    }
                },
            },
        )
        create_resp.raise_for_status()

        # _bulk-index in chunks (ES rejects >100MB single requests; 500 docs stays well under).
        for i in range(0, len(products), BULK_CHUNK):
            chunk = products[i : i + BULK_CHUNK]
            body_lines: list[str] = []
            for product in chunk:
                body_lines.append(
                    json.dumps({"index": {"_index": INDEX_NAME, "_id": product["id"]}})
                )
                body_lines.append(json.dumps(product))
            bulk_resp = await client.post(
                "/_bulk",
                content=("\n".join(body_lines) + "\n").encode("utf-8"),
                headers={"Content-Type": "application/x-ndjson"},
            )
            bulk_resp.raise_for_status()
            payload = bulk_resp.json()
            if payload.get("errors"):
                first_error = next(
                    (
                        item["index"].get("error")
                        for item in payload["items"]
                        if "error" in item.get("index", {})
                    ),
                    None,
                )
                logger.error("seed_es: bulk index reported errors; first: %s", first_error)
                return 1

        # Refresh so the doc count is observable immediately.
        await client.post(f"/{INDEX_NAME}/_refresh")

    logger.info(
        "seed_es: indexed %d products into %s/%s",
        len(products),
        cluster.base_url,
        INDEX_NAME,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
