# Cluster `base_url` SSRF guard

**Origin:** `bug_cluster_url_ssrf_hostname_bypass` (codebase security review, 2026-06-09).

RelyLoop probes every registered cluster's `base_url` — on registration, on the
`test-connection` diagnostic, and on every periodic health probe. Because the URL
is operator-supplied, an unrestricted `base_url` is a server-side request forgery
(SSRF) surface: a URL pointed at an internal service or a cloud-metadata endpoint
would make RelyLoop fetch it and surface the response (cached health, cluster
detail). This note documents the control that closes that path.

## The control

When **`RELYLOOP_ALLOW_PRIVATE_CLUSTERS=False`** (the hardened posture), the
cluster service rejects a `base_url` before any network call when its host:

1. **is a cloud-metadata hostname** — `metadata.google.internal` / `metadata`
   (the GCP metadata name, which resolves only inside the VM); or
2. **is a literal IP in a blocked range**; or
3. **resolves (DNS A/AAAA) to any address in a blocked range**.

Rejection is a deterministic **`400 CLUSTER_URL_BLOCKED`** (non-retryable) on both
`POST /api/v1/clusters` and `POST /api/v1/clusters/test-connection`. The check runs
*before* the adapter is built or any probe is issued, so a blocked URL is never
contacted.

### Blocked ranges

`is_private`, `is_loopback`, `is_link_local` (covers the AWS/Azure metadata IP
`169.254.169.254`), `is_reserved`, `is_multicast`, `is_unspecified`
(`0.0.0.0` / `::`), plus carrier-grade NAT `100.64.0.0/10` (RFC 6598, not flagged
`is_private` by the stdlib). IPv4-mapped IPv6 addresses (`::ffff:a.b.c.d`) are
unwrapped to their v4 form before classification, so a mapped private address
cannot slip through. If a host resolves to multiple addresses, **any** blocked
address fails the URL (fail-safe).

### The flag gate

`RELYLOOP_ALLOW_PRIVATE_CLUSTERS` **defaults to `True`** (laptop / local-dev
convenience) — in that posture the policy is a strict **no-op**, so internal
Docker hostnames like `http://elasticsearch:9200` register normally. The policy
only activates when an operator sets the flag `False` for a hardened deployment.
Flip it to `False` on any deployment reachable from an untrusted network or
running on a cloud host with an instance-metadata service.

## Where it lives

- Pure IP/hostname classification: `backend/app/domain/cluster/url_policy.py`
  (`is_blocked_address`, `is_metadata_hostname`, `METADATA_HOSTNAMES`).
- Async resolve-and-check orchestrator: `backend/app/services/cluster_url_policy.py`
  (`assert_base_url_allowed`, `ClusterUrlBlocked`). DNS resolution uses the async
  resolver (`asyncio.get_running_loop().getaddrinfo`) so it never blocks the event
  loop — this is why the policy lives in the service layer, not the synchronous
  Pydantic request validator (which retains only the structural scheme + host
  check).

## Residual risk — DNS rebinding (Phase 2)

The check resolves the host at registration time. A host that resolves to a
benign public IP then *re-resolves* to an internal IP when the adapter actually
connects (DNS rebinding) is **not** closed by this control. Closing it requires
pinning the validated IP through to the engine adapter's HTTP client (Host-header
+ TLS SNI preservation), tracked as Phase 2 in
`planned_features/.../bug_cluster_url_ssrf_hostname_bypass/phase2_idea.md`. Until
Phase 2 ships, treat trusted DNS + network segmentation as an operator-side
responsibility for hardened deployments.
