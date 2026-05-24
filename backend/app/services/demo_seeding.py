"""Demo-state reseed service (feat_home_demo_reseed_endpoint Story 1.1).

Orchestrates a complete wipe + reseed of the four demo scenarios used by
the dashboard tutorial. Imported by ``backend/app/api/v1/_test.py``'s
``POST /api/v1/_test/demo/reseed`` route handler.

This module intentionally has **no Postgres advisory-lock concerns** —
the route handler owns the session-level advisory lock on a dedicated
pinned ``AsyncConnection`` per FR-3. This module also does **not**
construct the two ``httpx.AsyncClient`` instances; the handler does
that per FR-1c so the per-call timeout is wired from ``Settings``.

Spec references:

* FR-1   — orchestrator behavior (wipe → loop scenarios → rename → return).
* FR-1c  — dual-client construction contract (route handler).
* FR-1d  — :func:`_resolve_engine_base_url` translates the CLI's
  ``localhost:9200/9201`` host URLs to Compose-DNS names inside the
  API container.
* §10 Threat 4 — the ``httpx.ReadTimeout`` recovery path requires
  ``docker compose restart api`` before retry (deliberate residual).
* AC-13  — the orchestrator MUST commit the TRUNCATE before any
  self-call so the AccessExclusive lock releases; the
  ``demo_reseed_truncate_committed`` log line is part of the contract.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any, Final, cast

import httpx
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.seed_meaningful_demos import (
    DEMO_ES_INDICES,
    DEMO_OS_INDICES,
    ES,
    OS,
    TRUNCATE_TABLES,
)
from scripts.seed_meaningful_demos import (
    SCENARIOS as _RAW_SCENARIOS,
)

# The CLI declares ``SCENARIOS`` as ``list[dict]`` (untyped values).
# Cast at the import boundary so the orchestrator code can index the
# expected string/tuple/list shapes without mypy complaining. The CLI
# is out of scope per locked decision D2 — we don't add type hints to
# ``scripts/seed_meaningful_demos.py``.
SCENARIOS: list[dict[str, Any]] = cast("list[dict[str, Any]]", _RAW_SCENARIOS)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------


# Lock key — same blake2b → signed int64 pattern as the digest worker
# (``backend/workers/digest.py``) and orchestrator (``orchestrator.py``).
# Single global key (no per-id suffix) because the demo dataset is a
# singleton — only one reseed can be running at a time across the
# entire install.
DEMO_RESEED_LOCK_KEY: Final[int] = int.from_bytes(
    hashlib.blake2b(b"demo:reseed", digest_size=8).digest(),
    byteorder="big",
    signed=True,
)


# Single source-of-truth TRUNCATE statement reused by both the orchestrator
# (Step 1a) and the route handler's cleanup pass. ``TRUNCATE_TABLES`` is a
# closed-set Python tuple from ``scripts/seed_meaningful_demos.py`` — no
# untrusted input flows here, so the f-string interpolation is safe (the
# same constant the CLI uses).
_TRUNCATE_DEMO_TABLES_SQL: Final[str] = (
    f"TRUNCATE {', '.join(TRUNCATE_TABLES)} RESTART IDENTITY CASCADE"
)


# Auth tuples for the cleanup-side ES/OS index DELETEs. Per cycle-12 plan
# review B2 we own these locally rather than importing the CLI's
# ``ES_AUTH`` / ``OS_AUTH`` — the spec doesn't promise those CLI symbols
# stay stable, but the dev-stack basic-auth credentials are part of the
# Compose contract.
_ES_DELETE_AUTH: Final[tuple[str, str]] = ("elastic", "changeme")
_OS_DELETE_AUTH: Final[tuple[str, str]] = ("admin", "admin")


# ---------------------------------------------------------------------------
# Public exception type
# ---------------------------------------------------------------------------


class DemoSeedingError(RuntimeError):
    """Raised by :func:`reseed_demo_state` on any unrecoverable failure.

    The route handler catches this AND any other ``Exception``, runs
    cleanup, and returns 503 ``SEED_FAILED``. Defined as a distinct
    class so log lines can discriminate ``DemoSeedingError`` from
    unexpected library exceptions.
    """


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------


class ReseedSummary(BaseModel):
    """Returned by :func:`reseed_demo_state` on success.

    Per spec §9 Required invariants, every counter is exactly 4 on the
    happy path; ``duration_ms`` is wall-clock from orchestration start
    to the rename commit.
    """

    model_config = ConfigDict(extra="forbid")

    clusters_created: int
    query_sets_created: int
    studies_completed: int
    proposals_created: int
    duration_ms: int


# ---------------------------------------------------------------------------
# Pure helpers (no I/O, no env-var reads — unit-testable)
# ---------------------------------------------------------------------------


# Mapping is module-private so the unit tests can assert on the exact
# closed set; production callers go through :func:`_resolve_engine_base_url`.
_ENGINE_BASE_URL_MAPPING: Final[dict[str, str]] = {
    "http://localhost:9200": "http://elasticsearch:9200",
    "http://localhost:9201": "http://opensearch:9201",
}


def _resolve_engine_base_url(host_base_url: str) -> str:
    """Map the CLI's host-shell URLs to in-container Compose DNS names.

    The imported :data:`SCENARIOS` constant from
    ``scripts/seed_meaningful_demos.py`` carries ``host_base_url`` values
    like ``"http://localhost:9200"`` (ES) and ``"http://localhost:9201"``
    (OS) — correct from the host shell, wrong from inside the API
    container where ``localhost`` is the API itself. This function
    transparently maps to the Compose service DNS names.

    Pure / deterministic / no I/O. No env hooks (per cycle-4 plan review
    A1 — AC-5's test injection lives in the test harness, not here).

    Per FR-1d.

    Raises:
        ValueError: when ``host_base_url`` is not one of the two
            recognized CLI URLs. The orchestrator unwraps this to a
            :class:`DemoSeedingError` so the route handler returns a
            503 ``SEED_FAILED`` envelope.
    """
    resolved = _ENGINE_BASE_URL_MAPPING.get(host_base_url)
    if resolved is None:
        raise ValueError(
            f"Unrecognized engine host URL: {host_base_url}. "
            f"Expected one of {sorted(_ENGINE_BASE_URL_MAPPING)}."
        )
    return resolved


# ---------------------------------------------------------------------------
# Per-call HTTP helpers — emit AC-13 lifecycle log before each call,
# raise DemoSeedingError on any non-2xx response.
# ---------------------------------------------------------------------------


def _log_call_started(method: str, url: str, client_label: str) -> None:
    """Emit the ``demo_reseed_api_call_started`` log line.

    AC-13's commit-ordering assertion in the integration tests reads
    this log entry to prove the TRUNCATE committed before any self-call
    fires. Centralized so every per-call helper gets the same shape.
    """
    logger.info(
        "demo_reseed_api_call_started",
        extra={"method": method, "url": url, "client": client_label},
    )


_AuthTuple = tuple[str, str]


def _httpx_auth(auth: _AuthTuple | None) -> Any:
    """Return ``auth`` for ``httpx`` callers, or the SDK sentinel when None.

    ``httpx.AsyncClient.{post,put,get,delete}`` types the ``auth`` kwarg
    as ``AuthTypes | UseClientDefault`` and rejects a plain ``None``
    annotation. Funnel both branches through this helper so callers
    don't have to repeat the sentinel.
    """
    if auth is None:
        return httpx.USE_CLIENT_DEFAULT
    return auth


async def _post(
    client: httpx.AsyncClient,
    url: str,
    *,
    json: Any = None,
    auth: _AuthTuple | None = None,
    client_label: str,
    step: str,
) -> dict[str, Any]:
    """Execute a POST + raise :class:`DemoSeedingError` on non-2xx."""
    _log_call_started("POST", url, client_label)
    response = await client.post(url, json=json, auth=_httpx_auth(auth))
    if response.status_code >= 300:
        raise DemoSeedingError(f"{step}: HTTP {response.status_code} {response.text[:200]}")
    if not response.content:
        return {}
    return cast("dict[str, Any]", response.json())


async def _put(
    client: httpx.AsyncClient,
    url: str,
    *,
    json: Any = None,
    auth: _AuthTuple | None = None,
    client_label: str,
    step: str,
) -> dict[str, Any]:
    """Execute a PUT + raise :class:`DemoSeedingError` on non-2xx."""
    _log_call_started("PUT", url, client_label)
    response = await client.put(url, json=json, auth=_httpx_auth(auth))
    if response.status_code >= 300:
        raise DemoSeedingError(f"{step}: HTTP {response.status_code} {response.text[:200]}")
    if not response.content:
        return {}
    return cast("dict[str, Any]", response.json())


async def _get(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    auth: _AuthTuple | None = None,
    client_label: str,
    step: str,
) -> dict[str, Any]:
    """Execute a GET + raise :class:`DemoSeedingError` on non-2xx."""
    _log_call_started("GET", url, client_label)
    response = await client.get(url, params=params, auth=_httpx_auth(auth))
    if response.status_code >= 300:
        raise DemoSeedingError(f"{step}: HTTP {response.status_code} {response.text[:200]}")
    if not response.content:
        return {}
    return cast("dict[str, Any]", response.json())


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def reseed_demo_state(
    db: AsyncSession,
    api_client: httpx.AsyncClient,
    engine_client: httpx.AsyncClient,
) -> ReseedSummary:
    """Orchestrate a complete wipe + reseed of the 4 demo scenarios.

    Steps:

    1. **TRUNCATE** the 10 demo tables ``RESTART IDENTITY CASCADE``,
       then COMMIT (AC-13 — commit before any self-call so the
       AccessExclusive lock releases). Emits the
       ``demo_reseed_truncate_committed`` log line.
    2. **DELETE** the 3 ES + 1 OS demo indices via ``engine_client``
       (tolerates 404 for the no-op-on-clean-stack case).
    3. **Loop** the 4 scenarios from
       :data:`scripts.seed_meaningful_demos.SCENARIOS`:

       * Engine: PUT index mapping, PUT each doc, POST ``_refresh``.
       * API: cluster → template → query-set → queries → judgments →
         seed-completed study.

    4. **Rename** the 4 studies with the spec's tutorial names.
    5. **Return** :class:`ReseedSummary` with timing info.

    Per FR-1, the caller (route handler) owns: advisory-lock acquisition
    and release; ``httpx.AsyncClient`` construction (with the per-call
    timeout); and the cleanup-on-failure pass.

    This function does NOT touch the advisory lock; that's the
    handler's job (FR-3).
    """
    started_at = time.monotonic()

    # ---- Step 1a: TRUNCATE demo tables, COMMIT before any self-call. ----
    await db.execute(text(_TRUNCATE_DEMO_TABLES_SQL))
    await db.commit()
    logger.info(
        "demo_reseed_truncate_committed",
        extra={"table_count": len(TRUNCATE_TABLES)},
    )

    # ---- Step 1b: DELETE ES + OS demo indices. ----
    es_base = _resolve_engine_base_url(ES)
    for idx in DEMO_ES_INDICES:
        _log_call_started("DELETE", f"{es_base}/{idx}", "engine")
        response = await engine_client.delete(f"{es_base}/{idx}", auth=_httpx_auth(_ES_DELETE_AUTH))
        if response.status_code not in (200, 204, 404):
            raise DemoSeedingError(
                f"step1b_es_delete: HTTP {response.status_code} {response.text[:200]}"
            )

    os_base = _resolve_engine_base_url(OS)
    for idx in DEMO_OS_INDICES:
        _log_call_started("DELETE", f"{os_base}/{idx}", "engine")
        response = await engine_client.delete(f"{os_base}/{idx}", auth=_httpx_auth(_OS_DELETE_AUTH))
        if response.status_code not in (200, 204, 404):
            raise DemoSeedingError(
                f"step1b_os_delete: HTTP {response.status_code} {response.text[:200]}"
            )

    # ---- Step 2: loop scenarios. ----
    results: list[tuple[str, str, str]] = []  # (slug, study_id, study_name)

    for scenario in SCENARIOS:
        slug: str = cast("str", scenario["slug"])
        engine_base = _resolve_engine_base_url(cast("str", scenario["host_base_url"]))
        target: str = cast("str", scenario["target"])
        host_auth: _AuthTuple = cast("_AuthTuple", scenario["host_auth"])
        scenario_docs = cast("list[dict[str, Any]]", scenario["docs"])
        scenario_queries = cast("list[dict[str, Any]]", scenario["queries"])
        scenario_judgments_map = cast("list[tuple[int, str, int]]", scenario["judgments_map"])

        # 2a. Engine: PUT index, PUT docs, POST _refresh.
        await _put(
            engine_client,
            f"{engine_base}/{target}",
            json=scenario["index_mapping"],
            auth=host_auth,
            client_label="engine",
            step=f"{slug}/put_index",
        )
        for doc in scenario_docs:
            await _put(
                engine_client,
                f"{engine_base}/{target}/_doc/{doc['id']}",
                json=doc["doc"],
                auth=host_auth,
                client_label="engine",
                step=f"{slug}/put_doc",
            )
        await _post(
            engine_client,
            f"{engine_base}/{target}/_refresh",
            json=None,
            auth=host_auth,
            client_label="engine",
            step=f"{slug}/refresh",
        )

        # 2b. API: cluster.
        cluster = await _post(
            api_client,
            "/api/v1/clusters",
            json={
                "name": scenario["slug"],
                "engine_type": scenario["engine_type"],
                "environment": scenario["environment"],
                "base_url": scenario["base_url"],
                "auth_kind": scenario["auth_kind"],
                "credentials_ref": scenario["credentials_ref"],
                "target_filter": scenario["target_filter"],
            },
            client_label="api",
            step=f"{slug}/post_cluster",
        )
        cluster_id: str = cluster["id"]

        # 2c. API: query template.
        template = await _post(
            api_client,
            "/api/v1/query-templates",
            json={
                "name": scenario["template_name"],
                "engine_type": scenario["engine_type"],
                "body": scenario["template_body"],
                "declared_params": scenario["template_declared_params"],
            },
            client_label="api",
            step=f"{slug}/post_template",
        )
        template_id: str = template["id"]

        # 2d. API: query set.
        qset = await _post(
            api_client,
            "/api/v1/query-sets",
            json={
                "name": scenario["query_set_name"],
                "cluster_id": cluster_id,
            },
            client_label="api",
            step=f"{slug}/post_query_set",
        )
        qset_id: str = qset["id"]

        # 2e. API: queries.
        await _post(
            api_client,
            f"/api/v1/query-sets/{qset_id}/queries",
            json={"queries": scenario_queries},
            client_label="api",
            step=f"{slug}/post_queries",
        )

        # 2f. API: fetch query IDs so judgments can reference them.
        qrows_resp = await _get(
            api_client,
            f"/api/v1/query-sets/{qset_id}/queries",
            params={"limit": 50},
            client_label="api",
            step=f"{slug}/get_queries",
        )
        qrows = qrows_resp["data"]
        qtext_to_id: dict[str, str] = {r["query_text"]: r["id"] for r in qrows}
        qid_by_idx: list[str] = [qtext_to_id[q["query_text"]] for q in scenario_queries]

        # 2g. API: judgments.
        judgments_payload = [
            {
                "query_id": qid_by_idx[qi],
                "doc_id": doc_id,
                "rating": rating,
            }
            for (qi, doc_id, rating) in scenario_judgments_map
        ]
        jlist = await _post(
            api_client,
            "/api/v1/judgment-lists/import",
            json={
                "name": scenario["judgment_list_name"],
                "query_set_id": qset_id,
                "cluster_id": cluster_id,
                "target": target,
                "rubric": scenario["rubric"],
                "judgments": judgments_payload,
            },
            client_label="api",
            step=f"{slug}/post_judgments",
        )
        jlist_id: str = jlist["id"]

        # 2h. API: seed completed study.
        seeded = await _post(
            api_client,
            "/api/v1/_test/studies/seed-completed",
            json={
                "cluster_id": cluster_id,
                "query_set_id": qset_id,
                "template_id": template_id,
                "judgment_list_id": jlist_id,
                "with_pending_proposal": True,
            },
            client_label="api",
            step=f"{slug}/seed_completed",
        )
        study_id: str = seeded["study_id"]
        study_name: str = cast("str", scenario["study_name"])
        results.append((slug, study_id, study_name))

    # ---- Step 3: rename the 4 studies. ----
    for _slug, study_id, study_name in results:
        await db.execute(
            text("UPDATE studies SET name = :name WHERE id = :id"),
            {"name": study_name, "id": study_id},
        )
    await db.commit()

    # ---- Step 4: return summary. ----
    duration_ms = int((time.monotonic() - started_at) * 1000)
    return ReseedSummary(
        clusters_created=4,
        query_sets_created=4,
        studies_completed=4,
        proposals_created=4,
        duration_ms=duration_ms,
    )
