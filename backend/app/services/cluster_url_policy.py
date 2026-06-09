# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Async SSRF policy for cluster ``base_url`` (bug_cluster_url_ssrf_hostname_bypass FR-1/2).

This is the service-layer orchestrator that resolves a hostname (DNS is I/O,
so it cannot live in the pure domain module) and applies the pure classifiers
from :mod:`backend.app.domain.cluster.url_policy`.

Gate: the policy is a strict no-op unless ``RELYLOOP_ALLOW_PRIVATE_CLUSTERS``
is ``False`` (the hardened posture). With the shipped default (``True``,
laptop convenience) nothing is blocked and local Docker hostnames keep working.

``ClusterUrlBlocked`` is defined here (rather than in ``cluster.py``) to avoid a
circular import — ``cluster.py`` imports :func:`assert_base_url_allowed` from
this module and re-exports the exception. The cluster routers map it to
``400 CLUSTER_URL_BLOCKED``.
"""

from __future__ import annotations

import asyncio
import socket
from ipaddress import ip_address
from urllib.parse import urlparse

from backend.app.core.settings import get_settings
from backend.app.domain.cluster.url_policy import (
    is_blocked_address,
    is_metadata_hostname,
)

#: Wall-clock cap on DNS resolution so a slow/blackholed resolver can't hang the
#: registration / test-connection request (Gemini review #1).
_DNS_TIMEOUT_S = 5.0


class ClusterUrlBlocked(Exception):
    """``base_url`` host is internal / cloud-metadata and private clusters are disallowed.

    Maps to ``400 CLUSTER_URL_BLOCKED`` at the cluster routers (non-retryable —
    the operator must change the URL, or deliberately set
    ``RELYLOOP_ALLOW_PRIVATE_CLUSTERS=True``).
    """


async def assert_base_url_allowed(base_url: str) -> None:
    """Reject a ``base_url`` that targets an internal / metadata endpoint.

    No-op when ``RELYLOOP_ALLOW_PRIVATE_CLUSTERS`` is ``True``. Otherwise:

    * raise if the host is a known cloud-metadata name;
    * if the host is a literal IP, classify it directly (no DNS);
    * else resolve the host and raise if **any** resolved address is in a
      blocked range.

    A DNS resolution failure is treated as "not an SSRF hit" (the host can't be
    reached anyway) — the caller's normal probe surfaces it as unreachable.
    Structural validation (scheme present, host present) is the Pydantic
    request validator's job; this function assumes a well-formed URL and
    returns quietly if it can't extract a host.
    """
    if get_settings().relyloop_allow_private_clusters:
        return

    host = urlparse(base_url).hostname
    if not host:
        return

    if is_metadata_hostname(host):
        raise ClusterUrlBlocked(
            f"base_url host {host!r} is a cloud-metadata endpoint and "
            "RELYLOOP_ALLOW_PRIVATE_CLUSTERS is false"
        )

    # Literal IP — classify directly, no DNS resolution needed.
    try:
        literal = ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if is_blocked_address(literal):
            raise ClusterUrlBlocked(
                f"base_url host {host!r} is a blocked-range address and "
                "RELYLOOP_ALLOW_PRIVATE_CLUSTERS is false"
            )
        return

    # Hostname — resolve and classify every returned address (fail-safe: any
    # blocked address fails the URL).
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(
            loop.getaddrinfo(host, None, type=socket.SOCK_STREAM),
            timeout=_DNS_TIMEOUT_S,
        )
    except (socket.gaierror, TimeoutError):
        return  # unresolvable or timeout -> not an SSRF target; probe reports unreachable

    for info in infos:
        addr_str = str(info[4][0])
        try:
            addr = ip_address(addr_str)
        except ValueError:
            continue
        if is_blocked_address(addr):
            raise ClusterUrlBlocked(
                f"base_url host {host!r} resolves to a blocked-range address "
                f"({addr_str}) and RELYLOOP_ALLOW_PRIVATE_CLUSTERS is false"
            )
