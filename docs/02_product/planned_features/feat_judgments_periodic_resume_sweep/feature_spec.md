# Feature Specification — feat_judgments_periodic_resume_sweep

**Date:** 2026-05-14
**Status:** Draft
**Owners:** RelyLoop maintainers (single-tenant MVP1)
**Related docs:**
- Idea: [idea.md](./idea.md)
- Precedent: [`feat_github_webhook`](../../../00_overview/implemented_features/2026_05_12_feat_github_webhook/feature_spec.md) (cron-pattern source-of-truth)
- Sibling: [`feat_llm_judgments`](../../../00_overview/implemented_features/2026_05_11_feat_llm_judgments/feature_spec.md) (boot-time sweep is at `backend/workers/all.py:127` + `:148-161`)
- Runbook: [`docs/03_runbooks/judgment-generation-debugging.md`](../../../03_runbooks/judgment-generation-debugging.md) §"Resuming a stuck `generating` row manually"

---

## 1) Purpose

- **Problem:** [`feat_llm_judgments`](../../../00_overview/implemented_features/2026_05_11_feat_llm_judgments/) ships a **boot-time** resume sweep at [`backend/workers/all.py:127`](../../../../backend/workers/all.py#L127) + [:148-161](../../../../backend/workers/all.py#L148-L161) that re-enqueues every `judgment_lists.status='generating'` row at worker startup. An `arq.enqueue_job` failure that lands **while the worker is already running** (e.g., transient Redis outage during `POST /api/v1/judgments/generate`) leaves the row stuck in `status='generating'` until the next worker restart. Recovery today is a manual `docker compose exec worker python -c "..."` snippet documented in the runbook — no operator-free self-healing.
- **Outcome:** A new Arq cron job `resume_stuck_judgment_lists` ticks every `RELYLOOP_JUDGMENTS_RESUME_SWEEP_MINUTES` minutes (default 15), re-enqueues every `judgment_lists.status='generating'` row via deterministic `_job_id` dedup, and caps re-enqueues per `(judgment_list_id, UTC day)` via a Redis daily counter so a structurally-broken row cannot drive a runaway loop. Operators stop having to docker-exec for transient enqueue failures; structurally-broken rows surface via a `judgment_resume_capped` WARN log within one day.
- **Non-goal:** This feature does **not** change the boot-time sweep, the `generate_judgments_llm` handler, the API surface, the data model, or the UI. It is strictly an additional background heal path layered onto existing infrastructure.

## 2) Current state audit

### Existing implementations

- **Boot-time resume sweep** — [`backend/workers/all.py:127`](../../../../backend/workers/all.py#L127) (SELECT) + [`:148-161`](../../../../backend/workers/all.py#L148-L161) (enqueue loop). Uses `repo.list_generating_judgment_list_ids(db)` and `arq_pool.enqueue_job("generate_judgments_llm", jid, _job_id=f"generate_judgments_llm:{jid}")`. Logs `event_type=judgment_resume_enqueued` per id at INFO.
- **Cron precedent — `reconcile_pr_state`** — [`backend/workers/all.py:218`](../../../../backend/workers/all.py#L218) registers `cron_jobs: list[Any] = [cron(reconcile_pr_state, **_poll_cron_kwargs())]`. The cron coroutine receives an Arq `ctx: dict[str, Any]` and runs once per tick. This feature adds a sibling entry to that list.
- **Settings + whitelist validator precedent** — [`backend/app/core/settings.py:162-193`](../../../../backend/app/core/settings.py#L162-L193) defines `relyloop_pr_poll_minutes` with `Field(default=15, ge=1, le=1440, ...)` + `@field_validator` that rejects values outside [`backend/workers/pr_reconcile.py:199-209`](../../../../backend/workers/pr_reconcile.py#L199-L209)'s `SUPPORTED_POLL_MINUTES` frozenset (18 cron-expressible values: divisors of 60 ∪ multiples of 60 that divide 1440).
- **Cron-kwargs routing precedent** — [`backend/workers/pr_reconcile.py:215-239`](../../../../backend/workers/pr_reconcile.py#L215-L239) `_poll_cron_kwargs()` translates the integer into `{"minute": set}` (sub-hourly) or `{"hour": set, "minute": {0}}` (multi-hour), with a fallback to `FALLBACK_POLL_MINUTES=15` + WARN log on an unsupported value (defense-in-depth — the field_validator catches it first at boot).
- **Redis daily-counter precedent** — [`backend/app/llm/budget_gate.py`](../../../../backend/app/llm/budget_gate.py) keys per UTC day (`openai:budget:YYYY-MM-DD`) with a 26h TTL + `INCRBYFLOAT` + `EXPIRE` refresh. Atomic, simple, no schema. This feature mirrors the pattern for the per-(id, day) re-enqueue cap.
- **Handler idempotency** — [`backend/workers/judgments.py:1-34`](../../../../backend/workers/judgments.py#L1-L34) docstring confirms `generate_judgments_llm` "bails early if the row vanished or is no longer `status='generating'`" and bulk_create_judgments uses `ON CONFLICT DO NOTHING`. A re-entry is therefore safe under all conditions the cron can produce.

### Navigation and link impact

N/A — backend-only feature, no UI surface, no link or URL changes.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/unit/test_workers.py::test_pr_reconcile_cron_registered` | `cron_jobs` length + coroutine `__name__` set | 1 | Extend assertion: `cron_jobs` MUST now contain BOTH `reconcile_pr_state` AND `resume_stuck_judgment_lists`. The existing test asserts `"reconcile_pr_state" in names` (set-membership, not equality) so it stays green; this feature adds a parallel `test_resume_judgment_lists_cron_registered` test using the same shape. |
| `backend/tests/unit/workers/test_poll_cron_kwargs.py` | Parametrized over `SUPPORTED_POLL_MINUTES` | 18+ | No change. New cron reuses `SUPPORTED_POLL_MINUTES` directly (decision #1 + open question #3 lock); the shared frozenset is already covered. |
| `backend/tests/unit/core/test_settings_pr_poll.py` | `relyloop_pr_poll_minutes` field behavior | 7 | No change. New `relyloop_judgments_resume_sweep_minutes` field gets a parallel `test_settings_judgments_resume_sweep.py` file with the same shape. |
| `backend/tests/integration/test_polling_reconciler.py` | `reconcile_pr_state` tick behavior | 9 | No change. New `resume_stuck_judgment_lists` gets a parallel `test_judgments_resume_sweep.py` (4-6 cases) — see §14. |

### Existing behaviors affected by scope change

- **Boot-time sweep ([`backend/workers/all.py:148-161`](../../../../backend/workers/all.py#L148-L161))**: Current behavior — fires once at worker startup against every `status='generating'` row. New behavior — unchanged. The new cron coexists at the same dedup key (`_job_id=f"generate_judgments_llm:{jid}"`); double-fires within Arq's result-retention window are no-ops by construction. Decision needed: no.
- **`generate_judgments_llm` handler**: Current behavior — handler early-bails on non-`generating` status (idempotent re-entry). New behavior — unchanged. The new cron relies on this exact bail logic, so any future change to it must preserve the "no-op on non-`generating`" property. Decision needed: no.
- **`docker compose exec worker python -c "..."` recovery snippet** ([runbook §"Resuming a stuck `generating` row manually"](../../../03_runbooks/judgment-generation-debugging.md)): Current behavior — operator-driven, surfaced as the workaround for stuck-while-running rows. New behavior — still valid, but rarely needed. Runbook MUST be updated to flag the new cron as the primary heal path; the manual snippet becomes the "needed only if the cron itself is broken" fallback. Decision needed: no.

---

## 3) Scope

### In scope

- New Arq cron job `resume_stuck_judgment_lists` registered in `WorkerSettings.cron_jobs` alongside `reconcile_pr_state`.
- New `Settings` field `relyloop_judgments_resume_sweep_minutes: int` (default `15`) with `@field_validator` against `SUPPORTED_POLL_MINUTES`.
- New `Settings` field `relyloop_judgments_resume_max_per_day: int` (default `24`) with `Field(ge=1, le=10000)` bounds.
- New cron-kwargs helper `_resume_sweep_cron_kwargs()` in `backend/workers/judgments_resume.py` (mirrors `_poll_cron_kwargs()` shape; reuses `SUPPORTED_POLL_MINUTES` + `FALLBACK_POLL_MINUTES`).
- New per-(id, day) Redis counter helpers (private functions inside `backend/workers/judgments_resume.py` — single consumer, small enough to keep co-located): key `judgments:resume:YYYY-MM-DD:<jid>` with 26h TTL, mirroring `backend/app/llm/budget_gate.py:44-50`. Exposes `resume_counter_key(now, jid) -> str` and `increment_and_check_cap(redis, jid, cap, *, now=None) -> tuple[int, bool]`. (If these grow beyond ~50 LOC at impl time, factor to `backend/workers/_resume_counter.py`.)
- Structured-log event-type catalog (all via `structlog`):

  | event_type | Severity | Origin | Per-tick frequency | Required fields |
  |---|---|---|---|---|
  | `judgments_resume_tick_complete` | INFO | **new** (FR-5, FR-6) | exactly 1 per tick | `{candidates, enqueued, capped, errored, cadence_min}` |
  | `judgment_stuck_detected` | INFO | **new** (FR-6) | 0 or 1 per tick (only when `candidates > 0`) | `{count, cadence_min, ids (≤10 truncated)}` |
  | `judgment_resume_enqueued` | INFO | **reused** from boot-time sweep at [`backend/workers/all.py:159`](../../../../backend/workers/all.py#L159) | 0..N per tick | `{judgment_list_id}` |
  | `judgment_resume_capped` | WARN | **new** (FR-5) | 0..N per tick | `{judgment_list_id, count, cap}` |
  | `judgment_resume_errored` | WARN | **new** (FR-5) | 0..N per tick | `{judgment_list_id, error_type, error_msg (truncated)}` |
  | `judgments_resume_sweep_minutes_unsupported` | WARN | **new** (FR-2 fallback) | 0 normally; 1 at first `_resume_sweep_cron_kwargs()` call if validator was bypassed | `{configured, falling_back_to, supported}` |

  Reuse of `judgment_resume_enqueued` is deliberate: operators grepping `make logs | grep judgment_resume_enqueued` see both the boot-sweep and the periodic cron paths under one event_type — that's the desired observability shape (the *path* doesn't matter; the *fact of re-enqueue* does).
- Runbook update at `docs/03_runbooks/judgment-generation-debugging.md` documenting the new cron + the cap-breach signal.
- Test coverage at unit + integration layers (see §14).

### Out of scope

- Schema changes to `judgment_lists` (no `started_at` / `updated_at` / `last_resume_attempted_at` column — locked decision #2 in idea.md).
- Repo-layer additions — feature reuses [`backend/app/db/repo/judgment_list.py:119`](../../../../backend/app/db/repo/judgment_list.py#L119) `list_generating_judgment_list_ids`.
- Cron-handler changes to `generate_judgments_llm` — feature relies on its existing terminal-status bail (verified in §2).
- API surface changes — no new endpoints, no new error codes, no contract surface.
- UI changes — no new dashboard widget, no new "stuck list" view. (If operator demand emerges, capture as a follow-up `feat_judgment_lists_stuck_dashboard` idea file.)
- An operator CLI for manual re-enqueue (`python -m backend.scripts.judgments_resume`). The original `feat_llm_judgments` plan named this CLI at Story 4.2 but it was never shipped, and the runbook's `docker compose exec` snippet is the actual manual recovery path. Building the CLI is a separate scope decision; not included here.
- Cron-tick observability surfaces beyond structlog (e.g., Prometheus, Langfuse). MVP2 brings Langfuse + ClickHouse + SigNoz per [`tech-stack.md` canonical release matrix](../../../01_architecture/tech-stack.md); structured logs are the only MVP1 sink.
- Notifying the operator of cap-breach via email / chat / dashboard. The WARN log is the signal; operators read `make logs` (or its production equivalent) per the runbook.

### API convention check

- **Endpoint prefix convention:** N/A — no endpoints added.
- **Router namespace for this feature:** N/A — no router file modified.
- **HTTP methods:** N/A.
- **Non-auth error envelope shape:** N/A — no API responses produced.
- **Auth error shape:** N/A — no auth surface.

This is a worker-only feature. The only "interface" with the rest of the system is the Settings module + the Arq cron registration list.

### Phase boundaries (if multi-phase)

**Single-phase.** All in-scope items above ship together. No deferred phases — phase 2 would mean adding observability or a UI surface, both of which are explicitly out-of-scope and would be captured as fresh idea files if pulled forward.

## 4) Product principles and constraints

- **Self-healing over operator intervention.** The MVP1 target is a single-operator-laptop install; expecting the operator to read every WARN log and react is unrealistic. Recover transient failures automatically; surface persistent failures loudly enough that the operator notices on the next `make logs` glance.
- **Reuse the `reconcile_pr_state` cron shape verbatim** (locked decision #1 in idea.md). Cross-precedent consistency makes both cron jobs interchangeable in the operator's mental model and the runbook only has to teach one cadence whitelist.
- **No schema delta** (locked decision #2). The `judgment_lists` table has only `created_at`; adding `last_resume_attempted_at` would require a migration + backfill for a self-healing feature that gets the same property cheaper via Redis.
- **Re-enqueue every `status='generating'` row each tick** (locked decision #3) — not "stuck >M minutes". The `_job_id` dedup makes the "stuck threshold" filter redundant; the daily counter prevents runaway loops for structurally-broken rows.
- **CLAUDE.md Absolute Rule #2 (secrets via mounted files):** N/A — no new secrets introduced. The Redis URL is non-secret config (already in Settings).
- **CLAUDE.md Absolute Rule #8 (no hardcoded LLM model names):** N/A — no LLM calls made by this feature.
- **CLAUDE.md Absolute Rule #11 (`/healthz` 200ms timeout):** N/A — this cron runs out-of-band, not inside `/healthz`.

### Anti-patterns

- **Do not** add a `last_resume_attempted_at` column to `judgment_lists` for "observability" — locked decision #2 specifically rules it out. Redis counter + structlog gives the same observability without a migration.
- **Do not** filter `WHERE status='generating' AND created_at < now() - INTERVAL '<M minutes>'` to "only re-enqueue stuck rows" — the `_job_id` dedup makes this redundant and a `created_at < now() - INTERVAL` threshold introduces a tunable that doesn't pull its weight. Re-enqueue every `status='generating'` row each tick and let dedup do the work.
- **Do not** create a separate `SUPPORTED_JUDGMENTS_RESUME_MINUTES` frozenset — reuse `SUPPORTED_POLL_MINUTES` from `backend.workers.pr_reconcile` (open question #3 lock). Two parallel whitelists drift; one shared whitelist stays consistent.
- **Do not** add a `RELYLOOP_JUDGMENTS_RESUME_DISABLED` toggle — operators who don't want the cron can set `RELYLOOP_JUDGMENTS_RESUME_SWEEP_MINUTES=1440` (one tick per day) which is functionally equivalent to disabled for the MVP1 single-operator-laptop target. Adding a boolean toggle creates a third config knob whose only purpose is the same as `1440`.
- **Do not** swallow exceptions inside the cron tick. Per Arq convention, a raised exception fails the tick — the next tick fires on schedule. Defensive `except Exception: pass` masks bugs that should surface.
- **Do not** double-fire the boot-sweep + cron-tick at worker startup (open question #4 lock). The existing `on_startup` hook at [`backend/workers/all.py:148-161`](../../../../backend/workers/all.py#L148-L161) covers boot; the new cron picks up from the next scheduled minute.

## 5) Assumptions and dependencies

- **Dependency:** Arq cron infrastructure (`WorkerSettings.cron_jobs`, `arq.cron()` helper).
  - Why required: registration site for the new cron job.
  - Status: implemented — landed with [`feat_github_webhook`](../../../00_overview/implemented_features/2026_05_12_feat_github_webhook/) (PR #56, merged 2026-05-12).
  - Risk if missing: N/A — already shipped.
- **Dependency:** `SUPPORTED_POLL_MINUTES` frozenset at [`backend/workers/pr_reconcile.py:199-209`](../../../../backend/workers/pr_reconcile.py#L199-L209).
  - Why required: reused by the new field validator + cron-kwargs helper.
  - Status: implemented (same PR #56).
  - Risk if missing: N/A.
- **Dependency:** Redis (already a Compose service; `Settings.redis_url` already populated).
  - Why required: per-(id, day) re-enqueue counter.
  - Status: implemented in `infra_foundation`.
  - Risk if missing: N/A.
- **Dependency:** `repo.list_generating_judgment_list_ids(db)` at [`backend/app/db/repo/judgment_list.py:119`](../../../../backend/app/db/repo/judgment_list.py#L119).
  - Why required: SELECT for stuck rows.
  - Status: implemented — landed with `feat_llm_judgments` (PR #35, merged 2026-05-11).
  - Risk if missing: N/A.
- **Dependency:** `arq_pool` cached in `ctx["arq_pool"]` by `on_startup` ([`backend/workers/all.py:113-114`](../../../../backend/workers/all.py#L113-L114)).
  - Why required: cron handler needs to enqueue child jobs.
  - Status: implemented (same boot-time hook).
  - Risk if missing: N/A.
- **Assumption:** Arq's `_job_id` dedup window is at least the cron cadence (i.e., a job's `_job_id` reservation persists in Redis at least 15 minutes by default). Arq's `result_retention` defaults to 1 day, which comfortably exceeds the 15-minute cadence.
  - Risk if assumption breaks: at the limit, the cron could enqueue a duplicate `generate_judgments_llm` job. The handler's terminal-status bail at [`backend/workers/judgments.py:1-34`](../../../../backend/workers/judgments.py#L1-L34) makes this safe — the second job inspects `judgment_lists.status`, sees `complete`, and returns immediately. Wasted CPU is bounded to one early-bail call per re-enqueue.

## 6) Actors and roles

- Primary actor: **system (the worker itself)**. No human-driven actions in this feature.
- Secondary actor: **operator** — observes `judgment_stuck_detected` and `judgment_resume_capped` log lines; reads the runbook to interpret them. Sets `RELYLOOP_JUDGMENTS_RESUME_*` env vars at install time.
- Role model: N/A — single-tenant install, no auth surface (MVP1).
- Permission boundaries: N/A.

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP2 per [`docs/01_architecture/data-model.md` §"Reserved for later releases"](../../../01_architecture/data-model.md). The cron job does not mutate user-visible state in `judgment_lists` (it only enqueues — the eventual mutation happens inside `generate_judgments_llm`, which is `feat_llm_judgments` scope and predates this feature).

---

## 7) Functional requirements

### FR-1: Cron job registration

- **Requirement:**
  - The system **MUST** register a new Arq cron job named `resume_stuck_judgment_lists` in `WorkerSettings.cron_jobs` at [`backend/workers/all.py:218`](../../../../backend/workers/all.py#L218).
  - Registration **MUST** use `arq.cron(resume_stuck_judgment_lists, **_resume_sweep_cron_kwargs())` so the cadence is sourced from `Settings.relyloop_judgments_resume_sweep_minutes`.
  - The cron list **MUST** contain both `reconcile_pr_state` and `resume_stuck_judgment_lists` after this feature lands.
- **Notes:** Reuses the exact registration pattern from [`feat_github_webhook` FR-2](../../../00_overview/implemented_features/2026_05_12_feat_github_webhook/feature_spec.md). Implementation lives in a new module `backend/workers/judgments_resume.py` (parallel to `pr_reconcile.py`).

### FR-2: Cadence cron-kwargs helper

- **Requirement:**
  - The system **MUST** expose `_resume_sweep_cron_kwargs() -> dict[str, Any]` in `backend/workers/judgments_resume.py`.
  - The helper **MUST** read `Settings.relyloop_judgments_resume_sweep_minutes` and translate it into `arq.cron()` kwargs per the same rules as `_poll_cron_kwargs()`:
    - `n ≤ 60` and `60 % n == 0` → `{"minute": set(range(0, 60, n))}`
    - `n > 60` and `1440 % n == 0` → `{"hour": set(range(0, 24, n // 60)), "minute": {0}}`
    - Unsupported value (validator bypassed by direct attribute mutation in tests) → log `judgments_resume_sweep_minutes_unsupported` at WARN and fall back to `FALLBACK_POLL_MINUTES=15`.
  - The helper **MUST** reuse `SUPPORTED_POLL_MINUTES` and `FALLBACK_POLL_MINUTES` imported from `backend.workers.pr_reconcile` — do not duplicate the frozenset.
- **Notes:** This is the open-question #3 lock: shared whitelist, not a parallel narrower one. The runbook teaches `RELYLOOP_PR_POLL_MINUTES` and `RELYLOOP_JUDGMENTS_RESUME_SWEEP_MINUTES` against the same supported set.

### FR-3: Settings field — sweep cadence

- **Requirement:**
  - The system **MUST** add `relyloop_judgments_resume_sweep_minutes: int = Field(default=15, ge=1, le=1440, description=...)` to `backend/app/core/settings.py`.
  - The field **MUST** be validated against `SUPPORTED_POLL_MINUTES` via an `@field_validator("relyloop_judgments_resume_sweep_minutes")` decorator, mirroring [`backend/app/core/settings.py:176-193`](../../../../backend/app/core/settings.py#L176-L193). Unsupported values **MUST** raise `ValueError` at boot with a message listing the supported set.
  - The env var **MUST** be `RELYLOOP_JUDGMENTS_RESUME_SWEEP_MINUTES` (Pydantic-settings default uppercasing of the field name).
- **Notes:** Default `15` lock from open question #1.

### FR-4: Settings field — daily cap

- **Requirement:**
  - The system **MUST** add `relyloop_judgments_resume_max_per_day: int = Field(default=24, ge=1, le=10000, description=...)` to `backend/app/core/settings.py`.
  - The env var **MUST** be `RELYLOOP_JUDGMENTS_RESUME_MAX_PER_DAY`.
  - The field **MUST** have no whitelist — any integer in `[1, 10000]` is acceptable. (`le=10000` is a sanity ceiling — at 15-min cadence that's >100 re-enqueues per minute, well past any rational operating point.)
- **Notes:** Default `24` lock from open question #2. The bound `le=10000` is defensive; operators don't get to set `MAX_PER_DAY=999999999` and forget about the cap.

### FR-5: Cron handler — re-enqueue with dedup

- **Requirement:**
  - The system **MUST** implement `async def resume_stuck_judgment_lists(ctx: dict[str, Any]) -> dict[str, int]` in `backend/workers/judgments_resume.py`.
  - The handler **MUST**:
    1. Build a fresh DB session via `get_session_factory()` and `SELECT id FROM judgment_lists WHERE status='generating'` via [`repo.list_generating_judgment_list_ids(db)`](../../../../backend/app/db/repo/judgment_list.py#L119). Close the session before any external calls.
    2. Always build a **fresh per-tick** Redis client via `Redis.from_url(get_settings().redis_url, decode_responses=False)` — match the `generate_judgments_llm` shape at [`backend/workers/judgments.py:368`](../../../../backend/workers/judgments.py#L368). Wrap the per-id loop in `try/finally` and close the client in `finally`. **MUST NOT** read or close any worker-shared Redis client from `ctx` — `ctx` carries `arq_pool` and `optuna_storage` from `on_startup`, but no shared Redis counter client; introducing one here would couple the cron's lifecycle to a worker-scoped resource.
    3. For each id, atomically `INCR` the per-(id, day) counter at key `judgments:resume:YYYY-MM-DD:<jid>` and refresh the 26h TTL on **every** INCR. The "EXPIRE on every INCR" cadence matches the existing daily-counter precedent at [`backend/app/llm/budget_gate.py:86-87`](../../../../backend/app/llm/budget_gate.py#L86-L87) (`incrbyfloat` + `expire` on every recorded cost). If `count > relyloop_judgments_resume_max_per_day`: log `judgment_resume_capped` at WARN and skip the enqueue.
    4. Otherwise, call `ctx["arq_pool"].enqueue_job("generate_judgments_llm", jid, _job_id=f"generate_judgments_llm:{jid}")`. Arq's `_job_id` dedup makes an in-flight or recently-completed job a no-op by construction.
    5. Log `judgment_resume_enqueued` (INFO) per successful enqueue; this reuses the same event_type as the boot-time sweep so observability dedupes the two paths.
  - The handler **MUST** return a summary dict `{candidates, enqueued, capped, errored}` and log a final `judgments_resume_tick_complete` (INFO) line with that summary. Mirrors the [`reconcile_pr_state` summary shape at backend/workers/pr_reconcile.py:83](../../../../backend/workers/pr_reconcile.py#L83).
  - On any unhandled exception inside the per-id loop, the handler **MUST** log `judgment_resume_errored` (WARN) with the id + exception type and continue to the next id — one bad id must not break the whole tick. A top-level exception (e.g., DB unreachable, Redis unreachable) is allowed to propagate so Arq logs the tick failure; the next scheduled tick fires per cron schedule.
- **Notes:** The `(judgment_list_id, UTC day)` cap key explicitly uses UTC date to avoid TZ drift between operator-laptop dev and CI. Mirrors [`backend/app/llm/budget_gate.py:44-50`](../../../../backend/app/llm/budget_gate.py#L44-L50).

### FR-6: Failure-floor metric — every tick

- **Requirement:**
  - On every tick, even when zero `generating` rows are found, the system **MUST** emit one `judgments_resume_tick_complete` log line (INFO) with `{candidates, enqueued, capped, errored, cadence_min}`.
  - When `candidates > 0`, the system **MUST** also emit one `judgment_stuck_detected` log line (INFO) with `{count, cadence_min, ids}` where `ids` is the first 10 ids (truncated for log volume; full set available in DB).
- **Notes:** The two-event pattern lets observability alarm on "consecutive ticks with `judgment_stuck_detected.count > 0`" without false positives from tick-no-op (`reconcile_pr_state` follows the same shape at [`pr_reconcile.py:88`](../../../../backend/workers/pr_reconcile.py#L88)).

### FR-7: Runbook update

- **Requirement:**
  - The system **MUST** ship an updated [`docs/03_runbooks/judgment-generation-debugging.md`](../../../03_runbooks/judgment-generation-debugging.md) in the same PR as the code change.
  - The runbook **MUST** add (or update) the "Known limitations (MVP1)" entry that currently cites this idea as future work — flip it to "Implemented at PR #X" and link the spec.
  - The runbook **MUST** add a new "Stuck-list cap-breach triage" subsection explaining: what `judgment_resume_capped` means, why it fires (structurally-broken row — e.g., bad rubric, missing query template), and the operator's recovery path (inspect `judgment_lists.failed_reason`, fix the underlying issue, manually re-enqueue via the existing `docker compose exec worker` snippet).
- **Notes:** The runbook update is the operator-facing artifact; no code change is complete without it.

## 8) API and data contract baseline

### 7.1 Endpoint surface

N/A — no endpoints added.

### 7.2 Contract rules

N/A — no API contract surface.

### 7.3 Response examples

N/A — no responses produced.

### 7.4 Enumerated value contracts

The only enumerated surface this feature introduces is the cadence whitelist, and it is reused (not redefined):

| Field | Accepted values (exact) | Backend source of truth | Frontend call site(s) |
|---|---|---|---|
| `RELYLOOP_JUDGMENTS_RESUME_SWEEP_MINUTES` (env var integer) | `{1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60, 120, 180, 240, 360, 720, 1440}` | [`backend/workers/pr_reconcile.py:199-209`](../../../../backend/workers/pr_reconcile.py#L199-L209) `SUPPORTED_POLL_MINUTES` frozenset (reused, not duplicated) | N/A — env var only, no frontend dropdown |

The cap (`RELYLOOP_JUDGMENTS_RESUME_MAX_PER_DAY`) is a free integer bounded by `Field(ge=1, le=10000)` — not enumerated, no whitelist.

### 7.5 Error code catalog

N/A — no API error codes added. The cron handler raises Python exceptions (`asyncpg.PostgresError`, `redis.exceptions.ConnectionError`) that surface in the worker's structlog output but do not propagate to an HTTP surface.

## 9) Data model and state transitions

### New/changed entities

**None.** This feature ships with **zero** schema changes — locked decision #2.

### Required invariants

- **Re-enqueue counter dedup-key:** The Redis key `judgments:resume:YYYY-MM-DD:<judgment_list_id>` **MUST** use the UTC date and **MUST NOT** be set with a TTL shorter than 24h. (26h, matching `budget_gate.py`, is the locked value.) A shorter TTL would cause the cap to silently reset mid-day at the operator's local-midnight rollover.
- **`_job_id` value:** The Arq enqueue **MUST** use `_job_id=f"generate_judgments_llm:{jid}"` — character-for-character identical to the boot-time sweep at [`backend/workers/all.py:155`](../../../../backend/workers/all.py#L155). Two slightly-different `_job_id` shapes would bypass dedup and allow concurrent runs of the same `(judgment_list_id)` to fire.

### State transitions

N/A — no state transitions in this feature. `judgment_lists.status` transitions are owned by `feat_llm_judgments` and unchanged here.

### Idempotency/replay behavior

- **Within a tick:** Re-running the same tick twice (e.g., manual invocation in a REPL during debugging) atomically double-INCRs the daily counter, advancing the cap by 1 per re-run. The `_job_id` dedup ensures the actual `generate_judgments_llm` job runs at most once per `(id, ~24h)` window from Arq's perspective.
- **Across ticks:** Two consecutive ticks separated by less than `generate_judgments_llm`'s execution time will both attempt to enqueue. The second tick's enqueue is a no-op via `_job_id`. The second tick's INCR still increments the counter — that's the intentional cost model: each *attempted* re-enqueue counts against the cap, not each *successful* enqueue. This is conservative (caps an aggressive caller, not just an aggressive enqueue-succeed pattern).

## 10) Security, privacy, and compliance

- **Threats:**
  1. **Runaway loop driven by a structurally-broken row** (e.g., bad rubric → `generate_judgments_llm` always raises → handler resets status to `generating` and exits → cron re-enqueues → repeat). **Mitigation:** Redis daily counter at default cap of 24 per (id, day). Cap-breach surfaces via WARN log.
  2. **Resource exhaustion from a flood of `generating` rows.** A burst of N stuck rows × every tick = N enqueues per tick. With default cadence 15 min and N=1000 rows, that's 1000 enqueues/15 min = ~67/min — well within Arq's job rate. **Mitigation:** None needed at MVP1 scale (single-operator-laptop, ≤50 query sets typical). At MVP2+ scale (>1000 lists) consider a per-tick batch cap.
  3. **Per-id Redis or Arq failure during the inner loop** (e.g., transient `redis.exceptions.ConnectionError` on INCR, or `arq` raises on `enqueue_job`). **Mitigation:** Each per-id iteration is wrapped in `try/except Exception`; the exception is caught, logged as `judgment_resume_errored` (WARN) with `error_type` + truncated message, and the loop moves to the next id. The tick continues; the failed id is retried on the next scheduled tick.
  4. **Top-level construction failure** (Redis client construction raises, DB SELECT raises, Arq pool unavailable from `ctx`). **Mitigation:** The exception propagates out of the handler → Arq logs the tick failure → the next scheduled cron tick fires per schedule (cron retry policy is "fire on schedule regardless of prior outcome"). No data corruption possible — this handler performs no DB writes; the only mutations are Redis INCR (atomic) and Arq enqueue (idempotent under `_job_id`).
  5. **Cap exhaustion during a legitimately long-running `generate_judgments_llm` job.** Per AC-7 + §9, the counter increments on every *attempted* enqueue (including Arq's silent dedup returns). A job that legitimately runs 6+ hours (e.g., large query set × slow upstream LLM with retries) accumulates ~24 counter INCRs at default 15-min cadence before the cap trips. If the long-running job then dies mid-flight WITHOUT setting `status='failed'` (e.g., container SIGKILL), the cron stops attempting to re-enqueue until UTC midnight rolls the key over. **Mitigation:** The boot-time sweep at [`backend/workers/all.py:148-161`](../../../../backend/workers/all.py#L148-L161) covers SIGKILL recovery on next worker restart (no cap; one re-enqueue per `generating` row at boot). Operators with legitimately long-running judgment generation jobs can raise `RELYLOOP_JUDGMENTS_RESUME_MAX_PER_DAY` (e.g., to `96` = every-tick-all-day for 15-min cadence). Spec keeps the default at `24` because the structurally-broken-row case is the dominant failure mode at MVP1 scale.
- **Controls:**
  - Cap enforcement at FR-5 step 3.
  - Logging at FR-6 (operator-visible signal of every tick + non-zero stuck count).
  - No new write paths (the handler only enqueues; the actual write to `judgment_lists` happens inside `generate_judgments_llm`, which is unchanged).
- **Secrets/key handling:** No new secrets. Reuses `Settings.redis_url`, mounted via the existing `redis_url_file` per CLAUDE.md Rule #2 (or its non-secret-default for local dev).
- **Auditability:** N/A — no `audit_log` until MVP2. Structlog event types serve as the MVP1 audit signal (the cron is the system actor, the action is the enqueue, the target is the `judgment_list_id`, and the timestamp is the log line's `@timestamp`).
- **Data retention/deletion/export:** N/A — feature stores no user data; the Redis counter is opaque to GDPR (no PII).

## 11) UX flows and edge cases

N/A — no UI. The feature is operator-visible only through log lines:

- **Operator workflow:** `make logs api worker | grep -E '(judgment_stuck_detected|judgment_resume_capped|judgments_resume_tick)'` shows the cron's activity.
- **Operator alert criteria** (informal, MVP1):
  - `judgment_stuck_detected.count > 0` for two consecutive ticks → there's a stuck list that isn't healing within one cadence window. Inspect `make logs` for `generate_judgments_llm` failures.
  - `judgment_resume_capped` for any id → structurally-broken row; inspect `judgment_lists.failed_reason` (if populated) or the `generate_judgments_llm` worker logs for the failure pattern.

These are documented in the §7 FR-7 runbook update.

## 12) Given/When/Then acceptance criteria

### AC-1: Cron is registered with default cadence

- Given the worker boots with default Settings (no env vars set).
- When `WorkerSettings.cron_jobs` is inspected.
- Then the list contains exactly two entries: one for `reconcile_pr_state` and one for `resume_stuck_judgment_lists`. The `resume_stuck_judgment_lists` entry's `arq.cron` `minute=` set is `{0, 15, 30, 45}` (default 15-min cadence).
- Example values:
  - Input: default Settings (`RELYLOOP_JUDGMENTS_RESUME_SWEEP_MINUTES` unset).
  - Expected: `{getattr(job.coroutine, "__name__", None) for job in WorkerSettings.cron_jobs} == {"reconcile_pr_state", "resume_stuck_judgment_lists"}`.

### AC-2: Settings field validates the whitelist at boot

- Given the worker boots with `RELYLOOP_JUDGMENTS_RESUME_SWEEP_MINUTES=7` (not in `SUPPORTED_POLL_MINUTES`).
- When `Settings()` is constructed.
- Then a `pydantic.ValidationError` is raised at boot with a message listing the supported set.
- Example values:
  - Input: `RELYLOOP_JUDGMENTS_RESUME_SWEEP_MINUTES=7`.
  - Expected: `pytest.raises(ValidationError)`, message contains `[1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60, 120, 180, 240, 360, 720, 1440]`.

### AC-3: Tick with no stuck rows is a clean no-op

- Given the DB contains zero rows with `status='generating'`.
- When `resume_stuck_judgment_lists({})` runs once (with a populated `ctx["arq_pool"]`).
- Then the handler returns `{"candidates": 0, "enqueued": 0, "capped": 0, "errored": 0}`, logs exactly one `judgments_resume_tick_complete` line, and does NOT log `judgment_stuck_detected`.
- Example values:
  - Input: empty `judgment_lists` table.
  - Expected return: `{"candidates": 0, "enqueued": 0, "capped": 0, "errored": 0}`.

### AC-4: Tick with one stuck row re-enqueues with deterministic `_job_id`

- Given the DB contains one row `judgment_lists.id='ABC', status='generating'` and the Redis counter for that (id, today) is `0`.
- When `resume_stuck_judgment_lists({"arq_pool": <fake>})` runs.
- Then `arq_pool.enqueue_job` is called exactly once with `("generate_judgments_llm", "ABC")` and `_job_id="generate_judgments_llm:ABC"`. The Redis counter for `judgments:resume:<today-UTC>:ABC` is `1` with a TTL of approximately 26h (between `26*3600 - 60` and `26*3600`). Handler returns `{"candidates": 1, "enqueued": 1, "capped": 0, "errored": 0}`.
- Example values:
  - Input: row `id='ABC', status='generating'`; Redis counter unset; cron tick fires.
  - Expected: 1 enqueue, counter=1, TTL ~26h.

### AC-5: Cap breach skips enqueue, emits WARN

- Given the DB contains one row `judgment_lists.id='ABC', status='generating'` and the Redis counter `judgments:resume:<today-UTC>:ABC` is already at `24` (the default cap).
- When `resume_stuck_judgment_lists({"arq_pool": <fake>})` runs.
- Then `arq_pool.enqueue_job` is NOT called for `ABC`. The Redis counter advances to `25` (the INCR still happens — the cap check reads the post-INCR value). The handler logs `judgment_resume_capped` at WARN with `{judgment_list_id: "ABC", count: 25, cap: 24}`. Handler returns `{"candidates": 1, "enqueued": 0, "capped": 1, "errored": 0}`.
- Example values:
  - Input: row `id='ABC', status='generating'`; Redis counter `24`.
  - Expected: zero enqueues, counter=25, exactly one `judgment_resume_capped` log line.

### AC-6: Per-id failure is isolated

- Given the DB contains two rows: `id='ABC', status='generating'` and `id='XYZ', status='generating'`. The Arq pool fake raises `redis.exceptions.ConnectionError` on the first `enqueue_job` call only.
- When `resume_stuck_judgment_lists({...})` runs.
- Then the handler logs `judgment_resume_errored` at WARN for `ABC` (with `error_type='ConnectionError'`) and successfully enqueues `XYZ` on the second call. Handler returns `{"candidates": 2, "enqueued": 1, "capped": 0, "errored": 1}`.
- Example values:
  - Input: 2 stuck rows, first enqueue raises.
  - Expected: 1 enqueue (XYZ), 1 errored (ABC), no tick-level exception.

### AC-7: Dedup with boot-sweep — coexistence is safe

- Given the worker has just booted; `on_startup` enqueued `generate_judgments_llm:ABC` (in-flight at the moment of cron tick).
- When the cron's first tick fires within Arq's `result_retention` window.
- Then the cron's enqueue with `_job_id="generate_judgments_llm:ABC"` is a no-op (Arq returns `None` from `enqueue_job` per the dedup contract). The Redis counter for `ABC` still advances to `1` (the cap counts attempts, not successes — by design). Handler returns `{"candidates": 1, "enqueued": 1, "capped": 0, "errored": 0}` — the `enqueued` counter reflects the cron's *attempt*, not Arq's accepted-vs-deduped decision (that's an internal Arq state).
- Example values:
  - Input: boot-sweep enqueued `ABC` < 1 day ago; cron tick fires; same row still `status='generating'`.
  - Expected: cron's enqueue call returns `None` per Arq dedup; counter=1; no double-job.

**Note on AC-7's `enqueued` counter semantics:** The handler counts every successful `arq_pool.enqueue_job` *call* (including Arq's silent-dedup returns of `None`) as "enqueued" — the cron doesn't introspect Arq's internal dedup result. Operators reading logs see `"enqueued": 1` and know "the cron tried." The actual job count is observable via Arq's own job-completion logs.

### AC-8: Unsupported cadence value at runtime falls back

- Given `Settings.relyloop_judgments_resume_sweep_minutes` is forced to `7` via direct attribute mutation (bypassing the field_validator that would catch this at boot).
- When `_resume_sweep_cron_kwargs()` is called.
- Then it returns `{"minute": set(range(0, 60, 15))}` (the `FALLBACK_POLL_MINUTES=15` default) and emits a `judgments_resume_sweep_minutes_unsupported` WARN log line.
- Example values:
  - Input: forced `relyloop_judgments_resume_sweep_minutes=7`.
  - Expected: kwargs `{"minute": {0, 15, 30, 45}}`.

## 13) Non-functional requirements

- **Performance:** Each tick completes in < 100 ms under MVP1 scale (≤50 `generating` rows expected). At 1000 rows, completion < 2 s (linear DB SELECT + N Redis INCRs + N Arq enqueues; all are sub-ms per call locally).
- **Reliability:** A failed tick (top-level exception) does not affect subsequent ticks — Arq's cron retry policy is "fire on schedule, regardless of prior outcome." No retry budget is consumed.
- **Operability:** All three new event types are structlog-emitted and grep-able. The runbook surfaces the cap-breach signal explicitly. No Prometheus / Langfuse / SigNoz emission in MVP1 (those arrive at MVP2).
- **Accessibility/usability:** N/A — no UI.
- **Resource impact:** One additional Redis client per tick (created + closed inside the handler). One additional DB session per tick. Negligible at all MVP1-realistic scales.

## 14) Test strategy requirements (spec-level)

Minimum required coverage:

### Unit tests (`backend/tests/unit/`)

- **`backend/tests/unit/core/test_settings_judgments_resume.py`** (new file, ~6 cases):
  - `relyloop_judgments_resume_sweep_minutes` defaults to 15.
  - Env var override (`RELYLOOP_JUDGMENTS_RESUME_SWEEP_MINUTES=30`) is read.
  - Whitelist validator accepts `1`, `15`, `1440`.
  - Whitelist validator rejects `7` with a message listing `SUPPORTED_POLL_MINUTES`.
  - `relyloop_judgments_resume_max_per_day` defaults to 24.
  - `relyloop_judgments_resume_max_per_day` rejects `0` and `10001` (bounds).
- **`backend/tests/unit/workers/test_resume_sweep_cron_kwargs.py`** (new file, parametrized over `SUPPORTED_POLL_MINUTES`, ~3 cases):
  - Sub-hourly values produce `{"minute": set(...)}`.
  - Multi-hour values produce `{"hour": set(...), "minute": {0}}`.
  - Unsupported value (forced via `settings.__dict__` mutation) falls back to `{"minute": {0, 15, 30, 45}}`.
- **`backend/tests/unit/test_workers.py::test_resume_judgment_lists_cron_registered`** (extends existing file, +1 case):
  - `WorkerSettings.cron_jobs` contains a job whose `coroutine.__name__ == "resume_stuck_judgment_lists"` AND the existing assertion for `"reconcile_pr_state"` still passes.
- **`backend/tests/unit/workers/test_resume_counter.py`** (new file, ~3 cases):
  - `resume_counter_key(now)` returns `judgments:resume:YYYY-MM-DD:<jid>` with UTC date.
  - `increment_and_check_cap(redis, jid, cap)` returns `(count, capped: bool)` correctly across `count <= cap` and `count > cap`.
  - TTL is refreshed on every INCR (set to 26h ± 60s tolerance).

### Integration tests (`backend/tests/integration/`)

- **`backend/tests/integration/test_judgments_resume_sweep.py`** (new file, ~6 cases mirroring `test_polling_reconciler.py`):
  - **No stuck rows** → `{candidates: 0, ...}`, no `judgment_stuck_detected` log.
  - **One stuck row, counter < cap** → 1 enqueue, counter=1.
  - **One stuck row, counter at cap** → 0 enqueues, 1 `judgment_resume_capped` log.
  - **Two stuck rows, first enqueue raises** → 1 enqueue (second), 1 errored (first); no tick-level exception.
  - **Stuck row + Arq dedup** → enqueue call still happens; assert idempotent behavior via Arq fake's recorded `_job_id`.
  - **TTL refresh on subsequent INCR** → after two ticks against the same id, TTL stays at ~26h (not decaying).

### Contract tests (`backend/tests/contract/`)

- N/A — no API surface.

### E2E tests

- N/A — no UI.

### Operator-acceptance smoke (manual; documented in runbook)

- Spec'd in runbook update (§FR-7) but not part of automated CI. Operator action: bring up the stack, INSERT a row with `status='generating'` and a bad rubric, wait 15 minutes, observe `judgment_resume_enqueued` in logs and `judgment_resume_capped` after 24 ticks (~6 hours at default cadence).

## 15) Documentation update requirements

- **`docs/01_architecture/`:** No new topical doc required. Update [`docs/01_architecture/optimization.md`](../../../01_architecture/optimization.md) only if Arq cron jobs are described there (they aren't currently — confirm during impl). If a "background jobs" appendix is added during impl, document both cron jobs (this one + `reconcile_pr_state`).
- **`docs/02_product/`:** N/A — this spec IS the doc update for product.
- **`docs/03_runbooks/`:** Update [`docs/03_runbooks/judgment-generation-debugging.md`](../../../03_runbooks/judgment-generation-debugging.md) per FR-7. Flip the "Known limitations (MVP1)" entry that currently flags this idea as future work; add the "Stuck-list cap-breach triage" subsection.
- **`docs/04_security/`:** No update. No new auth surface, no new secret, no new external integration.
- **`docs/05_quality/`:** No update to [`testing.md`](../../../05_quality/testing.md). Existing test-layer conventions cover the new tests.
- **`state.md`:** Update active priorities, recent changes, and the "Remaining backlog" count after PR merge — handled by `/impl-execute` Step 7 finalization.
- **`MVP1_DASHBOARD.md`:** Regenerated by pre-commit hook on folder rename + status update; no manual edit needed.

## 16) Rollout and migration readiness

- **Feature flags:** None. The feature is gated entirely by the Settings field — operators who don't want the cron set `RELYLOOP_JUDGMENTS_RESUME_SWEEP_MINUTES=1440` (one tick per day, functionally disabled for the MVP1 target). Anti-pattern §4 forbids a separate boolean toggle.
- **Migration/backfill:** None. No schema changes.
- **Operational readiness gates:** Runbook update (FR-7) MUST land in the same PR as the code change. Otherwise on-call has a feature in production without operator-facing documentation.
- **Release gate:** Standard PR pipeline — `make fmt` + `make lint` + `make typecheck` + `make test-unit` + `make test-integration` + 80% coverage gate. Plus the existing smoke-test job in `pr.yml` (verifies `make up` boots clean) — the new cron registration MUST not break boot.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (cron registration) | AC-1 | Story 1: Settings field. Story 2: cron-kwargs helper. Story 3: cron handler + registration. | `backend/tests/unit/test_workers.py` (extend), `backend/tests/unit/workers/test_resume_sweep_cron_kwargs.py` | — |
| FR-2 (cadence helper) | AC-1, AC-8 | Story 2 | `backend/tests/unit/workers/test_resume_sweep_cron_kwargs.py` | — |
| FR-3 (Settings field — cadence) | AC-1, AC-2 | Story 1 | `backend/tests/unit/core/test_settings_judgments_resume.py` | — |
| FR-4 (Settings field — cap) | AC-5 | Story 1 | `backend/tests/unit/core/test_settings_judgments_resume.py` | — |
| FR-5 (handler — dedup + cap) | AC-3, AC-4, AC-5, AC-6, AC-7 | Story 3: handler. Story 4: Redis counter helper. | `backend/tests/integration/test_judgments_resume_sweep.py`, `backend/tests/unit/workers/test_resume_counter.py` | — |
| FR-6 (failure-floor metric) | AC-3, AC-4 | Story 3 | `backend/tests/integration/test_judgments_resume_sweep.py` (assert log lines via `structlog.testing.capture_logs`) | — |
| FR-7 (runbook) | — (operator-visible) | Story 5: runbook + state.md | — | [`docs/03_runbooks/judgment-generation-debugging.md`](../../../03_runbooks/judgment-generation-debugging.md), `state.md` |

## 18) Definition of feature done

- [ ] All AC-1 through AC-8 pass in CI.
- [ ] Unit tests at `backend/tests/unit/core/test_settings_judgments_resume.py`, `backend/tests/unit/workers/test_resume_sweep_cron_kwargs.py`, `backend/tests/unit/workers/test_resume_counter.py`, and the extended `backend/tests/unit/test_workers.py` are green.
- [ ] Integration tests at `backend/tests/integration/test_judgments_resume_sweep.py` are green.
- [ ] 80% coverage gate clears.
- [ ] Runbook update at `docs/03_runbooks/judgment-generation-debugging.md` landed in the same PR.
- [ ] `state.md` updated (handled by `/impl-execute` finalization).
- [ ] Smoke-test job in `pr.yml` boots `make up` clean with the new cron registered.
- [ ] No open questions in §19 remain unresolved.

## 19) Open questions and decision log

### Open questions

None remaining. The four open questions surfaced during `/idea-preflight` are all locked below in the Decision log.

### Decision log

- **2026-05-11** — Original idea captured during `feat_llm_judgments` cycle-2 plan review. Deferred: "Periodic in-worker sweeps need cron-style infra that isn't yet in the worker."
- **2026-05-12** — `feat_github_webhook` shipped `reconcile_pr_state` cron + `WorkerSettings.cron_jobs` registration + `SUPPORTED_POLL_MINUTES` whitelist + `_poll_cron_kwargs()` translator. Cron infrastructure now exists.
- **2026-05-14 (preflight)** — Folder renamed `chore_judgments_periodic_resume_sweep` → `feat_judgments_periodic_resume_sweep` after work-type re-evaluation. New background behavior + new operator settings + new observability events = feat-shaped per `feature_templates/README.md` "pick the one the user sees first" rule.
- **2026-05-14 (preflight)** — Locked: reuse `reconcile_pr_state` cron-pattern shape verbatim. (No parallel registration pattern.)
- **2026-05-14 (preflight)** — Locked: no schema change to `judgment_lists`. `_job_id` dedup + Redis counter give the same property without a migration.
- **2026-05-14 (preflight)** — Locked: re-enqueue every `status='generating'` row each tick, not "stuck >M minutes". Dedup handles in-flight; cap handles runaway.
- **2026-05-14 (spec)** — Locked: cadence default = **15 minutes** (matches `RELYLOOP_PR_POLL_MINUTES`). Open question #1 resolved.
- **2026-05-14 (spec)** — Locked: daily cap default = **24** (one per hour at 15-min cadence ≈ 1-in-4 ticks). Open question #2 resolved.
- **2026-05-14 (spec)** — Locked: cadence whitelist **reuses** `SUPPORTED_POLL_MINUTES` from `backend.workers.pr_reconcile`. Open question #3 resolved.
- **2026-05-14 (spec)** — Locked: boot sweep handles boot; cron picks up from the next scheduled minute. No double-fire at startup. Open question #4 resolved.
- **2026-05-14 (spec)** — Locked: the `enqueued` summary counter counts attempted enqueues, not Arq-accepted enqueues. Operators read `"enqueued": 1` as "the cron tried"; Arq's own logs show whether the job actually ran. AC-7 note codifies this.
- **2026-05-14 (spec)** — Locked: no operator CLI for manual re-enqueue. The existing `docker compose exec worker python -c "..."` snippet in the runbook is the manual recovery path. Out-of-scope per §3.
- **2026-05-14 (spec)** — Locked: no boolean disable toggle (`RELYLOOP_JUDGMENTS_RESUME_DISABLED`). Set `RELYLOOP_JUDGMENTS_RESUME_SWEEP_MINUTES=1440` for functionally-disabled behavior.
- **2026-05-14 (GPT-5.5 cross-model review cycle 1)** — 6 Medium findings. 5 accepted + applied:
  - F1: Redis client ownership clarified — handler always builds fresh per-tick client, closes in `finally`; never reads from `ctx`. (FR-5 step 2.)
  - F2: TTL refresh standardized to "every INCR" matching `budget_gate.py:86-87` precedent. (FR-5 step 3.)
  - F3: Per-id vs top-level Redis-failure boundary made explicit. (§10 Threats 3+4.)
  - F4: Structured-log event catalog expanded from 3 short bullets to full 6-event table including reuse vs new. (§3.)
  - F5: Long-running-job cap-exhaustion edge case documented; recovery via boot-sweep on next worker restart. (§10 Threat 5.)
  - F6 rejected: `judgment_lists.failed_reason` column existence verified at [`backend/app/db/models/judgment_list.py:56-57`](../../../../backend/app/db/models/judgment_list.py#L56-L57) (`Mapped[str | None] = mapped_column(Text, nullable=True)` with docstring "Populated when `status == 'failed'`"). GPT-5.5's flag was a missed citation, not a real gap.

  None of the accepted findings change the implementation contract (API, data model, AC, invariants) — all are clarification/correctness on FR wording, §3 documentation, and §10 threat enumeration. Per the cross-model loop stop rule, cycle 1 ships as convergence (no major-element re-review required).
