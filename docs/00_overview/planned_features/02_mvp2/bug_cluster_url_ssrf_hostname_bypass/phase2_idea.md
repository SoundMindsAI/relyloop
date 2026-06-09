# bug_cluster_url_ssrf_hostname_bypass — Phase 2: connect-time IP pinning (DNS-rebinding defense)

**Date:** 2026-06-09
**Status:** Idea — deferred Phase 2 of `feature_spec.md` (see §3 Phase boundaries + §19 D-4)
**Priority:** Backlog
**Origin:** `feature_spec.md` §3 "Phase boundaries" + §10 Threat 3 (residual DNS-rebinding risk). Phase 1 closes the standing unconditional hostname bypass at registration/test-connection time but does not pin the resolved IP through to the connect call.
**Depends on:** Phase 1 (`feature_spec.md`) merged — the `is_blocked_address` classifier + `assert_base_url_allowed` orchestrator are reused here.

## Problem

Phase 1 resolves the `base_url` host and rejects blocked-range addresses **at registration / test-connection time**. But validation-time and connect-time are different moments: an attacker-controlled DNS name can resolve to a benign public IP when `assert_base_url_allowed` runs, then re-resolve to an internal IP (`127.0.0.1`, `169.254.169.254`, `10.x`) when the engine adapter's httpx client actually connects — on the registration probe or any later health probe. Phase 1's `docs/04_security/` note documents this residual risk as an operator-network responsibility; Phase 2 closes it in-process.

## Proposed capabilities

### Pin the validated IP through to the adapter connect call

- Thread the resolved-and-validated IP address from `assert_base_url_allowed` into `_build_adapter_from_args` so the `ElasticAdapter` / `SolrAdapter` httpx client connects to that pinned IP rather than re-resolving the hostname.
- Preserve the original hostname for the `Host` header and TLS SNI / certificate verification (connect-to-IP, verify-as-hostname) so HTTPS clusters still validate correctly.
- Re-validate at connect time as defense-in-depth (a custom httpx transport / resolver hook that runs `is_blocked_address` on the address actually being dialed), so even a re-resolution is caught.

## Scope signals

- **Backend:** `backend/app/services/cluster.py` (`_build_adapter_from_args` signature gains a pinned-IP arg); `backend/app/adapters/elastic.py` + `backend/app/adapters/solr.py` (httpx client construction — custom transport or `host`-pinning with SNI preservation). Reuses the Phase 1 classifier.
- **Frontend:** none.
- **Migration:** none.
- **Config:** reuses `RELYLOOP_ALLOW_PRIVATE_CLUSTERS`.
- **Audit events:** N/A (MVP3).

## Why deferred

Connect-time pinning touches the engine adapters' HTTP client construction (Host-header + TLS SNI handling across two adapters) — a materially larger, engine-touching change than the registration-time gate, and riskier (a bug breaks all cluster connectivity, not just a rejection path). The DNS-rebinding window is also a narrower, more sophisticated threat than the standing unconditional bypass Phase 1 closes. Per `feature_spec.md` D-4, Phase 1 ships the high-value self-contained fix first.

## Relationship to other work

Phase 2 of the parent spec. Reuses the Phase 1 `domain/cluster/url_policy.py` classifier. Independent of the other security-review sweep idea files.
