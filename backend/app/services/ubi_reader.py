# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``UbiReader`` — engine-neutral UBI scan + client-side join (feat_ubi_judgments Story 2.1 / FR-1).

Reads ``ubi_queries`` + ``ubi_events`` via
:meth:`SearchAdapter.search_batch` (no new adapter method per CLAUDE.md
Absolute Rule #4 — UBI works on every engine the adapter Protocol
supports), performs the ``query_id`` join client-side, and aggregates
into per-(query_id, doc_id) :class:`FeatureVec` via the pure-domain
:func:`aggregate_features`.

**Read-only contract.** This module issues only ``GET /<index>/_mapping``
(via ``adapter.get_schema``) and ``POST /_msearch`` (via
``adapter.search_batch``). No ``PUT``, ``DELETE``, ``_bulk``, ``_update``,
``_doc``, or ``_create`` calls. The
:func:`backend.tests.integration.test_ubi_reader_no_writes` invariant
test mocks the underlying ``httpx`` transport and asserts zero
write-shaped requests escape the reader's call boundary.

**Multi-application disambiguation.** UBI's standardized schema includes
an ``application`` field on both indices so operators running multiple
front-ends against the same UBI back-end can scope events per app. The
reader passes ``target`` (the live index being tuned, e.g. ``products``)
as the ``application`` filter — operators MUST configure UBI capture so
``application == <target-index-name>`` for the index being optimized.
The runbook (Story 5.1) documents the per-engine wire-up.

**Field-name extraction.** UBI's reference schemas use:

* ``ubi_queries``: top-level ``query_id``, ``user_query``,
  ``application``, ``timestamp``.
* ``ubi_events``: top-level ``query_id``, ``action_name``,
  ``application``, ``timestamp`` + a nested ``event_attributes`` object
  carrying ``position``, ``object.object_id`` (doc_id), and
  ``dwell_time_seconds``. The reader also accepts top-level fallbacks
  (``object_id``, ``position``, ``dwell_seconds``) so the o19s ES UBI
  fork's flatter shape works without operator-side translation. Events
  missing both the nested AND fallback path for ``doc_id`` are silently
  dropped (logged at DEBUG); the aggregator never sees them. This
  matches the same "unknown event types ignored" tolerance built into
  :func:`aggregate_features`.

**Per-spec FR-1.** The signature returns
``dict[tuple[str, str], FeatureVec]`` where the tuple is
``(ubi_query_id, doc_id)`` — the ``ubi_query_id`` is the UBI plugin's
own UUID (NOT RelyLoop's ``queries.id``). Story 3.3's worker joins
``ubi_query_id`` → ``user_query`` → ``queries.query_text`` →
``queries.id`` via the locked ``mapping_strategy`` (spec D-4) — that
join lives in the worker, not the reader. The reader's ``ubi_query_id``
→ ``user_query`` map is exposed via :meth:`UbiReader.read_user_query_map`
for the same window so the worker doesn't have to re-scan
``ubi_queries`` twice.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from backend.app.adapters.errors import TargetNotFoundError
from backend.app.adapters.protocol import NativeQuery, ScoredHit, SearchAdapter
from backend.app.domain.ubi import FeatureVec, aggregate_features
from backend.app.domain.ubi.features import UbiEvent
from backend.app.services.ubi_errors import UbiNotEnabledError

logger = structlog.get_logger(__name__)

UBI_QUERIES_INDEX = "ubi_queries"
"""Standardized UBI queries index name (OpenSearch UBI plugin + o19s ES fork)."""

UBI_EVENTS_INDEX = "ubi_events"
"""Standardized UBI events index name (OpenSearch UBI plugin + o19s ES fork)."""

ES_MAX_RESULT_WINDOW = 10_000
"""Elasticsearch/OpenSearch default ``index.max_result_window``.

A single ``search_batch`` call is a ``size``-limited query (NOT a
scroll / ``search_after`` paginator), so requesting ``size`` above this
window makes the engine fail the query with "Result window is too
large / all shards failed". The adapter swallows that per-query error
in non-strict mode and returns ``[]`` — which previously surfaced as a
spurious ``UBI_INSUFFICIENT_DATA`` even on dense clusters (found via
the rung-3 E2E against a real engine; a stubbed adapter can't catch an
engine-side window error). Both scan caps below MUST stay <= this.
"""

DEFAULT_MAX_QUERIES = 5000
"""Default cap on ``ubi_queries`` rows per window. < ES_MAX_RESULT_WINDOW."""

DEFAULT_MAX_EVENTS = ES_MAX_RESULT_WINDOW
"""Default cap on ``ubi_events`` rows scanned per window.

Capped at :data:`ES_MAX_RESULT_WINDOW` because a single ``search_batch``
is ``size``-limited, not scrolling — requesting more makes the engine
reject the query (see :data:`ES_MAX_RESULT_WINDOW`). 10k events is a
representative sample for CTR/dwell rating derivation on any single
(target, window); operators with denser traffic narrow the window via
``since``/``until``. Exact full-traffic aggregation via ``search_after``
pagination is a documented future enhancement
(``chore_ubi_reader_search_after_pagination``), not MVP scope.
"""


def _to_solr_instant(value: datetime) -> str:
    """Render a UTC ``datetime`` as Solr's ``DatePointField`` instant (``...Z``).

    ``datetime.isoformat()`` renders the UTC offset as ``+00:00``; Solr's
    ``DatePointField`` only accepts the canonical ``...Z`` form (and rejects
    ``+00:00`` with "Invalid Date String"). Mirrors the write-path helper
    ``backend.app.services.demo_ubi_seed._to_solr_date`` so the read-path
    range bounds match the stored ``timestamp`` field format. ES/OpenSearch's
    ``date`` type tolerates both, so this conversion is Solr-only.
    """
    iso = value.isoformat()
    if iso.endswith("+00:00"):
        return iso[: -len("+00:00")] + "Z"
    return iso


def _build_solr_ubi_body(
    *,
    target: str,
    since: datetime,
    until: datetime,
    query_ids: list[str] | None,
    rows: int,
    fl: str,
) -> dict[str, Any]:
    """Build a Solr ``/select`` request-param body for a UBI scan/count.

    The ES/OpenSearch path hands ``search_batch`` an Elasticsearch query DSL
    body (``{"query": {"bool": {"filter": [...]}}}``); the SolrAdapter rejects
    that shape (``_validate_solr_param_values`` requires scalars / lists of
    scalars). This builder emits the equivalent Solr request params instead:

    * ``q="*:*"`` — match all; all filtering is via ``fq``.
    * ``fq`` — a list of filter-query strings (list-of-scalars is allowed):
        - timestamp range ``timestamp:[<since> TO <until>}`` (inclusive lower,
          exclusive upper — matches the ES ``gte``/``lt`` half-open intent;
          Solr supports the ``}`` exclusive-upper bound).
        - ``application:"<target>"`` (quoted).
        - when ``query_ids`` is non-empty, ``{!terms f=query_id}<id>,<id>,...``
          (the Solr ``terms`` query parser — NOT a boolean ``OR`` expansion,
          which would blow past ``maxBooleanClauses`` (default 1024) once an
          operator's query set exceeds ~1k unique ids; ``max_queries`` defaults
          to 5000).
    * ``rows`` — ``str(rows)``.
    * ``fl`` — the caller's field list (``_normalize_fl`` will inject ``score``
      + the uniqueKey).

    Deliberately omits ES-only keys (``query``, ``_source``,
    ``track_total_hits``, ``size``) — they would fail
    ``_validate_solr_param_values`` or be meaningless to Solr.
    """
    since_solr = _to_solr_instant(since)
    until_solr = _to_solr_instant(until)
    fq: list[str] = [
        f"timestamp:[{since_solr} TO {until_solr}}}",
        f'application:"{target}"',
    ]
    if query_ids:
        # Solr ``terms`` query parser — handles arbitrarily long id lists
        # without expanding to boolean clauses (avoids ``TooManyClauses`` once
        # an operator's query set exceeds ``maxBooleanClauses``). UBI query_ids
        # are plugin UUIDs (no commas), so the default comma separator is safe.
        fq.append("{!terms f=query_id}" + ",".join(query_ids))
    return {
        "q": "*:*",
        "fq": fq,
        "rows": str(rows),
        "fl": fl,
    }


class UbiReader:
    """Engine-neutral UBI scan + client-side join.

    Constructed per (cluster, position-bias-prior) pair; reusable across
    multiple ``read_features`` calls within the same generation job.
    The adapter is owned by the caller (the dispatcher / worker holds
    ``adapter.aclose()`` responsibility via
    :func:`backend.app.services.cluster.acquire_adapter`).

    Position-bias prior is passed as a plain dict so the reader is
    decoupled from :class:`backend.app.core.settings.Settings` (callers
    resolve the prior via ``settings.ubi_position_bias_prior`` and inject
    it explicitly — keeps the reader unit-testable without a settings
    fixture).
    """

    def __init__(
        self,
        adapter: SearchAdapter,
        position_bias_prior: dict[int, float] | None = None,
    ) -> None:
        """Bind the reader to an adapter + (optional) position-bias prior.

        Args:
            adapter: Any :class:`SearchAdapter` implementation — UBI is
                engine-neutral. The adapter is consumed but NOT owned;
                lifecycle (``aclose()``) is the caller's responsibility.
            position_bias_prior: Optional ``{rank: weight}`` mapping for
                the Wang-Bendersky CTR correction in
                :func:`aggregate_features`. ``None`` (default) is the
                uninformed prior — every rank weighted 1.0 (corrected
                CTR == raw CTR).
        """
        self._adapter = adapter
        self._position_bias_prior = position_bias_prior or {}

    async def _probe_enabled(self) -> None:
        """Probe ``ubi_queries`` mapping; raise :class:`UbiNotEnabledError` on 404.

        Wraps :meth:`SearchAdapter.get_schema` so the readiness service
        (Story 2.2) and the dispatcher preflight U-C (Story 2.2) share
        one probe shape — both call this method to classify a cluster's
        UBI rung.

        Raises:
            UbiNotEnabledError: when the engine returns 404 for the
                ``ubi_queries`` index.
            ClusterUnreachableError: connection / auth / 5xx failure
                (propagated unchanged so the router can translate to
                503 ``CLUSTER_UNREACHABLE``).
        """
        try:
            await self._adapter.get_schema(UBI_QUERIES_INDEX)
        except TargetNotFoundError as exc:
            raise UbiNotEnabledError(
                f"ubi_queries index not found on engine {self._adapter.engine_type} — "
                "install the UBI plugin (OpenSearch UBI plugin / o19s ES UBI fork) "
                "and configure event capture for this cluster"
            ) from exc

    async def read_features(
        self,
        *,
        target: str,
        since: datetime,
        until: datetime | None = None,
        query_filter: str | None = None,
        max_queries: int = DEFAULT_MAX_QUERIES,
        max_events: int = DEFAULT_MAX_EVENTS,
        request_id: str | None = None,
    ) -> dict[tuple[str, str], FeatureVec]:
        """Two-index scan + client-side join → per-(query, doc) features.

        Workflow:

        1. Probe ``ubi_queries`` schema. Raises
           :class:`UbiNotEnabledError` on 404.
        2. Scan ``ubi_queries`` filtered by ``timestamp ∈ [since, until)``
           ``AND application == target`` (and ``user_query`` substring
           when ``query_filter`` is provided). Capped at ``max_queries``.
        3. If step 2 returns zero queries, log + return ``{}`` (race-
           condition fallback per FR-1 — preflight U-D2 covers the sync
           case).
        4. Scan ``ubi_events`` filtered by the same window +
           ``application`` + ``query_id IN <step-2 ids>``. Capped at
           ``max_events``.
        5. Bucket events by ``(query_id, doc_id)``, materialize as
           :class:`UbiEvent` instances, pass to
           :func:`aggregate_features` with the bound position-bias prior.

        Args:
            target: Operator-supplied index name (the live target being
                tuned). Used as the UBI ``application`` filter — operators
                MUST configure UBI capture so ``application == target``.
            since: Inclusive lower bound on the event ``timestamp``
                window. ISO-8601 UTC.
            until: Exclusive upper bound on the event ``timestamp``
                window. Defaults to "now" (UTC) when ``None``.
            query_filter: Optional ``user_query`` substring; when set, the
                ``ubi_queries`` scan narrows to queries whose
                ``user_query`` contains this substring (wildcard match —
                ``*<filter>*``).
            max_queries: Cap on ``ubi_queries`` hits; default
                ``DEFAULT_MAX_QUERIES``.
            max_events: Cap on ``ubi_events`` hits; default
                ``DEFAULT_MAX_EVENTS``.
            request_id: Optional correlation id surfaced to the engine
                via ``X-Opaque-Id`` (carried through ``search_batch``).

        Returns:
            ``{(ubi_query_id, doc_id): FeatureVec}`` — empty dict when
            the window has no events. The ``ubi_query_id`` is the UBI
            plugin's UUID, not RelyLoop's ``queries.id`` — Story 3.3's
            worker joins via ``user_query`` strings (see module
            docstring).
        """
        await self._probe_enabled()

        effective_until = until or datetime.now(UTC)

        queries_payload = await self._scan_ubi_queries(
            target=target,
            since=since,
            until=effective_until,
            query_filter=query_filter,
            max_queries=max_queries,
            request_id=request_id,
        )

        if not queries_payload:
            logger.info(
                "ubi_reader_empty_features",
                event_type="ubi_reader_empty_features",
                engine_type=self._adapter.engine_type,
                target=target,
                since=since.isoformat(),
                until=effective_until.isoformat(),
                reason="no_ubi_queries_in_window",
            )
            return {}

        query_ids = sorted({entry["query_id"] for entry in queries_payload})

        events_payload = await self._scan_ubi_events(
            target=target,
            since=since,
            until=effective_until,
            query_ids=query_ids,
            max_events=max_events,
            request_id=request_id,
        )

        events_by_pair: dict[tuple[str, str], list[UbiEvent]] = {}
        for raw_event in events_payload:
            event = _extract_event(raw_event)
            if event is None:
                # Missing required fields (query_id, doc_id, action_name).
                # Already logged at DEBUG inside _extract_event.
                continue
            pair = (event.query_id, event.doc_id)
            events_by_pair.setdefault(pair, []).append(event)

        if not events_by_pair:
            logger.info(
                "ubi_reader_empty_features",
                event_type="ubi_reader_empty_features",
                engine_type=self._adapter.engine_type,
                target=target,
                since=since.isoformat(),
                until=effective_until.isoformat(),
                reason="no_ubi_events_for_queries",
                query_count=len(query_ids),
            )
            return {}

        return aggregate_features(events_by_pair, self._position_bias_prior)

    async def read_user_query_map(
        self,
        *,
        target: str,
        since: datetime,
        until: datetime | None = None,
        query_filter: str | None = None,
        max_queries: int = DEFAULT_MAX_QUERIES,
        request_id: str | None = None,
    ) -> dict[str, str]:
        """Surface the ``{ubi_query_id: user_query}`` map for the same window.

        Story 3.3's worker joins UBI ``query_id`` → ``user_query`` →
        ``queries.id`` via :ref:`mapping_strategy` (spec D-4) — without
        this method the worker would have to re-scan ``ubi_queries``
        after :meth:`read_features` ran. Both methods share the same
        ``ubi_queries`` filter shape so cached engine responses on the
        same window are reusable.

        Returns an empty dict on empty windows (no ``UbiNotEnabledError``
        re-probe; callers expected to have already invoked
        ``read_features`` which triggers the probe).
        """
        queries_payload = await self._scan_ubi_queries(
            target=target,
            since=since,
            until=until or datetime.now(UTC),
            query_filter=query_filter,
            max_queries=max_queries,
            request_id=request_id,
        )
        return {entry["query_id"]: entry["user_query"] for entry in queries_payload}

    async def _scan_ubi_queries(
        self,
        *,
        target: str,
        since: datetime,
        until: datetime,
        query_filter: str | None,
        max_queries: int,
        request_id: str | None,
    ) -> list[dict[str, Any]]:
        """Issue one ``_msearch`` call against ``ubi_queries``; return source dicts.

        Each returned dict has at minimum ``query_id`` (string) and
        ``user_query`` (string). Hits missing either field are dropped
        (logged at DEBUG) — defensive against operator UBI mis-config.
        """
        scan_rows = min(max_queries, ES_MAX_RESULT_WINDOW)
        if self._adapter.engine_type == "solr":
            body: dict[str, Any] = _build_solr_ubi_body(
                target=target,
                since=since,
                until=until,
                query_ids=None,
                rows=scan_rows,
                fl="query_id,user_query,application,timestamp",
            )
            if query_filter:
                body["fq"].append(f"user_query:*{query_filter}*")
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
            if query_filter:
                filters.append({"wildcard": {"user_query": f"*{query_filter}*"}})

            body = {
                "query": {"bool": {"filter": filters}},
                "_source": ["query_id", "user_query", "application", "timestamp"],
                "track_total_hits": False,
            }
        native = NativeQuery(query_id="ubi_queries_scan", body=body)

        result = await self._adapter.search_batch(
            UBI_QUERIES_INDEX,
            queries=[native],
            # Clamp to the engine result-window — search_batch is size-limited,
            # not scrolling; a larger size makes the engine reject the query.
            top_k=scan_rows,
            request_id=request_id,
        )
        hits = result.get("ubi_queries_scan", [])
        return _extract_query_hits(hits)

    async def _scan_ubi_events(
        self,
        *,
        target: str,
        since: datetime,
        until: datetime,
        query_ids: list[str],
        max_events: int,
        request_id: str | None,
    ) -> list[dict[str, Any]]:
        """Issue one ``_msearch`` call against ``ubi_events``; return source dicts.

        Filters by the same window + ``application`` + ``query_id IN
        <step-1 ids>``. Returns raw ``_source`` dicts; field extraction
        happens in :func:`_extract_event`.
        """
        if not query_ids:
            return []

        scan_rows = min(max_events, ES_MAX_RESULT_WINDOW)
        if self._adapter.engine_type == "solr":
            # Solr UBI event docs are flat (object_id / position /
            # dwell_seconds — see demo_ubi_seed._to_solr_docs), so fl="*"
            # returns every field _extract_event reads via its top-level
            # fallback path.
            body: dict[str, Any] = _build_solr_ubi_body(
                target=target,
                since=since,
                until=until,
                query_ids=query_ids,
                rows=scan_rows,
                fl="*",
            )
        else:
            body = {
                "query": {
                    "bool": {
                        "filter": [
                            {
                                "range": {
                                    "timestamp": {
                                        "gte": since.isoformat(),
                                        "lt": until.isoformat(),
                                    }
                                }
                            },
                            {"term": {"application": target}},
                            {"terms": {"query_id": query_ids}},
                        ]
                    }
                },
                "_source": [
                    "query_id",
                    "action_name",
                    "event_attributes",
                    "object_id",
                    "position",
                    "dwell_seconds",
                    "timestamp",
                ],
                "track_total_hits": False,
            }
        native = NativeQuery(query_id="ubi_events_scan", body=body)

        result = await self._adapter.search_batch(
            UBI_EVENTS_INDEX,
            queries=[native],
            # Clamp to the engine result-window (see ES_MAX_RESULT_WINDOW) —
            # exceeding it makes the engine fail the query ("all shards
            # failed"), which the adapter swallows to an empty result.
            top_k=scan_rows,
            request_id=request_id,
        )
        return [hit.source for hit in result.get("ubi_events_scan", []) if hit.source is not None]


def _extract_query_hits(hits: list[ScoredHit]) -> list[dict[str, Any]]:
    """Filter ``ubi_queries`` hits down to ones with the required fields.

    Returns a list of ``{query_id, user_query, application, timestamp}``
    dicts. Hits missing ``query_id`` or ``user_query`` are dropped with
    a DEBUG log line; both are spec-required UBI fields, so absence
    signals operator UBI mis-config (worth surfacing in the runbook,
    not worth crashing the worker).
    """
    out: list[dict[str, Any]] = []
    dropped = 0
    for hit in hits:
        source = hit.source
        if source is None:
            dropped += 1
            continue
        query_id = source.get("query_id")
        user_query = source.get("user_query")
        if not isinstance(query_id, str) or not isinstance(user_query, str):
            dropped += 1
            continue
        out.append(
            {
                "query_id": query_id,
                "user_query": user_query,
                "application": source.get("application"),
                "timestamp": source.get("timestamp"),
            }
        )
    if dropped:
        logger.debug(
            "ubi_reader_dropped_query_hits",
            event_type="ubi_reader_dropped_query_hits",
            dropped=dropped,
            kept=len(out),
            reason="missing_required_fields",
        )
    return out


def _extract_event(source: dict[str, Any]) -> UbiEvent | None:
    """Extract a :class:`UbiEvent` from a raw ``ubi_events._source`` dict.

    Handles both nested (``event_attributes.{position, object.object_id,
    dwell_time_seconds}`` per OpenSearch UBI plugin reference) and
    top-level fallbacks (``position``, ``object_id``, ``dwell_seconds``
    per o19s ES UBI fork's flatter shape).

    Returns ``None`` when the event is missing ``query_id``,
    ``action_name``, OR a resolvable ``doc_id``. Aggregator never sees
    half-populated events.
    """
    query_id = source.get("query_id")
    action_name = source.get("action_name")
    if not isinstance(query_id, str) or not isinstance(action_name, str):
        return None

    attrs = source.get("event_attributes") or {}
    if not isinstance(attrs, dict):
        attrs = {}

    # doc_id — prefer nested event_attributes.object.object_id, fall back
    # to top-level object_id (o19s ES UBI fork shape). Coerce numeric ids to
    # str: operators may emit object_id as an integer/float (e.g. a numeric
    # product SKU), and a strict isinstance(str) check would silently drop
    # those events (Gemini PR #317 finding #4). The engine's own `_id` is
    # always a string, but UBI event_attributes are operator-populated.
    doc_id: str | None = None
    obj = attrs.get("object")
    if isinstance(obj, dict):
        candidate = obj.get("object_id")
        if candidate is not None:
            candidate_str = str(candidate).strip()
            if candidate_str:
                doc_id = candidate_str
    if doc_id is None:
        top_level = source.get("object_id")
        if top_level is not None:
            top_level_str = str(top_level).strip()
            if top_level_str:
                doc_id = top_level_str
    if doc_id is None:
        logger.debug(
            "ubi_reader_dropped_event",
            event_type="ubi_reader_dropped_event",
            reason="missing_doc_id",
            query_id=query_id,
            action_name=action_name,
        )
        return None

    # position — int | None
    position: int | None = None
    raw_position = attrs.get("position", source.get("position"))
    if isinstance(raw_position, int):
        position = raw_position
    elif isinstance(raw_position, float):
        position = int(raw_position)

    # dwell_seconds — float | None
    dwell_seconds: float | None = None
    raw_dwell = attrs.get(
        "dwell_time_seconds",
        attrs.get("dwell_seconds", source.get("dwell_seconds")),
    )
    if isinstance(raw_dwell, int | float):
        dwell_seconds = float(raw_dwell)

    return UbiEvent(
        query_id=query_id,
        doc_id=doc_id,
        event_type=action_name.lower(),
        position=position,
        dwell_seconds=dwell_seconds,
    )
