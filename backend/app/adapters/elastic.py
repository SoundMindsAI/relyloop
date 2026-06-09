# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

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
import fnmatch
import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx
import structlog

from backend.app.adapters.credentials import resolve_credentials
from backend.app.adapters.errors import (
    ClusterUnreachableError,
    TargetNotFoundError,
    TargetsForbiddenError,
)
from backend.app.adapters.protocol import (
    AdapterDocumentHit,
    Document,
    DocumentPage,
    EngineType,
    ExplainTree,
    FieldSpec,
    HealthStatus,
    NativeQuery,
    ParamValue,
    QueryTemplate,
    ScanPage,
    Schema,
    ScoredHit,
    TargetInfo,
)

# Engine + auth allowlists relocated to ``backend/app/adapters/registry.py`` by
# ``infra_adapter_solr`` Story A6 (spec FR-3). These ``as X`` re-exports are a
# transitional shim for one release so existing imports
# (``from backend.app.adapters.elastic import SUPPORTED_AUTH_KINDS``) keep
# working; new code imports from ``registry`` directly. The ``as X`` aliasing
# makes them explicit re-exports under mypy strict's ``no_implicit_reexport``.
from backend.app.adapters.registry import (
    ALLOWED_AUTH_PER_ENGINE as ALLOWED_AUTH_PER_ENGINE,
)
from backend.app.adapters.registry import (
    RESERVED_AUTH_KINDS as RESERVED_AUTH_KINDS,
)
from backend.app.adapters.registry import (
    SUPPORTED_AUTH_KINDS as SUPPORTED_AUTH_KINDS,
)
from backend.app.adapters.registry import (
    SUPPORTED_ENGINE_TYPES as SUPPORTED_ENGINE_TYPES,
)
from backend.app.adapters.registry import (
    SUPPORTED_ENVIRONMENTS as SUPPORTED_ENVIRONMENTS,
)
from backend.app.domain.study.normalizers import (
    DEFAULT_NORMALIZER,
    normalize_pipeline,
    steps_for_label,
)

logger = structlog.get_logger(__name__)

ES_MIN_VERSION: tuple[int, int] = (8, 11)
"""Elasticsearch minimum supported version (per spec §11)."""

OPENSEARCH_MIN_VERSION: tuple[int, int] = (2, 0)
"""OpenSearch minimum supported version (per spec §11)."""


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

    async def list_targets(
        self,
        *,
        request_id: str | None = None,
        target_filter: str | None = None,
    ) -> list[TargetInfo]:
        """List indices on the cluster via ``_cat/indices?format=json``.

        System indices (those whose name starts with ``.``) are filtered out
        so the operator sees only user-facing collections.

        When ``target_filter`` is provided (feat_cluster_target_filter FR-3),
        the result is further restricted to names where
        ``fnmatch.fnmatchcase(name, target_filter)`` returns True. The system-
        index exclusion runs FIRST so operators cannot re-expose ``.kibana*``
        via a permissive filter.

        ``translate_errors=False`` is used so the per-status mapping below can
        distinguish ACL-restricted clusters (401/403 → ``TargetsForbiddenError``)
        from unreachable clusters (5xx / connection failures →
        ``ClusterUnreachableError``). The frontend uses this distinction to
        auto-engage manual-mode target entry on ACL restriction
        (``feat_create_study_target_autocomplete`` FR-2 / FR-5).

        Raises:
            TargetsForbiddenError: when the cluster returns HTTP 401 or 403.
            ClusterUnreachableError: connection failures (after the one
                internal retry in ``_request``) or any non-2xx response other
                than 401/403.
        """
        try:
            resp = await self._request(
                "GET",
                "/_cat/indices",
                params={"format": "json", "h": "index,docs.count"},
                request_id=request_id,
                translate_errors=False,
            )
        except httpx.HTTPError as exc:
            # _request with translate_errors=False re-raises httpx
            # connection-class exceptions (ConnectError, RemoteProtocolError,
            # ConnectTimeout, ReadTimeout) AFTER its one internal retry. We
            # translate here so the router emits 503 CLUSTER_UNREACHABLE
            # instead of letting the raw exception surface as 500.
            raise ClusterUnreachableError(str(exc)) from exc
        if resp.status_code in (401, 403):
            raise TargetsForbiddenError(
                f"cluster denied listing call (HTTP {resp.status_code} from /_cat/indices)"
            )
        if resp.status_code >= 400:
            raise ClusterUnreachableError(f"HTTP {resp.status_code} from /_cat/indices")
        rows: list[dict[str, Any]] = resp.json()
        out: list[TargetInfo] = []
        for row in rows:
            name = row.get("index")
            if not name or name.startswith("."):
                continue  # system-index exclusion — runs FIRST
            if target_filter is not None and not fnmatch.fnmatchcase(name, target_filter):
                continue  # operator glob filter — runs SECOND
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
            ClusterUnreachableError: connection failures (after the one internal
                retry in ``_request``) or any non-2xx response other than 404.
        """
        try:
            mapping_resp = await self._request(
                "GET",
                f"/{target}/_mapping",
                request_id=request_id,
                translate_errors=False,
            )
        except httpx.HTTPError as exc:
            # _request with translate_errors=False re-raises httpx
            # connection-class exceptions AFTER its one internal retry.
            # Translate to ClusterUnreachableError so the router emits 503
            # CLUSTER_UNREACHABLE instead of 500 INTERNAL_ERROR. Mirrors the
            # pattern adopted by list_targets in feat_create_study_target_autocomplete.
            raise ClusterUnreachableError(str(exc)) from exc
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

        # Pre-render hook: pop the reserved query_normalizer off a LOCAL copy
        # (never mutate the caller's dict) and apply it to query_text before it
        # enters the Jinja context. Default "none" is a verbatim pass-through.
        # The value is either a Phase-1 bundle string OR a typed-pipeline
        # powerset label (feat_query_normalizer_typed_pipeline Story 1.4) — both
        # resolve through steps_for_label -> normalize_pipeline, so a winning
        # non-bundle label (e.g. "lowercase+strip_punctuation") applies correctly
        # instead of raising. Bad tokens raise ValueError, which the existing
        # trial-failure path subsumes.
        local_params = dict(params)
        choice = local_params.pop("query_normalizer", DEFAULT_NORMALIZER)
        # FR-2 guarantees a str by the create-study path; a non-str here can
        # only come from a direct DB mutation — treat it as an unknown choice
        # so it fails through the existing render-failure path.
        if not isinstance(choice, str):
            raise ValueError(f"unknown normalizer: {choice!r}")
        normalized_query_text = normalize_pipeline(query_text, steps_for_label(choice))

        # query_normalizer is consumed here, so exclude it from the declared-vs-
        # supplied check — it lives in declared_params but never in local_params.
        missing = set(template.declared_params) - set(local_params.keys()) - {"query_normalizer"}
        if missing:
            raise ValueError(f"render: missing required template params: {sorted(missing)}")

        context: dict[str, Any] = {**local_params, "query_text": normalized_query_text}
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
        * Auth / 5xx → ``ClusterUnreachableError``.
        * Connection failures (after one internal retry in ``_request``) →
          ``ClusterUnreachableError`` via the defensive ``httpx.HTTPError``
          catch (mirrors ``list_targets`` + ``get_schema``).
        """
        try:
            resp = await self._request(
                "POST",
                f"/{target}/_explain/{doc_id}",
                json=query.body,
                request_id=request_id,
                translate_errors=False,
            )
        except httpx.HTTPError as exc:
            raise ClusterUnreachableError(str(exc)) from exc
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

    async def get_document(
        self,
        target: str,
        doc_id: str,
        *,
        request_id: str | None = None,
    ) -> Document | None:
        """Fetch one document by ``_id`` (feat_index_document_browser FR-2).

        Maps engine responses:
        * ``200`` with ``_source`` → ``Document(doc_id, source)``.
        * ``200`` without ``_source`` (engine has ``_source: false``) →
          ``Document(doc_id, source=None)``.
        * ``404`` + ``found: false`` → ``None`` (doc absent on a live index).
        * ``404`` + ``error.type == "index_not_found_exception"`` →
          ``TargetNotFoundError`` (the target itself is missing).
        * ``401`` / ``403`` → ``TargetsForbiddenError`` (matches ``list_targets``
          pattern at lines 404-407, so the router can translate to 403
          ``TARGETS_FORBIDDEN`` instead of 503 ``CLUSTER_UNREACHABLE``).
        * Any other ``>= 400`` or connection failure → ``ClusterUnreachableError``.

        Both ``target`` and ``doc_id`` path segments are URL-encoded so IDs
        containing ``/``, ``%``, ``#``, ``?``, or spaces round-trip through
        the engine (feat_index_document_browser spec D-25 + AC-16).
        """
        from urllib.parse import quote

        encoded_target = quote(target, safe="")
        encoded_doc_id = quote(doc_id, safe="")
        try:
            resp = await self._request(
                "GET",
                f"/{encoded_target}/_doc/{encoded_doc_id}",
                request_id=request_id,
                translate_errors=False,
            )
        except httpx.HTTPError as exc:
            raise ClusterUnreachableError(str(exc)) from exc
        if resp.status_code in (401, 403):
            raise TargetsForbiddenError(
                f"cluster denied document fetch (HTTP {resp.status_code} from /_doc/...)"
            )
        if resp.status_code == 404:
            # 404 may come from an intermediate proxy as a non-JSON HTML page
            # rather than an ES envelope — guard the .json() call so we
            # surface a typed adapter error instead of bubbling a
            # JSONDecodeError as a 500 (per Gemini cycle-1 finding #1).
            try:
                payload = resp.json()
            except (ValueError, TypeError):
                payload = None
            if (
                isinstance(payload, dict)
                and isinstance(payload.get("error"), dict)
                and payload["error"].get("type") == "index_not_found_exception"
            ):
                raise TargetNotFoundError(target)
            # found: false → return None
            return None
        if resp.status_code >= 400:
            raise ClusterUnreachableError(
                f"HTTP {resp.status_code} from /{encoded_target}/_doc/{encoded_doc_id}"
            )
        payload = resp.json()
        return Document(doc_id=payload["_id"], source=payload.get("_source"))

    async def list_documents(
        self,
        target: str,
        *,
        search_after: list[Any] | None = None,
        limit: int = 25,
        fields: list[str] | None = None,
        request_id: str | None = None,
    ) -> DocumentPage:
        """Paginated browse via _search + match_all + search_after.

        feat_index_document_browser FR-2 + spec D-26 / D-24.

        Request body locks:
        * ``"sort": [{"_doc": "asc"}]`` — pagination key. The spec's primary
          choice was ``_id``, but ES 9 disallows ``_id`` fielddata by default
          (``indices.id_field_data.enabled`` is off, surfaced as HTTP 400 on
          first probe). ``_doc`` is the spec D-26 fallback — shard-internal
          but always available, and ``search_after`` works against it
          identically. Tradeoff acknowledged: shard rebalancing could shift
          ``_doc`` IDs and corrupt cursor continuity. For the MVP1 browse use
          case (read-only operator inspection) this is acceptable. The
          PIT + ``_shard_doc`` fallback remains available if shard churn
          becomes a real-world problem.
        * ``"track_total_hits": true`` — preserves exact ``hits.total.value``
          for the router's ``X-Total-Count`` header (D-24; without this ES
          caps total at 10000).

        Error envelope matches :meth:`get_document` (401/403 → TargetsForbidden,
        404 index_not_found → TargetNotFoundError, etc.).

        Returns a :class:`DocumentPage` with up to ``limit`` hits, each
        carrying its engine-native ``sort`` value so the router can encode
        the cursor from the in-body hit under its ``limit + 1`` overfetch
        pattern (per FR-3).
        """
        from urllib.parse import quote

        encoded_target = quote(target, safe="")
        body: dict[str, Any] = {
            "query": {"match_all": {}},
            "sort": [{"_doc": "asc"}],
            "size": limit,
            "track_total_hits": True,
        }
        if search_after is not None:
            body["search_after"] = search_after
        if fields is not None:
            body["_source"] = {"includes": fields}
        try:
            resp = await self._request(
                "POST",
                f"/{encoded_target}/_search",
                json=body,
                request_id=request_id,
                translate_errors=False,
            )
        except httpx.HTTPError as exc:
            raise ClusterUnreachableError(str(exc)) from exc
        if resp.status_code in (401, 403):
            raise TargetsForbiddenError(
                f"cluster denied _search (HTTP {resp.status_code} from /_search)"
            )
        if resp.status_code == 404:
            # Guarded JSON parse — see get_document for the rationale
            # (Gemini cycle-1 finding #2).
            try:
                payload = resp.json()
            except (ValueError, TypeError):
                payload = None
            if (
                isinstance(payload, dict)
                and isinstance(payload.get("error"), dict)
                and payload["error"].get("type") == "index_not_found_exception"
            ):
                raise TargetNotFoundError(target)
            raise ClusterUnreachableError(
                f"HTTP 404 from /{encoded_target}/_search "
                "(unexpected — not index_not_found_exception)"
            )
        if resp.status_code >= 400:
            raise ClusterUnreachableError(f"HTTP {resp.status_code} from /{encoded_target}/_search")
        payload = resp.json()
        hits_raw = payload.get("hits", {}).get("hits", [])
        total = int(payload.get("hits", {}).get("total", {}).get("value", 0))
        hits = [
            AdapterDocumentHit(
                doc_id=h["_id"],
                source=h.get("_source"),
                sort=h["sort"],  # fail-loud KeyError if engine omits sort under sort: [...] query
            )
            for h in hits_raw
        ]
        return DocumentPage(hits=hits, total=total)

    # ------------------------------------------------------------------
    # Cursor scan (chore_ubi_reader_search_after_pagination Story 2.1)
    # ------------------------------------------------------------------

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
        """ES + OpenSearch ``search_after``+PIT page (FR-2 / AC-2..AC-11).

        First page opens a PIT (engine-branched endpoint per
        :data:`_PIT_PATHS`) and issues the PIT-bound ``POST /_search``
        with the deterministic total-order sort
        ``[{timestamp: asc}, {_shard_doc: asc}]`` and ``size=page_size``.
        Each response's ``pit_id`` (when present) rotates the cursor's
        PIT id; the last hit's raw ``sort`` array becomes the next
        page's ``search_after``. Terminal page (short page) closes the
        PIT best-effort and returns ``cursor=None``.

        Continuation pages carry a non-None ``cursor`` produced by this
        method on the prior page — the caller round-trips it verbatim.
        Cursor shape (engine-internal, never inspected by the caller)::

            {"pit_id": "<rotated id>", "search_after": [...], "no_pit": False}

        Narrow PIT-unsupported fallback (405/501 from PIT open):

        * If ``Settings.ubi_no_pit_tiebreaker_field`` is configured →
          paginate ``[timestamp, <tiebreaker>]`` with ``search_after``
          and a ``no_pit=True`` cursor — terminal on short page.
        * Otherwise → single sampled query bounded by ``page_size`` and
          a WARN log; terminal immediately (``cursor=None``).

        401/403/404 propagate as ``TargetsForbiddenError`` /
        ``TargetNotFoundError`` — never silently fall back.

        Pagination keys are adapter-owned: caller-supplied ``pit`` /
        ``sort`` / ``size`` / ``search_after`` / ``from`` keys in
        ``body`` are stripped before request construction (so a stray
        caller ``pit`` does not leak into either the PIT-mode body
        merge or the no-PIT fallback request — P3-A1 / P5-A1).

        On any exception during the PIT-mode page, the PIT is closed
        best-effort in ``finally`` (catch+log close failures, re-raise
        the primary — P3-A2). Terminal-close failure is also best-
        effort: log + still return ``ScanPage(cursor=None)`` so a close
        failure cannot mask a successful final page (P4-A3).
        """
        # ----- Decode + validate the inbound cursor -----
        pit_id: str | None = None
        search_after: list[Any] | None = None
        no_pit = False
        if cursor is not None:
            if not isinstance(cursor, dict):
                # Defensive: an unrecognized cursor shape is operator error.
                # Treat as terminal so we never run an unbounded scan; the
                # caller-side test surfaces the contract violation loudly.
                raise ClusterUnreachableError(
                    f"ElasticAdapter.scan_all: unrecognized cursor shape "
                    f"{type(cursor).__name__!r} — must be a dict produced by this adapter"
                )
            pit_id = cursor.get("pit_id") if isinstance(cursor.get("pit_id"), str) else None
            sa = cursor.get("search_after")
            if isinstance(sa, list):
                search_after = sa
            no_pit = bool(cursor.get("no_pit"))

        # ----- Strip caller-owned pagination keys (P3-A1 / P5-A1) -----
        safe_body = {k: v for k, v in body.items() if k not in _ES_PAGINATION_STRIP_KEYS}
        if fl is not None:
            safe_body["_source"] = {"includes": list(fl)}

        # ----- First-page PIT open (or no-PIT fallback trigger) -----
        if cursor is None:
            try:
                pit_id = await self._open_pit(target, request_id=request_id)
            except _PitUnsupportedError:
                # Narrow fallback — degrade to no-PIT path.
                return await self._scan_no_pit(
                    target,
                    safe_body,
                    page_size=page_size,
                    search_after=None,
                    request_id=request_id,
                )

        # ----- No-PIT continuation -----
        if no_pit:
            return await self._scan_no_pit(
                target,
                safe_body,
                page_size=page_size,
                search_after=search_after,
                request_id=request_id,
            )

        # ----- PIT-mode page (first or continuation) -----
        # `pit_id` is guaranteed non-None here: either the open succeeded
        # (first page) or the continuation cursor carried one. mypy narrows
        # via the explicit guard below.
        if not pit_id:
            raise ClusterUnreachableError(
                "ElasticAdapter.scan_all: PIT-mode continuation cursor missing pit_id"
            )

        try:
            request_body: dict[str, Any] = {
                **safe_body,
                "pit": {"id": pit_id, "keep_alive": _PIT_KEEP_ALIVE},
                "sort": [{"timestamp": "asc"}, {"_shard_doc": "asc"}],
                "size": page_size,
            }
            if search_after is not None:
                request_body["search_after"] = search_after

            # PIT-bound search is INDEX-LESS (the PIT binds the target).
            resp = await self._request(
                "POST",
                "/_search",
                json=request_body,
                request_id=request_id,
                translate_errors=False,
            )
            self._raise_scan_search_errors(resp, path="/_search (PIT)")
            payload = resp.json()

            # Rotate the PIT id. Both ES + OpenSearch echo the rotated id
            # under "pit_id" in the PIT-mode _search response. If absent,
            # retain the prior id (the server kept it stable).
            rotated = payload.get("pit_id")
            if isinstance(rotated, str) and rotated:
                pit_id = rotated

            hits_raw = payload.get("hits", {}).get("hits", [])
            hits: list[ScoredHit] = []
            last_sort: list[Any] | None = None
            for h in hits_raw:
                hits.append(
                    ScoredHit(
                        doc_id=str(h.get("_id", "")),
                        score=float(h.get("_score") or 0.0),
                        source=h.get("_source"),
                    )
                )
                sort_arr = h.get("sort")
                if isinstance(sort_arr, list):
                    last_sort = sort_arr

            # Terminal detection: short page or no usable last_sort.
            terminal = last_sort is None or len(hits) < page_size

            if terminal:
                # Best-effort terminal close (P4-A3) — log + swallow on
                # failure so the final page is still returned.
                await self._close_pit_best_effort(pit_id, request_id=request_id)
                return ScanPage(hits=hits, cursor=None)

            return ScanPage(
                hits=hits,
                cursor={
                    "pit_id": pit_id,
                    "search_after": last_sort,
                    "no_pit": False,
                },
            )
        except Exception:
            # Best-effort exception-path cleanup (P3-A2).
            await self._close_pit_best_effort(pit_id, request_id=request_id)
            raise

    async def close_scan(
        self,
        cursor: object | None,
        *,
        request_id: str | None = None,
    ) -> None:
        """Release any PIT held by a non-terminal ``scan_all`` cursor.

        No-op when ``cursor`` is ``None``, when the cursor was produced
        by the no-PIT fallback path (``no_pit=True``), or when its
        ``pit_id`` is missing. Idempotent. Cleanup is best-effort: a
        close failure is logged and swallowed (never re-raised) so the
        caller's primary exception is never masked.

        Wire shape:

        * ES → ``DELETE /_pit`` body ``{"id": <pit_id>}``.
        * OpenSearch → ``DELETE /_search/point_in_time`` body
          ``{"pit_id": [<pit_id>]}``.
        """
        if cursor is None or not isinstance(cursor, dict):
            return
        if cursor.get("no_pit"):
            return
        pit_id = cursor.get("pit_id")
        if not isinstance(pit_id, str) or not pit_id:
            return
        await self._close_pit_best_effort(pit_id, request_id=request_id)

    # ----- scan_all helpers (private) -----

    async def _open_pit(self, target: str, *, request_id: str | None) -> str:
        """Open a PIT against ``target``; return its id.

        Engine-branched (P4-A1):

        * ES: ``POST /<target>/_pit?keep_alive=<ttl>`` → response carries
          ``{"id": <pit_id>}``.
        * OpenSearch: ``POST /<target>/_search/point_in_time?keep_alive=<ttl>``
          → response carries ``{"pit_id": <pit_id>}`` (P2-A2).

        Narrow PIT-unsupported fallback signals (raise
        :class:`_PitUnsupportedError`): HTTP 405, 501, or 400 whose
        response body indicates the endpoint is unsupported.

        Other statuses propagate via the standard error taxonomy
        (``TargetsForbiddenError`` on 401/403,
        ``TargetNotFoundError`` when the response carries
        ``index_not_found_exception``, otherwise
        ``ClusterUnreachableError``).
        """
        encoded = quote(target, safe="")
        open_path, _ = _PIT_PATHS[self.engine_type]
        path = open_path.format(idx=encoded)
        response_id_field = "id" if self.engine_type == "elasticsearch" else "pit_id"

        try:
            resp = await self._request(
                "POST",
                path,
                params={"keep_alive": _PIT_KEEP_ALIVE},
                request_id=request_id,
                translate_errors=False,
            )
        except httpx.HTTPError as exc:
            raise ClusterUnreachableError(str(exc)) from exc

        if resp.status_code in (401, 403):
            raise TargetsForbiddenError(
                f"cluster denied PIT open (HTTP {resp.status_code} from {path})"
            )
        if resp.status_code == 404:
            try:
                payload = resp.json()
            except (ValueError, TypeError):
                payload = None
            if (
                isinstance(payload, dict)
                and isinstance(payload.get("error"), dict)
                and payload["error"].get("type") == "index_not_found_exception"
            ):
                raise TargetNotFoundError(target)
            # 404 on the PIT endpoint itself — propagate as unreachable.
            raise ClusterUnreachableError(f"HTTP 404 from {path}")
        if resp.status_code in (405, 501):
            raise _PitUnsupportedError(f"HTTP {resp.status_code} from {path}")
        if resp.status_code == 400:
            # 400 may be a real client error OR "endpoint unsupported" on
            # an older OSS distribution. Narrow: look for the unsupported
            # hint in the response body before treating as a fallback
            # trigger.
            body_text = resp.text or ""
            lowered = body_text.lower()
            if (
                "no handler" in lowered
                or "unsupported" in lowered
                or "not supported" in lowered
                or "unknown" in lowered
            ):
                raise _PitUnsupportedError(
                    f"HTTP 400 from {path} indicates PIT unsupported: {body_text[:200]}"
                )
            raise ClusterUnreachableError(f"HTTP 400 from {path}: {body_text[:200]}")
        if resp.status_code >= 400:
            raise ClusterUnreachableError(f"HTTP {resp.status_code} from {path}")

        try:
            payload = resp.json()
        except (ValueError, TypeError) as exc:
            raise ClusterUnreachableError(f"PIT open response not JSON: {exc}") from exc

        pit_id = payload.get(response_id_field)
        if not isinstance(pit_id, str) or not pit_id:
            raise ClusterUnreachableError(
                f"PIT open response missing {response_id_field!r}: {payload}"
            )
        return pit_id

    async def _close_pit_best_effort(self, pit_id: str | None, *, request_id: str | None) -> None:
        """Close a PIT; catch + log any failure (never re-raise).

        Engine-branched (P4-A1) wire bodies (P2-A2):

        * ES → ``DELETE /_pit`` body ``{"id": <pit_id>}``.
        * OpenSearch → ``DELETE /_search/point_in_time`` body
          ``{"pit_id": [<pit_id>]}``.
        """
        if not pit_id:
            return
        _, close_path = _PIT_PATHS[self.engine_type]
        if self.engine_type == "opensearch":
            close_body: dict[str, Any] = {"pit_id": [pit_id]}
        else:
            close_body = {"id": pit_id}
        try:
            await self._request(
                "DELETE",
                close_path,
                json=close_body,
                request_id=request_id,
                translate_errors=False,
            )
        except Exception as exc:  # noqa: BLE001 — best-effort cleanup
            logger.warning(
                "elastic_scan_close_pit_failed",
                event_type="elastic_scan_close_pit_failed",
                cluster_id=self.cluster_id,
                engine_type=self.engine_type,
                error_type=type(exc).__name__,
            )

    async def _scan_no_pit(
        self,
        target: str,
        safe_body: dict[str, Any],
        *,
        page_size: int,
        search_after: list[Any] | None,
        request_id: str | None,
    ) -> ScanPage:
        """No-PIT fallback page.

        Two sub-paths (D-8 / AC-3 / AC-3b):

        * If :attr:`Settings.ubi_no_pit_tiebreaker_field` is configured
          → paginate ``[timestamp, <tiebreaker>]`` with
          ``search_after``; terminal on short page; non-terminal cursor
          carries ``{search_after, no_pit: True}``.
        * Otherwise → single sampled query (size capped to
          ``page_size``); WARN logged; terminal immediately
          (``cursor=None``). Sampled mode IS the documented fallback —
          callers see WARN in their logs as the signal that exact
          full-traffic aggregation is degraded on this cluster.

        NEVER sorts on ``_id`` (ES 9 disallows ``_id`` fielddata).
        """
        # Lazy import — Settings is constructed at request time and
        # avoids a module-import cycle (Settings imports adapters
        # transitively at boot).
        from backend.app.core.settings import get_settings

        settings = get_settings()
        tiebreaker = settings.ubi_no_pit_tiebreaker_field

        encoded = quote(target, safe="")
        path = f"/{encoded}/_search"

        if tiebreaker:
            request_body: dict[str, Any] = {
                **safe_body,
                "sort": [{"timestamp": "asc"}, {tiebreaker: "asc"}],
                "size": page_size,
            }
            if search_after is not None:
                request_body["search_after"] = search_after
        else:
            # Sampled mode — single page, no continuation.
            logger.warning(
                "elastic_scan_no_pit_sampled_fallback",
                event_type="elastic_scan_no_pit_sampled_fallback",
                cluster_id=self.cluster_id,
                engine_type=self.engine_type,
                target=target,
                reason="pit_unsupported_and_no_tiebreaker_configured",
                page_size=page_size,
            )
            request_body = {**safe_body, "size": page_size}

        try:
            resp = await self._request(
                "POST",
                path,
                json=request_body,
                request_id=request_id,
                translate_errors=False,
            )
        except httpx.HTTPError as exc:
            raise ClusterUnreachableError(str(exc)) from exc
        self._raise_scan_search_errors(resp, path=path)
        payload = resp.json()

        hits_raw = payload.get("hits", {}).get("hits", [])
        hits: list[ScoredHit] = []
        last_sort: list[Any] | None = None
        for h in hits_raw:
            hits.append(
                ScoredHit(
                    doc_id=str(h.get("_id", "")),
                    score=float(h.get("_score") or 0.0),
                    source=h.get("_source"),
                )
            )
            sort_arr = h.get("sort")
            if isinstance(sort_arr, list):
                last_sort = sort_arr

        # Sampled mode is single-page; tiebreaker mode walks until short.
        if not tiebreaker:
            return ScanPage(hits=hits, cursor=None)
        if last_sort is None or len(hits) < page_size:
            return ScanPage(hits=hits, cursor=None)
        return ScanPage(
            hits=hits,
            cursor={"pit_id": None, "search_after": last_sort, "no_pit": True},
        )

    def _raise_scan_search_errors(self, resp: httpx.Response, *, path: str) -> None:
        """Translate non-2xx ``_search`` responses for the scan path.

        Same envelope as :meth:`list_documents` (401/403 → TargetsForbidden,
        404 + ``index_not_found_exception`` → TargetNotFoundError, other
        4xx/5xx → ClusterUnreachableError). Extracted so PIT-mode and
        no-PIT-mode both apply it identically.
        """
        if resp.status_code in (401, 403):
            raise TargetsForbiddenError(
                f"cluster denied _search (HTTP {resp.status_code} from {path})"
            )
        if resp.status_code == 404:
            try:
                payload = resp.json()
            except (ValueError, TypeError):
                payload = None
            if (
                isinstance(payload, dict)
                and isinstance(payload.get("error"), dict)
                and payload["error"].get("type") == "index_not_found_exception"
            ):
                # We don't have the un-encoded target here; the path string is
                # the next-best diagnostic anchor for operators.
                raise TargetNotFoundError(path)
            raise ClusterUnreachableError(f"HTTP 404 from {path}")
        if resp.status_code >= 400:
            raise ClusterUnreachableError(f"HTTP {resp.status_code} from {path}")


# ------------------------------------------------------------------
# Cursor scan module-level constants (Story 2.1)
# ------------------------------------------------------------------

_PIT_KEEP_ALIVE = "1m"
"""Default ``keep_alive`` sent on PIT open + every PIT-mode continuation.

1 minute is long enough that a multi-page reader scan doesn't expire
between consecutive ``POST /_search`` calls under normal latency, and
short enough that a leaked PIT (e.g. operator kills the worker mid-
scan) self-clears quickly. Sent on EVERY continuation — the engine
extends the TTL on each touch."""


_PIT_PATHS: dict[EngineType, tuple[str, str]] = {
    # (open_path_template, close_path) — open is indexed, close is unindexed.
    "elasticsearch": ("/{idx}/_pit", "/_pit"),
    "opensearch": ("/{idx}/_search/point_in_time", "/_search/point_in_time"),
    # solr is handled by SolrAdapter (cursorMark) — never reaches here.
    "solr": ("", ""),
}
"""Engine-branched PIT endpoints (P4-A1 / P2-A2).

The plan locks the open vs close split: open is indexed (the PIT binds
the target); close is unindexed (the PIT id alone identifies the
resource). The no-writes allowlist in
``test_ubi_reader_no_writes.py`` permits only the unindexed close
paths."""


_ES_PAGINATION_STRIP_KEYS: frozenset[str] = frozenset(
    {"from", "search_after", "size", "sort", "pit"}
)
"""Caller-supplied keys stripped from the inherited ``body`` before
``scan_all`` constructs the request (P3-A1 / P5-A1).

Pagination is adapter-owned: any of these keys in the caller's body
gets stripped (in BOTH the PIT and no-PIT fallback paths) so a stray
key cannot leak into the request and disrupt cursor continuity. ``pit``
is included so a caller PIT object does NOT leak into the no-PIT
fallback ``POST /<target>/_search`` after PIT open returned a fallback
signal (P5-A1)."""


class _PitUnsupportedError(Exception):
    """Internal signal: PIT open returned a narrow-fallback status.

    Raised by :meth:`ElasticAdapter._open_pit` on HTTP 405/501 or 400
    whose body indicates the endpoint is unsupported. Caught by
    :meth:`ElasticAdapter.scan_all` to trigger the no-PIT fallback.
    Never propagates to callers — it is strictly an adapter-internal
    control-flow signal.
    """


def _build_explain_tree(node: dict[str, Any], doc_id: str, matched: bool) -> ExplainTree:
    """Recursively build an ``ExplainTree`` from the engine's nested explanation node."""
    return ExplainTree(
        doc_id=doc_id,
        matched=matched,
        value=float(node.get("value", 0.0)),
        description=str(node.get("description", "")),
        details=[_build_explain_tree(child, doc_id, matched) for child in node.get("details", [])],
    )
