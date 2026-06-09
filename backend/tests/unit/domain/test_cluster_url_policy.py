# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the pure cluster-URL SSRF classifier (FR-1 / FR-5).

Covers ``bug_cluster_url_ssrf_hostname_bypass`` AC-1 (metadata hostname) and
AC-6 (expanded range coverage incl. IPv4-mapped IPv6).
"""

from __future__ import annotations

from ipaddress import ip_address

import pytest

from backend.app.domain.cluster.url_policy import (
    is_blocked_address,
    is_metadata_hostname,
)

# AC-6: every one of these must classify as blocked.
BLOCKED = [
    "127.0.0.1",  # loopback
    "10.0.0.1",  # RFC1918 private
    "192.168.1.1",  # RFC1918 private
    "172.16.0.1",  # RFC1918 private
    "169.254.169.254",  # link-local (AWS/Azure metadata IP)
    "100.64.0.1",  # carrier-grade NAT (RFC 6598)
    "0.0.0.0",  # unspecified
    "224.0.0.1",  # multicast
    "fe80::1",  # IPv6 link-local
    "::1",  # IPv6 loopback
    "fd00::1",  # IPv6 ULA (private)
    "::",  # IPv6 unspecified
    "::ffff:10.0.0.1",  # IPv4-mapped private -> unwrapped, blocked
    "::ffff:127.0.0.1",  # IPv4-mapped loopback -> unwrapped, blocked
]

# Public addresses that must NOT be blocked.
ALLOWED = [
    "93.184.216.34",  # example.com
    "8.8.8.8",  # public DNS
    "1.1.1.1",  # public DNS
    "2606:4700:4700::1111",  # public IPv6
    "::ffff:93.184.216.34",  # IPv4-mapped public -> unwrapped, allowed
]


@pytest.mark.parametrize("addr", BLOCKED)
def test_blocked_addresses(addr: str) -> None:
    assert is_blocked_address(ip_address(addr)) is True


@pytest.mark.parametrize("addr", ALLOWED)
def test_allowed_addresses(addr: str) -> None:
    assert is_blocked_address(ip_address(addr)) is False


@pytest.mark.parametrize(
    "host",
    [
        "metadata.google.internal",
        "METADATA.GOOGLE.INTERNAL",
        "metadata.google.internal.",  # trailing dot (FQDN)
        "metadata",
        "  metadata  ",  # surrounding whitespace
    ],
)
def test_metadata_hostnames_blocked(host: str) -> None:
    assert is_metadata_hostname(host) is True


@pytest.mark.parametrize(
    "host",
    [
        "search.example.com",
        "elasticsearch",
        "metadata.example.com",  # not the GCP metadata name
        "notmetadata",
    ],
)
def test_non_metadata_hostnames_pass(host: str) -> None:
    assert is_metadata_hostname(host) is False
