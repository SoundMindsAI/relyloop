# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Lock the internal-domain guard (scripts/check_internal_domains.py).

This gate is the enforcement layer for the "no plain-text operator domain
ever lands in state.md/state_history.md" invariant, so its true/false
positives matter: a false negative leaks operator infrastructure into a
public repo; a false positive trains people to disable the hook. These tests
pin both edges.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(_REPO_ROOT))

from scripts.check_internal_domains import (  # noqa: E402
    _classify_ip,
    is_allowed,
    load_allowlist,
    scan_text,
)

ALLOW = frozenset({"github.com", "relyloop.com", "acme.com", "host.docker.internal"})


def _tokens(text: str) -> set[str]:
    return {v.token for v in scan_text(text, "x.md", ALLOW)}


# --- domains: must FLAG (real leak shapes) ---------------------------------


def test_flags_internal_fqdn() -> None:
    assert "es-prod.corp-name.internal" in _tokens("box es-prod.corp-name.internal down")


def test_flags_public_customer_domain() -> None:
    assert "search.customer-co.com" in _tokens("deployed to search.customer-co.com")


def test_flags_subdomain_even_when_apex_looks_generic() -> None:
    assert "vpn.acme-corp.io" in _tokens("connect vpn.acme-corp.io")


def test_flags_corp_pseudo_tld() -> None:
    assert "proxy.intra" in _tokens("set proxy.intra as upstream")


# --- domains: must NOT flag (allowlist, subdomains, reserved, code) ---------


def test_allowlisted_domain_passes() -> None:
    assert _tokens("see github.com/foo and relyloop.com") == set()


def test_subdomain_of_allowlisted_passes() -> None:
    assert _tokens("api.github.com and registry.relyloop.com") == set()


def test_allowlist_suffix_is_label_aligned_not_substring() -> None:
    # `acme.com` allowlisted must NOT let `evil-acme.com` through, but the
    # apex `acme.com` and true subdomains must pass.
    assert is_allowed("acme.com", ALLOW)
    assert is_allowed("shop.acme.com", ALLOW)
    assert not is_allowed("evilacme.com", ALLOW)


def test_reserved_example_tlds_never_flagged() -> None:
    text = "hosts foo.example, bar.test, baz.invalid, qux.localhost"
    assert _tokens(text) == set()


def test_dotted_code_identifiers_not_flagged() -> None:
    # The most important false-positive class: dotted identifiers whose tail
    # is not a real TLD.
    text = "asyncio.gather, vi.mock, router.replace, study.metric, e.preventDefault"
    assert _tokens(text) == set()


def test_angle_bracket_placeholder_is_invisible() -> None:
    assert _tokens("proxy at <corp-proxy> and <operator>.internal via <internal-domain>") == set()


# --- IPv4 classification ----------------------------------------------------


def test_flags_private_host_ips() -> None:
    assert _classify_ip(("10", "42", "7", "19"))
    assert _classify_ip(("172", "20", "5", "8"))
    assert _classify_ip(("192", "168", "1", "50"))


def test_does_not_flag_universal_or_reserved_ips() -> None:
    assert not _classify_ip(("10", "0", "0", "0"))  # network address
    assert not _classify_ip(("192", "168", "1", "255"))  # broadcast
    assert not _classify_ip(("169", "254", "169", "254"))  # cloud metadata / link-local
    assert not _classify_ip(("127", "0", "0", "1"))  # loopback
    assert not _classify_ip(("192", "0", "2", "1"))  # RFC 5737 doc range
    assert not _classify_ip(("8", "8", "8", "8"))  # public resolver, not private
    assert not _classify_ip(("1", "2", "3", "999"))  # not a real IP


def test_scan_reports_line_numbers() -> None:
    text = "line one clean\nleak proxy.intra here\n"
    violations = scan_text(text, "f.md", ALLOW)
    assert len(violations) == 1
    assert violations[0].lineno == 2


# --- allowlist file loads + covers the committed state files ----------------


def test_committed_allowlist_loads() -> None:
    allow = load_allowlist()
    assert "github.com" in allow
    assert "relyloop.com" in allow


def test_committed_state_files_pass_the_gate() -> None:
    """Regression: state.md + state_history.md must stay clean going forward."""
    allow = load_allowlist()
    for name in ("state.md", "state_history.md"):
        p = _REPO_ROOT / name
        if p.is_file():
            assert scan_text(p.read_text(encoding="utf-8"), name, allow) == []
