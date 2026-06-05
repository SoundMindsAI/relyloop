# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``UbiReader`` — engine-neutral UBI scan + client-side join (feat_ubi_judgments Story 2.1 / FR-1).

Reads ``ubi_queries`` + ``ubi_events`` via
:meth:`SearchAdapter.scan_all` + :meth:`SearchAdapter.close_scan`
(``chore_ubi_reader_search_after_pagination`` FR-4 — the
generic cursor-scan surface replaced the original single-page
``search_batch`` call so dense (>10k-event) clusters get exact
full-traffic aggregation instead of a silent 10k-row sample), performs
the ``query_id`` join client-side, and aggregates into
per-(query_id, doc_id) :class:`FeatureVec` via the pure-domain
:func:`aggregate_features`.

**Read-only contract.** This module issues only ``GET /<index>/_mapping``
(via ``adapter.get_schema``), the engine's paginated read surface
(ES/OpenSearch: ``POST /<index>/_pit`` + ``POST /_search`` +
``DELETE /_pit`` / ``DELETE /_search/point_in_time``; Solr:
``POST /<target>/select``), and ``adapter.search_batch`` for the
narrow no-PIT sampled fallback. No ``PUT``, ``DELETE`` against
indexed paths, ``_bulk``, ``_update``, ``_doc``, or ``_create``
calls — the only ``DELETE`` is the unindexed PIT-close which
releases a read snapshot. The
:func:`backend.tests.unit.services.test_ubi_reader_no_writes`
invariant test mocks the underlying ``httpx`` transport and asserts
zero write-shaped requests escape the reader's call boundary.

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

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import structlog

from backend.app.adapters.errors import TargetNotFoundError
from backend.app.adapters.protocol import ScoredHit, SearchAdapter
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

A single paginated request still caps individual page sizes at this
value — the engine rejects ``size`` above it with "Result window is
too large / all shards failed". With
``chore_ubi_reader_search_after_pagination`` (FR-4) the reader now
loops :meth:`SearchAdapter.scan_all` so the overall scan can read far
more than 10k events — but each PAGE still respects this cap.
"""

DEFAULT_MAX_QUERIES = 200_000
"""Default ceiling on ``ubi_queries`` rows per window (FR-5).

High-but-finite — operators with denser traffic see exact
aggregation, not a sample. Overridden by the caller via
:meth:`UbiReader.__init__` (workers resolve from
:attr:`backend.app.core.settings.Settings.ubi_max_queries_scan`).
"""

DEFAULT_MAX_EVENTS = 1_000_000
"""Default ceiling on ``ubi_events`` rows scanned per window (FR-5).

High-but-finite — the prior 10k single-page cap (``ES_MAX_RESULT_WINDOW``)
became a per-page cap once ``scan_all`` shipped; the overall scan is
bounded by this ceiling instead and operators can lift it via
:attr:`backend.app.core.settings.Settings.ubi_max_events_scan`.
Overridden by the caller via :meth:`UbiReader.__init__`.
"""

DEFAULT_UBI_QUERY_ID_BATCH_SIZE = 1024
"""Default id-count ceiling per ``query_id`` batch on the events scan (FR-7).

A batch splits whenever EITHER this OR
:data:`DEFAULT_UBI_QUERY_ID_BATCH_MAX_BYTES` would be exceeded.
Operators override via
:attr:`backend.app.core.settings.Settings.ubi_query_id_batch_size`.
"""

DEFAULT_UBI_QUERY_ID_BATCH_MAX_BYTES = 32_768
"""Default encoded byte-length ceiling per ``query_id`` batch (FR-7 / P2-B1).

Measured on the FULLY-SERIALIZED filter fragment (Solr
``{!terms f=query_id}a,b,c`` / ES JSON terms list) — so the request
body stays bounded regardless of id length. Operators override via
:attr:`backend.app.core.settings.Settings.ubi_query_id_batch_max_bytes`.
"""


def _serialized_terms_fragment_size(engine_type: str, ids: list[str]) -> int:
    """Return the encoded byte-length of the engine's terms-filter fragment.

    The byte budget is measured on the **fully-serialized** filter
    fragment so wrapper + separator overhead are counted (P2-B1) — that
    is what enforces the request-size ceiling at the wire level, not the
    summed raw id-byte total.

    Solr: ``{!terms f=query_id}id1,id2,...``.
    ES / OpenSearch: ``{"terms": {"query_id": ["id1", "id2", ...]}}`` —
    JSON-encoded (matches the terms-filter shape ``_build_ubi_events_body``
    emits in the ``query.bool.filter`` list).
    """
    if engine_type == "solr":
        fragment = "{!terms f=query_id}" + ",".join(ids)
        return len(fragment.encode("utf-8"))
    return len(json.dumps({"terms": {"query_id": ids}}).encode("utf-8"))


def _chunk_query_ids(
    query_ids: list[str],
    *,
    max_count: int,
    max_bytes: int,
    engine_type: str,
) -> Iterator[list[str]]:
    """Split ``query_ids`` into ceiling-bounded chunks (FR-7 / P2-B1).

    Chunks are bounded by BOTH the id-count AND the encoded byte-length
    of the engine's terms-filter fragment.

    A chunk is flushed whenever appending the next id would breach
    EITHER ceiling. The byte ceiling is the HARD limit — a single id
    that, alone, exceeds ``max_bytes`` is yielded by itself (the engine
    request will likely succeed since UBI ids are UUID-shaped and well
    under any reasonable per-id length; pathological-id-size config is
    an operator concern surfaced through the resulting engine error,
    not silently dropped).
    """
    if not query_ids:
        return
    current: list[str] = []
    for qid in query_ids:
        candidate = current + [qid]
        over_count = len(candidate) > max_count
        over_bytes = _serialized_terms_fragment_size(engine_type, candidate) > max_bytes
        if over_count or over_bytes:
            if current:
                yield current
                current = [qid]
            else:
                # Single-id batch exceeds the byte ceiling — yield alone
                # so the operator sees the engine-side error (preferable
                # to silent drops). UBI query_id values are UUIDs so this
                # branch is effectively unreachable in normal operation.
                yield [qid]
                current = []
        else:
            current = candidate
    if current:
        yield current


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
        *,
        max_events: int = DEFAULT_MAX_EVENTS,
        max_queries: int = DEFAULT_MAX_QUERIES,
        query_id_batch_size: int = DEFAULT_UBI_QUERY_ID_BATCH_SIZE,
        query_id_batch_max_bytes: int = DEFAULT_UBI_QUERY_ID_BATCH_MAX_BYTES,
    ) -> None:
        """Bind the reader to an adapter + (optional) position-bias prior + ceilings.

        Args:
            adapter: Any :class:`SearchAdapter` implementation — UBI is
                engine-neutral. The adapter is consumed but NOT owned;
                lifecycle (``aclose()``) is the caller's responsibility.
            position_bias_prior: Optional ``{rank: weight}`` mapping for
                the Wang-Bendersky CTR correction in
                :func:`aggregate_features`. ``None`` (default) is the
                uninformed prior — every rank weighted 1.0 (corrected
                CTR == raw CTR).
            max_events: Default ceiling on per-window ``ubi_events`` rows
                aggregated via the paginated scan (FR-5). Caller may
                override per-call via :meth:`read_features`. Workers
                resolve this from
                :attr:`backend.app.core.settings.Settings.ubi_max_events_scan`
                and inject it here so the reader stays decoupled from
                ``Settings`` (mirrors the ``position_bias_prior`` injection
                pattern).
            max_queries: Default ceiling on per-window ``ubi_queries`` rows.
                Same injection pattern as ``max_events``.
            query_id_batch_size: Id-count ceiling per ``query_id`` chunk on
                the events scan (FR-7). A batch splits whenever EITHER this
                OR ``query_id_batch_max_bytes`` would be exceeded.
            query_id_batch_max_bytes: Encoded byte-length ceiling per chunk
                — measured on the FULLY-SERIALIZED filter fragment
                (P2-B1). HARD limit: a batch splits when this is hit even
                if the id-count ceiling has not been.
        """
        self._adapter = adapter
        self._position_bias_prior = position_bias_prior or {}
        self._max_events = max_events
        self._max_queries = max_queries
        self._ubi_query_id_batch_size = query_id_batch_size
        self._ubi_query_id_batch_max_bytes = query_id_batch_max_bytes

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
        max_queries: int | None = None,
        max_events: int | None = None,
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
            max_queries: Per-call override of the ceiling injected at
                construction. ``None`` (default) → use
                ``self._max_queries`` (FR-5: workers inject
                :attr:`Settings.ubi_max_queries_scan`).
            max_events: Per-call override of the ``max_events`` ceiling
                injected at construction. ``None`` (default) → use
                ``self._max_events``.
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
        effective_max_queries = max_queries if max_queries is not None else self._max_queries
        effective_max_events = max_events if max_events is not None else self._max_events

        queries_payload = await self._scan_ubi_queries(
            target=target,
            since=since,
            until=effective_until,
            query_filter=query_filter,
            max_queries=effective_max_queries,
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
            max_events=effective_max_events,
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
        max_queries: int | None = None,
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
        effective_max_queries = max_queries if max_queries is not None else self._max_queries
        queries_payload = await self._scan_ubi_queries(
            target=target,
            since=since,
            until=until or datetime.now(UTC),
            query_filter=query_filter,
            max_queries=effective_max_queries,
            request_id=request_id,
        )
        return {entry["query_id"]: entry["user_query"] for entry in queries_payload}

    def _build_ubi_queries_body(
        self,
        *,
        target: str,
        since: datetime,
        until: datetime,
        query_filter: str | None,
    ) -> dict[str, Any]:
        """Build the engine-native filter body for a ``ubi_queries`` scan.

        Engine-aware (the only place the read path branches on
        ``engine_type`` outside the adapters per Rule #4 — same
        precedent as the pre-pagination code; the adapter Protocol
        accepts the body as opaque).

        Solr: ``q``/``fq``/``fl`` request params (the SolrAdapter rejects
        ES DSL via ``_validate_solr_param_values``).
        ES/OpenSearch: a ``query.bool.filter`` DSL body with
        ``_source`` field selection.
        """
        if self._adapter.engine_type == "solr":
            body: dict[str, Any] = _build_solr_ubi_body(
                target=target,
                since=since,
                until=until,
                query_ids=None,
                # ``rows`` is supplied by the adapter's scan_all (it owns
                # the page-size param); we still pass a non-zero ``rows``
                # to keep the build helper's contract intact — it gets
                # stripped by the adapter's pagination-key stripper.
                rows=1,
                fl="query_id,user_query,application,timestamp",
            )
            if query_filter:
                body["fq"].append(f"user_query:*{query_filter}*")
            return body

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
        return {
            "query": {"bool": {"filter": filters}},
            "_source": ["query_id", "user_query", "application", "timestamp"],
            "track_total_hits": False,
        }

    def _build_ubi_events_body(
        self,
        *,
        target: str,
        since: datetime,
        until: datetime,
        query_ids: list[str],
    ) -> dict[str, Any]:
        """Build the engine-native filter body for a ``ubi_events`` scan.

        Solr: flat docs (``object_id``/``position``/``dwell_seconds``
        top-level — see ``demo_ubi_seed._to_solr_docs``). ``fl="*"`` so
        :func:`_extract_event` reads every field via its top-level
        fallback path. ES/OpenSearch: nested
        ``event_attributes.{position, object.object_id,
        dwell_time_seconds}`` per the OpenSearch UBI plugin reference
        schema.
        """
        if self._adapter.engine_type == "solr":
            return _build_solr_ubi_body(
                target=target,
                since=since,
                until=until,
                query_ids=query_ids,
                # See ``_build_ubi_queries_body`` — ``rows`` is overwritten
                # by the adapter's scan_all page-size.
                rows=1,
                fl="*",
            )
        return {
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
        """Loop ``adapter.scan_all`` over ``ubi_queries`` (FR-4).

        Pages through the full stream, enforces the ``max_queries`` ceiling
        exactly (clamped per page + sliced on the final page), and closes
        the cursor in ``finally`` on every exit path (terminal, ceiling,
        exception — P3-A2 best-effort cleanup).

        Returns ``{query_id, user_query, application, timestamp}`` dicts;
        hits missing required fields are dropped (logged at DEBUG inside
        :func:`_extract_query_hits`).
        """
        body = self._build_ubi_queries_body(
            target=target, since=since, until=until, query_filter=query_filter
        )
        accumulated: list[ScoredHit] = []
        remaining = max_queries
        cursor: object | None = None
        ceiling_hit = False
        try:
            while remaining > 0:
                page_size = min(ES_MAX_RESULT_WINDOW, remaining)
                page = await self._adapter.scan_all(
                    UBI_QUERIES_INDEX,
                    body,
                    page_size=page_size,
                    cursor=cursor,
                    request_id=request_id,
                )
                # P1-B2: assign cursor IMMEDIATELY after await, BEFORE any
                # folding — so a fold-time exception still closes the
                # rotated PIT in `finally`.
                cursor = page.cursor
                take = page.hits[:remaining]
                accumulated.extend(take)
                remaining -= len(take)
                if cursor is None:
                    break
                if len(take) < len(page.hits):
                    # Ceiling reached mid-page.
                    ceiling_hit = True
                    break
        finally:
            # Best-effort cleanup (P3-A2) — never mask a primary exception.
            try:
                await self._adapter.close_scan(cursor, request_id=request_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "ubi_reader_close_scan_failed",
                    event_type="ubi_reader_close_scan_failed",
                    cluster_id=getattr(self._adapter, "cluster_id", None),
                    engine_type=self._adapter.engine_type,
                    target=UBI_QUERIES_INDEX,
                    error_type=type(exc).__name__,
                )

        # Truncation = we stopped before the stream ended. Either a ceiling
        # hit mid-page (ceiling_hit) OR the budget hit exactly a page
        # boundary while MORE data remained (remaining<=0 AND a non-terminal
        # cursor is still held). A terminal page that happens to fill the
        # budget exactly (cursor is None) is NOT truncation — don't WARN.
        if ceiling_hit or (remaining <= 0 and cursor is not None):
            logger.warning(
                "ubi_reader_scan_truncated",
                event_type="ubi_reader_scan_truncated",
                target=UBI_QUERIES_INDEX,
                scanned=max_queries - remaining,
                ceiling=max_queries,
                engine_type=self._adapter.engine_type,
            )
        return _extract_query_hits(accumulated)

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
        """Loop ``adapter.scan_all`` over ``ubi_events`` with ``query_id`` chunking.

        Splits ``query_ids`` into chunks bounded by the configured
        id-count AND byte-length ceilings (FR-7) so no single request
        emits an oversized ``{!terms}`` fq (Solr) or ``terms`` filter
        (ES). Iterates each chunk's full page stream via ``scan_all``,
        folds incrementally, and respects the global ``max_events``
        ceiling across chunks.

        Closes the cursor in ``finally`` on every exit path (P3-A2).
        Cursor is assigned immediately after the ``scan_all`` await —
        BEFORE any folding — so a fold-time exception still closes the
        rotated PIT (P1-B2).
        """
        if not query_ids:
            return []

        engine_type = self._adapter.engine_type
        out: list[dict[str, Any]] = []
        remaining = max_events
        # ``truncated`` is set explicitly at each genuine truncation point so
        # the end-of-scan WARN never fires on a clean full read that merely
        # happened to consume exactly the budget on a terminal page.
        truncated = False

        for batch in _chunk_query_ids(
            query_ids,
            max_count=self._ubi_query_id_batch_size,
            max_bytes=self._ubi_query_id_batch_max_bytes,
            engine_type=engine_type,
        ):
            if remaining <= 0:
                # The budget was exhausted by a prior batch and there are
                # still batches (query_ids) left to scan — that's truncation.
                truncated = True
                break
            body = self._build_ubi_events_body(
                target=target, since=since, until=until, query_ids=batch
            )
            cursor: object | None = None
            try:
                while remaining > 0:
                    page_size = min(ES_MAX_RESULT_WINDOW, remaining)
                    page = await self._adapter.scan_all(
                        UBI_EVENTS_INDEX,
                        body,
                        page_size=page_size,
                        cursor=cursor,
                        request_id=request_id,
                    )
                    # P1-B2 — cursor assignment BEFORE folding.
                    cursor = page.cursor
                    take = page.hits[:remaining]
                    out.extend(h.source for h in take if h.source is not None)
                    remaining -= len(take)
                    if cursor is None:
                        break
                    if len(take) < len(page.hits):
                        # Ceiling reached mid-page (more hits on this page
                        # than the budget allowed) — truncation.
                        truncated = True
                        break
                else:
                    # Inner loop exited via `while remaining > 0` going false
                    # (budget hit exactly a page boundary) while a non-terminal
                    # cursor is still held → more data existed in THIS batch.
                    if cursor is not None:
                        truncated = True
            finally:
                # Best-effort cleanup (P3-A2).
                try:
                    await self._adapter.close_scan(cursor, request_id=request_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "ubi_reader_close_scan_failed",
                        event_type="ubi_reader_close_scan_failed",
                        cluster_id=getattr(self._adapter, "cluster_id", None),
                        engine_type=engine_type,
                        target=UBI_EVENTS_INDEX,
                        error_type=type(exc).__name__,
                    )

        if truncated:
            logger.warning(
                "ubi_reader_scan_truncated",
                event_type="ubi_reader_scan_truncated",
                target=UBI_EVENTS_INDEX,
                # scanned = rows INSPECTED (budget consumed), not rows KEPT —
                # some hits may have source=None and never enter `out` (F3).
                scanned=max_events - remaining,
                ceiling=max_events,
                engine_type=engine_type,
            )
        return out


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
