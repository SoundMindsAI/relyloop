# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Corporate-CA trust-store regression tests for both Dockerfiles.

Pins the fix for the "ran `make corp-ca-extract` but `make up` still fails
with SELF_SIGNED_CERT_IN_CHAIN" failure mode.

Root cause: `update-ca-certificates` rebuilds only the OpenSSL system trust
bundle (`/etc/ssl/certs/ca-certificates.crt`). Two of the build's tools keep
their OWN trust stores and ignore the system bundle:

  * Node.js (npm + pnpm) — uses a CA list compiled into the binary. Needs
    NODE_EXTRA_CA_CERTS pointing at a PEM file to ADD certs to its roots.
  * uv — ships bundled webpki-roots. Needs UV_NATIVE_TLS=1 to use the OS
    trust store.

Without these env vars the corp CA install is a silent no-op for those tools
and the build fails behind a TLS-intercepting corp proxy even though the cert
was correctly extracted and installed. See
docs/03_runbooks/corporate-network-install.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
UI_DOCKERFILE = _REPO_ROOT / "ui" / "Dockerfile"
BACKEND_DOCKERFILE = _REPO_ROOT / "Dockerfile"

# The system bundle is the canonical target. It is NOT guaranteed to ship in
# the slim base images (node:26-bookworm-slim does not), so every Dockerfile
# stage that relies on it must `apt-get install ca-certificates` first — that
# both creates the bundle AND makes `update-ca-certificates` available, which
# then appends the corp CA. With the bundle guaranteed, NODE_EXTRA_CA_CERTS is
# a harmless no-op without a corp CA and a working fix with one. A regression
# that drops the explicit install resurfaces the original failure: Node logs
# "Ignoring extra certs ... No such file or directory" and falls back to its
# built-in roots, so `npm install` fails with SELF_SIGNED_CERT_IN_CHAIN behind
# a TLS-intercepting proxy. Pointing NODE_EXTRA_CA_CERTS at the individual
# `corp_ca.crt` would likewise break the OSS (no-corp-CA) path.
SYSTEM_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"


def _directive_lines(text: str, directive: str) -> list[tuple[int, str]]:
    """Return (index, line) for every real (non-comment) line starting with `directive`."""
    out: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines()):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith(directive):
            out.append((i, stripped))
    return out


@pytest.fixture(scope="module")
def ui_dockerfile() -> str:
    return UI_DOCKERFILE.read_text()


@pytest.fixture(scope="module")
def backend_dockerfile() -> str:
    return BACKEND_DOCKERFILE.read_text()


class TestUiNodeExtraCaCerts:
    def test_node_extra_ca_certs_points_at_system_bundle(self, ui_dockerfile: str) -> None:
        env_lines = [
            line
            for _, line in _directive_lines(ui_dockerfile, "ENV")
            if "NODE_EXTRA_CA_CERTS" in line
        ]
        assert env_lines, (
            "ui/Dockerfile must set NODE_EXTRA_CA_CERTS — without it npm/pnpm "
            "ignore the corp CA installed via update-ca-certificates and the "
            "build fails with SELF_SIGNED_CERT_IN_CHAIN behind a corp proxy."
        )
        assert all(SYSTEM_BUNDLE in line for line in env_lines), (
            f"NODE_EXTRA_CA_CERTS must point at the system bundle "
            f"({SYSTEM_BUNDLE}). Pointing it at the individual corp_ca.crt "
            "breaks the no-corp-CA path with a missing-file warning."
        )

    def test_node_extra_ca_certs_set_before_npm_install(self, ui_dockerfile: str) -> None:
        lines = ui_dockerfile.splitlines()
        env_idx = next(
            (
                i
                for i, ln in enumerate(lines)
                if ln.lstrip().startswith("ENV") and "NODE_EXTRA_CA_CERTS" in ln
            ),
            None,
        )
        assert env_idx is not None, (
            "ui/Dockerfile must set NODE_EXTRA_CA_CERTS in an ENV directive."
        )
        npm_idx = next(
            (
                i
                for i, ln in enumerate(lines)
                if ln.lstrip().startswith("RUN") and "npm install -g pnpm" in ln
            ),
            None,
        )
        assert npm_idx is not None, (
            "ui/Dockerfile must install pnpm via `RUN npm install -g pnpm@9`."
        )
        assert env_idx < npm_idx, (
            "NODE_EXTRA_CA_CERTS must be set BEFORE `RUN npm install -g pnpm@9` "
            "or the first npm call still fails behind a TLS-intercepting proxy."
        )

    def test_ca_certificates_installed_before_npm_install(self, ui_dockerfile: str) -> None:
        """node:26-bookworm-slim does not ship the generated system CA bundle.

        Without an explicit `apt-get install ca-certificates`, the file
        NODE_EXTRA_CA_CERTS points at (/etc/ssl/certs/ca-certificates.crt) does
        not exist at the `npm install` step, so Node ignores the corp CA and
        the build fails with SELF_SIGNED_CERT_IN_CHAIN behind a corp proxy.
        """
        lines = ui_dockerfile.splitlines()
        # The install lands on a backslash-continuation line (`&& apt-get
        # install ... ca-certificates \`), which does not start with RUN, so
        # match on the substrings rather than the directive prefix.
        ca_idx = next(
            (
                i
                for i, ln in enumerate(lines)
                if "apt-get install" in ln and "ca-certificates" in ln
            ),
            None,
        )
        assert ca_idx is not None, (
            "ui/Dockerfile must explicitly `apt-get install ca-certificates` — "
            "node:26-bookworm-slim does not ship the generated system bundle at "
            f"{SYSTEM_BUNDLE}, so NODE_EXTRA_CA_CERTS resolves to a missing file "
            "and npm/pnpm fall back to built-in roots (SELF_SIGNED_CERT_IN_CHAIN)."
        )
        npm_idx = next(
            (
                i
                for i, ln in enumerate(lines)
                if ln.lstrip().startswith("RUN") and "npm install -g pnpm" in ln
            ),
            None,
        )
        assert npm_idx is not None, (
            "ui/Dockerfile must install pnpm via `RUN npm install -g pnpm@9`."
        )
        assert ca_idx < npm_idx, (
            "`apt-get install ca-certificates` must run BEFORE "
            "`RUN npm install -g pnpm@9` so the system CA bundle exists."
        )

    def test_runner_stage_installs_ca_certificates(self, ui_dockerfile: str) -> None:
        """The runner stage is a fresh FROM and must install ca-certificates too.

        Its NODE_EXTRA_CA_CERTS (for SSR runtime egress) points at the same
        system bundle, which the slim base does not ship — so the runner needs
        its own explicit install. We assert at least two such installs exist
        (one per fresh `node` FROM: deps + runner).
        """
        install_count = sum(
            1
            for ln in ui_dockerfile.splitlines()
            if "apt-get install" in ln and "ca-certificates" in ln
        )
        assert install_count >= 2, (
            "Both the deps and runner stages (each a fresh node:26-bookworm-slim "
            "FROM) must `apt-get install ca-certificates`; found "
            f"{install_count} such install(s)."
        )


class TestBackendUvNativeTls:
    def test_uv_native_tls_enabled(self, backend_dockerfile: str) -> None:
        assert "UV_NATIVE_TLS=1" in backend_dockerfile, (
            "Backend Dockerfile must set UV_NATIVE_TLS=1 — uv ships bundled "
            "webpki-roots and ignores the corp CA in the system trust store "
            "without it, so `uv sync` fails behind a corp proxy."
        )
