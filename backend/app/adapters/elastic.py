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
from typing import Any

import httpx

from backend.app.adapters.credentials import resolve_credentials
from backend.app.adapters.errors import ClusterUnreachableError
from backend.app.adapters.protocol import (
    EngineType,
    ExplainTree,
    NativeQuery,
    ParamValue,
    QueryTemplate,
    Schema,
    ScoredHit,
    TargetInfo,
)

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

    async def health_check(self, *, request_id: str | None = None) -> Any:
        """Stub — implemented in Story 2.2."""
        raise NotImplementedError("Story 2.2")

    async def list_targets(self, *, request_id: str | None = None) -> list[TargetInfo]:
        """Stub — implemented in Story 2.3."""
        raise NotImplementedError("Story 2.3")

    async def get_schema(self, target: str, *, request_id: str | None = None) -> Schema:
        """Stub — implemented in Story 2.3."""
        raise NotImplementedError("Story 2.3")

    def list_query_parsers(self) -> list[str]:
        """Stub — implemented in Story 2.3."""
        raise NotImplementedError("Story 2.3")

    def render(
        self,
        template: QueryTemplate,
        params: dict[str, ParamValue],
        query_text: str,
    ) -> NativeQuery:
        """Stub — implemented in Story 2.4."""
        raise NotImplementedError("Story 2.4")

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
        """Stub — implemented in Story 2.5."""
        raise NotImplementedError("Story 2.5")

    async def explain(
        self,
        target: str,
        query: NativeQuery,
        doc_id: str,
        *,
        request_id: str | None = None,
    ) -> ExplainTree:
        """Stub — implemented in Story 2.6."""
        raise NotImplementedError("Story 2.6")
