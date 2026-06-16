# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Corporate package-registry mirror regression tests (npm + PyPI).

Pins the fix for the "build reaches the package-install step, TLS succeeds, but
the corp proxy returns 403 Forbidden for the PUBLIC registry" failure mode:

    npm error code E403
    npm error 403 Forbidden - GET https://registry.npmjs.org/pnpm

This is distinct from the TLS (SELF_SIGNED_CERT_IN_CHAIN) and DNS/egress cases:
the proxy is reachable and trusted but FORBIDS the public npm / PyPI registries
by policy, so the build must use the operator's internal Artifactory / Nexus
virtual repo instead. The knobs:

  * ui/Dockerfile     — NPM_CONFIG_REGISTRY ARG → npm_config_registry ENV
                        (honored by `npm install -g pnpm` AND `pnpm install`)
  * backend Dockerfile — UV_DEFAULT_INDEX ARG/ENV (honored by both `uv sync`
                        steps)

Both default to the PUBLIC registries, so OSS builds are byte-for-byte
unchanged; corp operators override via `.env`. See
docs/03_runbooks/corporate-network-install.md §"Package-registry 403".
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
UI_DOCKERFILE = _REPO_ROOT / "ui" / "Dockerfile"
BACKEND_DOCKERFILE = _REPO_ROOT / "Dockerfile"
COMPOSE_FILE = _REPO_ROOT / "docker-compose.yml"
ENV_EXAMPLE = _REPO_ROOT / ".env.example"

PUBLIC_NPM = "https://registry.npmjs.org/"
PUBLIC_PYPI = "https://pypi.org/simple"


def _logical_lines(text: str) -> list[str]:
    """Collapse backslash-continuations into one logical line each, skip comments."""
    logical: list[str] = []
    current = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith("\\"):
            current += " " + stripped[:-1].strip()
        else:
            current += " " + stripped
            logical.append(current.strip())
            current = ""
    if current:
        logical.append(current.strip())
    return logical


@pytest.fixture(scope="module")
def ui_dockerfile() -> str:
    return UI_DOCKERFILE.read_text()


@pytest.fixture(scope="module")
def backend_dockerfile() -> str:
    return BACKEND_DOCKERFILE.read_text()


@pytest.fixture(scope="module")
def compose() -> str:
    return COMPOSE_FILE.read_text()


class TestUiNpmRegistryMirror:
    def test_npm_registry_arg_defaults_to_public(self, ui_dockerfile: str) -> None:
        lines = _logical_lines(ui_dockerfile)
        arg = next((ln for ln in lines if ln.startswith("ARG NPM_CONFIG_REGISTRY")), None)
        assert arg is not None, (
            "ui/Dockerfile must declare `ARG NPM_CONFIG_REGISTRY` so corp "
            "operators can point npm/pnpm at an internal mirror (the E403 fix)."
        )
        assert PUBLIC_NPM in arg, (
            "ARG NPM_CONFIG_REGISTRY must default to the public npm registry "
            f"({PUBLIC_NPM}) so OSS builds are unchanged; got: {arg!r}"
        )

    def test_npm_registry_env_consumes_arg(self, ui_dockerfile: str) -> None:
        lines = _logical_lines(ui_dockerfile)
        env = next((ln for ln in lines if ln.startswith("ENV npm_config_registry")), None)
        assert env is not None and "${NPM_CONFIG_REGISTRY}" in env, (
            "ui/Dockerfile must set `ENV npm_config_registry=${NPM_CONFIG_REGISTRY}` "
            "— both `npm install -g pnpm` and `pnpm install` honor the lowercase "
            "npm_config_registry env var."
        )

    def test_npm_registry_set_before_npm_install(self, ui_dockerfile: str) -> None:
        lines = _logical_lines(ui_dockerfile)
        env_idx = next(
            (i for i, ln in enumerate(lines) if ln.startswith("ENV npm_config_registry")),
            None,
        )
        npm_idx = next(
            (
                i
                for i, ln in enumerate(lines)
                if ln.startswith("RUN") and "npm install -g pnpm" in ln
            ),
            None,
        )
        assert env_idx is not None and npm_idx is not None
        assert env_idx < npm_idx, (
            "npm_config_registry must be set BEFORE `RUN npm install -g pnpm@9` "
            "or the first npm call still hits the public registry (E403)."
        )


class TestBackendUvIndexMirror:
    def test_uv_default_index_arg_defaults_to_public(self, backend_dockerfile: str) -> None:
        lines = _logical_lines(backend_dockerfile)
        arg = next((ln for ln in lines if ln.startswith("ARG UV_DEFAULT_INDEX")), None)
        assert arg is not None, (
            "Backend Dockerfile must declare `ARG UV_DEFAULT_INDEX` so corp "
            "operators can point uv at an internal PyPI mirror."
        )
        assert PUBLIC_PYPI in arg, (
            f"ARG UV_DEFAULT_INDEX must default to public PyPI ({PUBLIC_PYPI}); got: {arg!r}"
        )

    def test_uv_default_index_passed_inline_not_persistent_env(
        self, backend_dockerfile: str
    ) -> None:
        """Security: the index is passed INLINE to `uv sync`, never as a persistent ENV.

        A credentialed mirror URL in a base- or runtime-stage `ENV` would be
        baked into the final image metadata (visible in `docker inspect`).
        Pins the PR #537 Gemini security-high finding fix.
        """
        lines = _logical_lines(backend_dockerfile)
        assert not any(ln.startswith("ENV UV_DEFAULT_INDEX") for ln in lines), (
            "UV_DEFAULT_INDEX must NOT be a persistent ENV — a credentialed "
            "mirror URL would leak into the final image metadata. Pass it inline "
            "to the deps-stage `uv sync` instead."
        )
        inline = next(
            (
                ln
                for ln in lines
                if ln.startswith("RUN")
                and 'UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX}"' in ln
                and "uv sync" in ln
            ),
            None,
        )
        assert inline is not None, (
            "The deps-stage uv sync must be invoked as "
            '`RUN UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX}" uv sync ...` so the corp '
            "PyPI mirror is honored without a persistent ENV (the discarded deps "
            "stage keeps the value out of the shipped image entirely)."
        )


class TestComposeWiring:
    def test_ui_service_passes_npm_registry(self, compose: str) -> None:
        assert (
            "NPM_CONFIG_REGISTRY: ${NPM_CONFIG_REGISTRY:-https://registry.npmjs.org/}" in compose
        ), (
            "docker-compose.yml must pass NPM_CONFIG_REGISTRY into the ui "
            "build.args, defaulting to the public npm registry."
        )

    def test_backend_services_pass_uv_index(self, compose: str) -> None:
        # migrate + api + worker all build from the backend Dockerfile.
        count = compose.count("UV_DEFAULT_INDEX: ${UV_DEFAULT_INDEX:-https://pypi.org/simple}")
        assert count == 3, (
            "All three backend services (migrate / api / worker) must pass "
            f"UV_DEFAULT_INDEX into build.args; found {count} (expected 3)."
        )


class TestEnvExampleDocumented:
    def test_env_example_documents_both_knobs(self) -> None:
        text = ENV_EXAMPLE.read_text()
        assert "NPM_CONFIG_REGISTRY=" in text and "UV_DEFAULT_INDEX=" in text, (
            ".env.example must document NPM_CONFIG_REGISTRY and UV_DEFAULT_INDEX "
            "so operators behind a package-firewall know the knobs exist."
        )
