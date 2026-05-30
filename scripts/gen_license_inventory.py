# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Generate the dependency license inventory (docs/04_security/license-inventory.md).

RelyLoop is distributed under Apache-2.0, which is incompatible with strong
copyleft (GPL / AGPL) in a *shipped* dependency. This script inventories every
dependency in the locked closure, classifies each license against Apache-2.0,
and records the adjudication for any flagged license.

Determinism is the whole point: the inventory is derived from the LOCKED
dependency closure (``uv tree`` + ``pnpm``), never from whatever happens to be
installed in the ambient virtualenv. A developer's polluted ``.venv`` (stale
packages from a previous branch) therefore can't change the output — CI's clean
``uv sync --frozen`` env and a local run produce byte-identical files. Versions
are deliberately excluded from the table so routine dependency bumps don't churn
the committed file; only a *new* dependency, a *removed* one, or a *changed
license* moves it.

Usage::

    python scripts/gen_license_inventory.py           # rewrite the inventory
    python scripts/gen_license_inventory.py --check    # CI gate (see below)

``--check`` does two things and exits non-zero on either failure:

1. Regenerates the inventory into memory and diffs it against the committed
   ``docs/04_security/license-inventory.md``. Drift (new/removed dep, changed
   license) fails — fix by running the script without ``--check`` and committing.
2. Hard-fails if any *shipped* dependency (Python runtime closure or frontend
   prod deps) carries a forbidden copyleft license (GPL / AGPL) or an
   unclassifiable license with no adjudication. Dev-only copyleft is allowed
   (it never ships) but is still listed.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT = REPO_ROOT / "docs" / "04_security" / "license-inventory.md"
UI_DIR = REPO_ROOT / "ui"

# Licenses pip-licenses cannot read from package metadata ("UNKNOWN"). Each was
# verified by hand against the package's own LICENSE file / PyPI classifiers.
# A package that newly reports UNKNOWN and is NOT in this map is rendered as
# "UNKNOWN" and fails the --check gate if it ships, forcing classification.
PY_LICENSE_OVERRIDES = {
    "certifi": "MPL-2.0",
    "idna": "BSD-3-Clause",
    "typing-extensions": "PSF-2.0",
    "ply": "BSD-3-Clause",
}

# Per-package adjudications for any license that is not plainly permissive.
# Keyed by normalized package name. This is the single source of truth for the
# "Decided action" column — editing it here is what updates the inventory.
ADJUDICATIONS = {
    "reuse": (
        "**Accept.** Dev-only (the SPDX-header linter run by pre-commit + the "
        "`license-headers` CI job). GPL-3.0, but `reuse` is never imported, "
        "linked, or bundled into the distributed RelyLoop artifact — it is a "
        "build-time tool, so its copyleft does not reach distributed code."
    ),
    "certifi": (
        "**Accept.** MPL-2.0 is file-level (weak) copyleft and is explicitly "
        "compatible with Apache-2.0 for mere aggregation/distribution; we ship "
        "certifi unmodified, so no source-disclosure obligation attaches to "
        "RelyLoop's own Apache-2.0 code."
    ),
    "psycopg2-binary": (
        "**Accept.** LGPL-3.0 (with the OpenSSL exception). LGPL's copyleft is "
        "library-level: we use psycopg2 as an unmodified, dynamically-imported "
        "PostgreSQL driver and never modify its source, so no obligation "
        "attaches to RelyLoop's Apache-2.0 code. Shipping an unmodified LGPL "
        "library alongside permissive code is the canonical allowed case."
    ),
    "tqdm": (
        "**Accept.** Dual-licensed MPL-2.0 AND MIT — the MIT grant alone is "
        "fully Apache-2.0-compatible, so we take it under MIT. (tqdm is a "
        "transitive progress-bar dep; shipped unmodified regardless.)"
    ),
    "pathspec": (
        "**Accept.** Dev-only (pulled by the `reuse`/pre-commit toolchain). "
        "MPL-2.0 file-level copyleft; never shipped in the runtime artifact."
    ),
    "python-debian": (
        "**Accept.** Dev-only (transitive dep of the `reuse` SPDX linter). "
        "GPL-2.0+, but a build-time tool that is never imported, linked, or "
        "bundled into the distributed artifact — its copyleft does not reach "
        "shipped code."
    ),
    "@img/sharp-libvips-<platform>": (
        "**Accept.** LGPL-3.0 platform binary for `sharp` (image processing, "
        "transitively via Next.js). Shipped unmodified as a dynamically-loaded "
        "library; LGPL library-level copyleft imposes no obligation on "
        "RelyLoop's own Apache-2.0 code. Replaceable if ever needed."
    ),
    "@img/sharp-<platform>": (
        "**Accept.** Apache-2.0 platform binary for `sharp` (the LGPL part is "
        "the separate libvips binary, adjudicated above). Listed because the "
        "platform-suffix canonicalization groups it; fully permissive."
    ),
    "axe-core": (
        "**Accept.** Dev-only (accessibility testing, transitive via the test "
        "tooling). MPL-2.0 file-level copyleft; never shipped."
    ),
    "lightningcss": (
        "**Accept.** Dev-only (CSS build tooling). MPL-2.0 file-level "
        "copyleft; never shipped in the runtime artifact."
    ),
    "lightningcss-<platform>": (
        "**Accept.** Dev-only platform binary for the `lightningcss` CSS build "
        "tool (installed only on the build host). MPL-2.0 file-level copyleft; "
        "never shipped in the runtime artifact."
    ),
    "@tailwindcss/oxide-<platform>": (
        "**Accept.** Dev-only platform binary for the Tailwind `oxide` engine "
        "(installed only on the build host). MIT-licensed and never shipped in "
        "the runtime artifact."
    ),
}

# License classification. Order matters: copyleft checks run before permissive.
FORBIDDEN_PATTERNS = [  # strong copyleft — must NOT appear in a shipped dep
    r"\bAGPL",
    r"AFFERO",
    r"\bGPL",  # GPLv2/v3; LGPL is excluded below before this runs
    r"GENERAL PUBLIC LICENSE",
]
WEAK_COPYLEFT_PATTERNS = [  # allowed but flagged for review
    r"\bLGPL",
    r"LESSER GENERAL PUBLIC",
    r"\bMPL",
    r"MOZILLA PUBLIC",
    r"\bEPL",
    r"ECLIPSE PUBLIC",
    r"\bCDDL",
]
PERMISSIVE_PATTERNS = [
    r"\bMIT\b",
    r"\bMIT\*",
    r"\bBSD\b",
    r"BSD-[0-9]",
    r"\b0BSD\b",  # BSD Zero Clause (tslib)
    r"\bISC\b",
    r"APACHE",
    r"\bPSF\b",
    r"PYTHON SOFTWARE FOUNDATION",
    r"PYTHON-2",
    r"\bCC0",
    r"CC-BY-[0-9]",  # Creative Commons Attribution (caniuse-lite data set)
    r"UNLICENSE",
    r"\bZLIB\b",
    r"HPND",
    r"BLUE ?OAK",  # "Blue Oak" or "BlueOak-1.0.0"
    r"BLUEOAK",
]


def _norm(name: str) -> str:
    return name.strip().lower().replace("_", "-")


# pnpm reports only the OPTIONAL platform binaries for the *current* host
# (e.g. @img/sharp-libvips-darwin-arm64 on macOS, @next/swc-linux-x64-gnu on
# CI's Linux runner). Left raw, the inventory would differ per platform and the
# --check gate would fail on every CI run. Collapse each platform variant to a
# single canonical "<pkg>-<platform>" entry so the output is host-independent.
#
# The suffix is "<os>[-<arch>][-<libc/abi>]" with wide real-world variation
# (-linux-x64-gnu, -linux-x64-musl, -win32-ia32-msvc, -linux-arm-gnueabihf,
# -wasm32-wasi, …). Match the first OS token and EVERYTHING after it so the
# libc/abi tail (gnu, musl, msvc, gnueabihf) collapses too — anchoring on the
# trailing arch alone left Linux -gnu/-musl variants diverging from the
# macOS-generated committed file. Verified against ui/pnpm-lock.yaml: all
# native-package families collapse to a single canonical name each.
_PLATFORM_SUFFIX = re.compile(
    r"-(darwin|linux|linuxmusl|win32|freebsd|openbsd|netbsd|android|sunos|wasm32)"
    r"(-.*)?$"
)


def _canonical_npm(name: str) -> str:
    return _PLATFORM_SUFFIX.sub("-<platform>", name)


def _run(cmd: list[str], cwd: Path | None = None) -> str:
    # noqa: S603 — cmd is always a hardcoded literal arg list (uv / pnpm /
    # pip-licenses), never user input. No shell=True; this is a dev/CI tool.
    return subprocess.run(  # noqa: S603
        cmd, cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


def _tree_names(extra_args: list[str]) -> set[str]:
    """Package names in a ``uv tree`` closure (deduped, normalized)."""
    out = _run(["uv", "tree", "--frozen", *extra_args], cwd=REPO_ROOT)
    names: set[str] = set()
    for line in out.splitlines():
        m = re.search(r"([a-zA-Z0-9_.-]+)\s+v[0-9]", line)
        if m:
            names.add(_norm(m.group(1)))
    return names


def classify(license_str: str) -> str:
    """Return one of: forbidden | weak-copyleft | permissive | unknown."""
    up = license_str.upper()
    # Exclude LGPL from the GPL forbidden check first.
    is_lgpl = bool(re.search(r"\bLGPL", up) or "LESSER GENERAL PUBLIC" in up)
    if not is_lgpl and any(re.search(p, up) for p in FORBIDDEN_PATTERNS):
        return "forbidden"
    if any(re.search(p, up) for p in WEAK_COPYLEFT_PATTERNS):
        return "weak-copyleft"
    if any(re.search(p, up) for p in PERMISSIVE_PATTERNS):
        return "permissive"
    return "unknown"


def _compat_label(bucket: str) -> str:
    return {
        "permissive": "Yes",
        "weak-copyleft": "Yes — weak copyleft (file-level), flagged",
        "forbidden": "**NO — strong copyleft**",
        "unknown": "**Unclassified — needs review**",
    }[bucket]


def collect_python() -> list[dict]:
    runtime = _tree_names(["--no-dev"])
    full = _tree_names([])
    raw = json.loads(_run(["uv", "run", "pip-licenses", "--format=json"], cwd=REPO_ROOT))
    rows: list[dict] = []
    for entry in raw:
        norm = _norm(entry["Name"])
        if norm not in full:
            continue  # ambient-venv pollution; not in the locked closure
        lic = entry.get("License", "UNKNOWN")
        if lic in ("UNKNOWN", "", None):
            lic = PY_LICENSE_OVERRIDES.get(norm, "UNKNOWN")
        rows.append(
            {
                "ecosystem": "Python",
                "name": entry["Name"],
                "norm": norm,
                "license": lic,
                "scope": "runtime" if norm in runtime else "dev",
            }
        )
    return rows


def collect_frontend() -> list[dict]:
    prod = json.loads(_run(["pnpm", "licenses", "list", "--prod", "--json"], cwd=UI_DIR))
    dev = json.loads(_run(["pnpm", "licenses", "list", "--dev", "--json"], cwd=UI_DIR))
    prod_names = {_norm(_canonical_npm(item["name"])) for items in prod.values() for item in items}
    seen: dict[str, dict] = {}
    for source, scope in ((prod, "runtime"), (dev, "dev")):
        for lic, items in source.items():
            for item in items:
                canon = _canonical_npm(item["name"])
                norm = _norm(canon)
                # prod wins: a package used in both ships, so it's runtime.
                eff_scope = "runtime" if norm in prod_names else scope
                # Keep the first (or upgrade dev->runtime if seen later).
                if norm in seen and seen[norm]["scope"] == "runtime":
                    continue
                seen[norm] = {
                    "ecosystem": "npm",
                    "name": canon,
                    "norm": norm,
                    "license": lic,
                    "scope": eff_scope,
                }
    return list(seen.values())


def render(rows: list[dict]) -> str:
    rows = sorted(rows, key=lambda r: (r["ecosystem"], r["norm"]))
    flagged = [r for r in rows if classify(r["license"]) != "permissive"]

    lines: list[str] = []
    lines.append("# Dependency License Inventory")
    lines.append("")
    lines.append(
        "> **Generated file — do not edit by hand.** Regenerate with "
        "`python scripts/gen_license_inventory.py`. Per-package adjudications "
        "and license overrides live in that script "
        "(`ADJUDICATIONS` / `PY_LICENSE_OVERRIDES`)."
    )
    lines.append("")
    lines.append(
        "RelyLoop is distributed under **Apache-2.0**. Apache-2.0 is "
        "incompatible with **strong copyleft (GPL / AGPL)** in a *shipped* "
        "dependency. This inventory is derived from the locked dependency "
        "closure (`uv tree` + `pnpm licenses`), so it is identical in CI and "
        "locally regardless of ambient virtualenv state. Versions are omitted "
        "on purpose — they live in `uv.lock` / `ui/pnpm-lock.yaml`, and "
        "excluding them keeps routine bumps from churning this file."
    )
    lines.append("")
    lines.append(
        "The `license-inventory` CI job runs "
        "`python scripts/gen_license_inventory.py --check`, which fails if "
        "(a) this file is stale, or (b) any **shipped** dependency carries a "
        "forbidden or unclassified license."
    )
    lines.append("")

    # --- Flagged section (the part humans actually care about) ---------------
    lines.append("## Flagged licenses (non-permissive)")
    lines.append("")
    if not flagged:
        lines.append("_None — every dependency is permissively licensed._")
    else:
        lines.append(
            "| Package | Ecosystem | License | Scope | Apache-2.0 compatible? | Decided action |"
        )
        lines.append("|---|---|---|---|---|---|")
        for r in flagged:
            action = ADJUDICATIONS.get(
                r["norm"], "**Needs adjudication** — add to `ADJUDICATIONS`."
            )
            lines.append(
                f"| {r['name']} | {r['ecosystem']} | {r['license']} | "
                f"{r['scope']} | {_compat_label(classify(r['license']))} | {action} |"
            )
    lines.append("")

    # --- Full table ----------------------------------------------------------
    lines.append("## Full inventory")
    lines.append("")
    lines.append("| Package | Ecosystem | License | Scope | Apache-2.0 compatible? |")
    lines.append("|---|---|---|---|---|")
    for r in rows:
        lines.append(
            f"| {r['name']} | {r['ecosystem']} | {r['license']} | "
            f"{r['scope']} | {_compat_label(classify(r['license']))} |"
        )
    lines.append("")

    # --- Summary -------------------------------------------------------------
    n_runtime = sum(1 for r in rows if r["scope"] == "runtime")
    n_dev = len(rows) - n_runtime
    lines.append("## Summary")
    lines.append("")
    lines.append(
        f"- Total dependencies in locked closure: **{len(rows)}** "
        f"({n_runtime} shipped, {n_dev} dev-only)."
    )
    lines.append(f"- Non-permissive licenses: **{len(flagged)}** (all adjudicated above).")
    # Exactly one trailing newline so the end-of-file-fixer pre-commit hook
    # doesn't rewrite the generated file and break --check determinism.
    return "\n".join(lines) + "\n"


def violations(rows: list[dict]) -> list[str]:
    """Shipped deps with a forbidden or unadjudicated-unknown license."""
    out: list[str] = []
    for r in rows:
        if r["scope"] != "runtime":
            continue
        bucket = classify(r["license"])
        if bucket == "forbidden":
            out.append(
                f"{r['name']} ({r['ecosystem']}): {r['license']} — "
                "strong copyleft in a shipped dependency"
            )
        elif bucket == "unknown" and r["norm"] not in ADJUDICATIONS:
            out.append(f"{r['name']} ({r['ecosystem']}): UNKNOWN license, no adjudication")
    return out


def main() -> int:
    check = "--check" in sys.argv[1:]
    rows = collect_python() + collect_frontend()
    content = render(rows)

    viol = violations(rows)

    if check:
        current = OUTPUT.read_text() if OUTPUT.exists() else ""
        drift = current != content
        if drift:
            print("ERROR: license-inventory.md is stale.", file=sys.stderr)
            print(
                "Run: python scripts/gen_license_inventory.py && git add "
                "docs/04_security/license-inventory.md",
                file=sys.stderr,
            )
        if viol:
            print("ERROR: forbidden/unclassified license in a shipped dependency:", file=sys.stderr)
            for v in viol:
                print(f"  - {v}", file=sys.stderr)
        return 1 if (drift or viol) else 0

    OUTPUT.write_text(content)
    print(
        f"Wrote {OUTPUT.relative_to(REPO_ROOT)} ({len(rows)} dependencies, {len(viol)} violations)."
    )
    if viol:
        for v in viol:
            print(f"  VIOLATION: {v}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
