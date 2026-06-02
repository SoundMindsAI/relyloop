<!--
SPDX-FileCopyrightText: 2026 soundminds.ai

SPDX-License-Identifier: Apache-2.0
-->

# Bug fix — `bug_llm_capability_cache_no_refresh`

**Source idea:** [idea.md](./idea.md)
**Branch:** `bug/llm-capability-cache-no-refresh`
**Type:** bug fix — medium (one subsystem + design fork + cross-layer consumers)
**Date:** 2026-06-02

## Problem

The OpenAI capability check runs **exactly once** at API startup ([`backend/app/main.py:94`](../../../../backend/app/main.py)), caching its result in Redis with a 24h TTL ([`backend/app/llm/capability_check.py:48`](../../../../backend/app/llm/capability_check.py)). Nothing repopulates the cache after expiry. Any stack up >24h silently loses all LLM-dependent capability — `POST /judgments/generate` and the chat orchestrator's tool dispatch return `503 LLM_PROVIDER_INCAPABLE "cache miss"` until the api process restarts. Confirmed live 2026-06-02 on an operator stack at 34h uptime (`redis-cli --scan --pattern 'openai:capabilities:*'` returned zero keys; `docker compose restart api` re-ran the lifespan check and immediately fixed it).

## Reproduction

The bug is repo-portable as a unit test that mirrors the live failure mode (cache exists → key disappears → preflight refuses). The regression test lives at [`backend/tests/unit/test_capability_check.py`](../../../../backend/tests/unit/test_capability_check.py) under `TestReadOrRecomputeCapabilityResult`:

```bash
# Before this fix — fails on main:
.venv/bin/pytest backend/tests/unit/test_capability_check.py::TestReadOrRecomputeCapabilityResult -v

# Expected on main: ImportError (helper doesn't exist) or the cache-miss case
# returns None → operator-facing preflight would raise LLM_PROVIDER_INCAPABLE.
# After this fix: all 4 cases pass; cache-miss recomputes and writes back.
```

## Root cause

- **Owning layer:** `backend/app/llm/capability_check.py` — the cache-write lifecycle ends at startup; there is no read-time refresh trigger.
- **Origin:** [`backend/app/llm/capability_check.py:48`](../../../../backend/app/llm/capability_check.py) — `CACHE_TTL_SECONDS = 86_400` (24h). The TTL is set once when `check_capabilities()` writes (line 357), and nothing re-runs after expiry.
- **Propagation 1:** [`backend/app/main.py:94`](../../../../backend/app/main.py) — `run_capability_check_background(...)` is fired-and-forgotten in the FastAPI `lifespan` startup hook. Once the task completes (or fails), nothing schedules another one for the process's lifetime.
- **Propagation 2:** [`backend/app/services/agent_judgments_dispatch.py:236-253`](../../../../backend/app/services/agent_judgments_dispatch.py) — `_check_llm_preflight` treats `cap is None` (the cache-miss return from [`read_capability_result()` at line 392](../../../../backend/app/llm/capability_check.py)) as a fatal `LLM_PROVIDER_INCAPABLE` 503 with `retryable=False`. After 24h this is the user-visible symptom.

The current behavior is also self-contradictory: `check_capabilities()` is *gentle* on transient failures (caches a degraded result, logs WARN, never crashes), but the surrounding lifecycle is *brittle* on expiry — a healthy endpoint becomes "incapable" purely because wall-clock crossed 24h.

## Fix design (locked decisions)

1. **D-1 (Option A, locked at preflight)** — recompute-on-miss in the preflight (lazy self-heal). New helper `read_or_recompute_capability_result()` in `capability_check.py`: read the cache; on miss with a configured `api_key`, call `check_capabilities()` inline (which writes the result back). Cites: idea D-1 + CLAUDE.md "Bug Fix Protocol — make the minimal change that addresses the root cause."

2. **D-2 (Option B rejected, locked at preflight)** — no background refresh. Reasons: another always-on task to reason about at shutdown; scheduling skew across replicas; disproportionate infrastructure for a per-stack-once-per-24h problem. Cites: idea D-2.

3. **D-3 (Option C rejected, locked at preflight)** — no stale-but-usable semantic. Trades a real correctness property (refuse when capabilities are unknown) for a latency win that D-1 already gets. Cites: idea D-3.

4. **D-4 (final lock — refined after GPT-5.5 PR #426 review)** — **per-worker `asyncio.Lock` single-flight, no Redis-level lock**. The preflight recommended a Redis `SET NX EX` mutex; the original D-4 lock attempted "no lock — `WEB_CONCURRENCY × probes` bound". GPT-5.5's PR #426 final review caught that the "WEB_CONCURRENCY × probes" bound undercounts: a single uvicorn worker can run multiple concurrent request coroutines that all observe the same Redis cache miss between the helper's read and write, and each fire its own probe. True bound was actually `concurrent_requests × probes`, not `WEB_CONCURRENCY × probes`. Refined fix: an `asyncio.Lock` module-global in `capability_check.py` wraps the recompute path, with a double-checked read inside the lock so a coroutine that lost the race sees the populated cache instead of re-probing. Per-worker bound is now exactly **1 probe per cold expiry** regardless of concurrent in-worker requests; cross-worker bound stays at `WEB_CONCURRENCY` (Redis-level lock still rejected — `check_capabilities` is deterministic + Redis writes are last-write-wins + WEB_CONCURRENCY×1 probe is trivially bounded). The asyncio.Lock costs ~6 LOC vs. the Redis lock's ~30 (token generation, EX-timeout tuning, loser-poll, cleanup) — meets the CLAUDE.md "Bug Fix Protocol — minimal change" bar where the no-lock option couldn't. Cites: GPT-5.5 PR #426 final review finding #1; CLAUDE.md minimal-change rule.

5. **D-5 (locked at preflight, scope-narrowed here)** — helper lives in `capability_check.py` (single-source the recompute trigger). **Caller scope narrowed**: only `agent_judgments_dispatch._check_llm_preflight` opts in. `/healthz` stays on the read-only `read_capability_result` because the 200ms `/healthz` SLO ([CLAUDE.md Absolute Rule #11](../../../../CLAUDE.md)) is incompatible with a 1-4s synchronous recompute — `/healthz` correctly reports cache-miss as a degraded `openai` subsystem state without trying to self-heal. The chat orchestrator is unchanged because no live 503 from that path has been reported; it can opt in via a one-line call-site swap if it ever hits the same symptom. Cites: idea D-5 + CLAUDE.md Absolute Rule #11.

### Open questions

None. D-4 (the only fork that was open at preflight) is locked above.

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| Unit | [`backend/tests/unit/test_capability_check.py`](../../../../backend/tests/unit/test_capability_check.py) — `TestReadOrRecomputeCapabilityResult` | Cache-hit path: helper returns the cached `CapabilityResult` without touching the HTTP client. Cache-miss path: helper calls `check_capabilities()`, returns a non-None result, and writes the result back to Redis. Empty-`api_key` path: helper returns `None` (preserves the existing "no key → no probe" semantic). Cached-non-None path: when the cache has a stale-but-present row, helper returns it unchanged (never re-probes on hit). |

The four cases together prove: (a) no regression on the cache-hit path (no new latency), (b) the 24h-expiry symptom is recovered automatically, (c) the empty-key contract is preserved (consumers like `/healthz` still get `None` when no key is configured), (d) the cache-write side effect on miss is preserved (one re-probe regenerates the cache).

Three additional cases were added after the PR #426 GPT-5.5 final review and Gemini Code Assist review surfaced new evidence:

| # | Case | What it proves |
|---|---|---|
| 5 | `check_capabilities` raises during recompute | The helper translates unexpected exceptions to `None` (cap-miss path → 503 LLM_PROVIDER_INCAPABLE) instead of letting them bubble as a generic 500. Matches `run_capability_check_background`'s defensive posture. |
| 6 | 10 concurrent in-worker requests at cold expiry | The `asyncio.Lock` + in-lock double-checked read collapses the burst to exactly 1 probe (single-flight). All 10 callers receive the recomputed result; no stampede. |
| 7 | `api_key=None` (vs empty string) | Same `None`-return semantic as empty-key. Confirms the `str | None` signature is callable with `settings.openai_api_key` directly (no `or ""` boilerplate at the call site). |

## Rollout

None — code-only change. No migration, no new endpoint, no new env var, no operator action. The change is internal to the LLM capability subsystem; the existing 503 `LLM_PROVIDER_INCAPABLE` error path is unaffected for the legitimate cases (`api_key` empty, `structured_output != "ok"`, `model` mismatch). The only behavioral change at the operator-visible layer is: judgments-generation no longer 503s after the 24h cache TTL passes.

## Tangential observations

- None requiring an idea file or inline fix. The capability-check subsystem is otherwise current; existing `test_capability_check.py` cases (degraded probes, models-endpoint failures, transport errors) all stay valid post-helper.
