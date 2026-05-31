# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""UBI readiness classifier (feat_ubi_judgments Story 2.2 / FR-7).

Classifies a ``(cluster, query_set, target)`` tuple on the UBI rung
ladder:

* ``rung_0`` — ``ubi_queries`` index does not exist (UBI plugin not
  installed). Both the dispatcher preflight U-C and the readiness
  endpoint return this label so the UI can surface the on-ramp nudge.
* ``rung_1`` — ``ubi_queries`` exists but the (cluster, target) window
  has too few events for meaningful per-pair signal
  (``event_count < min_impressions_threshold``).
* ``rung_2`` — ``event_count >= min_impressions_threshold`` AND
  ``< 5 * min_impressions_threshold`` (default 100…500).
* ``rung_3`` — ``event_count >= 5 * min_impressions_threshold``
  (default ≥500). The UI uses this rung to default the dialog
  method-picker to a pure-UBI converter.

Caches the result in Redis for 60 s per scope tuple (the dispatcher
preflight U-C and the ``GET /clusters/{id}/ubi-readiness`` endpoint
share the same cache key shape; back-to-back calls during dialog open
+ submit hit the cache, not the cluster).

**Why event-count thresholds (no covered-pairs-pct / head-covered):**
the SearchAdapter Protocol exposes ``search_batch`` (hits only), no
``_count`` endpoint, and Story 2.1's DoD locked "no new adapter
method." A pair-coverage computation would require either a new
adapter method or a multi-call scan that pushes the readiness probe
past its 2-second budget (spec §6). The simplification: event-count
thresholds are coarser but probe-cheap (one ``search_batch`` call
with ``size=cap, _source=False``), surface the same rung_0/1/2/3
ladder the UI consumes, and never lie — they just don't compute the
optional ``covered_pairs_pct`` / ``head_covered`` fields. Future
``infra_adapter_count_method`` work can re-introduce exact pair
counts if operator feedback asks for it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from redis.asyncio import Redis

from backend.app.adapters.protocol import NativeQuery, SearchAdapter
from backend.app.services.ubi_errors import UbiNotEnabledError
from backend.app.services.ubi_reader import (
    UBI_EVENTS_INDEX,
    UbiReader,
    _build_solr_ubi_body,
)

logger = structlog.get_logger(__name__)

UbiReadinessRung = Literal["rung_0", "rung_1", "rung_2", "rung_3"]

DEFAULT_MIN_IMPRESSIONS_THRESHOLD = 100
"""Default rung_1 → rung_2 cutoff. Mirrors the dispatcher's U-D2 default."""

DEFAULT_READINESS_WINDOW_DAYS = 30
"""Default trailing window for the readiness probe (FR-7)."""

CACHE_TTL_SECONDS = 60
"""Plan §"Key interfaces" — 60 s per scope tuple."""


@dataclass(frozen=True, slots=True)
class UbiReadiness:
    """One readiness snapshot for a ``(cluster, query_set, target)`` tuple.

    ``covered_pairs_pct`` and ``head_covered`` stay ``None`` in MVP2 —
    see the module docstring rationale (Protocol surface doesn't expose
    an exact-count endpoint; event-count thresholds drive the rung).
    """

    rung: UbiReadinessRung
    covered_pairs_pct: float | None
    head_covered: bool | None
    checked_at: datetime

    def to_cache_payload(self) -> str:
        """Serialize for the 60 s Redis cache. ``checked_at`` → ISO-8601."""
        payload: dict[str, Any] = asdict(self)
        payload["checked_at"] = self.checked_at.isoformat()
        return json.dumps(payload)

    @classmethod
    def from_cache_payload(cls, raw: str) -> UbiReadiness:
        """Deserialize a cache hit. Raises ``ValueError`` on malformed JSON."""
        data = json.loads(raw)
        return cls(
            rung=data["rung"],
            covered_pairs_pct=data["covered_pairs_pct"],
            head_covered=data["head_covered"],
            checked_at=datetime.fromisoformat(data["checked_at"]),
        )


def _cache_key(cluster_id: str, query_set_id: str, target: str) -> str:
    return f"ubi-readiness:{cluster_id}:{query_set_id}:{target}"


async def classify_rung(
    *,
    adapter: SearchAdapter,
    cluster_id: str,
    query_set_id: str,
    query_set_query_ids: list[str],
    target: str,
    redis: Redis,
    min_impressions_threshold: int = DEFAULT_MIN_IMPRESSIONS_THRESHOLD,
    window_days: int = DEFAULT_READINESS_WINDOW_DAYS,
) -> UbiReadiness:
    """Probe + classify; 60 s Redis cache per ``(cluster_id, query_set_id, target)``.

    Workflow:

    1. Read-through the Redis cache.
    2. On miss: probe ``ubi_queries`` schema via :class:`UbiReader`.
       Schema 404 → ``rung_0``.
    3. Issue one bounded event count against ``ubi_events`` filtered by
       the ``(application, window, query_id IN <set>)`` triple.
    4. Apply the event-count thresholds → ``rung_1 | rung_2 | rung_3``.
    5. Cache + return.

    Args:
        adapter: Engine adapter; consumed but NOT owned (caller manages
            ``aclose()``).
        cluster_id: Cluster row id (cache-key only — adapter already
            bound).
        query_set_id: Query set id (cache-key + event filter).
        query_set_query_ids: UBI ``query_id`` values to filter on. Pass
            the result of :func:`backend.app.db.repo.query.list_queries_for_set`
            with the caller's mapping applied — or pass empty for the
            dispatcher's degraded path (which still gets a meaningful
            "is there ANY UBI traffic" signal).
        target: Operator-supplied index name; flows through as the
            UBI ``application`` filter.
        redis: Redis client for the 60 s cache.
        min_impressions_threshold: Rung_1 → rung_2 cutoff.
        window_days: Trailing-window size for the event count.

    Returns:
        :class:`UbiReadiness` with the rung label + ``checked_at``
        timestamp. ``covered_pairs_pct`` + ``head_covered`` are
        ``None`` in MVP2 (see module docstring).
    """
    key = _cache_key(cluster_id, query_set_id, target)

    # 1. Cache read-through.
    try:
        cached = await redis.get(key)
    except Exception as exc:  # noqa: BLE001 — Redis hiccup degrades to live probe
        logger.warning(
            "ubi_readiness_cache_read_failed",
            event_type="ubi_readiness_cache_read_failed",
            cluster_id=cluster_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        cached = None
    if cached is not None:
        try:
            raw = cached.decode() if isinstance(cached, bytes) else cached
            return UbiReadiness.from_cache_payload(raw)
        except (ValueError, KeyError) as exc:
            logger.warning(
                "ubi_readiness_cache_decode_failed",
                event_type="ubi_readiness_cache_decode_failed",
                cluster_id=cluster_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            # fall through to fresh probe

    reader = UbiReader(adapter)
    try:
        await reader._probe_enabled()
    except UbiNotEnabledError:
        snapshot = UbiReadiness(
            rung="rung_0",
            covered_pairs_pct=None,
            head_covered=None,
            checked_at=datetime.now(UTC),
        )
        await _cache_write(redis, key, snapshot)
        return snapshot

    # 2. Bounded event count against the rung_3 cap so we can distinguish
    # all three non-zero rungs in one call.
    cap = max(min_impressions_threshold * 5, min_impressions_threshold + 1)
    from datetime import timedelta

    until = datetime.now(UTC)
    since = until - timedelta(days=window_days)

    event_count = await _count_ubi_events_at_most(
        adapter,
        target=target,
        since=since,
        until=until,
        query_ids=query_set_query_ids,
        cap=cap,
    )

    if event_count < min_impressions_threshold:
        rung: UbiReadinessRung = "rung_1"
    elif event_count < min_impressions_threshold * 5:
        rung = "rung_2"
    else:
        rung = "rung_3"

    snapshot = UbiReadiness(
        rung=rung,
        covered_pairs_pct=None,
        head_covered=None,
        checked_at=datetime.now(UTC),
    )
    await _cache_write(redis, key, snapshot)
    return snapshot


async def count_ubi_events_in_window(
    adapter: SearchAdapter,
    *,
    target: str,
    since: datetime,
    until: datetime,
    cap: int,
) -> int:
    """Public wrapper used by the dispatcher's preflight U-D2 (FR-4).

    Issues one bounded ``search_batch`` against ``ubi_events`` filtered
    by ``(application=target, since <= timestamp < until)`` and returns
    ``min(actual_count, cap)``. The dispatcher compares the result
    against ``min_impressions_threshold`` and rejects sync with
    422 ``UBI_INSUFFICIENT_DATA`` when below.
    """
    return await _count_ubi_events_at_most(
        adapter,
        target=target,
        since=since,
        until=until,
        query_ids=None,
        cap=cap,
    )


async def _count_ubi_events_at_most(
    adapter: SearchAdapter,
    *,
    target: str,
    since: datetime,
    until: datetime,
    query_ids: list[str] | None,
    cap: int,
) -> int:
    """Issue one ``search_batch`` and return ``min(actual_count, cap)``.

    Sets ``_source=False`` so the response carries no document bodies —
    just doc ids + scores. ``cap`` bounds memory; the caller compares
    the returned count against their threshold and treats ``return == cap``
    as "≥ cap events present".
    """
    if adapter.engine_type == "solr":
        # Count-only — the caller does len(result[...]), so request the
        # minimal field (fl="id") rather than full docs. _normalize_fl
        # injects score + uniqueKey; "id" keeps the projection tight.
        body: dict[str, Any] = _build_solr_ubi_body(
            target=target,
            since=since,
            until=until,
            query_ids=query_ids,
            rows=cap,
            fl="id",
        )
    else:
        filters: list[dict[str, Any]] = [
            {
                "range": {
                    "timestamp": {
                        "gte": since.isoformat(),
                        "lt": until.isoformat(),
                    }
                }
            },
            {"term": {"application": target}},
        ]
        if query_ids:
            filters.append({"terms": {"query_id": query_ids}})

        body = {
            "query": {"bool": {"filter": filters}},
            "_source": False,
            "track_total_hits": False,
            "size": cap,
        }
    native = NativeQuery(query_id="ubi_readiness_count", body=body)
    result = await adapter.search_batch(
        UBI_EVENTS_INDEX,
        queries=[native],
        top_k=cap,
    )
    return len(result.get("ubi_readiness_count", []))


async def _cache_write(redis: Redis, key: str, snapshot: UbiReadiness) -> None:
    """Persist the snapshot for ``CACHE_TTL_SECONDS``; swallow Redis errors."""
    try:
        await redis.set(key, snapshot.to_cache_payload(), ex=CACHE_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001 — cache is advisory
        logger.warning(
            "ubi_readiness_cache_write_failed",
            event_type="ubi_readiness_cache_write_failed",
            key=key,
            error_type=type(exc).__name__,
            error=str(exc),
        )
