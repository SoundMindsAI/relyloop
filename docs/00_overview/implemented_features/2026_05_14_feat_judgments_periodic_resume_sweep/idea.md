# Periodic in-worker resume sweep for stuck judgment lists

**Date:** 2026-05-11
**Preflighted:** 2026-05-14 — cron-deferral rationale flipped (precedent shipped); CLI reference corrected; design grounded against the existing `reconcile_pr_state` cron pattern.
**Status:** Idea — deferred from feat_llm_judgments cycle-2 plan review; **eligible** as of 2026-05-12 once `feat_github_webhook` shipped the cron precedent.
**Origin:** `docs/00_overview/implemented_features/2026_05_11_feat_llm_judgments/implementation_plan.md` cycle 2 F1 (Appendix); resume CLI was planned in that plan's Story 4.2 but ultimately not shipped — see Problem section.
**Depends on:** Cron infrastructure shipped in `feat_github_webhook` (PR #56, 2026-05-12). Precedent: [`backend/workers/all.py:218`](../../../../backend/workers/all.py#L218) registers `WorkerSettings.cron_jobs`; [`backend/workers/pr_reconcile.py:199-209`](../../../../backend/workers/pr_reconcile.py#L199-L209) defines `SUPPORTED_POLL_MINUTES`; [`backend/app/core/settings.py:162-193`](../../../../backend/app/core/settings.py#L162-L193) defines `relyloop_pr_poll_minutes` + whitelist validator. This idea reuses the entire shape.

## Problem

`feat_llm_judgments` Story 2.1 ships a **boot-time** resume sweep in
[`backend/workers/all.py:127`](../../../../backend/workers/all.py#L127) + [:148-161](../../../../backend/workers/all.py#L148-L161): every `judgment_lists.status='generating'`
row gets re-enqueued at worker boot via deterministic `_job_id=f"generate_judgments_llm:{jid}"`,
covering the case where `POST /judgments/generate` committed the row but
`arq.enqueue_job` raised mid-call (Redis transient outage).

Gap: an Arq enqueue failure that lands **while the worker is already
running** leaves the row stuck in `status='generating'` until the next
worker restart. The runbook ([`docs/03_runbooks/judgment-generation-debugging.md` §"Resuming a stuck `generating` row manually"](../../../03_runbooks/judgment-generation-debugging.md)) documents a manual recovery via `docker compose exec worker python -c "..."` that enqueues directly through Arq. (Note: the original `feat_llm_judgments` plan named a `python -m backend.scripts.judgments_resume` CLI at Story 4.2 but that CLI was never shipped — `backend/scripts/` does not exist; the docker-exec snippet is the actual operator path.)

A periodic in-worker sweep would heal these without operator
intervention — and the necessary cron infrastructure now exists
(see "Depends on" above), so the deferral rationale that originally
sent this to an idea file no longer applies.

## Proposed capabilities

### In-worker periodic re-enqueue

Register a new Arq cron job `resume_stuck_judgment_lists` in
`backend/workers/all.py` alongside the existing `reconcile_pr_state`
entry. Each tick:

* `SELECT id FROM judgment_lists WHERE status='generating'` via the existing
  [`repo.list_generating_judgment_list_ids(db)`](../../../../backend/app/db/repo/judgment_list.py#L119) — no new repo helper needed; no
  schema change (the `judgment_lists` table has only `created_at`, no
  `updated_at`/`started_at`, so we deliberately avoid taking a column
  delta in this idea — see locked decision #2).
* For each id, call `arq_pool.enqueue_job("generate_judgments_llm", jid, _job_id=f"generate_judgments_llm:{jid}")` — the deterministic `_job_id` mirrors the boot-time sweep ([`backend/workers/all.py:152-156`](../../../../backend/workers/all.py#L152-L156)) and is also Arq's dedup key, so an already-in-flight or recently-completed job makes the enqueue a no-op. This deliberately replaces the earlier "fetch the most recent Arq job log entry" handwave — Arq doesn't expose a queryable last-observed timestamp, but `_job_id` dedup gives us the same property cheaper.
* Runaway-loop guard: Redis daily counter `judgments:resume:YYYY-MM-DD:<jid>` with `INCR` + 26h `EXPIRE` (mirrors the existing budget-gate key pattern at [`backend/app/llm/budget_gate.py:47-50`](../../../../backend/app/llm/budget_gate.py#L47-L50) — `openai:budget:YYYY-MM-DD`). Gate the re-enqueue on counter `< max`; on breach, log `event_type=judgment_resume_capped` at WARN and skip.
* The handler `generate_judgments_llm` already early-bails on terminal status, so re-enqueueing a row that completed between SELECT and enqueue is safe (the bail logic is the same one the boot sweep relies on).

### Failure-floor metric

Emit a structured `event_type=judgment_stuck_detected` log line on every
sweep tick with `count`, `ids`, and `cadence_min` so observability can
alarm when N>0 lists are stuck across consecutive sweeps. Per-id WARN
`event_type=judgment_resume_capped` when the daily cap trips — that's
the signal a list is structurally broken (e.g., bad rubric) and needs
operator inspection.

## Scope signals

- **Backend:** new Arq cron job `resume_stuck_judgment_lists` registered in `WorkerSettings.cron_jobs`; new Settings field `relyloop_judgments_resume_sweep_minutes` + `@field_validator` against `SUPPORTED_POLL_MINUTES` whitelist (or a parallel narrower set; see open question #1). No new repo helpers — reuses `list_generating_judgment_list_ids`.
- **Frontend:** none
- **Migration:** none (uses existing `status` column; daily counter lives in Redis)
- **Config:** new settings `RELYLOOP_JUDGMENTS_RESUME_SWEEP_MINUTES` (default 15, matching `RELYLOOP_PR_POLL_MINUTES`) and `RELYLOOP_JUDGMENTS_RESUME_MAX_PER_DAY` (default 24 — see open question #2). Names use the `RELYLOOP_*` prefix matching the existing precedent at [`backend/app/core/settings.py:162`](../../../../backend/app/core/settings.py#L162).
- **Audit events:** N/A (MVP1; audit_log lands at MVP2)

## Locked decisions

1. **Reuse the `reconcile_pr_state` cron precedent verbatim.** Same `WorkerSettings.cron_jobs` registration site, same `_poll_cron_kwargs()`-style sub-hour/multi-hour cadence routing, same `SUPPORTED_POLL_MINUTES` whitelist + field_validator pattern. Rationale: cross-precedent consistency makes the cadence settings interchangeable in the operator's mental model and lets the cron-cadence runbook serve both jobs.
2. **No schema change.** Specifically, do NOT add a `started_at` / `updated_at` / `last_resume_attempted_at` column to `judgment_lists`. Arq's `_job_id` dedup gives us the "don't re-enqueue what's already running" property without a column; the Redis daily counter handles the per-(id, day) cap. Adding a column would require a migration and a backfill default — out of scope for a self-healing chore. (If a future feature genuinely needs durable per-row observability state, raise it then.)
3. **Re-enqueue every `status='generating'` row each tick, not "stuck >M minutes".** The dedup makes the "stuck >M minutes" filter redundant: an in-flight job's enqueue is a no-op via `_job_id`. The daily-counter cap prevents runaway loops for structurally-broken rows. Simpler than tracking a "how long has it been generating" duration we don't have a column for anyway.

## Why deferred (historical — now eligible)

* **Original rationale (2026-05-11):** MVP1 shipped a boot-time sweep + a planned CLI; both were considered sufficient for the single-operator-laptop deployment target. Periodic in-worker sweeps were said to need cron-style infra not yet wired in the worker.
* **What changed:** `feat_github_webhook` (PR #56, merged 2026-05-12) wired Arq `cron_jobs` for `reconcile_pr_state` and shipped the full surrounding pattern (settings field, whitelist validator, sub-hour/multi-hour cadence routing). The "no cron infra" blocker no longer exists. **This idea is now eligible to run through `/pipeline` whenever the operator chooses to pull it forward.**
* The original idea also leaned on a `python -m backend.scripts.judgments_resume` CLI as the MVP1 workaround; that CLI was never shipped — the actual runbook recovery path is a `docker compose exec worker python -c "..."` snippet (see Problem section). The change in workaround shape doesn't affect this idea's design but it does mean "manual CLI exists" is no longer accurate framing.

## Relationship to other work

* **`feat_github_webhook`** (shipped 2026-05-12) — provides the cron infrastructure this idea reuses. No coordination needed beyond grounding the design in its precedent.
* **`feat_llm_judgments`** (shipped 2026-05-11) — owns the boot-time sweep this idea complements. The `_job_id` convention used here (`generate_judgments_llm:{jid}`) is the same one the boot sweep already uses, so the periodic sweep and the boot sweep dedup against each other automatically.
* **No interference with sibling planned features:** `feat_chat_last_message_preview`, `chore_digest_worker_narrow_except`, `infra_arq_subprocess_test` all touch different surfaces.

## Open questions for /spec-gen

1. **Cadence default.** Recommend `15` minutes (matches `RELYLOOP_PR_POLL_MINUTES` and gives runaway-recovery within one cadence cycle). Alternatives: `5` (faster heal, more Redis/DB hits) or `60` (less load, longer stuck windows). **Recommendation: 15.**
2. **`RELYLOOP_JUDGMENTS_RESUME_MAX_PER_DAY` default.** Recommend `24` (one re-enqueue per hour — enough to recover a transient Redis blip but a structurally-broken row trips the cap within a day and surfaces via the WARN log). At 15-min cadence × 24h = 96 ticks/day, so 24 caps at roughly 1-in-4 ticks. Alternatives: `12` (stricter cap, less noise) or `96` (every tick allowed; relies entirely on `_job_id` dedup). **Recommendation: 24.**
3. **Cadence whitelist scope.** Reuse the shared `SUPPORTED_POLL_MINUTES` frozenset from `backend.workers.pr_reconcile`, or define a narrower local whitelist (e.g., `{5, 10, 15, 30, 60}`)? **Recommendation: reuse** — keeps the operator's mental model uniform across both cron jobs and the runbook only has to teach one whitelist.
4. **Boot-sweep coexistence.** Should the new cron job also fire once at worker boot (in addition to its scheduled tick), or do we rely on the existing `on_startup` sweep at `backend/workers/all.py:148-161` to cover boot? **Recommendation: rely on existing `on_startup` sweep** — it already does the same `_job_id`-deduped re-enqueue for `generating` rows; double-firing on boot is redundant.
