# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Pure IP/hostname classification for the cluster ``base_url`` SSRF guard.

Part of ``bug_cluster_url_ssrf_hostname_bypass`` (FR-1 / FR-5). This module
is **pure** per CLAUDE.md's domain-layer convention — no I/O, no async, no DNS
resolution. It answers two yes/no questions:

* :func:`is_blocked_address` — is an IP in a range that a cluster ``base_url``
  must not point at when the hardened posture is active
  (``RELYLOOP_ALLOW_PRIVATE_CLUSTERS=False``)?
* :func:`is_metadata_hostname` — is a host one of the well-known cloud-metadata
  names that never resolves to a classifiable public IP from outside the VM?

The async orchestrator that resolves a hostname to addresses and applies these
predicates lives in :mod:`backend.app.services.cluster_url_policy` (DNS is I/O,
so it cannot live in the domain layer).

Blocked ranges (the union below) cover loopback, RFC 1918 private,
link-local (incl. the AWS/Azure metadata IP ``169.254.169.254``), reserved,
multicast, unspecified (``0.0.0.0`` / ``::``), and carrier-grade NAT
(``100.64.0.0/10`` — not classified ``is_private`` by the stdlib). IPv4-mapped
IPv6 addresses (``::ffff:a.b.c.d``) are unwrapped to their v4 form before
classification so a mapped private address cannot slip through.
"""

from __future__ import annotations

from ipaddress import IPv4Address, IPv6Address, ip_network

#: Cloud-metadata hostnames that are never a legitimate cluster target. The
#: bare metadata IPs (``169.254.169.254`` etc.) are already caught by
#: :func:`is_blocked_address` via ``is_link_local``; this denylist covers the
#: name-based GCP path (``metadata.google.internal``) that resolves only inside
#: the VM. Compared case-insensitively, trailing dot stripped.
METADATA_HOSTNAMES: frozenset[str] = frozenset(
    {
        "metadata.google.internal",
        "metadata",
    }
)

#: Carrier-grade NAT (RFC 6598). Not reported by ``IPv4Address.is_private`` on
#: the stdlib, so checked explicitly.
_CGNAT_V4 = ip_network("100.64.0.0/10")


def _is_blocked_v4(addr: IPv4Address) -> bool:
    """Pure range classification for an IPv4 address."""
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
        or addr in _CGNAT_V4
    )


def is_blocked_address(ip: IPv4Address | IPv6Address) -> bool:
    """Return ``True`` if ``ip`` is in a range a cluster URL must not target.

    IPv4-mapped IPv6 addresses (``::ffff:a.b.c.d``) are unwrapped and
    classified as their embedded v4 address.
    """
    if isinstance(ip, IPv6Address):
        mapped = ip.ipv4_mapped
        if mapped is not None:
            return _is_blocked_v4(mapped)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        )
    return _is_blocked_v4(ip)


def is_metadata_hostname(host: str) -> bool:
    """Return ``True`` if ``host`` is a known cloud-metadata hostname.

    Case-insensitive; a single trailing dot (FQDN form) is ignored.
    """
    return host.strip().rstrip(".").lower() in METADATA_HOSTNAMES
