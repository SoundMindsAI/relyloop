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
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Final, Literal, cast

import httpx
from pydantic import BaseModel, ConfigDict
from redis.asyncio import Redis
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


# Redis key holding the JSON-serialized :class:`ReseedStatusResponse`. TTL
# is 1 hour — long enough for any in-flight reseed to finish + the
# operator to see the result, short enough that stale failures clear
# themselves. Per ``bug_demo_reseed_fake_metric_regression`` D-2.
DEMO_RESEED_STATUS_KEY: Final[str] = "demo_reseed:status"
DEMO_RESEED_STATUS_TTL_S: Final[int] = 3600

# 20-minute hard ceiling on the entire reseed — 4 small scenarios + the
# rich ESCI scenario (1000 docs + LLM judgments + 15-trial study). Per
# scripts/seed_meaningful_demos.py wall-clock notes: small scenarios run
# ~1 min each, the rich scenario adds ~3-5 min, plus digest waits and
# headroom. The advisory lock prevents concurrent runs from piling up;
# this timeout bounds the worst case AND drives the POST handler's
# stale-status auto-recovery (per
# ``bug_demo_reseed_button_silent_enqueue_failure``). Lives here (not in
# the worker module) so the route handler can read it without an
# API → worker import.
DEMO_RESEED_JOB_TIMEOUT_S: Final[int] = 1200


# Real-study Optuna config — identical to the CLI's
# ``scripts/seed_meaningful_demos.py:seed_scenario`` so the reseed-button
# output matches ``make seed-demo`` byte-for-byte (same seed=42, same
# max_trials=12, same parallelism=2).
_REAL_STUDY_MAX_TRIALS: Final[int] = 12
_REAL_STUDY_PARALLELISM: Final[int] = 2
_REAL_STUDY_SAMPLER: Final[str] = "tpe"
_REAL_STUDY_SEED: Final[int] = 42

# Polling ceilings — wide safety margins around expected wall-clock
# (study: 30-60s typical; digest: 5-15s typical).
_REAL_STUDY_POLL_CEILING_S: Final[float] = 180.0
_REAL_STUDY_POLL_INTERVAL_S: Final[float] = 3.0
_DIGEST_POLL_CEILING_S: Final[float] = 90.0
_DIGEST_POLL_INTERVAL_S: Final[float] = 3.0


# Rich scenario constants — mirror
# ``scripts/seed_meaningful_demos.py:851`` so the button's output matches
# ``make seed-demo``'s 5th study (1000 ESCI products + LLM judgments).
_RICH_SCENARIO_SLUG: Final[str] = "acme-products-rich-prod"
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


ReseedStatusLiteral = Literal["idle", "running", "complete", "failed"]


class ReseedStatusResponse(BaseModel):
    """Polling-endpoint response for ``GET /api/v1/_test/demo/reseed/status``.

    Per ``bug_demo_reseed_fake_metric_regression`` D-2. Lives in Redis as a
    single JSON blob keyed by :data:`DEMO_RESEED_STATUS_KEY` so the
    handler reads it in one round-trip.
    """

    model_config = ConfigDict(extra="forbid")

    status: ReseedStatusLiteral
    started_at: str | None = None
    finished_at: str | None = None
    scenarios_total: int = 0
    scenarios_completed: int = 0
    current_step: str | None = None
    failed_reason: str | None = None
    summary: ReseedSummary | None = None


# Status callback receives an in-progress ReseedStatusResponse and persists
# it. Sync callers (tests) pass a no-op; the Arq worker passes a closure
# that writes the Redis key.
StatusCallback = Callable[[ReseedStatusResponse], Awaitable[None]]


async def _noop_status(_status: ReseedStatusResponse) -> None:
    """Default :type:`StatusCallback` — discards progress updates.

    Used by unit/integration callers that don't care about progress
    streaming. The Arq worker passes a Redis-writing closure instead.
    """
    return None


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
# Redis-backed status helpers (bug_demo_reseed_fake_metric_regression D-1/D-2)
# ---------------------------------------------------------------------------


async def status_set(redis: Redis, status: ReseedStatusResponse) -> None:
    """Persist the current reseed status as JSON under :data:`DEMO_RESEED_STATUS_KEY`.

    Refreshes the 1-hour TTL on every write so an in-flight reseed never
    expires mid-run.
    """
    payload = json.dumps(status.model_dump(mode="json"))
    await redis.set(DEMO_RESEED_STATUS_KEY, payload, ex=DEMO_RESEED_STATUS_TTL_S)


async def status_get(redis: Redis) -> ReseedStatusResponse:
    """Read the current reseed status; returns ``status="idle"`` when absent.

    Per ``bug_demo_reseed_fake_metric_regression`` D-5: absent key means
    no reseed has run (or the result aged out) — return idle rather than
    404 so the frontend's polling loop is trivially safe.
    """
    raw = await redis.get(DEMO_RESEED_STATUS_KEY)
    if raw is None:
        return ReseedStatusResponse(status="idle")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("demo_reseed_status_payload_malformed", extra={"raw": raw[:200]})
        return ReseedStatusResponse(status="idle")
    return ReseedStatusResponse.model_validate(payload)


def _now_iso() -> str:
    """UTC timestamp in ISO-8601 (Z-suffix), matching the rest of the API."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def reseed_status_is_stale(
    status: ReseedStatusResponse,
    *,
    now: datetime | None = None,
    timeout_s: int = DEMO_RESEED_JOB_TIMEOUT_S,
) -> bool:
    """True when a ``running`` status payload is older than ``timeout_s``.

    Defense-in-depth check for the case where the worker process itself
    died (OOM, container restart, hard kill) before any exception handler
    — including the outer ``except BaseException`` barrier added by
    ``bug_demo_reseed_button_silent_enqueue_failure`` — could run. The
    POST handler uses this to convert a stuck-running status into a
    "treat as failed and let the new POST proceed" outcome, instead of
    leaving the operator 409-blocked forever.

    Pure / deterministic — accepts ``now`` for testability. Treats
    parse failures + missing ``started_at`` as not-stale (conservative:
    if we can't prove staleness, prefer the existing 409 behavior so we
    don't double-enqueue against a real in-flight worker).

    Per ``bug_demo_reseed_button_silent_enqueue_failure`` §"Proposed
    capabilities" #2.
    """
    if status.status != "running" or status.started_at is None:
        return False
    try:
        started = datetime.fromisoformat(status.started_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    now_utc = now if now is not None else datetime.now(UTC)
    return (now_utc - started).total_seconds() > timeout_s


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

    Returns:
        The new study's id (UUIDv7 string).
    """
    slug = cast("str", scenario["slug"])
    declared_params = cast("dict[str, str]", scenario["template_declared_params"])
    study_name = cast("str", scenario["study_name"])
    target = cast("str", scenario["target"])
    engine_type = cast("str", scenario["engine_type"])

    # Acme-specific swap template (per CLI line 714 / D-6 follow-through).
    if slug == "acme-products-prod":
        progress.current_step = f"{slug}: creating swap-template candidate"
        await status_callback(progress)
        await _create_acme_swap_template(
            api_client, engine_type=engine_type, declared_params=declared_params
        )

    # POST /studies — real create, no test-endpoint shortcut.
    progress.current_step = f"{slug}: creating study (max_trials={_REAL_STUDY_MAX_TRIALS})"
    await status_callback(progress)
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
    await status_callback(progress)
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
        await status_callback(progress)
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
    await status_callback(progress)
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
    await status_callback(progress)
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
    await status_callback(progress)
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
    await status_callback(progress)
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
    await status_callback(progress)
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
    await status_callback(progress)
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
    await status_callback(progress)
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
        await status_callback(progress)
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
    await status_callback(progress)
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
        await status_callback(progress)
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
    # scenarios_total counts the 4 small SCENARIOS + the rich ESCI scenario
    # (matches the CLI's 5-study output from ``make seed-demo``).
    progress = ReseedStatusResponse(
        status="running",
        started_at=_now_iso(),
        scenarios_total=len(SCENARIOS) + 1,
        scenarios_completed=0,
        current_step="wiping demo state",
    )
    await status_callback(progress)

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

        progress.current_step = f"{slug}: indexing {len(scenario_docs)} docs into {target}"
        await status_callback(progress)

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

        progress.current_step = f"{slug}: registering cluster + template + query set"
        await status_callback(progress)

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

        progress.current_step = f"{slug}: importing {len(scenario_judgments_map)} judgments"
        await status_callback(progress)

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

        # 2h. API: REAL study create + poll + digest wait.
        #
        # Previously called /_test/studies/seed-completed which hardcoded
        # best_metric=0.487 for every scenario. The CLI's
        # scripts/seed_meaningful_demos.py:seed_scenario step 8 was rewritten
        # to use real studies in an earlier PR; this path was the holdout
        # that produced the bug surfaced as
        # ``bug_demo_reseed_fake_metric_regression``. Now matches the CLI
        # byte-for-byte so home-button reseed === ``make seed-demo`` output.
        study_id = await _seed_real_study_for_scenario(
            api_client,
            scenario=scenario,
            cluster_id=cluster_id,
            template_id=template_id,
            qset_id=qset_id,
            judgment_list_id=jlist_id,
            status_callback=status_callback,
            progress=progress,
        )
        study_name: str = cast("str", scenario["study_name"])
        results.append((slug, study_id, study_name))
        progress.scenarios_completed += 1
        await status_callback(progress)

    # ---- Step 2b: rich ESCI scenario (5th study). ----
    # Matches scripts/seed_meaningful_demos.py:851 — 1000 docs +
    # LLM-generated judgments + 15-trial study. Failures here are
    # tolerated (the 4 small scenarios are still valuable on their own,
    # per the CLI's policy at line 878-880).
    rich_study_id: str | None = None
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
        progress.scenarios_completed += 1
        await status_callback(progress)

    # ---- Step 3: rename the 4 small studies. ----
    progress.current_step = "renaming studies to tutorial names"
    await status_callback(progress)
    for _slug, study_id, study_name in results:
        await db.execute(
            text("UPDATE studies SET name = :name WHERE id = :id"),
            {"name": study_name, "id": study_id},
        )
    await db.commit()

    # ---- Step 4: build summary + mark status complete. ----
    duration_ms = int((time.monotonic() - started_at) * 1000)
    studies_seeded = len(SCENARIOS) + (1 if rich_study_id is not None else 0)
    summary = ReseedSummary(
        clusters_created=studies_seeded,
        query_sets_created=studies_seeded,
        studies_completed=studies_seeded,
        proposals_created=studies_seeded,
        duration_ms=duration_ms,
    )
    progress.status = "complete"
    progress.finished_at = _now_iso()
    progress.current_step = None
    progress.summary = summary
    await status_callback(progress)
    return summary
