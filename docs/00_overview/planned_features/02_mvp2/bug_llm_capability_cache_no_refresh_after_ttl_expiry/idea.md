# LLM capability cache never refreshes after its 24h TTL expires

**Date:** 2026-06-02
**Status:** Idea — surfaced live while debugging a demo-reseed failure (operator's stack had been up 34h)
**Priority:** P1
**Origin:** Debugging session 2026-06-02. The original symptom was `DemoSeedingError: corp-docs-search/dispatch_ubi_judgments: HTTP 503 LLM_PROVIDER_INCAPABLE "OpenAI capability check (cache miss); structured-output required"`. Root cause traced below.
**Depends on:** None.

## Problem

The OpenAI capability check runs **exactly once**, as a fire-and-forget task in the FastAPI `lifespan` startup hook ([`backend/app/main.py:93`](../../../../backend/app/main.py)), and caches its result in Redis with a **24h TTL** (`CACHE_TTL_SECONDS = 86_400` in [`backend/app/llm/capability_check.py:48`](../../../../backend/app/llm/capability_check.py)). Nothing re-runs it while the process keeps running.

Every LLM-gated endpoint reads that cache and **refuses on a miss**. The judgment-dispatch preflight `_check_llm_preflight` ([`backend/app/services/agent_judgments_dispatch.py:236-253`](../../../../backend/app/services/agent_judgments_dispatch.py)) treats `cap is None` as `LLM_PROVIDER_INCAPABLE` (503, `retryable=False`).

The consequence: **any stack left running longer than 24h silently loses all LLM-dependent capability** (UBI hybrid judgment generation, LLM judgments, digest narrative, chat tool dispatch) until the API process is restarted. The cache key simply expires and is never rewritten. This is exactly what bit the operator at 34h uptime — confirmed live: `redis-cli --scan --pattern 'openai:capabilities:*'` returned zero keys, and a `docker compose restart api` (re-running the lifespan check) immediately fixed it.

The current behavior is also self-contradictory: the check is gentle on *transient* failures (it caches a degraded result and logs WARN, never crashes) but brittle on *expiry* (a healthy endpoint becomes "incapable" purely because wall-clock crossed 24h).

## Proposed capabilities

Pick one (this is the open design fork — a spec should decide):

### Option A — recompute-on-miss in the preflight (lazy self-heal)

- When `read_capability_result(...)` returns `None`, kick a fresh `check_capabilities(...)` inline (or await a short-bounded version) before deciding to refuse.
- Pro: self-heals exactly when needed; no background machinery. Con: adds ~1–4s latency to the first LLM dispatch after expiry; needs a single-flight guard so concurrent requests don't stampede the probe.

### Option B — periodic background refresh

- A worker cron (Arq already has `cron:` jobs) or an `asyncio` loop re-runs the check on an interval well under the TTL (e.g. every 6–12h), so the cache never goes cold.
- Pro: dispatch latency unaffected. Con: runs even when no LLM work is happening; another always-on task to reason about at shutdown.

### Option C — distinguish "expired" from "never-checked"

- Lengthen/remove the TTL and instead store `tested_at`; the preflight treats a *stale* (old `tested_at`) result as usable-but-trigger-refresh, and only a truly-absent result as a hard miss.
- Pro: never a hard refusal on a previously-healthy endpoint. Con: can serve a stale "ok" after the endpoint actually went bad.

## Scope signals

- **Backend:** `backend/app/llm/capability_check.py` (refresh trigger / single-flight), `backend/app/services/agent_judgments_dispatch.py` (`_check_llm_preflight` miss handling), possibly `backend/app/main.py` (if background refresh) or `backend/workers/` (if Arq cron). The same cache is read by `/healthz` probes and the chat orchestrator — keep them consistent.
- **Frontend:** none.
- **Migration:** none.
- **Config:** possibly a new `OPENAI_CAPABILITY_REFRESH_INTERVAL` / TTL setting (read from `Settings`, never hardcoded).
- **Audit events:** N/A (pre-MVP3).

## Why not fixed inline during the surfacing session

Per the inline-fix-vs-idea rubric: this is a **separate subsystem** from the demo-seed CLI bug that the same session fixed (capability-check lifecycle vs. `scripts/seed_meaningful_demos.py`), and it carries a **genuine design fork** (A/B/C above) with latency-vs-freshness trade-offs that warrant a spec decision rather than a unilateral inline choice. The operational unblock (restart the API) is immediate and was applied, so there is no live incident pressure forcing an inline fix.

## Relationship to other work

- Independent of the CLI demo-seed `engine_type` / `study_name` fixes shipped in the same session (those are `scripts/seed_meaningful_demos.py`; this is the LLM capability subsystem).
- Touches the same preflight gate that `feat_ubi_judgments` and `feat_llm_judgments` rely on.
