# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""SolrAdapter — Apache Solr 9.x + 10.x adapter (infra_adapter_solr Story A1+).

Single adapter for SolrCloud and standalone Solr — modes are auto-detected via
capability probe (``probe_capabilities``). The wire surface RelyLoop uses
(``/admin/info/system``, ``/admin/zookeeper/status``, ``/admin/collections``,
``/admin/cores``, ``/<target>/schema/...``, ``/<target>/select``,
``/<target>/get``, ``/<target>/config/...``) is stable across Solr 9 and 10.

Per CLAUDE.md Absolute Rule #4, no engine-specific code lives outside this
module — services consume the unified ``SearchAdapter`` Protocol from
``backend.app.adapters.protocol``.

I/O methods are async (``httpx.AsyncClient``); ``render`` /
``list_query_parsers`` stay synchronous per the Protocol. ``aclose()`` MUST be
called when the adapter goes out of scope (the service layer wraps registration
probes in ``try/finally``; ``acquire_adapter`` in ``services/cluster.py`` does
the same for transient adapters).

Story A1 lands the skeleton:

* ``__init__`` — auth_kind allowlist validation, BasicAuth + Bearer header build.
* ``_request`` — single-retry on connection-class failures, typed error mapping.
* ``health_check`` — full implementation; lazy-fetches version + enforces
  ``SOLR_MIN_VERSION`` floor (9.0).
* ``list_query_parsers`` — full implementation; returns the static set
  ``["edismax", "dismax", "lucene"]`` (no HTTP call).
* ``probe_capabilities`` — full implementation; returns ``ProbeResult``.
* Other Protocol methods (``list_targets``, ``get_schema``, ``render``,
  ``search_batch``, ``explain``, ``get_document``, ``list_documents``) raise
  ``NotImplementedError`` until Stories A2–A8 land. The Protocol-conformance
  test only checks shape (``isinstance``), not behavior, so the NotImplementedError
  stubs are intentional during incremental delivery.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from pydantic import BaseModel

from backend.app.adapters.credentials import resolve_credentials
from backend.app.adapters.errors import (
    ClusterUnreachableError,
    InvalidQueryDSLError,
    QueryTimeoutError,
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
    Schema,
    ScoredHit,
    TargetInfo,
)
from backend.app.adapters.registry import (
    RESERVED_AUTH_KINDS,
    SUPPORTED_AUTH_KINDS,
)

SOLR_MIN_VERSION: tuple[int, int] = (9, 0)
"""Apache Solr minimum supported version (spec FR-2)."""

SOLR_MODE_VALUES = Literal["cloud", "standalone"]
"""Solr deployment mode — auto-detected by the capability probe."""

# Targets returned by ``/admin/collections?action=LIST`` or
# ``/admin/cores?action=STATUS`` that should never surface to operators.
# Names starting with ``.`` are also excluded (Solr-system convention).
_SOLR_SYSTEM_TARGETS: frozenset[str] = frozenset({".system", "_default"})


def _format_number(value: int | float) -> str:
    """Render a number for a Solr request param.

    Floats use Python's ``repr`` shortest-round-trip form (``0.3``, not
    ``0.29999999999999999``); ints render without a decimal point. Solr
    parses both.
    """
    if isinstance(value, bool):
        # Defensive: ``bool`` is a subclass of ``int``; keep its wire shape
        # explicit instead of writing "True" / "False".
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    # float — repr gives the shortest round-trip representation.
    return repr(value)


def _join_field_boosts(value: dict[str, Any]) -> str:
    """Render ``{field: boost}`` as Solr's space-separated ``"f1^b1 f2^b2"``.

    Insertion order from the dict is preserved. Boost values may be int or
    float. Missing boosts (None) raise — the template must declare them.
    """
    parts: list[str] = []
    for field, boost in value.items():
        if boost is None:
            raise InvalidQueryDSLError(f"field_boosts: missing boost for field {field!r}")
        if not isinstance(boost, (int, float)):
            raise InvalidQueryDSLError(
                f"field_boosts[{field!r}]: boost must be a number, got {type(boost).__name__}"
            )
        parts.append(f"{field}^{_format_number(boost)}")
    return " ".join(parts)


# Lucene query metacharacters that must be escaped when injecting an
# arbitrary value (like a doc_id) into a Lucene/Solr query string. Source:
# Solr Ref Guide "Standard Query Parser" + Lucene QueryParser javadoc.
_LUCENE_META = set('+-&|!(){}[]^"~*?:\\/')


def _lucene_escape(value: str) -> str:
    """Escape Lucene query metacharacters in ``value``.

    URL encoding is a *separate* concern handled by httpx when the params
    are serialized — Solr decodes the URL, then parses the value as a
    Lucene expression. Both stages need escaping (URL encoding hides ``/``
    from the URL parser; Lucene escaping hides ``/`` from the Lucene
    parser). Without the Lucene escape, a doc_id like ``a/b`` would be
    interpreted as a regex query.
    """
    out: list[str] = []
    for ch in value:
        if ch in _LUCENE_META or ch.isspace():
            out.append("\\" + ch)
        else:
            out.append(ch)
    return "".join(out)


def _solr_explain_to_unified(node: dict[str, Any], *, doc_id: str) -> ExplainTree:
    """Convert one node of Solr's debug.explain tree into a unified ExplainTree.

    Solr keys: ``match`` (bool), ``value`` (float), ``description`` (str),
    ``details`` (list of nested nodes). The unified shape mirrors the same
    semantics; ``matched`` is the unified key for ``match``.
    """
    children: list[ExplainTree] = []
    for child in node.get("details") or []:
        if isinstance(child, dict):
            children.append(_solr_explain_to_unified(child, doc_id=doc_id))
    return ExplainTree(
        doc_id=doc_id,
        matched=bool(node.get("match", False)),
        value=float(node.get("value", 0.0)),
        description=str(node.get("description", "")),
        details=children,
    )


def _normalize_fl(existing: Any, unique_key: str) -> str:
    """Merge ``score`` AND ``unique_key`` into a Solr ``fl`` request param.

    Without ``score`` in ``fl``, Solr's response.docs entries omit the
    ``score`` field (it's not returned by default) and
    ``search_batch._consume_search_result`` skips those docs as malformed.
    Without ``unique_key``, the parser can't extract ``doc_id``.

    Cases:
    * ``existing`` is None / empty → ``"*,score"`` (default).
    * ``existing`` is ``"*"`` or ``"*,score"`` → leave alone (``*`` already
      pulls every field including the uniqueKey).
    * ``existing`` is a comma-separated list → prepend ``score`` and
      ``unique_key`` if missing; dedupe while preserving order.
    """
    if existing is None or existing == "":
        return "*,score"
    if not isinstance(existing, str):
        existing = str(existing)
    fields = [f.strip() for f in existing.split(",") if f.strip()]
    if "*" in fields and "score" in fields:
        return ",".join(fields)
    if "*" in fields:
        # Append score after the wildcard so callers can see we added it.
        if "score" not in fields:
            fields.append("score")
        return ",".join(fields)
    # Specific field list — prepend score + unique_key if absent.
    needed: list[str] = []
    if "score" not in fields:
        needed.append("score")
    if unique_key not in fields:
        needed.append(unique_key)
    return ",".join(needed + fields)


def _coerce_to_solr_param_value(value: Any) -> Any:
    """Coerce a Solr-native template value to its request-param wire form.

    Solr request params are strings (the ``/select?key=value`` query string
    accepts only strings) or lists of strings (for repeated params like
    ``fq``). The template emits Python ints/floats/bools/strings; this
    helper normalizes to the wire shape without losing the repeated-list
    semantics.
    """
    if isinstance(value, list):
        return [_coerce_to_solr_param_value(v) for v in value]
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _format_number(value)
    if isinstance(value, str):
        return value
    # Fallback: dict / None / something else — leave as-is and let Solr
    # complain. The pivot path handles dicts (qf, pf, boost_fn,
    # rerank_model); Solr-native dict-valued params are rare but exist
    # (e.g., local params via ``{!key=value}``) and are template-author
    # responsibility.
    return value


class ProbeResult(BaseModel):
    """Capability probe output.

    Written to ``clusters.engine_config`` by the service layer
    (``services.cluster.register_cluster`` / ``reprobe_cluster``).

    The adapter itself does NOT persist this — it returns it; the service
    layer writes it inside the same transaction as the row INSERT/UPDATE so
    a probe failure rolls the row back atomically (spec FR-2 / Story A9).
    """

    version: str
    """Solr engine version (e.g. ``"10.0.0"``)."""

    mode: SOLR_MODE_VALUES
    """``cloud`` if ``/admin/zookeeper/status`` responded 200, else ``standalone``."""

    ubi_component_present: bool
    """``solr.UBIComponent`` is registered as a searchComponent on at least
    one of the enumerated targets."""

    ltr_module_present: bool
    """The LTR module (``solr.ltr.LTRQParserPlugin``) is loaded and reachable
    via ``/<target>/config/queryParser``."""

    ltr_models: list[str]
    """LTR model names listed in ``/<target>/schema/model-store`` for the
    first enumerated target. Per-collection in Solr (not cluster-wide) — see
    the runbook for the maintenance implications."""

    unique_key_per_target: dict[str, str]
    """{target_name: uniqueKey_field_name} — populated from
    ``/<target>/schema/uniquekey`` for every enumerated target. Solr's
    ``uniqueKey`` is configurable per collection (typically ``id`` but may be
    ``sku``/``pk``/etc.); ``search_batch``/``explain``/``get_document`` resolve
    against this map rather than hardcoding ``"id"``."""


class SolrAdapter:
    """Engine adapter for Apache Solr 9.x + 10.x (cloud + standalone)."""

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
        """Construct a Solr adapter; validates the auth_kind allowlist immediately."""
        if auth_kind in RESERVED_AUTH_KINDS:
            raise NotImplementedError(f"{auth_kind!r} is reserved but not implemented in MVP2")
        if auth_kind not in SUPPORTED_AUTH_KINDS:
            raise ValueError(f"unknown auth_kind: {auth_kind!r}")
        if auth_kind not in ("solr_basic", "solr_apikey"):
            raise ValueError(
                f"auth_kind {auth_kind!r} is not valid for engine_type='solr' "
                "(valid: solr_basic, solr_apikey)"
            )
        if engine_type != "solr":
            raise ValueError(f"SolrAdapter requires engine_type='solr', got {engine_type!r}")
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
        # Adapter-side memory-only cache for uniqueKey lookups against targets
        # created AFTER cluster registration (and therefore absent from
        # engine_config.unique_key_per_target). Not persisted — Story A8
        # spec FR-9 requires service-layer-only writes to engine_config.
        # The cache is seeded lazily on the first get_document/list_documents
        # call against a new target; survives the adapter's lifetime only.
        seeded: dict[str, str] = dict(self.engine_config.get("unique_key_per_target", {}) or {})
        self._unique_key_cache: dict[str, str] = seeded

    def _build_auth_headers(self) -> dict[str, str]:
        """Resolve mounted credentials and build the static Authorization header.

        * ``solr_basic`` → ``Authorization: Basic <base64(user:password)>``
          for ``BasicAuthPlugin``.
        * ``solr_apikey`` → ``Authorization: Bearer <jwt_token>`` for Solr 9+
          ``JWTAuthPlugin``. ``refresh_url`` is out of scope for MVP2 per spec
          FR-3 — the credential file may carry it as metadata but the adapter
          ignores it.
        """
        creds = resolve_credentials(self.auth_kind, self.credentials_ref)
        if self.auth_kind == "solr_basic":
            token = base64.b64encode(f"{creds['username']}:{creds['password']}".encode()).decode()
            return {"Authorization": f"Basic {token}"}
        if self.auth_kind == "solr_apikey":
            return {"Authorization": f"Bearer {creds['jwt_token']}"}
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

        Mirrors ``ElasticAdapter._request``: connection-class failures are
        retried exactly once before propagating; ``translate_errors=True``
        maps retried-and-still-failed connection errors + 401/403/5xx to
        ``ClusterUnreachableError``. ``health_check`` opts out so it can own
        its own status mapping.

        ``X-Request-Id`` carries the operator-supplied correlation id. (Solr
        does not have an ES-style ``X-Opaque-Id`` convention; ``X-Request-Id``
        is the canonical project-wide correlation header.)
        """
        headers = dict(self._auth_headers)
        if extra_headers:
            headers.update(extra_headers)
        if request_id:
            headers["X-Request-Id"] = request_id

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

        resp: httpx.Response | None = None
        for attempt in (1, 2):
            try:
                resp = await self._client.request(**kwargs)
                break
            except httpx.ReadTimeout as exc:
                # Distinct from connection errors at the typed-exception layer:
                # callers (search_batch with strict_errors=True) need
                # QueryTimeoutError to translate to 504 QUERY_TIMEOUT rather
                # than 503 CLUSTER_UNREACHABLE.
                if attempt == 2:
                    if translate_errors:
                        raise QueryTimeoutError(str(exc)) from exc
                    raise
                continue
            except connection_excs as exc:
                if attempt == 2:
                    if translate_errors:
                        raise ClusterUnreachableError(str(exc)) from exc
                    raise
                continue
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
    # Capability probe (Story A1, FR-2)
    # ------------------------------------------------------------------

    async def probe_capabilities(self, *, request_id: str | None = None) -> ProbeResult:
        """Probe Solr capabilities + enumerate uniqueKey per target.

        Pure I/O; no DB writes (the service layer persists the result in the
        same transaction as the cluster row INSERT/UPDATE per spec FR-2).

        The probe is robust to per-endpoint 404s — missing capabilities resolve
        to ``False`` / empty list rather than propagating exceptions. The only
        connection-level failure path is ``ClusterUnreachableError`` from the
        very first ``/admin/info/system`` call (which also drives the version-
        floor check). On version below ``SOLR_MIN_VERSION`` the probe raises
        ``ClusterUnreachableError`` so the service layer rolls back the row
        atomically and returns 503 ``CLUSTER_UNREACHABLE`` (cycle 3 C3-F2).
        """
        # 1. Version + version-floor — REQUIRED. Any failure aborts the probe.
        info_resp = await self._request(
            "GET", "/solr/admin/info/system", request_id=request_id, translate_errors=False
        )
        if info_resp.status_code in (401, 403):
            raise ClusterUnreachableError(
                f"Authentication failed (HTTP {info_resp.status_code}) on /admin/info/system"
            )
        if info_resp.status_code != 200:
            raise ClusterUnreachableError(
                f"HTTP {info_resp.status_code} from /admin/info/system — cannot read Solr version"
            )
        info_body = info_resp.json()
        version = self._extract_version(info_body)
        if version is None:
            raise ClusterUnreachableError(
                "/admin/info/system response missing lucene.solr-spec-version "
                "— cannot enforce engine floor"
            )
        if not self._meets_min_version(version):
            raise ClusterUnreachableError(
                f"Solr {SOLR_MIN_VERSION[0]}.{SOLR_MIN_VERSION[1]} or later required "
                f"(cluster reports {version})"
            )
        self._version = version

        # 2. Mode detection — 200 zkStatus → cloud, otherwise standalone.
        mode = await self._detect_mode(request_id=request_id)

        # 3. Target enumeration (mode-dispatched).
        targets = await self._enumerate_targets(mode, request_id=request_id)

        # 4. uniqueKey per target — best-effort per-target probe.
        unique_key_per_target: dict[str, str] = {}
        for t in targets:
            uk = await self._fetch_unique_key(t, request_id=request_id)
            if uk is not None:
                unique_key_per_target[t] = uk

        # 5. LTR module presence (per spec FR-2): check the modules array on
        #    Solr 10+, fall back to the query-parser config on Solr 9.
        ltr_module_present = await self._detect_ltr_module(
            info_body, targets, request_id=request_id
        )

        # 6. LTR models — only if module is present; per-collection (first
        #    enumerated target). 404 → empty list.
        ltr_models: list[str] = []
        if ltr_module_present and targets:
            ltr_models = await self._fetch_ltr_models(targets[0], request_id=request_id)

        # 7. UBI component — first enumerated target's searchComponent config.
        ubi_component_present = False
        if targets:
            ubi_component_present = await self._detect_ubi_component(
                targets[0], request_id=request_id
            )

        # Refresh adapter-side cache so subsequent calls within this adapter
        # lifetime see the probed uniqueKeys without an extra schema/uniquekey
        # round-trip.
        self._unique_key_cache.update(unique_key_per_target)

        return ProbeResult(
            version=version,
            mode=mode,
            ubi_component_present=ubi_component_present,
            ltr_module_present=ltr_module_present,
            ltr_models=ltr_models,
            unique_key_per_target=unique_key_per_target,
        )

    @staticmethod
    def _extract_version(info_body: dict[str, Any]) -> str | None:
        """Pull ``lucene.solr-spec-version`` out of the ``/admin/info/system`` body.

        Solr 9 + 10 both expose this nested field; the top-level ``solr-spec-
        version`` is the same value on most distributions but the ``lucene``
        block is the canonical spec location.
        """
        lucene = info_body.get("lucene") or {}
        version = lucene.get("solr-spec-version")
        if isinstance(version, str) and version:
            return version
        # Fallback: top-level ``solr-spec-version`` exists on some distros.
        top = info_body.get("solr-spec-version")
        if isinstance(top, str) and top:
            return top
        return None

    @staticmethod
    def _meets_min_version(version: str) -> bool:
        """Compare ``version`` against ``SOLR_MIN_VERSION`` (major.minor).

        Bad/partial version strings (no dot, non-numeric) conservatively
        return False so the floor enforcement aborts registration rather than
        silently letting an unknown Solr through.
        """
        parts = [int(p) for p in version.split(".")[:2] if p.isdigit()]
        if len(parts) < 2:
            return False
        return (parts[0], parts[1]) >= SOLR_MIN_VERSION

    async def _detect_mode(self, *, request_id: str | None) -> SOLR_MODE_VALUES:
        """``GET /admin/zookeeper/status`` — 200 → cloud; anything else → standalone.

        SolrCloud always exposes ``zkStatus``; standalone Solr has no
        ZooKeeper at all and the endpoint returns 404 (Solr 9+) or 503.
        """
        try:
            resp = await self._request(
                "GET",
                "/solr/admin/zookeeper/status",
                request_id=request_id,
                translate_errors=False,
            )
        except (ClusterUnreachableError, QueryTimeoutError, httpx.HTTPError):
            return "standalone"
        if resp.status_code == 200:
            body = resp.json()
            # Belt-and-suspenders: status 200 with explicit zkStatus is cloud.
            if "zkStatus" in body or "zkStatus" in (body.get("zkStatus") or {}):
                return "cloud"
            # Some Solr distros return 200 with no zkStatus block in standalone
            # (unlikely but defensive).
            if body:
                return "cloud"
        return "standalone"

    async def _enumerate_targets(
        self, mode: SOLR_MODE_VALUES, *, request_id: str | None
    ) -> list[str]:
        """List collections (cloud) or cores (standalone), excluding system targets.

        404s on the listing endpoint yield an empty list rather than raising
        — the rest of the probe still resolves (operators may register a
        cluster before any collection exists; the probe then writes empty
        engine_config blocks).
        """
        if mode == "cloud":
            resp = await self._request(
                "GET",
                "/solr/admin/collections",
                params={"action": "LIST"},
                request_id=request_id,
                translate_errors=False,
            )
            if resp.status_code == 404:
                return []
            if resp.status_code >= 400:
                raise ClusterUnreachableError(f"HTTP {resp.status_code} from /admin/collections")
            body = resp.json()
            raw: list[Any] = body.get("collections") or []
            return [str(c) for c in raw if self._is_visible_target(str(c))]
        # standalone
        resp = await self._request(
            "GET",
            "/solr/admin/cores",
            params={"action": "STATUS", "indexInfo": "false"},
            request_id=request_id,
            translate_errors=False,
        )
        if resp.status_code == 404:
            return []
        if resp.status_code >= 400:
            raise ClusterUnreachableError(f"HTTP {resp.status_code} from /admin/cores")
        body = resp.json()
        status_block = body.get("status") or {}
        names: list[str] = []
        for name, defn in status_block.items():
            if self._is_visible_target(name):
                # Solr's ``status`` block keys ARE the core names; ``defn.name``
                # mirrors but is more authoritative when present.
                actual = defn.get("name") if isinstance(defn, dict) else None
                names.append(str(actual or name))
        return names

    @staticmethod
    def _is_visible_target(name: str) -> bool:
        """Exclude Solr-system targets (names starting with ``.`` or canonical names)."""
        if not name:
            return False
        if name.startswith("."):
            return False
        if name in _SOLR_SYSTEM_TARGETS:
            return False
        return True

    async def _fetch_unique_key(self, target: str, *, request_id: str | None) -> str | None:
        """``GET /<target>/schema/uniquekey`` → ``uniqueKey`` field name.

        404 → ``None`` (the probe simply omits that target from the map; the
        adapter's run-time cache will lazy-populate on first get_document call
        per spec FR-9). Other non-2xx → ``None`` (defensive; engine_config
        omission is recoverable).
        """
        try:
            resp = await self._request(
                "GET",
                f"/solr/{target}/schema/uniquekey",
                request_id=request_id,
                translate_errors=False,
            )
        except (ClusterUnreachableError, QueryTimeoutError, httpx.HTTPError):
            return None
        if resp.status_code != 200:
            return None
        body = resp.json()
        uk = body.get("uniqueKey")
        if isinstance(uk, str) and uk:
            return uk
        return None

    async def _detect_ltr_module(
        self,
        info_body: dict[str, Any],
        targets: list[str],
        *,
        request_id: str | None,
    ) -> bool:
        """Detect whether the LTR module is loaded.

        Solr 10+ exposes ``.system.modules`` (a list of loaded module names)
        in the ``/admin/info/system`` response — ``"ltr"`` in that list →
        ``True``. Solr 9 does not expose modules there; fall back to a
        per-collection ``GET /<target>/config/queryParser`` and look for the
        ``ltr`` parser registration (the LTR module installs that parser when
        loaded).
        """
        system_block = info_body.get("system") or {}
        modules = system_block.get("modules")
        if isinstance(modules, list) and "ltr" in modules:
            return True
        if not targets:
            return False
        try:
            resp = await self._request(
                "GET",
                f"/solr/{targets[0]}/config/queryParser",
                request_id=request_id,
                translate_errors=False,
            )
        except (ClusterUnreachableError, QueryTimeoutError, httpx.HTTPError):
            return False
        if resp.status_code != 200:
            return False
        body = resp.json()
        qparsers = body.get("config", {}).get("queryParser") or {}
        if isinstance(qparsers, dict) and "ltr" in qparsers:
            return True
        return False

    async def _fetch_ltr_models(self, target: str, *, request_id: str | None) -> list[str]:
        """``GET /<target>/schema/model-store`` → list of LTR model names.

        Solr's model-store is per-collection — the probe records the models
        visible on the FIRST enumerated target only. Operators with multi-
        collection LTR deployments rerun ``/reprobe`` after selecting the
        intended collection (documented in the runbook).
        """
        try:
            resp = await self._request(
                "GET",
                f"/solr/{target}/schema/model-store",
                request_id=request_id,
                translate_errors=False,
            )
        except (ClusterUnreachableError, QueryTimeoutError, httpx.HTTPError):
            return []
        if resp.status_code == 404:
            return []
        if resp.status_code != 200:
            return []
        body = resp.json()
        raw_models = body.get("models") or []
        out: list[str] = []
        for m in raw_models:
            if isinstance(m, dict):
                name = m.get("name")
                if isinstance(name, str) and name:
                    out.append(name)
        return out

    async def _detect_ubi_component(self, target: str, *, request_id: str | None) -> bool:
        """Detect whether ``solr.UBIComponent`` is registered on the target.

        Primary signal: ``GET /<target>/config/searchComponent`` → look for
        any registered component whose ``class`` equals ``solr.UBIComponent``.
        404 / non-200 → ``False`` (the cluster may not have the UBI module
        installed; the probe records that and the UI nudge prompts the
        operator to enable it).
        """
        try:
            resp = await self._request(
                "GET",
                f"/solr/{target}/config/searchComponent",
                request_id=request_id,
                translate_errors=False,
            )
        except (ClusterUnreachableError, QueryTimeoutError, httpx.HTTPError):
            return False
        if resp.status_code != 200:
            return False
        body = resp.json()
        components = body.get("config", {}).get("searchComponent") or {}
        if not isinstance(components, dict):
            return False
        for defn in components.values():
            if not isinstance(defn, dict):
                continue
            cls = defn.get("class")
            if isinstance(cls, str) and cls.lower().endswith("ubicomponent"):
                return True
        return False

    # ------------------------------------------------------------------
    # health_check (Story A1, FR-1) — full implementation.
    # ------------------------------------------------------------------

    async def health_check(self, *, request_id: str | None = None) -> HealthStatus:
        """Probe ``/solr/admin/info/system`` for reachability + version.

        Connection-class failures and unsupported versions surface as
        ``HealthStatus(status='unreachable', error=...)`` — never raised. The
        cluster service relies on this contract to translate to
        ``CLUSTER_UNREACHABLE`` (spec FR-1 / FR-2).

        On the FIRST successful call, the version is cached on the adapter
        instance — subsequent ``health_check`` calls skip the version-floor
        check (already passed) and return the cached value, mirroring
        ``ElasticAdapter``'s pattern.
        """
        now = datetime.now(UTC).isoformat()
        try:
            resp = await self._request(
                "GET",
                "/solr/admin/info/system",
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
                error=f"HTTP {resp.status_code} from /admin/info/system",
            )
        if resp.status_code in (401, 403):
            return HealthStatus(
                status="unreachable",
                checked_at=now,
                error=f"Authentication failed (HTTP {resp.status_code})",
            )
        if resp.status_code != 200:
            return HealthStatus(
                status="unreachable",
                checked_at=now,
                error=f"HTTP {resp.status_code} from /admin/info/system",
            )

        body = resp.json()
        version = self._extract_version(body)
        if version is None:
            return HealthStatus(
                status="unreachable",
                checked_at=now,
                error="/admin/info/system response missing lucene.solr-spec-version",
            )
        if not self._meets_min_version(version):
            return HealthStatus(
                status="unreachable",
                version=version,
                checked_at=now,
                error=(
                    f"Solr engine version {version} is below minimum "
                    f"{SOLR_MIN_VERSION[0]}.{SOLR_MIN_VERSION[1]}"
                ),
            )
        # Solr has no global ``cluster.status`` analog to ES — reachability +
        # version-floor compliance maps to green.
        self._version = version
        return HealthStatus(status="green", version=version, checked_at=now)

    # ------------------------------------------------------------------
    # list_query_parsers (Story A1) — full implementation, pure return.
    # ------------------------------------------------------------------

    def list_query_parsers(self) -> list[str]:
        """Return the static set of query parsers MVP2 Solr templates use.

        ``edismax`` is the primary; ``dismax`` and ``lucene`` are included for
        feature parity with the cross-engine parameter map. The list is
        stable across Solr 9 and 10 — no HTTP call needed.
        """
        return ["edismax", "dismax", "lucene"]

    # ------------------------------------------------------------------
    # Helpers shared with Stories A2–A8 — uniqueKey resolution.
    # ------------------------------------------------------------------

    async def _resolve_unique_key(self, target: str, *, request_id: str | None = None) -> str:
        """Return the ``uniqueKey`` field for ``target``.

        Lookup order:
        1. Adapter instance cache (seeded from ``engine_config.unique_key_per_target``
           at construction; refreshed by the probe).
        2. On miss → ``/<target>/schema/uniquekey`` (best-effort; cached on success).
        3. On failure → ``"id"`` fallback (Solr's universal default).

        Story A8 spec FR-9 forbids persisting NEW target uniqueKeys back to
        ``engine_config`` from the adapter — the service layer alone writes
        that field. The in-memory cache is per-adapter-instance and disappears
        on the next process restart; operators rerun ``/reprobe`` if they
        want the new uniqueKey persisted.
        """
        cached = self._unique_key_cache.get(target)
        if cached is not None:
            return cached
        fetched = await self._fetch_unique_key(target, request_id=request_id)
        resolved = fetched or "id"
        self._unique_key_cache[target] = resolved
        return resolved

    # ------------------------------------------------------------------
    # Protocol method stubs — Stories A2–A8 land these.
    # ------------------------------------------------------------------

    async def list_targets(
        self,
        *,
        request_id: str | None = None,
        target_filter: str | None = None,
    ) -> list[TargetInfo]:
        """List collections (cloud) or cores (standalone), filtered + system-excluded.

        Mode is read from ``self.engine_config["mode"]`` (populated by the
        probe at registration). When the mode is missing (engine_config not
        yet probed), defaults to detecting on the fly — the listing call
        itself is mode-specific, so a fresh detect is cheap.

        Applies ``target_filter`` glob via ``fnmatch.fnmatchcase`` mirroring
        ``ElasticAdapter.list_targets`` (system-target exclusion runs FIRST
        then glob filter so operators cannot re-expose system targets).

        Raises ``TargetsForbiddenError`` on 401/403 (Solr ``BasicAuthPlugin``
        denial); ``ClusterUnreachableError`` on 5xx / connection.
        """
        import fnmatch

        mode = self.engine_config.get("mode")
        if mode not in ("cloud", "standalone"):
            mode = await self._detect_mode(request_id=request_id)

        # Fetch raw targets + their doc-count (cores carry it directly; cloud
        # requires a per-collection /select?q=*:*&rows=0 to derive numFound).
        if mode == "cloud":
            raw_targets = await self._list_targets_cloud(request_id=request_id)
        else:
            raw_targets = await self._list_targets_standalone(request_id=request_id)

        # System-target exclusion runs FIRST.
        visible = [t for t in raw_targets if self._is_visible_target(t.name)]
        # Glob filter runs SECOND. Match the ElasticAdapter pattern exactly.
        if target_filter is not None:
            visible = [t for t in visible if fnmatch.fnmatchcase(t.name, target_filter)]
        return visible

    async def _list_targets_cloud(self, *, request_id: str | None) -> list[TargetInfo]:
        """SolrCloud target listing.

        ``/admin/collections?action=LIST`` returns collection names only;
        doc counts require per-collection ``/select?q=*:*&rows=0``.
        """
        try:
            resp = await self._request(
                "GET",
                "/solr/admin/collections",
                params={"action": "LIST"},
                request_id=request_id,
                translate_errors=False,
            )
        except httpx.HTTPError as exc:
            raise ClusterUnreachableError(str(exc)) from exc
        if resp.status_code in (401, 403):
            raise TargetsForbiddenError(
                f"cluster denied listing call (HTTP {resp.status_code} from /admin/collections)"
            )
        if resp.status_code >= 400:
            raise ClusterUnreachableError(f"HTTP {resp.status_code} from /admin/collections")
        body = resp.json()
        names = [str(c) for c in (body.get("collections") or [])]

        # Doc counts via parallel /select?q=*:*&rows=0 — best effort; failures
        # surface as None (not raised) so a partial listing remains useful.
        async def _count(name: str) -> int | None:
            try:
                count_resp = await self._request(
                    "GET",
                    f"/solr/{name}/select",
                    params={"q": "*:*", "rows": "0"},
                    request_id=request_id,
                    translate_errors=False,
                )
            except httpx.HTTPError:
                return None
            if count_resp.status_code != 200:
                return None
            data = count_resp.json()
            return (data.get("response") or {}).get("numFound")

        counts = await asyncio.gather(*(_count(n) for n in names))
        return [TargetInfo(name=n, doc_count=c) for n, c in zip(names, counts, strict=True)]

    async def _list_targets_standalone(self, *, request_id: str | None) -> list[TargetInfo]:
        """Standalone Solr target listing.

        ``/admin/cores?action=STATUS`` includes ``index.numDocs`` per core.
        """
        try:
            resp = await self._request(
                "GET",
                "/solr/admin/cores",
                params={"action": "STATUS"},
                request_id=request_id,
                translate_errors=False,
            )
        except httpx.HTTPError as exc:
            raise ClusterUnreachableError(str(exc)) from exc
        if resp.status_code in (401, 403):
            raise TargetsForbiddenError(
                f"cluster denied listing call (HTTP {resp.status_code} from /admin/cores)"
            )
        if resp.status_code >= 400:
            raise ClusterUnreachableError(f"HTTP {resp.status_code} from /admin/cores")
        body = resp.json()
        status_block = body.get("status") or {}
        out: list[TargetInfo] = []
        for name, defn in status_block.items():
            doc_count: int | None = None
            if isinstance(defn, dict):
                idx = defn.get("index") or {}
                num = idx.get("numDocs")
                if isinstance(num, int):
                    doc_count = num
            out.append(TargetInfo(name=str(name), doc_count=doc_count))
        return out

    async def get_schema(self, target: str, *, request_id: str | None = None) -> Schema:
        """Build a ``Schema`` from Solr's Schema API.

        Issues two parallel calls: ``/<target>/schema/fields`` (the field
        definitions) and ``/<target>/select?q=*:*&rows=0`` (the per-target
        document count which the Schema doesn't carry). The doc-count call
        is best-effort — its failure logs a degraded count but the schema
        still resolves.

        404 on ``/schema/fields`` → ``TargetNotFoundError`` (the target
        collection or core does not exist). 401/403 / 5xx → ``ClusterUnreachableError``.
        """
        try:
            fields_resp = await self._request(
                "GET",
                f"/solr/{target}/schema/fields",
                request_id=request_id,
                translate_errors=False,
            )
        except httpx.HTTPError as exc:
            raise ClusterUnreachableError(str(exc)) from exc
        if fields_resp.status_code == 404:
            raise TargetNotFoundError(target)
        if fields_resp.status_code in (401, 403):
            raise ClusterUnreachableError(
                f"Authentication failed (HTTP {fields_resp.status_code}) on /{target}/schema/fields"
            )
        if fields_resp.status_code >= 400:
            raise ClusterUnreachableError(
                f"HTTP {fields_resp.status_code} from /{target}/schema/fields"
            )
        body = fields_resp.json()
        raw_fields: list[dict[str, Any]] = body.get("fields") or []
        fields = [
            FieldSpec(
                name=str(f.get("name")),
                type=str(f.get("type", "text")),
                # Solr fields don't carry a per-field analyzer in the
                # /schema/fields response (analyzers are on the fieldType,
                # not the field). Leave None — the cross-engine API surface
                # treats analyzer as advisory.
                analyzer=None,
            )
            for f in raw_fields
            if isinstance(f, dict) and f.get("name")
        ]
        return Schema(name=target, fields=fields)

    def render(
        self,
        template: QueryTemplate,
        params: dict[str, ParamValue],
        query_text: str,
    ) -> NativeQuery:
        """Render a Jinja query template + params into a Solr request-parameter dict.

        Unlike ``ElasticAdapter.render`` (which emits a query *body*), the
        Solr return shape is a flat ``dict[str, str]`` mapping Solr request
        parameters that the caller serializes into the ``/select`` query
        string. The output dict is post-processed: any key recognized as a
        unified (cross-engine) parameter name is pivoted into its Solr
        equivalent per `docs/01_architecture/adapters.md` cross-engine map.

        Templates can mix Solr-native keys (``defType``, ``q``, ``qf``,
        ``pf``, ``tie``, ``mm``, ``ps``, ``bf``, ``boost``, ``rq``, ``fl``,
        ``rows``, ``start``, ``sort``, ``fq``, ``qs``) with unified keys
        (``field_boosts``, ``phrase_field_boosts``, ``tie_breaker``,
        ``min_should_match``, ``slop``, ``boost_fn``, ``rerank_model``).
        Unrecognized keys raise ``InvalidQueryDSLError`` — that includes
        ``fuzziness`` (Solr's edismax handles fuzziness via the ``~``
        operator in the query body, not as a request param) so a template
        author can't silently drop a parameter that doesn't translate.

        Validates that every key in ``template.declared_params`` is supplied;
        the Jinja sandbox forbids attribute access so unified params are
        flat (``field_boosts``, not ``boost_config.fields``).
        """
        from jinja2 import UndefinedError

        from backend.app.domain.query.render import render_template

        missing = set(template.declared_params) - set(params.keys())
        if missing:
            raise ValueError(f"render: missing required template params: {sorted(missing)}")

        context: dict[str, Any] = {**params, "query_text": query_text}
        try:
            rendered = render_template(template.body, context)
        except UndefinedError as exc:
            raise ValueError(f"render: undefined parameter — {exc}") from exc

        body = self._pivot_to_solr_params(rendered)
        return NativeQuery(query_id=template.name, body=body)

    @staticmethod
    def _pivot_to_solr_params(rendered: dict[str, Any]) -> dict[str, Any]:
        """Translate a mixed Solr-native + unified-param dict into a pure Solr param dict.

        Pivots (unified → Solr):
        * ``field_boosts: {field: boost}`` → ``qf: "f1^b1 f2^b2"``
        * ``phrase_field_boosts: {field: boost}`` → ``pf: "f1^b1 f2^b2"``
        * ``tie_breaker: float`` → ``tie: "0.3"``
        * ``min_should_match: int|float|str`` → ``mm: "..."``
        * ``slop: int`` → ``ps: "2"``
        * ``boost_fn: {expr, combine}`` → ``bf`` (combine="add") or
          ``boost`` (combine="multiply")
        * ``rerank_model: {id, top_k}`` → ``rq: "{!ltr model=ID reRankDocs=K}"``

        Solr-native keys pass through unchanged. Any other key raises
        ``InvalidQueryDSLError`` (including ``fuzziness``).
        """
        out: dict[str, Any] = {}
        for key, value in rendered.items():
            pivot = _PARAM_PIVOTS.get(key)
            if pivot is not None:
                solr_key, solr_value = pivot(value)
                out[solr_key] = solr_value
                continue
            if key in _SOLR_NATIVE_PARAMS:
                out[key] = _coerce_to_solr_param_value(value)
                continue
            raise InvalidQueryDSLError(_unified_parameter_error_message(key))
        return out

    @staticmethod
    def _render_qf(value: Any) -> tuple[str, str]:
        """``field_boosts: {field: boost}`` → ``("qf", "f1^b1 f2^b2")``.

        Insertion order from the dict is preserved (Python 3.7+ guarantee).
        Boost values may be int or float; integers render without a decimal
        point. Non-dict input raises (defensive; the validator should have
        caught it earlier).
        """
        if not isinstance(value, dict):
            raise InvalidQueryDSLError(f"field_boosts must be a dict, got {type(value).__name__}")
        return "qf", _join_field_boosts(value)

    @staticmethod
    def _render_pf(value: Any) -> tuple[str, str]:
        """``phrase_field_boosts: {field: boost}`` → ``("pf", "f1^b1 f2^b2")``."""
        if not isinstance(value, dict):
            raise InvalidQueryDSLError(
                f"phrase_field_boosts must be a dict, got {type(value).__name__}"
            )
        return "pf", _join_field_boosts(value)

    @staticmethod
    def _render_tie(value: Any) -> tuple[str, str]:
        """``tie_breaker: float`` → ``("tie", "0.3")``."""
        if not isinstance(value, (int, float)):
            raise InvalidQueryDSLError(f"tie_breaker must be a number, got {type(value).__name__}")
        return "tie", _format_number(value)

    @staticmethod
    def _render_mm(value: Any) -> tuple[str, str]:
        """``min_should_match`` → ``("mm", "...")``.

        Accepts int, float, or string. Arithmetic syntax like
        ``"2<-25% 9<-3"`` is preserved verbatim (Solr parses the string).
        """
        if isinstance(value, str):
            return "mm", value
        if isinstance(value, (int, float)):
            return "mm", _format_number(value)
        raise InvalidQueryDSLError(
            f"min_should_match must be int|float|str, got {type(value).__name__}"
        )

    @staticmethod
    def _render_ps(value: Any) -> tuple[str, str]:
        """``slop: int`` → ``("ps", "2")``."""
        if not isinstance(value, int):
            raise InvalidQueryDSLError(f"slop must be an int, got {type(value).__name__}")
        return "ps", str(value)

    @staticmethod
    def _render_boost_fn(value: Any) -> tuple[str, str]:
        """``boost_fn: {expr, combine}`` → either ``bf`` (add) or ``boost`` (multiply).

        The ``combine`` field is required and must be one of ``"add"`` /
        ``"multiply"``. ``expr`` is the Solr function-query expression
        (passed through verbatim — Solr parses it).
        """
        if not isinstance(value, dict):
            raise InvalidQueryDSLError(f"boost_fn must be a dict, got {type(value).__name__}")
        expr = value.get("expr")
        combine = value.get("combine")
        if not isinstance(expr, str) or not expr:
            raise InvalidQueryDSLError("boost_fn.expr must be a non-empty string")
        if combine == "add":
            return "bf", expr
        if combine == "multiply":
            return "boost", expr
        raise InvalidQueryDSLError(f"boost_fn.combine must be 'add' or 'multiply', got {combine!r}")

    @staticmethod
    def _render_rerank_model(value: Any) -> tuple[str, str]:
        """``rerank_model: {id, top_k}`` → ``("rq", "{!ltr model=ID reRankDocs=K}")``.

        ``top_k`` must be a positive int (the LTR rescore window). The model
        ``id`` is the Solr model-store entry name. Story A7's validator runs
        BEFORE this render to confirm the id exists in
        ``engine_config.ltr_models``; this method does the literal string
        translation only.
        """
        if not isinstance(value, dict):
            raise InvalidQueryDSLError(f"rerank_model must be a dict, got {type(value).__name__}")
        model_id = value.get("id")
        top_k = value.get("top_k")
        if not isinstance(model_id, str) or not model_id:
            raise InvalidQueryDSLError("rerank_model.id must be a non-empty string")
        if not isinstance(top_k, int) or top_k <= 0:
            raise InvalidQueryDSLError("rerank_model.top_k must be a positive int")
        return "rq", f"{{!ltr model={model_id} reRankDocs={top_k}}}"

    # ------------------------------------------------------------------
    # Protocol method stubs — Stories A3/A5/A8 land these.
    # ------------------------------------------------------------------

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
        """Hot path: parallel ``/select`` calls with preserved query_id mapping.

        Spec FR-5. Solr has no ``_msearch`` analog — each query is its own HTTP call.
        ``asyncio.gather(..., return_exceptions=True)`` makes the per-query
        error isolation natural: a malformed query in the middle of the
        batch doesn't abort its siblings under ``strict_errors=False``.

        ``strict_errors=True`` (run_query API path):
            per-query 400 → raise ``InvalidQueryDSLError``
            per-query connection/5xx → raise ``ClusterUnreachableError``
            timeout → raise ``QueryTimeoutError``

        ``strict_errors=False`` (Optuna trial runner — default):
            per-query failure → ``query_id`` maps to ``[]`` (trial records as
            failed without aborting the batch).

        ``fl`` normalization (cycle-3 C3-F3): ensure ``score`` AND the
        resolved uniqueKey are always in the ``fl`` request param. Without
        this Solr may omit ``score`` from the response (it's not returned
        by default unless requested) and the parser raises KeyError; without
        the uniqueKey field the parser can't extract ``doc_id``. The
        normalizer merges into any caller-provided ``fl`` value.
        """
        if not queries:
            return {}

        unique_key = await self._resolve_unique_key(target, request_id=request_id)
        urls_params = [self._build_select_request(query, top_k, unique_key) for query in queries]

        async def _execute(url_params: dict[str, Any]) -> httpx.Response:
            return await self._request(
                "GET",
                f"/solr/{target}/select",
                params=url_params,
                request_id=request_id,
                timeout=timeout,
                translate_errors=False,
            )

        raw_results = await asyncio.gather(
            *(_execute(p) for p in urls_params),
            return_exceptions=True,
        )

        out: dict[str, list[ScoredHit]] = {}
        for query, result in zip(queries, raw_results, strict=True):
            out[query.query_id] = self._consume_search_result(
                result, target=target, unique_key=unique_key, strict_errors=strict_errors
            )
        return out

    def _build_select_request(
        self, query: NativeQuery, top_k: int, unique_key: str
    ) -> dict[str, Any]:
        """Build the request-param dict for one ``/select`` call.

        Starts from ``query.body`` (the ``render`` output) and:
        * Sets ``rows=<top_k>`` if not already specified.
        * Normalizes ``fl`` so ``score`` AND ``<unique_key>`` are always
          included (without ``score``, Solr omits the field from response.docs).
        """
        params: dict[str, Any] = dict(query.body)
        params.setdefault("rows", str(top_k))
        params["fl"] = _normalize_fl(params.get("fl"), unique_key)
        return params

    def _consume_search_result(
        self,
        result: httpx.Response | BaseException,
        *,
        target: str,
        unique_key: str,
        strict_errors: bool,
    ) -> list[ScoredHit]:
        """Translate one ``asyncio.gather`` result into a ``list[ScoredHit]``.

        On exception:
        * ``strict_errors=True`` re-raises (typed translations applied).
        * ``strict_errors=False`` returns ``[]`` (trial-runner contract).

        On HTTP response:
        * 2xx → parse ``response.docs`` into ``ScoredHit`` list.
        * 400 → ``InvalidQueryDSLError`` (strict) / ``[]`` (lenient).
        * 401/403/5xx → ``ClusterUnreachableError`` (strict) / ``[]`` (lenient).
        * 404 → ``TargetNotFoundError`` regardless of mode (the target gone
          mid-batch is a hard error worth surfacing).
        """
        if isinstance(result, QueryTimeoutError):
            if strict_errors:
                raise result
            return []
        if isinstance(result, ClusterUnreachableError):
            if strict_errors:
                raise result
            return []
        if isinstance(result, BaseException):
            if strict_errors:
                raise ClusterUnreachableError(str(result)) from result
            return []

        if result.status_code == 404:
            raise TargetNotFoundError(target)
        if result.status_code == 400:
            detail = self._extract_solr_error_detail(result)
            if strict_errors:
                raise InvalidQueryDSLError(f"Solr parse error: {detail}")
            return []
        if result.status_code in (401, 403):
            if strict_errors:
                raise ClusterUnreachableError(
                    f"Authentication failed (HTTP {result.status_code}) on /select"
                )
            return []
        if result.status_code >= 500:
            if strict_errors:
                raise ClusterUnreachableError(f"HTTP {result.status_code} from /{target}/select")
            return []
        if result.status_code != 200:
            if strict_errors:
                raise ClusterUnreachableError(f"HTTP {result.status_code} from /{target}/select")
            return []

        body = result.json()
        docs = (body.get("response") or {}).get("docs") or []
        hits: list[ScoredHit] = []
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            raw_id = doc.get(unique_key)
            score = doc.get("score")
            if raw_id is None or score is None:
                # Defensive: skip docs missing required fields rather than
                # raising; strict_errors only governs the per-request error
                # path, not malformed responses.
                continue
            hits.append(ScoredHit(doc_id=str(raw_id), score=float(score), source=doc))
        return hits

    @staticmethod
    def _extract_solr_error_detail(resp: httpx.Response) -> str:
        """Pull a human-readable error message from a Solr error response.

        Solr 9+ returns ``{"error": {"msg": "...", "code": 400}}`` for parser
        errors. Falls back to the raw body text when the JSON shape is
        unexpected (e.g., a bare 400 from the auth plugin).
        """
        try:
            payload = resp.json()
        except ValueError:
            return resp.text[:200]
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict):
                msg = err.get("msg") or err.get("message")
                if isinstance(msg, str) and msg:
                    return msg
        return resp.text[:200]

    async def explain(
        self,
        target: str,
        query: NativeQuery,
        doc_id: str,
        *,
        request_id: str | None = None,
    ) -> ExplainTree:
        r"""Return Solr's scoring explanation for a (target, query, doc_id) triple.

        Solr's explain is exposed via ``debugQuery=true&debug=results`` on
        ``/<target>/select``. We pin the response to the single doc via
        ``fq=<uniqueKey>:<lucene-escaped doc_id>&rows=1``.

        Doc IDs containing Lucene metacharacters are escaped first
        (``+ - && || ! ( ) { } [ ] ^ " ~ * ? : \ / `` plus whitespace),
        then URL-encoded via httpx's request-param machinery.

        Raises:
            TargetNotFoundError: when /<target>/select returns 404.
            ClusterUnreachableError: 5xx / 401 / 403 / connection.
        """
        unique_key = await self._resolve_unique_key(target, request_id=request_id)
        params: dict[str, Any] = dict(query.body)
        params["debugQuery"] = "true"
        params["debug"] = "results"
        # ``fq`` may already be present from the query body; we append rather
        # than overwriting. Solr supports repeated fq via list values.
        fq_pin = f"{unique_key}:{_lucene_escape(doc_id)}"
        existing_fq = params.get("fq")
        if existing_fq is None:
            params["fq"] = fq_pin
        elif isinstance(existing_fq, list):
            params["fq"] = [*existing_fq, fq_pin]
        else:
            params["fq"] = [existing_fq, fq_pin]
        params["rows"] = "1"

        try:
            resp = await self._request(
                "GET",
                f"/solr/{target}/select",
                params=params,
                request_id=request_id,
                translate_errors=False,
            )
        except httpx.HTTPError as exc:
            raise ClusterUnreachableError(str(exc)) from exc
        if resp.status_code == 404:
            raise TargetNotFoundError(target)
        if resp.status_code in (401, 403):
            raise ClusterUnreachableError(
                f"Authentication failed (HTTP {resp.status_code}) on /{target}/select (explain)"
            )
        if resp.status_code >= 400:
            raise ClusterUnreachableError(
                f"HTTP {resp.status_code} from /{target}/select (explain)"
            )

        body = resp.json()
        debug = body.get("debug") or {}
        explain_block = debug.get("explain") or {}
        node = explain_block.get(doc_id)
        if not isinstance(node, dict):
            # No matching doc OR doc id missing from explain map → unmatched.
            return ExplainTree(
                doc_id=doc_id,
                matched=False,
                value=0.0,
                description="no match",
            )
        return _solr_explain_to_unified(node, doc_id=doc_id)

    async def get_document(
        self,
        target: str,
        doc_id: str,
        *,
        request_id: str | None = None,
    ) -> Document | None:
        """Fetch one document by id via Solr's RealTime Get (``/<target>/get``).

        Returns ``None`` when Solr reports no match (``doc`` is null in the
        response). Raises ``TargetNotFoundError`` when the target itself
        does not exist (404 from ``/get``), ``ClusterUnreachableError`` on
        connection / 5xx / 401 / 403.

        uniqueKey resolved via ``_resolve_unique_key`` (engine_config cache
        → on-demand ``/schema/uniquekey`` → ``id`` fallback). Adapter-side
        memory-only cache for targets created post-registration per spec
        FR-9 service-layer-only-write invariant.
        """
        await self._resolve_unique_key(target, request_id=request_id)
        try:
            resp = await self._request(
                "GET",
                f"/solr/{target}/get",
                params={"id": doc_id},
                request_id=request_id,
                translate_errors=False,
            )
        except httpx.HTTPError as exc:
            raise ClusterUnreachableError(str(exc)) from exc
        if resp.status_code == 404:
            raise TargetNotFoundError(target)
        if resp.status_code in (401, 403):
            raise ClusterUnreachableError(
                f"Authentication failed (HTTP {resp.status_code}) on /{target}/get"
            )
        if resp.status_code >= 400:
            raise ClusterUnreachableError(f"HTTP {resp.status_code} from /{target}/get")
        body = resp.json()
        doc = body.get("doc")
        if not isinstance(doc, dict):
            return None
        return Document(doc_id=doc_id, source=doc)

    async def list_documents(
        self,
        target: str,
        *,
        search_after: list[Any] | None = None,
        limit: int = 25,
        fields: list[str] | None = None,
        request_id: str | None = None,
    ) -> DocumentPage:
        """Paginated browse via Solr cursorMark (FR-9, AC-13).

        Solr cursor-based paging:
        * First page sets ``cursorMark=*`` (REQUIRED — omitting it falls
          back to standard paging which doesn't return ``nextCursorMark``).
        * Subsequent pages set ``cursorMark=<previous nextCursorMark>``.
        * Terminal page: Solr returns ``nextCursorMark`` equal to the
          current ``cursorMark`` — at that point the page is "stable" and
          there's nothing more to fetch. We set ``next_cursor_token=None``
          on the terminal page so the router's ``has_more`` derivation
          falls naturally to ``False``.

        ``rows=<limit>`` exactly (no overfetch). The ES path overfetches by
        one to derive has_more from the trailing hit; Solr doesn't need
        that because ``nextCursorMark`` IS the signal.

        ``search_after`` carries the previous page's ``nextCursorMark`` in a
        single-element list (kept as a list for cross-engine Protocol
        compatibility with the ES path's per-hit sort).
        """
        unique_key = await self._resolve_unique_key(target, request_id=request_id)
        cursor_mark = "*"
        if search_after:
            first = search_after[0]
            if isinstance(first, str) and first:
                cursor_mark = first

        params: dict[str, Any] = {
            "q": "*:*",
            "sort": f"{unique_key} asc",
            "rows": str(limit),
            "cursorMark": cursor_mark,
        }
        # fl handling: when caller supplies fields, ensure uniqueKey is in
        # the list so we can extract doc_id; otherwise use wildcard.
        if fields:
            requested = list(fields)
            if unique_key not in requested:
                requested.insert(0, unique_key)
            params["fl"] = ",".join(requested)
        else:
            params["fl"] = "*"

        try:
            resp = await self._request(
                "GET",
                f"/solr/{target}/select",
                params=params,
                request_id=request_id,
                translate_errors=False,
            )
        except httpx.HTTPError as exc:
            raise ClusterUnreachableError(str(exc)) from exc
        if resp.status_code == 404:
            raise TargetNotFoundError(target)
        if resp.status_code in (401, 403):
            raise ClusterUnreachableError(
                f"Authentication failed (HTTP {resp.status_code}) on /{target}/select (list)"
            )
        if resp.status_code >= 400:
            raise ClusterUnreachableError(f"HTTP {resp.status_code} from /{target}/select (list)")

        body = resp.json()
        response_block = body.get("response") or {}
        total = response_block.get("numFound", 0)
        if not isinstance(total, int):
            total = 0
        docs = response_block.get("docs") or []
        hits: list[AdapterDocumentHit] = []
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            raw_id = doc.get(unique_key)
            if raw_id is None:
                continue
            hits.append(
                AdapterDocumentHit(
                    doc_id=str(raw_id),
                    source=doc,
                    # The per-hit ``sort`` field is used by the ES path for
                    # cursor encoding. For Solr we drive cursors from
                    # nextCursorMark instead; this list stays present so
                    # the cross-engine Protocol shape is honored, but the
                    # router prefers ``next_cursor_token`` when populated.
                    sort=[str(raw_id)],
                )
            )

        next_cursor_token = body.get("nextCursorMark")
        if not isinstance(next_cursor_token, str):
            next_cursor_token = None
        elif next_cursor_token == cursor_mark:
            # Terminal page — Solr signals "no more" by returning the same
            # cursorMark back. Setting None lets the router's has_more
            # derivation flip to False without an explicit page-count check.
            next_cursor_token = None

        return DocumentPage(hits=hits, total=total, next_cursor_token=next_cursor_token)


# Solr-native request param keys that the templates may emit. Anything
# outside this set + ``_PARAM_PIVOTS`` raises ``InvalidQueryDSLError``.
# Source: Solr Ref Guide "Common Query Parameters" + edismax / LTR /
# rescoring sections. Extend conservatively — every added key is a
# forward-compatibility commitment.
_SOLR_NATIVE_PARAMS: frozenset[str] = frozenset(
    {
        "defType",  # query parser pick (edismax / dismax / lucene)
        "q",  # main query
        "qf",  # qf field boosts (post-pivot or native)
        "pf",  # phrase field boosts
        "pf2",  # 2-gram phrase boosts
        "pf3",  # 3-gram phrase boosts
        "tie",  # tie breaker
        "mm",  # min should match
        "ps",  # phrase slop
        "qs",  # query string slop
        "bf",  # additive boost function
        "boost",  # multiplicative boost function
        "rq",  # rescoring query (LTR lives here)
        "fl",  # field list
        "rows",  # page size
        "start",  # offset
        "sort",  # sort spec
        "fq",  # filter query (may repeat)
        "debugQuery",  # explain
        "debug",  # explain detail level
        "wt",  # response writer
    }
)


# Unified-key → pivot-helper map. The helpers live on ``SolrAdapter`` as
# staticmethods so they're individually testable (``test_solr_render``
# and friends parametrize over the helper outputs). The map is module-level
# so ``_pivot_to_solr_params`` can be a staticmethod.
_PARAM_PIVOTS: dict[str, Any] = {
    "field_boosts": SolrAdapter._render_qf,
    "phrase_field_boosts": SolrAdapter._render_pf,
    "tie_breaker": SolrAdapter._render_tie,
    "min_should_match": SolrAdapter._render_mm,
    "slop": SolrAdapter._render_ps,
    "boost_fn": SolrAdapter._render_boost_fn,
    "rerank_model": SolrAdapter._render_rerank_model,
}


def _unified_parameter_error_message(key: str) -> str:
    """Friendly error for unknown / Solr-incompatible unified params."""
    if key == "fuzziness":
        return (
            "unified parameter 'fuzziness' has no Solr edismax equivalent; "
            "use the '~' operator in the query body"
        )
    return (
        f"unified parameter {key!r} has no Solr pivot; "
        "use a Solr-native param name (qf, pf, tie, mm, ps, bf, boost, rq, ...) "
        "or one of: field_boosts, phrase_field_boosts, tie_breaker, "
        "min_should_match, slop, boost_fn, rerank_model"
    )
