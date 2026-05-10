"""ElasticAdapter — single adapter for Elasticsearch + OpenSearch (Story 2.1+).

One class handles both engines because the wire surface RelyLoop uses
(``_cluster/health``, ``_mapping``, ``_settings``, ``_cat/indices``,
``_msearch``, ``_explain``) is identical from ES 8.11+ through ES 9.x and
OpenSearch 2.x. ``engine_type`` only pivots:

* The minimum-version threshold (ES 8.11 vs OpenSearch 2.0) in
  ``_enforce_min_version`` (Story 2.2).
* The ``GET /`` body shape — ES exposes ``version.number``; OpenSearch adds
  ``version.distribution`` (Story 2.7's branch test asserts both).

I/O methods are async; ``render`` / ``list_query_parsers`` stay synchronous
per the Protocol. ``aclose()`` MUST be called when the adapter goes out of
scope (the service layer wraps registration probes in ``try/finally``).

Per CLAUDE.md Absolute Rule #4, no engine-specific code lives outside this
module — services consume the unified ``SearchAdapter`` Protocol.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from typing import Any

import httpx

from backend.app.adapters.credentials import resolve_credentials
from backend.app.adapters.errors import ClusterUnreachableError, TargetNotFoundError
from backend.app.adapters.protocol import (
    EngineType,
    ExplainTree,
    FieldSpec,
    HealthStatus,
    NativeQuery,
    ParamValue,
    QueryTemplate,
    Schema,
    ScoredHit,
    TargetInfo,
)

ES_MIN_VERSION: tuple[int, int] = (8, 11)
"""Elasticsearch minimum supported version (per spec §11)."""

OPENSEARCH_MIN_VERSION: tuple[int, int] = (2, 0)
"""OpenSearch minimum supported version (per spec §11)."""

SUPPORTED_ENGINE_TYPES: frozenset[str] = frozenset({"elasticsearch", "opensearch"})
"""Wire-value source of truth for cluster registration. Mirrors the
``clusters_engine_type_check`` CHECK constraint in migration 0002."""

SUPPORTED_ENVIRONMENTS: frozenset[str] = frozenset({"prod", "staging", "dev"})
"""Mirrors ``clusters_environment_check``."""

SUPPORTED_AUTH_KINDS: frozenset[str] = frozenset({"es_apikey", "es_basic", "opensearch_basic"})
"""``auth_kind`` values implemented in MVP1."""

RESERVED_AUTH_KINDS: frozenset[str] = frozenset({"opensearch_sigv4"})
"""Wire values that pass the DB CHECK constraint but are not implemented in MVP1.

The cluster service raises ``AuthKindNotSupported`` for these so the operator
gets a 400 with a clear message rather than a 500 from the adapter."""

ALLOWED_AUTH_PER_ENGINE: dict[str, frozenset[str]] = {
    "elasticsearch": frozenset({"es_apikey", "es_basic"}),
    "opensearch": frozenset({"opensearch_basic"}),  # + opensearch_sigv4 at MVP3
}
"""Cross-product allowlist enforced at registration time.

The DB ``auth_kind`` CHECK constraint accepts any of the four wire values for
any engine, but pairing ``engine_type=opensearch`` with ``auth_kind=es_apikey``
(or vice versa) is operator misconfiguration: the labels exist precisely to
distinguish which auth method goes with which engine. The service layer rejects
mismatched pairings with 400 ``AUTH_KIND_NOT_SUPPORTED`` so the error surfaces
at request time rather than at the first probe.

Reserved kinds (``opensearch_sigv4``) are NOT enumerated here — they're rejected
earlier in ``register_cluster`` via ``RESERVED_AUTH_KINDS`` regardless of engine."""


class ElasticAdapter:
    """Engine adapter for Elasticsearch (8.11+/9.x) and OpenSearch (2.x)."""

    engine_type: EngineType

    def __init__(
        self,
        *,
        cluster_id: str,
        engine_type: EngineType,
        base_url: str,
        auth_kind: str,
        credentials_ref: str,
        engine_config: dict[str, Any] | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Construct an adapter; validates the auth_kind allowlist immediately."""
        if auth_kind in RESERVED_AUTH_KINDS:
            raise NotImplementedError(f"{auth_kind!r} is reserved but not implemented in MVP1")
        if auth_kind not in SUPPORTED_AUTH_KINDS:
            raise ValueError(f"unknown auth_kind: {auth_kind!r}")
        self.cluster_id = cluster_id
        self.engine_type = engine_type
        self.base_url = base_url.rstrip("/")
        self.auth_kind = auth_kind
        self.credentials_ref = credentials_ref
        self.engine_config = engine_config or {}
        self._auth_headers = self._build_auth_headers()
        self._client = client or httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=2.0))
        self._version: str | None = None
        """Engine version string; populated on the first health_check."""

    def _build_auth_headers(self) -> dict[str, str]:
        """Resolve mounted credentials and build the static Authorization header."""
        creds = resolve_credentials(self.auth_kind, self.credentials_ref)
        if self.auth_kind == "es_apikey":
            return {"Authorization": f"ApiKey {creds['api_key']}"}
        if self.auth_kind in ("es_basic", "opensearch_basic"):
            token = base64.b64encode(f"{creds['username']}:{creds['password']}".encode()).decode()
            return {"Authorization": f"Basic {token}"}
        # Unreachable — auth_kind validated in __init__.
        raise AssertionError("unreachable: auth_kind validated in __init__")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        content: bytes | str | None = None,
        params: dict[str, Any] | None = None,
        request_id: str | None = None,
        timeout: float | None = None,
        extra_headers: dict[str, str] | None = None,
        translate_errors: bool = True,
    ) -> httpx.Response:
        """Issue an HTTP request to the cluster with the spec §13 single retry.

        Per spec §13 Reliability, connection-class failures are retried exactly
        once before propagating. When ``translate_errors=True`` (default), the
        retried-and-still-failed connection error and 401/403/5xx responses
        surface as ``ClusterUnreachableError``. ``health_check`` opts out by
        passing ``translate_errors=False`` because it owns its own status mapping
        and returns ``HealthStatus(status='unreachable', ...)`` instead of
        raising.

        ``X-Opaque-Id`` carries the operator-supplied ``request_id`` to the
        engine for cross-service correlation.

        Args:
            method: HTTP method (``GET``, ``POST``, ...).
            path: Request path appended to ``self.base_url``.
            json: Optional JSON body (sent as ``application/json``).
            content: Optional raw bytes/str body (used for NDJSON ``_msearch``).
            params: Optional query string mapping.
            request_id: Optional correlation id surfaced to the engine.
            timeout: Per-request override of the adapter's default httpx timeout.
            extra_headers: Optional headers merged on top of auth headers.
            translate_errors: If True, raise ``ClusterUnreachableError`` for
                connection failures + 401/403/5xx responses; if False, return the
                response (or re-raise the underlying httpx exception) so the
                caller can implement bespoke status mapping.

        Returns:
            The successful ``httpx.Response``.

        Raises:
            ClusterUnreachableError: when ``translate_errors=True`` and the
                request fails or returns 401/403/5xx.
        """
        headers = dict(self._auth_headers)
        if extra_headers:
            headers.update(extra_headers)
        if request_id:
            headers["X-Opaque-Id"] = request_id

        kwargs: dict[str, Any] = dict(
            method=method,
            url=f"{self.base_url}{path}",
            headers=headers,
            params=params,
        )
        if json is not None:
            kwargs["json"] = json
        if content is not None:
            kwargs["content"] = content
        if timeout is not None:
            kwargs["timeout"] = timeout

        connection_excs = (
            httpx.ConnectError,
            httpx.RemoteProtocolError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
        )

        # Spec §13: exactly one retry on connection-class failures.
        resp: httpx.Response | None = None
        for attempt in (1, 2):
            try:
                resp = await self._client.request(**kwargs)
                break
            except connection_excs as exc:
                if attempt == 2:
                    if translate_errors:
                        raise ClusterUnreachableError(str(exc)) from exc
                    raise
                # First attempt failed; retry once.
                continue
        # mypy: the loop assigns resp on success or raises; narrow.
        assert resp is not None  # noqa: S101

        if translate_errors and resp.status_code in (401, 403):
            raise ClusterUnreachableError(
                f"Authentication failed (HTTP {resp.status_code}) for {method} {path}"
            )
        if translate_errors and resp.status_code >= 500:
            raise ClusterUnreachableError(f"HTTP {resp.status_code} from {method} {path}")
        return resp

    async def aclose(self) -> None:
        """Close the underlying httpx client. Idempotent at the httpx level."""
        await self._client.aclose()

    # ------------------------------------------------------------------
    # Protocol method stubs — filled by Stories 2.2–2.6.
    # ------------------------------------------------------------------

    async def health_check(self, *, request_id: str | None = None) -> HealthStatus:
        """Probe ``GET /_cluster/health``; lazy-load engine version on first call.

        All connection-class failures and unsupported versions surface as
        ``HealthStatus(status='unreachable', error=...)`` — never raised. The
        cluster service relies on this contract to translate to
        ``CLUSTER_UNREACHABLE`` (FR-5 / AC-6).

        ``translate_errors=False`` is used so this method owns its own status
        mapping (rather than catching ``ClusterUnreachableError`` from
        ``_request``); the spec §13 single retry still applies inside
        ``_request`` before the call returns.
        """
        now = datetime.now(UTC).isoformat()
        try:
            resp = await self._request(
                "GET",
                "/_cluster/health",
                request_id=request_id,
                translate_errors=False,
            )
        except (
            httpx.ConnectError,
            httpx.ReadTimeout,
            httpx.RemoteProtocolError,
            httpx.ConnectTimeout,
        ) as exc:
            return HealthStatus(status="unreachable", checked_at=now, error=str(exc))

        if resp.status_code >= 500:
            return HealthStatus(
                status="unreachable",
                checked_at=now,
                error=f"HTTP {resp.status_code} from /_cluster/health",
            )
        if resp.status_code in (401, 403):
            return HealthStatus(
                status="unreachable",
                checked_at=now,
                error=f"Authentication failed (HTTP {resp.status_code})",
            )

        body = resp.json()
        cluster_status = body.get("status", "red")
        if cluster_status not in ("green", "yellow", "red"):
            cluster_status = "red"

        if self._version is None:
            try:
                info = await self._request(
                    "GET", "/", request_id=request_id, translate_errors=False
                )
            except (
                httpx.ConnectError,
                httpx.ReadTimeout,
                httpx.RemoteProtocolError,
                httpx.ConnectTimeout,
            ) as exc:
                return HealthStatus(status="unreachable", checked_at=now, error=str(exc))
            # Per GPT-5.5 final-review F2: non-200 on GET / must surface as
            # unreachable so registration refuses to insert. Without this guard,
            # an auth-misconfigured cluster (200 on /_cluster/health, 401 on /)
            # would pass registration with version=None and bypass
            # _enforce_min_version (no-op when _version is None).
            if info.status_code in (401, 403):
                return HealthStatus(
                    status="unreachable",
                    checked_at=now,
                    error=f"Authentication failed (HTTP {info.status_code}) on GET /",
                )
            if info.status_code != 200:
                return HealthStatus(
                    status="unreachable",
                    checked_at=now,
                    error=f"HTTP {info.status_code} from GET / — cannot read engine version",
                )
            self._version = info.json().get("version", {}).get("number")
            if self._version is None:
                return HealthStatus(
                    status="unreachable",
                    checked_at=now,
                    error="GET / response missing version.number — cannot enforce engine floor",
                )
            try:
                self._enforce_min_version()
            except ValueError as exc:
                return HealthStatus(
                    status="unreachable",
                    version=self._version,
                    checked_at=now,
                    error=str(exc),
                )

        return HealthStatus(
            status=cluster_status,
            version=self._version,
            checked_at=now,
        )

    def _enforce_min_version(self) -> None:
        """Raise ``ValueError`` if the engine version is below the supported floor.

        Caught by ``health_check`` and surfaced as ``HealthStatus(status='unreachable')``
        so the registration service refuses to insert (AC-6).
        """
        if self._version is None:
            return
        parts = [int(p) for p in self._version.split(".")[:2] if p.isdigit()]
        if len(parts) < 2:
            return
        version_pair = (parts[0], parts[1])
        if self.engine_type == "elasticsearch" and version_pair < ES_MIN_VERSION:
            raise ValueError(
                f"engine version {self._version} is below minimum "
                f"{ES_MIN_VERSION[0]}.{ES_MIN_VERSION[1]}"
            )
        if self.engine_type == "opensearch" and version_pair < OPENSEARCH_MIN_VERSION:
            raise ValueError(
                f"engine version {self._version} is below minimum "
                f"{OPENSEARCH_MIN_VERSION[0]}.{OPENSEARCH_MIN_VERSION[1]}"
            )

    async def list_targets(self, *, request_id: str | None = None) -> list[TargetInfo]:
        """List indices on the cluster via ``_cat/indices?format=json``.

        System indices (those whose name starts with ``.``) are filtered out
        so the operator sees only user-facing collections.
        """
        resp = await self._request(
            "GET",
            "/_cat/indices",
            params={"format": "json", "h": "index,docs.count"},
            request_id=request_id,
        )
        resp.raise_for_status()
        rows: list[dict[str, Any]] = resp.json()
        out: list[TargetInfo] = []
        for row in rows:
            name = row.get("index")
            if not name or name.startswith("."):
                continue
            doc_count_raw = row.get("docs.count")
            doc_count: int | None
            if doc_count_raw is None or doc_count_raw == "":
                doc_count = None
            else:
                doc_count = int(str(doc_count_raw))
            out.append(TargetInfo(name=name, doc_count=doc_count))
        return out

    async def get_schema(self, target: str, *, request_id: str | None = None) -> Schema:
        """Build a ``Schema`` from ``_mapping`` + the index's default analyzer.

        Per cycle 1 F6 + cycle 2 F5: ``_field_caps`` is **not** consulted —
        that endpoint does not return analyzer info on either ES or
        OpenSearch. Analyzer derivation:

        * Explicit ``analyzer`` in the field mapping → used verbatim.
        * ``text`` field with no explicit analyzer → defaults to the index's
          default analyzer from ``_settings`` (or ``"standard"`` on miss).
        * Non-``text`` fields (``keyword``, ``float``, ``date``, ...) → ``None``.

        Raises:
            TargetNotFoundError: when the cluster returns 404 for ``target``.
            ClusterUnreachableError: connection / auth / 5xx; raised inside
                ``_request`` because ``translate_errors=True`` (default).
        """
        mapping_resp = await self._request(
            "GET",
            f"/{target}/_mapping",
            request_id=request_id,
            translate_errors=False,
        )
        if mapping_resp.status_code == 404:
            raise TargetNotFoundError(target)
        if mapping_resp.status_code in (401, 403) or mapping_resp.status_code >= 500:
            raise ClusterUnreachableError(
                f"HTTP {mapping_resp.status_code} from /{target}/_mapping"
            )
        if mapping_resp.status_code >= 400:
            # Other 4xx (e.g. 400 with "invalid_index_name") — no separate
            # spec error code, surface as unreachable.
            raise ClusterUnreachableError(
                f"HTTP {mapping_resp.status_code} from /{target}/_mapping"
            )
        mapping = mapping_resp.json()
        if not mapping:
            return Schema(name=target, fields=[])
        # Mapping body is keyed by index name (which can differ from `target`
        # when `target` is an alias). Take the first / only entry.
        inner = next(iter(mapping.values()))
        props = inner.get("mappings", {}).get("properties", {})

        default_analyzer = await self._resolve_default_analyzer(target, request_id=request_id)

        fields: list[FieldSpec] = []
        for name, defn in props.items():
            ftype = defn.get("type", "object")
            analyzer = defn.get("analyzer")
            if analyzer is None and ftype == "text":
                analyzer = default_analyzer
            fields.append(FieldSpec(name=name, type=ftype, analyzer=analyzer))
        return Schema(name=target, fields=fields)

    async def _resolve_default_analyzer(self, target: str, *, request_id: str | None = None) -> str:
        """Resolve the index's default analyzer.

        Defaults to ``"standard"`` on any error — this is a UX nicety, not a
        load-bearing contract. The caller already succeeded fetching
        ``_mapping`` so the cluster is reachable; analyzer-fetch failures
        degrade rather than propagate.
        """
        try:
            resp = await self._request(
                "GET",
                f"/{target}/_settings",
                request_id=request_id,
                translate_errors=False,
            )
        except Exception:  # noqa: BLE001 — defensive: degrade to default
            return "standard"
        if resp.status_code != 200:
            return "standard"
        body = resp.json()
        if not body:
            return "standard"
        inner = next(iter(body.values()))
        analysis = inner.get("settings", {}).get("index", {}).get("analysis", {})
        default = analysis.get("analyzer", {}).get("default", {})
        return str(default.get("type", "standard"))

    def list_query_parsers(self) -> list[str]:
        """Return the static set of query parsers MVP1 templates use.

        Both ES and OpenSearch support these out of the box; future engines
        (Solr, Vespa) override at the adapter level.
        """
        return ["match", "multi_match", "match_phrase", "bool", "function_score"]

    def render(
        self,
        template: QueryTemplate,
        params: dict[str, ParamValue],
        query_text: str,
    ) -> NativeQuery:
        """Render a Jinja query template + params into an engine-native ``NativeQuery``.

        Validates that every key in ``template.declared_params`` is supplied;
        ``query_text`` is added to the render context as ``query_text`` so
        templates can reference it directly.

        Raises:
            ValueError: when required template params are missing OR when the
                Jinja render fails (StrictUndefined surfaces as
                ``UndefinedError`` from Jinja; we wrap as ``ValueError`` so
                the service layer / API translate to a single error code).
        """
        from jinja2 import UndefinedError

        from backend.app.domain.query.render import render_template

        missing = set(template.declared_params) - set(params.keys())
        if missing:
            raise ValueError(f"render: missing required template params: {sorted(missing)}")

        context: dict[str, Any] = {**params, "query_text": query_text}
        try:
            body = render_template(template.body, context)
        except UndefinedError as exc:
            raise ValueError(f"render: undefined parameter — {exc}") from exc
        # query_id defaults to the template name; search_batch lets callers
        # override per-query for batch responses.
        return NativeQuery(query_id=template.name, body=body)

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
        """Issue one ``_msearch`` call and preserve query_id mapping (FR-3, AC-4).

        ``strict_errors`` controls per-query error handling:

        * ``False`` (default — Optuna trial runner): per-query engine errors
          yield empty ``[]`` for that ``query_id``; caller records a trial failure.
        * ``True`` (run_query API path): per-query parsing errors raise
          ``InvalidQueryDSLError``; per-query non-parse errors raise
          ``ClusterUnreachableError``.

        ``timeout`` overrides the adapter's default httpx client timeout for this
        call so the run_query endpoint's operator-supplied budget actually fires.

        Cycle 3 F2 fix: routed through ``_request`` to inherit the spec §13
        single retry + 401/403/5xx translation. Top-level 400 is mapped here
        (strict → ``InvalidQueryDSLError``, non-strict →
        ``ClusterUnreachableError``).
        """
        from backend.app.adapters.errors import InvalidQueryDSLError, QueryTimeoutError

        if not queries:
            return {}

        # Build the NDJSON body: alternating {index header} + {query body, size}
        lines: list[str] = []
        for q in queries:
            lines.append(json.dumps({"index": target}))
            body = dict(q.body)
            body.setdefault("size", top_k)
            lines.append(json.dumps(body))
        ndjson_body = "\n".join(lines) + "\n"

        try:
            resp = await self._request(
                "POST",
                "/_msearch",
                content=ndjson_body,
                extra_headers={"Content-Type": "application/x-ndjson"},
                request_id=request_id,
                timeout=timeout,
                translate_errors=False,
            )
        except httpx.ReadTimeout as exc:
            # Read timeout the retry didn't recover — strict callers (run_query)
            # get QueryTimeoutError; hot-path gets ClusterUnreachableError so
            # trial runners can degrade gracefully.
            if strict_errors:
                raise QueryTimeoutError(str(exc)) from exc
            raise ClusterUnreachableError(str(exc)) from exc
        except (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ConnectTimeout) as exc:
            raise ClusterUnreachableError(str(exc)) from exc

        # Top-level status mapping (translate_errors=False kept it visible).
        if resp.status_code in (401, 403):
            raise ClusterUnreachableError(
                f"Authentication failed (HTTP {resp.status_code}) for _msearch"
            )
        if resp.status_code >= 500:
            raise ClusterUnreachableError(f"HTTP {resp.status_code} from _msearch")
        if resp.status_code == 400:
            body_txt = resp.text[:500]
            if strict_errors:
                raise InvalidQueryDSLError(f"_msearch rejected the request: {body_txt}")
            raise ClusterUnreachableError(f"HTTP 400 from _msearch: {body_txt}")
        resp.raise_for_status()

        payload = resp.json()
        items = payload.get("responses", [])
        out: dict[str, list[ScoredHit]] = {}
        for q, item in zip(queries, items, strict=True):
            if "error" in item:
                err = item["error"]
                err_type = err.get("type") if isinstance(err, dict) else None
                err_reason = err.get("reason") if isinstance(err, dict) else str(err)
                if strict_errors:
                    if err_type in (
                        "parsing_exception",
                        "x_content_parse_exception",
                        "json_parse_exception",
                    ):
                        raise InvalidQueryDSLError(f"query {q.query_id}: {err_reason}")
                    raise ClusterUnreachableError(f"query {q.query_id} failed: {err_reason}")
                out[q.query_id] = []
                continue
            hits = item.get("hits", {}).get("hits", [])
            out[q.query_id] = [
                ScoredHit(
                    doc_id=h["_id"],
                    score=float(h.get("_score") or 0.0),
                    source=h.get("_source"),
                )
                for h in hits
            ]
        return out

    async def explain(
        self,
        target: str,
        query: NativeQuery,
        doc_id: str,
        *,
        request_id: str | None = None,
    ) -> ExplainTree:
        """Return the engine's scoring breakdown for ``(target, query, doc_id)``.

        Maps engine errors:
        * 404 → ``TargetNotFoundError`` (target doesn't exist).
        * Auth / 5xx → ``ClusterUnreachableError`` (raised by ``_request``).
        """
        resp = await self._request(
            "POST",
            f"/{target}/_explain/{doc_id}",
            json=query.body,
            request_id=request_id,
            translate_errors=False,
        )
        if resp.status_code == 404:
            raise TargetNotFoundError(target)
        if resp.status_code in (401, 403) or resp.status_code >= 500:
            raise ClusterUnreachableError(
                f"HTTP {resp.status_code} from /{target}/_explain/{doc_id}"
            )
        resp.raise_for_status()
        payload = resp.json()
        return _build_explain_tree(
            payload.get("explanation", {}),
            doc_id,
            bool(payload.get("matched", False)),
        )


def _build_explain_tree(node: dict[str, Any], doc_id: str, matched: bool) -> ExplainTree:
    """Recursively build an ``ExplainTree`` from the engine's nested explanation node."""
    return ExplainTree(
        doc_id=doc_id,
        matched=matched,
        value=float(node.get("value", 0.0)),
        description=str(node.get("description", "")),
        details=[_build_explain_tree(child, doc_id, matched) for child in node.get("details", [])],
    )
