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
from typing import Any

import httpx

from backend.app.core.logging import get_logger
from backend.app.db import repo
from backend.app.db.session import get_session_factory

logger = get_logger(__name__)

# parents[3]: backend/app/scripts/seed_es.py → backend/app/scripts → backend/app → backend → repo
SAMPLES_PRODUCTS = Path(__file__).resolve().parents[3] / "samples" / "products.json"
INDEX_NAME = "products"
BULK_CHUNK = 500

# After the index is created, _cluster/health?wait_for_status=yellow is the
# explicit synchronization point that blocks until the primary shard is
# active. This is far more reliable than blind retries on the bulk call —
# on cold GHA runners the bulk endpoint's internal 60s shard-availability
# timeout would burn ~60s per attempt without making the shard active any
# faster. PR #297 run 26611895567 exhausted 8 attempts × 62s ≈ 8m45s with
# the shard still INITIALIZING.
#
# The retry loop below remains as a safety net for any residual transient
# error after the health probe returns — keep it small (3 attempts × 2s)
# because the heavy lifting is done by the probe.
BULK_RETRY_ATTEMPTS = 3
BULK_RETRY_SLEEP_SECS = 2.0
RETRYABLE_BULK_ERROR_TYPES = frozenset({"unavailable_shards_exception"})


def _first_bulk_error(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return the first per-item error in a bulk response, or None."""
    return next(
        (
            item["index"].get("error")
            for item in payload.get("items", [])
            if "error" in item.get("index", {})
        ),
        None,
    )


async def _bulk_with_retry(client: httpx.AsyncClient, body: bytes) -> bool:
    """POST a bulk-index body, retrying on transient shard-availability errors.

    Returns True on success, False after exhausting retries or hitting a
    non-retryable error. The caller (``main``) returns 1 on False.

    Retries are limited to ``RETRYABLE_BULK_ERROR_TYPES``; mapping bugs,
    type mismatches, and other deterministic failures bubble up on the
    first attempt so they don't get masked by sleep-and-hope behavior.
    """
    for attempt in range(1, BULK_RETRY_ATTEMPTS + 1):
        bulk_resp = await client.post(
            "/_bulk",
            content=body,
            headers={"Content-Type": "application/x-ndjson"},
        )
        bulk_resp.raise_for_status()
        payload = bulk_resp.json()
        if not payload.get("errors"):
            return True
        first_error = _first_bulk_error(payload)
        first_type = (first_error or {}).get("type")
        if first_type in RETRYABLE_BULK_ERROR_TYPES and attempt < BULK_RETRY_ATTEMPTS:
            logger.warning(
                "seed_es: bulk transient %s, retry %d/%d after %.1fs",
                first_type,
                attempt,
                BULK_RETRY_ATTEMPTS,
                BULK_RETRY_SLEEP_SECS,
            )
            await asyncio.sleep(BULK_RETRY_SLEEP_SECS)
            continue
        logger.error("seed_es: bulk index reported errors; first: %s", first_error)
        return False
    return False


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

        # Block until the primary shard is allocated before bulk-indexing. ES's
        # bulk endpoint silently waits ~60s per request for shard availability
        # and on cold GHA runners the activation can take many minutes;
        # _cluster/health?wait_for_status=yellow explicitly synchronizes with
        # ES's allocation state machine and returns as soon as the primary is
        # active (or after timeout). This is much more reliable than blind
        # retries on the bulk call. The retry loop below is still kept as a
        # safety net for any residual shard-transient errors.
        #
        # See bug_smoke_seed_es_unavailable_shards_race PR #297 run
        # 26611895567 — 8 retries × 62s exhausted without the shard activating;
        # this synchronization point is what was missing.
        # httpx default for the client is 90s; override here so the 10m
        # server-side wait doesn't get killed client-side at 90s.
        health_resp = await client.get(
            f"/_cluster/health/{INDEX_NAME}",
            params={
                "wait_for_status": "yellow",
                "timeout": "10m",
            },
            timeout=620.0,
        )
        # ES returns 408 (with body) when wait_for_status times out, and 200
        # when the condition was met. Both are valid; only treat other status
        # codes (e.g., 404 / 500) as fatal.
        if health_resp.status_code not in (200, 408):
            logger.error(
                "seed_es: cluster health probe for /%s returned %d: %s",
                INDEX_NAME,
                health_resp.status_code,
                health_resp.text[:200],
            )
            return 1
        health = health_resp.json()
        if health.get("timed_out"):
            logger.warning(
                "seed_es: cluster health probe timed out before /%s went yellow; "
                "proceeding to bulk + retries anyway (status=%s, active_shards=%s)",
                INDEX_NAME,
                health.get("status"),
                health.get("active_shards"),
            )
        else:
            logger.info(
                "seed_es: /%s reached %s (active_shards=%s) in %dms",
                INDEX_NAME,
                health.get("status"),
                health.get("active_shards"),
                health.get("number_of_in_flight_fetch", 0),
            )

        # _bulk-index in chunks (ES rejects >100MB single requests; 500 docs stays well under).
        for i in range(0, len(products), BULK_CHUNK):
            chunk = products[i : i + BULK_CHUNK]
            body_lines: list[str] = []
            for product in chunk:
                body_lines.append(
                    json.dumps({"index": {"_index": INDEX_NAME, "_id": product["id"]}})
                )
                body_lines.append(json.dumps(product))
            body = ("\n".join(body_lines) + "\n").encode("utf-8")
            if not await _bulk_with_retry(client, body):
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
