# bug_cluster_url_ssrf_hostname_bypass — cluster base_url SSRF guard only inspects literal IPs

**Date:** 2026-06-09
**Status:** Idea — surfaced during a codebase-wide security review (branch `claude/codebase-security-review-6njwio`)
**Priority:** P2
**Origin:** Security review of `backend/app/adapters/` + cluster registration; finding in `backend/app/api/v1/schemas.py`
**Depends on:** None

## Problem

The cluster registration `base_url` validator is intended to stop SSRF into internal/cloud-metadata endpoints (it cites "spec §10 Threat 3"), but the guard only fires when the host parses as a **literal IP address**. Any DNS **hostname** is returned unchecked, so the protection is trivially bypassable and gives a false sense of safety.

`backend/app/api/v1/schemas.py:128-143` (`CreateClusterRequest.validate_base_url`) and the duplicated logic at `schemas.py:162-180` (`ConnectionTestRequest.validate_base_url`):

```python
try:
    ip = ip_address(parsed.hostname)
except ValueError:
    return v  # hostname; skip private-IP check   <-- line 137 / 174
if (ip.is_private or ip.is_loopback) and not get_settings().relyloop_allow_private_clusters:
    raise ValueError(...)
```

Consequences:
1. **Hostname bypass (primary).** `http://metadata.google.internal/computeMetadata/v1/...` (GCP's metadata endpoint, reachable by name), `http://localhost.localdomain`, or any internal service DNS name (`http://vault.internal:8200`) passes validation unconditionally. The adapter then issues HTTP requests to it during the registration probe / `test-connection` and on every health probe, and the response body is cached in Redis and surfaced via cluster detail + `/healthz`. That is a read-SSRF exfiltration path.
2. **DNS rebinding.** Even if a literal-IP check passed, validation-time and connect-time are different moments; an attacker-controlled name can resolve to a benign IP at validation and an internal IP at probe time. The docstring explicitly says "DNS resolution is intentionally NOT performed at validation time," so this is a known-but-undefended gap.
3. **Carrier-grade NAT range** `100.64.0.0/10` reports `is_private=False`, so it is not blocked even as a literal IP (minor).

Note on what is **already** covered (so the fix is scoped accurately): on Python 3.11.4+/3.12.4+/3.13, `ipaddress.ip_address("169.254.169.254").is_private` is `True`, so the **AWS link-local metadata IP is already blocked** when `RELYLOOP_ALLOW_PRIVATE_CLUSTERS` is false (the MVP1 default). IPv6 link-local (`fe80::/10`) and `0.0.0.0` are likewise `is_private=True`. The gap is the hostname path, not the literal-IP path.

Severity in the MVP1 posture is **Medium**: single-tenant, no auth, local-only — anyone who can reach the API can already register a cluster pointing anywhere, so this is not a privilege-escalation across a trust boundary today. It becomes **High** the moment RelyLoop is deployed on a cloud host (IAM-role metadata reachable) or behind any auth boundary, which is exactly where the validator is supposed to earn its keep.

## Proposed capabilities

### Close the hostname SSRF path

- Resolve the hostname at validation time (and ideally re-check at connect time) and apply the same `is_private / is_loopback / is_link_local / is_reserved / is_multicast / is_unspecified` rejection to **every** resolved address, not just literal-IP hosts. Reject if any resolved A/AAAA record lands in a blocked range while `RELYLOOP_ALLOW_PRIVATE_CLUSTERS` is false.
- Add an explicit denylist for well-known metadata hostnames (`metadata.google.internal`, `metadata`, etc.) as defense-in-depth regardless of DNS resolution.
- Consolidate the duplicated validator (it is copy-pasted across `CreateClusterRequest` and `ConnectionTestRequest`) into one shared helper so the two paths cannot drift.
- For the DNS-rebinding window: pin the resolved IP and re-validate it at the adapter connect call (or document the residual risk explicitly in `docs/04_security/` as an operator-network responsibility if resolve-and-pin is deferred).
- Add `is_link_local`/`is_reserved`/`is_multicast`/`is_unspecified`/`100.64.0.0/10` to the literal-IP rejection set for completeness.

## Scope signals

- **Backend:** `backend/app/api/v1/schemas.py` (two validators → one helper); possibly a connect-time re-check in `backend/app/adapters/elastic.py` + `solr.py`. New unit tests for hostname-resolving-to-private, metadata hostname, IPv6 link-local, CGNAT.
- **Frontend:** none.
- **Migration:** none.
- **Config:** reuses `RELYLOOP_ALLOW_PRIVATE_CLUSTERS`; possibly add a metadata-hostname denylist constant.
- **Audit events:** N/A.

## Why filed as an idea rather than fixed inline

Surfaced during a read-only security review, not while touching the cluster registration path. The fix has a real design fork (resolve-at-validation vs resolve-and-pin-at-connect vs denylist-only) with a latency/DNS-I/O tradeoff the spec called out as deliberately deferred — that is a design decision, not a one-line correction, so it warrants a spec rather than an unilateral inline edit. The link-local-IP half of the original review claim was already covered by modern `ipaddress` semantics; this idea narrows the finding to the genuine hostname gap.

## Relationship to other work

Touches the same validator the cluster-registration / `test-connection` features own. Independent of the other security-review idea files filed in the same review sweep (request-ID validation, agent-confirmation matching, CORS-credentials hardening, test-router conditional mount).
