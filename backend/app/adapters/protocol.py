"""SearchAdapter Protocol + Pydantic types (infra_adapter_elastic Story 1.1 / FR-1).

The Protocol defines the engine boundary per
[`docs/01_architecture/adapters.md`](../../../docs/01_architecture/adapters.md).
Every adapter implementation (MVP1: ``ElasticAdapter`` for ES + OpenSearch;
MVP3+: ``LucidworksFusionAdapter``; v2+: ``SolrAdapter``) implements this
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

EngineType = Literal["elasticsearch", "opensearch"]
"""Wire values for cluster registration. Source-of-truth — DB CHECK in 0002 migration."""

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

    async def list_targets(self, *, request_id: str | None = None) -> list[TargetInfo]:
        """List indices/collections on the cluster (excludes engine system indices).

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
