# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

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

import asyncio
import hashlib
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any, Final, cast

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.domain.demo.synthetic_ubi import (
    UbiRung,
    fabricate_ubi_for_scenario,
)
from backend.app.scripts.seed_solr_products import (
    _bulk_index_products as _solr_bulk_index,
)
from backend.app.scripts.seed_solr_products import (
    _ensure_collection as _solr_ensure_collection,
)
from backend.app.services.demo_reseed_status import (
    _RICH_SCENARIO_SLUG,
    _SCENARIO_COPY,
    DEMO_RESEED_JOB_TIMEOUT_S,
    DEMO_RESEED_STATUS_KEY,
    DEMO_RESEED_STATUS_TTL_S,
    DEMO_RESEED_STEP_HISTORY_CAP,
    ReseedStatusLiteral,
    ReseedStatusResponse,
    ReseedSummary,
    ScenarioProgress,
    ScenarioState,
    StatusCallback,
    _build_scenario_manifest,
    _EngineType,
    _noop_status,
    _now_iso,
    _SkipReason,
    _stamp_scenario,
    append_step_history,
    reseed_status_is_stale,
    status_get,
    status_set,
)
from backend.app.services.demo_reseed_status import (
    emit_progress as _emit_progress,
)
from backend.app.services.demo_ubi_seed import (
    DemoUbiSeedError,
    ensure_ubi_indices,
    seed_synthetic_ubi,
)
from scripts.seed_meaningful_demos import (
    DEMO_ES_INDICES,
    DEMO_OS_INDICES,
    DEMO_SMALL_STUDY_MAX_TRIALS,
    ES,
    OS,
    TRUNCATE_TABLES,
)
from scripts.seed_meaningful_demos import (
    # Re-exported (``as SCENARIOS``) so ``backend.tests.integration.*``
    # callers can still ``from backend.app.services.demo_seeding import
    # SCENARIOS`` under mypy --strict (PEP 484 explicit-reexport rule).
    SCENARIOS as SCENARIOS,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DEMO_RESEED_JOB_TIMEOUT_S",
    "DEMO_RESEED_LOCK_KEY",
    "DEMO_RESEED_STATUS_KEY",
    "DEMO_RESEED_STATUS_TTL_S",
    "DEMO_RESEED_STEP_HISTORY_CAP",
    "ReseedStatusLiteral",
    "ReseedStatusResponse",
    "ReseedSummary",
    "ScenarioProgress",
    "ScenarioState",
    "StatusCallback",
    "_EngineType",
    "_SkipReason",
    "_RICH_SCENARIO_SLUG",
    "_SCENARIO_COPY",
    "_build_scenario_manifest",
    "_now_iso",
    "_noop_status",
    "_stamp_scenario",
    "append_step_history",
    "is_engine_reachable",
    "is_engine_reachable_with_version",
    "reseed_demo_state",
    "reseed_status_is_stale",
    "run_demo_reseed_cleanup",
    "status_get",
    "status_set",
]


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


# Real-study Optuna config — identical to the CLI's
# ``scripts/seed_meaningful_demos.py:seed_scenario`` so the reseed-button
# output matches ``make seed-demo`` byte-for-byte (same seed=42, same
# max_trials, same parallelism=2). ``max_trials`` is single-sourced via
# ``DEMO_SMALL_STUDY_MAX_TRIALS`` (Story 2.2 / FR-6 / D-11 / D-12) — pinned
# at the convergence-classifier's ``STUDIES_TPE_WARMUP_FLOOR`` (50) so the
# small-scenario LLM + UBI studies read a meaningful convergence verdict
# instead of a uniform ``too_few_trials``. The shared constant guarantees
# the CLI seed and the home-button reseed never drift.
_REAL_STUDY_MAX_TRIALS: Final[int] = DEMO_SMALL_STUDY_MAX_TRIALS
_REAL_STUDY_PARALLELISM: Final[int] = 2
_REAL_STUDY_SAMPLER: Final[str] = "tpe"
_REAL_STUDY_SEED: Final[int] = 42

# Polling ceilings — wide safety margins around expected wall-clock
# (study: 30-60s typical; digest: 5-15s typical).
_REAL_STUDY_POLL_CEILING_S: Final[float] = 180.0
_REAL_STUDY_POLL_INTERVAL_S: Final[float] = 3.0
_DIGEST_POLL_CEILING_S: Final[float] = 90.0
_DIGEST_POLL_INTERVAL_S: Final[float] = 3.0

# UBI judgment-list poll ceiling (Story 2.3 / FR-4). Mirrors the LLM
# study/digest budget — the UBI worker runs on the same Arq queue and
# the synthetic event count caps at ~640 per scenario (rung_3), so a
# 180s ceiling is a wide safety margin.
_UBI_JLIST_POLL_CEILING_S: Final[float] = 180.0
_UBI_JLIST_POLL_INTERVAL_S: Final[float] = 3.0


# Rich scenario constants — mirror
# ``scripts/seed_meaningful_demos.py:851`` so the button's output matches
# ``make seed-demo``'s 5th study (1000 ESCI products + LLM judgments).
_RICH_SCENARIO_INDEX: Final[str] = "acme-products-rich"
_RICH_SCENARIO_QUERY_COUNT: Final[int] = 5
_RICH_SCENARIO_MAX_TRIALS: Final[int] = 15
_RICH_SCENARIO_PARALLELISM: Final[int] = 3
_RICH_JUDGMENT_POLL_CEILING_S: Final[float] = 180.0
_RICH_STUDY_POLL_CEILING_S: Final[float] = 300.0
_SAMPLES_DIR: Final[str] = "/app/samples"


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


# Stable machine-readable token written into ``ReseedStatusResponse.failed_reason``
# when every demo engine is unreachable. Tests + operators match on this exact
# string; never reword it. (infra_solr_ci_readiness FR-2 / D-7.)
ALL_ENGINES_UNREACHABLE_MARKER: Final[str] = "all_engines_unreachable"


class AllEnginesUnreachableError(DemoSeedingError):
    """Raised when no demo engine (ES / OpenSearch / Solr) is reachable.

    Carries the full skipped-slug list so the worker can write it into the
    failed ``ReseedStatusResponse`` (the reseed is async — the orchestrator
    runs in the Arq worker, so this is the only channel the skip list reaches
    the GET-status payload). ``str(exc)`` is the stable
    :data:`ALL_ENGINES_UNREACHABLE_MARKER` token, distinct from the generic
    ``f"{type}: {msg}"`` reason written for mid-scenario failures.

    Routing all-engines-unreachable through ``status="failed"`` (rather than a
    no-op ``status="complete"``) prevents Arq's ``keep_result`` cache from
    masquerading a zero-scenario reseed as a success and locking out retries —
    see ``bug_reseed_failure_blocks_retry_arq_singleton_dedup``.
    """

    def __init__(self, scenarios_skipped: list[str]) -> None:
        """Store the skipped slugs; stringify to the stable marker token."""
        self.scenarios_skipped = scenarios_skipped
        super().__init__(ALL_ENGINES_UNREACHABLE_MARKER)


def _is_all_engines_unreachable(scenarios_skipped: list[str]) -> bool:
    """True iff EVERY reachability-relevant scenario was skipped.

    The reachability-relevant set is the ``len(SCENARIOS)`` entries in the
    scenario loop PLUS the separately-seeded rich ESCI scenario, so the total
    is ``len(SCENARIOS) + 1``. Each slug is appended to ``scenarios_skipped`` at
    most once, so equality means nothing seeded because no engine was reachable.

    Using the full-coverage count (rather than "no studies completed") avoids
    misclassifying a reachable-but-tolerated-failure (e.g. the rich scenario was
    reachable but its LLM judgment step failed) as engine absence — in that case
    the rich slug is NOT in ``scenarios_skipped``, so the count is < the total
    and this returns ``False`` (GPT-5.5 phase-gate Finding 4).

    ``>=`` (not ``==``) defensively: each slug is appended at most once today, so
    the two are equivalent, but ``>=`` can never under-detect the all-unreachable
    state if a future change ever double-appended a slug (Gemini PR #367 G1).
    """
    return len(scenarios_skipped) >= len(SCENARIOS) + 1


# ---------------------------------------------------------------------------
# Pure helpers (no I/O, no env-var reads — unit-testable)
# ---------------------------------------------------------------------------


# Mapping is module-private so the unit tests can assert on the exact
# closed set; production callers go through :func:`_resolve_engine_base_url`.
_ENGINE_BASE_URL_MAPPING: Final[dict[str, str]] = {
    # Host-published ES port (Compose ``"127.0.0.1:9200:9200"``) → in-container
    # ES service port.
    "http://localhost:9200": "http://elasticsearch:9200",
    # Host-published OS port (Compose ``"127.0.0.1:9201:9200"``) → in-container
    # OS service port. The host-side ``:9201`` exists ONLY to avoid colliding
    # with ES on the host; INSIDE the Compose network OpenSearch listens on
    # 9200 like every other engine container. Mapping to ``opensearch:9201``
    # would attempt to reach a port that's not bound and fail with
    # ``ConnectError`` (GPT-5.5 final-review High).
    "http://localhost:9201": "http://opensearch:9200",
    # Host-published Solr port (Compose ``"127.0.0.1:8983:8983"``) → in-container
    # Solr service port. Unlike OpenSearch, Solr's host and container ports
    # match (8983:8983) — there's no ES collision to avoid — so this maps
    # straight through to ``solr:8983``. Added with the MVP2 ``acme-kb-docs-solr``
    # demo scenario (``scripts/seed_meaningful_demos.py`` SCENARIOS); without it
    # the reseed raises ``Unrecognized engine host URL`` on the Solr scenario.
    "http://localhost:8983": "http://solr:8983",
}

# The Compose-DNS *targets* of the mapping above. When
# ``scripts/seed_meaningful_demos.py`` is imported INSIDE a container
# (``_INSIDE_CONTAINER`` → ``/.dockerenv`` present), its ``ES`` / ``OS`` /
# ``SOLR`` constants — and therefore every scenario's ``host_base_url`` — are
# already these Compose-DNS URLs, not the host-shell ``localhost`` URLs. The
# worker reseed runs in-container, so it feeds these already-resolved values
# into :func:`_resolve_engine_base_url`; treating them as a no-op pass-through
# (rather than raising) is what makes the resolver idempotent.
# bug_reseed_resolve_engine_base_url_not_idempotent_in_container.
_COMPOSE_DNS_TARGETS: Final[frozenset[str]] = frozenset(_ENGINE_BASE_URL_MAPPING.values())


def _resolve_engine_base_url(host_base_url: str) -> str:
    """Map an engine base URL to the in-container Compose-DNS name. Idempotent.

    The imported :data:`SCENARIOS` constant from
    ``scripts/seed_meaningful_demos.py`` carries ``host_base_url`` values that
    depend on WHERE the script is imported:

    - From the host shell: ``"http://localhost:9200"`` (ES) /
      ``":9201"`` (OS) / ``":8983"`` (Solr) — correct from the host, wrong
      from inside the API container where ``localhost`` is the API itself.
      These are mapped to the Compose service DNS names.
    - From INSIDE a container (``_INSIDE_CONTAINER`` in the seed script —
      ``/.dockerenv`` present, which is ALWAYS true for the worker reseed):
      the constants are already the Compose-DNS URLs (e.g.
      ``"http://elasticsearch:9200"``). Those pass through unchanged.

    The pass-through (rather than raising on an already-resolved value) is what
    makes this idempotent — required because the worker reseed runs in-container
    and so feeds the already-Compose-DNS URLs here. (Pre-existing latent bug:
    the home-button reseed's integration tests mock the engine probe layer, so
    the real in-container resolve path was never exercised end-to-end —
    bug_reseed_resolve_engine_base_url_not_idempotent_in_container.)

    Pure / deterministic / no I/O.

    Raises:
        ValueError: when ``host_base_url`` is neither a recognized host-shell
            URL nor an already-resolved Compose-DNS target. The orchestrator
            unwraps this to a :class:`DemoSeedingError` so the route handler
            returns a 503 ``SEED_FAILED`` envelope.
    """
    resolved = _ENGINE_BASE_URL_MAPPING.get(host_base_url)
    if resolved is not None:
        return resolved
    # Idempotent pass-through for already-resolved Compose-DNS targets.
    if host_base_url in _COMPOSE_DNS_TARGETS:
        return host_base_url
    raise ValueError(
        f"Unrecognized engine host URL: {host_base_url}. "
        f"Expected a host URL {sorted(_ENGINE_BASE_URL_MAPPING)} "
        f"or an already-resolved Compose-DNS URL {sorted(_COMPOSE_DNS_TARGETS)}."
    )


# ---------------------------------------------------------------------------
# Engine reachability probe (infra_solr_ci_readiness FR-1 / FR-2)
#
# A single, total (never-raises) reachability check reused by the orchestrator
# (skip-on-unreachable), the CLI (engine-tolerance), and the heavy-lane test
# (dynamic expected-count snapshot). Unauthenticated by design — the local
# Compose engines all run security-disabled (CLAUDE.md "Common Pitfalls"); this
# probe is scoped to those local engines and does not negotiate auth.
# ---------------------------------------------------------------------------


async def is_engine_reachable(
    engine_base_url: str,
    engine_type: _EngineType,
    *,
    timeout_s: float = 2.0,
) -> bool:
    """Return ``True`` iff a healthy engine of ``engine_type`` answers at the URL.

    Issues ONE GET to the engine's standard health path and validates the body
    shape so an accidental hit on a wrong service does not false-positive:

    - Solr: ``GET /solr/admin/info/system`` -> ``responseHeader.status == 0`` and
      a ``lucene`` block.
    - Elasticsearch / OpenSearch: ``GET /`` -> a ``version`` key.

    Total by contract: any ``httpx`` error, timeout, or unexpected exception is
    treated as "unreachable" (returns ``False`` + WARN log). This guarantees a
    transient DNS hiccup can never break the reseed — the worst case is a
    scenario being skipped (FR-2 / AC-9).
    """
    health_path = "/solr/admin/info/system" if engine_type == "solr" else "/"
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(f"{engine_base_url}{health_path}")
            if response.status_code != 200:
                return False
            body = response.json()
            if engine_type == "solr":
                return body.get("responseHeader", {}).get("status") == 0 and "lucene" in body
            return "version" in body
    except Exception as exc:  # noqa: BLE001 — probe is total; any failure => unreachable
        logger.warning(
            "demo_reseed_engine_probe_failed",
            extra={
                "engine_type": engine_type,
                "engine_base": engine_base_url,
                "error_type": type(exc).__name__,
            },
        )
        return False


async def is_engine_reachable_with_version(
    engine_base_url: str,
    engine_type: _EngineType,
    *,
    timeout_s: float = 2.0,
) -> tuple[bool, str | None]:
    """Return ``(reachable, version)`` for an engine. Total — never raises.

    feat_engine_version_selection FR-6. Sibling of :func:`is_engine_reachable`;
    same probe paths and 2-second total timeout, but additionally parses the
    engine's reported version number:

    - Solr: ``GET /solr/admin/info/system`` -> reads
      ``lucene.solr-spec-version`` from the same response that
      :func:`is_engine_reachable` validates for reachability.
    - Elasticsearch / OpenSearch: ``GET /`` -> reads ``body['version']['number']``
      from the same response that :func:`is_engine_reachable` validates.

    The two functions share a probe URL but expose distinct return types so
    callers pick the shape that matches what they need. The original
    :func:`is_engine_reachable` is unchanged — it's called by
    :func:`snapshot_engine_reachability` (slug -> bool map for the
    orchestrator's scenario filter) where only the boolean is needed; widening
    that signature would ripple through the orchestrator for no operator value.

    Return contract:
      - ``(True, "9.4.1")`` — engine reachable AND version parsed.
      - ``(True, None)`` — engine reachable but the version field is missing
        or malformed (engine answered, but RelyLoop can't tell what it is).
        Emits a WARN log so operators see the partial-success.
      - ``(False, None)`` — engine unreachable (any HTTP / timeout / parse
        error before the reachability check succeeds).

    The ``probe`` field in the WARN-log ``extra`` disambiguates this probe's
    failures from :func:`is_engine_reachable`'s in operator log grep
    (``demo_reseed_engine_probe_failed``).
    """
    health_path = "/solr/admin/info/system" if engine_type == "solr" else "/"
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(f"{engine_base_url}{health_path}")
            if response.status_code != 200:
                return False, None
            body = response.json()
            # A malformed body (JSON list / null / scalar) would be caught by
            # the broad `except` below, but that path logs a misleading
            # `error_type: AttributeError` WARN. Guard explicitly so an
            # unexpected shape returns a clean (False, None) "unreachable"
            # instead (Gemini review #1).
            if not isinstance(body, dict):
                return False, None
            if engine_type == "solr":
                # Reachability gate: the existing is_engine_reachable shape.
                response_header = body.get("responseHeader")
                if not isinstance(response_header, dict) or response_header.get("status") != 0:
                    return False, None
                if "lucene" not in body:
                    return False, None
                # Reachable; now try to extract the version.
                lucene = body.get("lucene")
                if not isinstance(lucene, dict):
                    return True, None
                version = lucene.get("solr-spec-version")
                if not isinstance(version, str):
                    logger.warning(
                        "demo_reseed_engine_probe_failed",
                        extra={
                            "engine_type": engine_type,
                            "engine_base": engine_base_url,
                            "error_type": "VersionFieldMalformed",
                            "probe": "is_engine_reachable_with_version",
                        },
                    )
                    return True, None
                return True, version
            # ES / OS path.
            if "version" not in body:
                return False, None
            version_block = body.get("version")
            if not isinstance(version_block, dict):
                logger.warning(
                    "demo_reseed_engine_probe_failed",
                    extra={
                        "engine_type": engine_type,
                        "engine_base": engine_base_url,
                        "error_type": "VersionFieldMalformed",
                        "probe": "is_engine_reachable_with_version",
                    },
                )
                return True, None
            number = version_block.get("number")
            if not isinstance(number, str):
                logger.warning(
                    "demo_reseed_engine_probe_failed",
                    extra={
                        "engine_type": engine_type,
                        "engine_base": engine_base_url,
                        "error_type": "VersionNumberMalformed",
                        "probe": "is_engine_reachable_with_version",
                    },
                )
                return True, None
            return True, number
    except Exception as exc:  # noqa: BLE001 — probe is total; any failure => unreachable
        logger.warning(
            "demo_reseed_engine_probe_failed",
            extra={
                "engine_type": engine_type,
                "engine_base": engine_base_url,
                "error_type": type(exc).__name__,
                "probe": "is_engine_reachable_with_version",
            },
        )
        return False, None


async def snapshot_engine_reachability(
    scenarios: list[dict[str, Any]],
) -> dict[str, bool]:
    """Probe every reseed scenario's engine once; return a slug -> reachable map.

    Keyed by scenario **slug** (not engine name) because multiple scenarios can
    share an engine and the orchestrator's ``scenarios_skipped`` is slug-keyed.
    Resolves each scenario's host URL to the in-container Compose-DNS URL via
    :func:`_resolve_engine_base_url` so the snapshot probes the SAME URL the
    orchestrator dispatches against (avoids host-vs-Compose namespace drift).

    Covers the ``scenarios`` passed (the 5 ``SCENARIOS`` entries) PLUS the
    separately-seeded rich ESCI scenario (``_RICH_SCENARIO_SLUG``, an
    Elasticsearch scenario) — so the returned map has 6 keys, matching
    ``scenarios_total = len(SCENARIOS) + 1``. (infra_solr_ci_readiness FR-2/FR-4.)
    """
    # Cache by resolved URL: multiple scenarios share an engine (the 3 ES
    # scenarios + rich all resolve to elasticsearch:9200), so probing per-URL
    # once avoids 3-4x redundant probes — which matters most when an engine is
    # down (each redundant probe burns the full timeout). Gemini PR #367 G2.
    url_cache: dict[str, bool] = {}

    async def _probe(url: str, etype: _EngineType) -> bool:
        if url not in url_cache:
            url_cache[url] = await is_engine_reachable(url, etype)
        return url_cache[url]

    result: dict[str, bool] = {}
    for scenario in scenarios:
        slug = cast("str", scenario["slug"])
        engine_type = cast("_EngineType", scenario["engine_type"])
        resolved = _resolve_engine_base_url(cast("str", scenario["host_base_url"]))
        result[slug] = await _probe(resolved, engine_type)
    # Rich ESCI scenario is seeded outside the SCENARIOS loop and is always ES.
    result[_RICH_SCENARIO_SLUG] = await _probe(_resolve_engine_base_url(ES), "elasticsearch")
    return result


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
# Solr scenario seeding (infra_adapter_solr Story A13 completion)
#
# Solr collections are created from configsets, not from an ES-style JSON
# mapping — so the ``acme-kb-docs-solr`` demo scenario carries no
# ``index_mapping`` key and the ES PUT-index path KeyErrors. This helper
# replaces the three ES calls (PUT index_mapping / per-doc PUT / _refresh)
# with the Solr equivalents, reusing the canonical sync logic from
# ``backend.app.scripts.seed_solr_products`` (which uploads the configset to
# ZooKeeper, creates the collection, and bulk-indexes with a commit). The
# sync functions take an ``httpx.Client`` with a ``base_url``; we run them off
# the event loop via ``asyncio.to_thread`` to avoid drift from a second async
# port. The local Compose Solr is security-disabled, so ``host_auth`` is
# harmless either way — we pass it through for parity with real operator
# clusters that DO enable auth.
# ---------------------------------------------------------------------------


def _seed_solr_scenario_sync(
    engine_base: str,
    target: str,
    configset: str,
    scenario_docs: list[dict[str, Any]],
    host_auth: _AuthTuple | None,
) -> None:
    """Blocking Solr seed: configset UPLOAD → collection CREATE → bulk index.

    Runs inside :func:`asyncio.to_thread`. Reuses the canonical sync helpers
    from ``seed_solr_products`` so the configset-zip / collection-create /
    commit logic never drifts. The scenario docs are the reseed's
    ``{"id": ..., "doc": {...}}`` wrapper shape; we unwrap them to the flat
    Solr doc shape (id merged into the body) before indexing.
    """
    flat_docs: list[dict[str, Any]] = [{"id": d["id"], **d["doc"]} for d in scenario_docs]
    with httpx.Client(base_url=engine_base, timeout=30.0, auth=host_auth) as client:
        _solr_ensure_collection(client, target, configset)
        _solr_bulk_index(client, target, flat_docs)


async def _seed_solr_scenario(
    *,
    engine_base: str,
    target: str,
    configset: str,
    scenario_docs: list[dict[str, Any]],
    host_auth: _AuthTuple | None,
    slug: str,
) -> None:
    """Async wrapper: emit the lifecycle log, then run the blocking Solr seed.

    Mirrors the per-call logging the ES path gets via :func:`_log_call_started`
    so the reseed step trail records the Solr collection-create + index calls.
    """
    _log_call_started(
        "POST", f"{engine_base}/solr/admin/collections?action=CREATE&name={target}", "engine"
    )
    _log_call_started("POST", f"{engine_base}/solr/{target}/update?commit=true", "engine")
    try:
        await asyncio.to_thread(
            _seed_solr_scenario_sync,
            engine_base,
            target,
            configset,
            scenario_docs,
            host_auth,
        )
    except httpx.HTTPError as exc:
        raise DemoSeedingError(f"{slug}/solr_seed: {exc}") from exc


# AC-12 test hook (lifted from the prior synchronous route handler) — a
# ``threading.Event`` injected by the integration test gates the cleanup
# pass on a signal from the test, letting the test fire a concurrent
# reseed during the window when cleanup is mid-flight but the advisory
# lock is still held. Production code path never reads or writes it.
_demo_reseed_cleanup_test_gate: Any = None


async def run_demo_reseed_cleanup(engine_client: httpx.AsyncClient) -> None:
    """Best-effort cleanup pass — TRUNCATE demo tables + delete demo indices.

    Used by the worker on mid-reseed failure to leave the system in a
    clean state. Opens a FRESH DB connection (NOT the orchestrator's
    session, which may be in a broken/rolled-back state after the
    mid-flight exception). Each cleanup step tolerates every error so
    cleanup always completes. Caller is expected to be holding the
    advisory lock so concurrent reseeds 409 until release.

    Cycle-1 GPT-5.5 plan review B1 (lifted from the previous sync handler)
    — cleanup MUST use a fresh DB unit, not the caller's session.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from backend.app.core.settings import get_settings

    if _demo_reseed_cleanup_test_gate is not None:
        await asyncio.to_thread(_demo_reseed_cleanup_test_gate.wait)

    cleanup_engine = create_async_engine(get_settings().database_url, echo=False, future=True)
    try:
        async with cleanup_engine.begin() as cleanup_conn:
            await cleanup_conn.execute(text(_TRUNCATE_DEMO_TABLES_SQL))
        logger.info("demo_reseed_cleanup_truncated")
    except Exception as exc:  # noqa: BLE001 - best-effort cleanup
        logger.warning("demo_reseed_cleanup_truncate_failed", extra={"exc": str(exc)})
    finally:
        await cleanup_engine.dispose()

    es_base = _resolve_engine_base_url(ES)
    for idx in DEMO_ES_INDICES:
        try:
            resp = await engine_client.delete(
                f"{es_base}/{idx}", auth=httpx.BasicAuth(*_ES_DELETE_AUTH)
            )
            if resp.status_code not in (200, 204, 404):
                logger.info(
                    "demo_reseed_cleanup_es_delete_unexpected_status",
                    extra={"idx": idx, "status": resp.status_code},
                )
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup
            logger.info(
                "demo_reseed_cleanup_es_delete_skipped",
                extra={"idx": idx, "exc": str(exc)},
            )

    os_base = _resolve_engine_base_url(OS)
    for idx in DEMO_OS_INDICES:
        try:
            resp = await engine_client.delete(
                f"{os_base}/{idx}", auth=httpx.BasicAuth(*_OS_DELETE_AUTH)
            )
            if resp.status_code not in (200, 204, 404):
                logger.info(
                    "demo_reseed_cleanup_os_delete_unexpected_status",
                    extra={"idx": idx, "status": resp.status_code},
                )
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup
            logger.info(
                "demo_reseed_cleanup_os_delete_skipped",
                extra={"idx": idx, "exc": str(exc)},
            )


# ---------------------------------------------------------------------------
# Real-study seeding helper (bug_demo_reseed_fake_metric_regression D-6)
# ---------------------------------------------------------------------------


def _build_search_space(
    template_declared_params: dict[str, str],
) -> dict[str, Any]:
    """Build the search_space body for a POST /studies request.

    Mirrors ``scripts/seed_meaningful_demos.py:766-771`` byte-for-byte —
    every declared float param gets a ``[0.5, 5.0]`` log-uniform range so
    the demo studies' search-space matches the CLI's exactly. Keeping
    these in lockstep is what allows the regression test to assert the
    button's metrics match a reference run from ``make seed-demo``.

    Per Gemini PR #286 finding #4: the SCENARIOS data structure ships
    ``template_declared_params`` as ``dict[str, str]`` (``{param: type}``),
    not a list. Iterating a dict yields its keys, so the function works at
    runtime either way, but typing it as a dict is honest.
    """
    return {
        "params": {
            name: {"type": "float", "low": 0.5, "high": 5.0, "log": True}
            for name in template_declared_params
        }
    }


async def _create_acme_swap_template(
    api_client: httpx.AsyncClient,
    *,
    engine_type: str,
    declared_params: dict[str, str],
) -> None:
    """Create the function-score-price-decay-v1 template for acme-products.

    Mirrors the special-case at ``scripts/seed_meaningful_demos.py:714-761``
    so the digest worker has a real swap_template candidate to suggest
    after the acme study completes. The template body is the same gauss
    over ``price`` the CLI uses.
    """
    body = json.dumps(
        {
            "query": {
                "function_score": {
                    "query": {
                        "multi_match": {
                            "query": "{{ query_text }}",
                            "fields": [
                                "title^{{ title_boost }}",
                                "description^{{ description_boost }}",
                                "brand^2",
                            ],
                            "type": "best_fields",
                        }
                    },
                    "functions": [{"gauss": {"price": {"origin": 0, "scale": 100, "decay": 0.5}}}],
                    "score_mode": "multiply",
                }
            }
        }
    )
    await _post(
        api_client,
        "/api/v1/query-templates",
        json={
            "name": "function-score-price-decay-v1",
            "engine_type": engine_type,
            "body": body,
            "declared_params": declared_params,
        },
        client_label="api",
        step="acme/post_swap_template",
    )


async def _poll_judgment_list_until_terminal(
    api_client: httpx.AsyncClient,
    judgment_list_id: str,
    *,
    slug: str,
    ceiling_s: float = _UBI_JLIST_POLL_CEILING_S,
    interval_s: float = _UBI_JLIST_POLL_INTERVAL_S,
) -> dict[str, Any]:
    """Poll ``GET /api/v1/judgment-lists/{id}`` until terminal.

    Returns the final detail body on ``status == "complete"``. Raises
    :class:`DemoSeedingError` on ``status == "failed"`` (includes the
    ``failed_reason`` from the row) or on the ``ceiling_s`` timeout.

    Mirrors the shape of the study-poll loop inside
    :func:`_seed_real_study_for_scenario` but inlined here since the
    UBI list status is a distinct enum (``generating | complete |
    failed`` per the DB CHECK at
    ``backend/app/db/models/judgment_list.py:37``) and the failure
    message format is UBI-flavored for operator clarity.
    """
    deadline = time.monotonic() + ceiling_s
    detail: dict[str, Any] = {}
    while time.monotonic() < deadline:
        detail = await _get(
            api_client,
            f"/api/v1/judgment-lists/{judgment_list_id}",
            client_label="api",
            step=f"{slug}/poll_ubi_jlist",
        )
        status = detail.get("status")
        if status == "complete":
            return detail
        if status == "failed":
            raise DemoSeedingError(
                f"ubi_judgments/{slug}: failed "
                f"({detail.get('failed_reason') or 'no failed_reason set'})"
            )
        await asyncio.sleep(interval_s)
    raise DemoSeedingError(
        f"ubi_judgments/{slug}: poll ceiling {ceiling_s}s exceeded "
        f"(last status={detail.get('status')!r})"
    )


async def _seed_real_study_for_scenario(
    api_client: httpx.AsyncClient,
    *,
    scenario: dict[str, Any],
    cluster_id: str,
    template_id: str,
    qset_id: str,
    judgment_list_id: str,
    status_callback: StatusCallback,
    progress: ReseedStatusResponse,
    study_name_override: str | None = None,
    create_swap_template: bool = True,
) -> str:
    """Real study create + poll + digest wait for one scenario.

    Replaces the previous ``POST /_test/studies/seed-completed`` shortcut
    (which hardcoded ``best_metric=0.487`` for every scenario). Mirrors
    the CLI's :func:`scripts.seed_meaningful_demos.seed_scenario` step 8
    so the home-button reseed and ``make seed-demo`` produce
    byte-identical demo state.

    Per ``bug_demo_reseed_fake_metric_regression`` D-6.

    Args:
        api_client: in-container ``httpx.AsyncClient`` against the API.
        scenario: one element of :data:`SCENARIOS`.
        cluster_id: cluster row id created earlier in :func:`reseed_demo_state`.
        template_id: template row id created earlier in :func:`reseed_demo_state`.
        qset_id: query-set row id created earlier in :func:`reseed_demo_state`.
        judgment_list_id: judgment-list row id created earlier in
            :func:`reseed_demo_state`.
        status_callback: invoked after each phase with the updated
            :class:`ReseedStatusResponse`.
        progress: mutable status payload the caller threads through every
            scenario. This function updates ``current_step`` in-place.
        study_name_override: when set (e.g., Story 2.3 / FR-9 dual-study
            seeding), use this instead of ``scenario["study_name"]`` as
            the new study's ``name``. The orchestrator already disambiguates
            with ``(LLM)`` / ``(UBI)`` suffixes; this lets the second call
            avoid colliding with the first by passing a distinct name.
        create_swap_template: when ``False``, skip the acme-only swap-
            template POST. The dual-study path (FR-9) calls this function
            twice for acme — the swap template must only be created on
            the LLM call to avoid a duplicate-name 4xx on the UBI call.

    Returns:
        The new study's id (UUIDv7 string).
    """
    slug = cast("str", scenario["slug"])
    declared_params = cast("dict[str, str]", scenario["template_declared_params"])
    study_name = study_name_override or cast("str", scenario["study_name"])
    target = cast("str", scenario["target"])
    engine_type = cast("str", scenario["engine_type"])

    # Acme-specific swap template (per CLI line 714 / D-6 follow-through).
    # Skipped on the UBI re-entry (FR-9) — the swap template was already
    # created on the LLM pass; creating it twice 4xxs on the unique name.
    if slug == "acme-products-prod" and create_swap_template:
        progress.current_step = f"{slug}: creating swap-template candidate"
        await _emit_progress(status_callback, progress)
        await _create_acme_swap_template(
            api_client, engine_type=engine_type, declared_params=declared_params
        )

    # POST /studies — real create, no test-endpoint shortcut.
    progress.current_step = f"{slug}: creating study (max_trials={_REAL_STUDY_MAX_TRIALS})"
    await _emit_progress(status_callback, progress)
    study = await _post(
        api_client,
        "/api/v1/studies",
        json={
            "name": study_name,
            "cluster_id": cluster_id,
            "target": target,
            "template_id": template_id,
            "query_set_id": qset_id,
            "judgment_list_id": judgment_list_id,
            "search_space": _build_search_space(declared_params),
            "objective": {"metric": "ndcg", "k": 10, "direction": "maximize"},
            "config": {
                "max_trials": _REAL_STUDY_MAX_TRIALS,
                "parallelism": _REAL_STUDY_PARALLELISM,
                "sampler": _REAL_STUDY_SAMPLER,
                "seed": _REAL_STUDY_SEED,
            },
        },
        client_label="api",
        step=f"{slug}/post_study",
    )
    study_id = cast("str", study["id"])

    # Poll for terminal state. The Arq worker runs trials async; we GET
    # the study row every 3s until status flips out of {queued, running}.
    progress.current_step = f"{slug}: polling study {study_id[:8]} for trial completion"
    await _emit_progress(status_callback, progress)
    deadline = time.monotonic() + _REAL_STUDY_POLL_CEILING_S
    detail: dict[str, Any] = study
    while time.monotonic() < deadline:
        detail = await _get(
            api_client,
            f"/api/v1/studies/{study_id}",
            client_label="api",
            step=f"{slug}/poll_study",
        )
        if detail.get("status") in {"completed", "failed", "cancelled"}:
            break
        # Update the current-step counter so the operator sees forward
        # motion — trials_summary.total bumps as the worker writes rows.
        trials_total = detail.get("trials_summary", {}).get("total", 0)
        progress.current_step = (
            f"{slug}: study {study_id[:8]} running (trials {trials_total}/{_REAL_STUDY_MAX_TRIALS})"
        )
        await _emit_progress(status_callback, progress)
        await asyncio.sleep(_REAL_STUDY_POLL_INTERVAL_S)
    final_status = detail.get("status")
    if final_status != "completed":
        raise DemoSeedingError(
            f"{slug}/poll_study: terminal status={final_status!r} "
            f"(expected 'completed'); best_metric={detail.get('best_metric')}"
        )

    # Wait for the digest worker — it fires automatically on the
    # completed-study transition. Without this, the post-reseed dashboard
    # would render the studies but the "Latest digest" sections would
    # all be empty until the next page load.
    progress.current_step = f"{slug}: waiting for digest worker"
    await _emit_progress(status_callback, progress)
    digest_deadline = time.monotonic() + _DIGEST_POLL_CEILING_S
    while time.monotonic() < digest_deadline:
        response = await api_client.get(f"/api/v1/studies/{study_id}/digest")
        if response.status_code == 200:
            break
        if response.status_code == 404:
            # 404 DIGEST_NOT_READY is expected while the worker runs;
            # any other 4xx is an error worth surfacing.
            await asyncio.sleep(_DIGEST_POLL_INTERVAL_S)
            continue
        raise DemoSeedingError(
            f"{slug}/poll_digest: HTTP {response.status_code} {response.text[:200]}"
        )
    else:
        # Soft failure — log + continue. The study is complete; the
        # digest will land eventually and the next reseed cycle clears
        # the slate. Don't fail the whole reseed for a slow LLM call.
        logger.warning(
            "demo_reseed_digest_poll_timeout",
            extra={"slug": slug, "study_id": study_id, "deadline_s": _DIGEST_POLL_CEILING_S},
        )

    return study_id


# ---------------------------------------------------------------------------
# Rich-scenario seeder — mirrors scripts/seed_meaningful_demos.py:851
# (the 5th demo study: 1000 ESCI products + LLM-generated judgments).
# ---------------------------------------------------------------------------


async def _seed_rich_scenario(
    api_client: httpx.AsyncClient,
    engine_client: httpx.AsyncClient,
    *,
    status_callback: StatusCallback,
    progress: ReseedStatusResponse,
) -> str | None:
    """Seed the rich ESCI scenario (1000 products + LLM judgments).

    Returns the new study id on success, or ``None`` on a tolerated
    failure (matches the CLI's behavior at
    ``scripts/seed_meaningful_demos.py:878`` — "Failures here are
    tolerated: the four small scenarios are still valuable on their
    own"). The orchestrator catches the None return + records the
    skip without failing the whole reseed.

    Differences from the CLI:

    * Reads ``samples/`` from ``/app/samples`` (the read-only bind mount
      shared by the api + worker containers).
    * Uses the engine_client / api_client constructed by the worker so
      basic-auth + Compose DNS resolution are consistent with the rest
      of the reseed.
    """
    es_base = _resolve_engine_base_url(ES)

    # 1. Load 1000 ESCI products from samples/. The file lives at
    # ``/app/samples/products.json`` thanks to the Compose mount.
    progress.current_step = f"{_RICH_SCENARIO_SLUG}: loading 1000 ESCI products from samples"
    await _emit_progress(status_callback, progress)
    products_path = f"{_SAMPLES_DIR}/products.json"
    try:
        with open(products_path, encoding="utf-8") as f:
            products = json.load(f)
    except FileNotFoundError:
        logger.warning(
            "demo_reseed_rich_skip_missing_samples",
            extra={"path": products_path},
        )
        return None

    # 2. DELETE (tolerate 404) + recreate the rich index with an explicit
    # mapping. The cleanup pass already DELETE'd ``acme-products-rich``
    # at orchestration start (it's in DEMO_ES_INDICES), so the DELETE
    # here is belt-and-suspenders against an operator who somehow
    # re-created the index between the cleanup and this step.
    delete_resp = await engine_client.delete(
        f"{es_base}/{_RICH_SCENARIO_INDEX}",
        auth=httpx.BasicAuth(*_ES_DELETE_AUTH),
    )
    if delete_resp.status_code not in (200, 204, 404):
        raise DemoSeedingError(
            f"rich/delete_index: HTTP {delete_resp.status_code} {delete_resp.text[:200]}"
        )

    progress.current_step = f"{_RICH_SCENARIO_SLUG}: creating index mapping"
    await _emit_progress(status_callback, progress)
    await _put(
        engine_client,
        f"{es_base}/{_RICH_SCENARIO_INDEX}",
        json={
            "mappings": {
                "properties": {
                    "title": {"type": "text"},
                    "description": {"type": "text"},
                    "brand": {"type": "keyword"},
                    "color": {"type": "keyword"},
                    "bullet_points": {"type": "text"},
                }
            }
        },
        auth=("elastic", "changeme"),
        client_label="engine",
        step="rich/put_index",
    )

    # 3. Bulk-index 1000 docs in chunks of 500. /_bulk requires NDJSON
    # with application/x-ndjson; the helper ``_post`` sends JSON, so
    # bypass it here and use the raw httpx client directly.
    progress.current_step = f"{_RICH_SCENARIO_SLUG}: bulk-indexing {len(products)} docs"
    await _emit_progress(status_callback, progress)
    bulk_chunk = 500
    for i in range(0, len(products), bulk_chunk):
        chunk = products[i : i + bulk_chunk]
        lines: list[str] = []
        for p in chunk:
            lines.append(json.dumps({"index": {"_index": _RICH_SCENARIO_INDEX, "_id": p["id"]}}))
            lines.append(json.dumps({k: v for k, v in p.items() if k != "id"}))
        body = ("\n".join(lines) + "\n").encode()
        bulk_resp = await engine_client.post(
            f"{es_base}/_bulk",
            content=body,
            headers={"Content-Type": "application/x-ndjson"},
            auth=httpx.BasicAuth("elastic", "changeme"),
        )
        if bulk_resp.status_code >= 300:
            raise DemoSeedingError(
                f"rich/bulk_index chunk {i}: HTTP {bulk_resp.status_code} {bulk_resp.text[:200]}"
            )
    await _post(
        engine_client,
        f"{es_base}/{_RICH_SCENARIO_INDEX}/_refresh",
        json=None,
        auth=("elastic", "changeme"),
        client_label="engine",
        step="rich/refresh",
    )

    # 4. Register cluster with target_filter so this cluster's dropdowns
    # only surface the rich index.
    progress.current_step = f"{_RICH_SCENARIO_SLUG}: registering cluster"
    await _emit_progress(status_callback, progress)
    cluster = await _post(
        api_client,
        "/api/v1/clusters",
        json={
            "name": _RICH_SCENARIO_SLUG,
            "engine_type": "elasticsearch",
            "base_url": "http://elasticsearch:9200",
            "auth_kind": "es_basic",
            "credentials_ref": "local-es",
            "environment": "prod",
            "target_filter": f"{_RICH_SCENARIO_INDEX}*",
        },
        client_label="api",
        step="rich/post_cluster",
    )
    cluster_id = cast("str", cluster["id"])

    # 5. Template from samples/templates/product_search.j2 — the
    # canonical 3-param multi_match used by the tutorial.
    template_path = f"{_SAMPLES_DIR}/templates/product_search.j2"
    try:
        with open(template_path, encoding="utf-8") as f:
            template_body = f.read()
    except FileNotFoundError:
        logger.warning(
            "demo_reseed_rich_skip_missing_template",
            extra={"path": template_path},
        )
        return None

    progress.current_step = f"{_RICH_SCENARIO_SLUG}: creating template + query set"
    await _emit_progress(status_callback, progress)
    template = await _post(
        api_client,
        "/api/v1/query-templates",
        json={
            "name": "product-search-multi-match-v1",
            "engine_type": "elasticsearch",
            "body": template_body,
            "declared_params": {
                "title_boost": "float",
                "description_boost": "float",
                "bullet_points_boost": "float",
            },
        },
        client_label="api",
        step="rich/post_template",
    )
    template_id = cast("str", template["id"])

    # 6. Query set + queries from samples/queries.csv (first N).
    qset = await _post(
        api_client,
        "/api/v1/query-sets",
        json={"name": "acme-rich-queries-q4-2025", "cluster_id": cluster_id},
        client_label="api",
        step="rich/post_query_set",
    )
    qset_id = cast("str", qset["id"])
    queries_path = f"{_SAMPLES_DIR}/queries.csv"
    try:
        with open(queries_path, encoding="utf-8") as f:
            csv_lines = f.read().strip().splitlines()
    except FileNotFoundError:
        logger.warning("demo_reseed_rich_skip_missing_queries", extra={"path": queries_path})
        return None
    queries_payload: list[dict[str, str]] = []
    for line in csv_lines[1 : _RICH_SCENARIO_QUERY_COUNT + 1]:  # skip header
        parts = line.split(",", 1)
        if len(parts) == 2:
            queries_payload.append({"query_text": parts[1].strip()})
    await _post(
        api_client,
        f"/api/v1/query-sets/{qset_id}/queries",
        json={"queries": queries_payload},
        client_label="api",
        step="rich/post_queries",
    )

    # 7. Generate judgments via LLM. Returns 202; worker generates async.
    progress.current_step = f"{_RICH_SCENARIO_SLUG}: generating LLM judgments (~30-60s)"
    await _emit_progress(status_callback, progress)
    jl_resp = await _post(
        api_client,
        "/api/v1/judgments/generate",
        json={
            "name": "acme-rich-judgments-q4-2025",
            "description": "ESCI demo judgments for the rich-data acme scenario",
            "query_set_id": qset_id,
            "cluster_id": cluster_id,
            "target": _RICH_SCENARIO_INDEX,
            "current_template_id": template_id,
            "rubric": (
                "Rate 0-3 by relevance to the query: "
                "0=irrelevant, 1=partial, 2=relevant, 3=highly relevant."
            ),
        },
        client_label="api",
        step="rich/post_judgments_generate",
    )
    jlist_id = cast("str", jl_resp["judgment_list_id"])

    # Poll until judgments complete. 3-min ceiling; gpt-4o-mini against
    # 5 queries × top-K is typically 30-60s.
    deadline = time.monotonic() + _RICH_JUDGMENT_POLL_CEILING_S
    jl_detail: dict[str, Any] = jl_resp
    while time.monotonic() < deadline:
        jl_detail = await _get(
            api_client,
            f"/api/v1/judgment-lists/{jlist_id}",
            client_label="api",
            step="rich/poll_judgments",
        )
        status_value = jl_detail.get("status")
        if status_value in {"complete", "failed"}:
            break
        progress.current_step = f"{_RICH_SCENARIO_SLUG}: LLM judgments status={status_value!r}"
        await _emit_progress(status_callback, progress)
        await asyncio.sleep(_REAL_STUDY_POLL_INTERVAL_S)
    if jl_detail.get("status") != "complete":
        logger.warning(
            "demo_reseed_rich_judgment_did_not_complete",
            extra={"jlist_id": jlist_id, "status": jl_detail.get("status")},
        )
        return None

    # 8. Real 15-trial study against the rich data. Three boost knobs
    # gives Optuna a 3-D search space that actually moves the metric.
    progress.current_step = (
        f"{_RICH_SCENARIO_SLUG}: creating study (max_trials={_RICH_SCENARIO_MAX_TRIALS})"
    )
    await _emit_progress(status_callback, progress)
    study = await _post(
        api_client,
        "/api/v1/studies",
        json={
            "name": "tune-acme-products-rich-boosts",
            "cluster_id": cluster_id,
            "target": _RICH_SCENARIO_INDEX,
            "template_id": template_id,
            "query_set_id": qset_id,
            "judgment_list_id": jlist_id,
            "search_space": {
                "params": {
                    "title_boost": {"type": "float", "low": 0.5, "high": 5.0, "log": True},
                    "description_boost": {
                        "type": "float",
                        "low": 0.5,
                        "high": 5.0,
                        "log": True,
                    },
                    "bullet_points_boost": {
                        "type": "float",
                        "low": 0.5,
                        "high": 5.0,
                        "log": True,
                    },
                }
            },
            "objective": {"metric": "ndcg", "k": 10, "direction": "maximize"},
            "config": {
                "max_trials": _RICH_SCENARIO_MAX_TRIALS,
                "parallelism": _RICH_SCENARIO_PARALLELISM,
                "sampler": _REAL_STUDY_SAMPLER,
                "seed": _REAL_STUDY_SEED,
            },
        },
        client_label="api",
        step="rich/post_study",
    )
    study_id = cast("str", study["id"])

    # Poll for terminal state. 5-min ceiling — 15 trials × parallelism=3
    # over 1000 docs is typically 1-3 min; the margin protects against
    # ES warmup.
    deadline = time.monotonic() + _RICH_STUDY_POLL_CEILING_S
    detail: dict[str, Any] = study
    while time.monotonic() < deadline:
        detail = await _get(
            api_client,
            f"/api/v1/studies/{study_id}",
            client_label="api",
            step="rich/poll_study",
        )
        if detail.get("status") in {"completed", "failed", "cancelled"}:
            break
        trials_total = detail.get("trials_summary", {}).get("total", 0)
        progress.current_step = (
            f"{_RICH_SCENARIO_SLUG}: study {study_id[:8]} running "
            f"(trials {trials_total}/{_RICH_SCENARIO_MAX_TRIALS})"
        )
        await _emit_progress(status_callback, progress)
        await asyncio.sleep(_REAL_STUDY_POLL_INTERVAL_S)
    if detail.get("status") != "completed":
        logger.warning(
            "demo_reseed_rich_study_did_not_complete",
            extra={"study_id": study_id, "status": detail.get("status")},
        )
        return None
    return study_id


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def reseed_demo_state(
    db: AsyncSession,
    api_client: httpx.AsyncClient,
    engine_client: httpx.AsyncClient,
    *,
    status_callback: StatusCallback = _noop_status,
    engines: list[_EngineType] | None = None,
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
    # Wall-clock anchor for the synthetic UBI generator (Story 2.2 / FR-3).
    # `seed_anchor_iso` is the orchestrator's start instant; the synthetic
    # generator builds events in `[seed_anchor - 60s, seed_anchor]` so the
    # UBI judgment dispatcher's `since/until` window (Story 2.3) captures
    # every row deterministically. `time.monotonic()` is unaffected by
    # wall-clock jumps; for the ISO timestamp we use `datetime.now(UTC)`.
    started_at_dt = datetime.now(UTC)
    seed_anchor_iso = started_at_dt.isoformat()
    # Per-invocation gate so `ensure_ubi_indices` runs at most once PER
    # ENGINE BASE across the scenario loop. Tracking the set of engine bases
    # already ensured (not a single bool) is required because the loop spans
    # multiple engines (ES on :9200, OpenSearch on :9201, Solr on :8983):
    # a bare bool flipped True by the first ES scenario would skip
    # `ensure_ubi_indices` for the Solr scenario, leaving its ubi_queries /
    # ubi_events collections uncreated. Local (NOT module-level) because the
    # cleanup pass DELETEs both UBI indices at start of every reseed —
    # caching across invocations would skip the create on the second reseed.
    ubi_indices_ready: set[str] = set()
    # scenarios_total counts the 4 small SCENARIOS + the rich ESCI scenario
    # (matches the CLI's 5-study output from ``make seed-demo``).
    progress = ReseedStatusResponse(
        status="running",
        started_at=_now_iso(),
        scenarios_total=len(SCENARIOS) + 1,
        scenarios_completed=0,
        current_step="wiping demo state",
        # Per-run scenario manifest (all pending; user-excluded engines pre-marked
        # skipped). The loop below stamps active/done/skipped as it processes.
        # feat_reseed_scenario_manifest_live_state FR-4.
        scenarios=_build_scenario_manifest(engines),
    )
    await _emit_progress(status_callback, progress)

    # Per-reseed reachability cache, keyed by resolved engine URL. The pre-loop
    # wipes, the per-scenario gates, and the rich gate all probe the same few
    # engine URLs; probing each once avoids redundant probes (and redundant
    # full-timeout waits when an engine is down). Caching for the duration of a
    # single reseed is correct — an engine that flaps mid-reseed surfaces as a
    # mid-scenario DemoSeedingError, not a silent skip. Gemini PR #367 G3.
    reachability_cache: dict[str, bool] = {}

    async def _check_reachable(url: str, etype: _EngineType) -> bool:
        if url not in reachability_cache:
            reachability_cache[url] = await is_engine_reachable(url, etype)
        return reachability_cache[url]

    # ---- Step 1a: TRUNCATE demo tables, COMMIT before any self-call. ----
    await db.execute(text(_TRUNCATE_DEMO_TABLES_SQL))
    await db.commit()
    logger.info(
        "demo_reseed_truncate_committed",
        extra={"table_count": len(TRUNCATE_TABLES)},
    )

    # ---- Step 1b: DELETE ES + OS demo indices. ----
    # Each engine's wipe is gated on reachability FIRST (infra_solr_ci_readiness
    # FR-2): an unreachable engine has no demo indices to wipe, and probing
    # before the DELETEs is what keeps the all-engines-unreachable path total —
    # otherwise a genuine all-down run would ConnectError here (before any
    # scenario-skip accounting) and surface as a generic failure instead of the
    # required `all_engines_unreachable` token. A reachable engine that then
    # returns a non-2xx/404 on DELETE is still a hard error (unchanged).
    es_base = _resolve_engine_base_url(ES)
    if await _check_reachable(es_base, "elasticsearch"):
        for idx in DEMO_ES_INDICES:
            _log_call_started("DELETE", f"{es_base}/{idx}", "engine")
            response = await engine_client.delete(
                f"{es_base}/{idx}", auth=_httpx_auth(_ES_DELETE_AUTH)
            )
            if response.status_code not in (200, 204, 404):
                raise DemoSeedingError(
                    f"step1b_es_delete: HTTP {response.status_code} {response.text[:200]}"
                )

    os_base = _resolve_engine_base_url(OS)
    if await _check_reachable(os_base, "opensearch"):
        for idx in DEMO_OS_INDICES:
            _log_call_started("DELETE", f"{os_base}/{idx}", "engine")
            response = await engine_client.delete(
                f"{os_base}/{idx}", auth=_httpx_auth(_OS_DELETE_AUTH)
            )
            if response.status_code not in (200, 204, 404):
                raise DemoSeedingError(
                    f"step1b_os_delete: HTTP {response.status_code} {response.text[:200]}"
                )

    # ---- Step 2: loop scenarios. ----
    results: list[tuple[str, str, str]] = []  # (slug, study_id, study_name)

    for scenario in SCENARIOS:
        slug: str = cast("str", scenario["slug"])
        engine_base = _resolve_engine_base_url(cast("str", scenario["host_base_url"]))
        engine_type: _EngineType = cast("_EngineType", scenario["engine_type"])
        target: str = cast("str", scenario["target"])
        host_auth: _AuthTuple = cast("_AuthTuple", scenario["host_auth"])
        scenario_docs = cast("list[dict[str, Any]]", scenario["docs"])
        scenario_queries = cast("list[dict[str, Any]]", scenario["queries"])
        scenario_judgments_map = cast("list[tuple[int, str, int]]", scenario["judgments_map"])

        # User-intent gate (feat_selective_engine_startup_and_demo FR-5).
        # When the caller passed an explicit ``engines`` filter (the reset
        # modal's checkbox group via the POST body), scenarios whose
        # engine_type the operator excluded MUST NOT be attempted — record
        # the slug with reason ``user_excluded`` and continue. The gate
        # fires BEFORE the reachability probe so the UI can distinguish
        # "you excluded this engine" from "we tried and it was down."
        if engines is not None and engine_type not in engines:
            logger.info(
                "demo_reseed_scenario_skipped_user_excluded",
                extra={"slug": slug, "engine_type": engine_type},
            )
            progress.scenarios_skipped.append(slug)
            progress.scenarios_skipped_reasons[slug] = "user_excluded"
            # Manifest already pre-marked this skipped at build (D-2); stamp +
            # emit so the skip is visible within one poll tick (FR-7 / FR-8).
            _stamp_scenario(progress, slug, "skipped", "user_excluded")
            await _emit_progress(status_callback, progress)
            continue

        # Skip-on-unreachable: probe the scenario's engine BEFORE any dispatch.
        # A False here means the engine container isn't running (e.g. Solr is
        # absent in the pr.yml backend job) — skip the scenario and record the
        # slug rather than ConnectError-ing the whole reseed. A transient error
        # mid-scenario (after this gate) still surfaces as DemoSeedingError.
        # (infra_solr_ci_readiness FR-2.)
        if not await _check_reachable(engine_base, engine_type):
            logger.info(
                "demo_reseed_scenario_skipped_engine_unreachable",
                extra={"slug": slug, "engine_type": engine_type, "engine_base": engine_base},
            )
            progress.scenarios_skipped.append(slug)
            progress.scenarios_skipped_reasons[slug] = "unreachable"
            _stamp_scenario(progress, slug, "skipped", "unreachable")
            await _emit_progress(status_callback, progress)
            continue

        # Scenario passed both gates — it's now actively seeding (FR-5).
        _stamp_scenario(progress, slug, "active")
        progress.current_step = f"{slug}: indexing {len(scenario_docs)} docs into {target}"
        await _emit_progress(status_callback, progress)

        # 2a. Engine: create the index/collection + load docs.
        #
        # Solr collections are built from configsets, not from an ES-style
        # JSON mapping, so the ``acme-kb-docs-solr`` scenario carries no
        # ``index_mapping`` key (it would KeyError on the ES path below).
        # Branch on the Solr engine hint and route through the configset +
        # collection-create + commit path instead. Every other scenario keeps
        # the unchanged ES PUT-index / per-doc PUT / _refresh sequence.
        if scenario.get("engine_type") == "solr":
            await _seed_solr_scenario(
                engine_base=engine_base,
                target=target,
                configset=cast("str", scenario["solr_configset"]),
                scenario_docs=scenario_docs,
                host_auth=host_auth,
                slug=slug,
            )
            # Fall through to the shared 2b+ API path (cluster/template/...).
        else:
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

        progress.current_step = f"{slug}: registering cluster + template + query set"
        await _emit_progress(status_callback, progress)

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
        # ``limit=200`` is the API's documented page-size cap (FR-2 /
        # api-conventions.md §Pagination). The current scenarios each
        # define 5 queries, but the cap leaves generous headroom for
        # future demo growth without needing to wire cursor pagination
        # into this single-page lookup. Per Gemini PR #228 review.
        qrows_resp = await _get(
            api_client,
            f"/api/v1/query-sets/{qset_id}/queries",
            params={"limit": 200},
            client_label="api",
            step=f"{slug}/get_queries",
        )
        qrows = qrows_resp["data"]
        qtext_to_id: dict[str, str] = {r["query_text"]: r["id"] for r in qrows}
        # Resolve each scenario query's text → API-assigned id. Surface a
        # descriptive ``DemoSeedingError`` if the API response somehow
        # omits a scenario's text (pagination cap hit, API normalization
        # of query_text changed, etc.) rather than letting a bare
        # ``KeyError`` propagate. Per Gemini PR #228 review.
        qid_by_idx: list[str] = []
        for q in scenario_queries:
            q_text = q["query_text"]
            if q_text not in qtext_to_id:
                raise DemoSeedingError(
                    f"{slug}: query text {q_text!r} not present in API "
                    f"response for query-set {qset_id} (returned "
                    f"{len(qrows)} of <= 200; possible pagination cap "
                    "or text-normalization mismatch)"
                )
            qid_by_idx.append(qtext_to_id[q_text])

        # 2f.5. Synthetic UBI seeding (Story 2.2 / FR-3, FR-4).
        # For UBI-enabled scenarios (SCENARIOS' new `ubi_target_rung` /
        # `ubi_converter` keys, Story 2.1 / FR-8): ensure both indices
        # exist (once per reseed), generate synthetic queries + events
        # via the pure-domain generator, and bulk-write through the
        # allowlisted helper. Runs BEFORE the LLM judgments import so a
        # UBI-seeding failure surfaces before more downstream work
        # commits — same posture the LLM dispatch helper uses.
        ubi_target_rung_raw = scenario.get("ubi_target_rung")
        if ubi_target_rung_raw is not None:
            ubi_target_rung = cast("UbiRung", ubi_target_rung_raw)
            # Wrap the whole UBI-seed block so any DemoUbiSeedError (engine
            # bulk-write failure) or ValueError (allowlist guard) surfaces
            # as DemoSeedingError("ubi_seed/{slug}: ...") — the failure
            # contract the spec's §6 failure catalog promises + the prefix
            # the route handler's 503 SEED_FAILED path expects. Without the
            # wrap the raw DemoUbiSeedError/ValueError still 503s (the
            # handler catches Exception), but the operator loses the
            # ubi_seed/{slug} attribution. Per GPT-5.5 final review on PR #320.
            try:
                ubi_engine_type = cast("str", scenario["engine_type"])
                if engine_base not in ubi_indices_ready:
                    await ensure_ubi_indices(
                        engine_client=engine_client,
                        engine_base_url=engine_base,
                        host_auth=host_auth,
                        engine_type=ubi_engine_type,
                    )
                    ubi_indices_ready.add(engine_base)
                query_id_by_index: dict[int, str] = dict(enumerate(qid_by_idx))
                query_text_by_index: dict[int, str] = {
                    i: cast("str", q["query_text"]) for i, q in enumerate(scenario_queries)
                }
                ubi_queries, ubi_events = fabricate_ubi_for_scenario(
                    scenario_judgments_map=scenario_judgments_map,
                    query_id_by_index=query_id_by_index,
                    query_text_by_index=query_text_by_index,
                    target_application=target,
                    target_rung=ubi_target_rung,
                    seed_anchor_iso=seed_anchor_iso,
                )
                progress.current_step = (
                    f"{slug}: writing synthetic UBI ({ubi_target_rung}, {len(ubi_events)} events)"
                )
                await _emit_progress(status_callback, progress)
                ubi_seed_started = time.monotonic()
                logger.info(
                    "demo_reseed_ubi_seed_started",
                    extra={
                        "slug": slug,
                        "rung": ubi_target_rung,
                        "event_count_target": len(ubi_events),
                    },
                )
                event_count = await seed_synthetic_ubi(
                    engine_client=engine_client,
                    engine_base_url=engine_base,
                    host_auth=host_auth,
                    engine_type=ubi_engine_type,
                    scenario_slug=slug,
                    target_application=target,
                    queries=ubi_queries,
                    events=ubi_events,
                )
            except (DemoUbiSeedError, ValueError) as exc:
                raise DemoSeedingError(f"ubi_seed/{slug}: {exc}") from exc
            logger.info(
                "demo_reseed_ubi_seed_complete",
                extra={
                    "slug": slug,
                    "event_count": event_count,
                    "duration_ms": int((time.monotonic() - ubi_seed_started) * 1000),
                },
            )

        progress.current_step = f"{slug}: importing {len(scenario_judgments_map)} judgments"
        await _emit_progress(status_callback, progress)

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

        # 2h. API: REAL study create + poll + digest wait (LLM-grade study).
        #
        # Previously called /_test/studies/seed-completed which hardcoded
        # best_metric=0.487 for every scenario. The CLI's
        # scripts/seed_meaningful_demos.py:seed_scenario step 8 was rewritten
        # to use real studies in an earlier PR; this path was the holdout
        # that produced the bug surfaced as
        # ``bug_demo_reseed_fake_metric_regression``. Now matches the CLI
        # byte-for-byte so home-button reseed === ``make seed-demo`` output.
        #
        # For UBI-enabled scenarios (Story 2.3 / FR-9), the study is
        # disambiguated up front with " (LLM)" so the rename loop (step
        # 3) doesn't have to special-case it; non-UBI scenarios keep the
        # bare study_name from SCENARIOS.
        base_study_name: str = cast("str", scenario["study_name"])
        llm_study_name: str = (
            f"{base_study_name} (LLM)" if ubi_target_rung_raw is not None else base_study_name
        )
        llm_study_id = await _seed_real_study_for_scenario(
            api_client,
            scenario=scenario,
            cluster_id=cluster_id,
            template_id=template_id,
            qset_id=qset_id,
            judgment_list_id=jlist_id,
            status_callback=status_callback,
            progress=progress,
            study_name_override=llm_study_name,
        )
        results.append((slug, llm_study_id, llm_study_name))

        # 2i. UBI dispatch + dual study (Story 2.3 / FR-4, FR-9).
        if ubi_target_rung_raw is not None:
            ubi_converter = cast("str", scenario["ubi_converter"])
            ubi_jlist_name = f"{cast('str', scenario['judgment_list_name'])} (UBI)"
            # `since`/`until` MUST bracket the synthetic events the
            # generator wrote in [seed_anchor - 60s, seed_anchor). Query rows
            # sit at the inclusive lower bound and events strictly below the
            # upper bound, so the reader's half-open `timestamp < until` scan
            # captures both. The dispatcher persists this exact window into
            # generation_params so the worker's resume payload is
            # reproducible (FR-4 spec lock).
            ubi_dispatch_body: dict[str, Any] = {
                "name": ubi_jlist_name,
                "query_set_id": qset_id,
                "cluster_id": cluster_id,
                "target": target,
                "since": (started_at_dt - timedelta(seconds=60)).isoformat(),
                "until": started_at_dt.isoformat(),
                "converter": ubi_converter,
                "mapping_strategy": "reject",
                # Derive the sync count-gate floor from the actually-seeded
                # event count so the sparse rung_1 scenario (~50 events, which
                # exists to demo hybrid LLM-fill) clears its own gate while
                # dense rungs keep the 100 default. Mirrors the CLI reseed in
                # scripts/seed_meaningful_demos.py.
                "min_impressions_threshold": min(100, event_count),
            }
            if ubi_converter == "hybrid_ubi_llm":
                # CreateJudgmentListFromUbiRequest's @model_validator
                # REQUIRES current_template_id + rubric for hybrid and
                # FORBIDS them otherwise.
                ubi_dispatch_body["current_template_id"] = template_id
                ubi_dispatch_body["rubric"] = scenario["rubric"]

            progress.current_step = f"{slug}: dispatching UBI judgment generation ({ubi_converter})"
            await _emit_progress(status_callback, progress)
            logger.info(
                "demo_reseed_ubi_judgment_dispatch_started",
                extra={"slug": slug, "converter": ubi_converter},
            )
            dispatch_resp = await _post(
                api_client,
                "/api/v1/judgments/generate-from-ubi",
                json=ubi_dispatch_body,
                client_label="api",
                step=f"{slug}/dispatch_ubi_judgments",
            )
            ubi_jlist_id: str = cast("str", dispatch_resp["judgment_list_id"])

            progress.current_step = (
                f"{slug}: polling UBI judgment list {ubi_jlist_id[:8]} for completion"
            )
            await _emit_progress(status_callback, progress)
            await _poll_judgment_list_until_terminal(api_client, ubi_jlist_id, slug=slug)

            # Second study seed against the UBI judgment list. Same
            # template/qset/cluster/search_space/seed=42/max_trials — only
            # the judgment_list_id differs (per D-12 the UBI study also runs
            # ``_REAL_STUDY_MAX_TRIALS`` trials for symmetry with the LLM
            # study, even though AC-8 only gates on the LLM study). Skip the
            # acme swap-template creation: it was already done on the LLM
            # pass.
            ubi_study_name = f"{base_study_name} (UBI)"
            progress.current_step = (
                f"{slug}: creating UBI study (max_trials={_REAL_STUDY_MAX_TRIALS})"
            )
            await _emit_progress(status_callback, progress)
            ubi_study_started = time.monotonic()
            ubi_study_id = await _seed_real_study_for_scenario(
                api_client,
                scenario=scenario,
                cluster_id=cluster_id,
                template_id=template_id,
                qset_id=qset_id,
                judgment_list_id=ubi_jlist_id,
                status_callback=status_callback,
                progress=progress,
                study_name_override=ubi_study_name,
                create_swap_template=False,
            )
            results.append((slug, ubi_study_id, ubi_study_name))
            logger.info(
                "demo_reseed_ubi_study_complete",
                extra={
                    "slug": slug,
                    "study_id": ubi_study_id,
                    "duration_ms": int((time.monotonic() - ubi_study_started) * 1000),
                },
            )

        # Scenario fully seeded — stamp done (recomputes scenarios_completed
        # from the manifest, FR-6/6a) and emit.
        _stamp_scenario(progress, slug, "done")
        await _emit_progress(status_callback, progress)

    # ---- Step 2b: rich ESCI scenario (5th study). ----
    # Matches scripts/seed_meaningful_demos.py:851 — 1000 docs +
    # LLM-generated judgments + 15-trial study. Failures here are
    # tolerated (the 4 small scenarios are still valuable on their own,
    # per the CLI's policy at line 878-880).
    #
    # The rich scenario is an Elasticsearch scenario seeded outside the
    # SCENARIOS loop, so it needs its own reachability gate: when ES is
    # unreachable, skip + record the slug rather than letting _seed_rich_scenario
    # raise on the first DELETE. (infra_solr_ci_readiness FR-2.)
    rich_study_id: str | None = None
    rich_engine_base = _resolve_engine_base_url(ES)
    # Rich scenario is an ES scenario; honor the same user-intent gate as the
    # small-SCENARIOS loop (feat_selective_engine_startup_and_demo FR-5). When
    # the caller's `engines` filter omits elasticsearch, skip the rich path
    # BEFORE the reachability probe + record reason `user_excluded`.
    if engines is not None and "elasticsearch" not in engines:
        logger.info(
            "demo_reseed_scenario_skipped_user_excluded",
            extra={"slug": _RICH_SCENARIO_SLUG, "engine_type": "elasticsearch"},
        )
        progress.scenarios_skipped.append(_RICH_SCENARIO_SLUG)
        progress.scenarios_skipped_reasons[_RICH_SCENARIO_SLUG] = "user_excluded"
        _stamp_scenario(progress, _RICH_SCENARIO_SLUG, "skipped", "user_excluded")
        await _emit_progress(status_callback, progress)
    elif not await _check_reachable(rich_engine_base, "elasticsearch"):
        logger.info(
            "demo_reseed_scenario_skipped_engine_unreachable",
            extra={
                "slug": _RICH_SCENARIO_SLUG,
                "engine_type": "elasticsearch",
                "engine_base": rich_engine_base,
            },
        )
        progress.scenarios_skipped.append(_RICH_SCENARIO_SLUG)
        progress.scenarios_skipped_reasons[_RICH_SCENARIO_SLUG] = "unreachable"
        _stamp_scenario(progress, _RICH_SCENARIO_SLUG, "skipped", "unreachable")
        await _emit_progress(status_callback, progress)
    else:
        # ES reachable + not excluded — the rich scenario is actively seeding.
        _stamp_scenario(progress, _RICH_SCENARIO_SLUG, "active")
        await _emit_progress(status_callback, progress)
        try:
            rich_study_id = await _seed_rich_scenario(
                api_client,
                engine_client,
                status_callback=status_callback,
                progress=progress,
            )
        except DemoSeedingError as exc:
            logger.warning(
                "demo_reseed_rich_scenario_failed_tolerated",
                extra={"exc": str(exc)[:200]},
            )
            rich_study_id = None
        if rich_study_id is not None:
            _stamp_scenario(progress, _RICH_SCENARIO_SLUG, "done")
            await _emit_progress(status_callback, progress)
        else:
            # Tolerated failure (ES reachable but rich seeding errored): it is
            # NOT in scenarios_skipped (legacy semantics) and did not complete —
            # stamp skipped with no reason so the checklist shows it didn't
            # finish instead of leaving it stuck "active". The frontend renders a
            # null skip_reason as a generic "skipped" (not "engine unreachable").
            _stamp_scenario(progress, _RICH_SCENARIO_SLUG, "skipped")
            await _emit_progress(status_callback, progress)

    # ---- Step 2c: engine-tolerance verdict. ----
    # If EVERY engine was unreachable (all 6 scenarios skipped), this is a hard
    # failure, not a partial — surfacing it as a no-op success would cache in
    # Arq's keep_result window and wedge retries (bug_reseed_failure_blocks_…).
    # Otherwise, if any scenario was skipped, emit one WARN summarizing the
    # partial completion. (infra_solr_ci_readiness FR-2 / AC-7 / AC-10.)
    if _is_all_engines_unreachable(progress.scenarios_skipped):
        raise AllEnginesUnreachableError(progress.scenarios_skipped)
    if progress.scenarios_skipped:
        logger.warning(
            "demo_reseed_partial_completion_engines_unreachable",
            extra={
                "scenarios_skipped": progress.scenarios_skipped,
                "scenarios_completed": progress.scenarios_completed,
            },
        )

    # ---- Step 3: rename the 4 small studies. ----
    progress.current_step = "renaming studies to tutorial names"
    await _emit_progress(status_callback, progress)
    for _slug, study_id, study_name in results:
        await db.execute(
            text("UPDATE studies SET name = :name WHERE id = :id"),
            {"name": study_name, "id": study_id},
        )
    await db.commit()

    # ---- Step 4: build summary + mark status complete. ----
    duration_ms = int((time.monotonic() - started_at) * 1000)
    # One cluster + one query set per SCENARIOS entry (+1 for rich) —
    # the UBI re-entry (Story 2.3) reuses the same cluster + query set,
    # so the cluster / query-set counts stay at the SCENARIOS cardinality.
    # Studies and proposals scale with `results` (each entry is one
    # completed study + one digest + one proposal).
    # One cluster + one query set per COMPLETED scenario (a UBI scenario reuses
    # its cluster/query-set across the LLM + UBI studies, so `results` — which
    # has one entry PER STUDY, i.e. two per UBI scenario — overcounts clusters).
    # Count DISTINCT completed scenario slugs instead. Studies + proposals scale
    # with `results` (each entry = one completed study + digest + proposal).
    # A scenario skipped for engine-unreachability creates nothing, so it
    # contributes to neither count. With no skips this equals the pre-feature
    # len(SCENARIOS) + rich. (GPT-5.5 phase-gate Finding 3.)
    rich_count = 1 if rich_study_id is not None else 0
    completed_scenario_slugs = {slug for slug, _study_id, _name in results}
    clusters_and_qsets = len(completed_scenario_slugs) + rich_count
    studies_and_proposals = len(results) + rich_count
    summary = ReseedSummary(
        clusters_created=clusters_and_qsets,
        query_sets_created=clusters_and_qsets,
        studies_completed=studies_and_proposals,
        proposals_created=studies_and_proposals,
        duration_ms=duration_ms,
    )
    progress.status = "complete"
    progress.finished_at = _now_iso()
    progress.current_step = None
    progress.summary = summary
    await _emit_progress(status_callback, progress)
    return summary
