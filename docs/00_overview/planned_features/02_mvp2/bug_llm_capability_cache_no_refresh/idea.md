# LLM capability cache never refreshes after its 24h TTL expires

**Date:** 2026-06-02
**Status:** Idea — surfaced live while debugging a demo-reseed failure (operator's stack had been up 34h)
**Priority:** P1
**Origin:** Debugging session 2026-06-02. The original symptom was `DemoSeedingError: corp-docs-search/dispatch_ubi_judgments: HTTP 503 LLM_PROVIDER_INCAPABLE "OpenAI capability check (cache miss); structured-output required"`. Root cause traced below.
**Depends on:** None.

## Problem

The OpenAI capability check runs **exactly once**, as a fire-and-forget task in the FastAPI `lifespan` startup hook ([`backend/app/main.py:94`](../../../../backend/app/main.py) — `run_capability_check_background(...)`), and caches its result in Redis with a **24h TTL** (`CACHE_TTL_SECONDS = 86_400` in [`backend/app/llm/capability_check.py:48`](../../../../backend/app/llm/capability_check.py)). Nothing re-runs it while the process keeps running.

Every LLM-gated endpoint reads that cache and **refuses on a miss**. The judgment-dispatch preflight `_check_llm_preflight` ([`backend/app/services/agent_judgments_dispatch.py:236-253`](../../../../backend/app/services/agent_judgments_dispatch.py)) treats `cap is None` as `LLM_PROVIDER_INCAPABLE` (503, `retryable=False`).

The consequence: **any stack left running longer than 24h silently loses all LLM-dependent capability** (UBI hybrid judgment generation, LLM judgments, digest narrative, chat tool dispatch) until the API process is restarted. The cache key simply expires and is never rewritten. This is exactly what bit the operator at 34h uptime — confirmed live: `redis-cli --scan --pattern 'openai:capabilities:*'` returned zero keys, and a `docker compose restart api` (re-running the lifespan check) immediately fixed it.

The current behavior is also self-contradictory: the check is gentle on *transient* failures (it caches a degraded result and logs WARN, never crashes) but brittle on *expiry* (a healthy endpoint becomes "incapable" purely because wall-clock crossed 24h).

## Decisions (locked at preflight 2026-06-02)

- **D-1. Option A locked as the recommended default** — recompute-on-miss in the preflight, with a single-flight guard so concurrent requests don't stampede the probe. Rationale: (a) **strictly safer** than C (never serves a stale "ok" after the endpoint actually went bad); (b) **strictly simpler** than B (no new Arq cron / `asyncio` loop / shutdown-cancellation reasoning — the existing fire-and-forget startup task pattern stays); (c) the latency cost (~1–4s) only fires on first LLM dispatch after expiry, which is exactly when freshness is *wanted*; healthy steady-state dispatches are unaffected. The existing failure mode (503 `LLM_PROVIDER_INCAPABLE` on miss) becomes "recompute then proceed" — operator stops getting paged at the 24h mark.
- **D-2. Option B rejected.** Adds an always-on background task (worker cron or in-process loop) to a problem that fires at most once per 24h per stack. The infra/lifecycle complexity (shutdown cancel/await, scheduling skew across replicas, choice of mechanism — Arq cron vs. `asyncio`) is disproportionate to the bounded latency cost A pays only on first-call-after-expiry.
- **D-3. Option C rejected.** Distinguishing "expired" from "never-checked" by treating stale results as usable-but-trigger-refresh trades a real correctness property (refuse when capabilities are unknown) for a latency win that A already gets via single-flight. The failure mode where the endpoint actually went bad after the last successful check is exactly when stale-serving hurts most.
- **D-4. Single-flight mechanism: Redis `SET NX EX` (operator decision deferred to spec)** — recommended default is a Redis-level lock (`SET openai:capabilities:probe:lock <token> NX EX 10`) rather than an in-process `asyncio.Lock()` since the api runs as multiple worker processes under uvicorn (in-process lock would let each worker fire its own probe concurrently after a cold expiry). Spec should confirm or reject; if rejected, the alternative is to accept the per-worker stampede on the recompute (4 workers × 1 probe per cold expiry is a known, bounded cost).
- **D-5. Single-source the refresh-trigger logic** in `backend/app/llm/capability_check.py` (the cache-write side already lives here), exposing a `read_or_recompute_capability_result(...)` that `agent_judgments_dispatch._check_llm_preflight` + the `/healthz` probe + the chat orchestrator all call. Rationale: the idea correctly notes "the same cache is read by `/healthz` probes and the chat orchestrator — keep them consistent"; consolidating the trigger here makes that a single edit, not three.

## Proposed capabilities

Picks one (D-1 above locks Option A):

### Option A — recompute-on-miss in the preflight (lazy self-heal) **(locked default, D-1)**

- When `read_capability_result(...)` returns `None`, kick a fresh `check_capabilities(...)` inline (await a short-bounded version) before deciding to refuse. Acquire a single-flight Redis lock (`SET openai:capabilities:probe:lock <token> NX EX 10`) per D-4 so concurrent requests across uvicorn workers don't stampede the probe.
- Pro: self-heals exactly when needed; no background machinery; no behavioral change for healthy steady-state dispatches. Con: adds ~1–4s latency to the first LLM dispatch after expiry (which is when freshness is *wanted*).

### Option B — periodic background refresh **(rejected, D-2)**

- A worker cron (Arq already has `cron:` jobs) or an `asyncio` loop re-runs the check on an interval well under the TTL (e.g. every 6–12h), so the cache never goes cold.
- Pro: dispatch latency unaffected. Con: another always-on task to reason about at shutdown; scheduling skew across api replicas; the infra cost is disproportionate to A's bounded latency.

### Option C — distinguish "expired" from "never-checked" **(rejected, D-3)**

- Lengthen/remove the TTL and instead store `tested_at`; the preflight treats a *stale* (old `tested_at`) result as usable-but-trigger-refresh, and only a truly-absent result as a hard miss.
- Pro: never a hard refusal on a previously-healthy endpoint. Con: serves stale "ok" after the endpoint actually went bad — exactly when the wrong answer hurts most.

## Scope signals

- **Backend:** `backend/app/llm/capability_check.py` (refresh trigger / single-flight), `backend/app/services/agent_judgments_dispatch.py` (`_check_llm_preflight` miss handling), possibly `backend/app/main.py` (if background refresh) or `backend/workers/` (if Arq cron). The same cache is read by `/healthz` probes and the chat orchestrator — keep them consistent.
- **Frontend:** none.
- **Migration:** none.
- **Config:** possibly a new `OPENAI_CAPABILITY_REFRESH_INTERVAL` / TTL setting (read from `Settings`, never hardcoded).
- **Audit events:** N/A — Redis cache write, not a tenant-visible state mutation. (Note: the `audit_log` table itself activates at **MVP2** per [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md), not MVP3; either way it doesn't apply to operational-cache writes.)

## Why not fixed inline during the surfacing session

Per the inline-fix-vs-idea rubric: this is a **separate subsystem** from the demo-seed CLI bug that the same session fixed (capability-check lifecycle vs. `scripts/seed_meaningful_demos.py`), and it carries a **genuine design fork** (A/B/C above) with latency-vs-freshness trade-offs that warrant a spec decision rather than a unilateral inline choice. The operational unblock (restart the API) is immediate and was applied, so there is no live incident pressure forcing an inline fix.

## Open questions for /spec-gen

- **Confirm D-4: single-flight lock mechanism.** Recommended default is a Redis `SET NX EX` lock keyed `openai:capabilities:probe:lock`. Alternative is per-worker recompute (no lock — accept the 4-worker stampede on cold expiry as a bounded one-shot cost). Spec should pick. (Everything else is locked in D-1..D-5.)

## Relationship to other work

- Independent of the CLI demo-seed `engine_type` / `study_name` fixes shipped in the same session (those are `scripts/seed_meaningful_demos.py`; this is the LLM capability subsystem).
- Touches the same preflight gate that [`feat_ubi_judgments`](../../implemented_features/2026_05_29_feat_ubi_judgments/feature_spec.md) (PR #317) and [`feat_llm_judgments`](../../implemented_features/2026_05_11_feat_llm_judgments/feature_spec.md) (PR #35) rely on — both already shipped, so this fix lands on top of stable consumers.
- Same `openai:capabilities:*` Redis namespace is also read by `/healthz` subsystem probes and the chat orchestrator's tool-dispatch preflight. Per D-5, the recompute trigger consolidates in `backend/app/llm/capability_check.py` so all three consumers transparently get the self-heal — no per-call-site edits.
