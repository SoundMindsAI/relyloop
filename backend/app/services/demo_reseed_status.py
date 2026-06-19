# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Status DTOs and Redis persistence for the demo-reseed flow."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Final, Literal, NamedTuple, cast

from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis

from scripts.seed_meaningful_demos import SCENARIOS

logger = logging.getLogger(__name__)


# Redis key holding the JSON-serialized :class:`ReseedStatusResponse`. TTL
# is 1 hour — long enough for any in-flight reseed to finish + the
# operator to see the result, short enough that stale failures clear
# themselves. Per ``bug_demo_reseed_fake_metric_regression`` D-2.
DEMO_RESEED_STATUS_KEY: Final[str] = "demo_reseed:status"
DEMO_RESEED_STATUS_TTL_S: Final[int] = 3600

# Upper bound on the step-history list carried in the status blob. The
# operator-facing reseed UI renders ``steps`` as a scrolling log; the worker
# appends one entry per *distinct* ``current_step`` transition. A real reseed
# emits well under 100 transitions, but the trial-polling loop bumps the step
# string every few seconds, so the count scales with run duration. Cap the
# list at the most recent N so the Redis blob (re-serialized on every poll
# write) can't grow unbounded over a long or pathologically-slow run. Per
# ``feat_demo_reseed_solr_and_steplog``.
DEMO_RESEED_STEP_HISTORY_CAP: Final[int] = 500

# 20-minute hard ceiling on the entire reseed — 4 small scenarios + the
# rich ESCI scenario (1000 docs + LLM judgments + 15-trial study). Per
# scripts/seed_meaningful_demos.py wall-clock notes: small scenarios run
# ~1 min each, the rich scenario adds ~3-5 min, plus digest waits and
# headroom. The advisory lock prevents concurrent runs from piling up;
# this timeout bounds the worst case AND drives the POST handler's
# stale-status auto-recovery (per
# ``bug_demo_reseed_button_silent_enqueue_failure``).
DEMO_RESEED_JOB_TIMEOUT_S: Final[int] = 1200

_RICH_SCENARIO_SLUG: Final[str] = "acme-products-rich-prod"


class ReseedSummary(BaseModel):
    """Returned by the demo reseed orchestrator on success."""

    model_config = ConfigDict(extra="forbid")

    clusters_created: int
    query_sets_created: int
    studies_completed: int
    proposals_created: int
    duration_ms: int


ReseedStatusLiteral = Literal["idle", "running", "complete", "failed"]

# Reason a demo scenario was skipped during reseed. ``user_excluded`` fires
# when the operator's ``engines=[...]`` selection excluded the scenario's
# engine_type before the reachability gate; ``unreachable`` fires when the
# engine container wasn't reachable at probe time (pre-existing semantics
# from ``infra_solr_ci_readiness``). Per
# ``feat_selective_engine_startup_and_demo`` FR-6. Mirrored on the frontend
# at ``ui/src/lib/enums.ts`` ``RESEED_SKIP_REASON_VALUES``.
_SkipReason = Literal["user_excluded", "unreachable"]

# Engine identifier used across the reseed orchestrator + reachability probes.
_EngineType = Literal["elasticsearch", "opensearch", "solr"]

# Live state of one demo scenario within a reseed run. Mirrored on the frontend
# at ``ui/src/lib/enums.ts`` ``SCENARIO_STATE_VALUES``.
# feat_reseed_scenario_manifest_live_state FR-1.
ScenarioState = Literal["pending", "active", "done", "skipped"]


class ScenarioProgress(BaseModel):
    """One entry in the per-run scenario manifest carried on reseed status."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    label: str
    description: str
    engine: _EngineType
    state: ScenarioState
    skip_reason: _SkipReason | None = None


class ReseedStatusResponse(BaseModel):
    """Polling-endpoint response for ``GET /api/v1/_test/demo/reseed/status``."""

    model_config = ConfigDict(extra="forbid")

    status: ReseedStatusLiteral
    started_at: str | None = None
    finished_at: str | None = None
    scenarios_total: int = 0
    scenarios_completed: int = 0
    current_step: str | None = None
    failed_reason: str | None = None
    summary: ReseedSummary | None = None
    steps: list[str] = Field(default_factory=list)
    scenarios_skipped: list[str] = Field(default_factory=list)
    scenarios_skipped_reasons: dict[str, _SkipReason] = Field(default_factory=dict)
    scenarios: list[ScenarioProgress] = Field(default_factory=list)


# Status callback receives an in-progress ReseedStatusResponse and persists
# it. Sync callers (tests) pass a no-op; the Arq worker passes a closure
# that writes the Redis key.
StatusCallback = Callable[[ReseedStatusResponse], Awaitable[None]]


async def _noop_status(_status: ReseedStatusResponse) -> None:
    """Default :type:`StatusCallback` — discards progress updates."""
    return None


class _ScenarioCopy(NamedTuple):
    """Backend-owned label + one-line description for a demo scenario."""

    label: str
    description: str


# Source-of-truth copy for the per-run scenario manifest, keyed by slug, in
# canonical processing order (the 5 SCENARIOS entries then the rich ESCI
# scenario). The order/membership here is locked to SCENARIOS by a unit test
# (AC-7 drift guard) so a SCENARIOS change without a matching copy update fails
# CI rather than KeyError-ing at run time.
# feat_reseed_scenario_manifest_live_state FR-3.
_SCENARIO_COPY: Final[dict[str, _ScenarioCopy]] = {
    "acme-products-prod": _ScenarioCopy(
        "Acme product catalog",
        "E-commerce product search over an electronics catalog",
    ),
    "corp-docs-search": _ScenarioCopy(
        "Corporate knowledge base",
        "Internal company docs & wiki article search",
    ),
    "news-search-staging": _ScenarioCopy(
        "News article search",
        "Time-sensitive news/article retrieval",
    ),
    "jobs-marketplace-prod": _ScenarioCopy(
        "Jobs marketplace",
        "Job-listing search (title + skill matching)",
    ),
    "acme-kb-docs-solr": _ScenarioCopy(
        "Support knowledge base (Solr)",
        "Help-center / support-article search on Apache Solr",
    ),
    _RICH_SCENARIO_SLUG: _ScenarioCopy(
        "Rich product demo",
        "1,000-doc ESCI catalog with LLM-generated relevance judgments",
    ),
}


def _build_scenario_manifest(engines: list[_EngineType] | None) -> list[ScenarioProgress]:
    """Build the all-``pending`` scenario manifest in canonical order."""
    manifest: list[ScenarioProgress] = []
    for scenario in SCENARIOS:
        slug = cast("str", scenario["slug"])
        engine = cast("_EngineType", scenario["engine_type"])
        copy = _SCENARIO_COPY[slug]
        excluded = engines is not None and engine not in engines
        manifest.append(
            ScenarioProgress(
                slug=slug,
                label=copy.label,
                description=copy.description,
                engine=engine,
                state="skipped" if excluded else "pending",
                skip_reason="user_excluded" if excluded else None,
            )
        )
    rich_copy = _SCENARIO_COPY[_RICH_SCENARIO_SLUG]
    rich_excluded = engines is not None and "elasticsearch" not in engines
    manifest.append(
        ScenarioProgress(
            slug=_RICH_SCENARIO_SLUG,
            label=rich_copy.label,
            description=rich_copy.description,
            engine="elasticsearch",
            state="skipped" if rich_excluded else "pending",
            skip_reason="user_excluded" if rich_excluded else None,
        )
    )
    return manifest


def _stamp_scenario(
    progress: ReseedStatusResponse,
    slug: str,
    state: ScenarioState,
    skip_reason: _SkipReason | None = None,
) -> None:
    """Set the manifest entry for ``slug`` to ``state``."""
    for entry in progress.scenarios:
        if entry.slug == slug:
            entry.state = state
            if skip_reason is not None:
                entry.skip_reason = skip_reason
            break
    if state == "done":
        progress.scenarios_completed = sum(1 for s in progress.scenarios if s.state == "done")


def append_step_history(
    steps: list[str],
    step: str | None,
    *,
    cap: int = DEMO_RESEED_STEP_HISTORY_CAP,
) -> None:
    """Append ``step`` to the ordered ``steps`` history in place."""
    if step is None:
        return
    if steps and steps[-1] == step:
        return
    steps.append(step)
    if len(steps) > cap:
        del steps[:-cap]


async def emit_progress(status_callback: StatusCallback, progress: ReseedStatusResponse) -> None:
    """Append the current step to history, then invoke ``status_callback``."""
    append_step_history(progress.steps, progress.current_step)
    await status_callback(progress)


async def status_set(redis: Redis, status: ReseedStatusResponse) -> None:
    """Persist the current reseed status as JSON under :data:`DEMO_RESEED_STATUS_KEY`."""
    payload = json.dumps(status.model_dump(mode="json"))
    await redis.set(DEMO_RESEED_STATUS_KEY, payload, ex=DEMO_RESEED_STATUS_TTL_S)


async def status_get(redis: Redis) -> ReseedStatusResponse:
    """Read the current reseed status; returns ``status="idle"`` when absent."""
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
    """True when a ``running`` status payload is older than ``timeout_s``."""
    if status.status != "running" or status.started_at is None:
        return False
    try:
        started = datetime.fromisoformat(status.started_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if now is None:
        now = datetime.now(UTC)
    if now.tzinfo is None and started.tzinfo is not None:
        now = now.replace(tzinfo=UTC)
    elif now.tzinfo is not None and started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    age_s = (now - started).total_seconds()
    return age_s > timeout_s
