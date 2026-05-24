# OpenAI capability check reports `incapable` after CI repo-secret restore

**Date:** 2026-05-24
**Status:** Idea — surfaced during PR #232 smoke-cascade unblock on 2026-05-24.
**Priority:** P1 — blocks smoke pytest from actually running (it currently `pytest.skip`s because `_wait_healthy` correctly detects the incapable state). Without the smoke pytest, the operator-path tutorial flow is silently uncovered on every PR.
**Origin:** Surfaced after `OPENAI_API_KEY_TEST` repo secret was restored from local `.env` (per operator authorization on 2026-05-24, 16:45 UTC). The smoke gate's sanity-check passed (key non-empty), the api container started cleanly (after the Dockerfile `scripts/` regression was fixed in PR #232), the `_wait_healthy` helper polled `/healthz` for 30s, but every poll returned:

```json
{
  "status": "ok",
  "subsystems": {
    "db": "ok",
    "redis": "ok",
    "openai": "incapable",
    "elasticsearch": "reachable",
    "opensearch": "reachable",
    "elasticsearch_clusters": {"registered": 4, "healthy": 0, "unreachable": 4}
  },
  "openai_capabilities": {
    "chat": "untested",
    "function_calling": "untested",
    "structured_output": "untested"
  }
}
```

`openai: "incapable"` means the capability check ran AND concluded the provider can't satisfy the required capabilities. But all three sub-capabilities are `"untested"` — which is inconsistent (if the check ran, sub-capabilities should be `"ok"` or `"fail"`, not `"untested"`).

## Hypotheses (decreasing likelihood)

1. **The `.env` OPENAI_API_KEY is a different value than the one that was working before the secret was cleared.** The user said they hadn't modified the repo secret; we don't know who/what cleared it. My re-upload from `.env` got the key INTO the secret, but if `.env`'s key has different model access / quota / region than the original, OpenAI's API may reject the capability probes.
2. **The capability check writes the top-level `incapable` flag BEFORE running individual sub-capability checks**, and one early step (e.g. `/v1/models` list) returned a non-2xx response → check short-circuits without populating the sub-fields. Code path at [`backend/app/llm/capability_check.py`](../../../../backend/app/llm/capability_check.py) needs tracing.
3. **OpenAI API issues today** affecting capability probes (network / auth / quota) — would self-resolve if so.

## Reproducing locally

The fastest reproduction is to set the OpenAI key in a fresh stack and watch `/healthz`:

```bash
docker compose restart api
# Wait ~3s for the fire-and-forget capability check to fire
curl -s http://127.0.0.1:8000/healthz | jq '.subsystems.openai, .openai_capabilities'
```

If you see `"incapable"` + `"untested"` × 3 (as above), reproduce confirmed. Tail the api logs:

```bash
docker compose logs api | grep -E "capability_check|OpenAI capability"
```

The structured logs at `backend/app/llm/capability_check.py:68/76/106/114/126/171/179/192/235` should reveal which step failed.

## Suggested fix path

1. **Add log inspection** to identify which capability probe failed. Most likely candidate: the `/v1/models` probe rejected the key with 401.
2. **If the key itself is invalid**: operator rotates the repo secret with a known-good key. Document that "the key in repo secret may diverge from the key in any individual operator's `.env`" — surface the divergence risk in [`docs/01_architecture/llm-orchestration.md`](../../../docs/01_architecture/llm-orchestration.md).
3. **If the capability check has a top-level/sub-field inconsistency bug**: fix the bug so a half-failed check writes the partial sub-capabilities AND the correct top-level value. Currently `"incapable"` + 3× `"untested"` is genuinely confusing.

## Why deferred

Out of scope for PR #232 (`feat_digest_executable_followups_swap_template`). PR #232 is admin-merged with smoke red; the cascade of fixes already applied address 5 of the 8 underlying issues. This bug + [`bug_demo_clusters_unreachable_in_healthz`](../bug_demo_clusters_unreachable_in_healthz/idea.md) are the remaining 2; together they keep the smoke gate red until investigated.

## Relationship to other work

- **Direct blocker for the smoke gate** (and therefore for any PR that needs smoke green to merge without admin override).
- **Probably masked** the original "cleared secret" mystery: it's possible the secret was changed by an operator to a DIFFERENT valid key, then this bug made the new key look broken. We don't know.
- `[chore_tutorial_polish]` §3 + decision log M5 (the sanity-check at `pr.yml:341`) ensured the secret is non-empty but doesn't validate that OpenAI accepts it.
