# Implementation Plan — feat_judgments_periodic_resume_sweep

**Date:** 2026-05-14
**Status:** Complete (PR [#104](https://github.com/SoundMindsAI/relyloop/pull/104), squash-merged `bace67d` 2026-05-14)
**Primary spec:** [feature_spec.md](./feature_spec.md)
**Policy source(s):** [CLAUDE.md](../../../../CLAUDE.md), [docs/01_architecture/](../../../01_architecture/)

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR-1 through FR-7.
- No migration, no API, no UI — backend-only worker enhancement.
- Reuse the `reconcile_pr_state` cron pattern verbatim where applicable; share `SUPPORTED_POLL_MINUTES`, do not duplicate.
- Single phase; all 4 stories ship in one PR.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic / Phase | Story | Notes |
|---|---|---|---|
| FR-1 (cron registration) | Epic 1 / Phase 1 | Story 1.3 | Add to `WorkerSettings.cron_jobs` alongside `reconcile_pr_state`. |
| FR-2 (cadence cron-kwargs helper) | Epic 1 / Phase 1 | Story 1.2 | `_resume_sweep_cron_kwargs()` in new `judgments_resume.py`; reuses `SUPPORTED_POLL_MINUTES` from `pr_reconcile`. |
| FR-3 (Settings — cadence) | Epic 1 / Phase 1 | Story 1.1 | `relyloop_judgments_resume_sweep_minutes`. |
| FR-4 (Settings — daily cap) | Epic 1 / Phase 1 | Story 1.1 | `relyloop_judgments_resume_max_per_day`. |
| FR-5 (handler — dedup + cap) | Epic 1 / Phase 1 | Story 1.2 | `resume_stuck_judgment_lists(ctx)` + Redis counter helpers in `judgments_resume.py`. |
| FR-6 (failure-floor metric) | Epic 1 / Phase 1 | Story 1.2 | Two log lines per tick (`judgments_resume_tick_complete` always; `judgment_stuck_detected` when `candidates > 0`). |
| FR-7 (runbook) | Epic 1 / Phase 1 | Story 1.4 | Update `docs/03_runbooks/judgment-generation-debugging.md` + state.md. |

All 7 FRs covered. No deferred phases (spec §3 confirms single-phase).

All 8 ACs covered:
- AC-1, AC-2 → Story 1.1 (Settings) + Story 1.3 (registration).
- AC-3, AC-4, AC-5, AC-6, AC-7 → Story 1.2 (handler integration tests).
- AC-8 → Story 1.2 (cron-kwargs unit test).

## 2) Delivery structure

**Epic 1 — Periodic in-worker resume sweep for stuck judgment lists** (single epic, single phase, 4 stories).

### Conventions (project-specific)

- Settings: `pydantic-settings` Field with `description`, `default`, `ge`/`le` bounds, optional `@field_validator`.
- Cron handler signature: `async def handler(ctx: dict[str, Any]) -> dict[str, int]` per `reconcile_pr_state` precedent at [`backend/workers/pr_reconcile.py:77`](../../../../backend/workers/pr_reconcile.py#L77).
- Cron registration: append to `WorkerSettings.cron_jobs: list[Any] = [cron(<handler>, **<cron_kwargs>())]` at [`backend/workers/all.py:218`](../../../../backend/workers/all.py#L218).
- Redis client lifecycle inside a worker function: `Redis.from_url(get_settings().redis_url, decode_responses=False)` constructed at function start, closed in `finally`. Pattern from [`backend/workers/judgments.py:368`](../../../../backend/workers/judgments.py#L368) + [`:541-543`](../../../../backend/workers/judgments.py#L541-L543).
- Structlog: `logger = structlog.get_logger(__name__)`; structured kwargs in every log call. The first positional arg to `logger.info(...)` / `.warning(...)` is the grep-able event name (structlog renders it as the JSON `event` key) — this matches the `reconcile_pr_state` precedent at [`backend/workers/pr_reconcile.py:88,193`](../../../../backend/workers/pr_reconcile.py#L88). Use an explicit `event_type=` kwarg ONLY when reusing an existing event name across multiple call paths so observability dedupes them (e.g., the new cron's `judgment_resume_enqueued` reuses the boot-sweep's at [`backend/workers/all.py:159`](../../../../backend/workers/all.py#L159); both call sites pass `event_type="judgment_resume_enqueued"`).
- Test fixture for Settings construction: `monkeypatch.setenv("DATABASE_URL_FILE", "/dev/null")` + `monkeypatch.setenv("POSTGRES_PASSWORD_FILE", "/dev/null")` + `get_settings.cache_clear()`. Mirrors [`backend/tests/unit/core/test_settings_pr_poll.py:21-34`](../../../../backend/tests/unit/core/test_settings_pr_poll.py#L21-L34).
- Cron-kwargs unit testing: `settings.__dict__["<field>"] = <value>` to bypass field_validator for fallback testing. Mirrors [`backend/tests/unit/workers/test_poll_cron_kwargs.py:24-27`](../../../../backend/tests/unit/workers/test_poll_cron_kwargs.py#L24-L27).
- Integration test fake-pool: `AsyncMock(return_value=MagicMock())` or `AsyncMock(side_effect=...)` for `enqueue_job`. Mirrors [`backend/tests/unit/services/test_agent_proposals_dispatch.py:159,178,195`](../../../../backend/tests/unit/services/test_agent_proposals_dispatch.py#L159).
- Log capture in tests: `structlog.testing.capture_logs()` context manager. Mirrors [`backend/tests/unit/test_capability_check.py:188-194`](../../../../backend/tests/unit/test_capability_check.py#L188-L194).

### AI Agent Execution Protocol

This plan is meant to be executed by `/impl-execute --all`. Each story below is implemented sequentially. Per-story protocol:

0. Load `architecture.md`, `state.md`, and the feature spec.
1. Read story scope (Outcome + New/Modified files + Key interfaces + Tasks + DoD).
2. Implement code first, then tests.
3. Run `make test-unit` (story-scoped subset acceptable) + `make lint` + `make typecheck`.
4. For Story 1.2 + 1.3: also run `make test-integration` (story-scoped subset).
5. Update story DoD checkboxes via PR description.

---

## Epic 1 — Periodic in-worker resume sweep

### Story 1.1 — Settings fields (cadence + daily cap)

**Outcome:** Operators can configure the sweep cadence (`RELYLOOP_JUDGMENTS_RESUME_SWEEP_MINUTES`) and runaway-loop cap (`RELYLOOP_JUDGMENTS_RESUME_MAX_PER_DAY`) via env vars. Invalid cadence values are rejected at Settings construction (boot) with a clear error message.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/unit/core/test_settings_judgments_resume.py` | Unit tests for the two new Settings fields. ~6 cases covering defaults, env-var reads, whitelist acceptance, whitelist rejection, daily-cap bounds (FR-3, FR-4 → AC-2). |

**Modified files**

| File | Change |
|---|---|
| `backend/app/core/settings.py` | Add `relyloop_judgments_resume_sweep_minutes: int = Field(default=15, ge=1, le=1440, description=...)` + `@field_validator` against `SUPPORTED_POLL_MINUTES` (imported lazily from `backend.workers.pr_reconcile` like the existing `_validate_pr_poll_minutes` at line 185). Add `relyloop_judgments_resume_max_per_day: int = Field(default=24, ge=1, le=10000, description=...)`. |
| `.env.example` | Document both env vars with their defaults and the link to the spec; placed under the existing `RELYLOOP_PR_POLL_MINUTES` block for grouping. |

**Key interfaces**

```python
# backend/app/core/settings.py — new fields in Settings class
relyloop_judgments_resume_sweep_minutes: int = Field(
    default=15,
    ge=1,
    le=1440,
    description=(
        "Cron cadence for the resume_stuck_judgment_lists worker "
        "(feat_judgments_periodic_resume_sweep FR-3). MVP1 default 15. "
        "Restricted to the same whitelist as RELYLOOP_PR_POLL_MINUTES: see "
        "backend.workers.pr_reconcile.SUPPORTED_POLL_MINUTES."
    ),
)

relyloop_judgments_resume_max_per_day: int = Field(
    default=24,
    ge=1,
    le=10000,
    description=(
        "Maximum re-enqueue attempts per (judgment_list_id, UTC day) before "
        "the cron skips a row and emits judgment_resume_capped at WARN "
        "(feat_judgments_periodic_resume_sweep FR-4). MVP1 default 24."
    ),
)

@field_validator("relyloop_judgments_resume_sweep_minutes")
@classmethod
def _validate_judgments_resume_sweep_minutes(cls, value: int) -> int:
    """Same whitelist as relyloop_pr_poll_minutes; lazy import to avoid cycle."""
    from backend.workers.pr_reconcile import SUPPORTED_POLL_MINUTES
    if value not in SUPPORTED_POLL_MINUTES:
        raise ValueError(
            f"RELYLOOP_JUDGMENTS_RESUME_SWEEP_MINUTES={value} is not in the "
            f"supported set {sorted(SUPPORTED_POLL_MINUTES)}. Pick a divisor of "
            "60 (≤60) or a multiple of 60 that divides 1440 (>60)."
        )
    return value
```

**Tasks**
1. Add both Settings fields to `backend/app/core/settings.py` after `relyloop_pr_poll_minutes` (grouped with the existing cron-config field).
2. Add `_validate_judgments_resume_sweep_minutes` field_validator mirroring `_validate_pr_poll_minutes` shape.
3. Document both env vars in `.env.example`.
4. Create `backend/tests/unit/core/test_settings_judgments_resume.py` with 6 cases:
   - `test_sweep_minutes_default_15`
   - `test_sweep_minutes_reads_env`
   - `test_sweep_minutes_accepts_whitelist_values` (parametrize over `SUPPORTED_POLL_MINUTES`)
   - `test_sweep_minutes_rejects_unsupported` (e.g., `7`) — assert `ValidationError`
   - `test_max_per_day_default_24`
   - `test_max_per_day_rejects_zero_and_above_10000`

**Definition of Done (DoD)**
- [ ] Both Settings fields land in `backend/app/core/settings.py` with the documented `Field()` shape.
- [ ] `_validate_judgments_resume_sweep_minutes` rejects `7` with a `ValidationError` whose message lists the supported set.
- [ ] `.env.example` documents both env vars with their defaults.
- [ ] All 6 unit tests in `test_settings_judgments_resume.py` pass: `make test-unit` (story-scoped).
- [ ] `make lint` + `make typecheck` green for `backend/app/core/settings.py`.

### Story 1.2 — `judgments_resume` module (cron-kwargs helper + Redis counter + cron handler)

**Outcome:** A new worker module `backend/workers/judgments_resume.py` exposes the `_resume_sweep_cron_kwargs()` helper, the Redis counter helpers, and the `resume_stuck_judgment_lists(ctx)` cron handler. The handler ticks, queries stuck `judgment_lists`, enqueues with deterministic `_job_id`, increments the per-(id, day) Redis counter, and caps runaway loops. Integration tests cover all 5 acceptance criteria for the handler (AC-3, AC-4, AC-5, AC-6, AC-7) plus the unsupported-cadence fallback (AC-8).

**New files**

| File | Purpose |
|---|---|
| `backend/workers/judgments_resume.py` | The complete module: `SUPPORTED_POLL_MINUTES` re-import, `_resume_sweep_cron_kwargs()`, Redis counter helpers (`resume_counter_key()`, `increment_and_check_cap()`), and the `resume_stuck_judgment_lists(ctx)` cron handler. |
| `backend/tests/unit/workers/test_resume_sweep_cron_kwargs.py` | Unit tests for `_resume_sweep_cron_kwargs()`. ~3 parametrized cases mirroring `test_poll_cron_kwargs.py` (sub-hourly, multi-hour, fallback for unsupported). |
| `backend/tests/unit/workers/test_resume_counter.py` | Unit tests for the Redis counter helpers. ~4 cases covering key shape, INCR + cap check, TTL refresh on every INCR, and the at-cap boundary. Uses `fakeredis.aioredis.FakeRedis` if available; otherwise a `MagicMock(spec=Redis)` with `await`-able methods. |
| `backend/tests/integration/test_judgments_resume_sweep.py` | Integration tests for `resume_stuck_judgment_lists(ctx)`. ~6 cases covering AC-3 (no rows), AC-4 (one row, counter < cap), AC-5 (one row, counter at cap), AC-6 (per-id failure isolation), AC-7 (boot-sweep coexistence), TTL-refresh-on-every-INCR. |

**Modified files**

None for this story. (Story 1.3 will wire the cron into `WorkerSettings`.)

**Key interfaces**

```python
# backend/workers/judgments_resume.py
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from redis.asyncio import Redis

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.workers.pr_reconcile import (
    FALLBACK_POLL_MINUTES,
    SUPPORTED_POLL_MINUTES,
)

logger = structlog.get_logger(__name__)

_TTL_SECONDS = 26 * 60 * 60  # mirrors budget_gate.py


def resume_counter_key(now: datetime, judgment_list_id: str) -> str:
    """Return ``judgments:resume:YYYY-MM-DD:<jid>`` keyed on UTC date.

    Per spec §9 "Required invariants": MUST use UTC date and MUST NOT use
    a TTL shorter than 24h. Mirrors backend/app/llm/budget_gate.py:44-50 but
    is more defensive: callers that hand us a non-UTC aware datetime (or a
    naive datetime they intend as UTC) get the right key — we normalize.
    """
    if now.tzinfo is None:
        utc_now = now.replace(tzinfo=UTC)
    else:
        utc_now = now.astimezone(UTC)
    return f"judgments:resume:{utc_now.strftime('%Y-%m-%d')}:{judgment_list_id}"


async def increment_and_check_cap(
    redis: Redis,
    judgment_list_id: str,
    cap: int,
    *,
    now: datetime | None = None,
) -> tuple[int, bool]:
    """Atomically ``INCR`` the per-(id, day) counter; refresh 26h TTL.

    Returns ``(count, capped)`` where ``capped`` is ``True`` when
    ``count > cap``. TTL is refreshed on every INCR matching the existing
    ``budget_gate.record_cost`` cadence at backend/app/llm/budget_gate.py:86-87.
    """
    now = now or datetime.now(UTC)
    key = resume_counter_key(now, judgment_list_id)
    count = int(await redis.incr(key))
    await redis.expire(key, _TTL_SECONDS)
    return count, count > cap


def _resume_sweep_cron_kwargs() -> dict[str, Any]:
    """Translate ``Settings.relyloop_judgments_resume_sweep_minutes`` into ``arq.cron`` kwargs.

    Mirrors backend/workers/pr_reconcile._poll_cron_kwargs() exactly:
    * n ≤ 60 (divisor of 60): ``minute=set(range(0, 60, n))``.
    * n > 60 (multiple of 60 dividing 1440):
      ``hour=set(range(0, 24, n // 60)), minute={0}``.
    Unsupported values fall back to ``FALLBACK_POLL_MINUTES=15`` with a WARN log.
    """
    n = get_settings().relyloop_judgments_resume_sweep_minutes
    if n not in SUPPORTED_POLL_MINUTES:
        logger.warning(
            "judgments_resume_sweep_minutes_unsupported",
            configured=n,
            falling_back_to=FALLBACK_POLL_MINUTES,
            supported=sorted(SUPPORTED_POLL_MINUTES),
        )
        n = FALLBACK_POLL_MINUTES
    if n <= 60:
        return {"minute": set(range(0, 60, n))}
    return {"hour": set(range(0, 24, n // 60)), "minute": {0}}


async def resume_stuck_judgment_lists(ctx: dict[str, Any]) -> dict[str, int]:
    """Periodic cron sweep — re-enqueue every status='generating' judgment_list.

    Per FR-5: re-enqueue every stuck row this tick. Arq's ``_job_id`` dedup
    makes an in-flight or recently-completed job a no-op by construction; the
    Redis daily counter (per FR-4) caps runaway loops on structurally-broken
    rows.

    Returns ``{candidates, enqueued, capped, errored}`` so the operator can
    grep a single summary line per tick.
    """
    settings = get_settings()
    summary = {"candidates": 0, "enqueued": 0, "capped": 0, "errored": 0}
    cadence_min = settings.relyloop_judgments_resume_sweep_minutes
    cap = settings.relyloop_judgments_resume_max_per_day

    # SELECT stuck rows (close DB session before opening Redis client).
    factory = get_session_factory()
    async with factory() as db:
        candidate_ids = await repo.list_generating_judgment_list_ids(db)
    summary["candidates"] = len(candidate_ids)

    if candidate_ids:
        logger.info(
            "judgment_stuck_detected",
            count=len(candidate_ids),
            cadence_min=cadence_min,
            ids=list(candidate_ids[:10]),
        )

    if not candidate_ids:
        logger.info("judgments_resume_tick_complete", cadence_min=cadence_min, **summary)
        return summary

    redis_client = Redis.from_url(settings.redis_url, decode_responses=False)
    arq_pool = ctx["arq_pool"]
    try:
        for jid in candidate_ids:
            try:
                count, capped = await increment_and_check_cap(redis_client, jid, cap)
                if capped:
                    logger.warning(
                        "judgment_resume_capped",
                        judgment_list_id=jid,
                        count=count,
                        cap=cap,
                    )
                    summary["capped"] += 1
                    continue
                await arq_pool.enqueue_job(
                    "generate_judgments_llm",
                    jid,
                    _job_id=f"generate_judgments_llm:{jid}",
                )
                logger.info(
                    "judgment_resume_enqueued",
                    event_type="judgment_resume_enqueued",
                    judgment_list_id=jid,
                )
                summary["enqueued"] += 1
            except Exception as exc:  # noqa: BLE001 — per-id isolation per FR-5
                logger.warning(
                    "judgment_resume_errored",
                    judgment_list_id=jid,
                    error_type=type(exc).__name__,
                    error_msg=str(exc)[:200],
                )
                summary["errored"] += 1
    finally:
        await redis_client.aclose()

    logger.info("judgments_resume_tick_complete", cadence_min=cadence_min, **summary)
    return summary
```

**Tasks**
1. Create `backend/workers/judgments_resume.py` with the four public symbols + the private constants. Match the docstring shape of `backend/workers/pr_reconcile.py` (top-of-file module docstring referencing FR IDs).
2. Create `backend/tests/unit/workers/test_resume_sweep_cron_kwargs.py` (parametrize sub-hourly + multi-hour over `SUPPORTED_POLL_MINUTES`; add the unsupported-fallback case mirroring `test_poll_cron_kwargs.py`).
3. Create `backend/tests/unit/workers/test_resume_counter.py` with 5 cases:
   - `test_resume_counter_key_format` — UTC date in key, jid embedded correctly.
   - `test_resume_counter_key_normalizes_non_utc_datetime` — pass an aware datetime in a non-UTC tz that crosses the UTC date boundary (e.g., `2026-05-14 23:30 PDT` = `2026-05-15 06:30 UTC`); assert the key uses `2026-05-15`, not `2026-05-14`. Defense against caller error.
   - `test_increment_returns_count_and_capped_below_cap` — at count=1, cap=24 → `(1, False)`.
   - `test_increment_returns_capped_when_post_incr_exceeds_cap` — counter starts at 24, INCR → `(25, True)`.
   - `test_ttl_refreshed_on_every_incr` — after two INCRs, `redis.expire` called twice with `_TTL_SECONDS`.
4. Create `backend/tests/integration/test_judgments_resume_sweep.py` with 6 cases covering AC-3..AC-7 + TTL refresh. Use real Postgres AND real Redis via the existing integration test fixtures — same approach as [`backend/tests/integration/test_budget_guardrail.py`](../../../../backend/tests/integration/test_budget_guardrail.py) and [`backend/tests/integration/test_polling_reconciler.py`](../../../../backend/tests/integration/test_polling_reconciler.py). Do NOT use `MagicMock(spec=Redis)` — AC-4 and AC-5 require concrete counter values and TTL behavior that a bare mock can't faithfully reproduce. Mock only `arq_pool.enqueue_job` via `AsyncMock`.
5. Verify each integration test by running `pytest backend/tests/integration/test_judgments_resume_sweep.py -v` against a running Postgres+Redis (CI fixture or local `make up`).

**Definition of Done (DoD)**
- [ ] `backend/workers/judgments_resume.py` exists with all four public symbols (`_resume_sweep_cron_kwargs`, `resume_counter_key`, `increment_and_check_cap`, `resume_stuck_judgment_lists`).
- [ ] All 3 unit-test cases in `test_resume_sweep_cron_kwargs.py` pass (AC-8).
- [ ] All 5 unit-test cases in `test_resume_counter.py` pass (key format, UTC normalization across date boundary, INCR below cap, INCR at-cap boundary, TTL refresh on every INCR).
- [ ] All 6 integration-test cases in `test_judgments_resume_sweep.py` pass — explicitly covering AC-3 (no-op tick), AC-4 (enqueue with `_job_id`), AC-5 (cap breach), AC-6 (per-id failure isolation), AC-7 (boot-sweep coexistence dedup), and TTL refresh on every INCR.
- [ ] `make lint` + `make typecheck` green for new + modified files.
- [ ] `make test-unit` + targeted `pytest backend/tests/integration/test_judgments_resume_sweep.py` both green.

### Story 1.3 — Register cron in `WorkerSettings`

**Outcome:** The worker boot wires `resume_stuck_judgment_lists` into `WorkerSettings.cron_jobs` alongside `reconcile_pr_state`. After boot, the cron fires per the cadence resolved by `_resume_sweep_cron_kwargs()` (default `minute={0, 15, 30, 45}`). Unit test in `test_workers.py` asserts both crons are registered (AC-1).

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `backend/workers/all.py` | Import `resume_stuck_judgment_lists` and `_resume_sweep_cron_kwargs` from `backend.workers.judgments_resume`. Extend `cron_jobs: list[Any] = [cron(reconcile_pr_state, **_poll_cron_kwargs()), cron(resume_stuck_judgment_lists, **_resume_sweep_cron_kwargs())]`. Update the `WorkerSettings` class docstring to mention both crons. |
| `backend/tests/unit/test_workers.py` | Add `test_resume_judgment_lists_cron_registered`: assert `WorkerSettings.cron_jobs` contains a job whose `coroutine.__name__ == "resume_stuck_judgment_lists"`. Existing `test_pr_reconcile_cron_registered` continues to assert `reconcile_pr_state` is also there (set-membership, not equality, so adding the second cron does not break the existing test). |

**Key interfaces**

```python
# backend/workers/all.py — additions
from backend.workers.judgments_resume import (
    _resume_sweep_cron_kwargs,
    resume_stuck_judgment_lists,
)

class WorkerSettings:
    # ... existing class body ...
    cron_jobs: list[Any] = [
        cron(reconcile_pr_state, **_poll_cron_kwargs()),
        cron(resume_stuck_judgment_lists, **_resume_sweep_cron_kwargs()),
    ]
```

```python
# backend/tests/unit/test_workers.py — new test
def test_resume_judgment_lists_cron_registered(_settings_env: None) -> None:
    """feat_judgments_periodic_resume_sweep FR-1 — resume_stuck_judgment_lists
    registered via cron_jobs (parallel to test_pr_reconcile_cron_registered).
    """
    from backend.workers.all import WorkerSettings

    cron_jobs = getattr(WorkerSettings, "cron_jobs", [])
    assert cron_jobs, "WorkerSettings.cron_jobs missing"
    names = {getattr(job.coroutine, "__name__", None) for job in cron_jobs}
    assert "resume_stuck_judgment_lists" in names
    # Sanity: the existing reconcile_pr_state cron is also still there.
    assert "reconcile_pr_state" in names
```

**Tasks**
1. Edit `backend/workers/all.py` to import the two new symbols + extend `cron_jobs`.
2. Update `WorkerSettings` class docstring to enumerate both crons.
3. Add the new test case to `backend/tests/unit/test_workers.py`.
4. Run `make test-unit` (story-scoped) + `make lint` + `make typecheck`.
5. Smoke test: `make up` and observe `make logs worker` shows both crons in the Arq startup banner (Arq logs scheduled cron jobs at boot).

**Definition of Done (DoD)**
- [ ] `WorkerSettings.cron_jobs` contains exactly 2 entries: `reconcile_pr_state` + `resume_stuck_judgment_lists`.
- [ ] Both existing `test_pr_reconcile_cron_registered` AND new `test_resume_judgment_lists_cron_registered` pass.
- [ ] `make up` boots clean; `make logs worker | head -50` shows Arq scheduling both crons.
- [ ] `make lint` + `make typecheck` green for `backend/workers/all.py`.

### Story 1.4 — Runbook + state.md update (FR-7)

**Outcome:** Operators reading `docs/03_runbooks/judgment-generation-debugging.md` understand the new periodic sweep, the `judgment_resume_capped` triage path, and the relationship between the boot-time sweep and the cron. `state.md` records the feature as Implemented.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `docs/03_runbooks/judgment-generation-debugging.md` | **§"Known limitations (MVP1)" first bullet** — flip from "No periodic in-worker resume sweep — only boot-time. A future `feat_judgments_periodic_resume_sweep` adds cron-based re-enqueueing for stuck `generating` rows" to "**Implemented** — `resume_stuck_judgment_lists` cron registered at PR #N. Tunable via `RELYLOOP_JUDGMENTS_RESUME_SWEEP_MINUTES` (default 15) and capped per-(id, day) by `RELYLOOP_JUDGMENTS_RESUME_MAX_PER_DAY` (default 24)." **New §"Stuck-list cap-breach triage"** — explain what `judgment_resume_capped` means, why it fires (structurally-broken row, e.g., bad rubric), how to inspect `judgment_lists.failed_reason` ([backend/app/db/models/judgment_list.py:56-57](../../../../backend/app/db/models/judgment_list.py#L56-L57)), and the operator's recovery path (fix the underlying issue, manually re-enqueue via the existing `docker compose exec worker python -c "..."` snippet). **§"Resuming a stuck `generating` row manually"** — add a one-line preamble: "The periodic cron resumes stuck rows automatically; this manual path is needed only when the cron is suppressed (cap reached) or the cron itself is failing." |
| `state.md` | Update "Last updated" line to 2026-05-14, post-merge of this feature. Add a new "Most recent meaningful changes" entry summarizing the feature. Update "Active feature" line if relevant. Update "Remaining backlog" count (drops 1 `/pipeline` candidate). |

**Tasks**
1. Edit `docs/03_runbooks/judgment-generation-debugging.md` per the spec FR-7 (flip "Known limitations" + add "Stuck-list cap-breach triage" + tweak manual-recovery preamble). Reference the PR number as `#N` until the PR opens; `/impl-execute` will replace `#N` with the actual number.
2. Edit `state.md`:
   - Update "Last updated" line.
   - Insert a new bullet at the top of "Most recent meaningful changes" describing the feature ship.
   - Update "Remaining backlog" count (was 3 `/bug-fix` + 1 `/pipeline` per the preflight commit → after this lands, becomes 3 `/bug-fix` + 0 `/pipeline`).
3. No code changes; ensure `make lint` + `make typecheck` still green (no-op for doc-only).

**Definition of Done (DoD)**
- [ ] `docs/03_runbooks/judgment-generation-debugging.md` has the "Known limitations" entry flipped to "Implemented" AND the "Stuck-list cap-breach triage" subsection added AND the manual-recovery preamble added.
- [ ] `state.md` reflects the feature as shipped (after impl-execute landed the PR).
- [ ] `make lint` (markdown lint not enforced; this is a no-op check for completeness).
- [ ] No regressions in other tests.

---

## 3) Testing workstream

### 3.1 Unit tests

- Location: `backend/tests/unit/`
- Scope: Settings field validation, cron-kwargs translation, Redis counter math.
- Tasks (assigned to story):
  - [ ] (Story 1.1) `test_settings_judgments_resume.py` — 6 cases.
  - [ ] (Story 1.2) `test_resume_sweep_cron_kwargs.py` — 3 parametrized + fallback cases.
  - [ ] (Story 1.2) `test_resume_counter.py` — 4 cases (key shape, INCR + cap, TTL refresh, at-cap boundary).
  - [ ] (Story 1.3) Extend `test_workers.py` with `test_resume_judgment_lists_cron_registered` — 1 case.
- DoD:
  - [ ] All Story 1.1 + 1.2 + 1.3 unit-test files green via `make test-unit`.

### 3.2 Integration tests

- Location: `backend/tests/integration/`
- Scope: cron handler behavior end-to-end against real Postgres + mocked Redis + fake Arq pool.
- Tasks (assigned to story):
  - [ ] (Story 1.2) `test_judgments_resume_sweep.py` — 6 cases:
    1. **No stuck rows** (AC-3): empty `judgment_lists` table → handler returns `{candidates: 0, ...}`; no `judgment_stuck_detected` log line.
    2. **One stuck row, counter < cap** (AC-4 + FR-6): row `id='ABC', status='generating'`; assert exactly one `arq_pool.enqueue_job` call with `_job_id="generate_judgments_llm:ABC"`; assert Redis counter at `1`; assert TTL ~26h (between `_TTL_SECONDS - 60` and `_TTL_SECONDS`). **Log assertions** via `structlog.testing.capture_logs()`: exactly one `judgment_stuck_detected` event with `{count: 1, cadence_min: 15, ids: ["ABC"]}`, exactly one `judgment_resume_enqueued` event with `{event_type: "judgment_resume_enqueued", judgment_list_id: "ABC"}`, and exactly one `judgments_resume_tick_complete` event with `{candidates: 1, enqueued: 1, capped: 0, errored: 0, cadence_min: 15}`.
    3. **One stuck row, counter at cap** (AC-5): pre-seed `judgments:resume:<today-UTC>:ABC` to `24`; assert no enqueue call; assert one `judgment_resume_capped` log line at WARN; assert counter advances to `25`.
    4. **Per-id failure isolation** (AC-6): two stuck rows; `arq_pool.enqueue_job` raises `redis.exceptions.ConnectionError` on the first call only; assert one enqueue (second row), one `judgment_resume_errored` log line at WARN; handler returns `{candidates: 2, enqueued: 1, capped: 0, errored: 1}`.
    5. **Boot-sweep coexistence dedup** (AC-7): pre-set the Arq pool fake to return `None` on `enqueue_job` (simulating Arq's silent dedup); assert counter still increments + handler still counts it as `enqueued` per the AC-7 note.
    6. **TTL refresh on every INCR**: tick twice against the same stuck row (within the same day); assert `redis.expire` called twice with `_TTL_SECONDS`.
- DoD:
  - [ ] All 6 cases green via `pytest backend/tests/integration/test_judgments_resume_sweep.py -v`.
  - [ ] No flakiness across 3 consecutive runs.

### 3.3 Contract tests

N/A — no API surface added by this feature. No new error codes.

### 3.4 E2E tests

N/A — no UI surface. The `make up` smoke job (per [`pr.yml`](../../../../.github/workflows/pr.yml)) suffices for "the new cron doesn't break boot."

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/unit/test_workers.py` | `test_pr_reconcile_cron_registered` asserts `"reconcile_pr_state" in names` (set membership) | 1 | **No change needed** — adding a second cron doesn't break the existing test because it uses `in`, not equality. Story 1.3 adds a sibling `test_resume_judgment_lists_cron_registered` test. |
| `backend/tests/unit/workers/test_poll_cron_kwargs.py` | Parametrized over `SUPPORTED_POLL_MINUTES` | 18+ | **No change needed** — `SUPPORTED_POLL_MINUTES` is unchanged; this feature reuses (doesn't redefine) the frozenset. |
| `backend/tests/unit/core/test_settings_pr_poll.py` | `relyloop_pr_poll_minutes` Settings field | 7 | **No change needed** — that field is unchanged; this feature adds two parallel fields with their own dedicated test file (Story 1.1). |
| `backend/tests/integration/test_polling_reconciler.py` | `reconcile_pr_state` integration cases | 9 | **No change needed** — `reconcile_pr_state` unchanged. New `test_judgments_resume_sweep.py` is a sibling file. |

### 3.5 Migration verification

N/A — no schema changes.

### 3.6 CI gates

- [ ] `make test-unit` — green.
- [ ] `make test-integration` — green (including the new test file).
- [ ] `make test-contract` — green (no new contract tests; existing surface unchanged).
- [ ] `make lint` + `make typecheck` — green.
- [ ] Smoke job in `pr.yml` — `make up` boots clean with both crons registered.

---

## 4) Documentation update workstream

### 4.0 Core context files

**`state.md`** — updated by Story 1.4:
- [ ] Last-updated date moved to 2026-05-14.
- [ ] Recent-changes bullet added at top.
- [ ] Remaining-backlog count adjusted (drops 1 `/pipeline` candidate; backlog now 3 actionable items).

**`architecture.md`** — no update needed. Cron jobs are listed under the worker layer in the existing `backend/workers/` block; no new top-level layer is added.

**`CLAUDE.md`** — no update needed. The feature doesn't introduce new conventions or env-var patterns beyond what `RELYLOOP_PR_POLL_MINUTES` already established.

### 4.1 Architecture docs (`docs/01_architecture`)

No update. Worker cron jobs are not a separate topical doc surface in MVP1.

### 4.2 Product docs (`docs/02_product`)

- [ ] (Story 1.4 / impl-execute Step 8.6) Move `docs/02_product/planned_features/feat_judgments_periodic_resume_sweep/` → `docs/00_overview/implemented_features/2026_05_14_feat_judgments_periodic_resume_sweep/`. Pre-commit dashboard hook regenerates MVP1_DASHBOARD.md automatically.

### 4.3 Runbooks (`docs/03_runbooks`)

- [ ] (Story 1.4) `judgment-generation-debugging.md` updated per FR-7.

### 4.4 Security docs (`docs/04_security`)

No update. No new secret, no new auth surface, no new external integration.

### 4.5 Quality docs (`docs/05_quality`)

No update. Existing test-layer conventions cover the new tests.

**Documentation DoD**
- [ ] `state.md` consistent with shipped behavior (post-PR-merge).
- [ ] `docs/03_runbooks/judgment-generation-debugging.md` reflects the new cron + cap-breach triage path.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

None. This feature is purely additive. No code paths in `pr_reconcile`, `judgments`, or `all.py` are restructured.

### 5.2 Planned refactor tasks

None.

### 5.3 Refactor guardrails

- [ ] No existing tests modified beyond extending the cron-registered assertion in Story 1.3.
- [ ] `SUPPORTED_POLL_MINUTES` remains the canonical source-of-truth at `backend.workers.pr_reconcile` — this feature only imports, does not redefine.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `arq.cron()` + `WorkerSettings.cron_jobs` | Story 1.3 | Implemented (PR #56 — `feat_github_webhook`) | N/A — already shipped. |
| `SUPPORTED_POLL_MINUTES` frozenset | Story 1.1, 1.2 | Implemented (PR #56) | N/A — already shipped. |
| `repo.list_generating_judgment_list_ids(db)` | Story 1.2 | Implemented (PR #35 — `feat_llm_judgments`) | N/A — already shipped. |
| `arq_pool` in `ctx` via `on_startup` | Story 1.2 | Implemented (PR #25 — `feat_study_lifecycle` Phase 2) | N/A — already shipped. |
| Redis (Compose service + `Settings.redis_url`) | Story 1.2 | Implemented (`infra_foundation`) | N/A — already shipped. |
| `judgment_lists.failed_reason` column (referenced by runbook) | Story 1.4 (runbook) | Implemented (PR #18 — `feat_study_lifecycle` Phase 1) | N/A — column exists at [`backend/app/db/models/judgment_list.py:56-57`](../../../../backend/app/db/models/judgment_list.py#L56-L57). |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Cron registration breaks worker boot (e.g., import cycle) | Low | High (worker won't start) | `judgments_resume.py` imports `SUPPORTED_POLL_MINUTES` + `FALLBACK_POLL_MINUTES` from `backend.workers.pr_reconcile` at module top level. No cycle is possible: `pr_reconcile.py` does NOT import from `judgments_resume.py`. The smoke job in `pr.yml` verifies `make up` boots clean with both crons registered. Note: the `_validate_pr_poll_minutes` field_validator at [`backend/app/core/settings.py:185`](../../../../backend/app/core/settings.py#L185) uses an inside-function import to avoid a different cycle (settings → workers → settings); the new field_validator in Story 1.1 follows the same pattern. |
| Default cap of 24 exhausted by a legitimately long-running judgment generation job | Medium | Low | Documented in spec §10 Threat 5. Boot-sweep at next worker restart covers SIGKILL recovery. Operators raise `RELYLOOP_JUDGMENTS_RESUME_MAX_PER_DAY` if they have legitimately long jobs. |
| Redis transient failure during INCR drops a stuck row from this tick | Medium | Low | Per-id `except Exception` logs `judgment_resume_errored` and continues; next tick retries (no permanent loss). |
| TTL drift (key expires before counter is meaningful) | Low | Low | 26h TTL with refresh on every INCR — exceeds 24h with safety margin. Mirrors budget_gate precedent. |
| `fakeredis.aioredis.FakeRedis` not in dev deps, breaks Story 1.2 integration tests | Low | Low | Fall back to `MagicMock(spec=Redis)` with `await`-able stubs. Spec'd in Story 1.2 Tasks. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Top-level Redis client construction raises | `Redis.from_url` fails (e.g., bad URL) | Exception propagates → Arq logs the tick failure | Next scheduled tick fires; persistent failure = operator must inspect `Settings.redis_url` |
| `repo.list_generating_judgment_list_ids` raises (DB unreachable) | Postgres down | Exception propagates → Arq logs the tick failure | Auto-recovery on next tick when DB returns |
| Per-id `await redis.incr(key)` raises | Redis transient | Logged as `judgment_resume_errored`, loop continues | Next tick retries that id |
| Per-id `arq_pool.enqueue_job` raises | Arq transient or pool exhausted | Logged as `judgment_resume_errored`, loop continues | Next tick retries that id |
| Cap exhausted for a row mid-day during a legit long-running job | Long `generate_judgments_llm` execution | Cron stops re-enqueueing that row; WARN log | Boot-sweep on next worker restart heals; operator can raise cap via env |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** (Settings fields) — must land first; Story 1.2 imports the Settings field.
2. **Story 1.2** (module + tests) — must land before Story 1.3 because Story 1.3 imports from it.
3. **Story 1.3** (cron registration) — depends on Stories 1.1 + 1.2.
4. **Story 1.4** (runbook + state.md) — can run in parallel with 1.3 but is the natural last step (PR number needed for the runbook reference).

### Parallelization opportunities

- Stories 1.1 and 1.2 cannot be parallelized within a single PR (1.2 imports from 1.1).
- Story 1.4 (docs-only) could land as a separate commit on the same PR while 1.3 is in flight.

For `/impl-execute --all`, the natural sequential order is 1.1 → 1.2 → 1.3 → 1.4.

## 8) Rollout and cutover plan

- **Rollout:** Single PR, single deploy (when staging exists at MVP3+; MVP1 has no remote staging — feature lives on the operator's laptop after merge).
- **Feature flag strategy:** None. The Settings field default (`RELYLOOP_JUDGMENTS_RESUME_SWEEP_MINUTES=15`) is the on-by-default behavior. Operators who want it disabled set `=1440` (one tick per day = functionally off; explicit anti-pattern in spec §4 against a boolean toggle).
- **Migration/cutover steps:** None. No schema changes; no data backfill; no breaking changes to existing behavior.
- **Reconciliation/repair:** N/A — feature does not interact with external systems.

## 9) Execution tracker

### Current sprint
- [ ] Story 1.1 — Settings fields (cadence + daily cap)
- [ ] Story 1.2 — `judgments_resume` module + unit + integration tests
- [ ] Story 1.3 — Register cron in `WorkerSettings`
- [ ] Story 1.4 — Runbook + state.md update

### Blocked items
None.

### Done this sprint
(populated as `/impl-execute` lands each story)

## 10) Story-by-Story Verification Gate

Before marking any story complete:

- [ ] Files created/modified match story scope.
- [ ] Key interfaces implemented with documented signatures.
- [ ] Required tests added/updated for the story's layer.
- [ ] Commands executed and passed: `make test-unit` (story-scoped) + `make lint` + `make typecheck`. Plus `make test-integration` for Story 1.2.
- [ ] Story 1.3 specifically: `make up` boots clean with both crons.
- [ ] Story 1.4 specifically: runbook reads cleanly; state.md correctly reflects shipped state.

## 11) Plan consistency review (required before execution)

### 11.1 Spec ↔ plan endpoint count

N/A — feature has zero API endpoints. Spec §8.1 says "N/A — no endpoints added." Plan §3.3 (Contract tests) says "N/A — no API surface." Matches.

### 11.2 Spec ↔ plan FR coverage

| FR | Covered in story | Spec AC mapping |
|---|---|---|
| FR-1 (cron registration) | 1.3 | AC-1 |
| FR-2 (cadence cron-kwargs helper) | 1.2 | AC-8 |
| FR-3 (Settings — cadence) | 1.1 | AC-2 |
| FR-4 (Settings — daily cap) | 1.1 | AC-5 |
| FR-5 (handler — dedup + cap) | 1.2 | AC-3, AC-4, AC-5, AC-6, AC-7 |
| FR-6 (failure-floor metric) | 1.2 | AC-3, AC-4 |
| FR-7 (runbook) | 1.4 | — (operator-visible, not a runtime AC) |

All 7 FRs covered; all 8 ACs covered.

### 11.3 Story internal consistency

- Story 1.1 creates only `test_settings_judgments_resume.py`; modifies only `settings.py` + `.env.example`. No ownership conflict.
- Story 1.2 creates only `judgments_resume.py` + 3 test files. No overlap with Story 1.1's files.
- Story 1.3 modifies only `all.py` + extends `test_workers.py`. No file ownership conflict with Stories 1.1 / 1.2.
- Story 1.4 modifies only `judgment-generation-debugging.md` + `state.md`. No code files touched.

### 11.4 Test file count

5 new test files:
- `backend/tests/unit/core/test_settings_judgments_resume.py` (Story 1.1)
- `backend/tests/unit/workers/test_resume_sweep_cron_kwargs.py` (Story 1.2)
- `backend/tests/unit/workers/test_resume_counter.py` (Story 1.2)
- `backend/tests/integration/test_judgments_resume_sweep.py` (Story 1.2)
- Plus extension of existing `backend/tests/unit/test_workers.py` (Story 1.3)

Matches the testing workstream (§3) inventory.

### 11.5 Gate arithmetic

This plan has 1 epic / 1 phase / 4 stories. The Epic 1 phase gate is implicit: all 4 stories' DoDs satisfied. No explicit endpoint-count gates apply (zero endpoints).

### 11.6 Open questions resolved

Spec §19 lists 0 open questions. The 4 originally-open questions from the preflight are all resolved in the spec's Decision log (2026-05-14 entries).

### 11.7 Plan ↔ codebase verification

| Claim | Verified by | Status |
|---|---|---|
| `backend/app/core/settings.py` has `relyloop_pr_poll_minutes` at line 162 | Read settings.py:162 | Verified |
| `_validate_pr_poll_minutes` field_validator at line 176-193 | Read settings.py:176 | Verified |
| `backend/workers/pr_reconcile.py` exports `SUPPORTED_POLL_MINUTES` + `FALLBACK_POLL_MINUTES` + `_poll_cron_kwargs` | Read pr_reconcile.py:199, 211, 215 | Verified |
| `backend/workers/all.py:218` registers `cron_jobs` | Read all.py:218 | Verified |
| `backend/app/db/repo/judgment_list.py:119` exports `list_generating_judgment_list_ids` | Read judgment_list.py:119 | Verified |
| `backend/workers/all.py:148-161` has the boot-time sweep with `_job_id="generate_judgments_llm:{jid}"` | Read all.py:148-161 | Verified |
| `backend/app/llm/budget_gate.py:86-87` uses `INCRBYFLOAT + EXPIRE` (precedent for "every INCR" TTL refresh) | Read budget_gate.py:86-87 | Verified |
| `backend/workers/judgments.py:368, :541-543` builds + closes Redis per-job | Read judgments.py | Verified |
| `judgment_lists.failed_reason` column exists at [models/judgment_list.py:56-57](../../../../backend/app/db/models/judgment_list.py#L56-L57) | Read judgment_list.py | Verified |
| `backend/tests/unit/test_workers.py:148-161` has `test_pr_reconcile_cron_registered` using set-membership | Read test_workers.py:148 | Verified |

### 11.8 Infrastructure path verification

- Migration path: N/A (no migrations).
- Test file paths: confirmed against `ls backend/tests/unit/workers/`, `ls backend/tests/unit/core/`, `ls backend/tests/integration/` — all paths exist as parent directories; new test files are leaf additions.

### 11.9 Frontend data plumbing

N/A — no frontend scope.

### 11.10 Persistence scope

N/A — feature uses Redis only (server-side, not client-side localStorage/sessionStorage).

### 11.11 Enumerated value contract audit

The only enumerated surface is `SUPPORTED_POLL_MINUTES` — reused, not redefined. Spec §7.4 documents this. Plan Story 1.1 imports `SUPPORTED_POLL_MINUTES` from `backend.workers.pr_reconcile` and uses it in the field_validator. No new enum, no new wire values, no source-of-truth drift risk.

### 11.12 Admin control audit

N/A — MVP1, no admin model.

### 11.13 Audit-event coverage audit

N/A — MVP1, no audit_log table. Spec §6 confirms "N/A — audit_log lands at MVP2."

---

## 12) Definition of plan done

- [x] Every FR (FR-1 through FR-7) mapped to stories/tasks/tests/docs.
- [x] Every story includes New files, Modified files, Key interfaces, Tasks, and DoD.
- [x] Test layers (unit + integration) are explicitly scoped per story.
- [x] Documentation updates planned (Story 1.4 + impl-execute's automatic state.md / dashboard updates).
- [x] No lean refactor required (additive feature).
- [x] Epic / phase gates measurable (single phase; all 4 story DoDs).
- [x] Story-by-Story Verification Gate included.
- [x] Plan consistency review §11 performed with zero unresolved findings.

---

## Cross-model review log (GPT-5.5)

**Cycle 1** — 5 findings (4 Medium + 1 Low). All adjudicated:
- F1 (Medium, Pass A) **Accept partial**: §2 Conventions structlog rule softened — positional event name is the canonical grep-able name (matches `reconcile_pr_state` precedent); explicit `event_type=` only for cross-call name reuse (e.g., the boot-sweep + cron both emit `judgment_resume_enqueued`).
- F2 (Medium, Pass B) **Accept**: `resume_counter_key` now normalizes `now` to UTC before formatting (`.astimezone(UTC)` for aware datetimes; `.replace(tzinfo=UTC)` for naive). Story 1.2 test list expanded from 4 → 5 cases to add a non-UTC tz date-boundary test.
- F3 (Medium, Pass B) **Accept**: Integration Case 2 extended to assert FR-6's full log contract (`judgment_stuck_detected` + `judgment_resume_enqueued` + `judgments_resume_tick_complete` with concrete payloads) via `structlog.testing.capture_logs()`.
- F4 (Medium, Pass B) **Accept**: Dropped the `MagicMock(spec=Redis)` fallback. Story 1.2 now requires real Redis via the existing integration test service container — matches the `test_budget_guardrail.py` + `test_polling_reconciler.py` precedent.
- F5 (Low, Pass A) **Accept**: §6 Risks text corrected — `judgments_resume.py` does top-level imports of `SUPPORTED_POLL_MINUTES` + `FALLBACK_POLL_MINUTES`; no cycle (verified: `pr_reconcile.py` doesn't import back). The lazy-import note now correctly refers only to the Story 1.1 field_validator (settings → workers → settings cycle protection).

None of the accepted findings change the FR scope, AC text, story scope, or contract surface — all are correctness/clarification fixes inside existing stories. Per the cross-model loop stop rule, cycle 1 ships as convergence.
