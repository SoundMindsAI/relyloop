# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""SearchAdapter Protocol + Pydantic types (infra_adapter_elastic Story 1.1 / FR-1).

The Protocol defines the engine boundary per
[`docs/01_architecture/adapters.md`](../../../docs/01_architecture/adapters.md).
Every adapter implementation (MVP1: ``ElasticAdapter`` for ES + OpenSearch;
MVP2: ``SolrAdapter`` for Apache Solr) implements this
Protocol so the orchestrator, study runner, evaluator, and UI consume one
unified surface — no engine-specific code outside ``backend/app/adapters/``
(CLAUDE.md Absolute Rule #4).

I/O methods are async because every concrete implementation in MVP1 talks to
the engine over HTTP via ``httpx`` async; the type-check stub in
`test_protocol.py` asserts ``inspect.iscoroutinefunction`` on each.
``render`` and ``list_query_parsers`` stay synchronous (pure CPU work).

NOTE on doc consistency: ``docs/01_architecture/adapters.md`` shows synchronous
signatures — that was an aspirational sketch. Story 4.2 patches the doc to
match this async contract.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

EngineType = Literal["elasticsearch", "opensearch", "solr"]
"""Wire values for cluster registration. Source-of-truth — DB CHECK in 0002 + 0022 migrations.
``solr`` added by ``infra_adapter_solr`` (Story A6)."""

ParamValue = bool | int | float | str | list[str]
"""Allowed Jinja-template parameter value types."""


class FieldSpec(BaseModel):
    """One field returned by ``get_schema``."""

    name: str
    type: str
    """Engine type label: 'text', 'keyword', 'float', 'boolean', 'date', ..."""
    analyzer: str | None = None
    doc_count: int | None = None


class Schema(BaseModel):
    """An index / collection's field schema."""

    name: str
    """Target index or collection name."""
    fields: list[FieldSpec]


class HealthStatus(BaseModel):
    """Result of a cluster reachability + version probe."""

    status: Literal["green", "yellow", "red", "unreachable"]
    version: str | None = None
    """Engine version string (e.g. '9.4.0').

    Populated for reachable clusters; ``None`` when status == 'unreachable'.
    """
    checked_at: str
    """ISO-8601 UTC timestamp of the probe."""
    error: str | None = None
    """Human-readable detail when status == 'unreachable'."""


class TargetInfo(BaseModel):
    """One target (index / collection) on a cluster."""

    name: str
    doc_count: int | None = None


class NativeQuery(BaseModel):
    """An engine-native query body. For ES/OpenSearch this is the Query DSL JSON."""

    query_id: str
    """Caller-supplied identifier; preserved through `search_batch` response mapping."""
    body: dict[str, Any]
    """The engine-native request body (e.g. {'query': {'match': {...}}, 'size': 10})."""


class ScoredHit(BaseModel):
    """One scored search hit."""

    doc_id: str
    score: float
    source: dict[str, Any] | None = None


class ExplainTree(BaseModel):
    """Recursive explain-tree returned by ``explain``."""

    doc_id: str
    matched: bool
    value: float
    description: str
    details: list[ExplainTree] = Field(default_factory=list)


class Document(BaseModel):
    """A single document by ID — return shape of ``SearchAdapter.get_document``.

    Mirrors :class:`ScoredHit` minus ``score`` (browsing doesn't need scoring).
    ``source`` is ``None`` when the engine's index has ``_source: false`` mapping.
    """

    doc_id: str = Field(min_length=1)
    source: dict[str, Any] | None = None


class AdapterDocumentHit(BaseModel):
    """One hit on the adapter's paginated list page.

    Carries the engine's per-hit ``sort`` value so the router can compute the
    next cursor from the correct in-body hit under the ``limit + 1`` overfetch
    pattern (router slices ``hits[:user_limit]`` and encodes
    ``hits[user_limit - 1].sort``).
    """

    doc_id: str = Field(min_length=1)
    source: dict[str, Any] | None = None
    sort: list[Any]


class DocumentPage(BaseModel):
    """Return shape of ``SearchAdapter.list_documents``.

    ``total`` is the engine's ``hits.total.value`` (request body sets
    ``track_total_hits: true`` so the count is exact, not capped at 10000).
    ``hits`` may contain up to ``limit + 1`` entries — the router caller
    slices to ``user_limit`` before serializing and uses the trailing entry
    only as the has-more sentinel, not for cursor encoding.

    ``next_cursor_token`` is an additive optional field for adapters that
    paginate via an engine-supplied opaque cursor token rather than per-hit
    sort values (Solr's ``nextCursorMark`` — see ``infra_adapter_solr``
    Story A8). When populated, the router prefers it over the trailing-hit
    ``sort`` for cursor encoding; when ``None``, the router falls back to
    the existing ES path (slice + encode ``hits[limit - 1].sort``). The
    Solr adapter sets it to ``None`` on the terminal page so ``has_more``
    derives correctly without an extra overfetch.
    """

    hits: list[AdapterDocumentHit]
    total: int
    next_cursor_token: str | None = None


class ScanPage(BaseModel):
    """One page of a full-stream scan (``SearchAdapter.scan_all``).

    Companion to :class:`DocumentPage` but for the bounded-result-window
    full-stream aggregation use case (``chore_ubi_reader_search_after_pagination``
    FR-1). ``UbiReader`` loops ``scan_all`` page-by-page, folding each
    page's hits into per-(query, doc) accumulators until either the
    engine signals terminal (``cursor=None``) or the configured ceiling
    is reached (caller invokes ``close_scan`` to release the held PIT).

    ``cursor`` is an **opaque, engine-internal continuation token** —
    the caller round-trips it verbatim and never inspects it. The
    encoding stays engine-agnostic:

    * ``ElasticAdapter`` packs ``{pit_id, search_after, no_pit}`` so
      each page advances ``search_after`` inside the same PIT and the
      PIT id rotates with each response.
    * ``SolrAdapter`` carries the ``nextCursorMark`` string directly.

    ``cursor=None`` means the terminal page has been served — there is
    nothing more to fetch and no engine-side resource still held.
    """

    hits: list[ScoredHit]
    cursor: object | None = None


class QueryTemplate(BaseModel):
    """A template definition handed to ``render``.

    The ``query_templates`` DB table is owned by ``feat_study_lifecycle``
    (per data-model.md); this Pydantic model is the wire shape adapter callers
    use to invoke ``render`` without coupling to that table.
    """

    name: str
    engine_type: EngineType
    body: str
    """Jinja2 source rendering to a JSON object (the engine's native query body)."""
    declared_params: dict[str, str]
    """{param_name: type/range hint} — used to validate ``params`` at render time."""


@runtime_checkable
class SearchAdapter(Protocol):
    """The adapter Protocol — the only place engine-specific logic lives.

    All I/O methods are async (httpx async client under the hood); pure
    methods (``render``, ``list_query_parsers``) are synchronous.
    """

    engine_type: EngineType

    async def health_check(self, *, request_id: str | None = None) -> HealthStatus:
        """Probe cluster reachability + engine version. See ``HealthStatus`` for shape."""
        ...

    async def list_targets(
        self,
        *,
        request_id: str | None = None,
        target_filter: str | None = None,
    ) -> list[TargetInfo]:
        """List indices/collections on the cluster (excludes engine system indices).

        When ``target_filter`` is provided, the result is further restricted to
        names where ``fnmatch.fnmatchcase(name, target_filter)`` returns True
        (feat_cluster_target_filter FR-3). Glob syntax: ``*``, ``?``, ``[seq]``,
        ``[!seq]`` — no brace expansion (pure Python ``fnmatch``). Case-sensitive
        via ``fnmatchcase`` (avoids platform-dependent ``os.path.normcase`` in
        ``fnmatch.fnmatch``).

        Order of operations: system-index ``.`` exclusion → glob filter.
        Operators cannot re-expose system indices via a permissive filter.

        Concrete implementations raise ``TargetsForbiddenError`` when the engine
        denies the listing call due to ACL (401/403), and ``ClusterUnreachableError``
        for connection failures / 5xx. Mirrors ``get_schema``'s pattern of
        404 → ``TargetNotFoundError``: per-failure exception classes let the
        router translate to distinct ``error_code`` envelopes.
        """
        ...

    async def get_schema(self, target: str, *, request_id: str | None = None) -> Schema:
        """Return the field schema for ``target``. Raises ``TargetNotFoundError`` on 404."""
        ...

    def list_query_parsers(self) -> list[str]:
        """Return the engine's supported query parsers (used by template validation)."""
        ...

    def render(
        self,
        template: QueryTemplate,
        params: dict[str, ParamValue],
        query_text: str,
    ) -> NativeQuery:
        """Render a Jinja query template + params + query text into a ``NativeQuery``."""
        ...

    async def search_batch(
        self,
        target: str,
        queries: list[NativeQuery],
        top_k: int,
        *,
        request_id: str | None = None,
        strict_errors: bool = False,
        timeout: float | None = None,
    ) -> dict[str, list[ScoredHit]]:
        """Hot path. Issue one ``_msearch`` call and return preserved query_id mapping.

        ``strict_errors=True`` (run_query API path): per-query parsing errors raise
        ``InvalidQueryDSLError``; per-query non-parse errors raise
        ``ClusterUnreachableError``. ``False`` (Optuna trial runner): per-query
        engine errors yield empty ``[]`` for that ``query_id`` so a trial can be
        recorded as failed without aborting the batch.

        ``timeout`` overrides the adapter's default httpx client timeout for this
        call. The run_query endpoint passes the operator-supplied budget so the
        spec's 5s default / 30s max actually fires.
        """
        ...

    async def explain(
        self,
        target: str,
        query: NativeQuery,
        doc_id: str,
        *,
        request_id: str | None = None,
    ) -> ExplainTree:
        """Return the engine's scoring breakdown for one (target, query, doc_id) triple."""
        ...

    async def get_document(
        self,
        target: str,
        doc_id: str,
        *,
        request_id: str | None = None,
    ) -> Document | None:
        """Fetch one document by ``_id`` (feat_index_document_browser FR-1).

        Returns ``None`` when the engine reports the document does not exist
        (e.g., ES ``{"found": false}``). Raises ``TargetNotFoundError`` when the
        target index itself does not exist (``index_not_found_exception``),
        ``TargetsForbiddenError`` on engine 401/403, and
        ``ClusterUnreachableError`` on connection failures / 5xx (after the
        adapter's internal retry budget is exhausted).
        """
        ...

    async def list_documents(
        self,
        target: str,
        *,
        search_after: list[Any] | None = None,
        limit: int = 25,
        fields: list[str] | None = None,
        request_id: str | None = None,
    ) -> DocumentPage:
        """Paginated browse over a target's documents (feat_index_document_browser FR-1).

        Adapters paginate using ``search_after`` over a deterministic ``sort``
        key with ``track_total_hits: true``. The ``ElasticAdapter`` sorts by
        ``_doc`` (per spec D-26 fallback — ES 9 disables ``_id`` fielddata by
        default); other engines may pick any stable internal key as long as
        ``hits[i].sort`` is returned for ``search_after`` round-trips. The
        caller is expected to request ``user_limit + 1`` and slice in the
        router so the engine never observes the user-facing page size — see
        ``FR-3``.

        Same error envelope as :meth:`get_document`: ``TargetNotFoundError`` /
        ``TargetsForbiddenError`` / ``ClusterUnreachableError``.
        """
        ...

    async def scan_all(
        self,
        target: str,
        body: dict[str, Any],
        *,
        page_size: int,
        cursor: object | None = None,
        fl: list[str] | None = None,
        request_id: str | None = None,
    ) -> ScanPage:
        """Full-stream paginated read (``chore_ubi_reader_search_after_pagination`` FR-1).

        Abstracts the two engine pagination idioms behind one async
        coroutine that returns one page at a time:

        * **ES + OpenSearch** — ``search_after`` over an injected
          deterministic total-order sort
          ``[{timestamp: asc}, {_shard_doc: asc}]``, anchored inside a
          PIT (Point-In-Time). The PIT id rotates with each response;
          the adapter packs the latest id into the opaque ``cursor`` so
          continuations carry it forward. Falls back narrowly (only on
          405/501/400-unsupported PIT-open responses) to a no-PIT path
          that uses a configured ``Settings.ubi_no_pit_tiebreaker_field``;
          if no tiebreaker is configured, the adapter falls back further
          to a single sampled query bounded by the 10k result window
          and logs a WARN.
        * **Solr** — ``cursorMark`` over a uniqueKey-terminated sort.
          Requests POST to ``/<target>/select`` (form-body params) so
          large ``{!terms f=query_id}`` filters do not overflow URL
          limits. Terminal when the engine returns
          ``nextCursorMark == request cursorMark`` (or a short page).

        ``cursor`` semantics: pass ``None`` on the first page; round-
        trip the value from the previous page's ``ScanPage.cursor``
        verbatim on continuations. The caller never inspects the
        value — it is engine-internal. A returned ``cursor=None``
        signals the terminal page (nothing left to fetch, no engine
        resource still held).

        Read-only invariant: ``scan_all`` MUST NOT mutate engine state.
        The only engine-side write-shaped requests permitted on this
        path are the read-only PIT close paths (``DELETE /_pit`` on ES,
        ``DELETE /_search/point_in_time`` on OpenSearch) which release
        ephemeral read snapshots; those land in :meth:`close_scan`,
        never inside ``scan_all``'s page loop.

        Args:
            target: Index/collection name to scan.
            body: Engine-native filter body. The adapter overwrites any
                pagination-shaped keys (``pit``/``sort``/``size``/
                ``search_after`` on ES; ``start``/``rows``/``cursorMark``/
                ``sort`` on Solr) before issuing the request — caller
                pagination keys are stripped, not respected.
            page_size: Maximum hits returned per page. The caller may
                clamp further (e.g. to the remaining ceiling).
            cursor: Continuation token from the previous page, or
                ``None`` for the first page.
            fl: Optional field-list selection (Solr) / ``_source``
                includes (ES) for narrowing the returned document
                shape.
            request_id: Optional correlation id surfaced to the engine
                via ``X-Opaque-Id`` (ES) / ``X-Request-Id`` (Solr).

        Returns:
            A :class:`ScanPage` with the page's hits and a continuation
            ``cursor`` (``None`` if this is the terminal page).

        Raises:
            ClusterUnreachableError: connection-class failures / 5xx
                after the spec §13 single retry.
            TargetsForbiddenError: engine 401/403 (e.g. on PIT open).
            TargetNotFoundError: engine 404 (e.g. missing UBI index).
        """
        ...

    async def close_scan(
        self,
        cursor: object | None,
        *,
        request_id: str | None = None,
    ) -> None:
        """Release any engine-side resource held by a non-terminal cursor.

        Idempotent + safe with ``cursor=None``:

        * **ES + OpenSearch** — ``DELETE`` the latest PIT id encoded in
          the cursor (ES path ``/_pit`` body ``{"id": <pit_id>}``;
          OpenSearch path ``/_search/point_in_time`` body
          ``{"pit_id": [<pit_id>]}``). No-op when the cursor was
          generated by the no-PIT fallback path or is ``None``.
        * **Solr** — always a no-op (``cursorMark`` holds no server-side
          resource).

        Called from the reader's ``finally`` block on early exit
        (ceiling reached, exception propagating) so a PIT is never
        leaked beyond the configured ``keep_alive``. Cleanup is
        best-effort: a close failure is logged and swallowed, never
        re-raised, so the cleanup path cannot mask the primary
        exception that motivated the early exit. Safe to call with the
        terminal cursor (``None``) as well — the adapter short-circuits.
        """
        ...
