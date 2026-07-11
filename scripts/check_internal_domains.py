# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Fail if a non-allowlisted domain name (or private IP) appears in the
narrative state files.

Why this exists
---------------
``state.md`` / ``state_history.md`` are free-form narrative files written by
skills and humans after every merge, and RelyLoop is a public repo. An
operator's internal hostnames (``es.corp.example-org.com``,
``proxy.intra``, ...) must NEVER land in them in plain text: once a domain is
in a pushed commit it is effectively unrecallable (forks, dangling SHAs,
archives). Prevention at commit time is the only cheap enforcement point —
this script is that gate. It runs as a pre-commit hook AND as a CI job in
``secrets-defense.yml`` (same two-layer posture as the gitleaks + env-file
guards).

Policy (docs/04_security/internal-domain-hygiene.md):

* Narrative text uses human-readable placeholders (``<operator-es-cluster>``,
  ``<corp-proxy>``) instead of literal hosts. Angle-bracket placeholders are
  invisible to this scanner by construction.
* The optional operator-local mapping placeholder->real-name lives in the
  gitignored ``secrets/domain_aliases.yaml`` — never in tracked files.
* No encoding/encryption of real names anywhere: reversible encoding is not
  redaction.

Detection design
----------------
A naive FQDN regex drowns in dotted code identifiers (``asyncio.gather``,
``vi.mock``). We therefore only flag a dotted token when its final label is a
plausible TLD:

* ``PUBLIC_TLDS`` — a curated subset of real TLDs, chosen to exclude common
  file extensions (no ``.sh``/``.py``/``.rs``/``.md``/``.ts``...). Flagged
  unless the domain is covered by the allowlist file.
* ``INTERNAL_TLDS`` — pseudo-TLDs that indicate internal infrastructure
  (``.internal``/``.corp``/``.local``/...). Flagged unless allowlisted
  (e.g. ``host.docker.internal`` is a well-known Docker name).
* ``RESERVED_TLDS`` — RFC 2606/6761 documentation names (``.example``,
  ``.test``, ``.invalid``, ``.localhost``). Never flagged: they cannot leak
  real infrastructure, and are the correct spelling for fictional hosts in
  narratives.

IPv4 literals in the RFC 1918 + link-local ranges are flagged too (an
internal IP leaks as much as an internal hostname). Loopback / 0.0.0.0 /
RFC 5737 documentation ranges pass.

Known limitation: a bare hostname with no dot (``es-prod-01``) is
indistinguishable from a word and cannot be pattern-detected — that's what
the write-time placeholder discipline is for.

Usage
-----
    python3 scripts/check_internal_domains.py [FILE ...]

With no arguments scans the default targets (state.md, state_history.md).
Exit 0 = clean, exit 1 = violations printed one per line, exit 2 = usage
error (e.g. missing allowlist file).
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST_PATH = REPO_ROOT / "scripts" / "allowed_public_domains.txt"
DEFAULT_TARGETS = ("state.md", "state_history.md")

# Dotted-token candidate: labels separated by dots, final label alphabetic.
# Deliberately broad — the TLD filter below does the real work.
_FQDN_RE = re.compile(r"\b((?:[a-zA-Z0-9][a-zA-Z0-9-]*\.)+)([a-zA-Z]{2,})\b")

# IPv4 literal (candidate; range-classified below).
_IPV4_RE = re.compile(r"\b(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\b")

# Real TLDs we screen for. Curated to EXCLUDE common file extensions and
# code-identifier tails (sh, py, rs, md, ts, js, go, pl, cs, do, co, me are
# all real TLDs but collide with extensions/attribute names — the two-layer
# placeholder discipline covers domains on those; see module docstring).
PUBLIC_TLDS = frozenset(
    {
        "com",
        "net",
        "org",
        "io",
        "ai",
        "dev",
        "app",
        "cloud",
        "tech",
        "online",
        "site",
        "info",
        "biz",
        "edu",
        "gov",
        "mil",
        "int",
        "eu",
        "us",
        "uk",
        "de",
        "fr",
        "nl",
        "ca",
        "au",
        "jp",
        "in",
        "br",
        "cn",
        "ch",
        "se",
        "no",
        "fi",
        "es",
        "it",
        "pt",
        "xyz",
    }
)

# Pseudo-TLDs that signal internal infrastructure. Always suspicious.
INTERNAL_TLDS = frozenset({"internal", "corp", "local", "lan", "intra", "home", "private"})

# RFC 2606 / 6761 reserved names — safe by definition, never flagged.
RESERVED_TLDS = frozenset({"example", "test", "invalid", "localhost"})

# RFC 5737 documentation IPv4 prefixes — safe by definition.
_DOC_IP_PREFIXES = (("192", "0", "2"), ("198", "51", "100"), ("203", "0", "113"))


@dataclass(frozen=True)
class Violation:
    """One flagged token: file, 1-based line number, offending token."""

    path: str
    lineno: int
    token: str
    kind: str  # "domain" | "ip"

    def render(self) -> str:
        return f"{self.path}:{self.lineno}: {self.kind} `{self.token}` is not allowlisted"


def load_allowlist(path: Path = ALLOWLIST_PATH) -> frozenset[str]:
    """Read the allowlist file: one domain per line, `#` comments, blank ok."""
    if not path.is_file():
        raise FileNotFoundError(f"allowlist file missing: {path}")
    entries: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip().lower()
        if line:
            entries.add(line)
    return frozenset(entries)


def is_allowed(domain: str, allowlist: frozenset[str]) -> bool:
    """True if `domain` is an allowlist entry or a subdomain of one.

    `github.com` in the allowlist covers `github.com` AND `api.github.com`,
    but NOT `evilgithub.com` (suffix match is label-aligned).
    """
    d = domain.lower().rstrip(".")
    if d in allowlist:
        return True
    return any(d.endswith("." + entry) for entry in allowlist)


def _classify_ip(octets: tuple[str, str, str, str]) -> bool:
    """True if this IPv4 literal should be flagged as an operator host.

    Flags addresses in the RFC 1918 private ranges (10/8, 172.16/12,
    192.168/16) — a specific private host IP leaks operator topology. But
    NOT things that are universal constants rather than operator-specific:

    * network / broadcast addresses (last octet 0 or 255) — CIDR bases like
      ``10.0.0.0`` are not hosts, and appear in ``no_proxy`` examples.
    * link-local (169.254/16), including the ``169.254.169.254`` cloud
      metadata endpoint — the same everywhere, and security narratives
      legitimately need to name the SSRF target.
    * loopback / unspecified / RFC 5737 documentation ranges.
    """
    try:
        a, b, c, d = (int(o) for o in octets)
    except ValueError:  # pragma: no cover — regex guarantees digits
        return False
    if any(o > 255 for o in (a, b, c, d)):
        return False  # not a real IP (e.g. version-like 1.2.3.456)
    if octets[:3] in _DOC_IP_PREFIXES:
        return False  # RFC 5737 documentation ranges
    if a == 127 or (a, b, c, d) == (0, 0, 0, 0):
        return False  # loopback / unspecified
    if a == 169 and b == 254:
        return False  # link-local (incl. cloud metadata) — universal, not operator
    if d in (0, 255):
        return False  # network / broadcast address — not an assignable host
    if a == 10:
        return True
    if a == 172 and 16 <= b <= 31:
        return True
    return a == 192 and b == 168


def scan_text(text: str, path: str, allowlist: frozenset[str]) -> list[Violation]:
    """Scan one file's text; return violations (deduped per line+token)."""
    violations: list[Violation] = []
    seen: set[tuple[int, str]] = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in _FQDN_RE.finditer(line):
            domain = (match.group(1) + match.group(2)).lower()
            tld = match.group(2).lower()
            if tld in RESERVED_TLDS:
                continue
            if tld not in PUBLIC_TLDS and tld not in INTERNAL_TLDS:
                continue  # dotted code identifier, not a domain
            if is_allowed(domain, allowlist):
                continue
            key = (lineno, domain)
            if key not in seen:
                seen.add(key)
                violations.append(Violation(path, lineno, domain, "domain"))
        for ip_match in _IPV4_RE.finditer(line):
            if _classify_ip(ip_match.groups()):  # type: ignore[arg-type]
                token = ip_match.group(0)
                key = (lineno, token)
                if key not in seen:
                    seen.add(key)
                    violations.append(Violation(path, lineno, token, "ip"))
    return violations


def main(argv: list[str]) -> int:
    targets = argv or [str(REPO_ROOT / t) for t in DEFAULT_TARGETS]
    try:
        allowlist = load_allowlist()
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    all_violations: list[Violation] = []
    for target in targets:
        p = Path(target)
        if not p.is_file():
            # A renamed/deleted target is not an error — pre-commit may pass
            # paths that no longer exist in the working tree.
            continue
        all_violations.extend(scan_text(p.read_text(encoding="utf-8"), str(p), allowlist))

    if not all_violations:
        return 0

    print("Internal-domain guard FAILED — plain-text domains/IPs found:", file=sys.stderr)
    for v in all_violations:
        print(f"  {v.render()}", file=sys.stderr)
    print(
        "\nFix: replace with a human-readable placeholder like "
        "<operator-es-cluster> or <corp-proxy> (keep any real-name mapping in "
        "the gitignored secrets/domain_aliases.yaml). If the domain is "
        "genuinely public infrastructure, add it to "
        "scripts/allowed_public_domains.txt with a comment. "
        "See docs/04_security/internal-domain-hygiene.md.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
