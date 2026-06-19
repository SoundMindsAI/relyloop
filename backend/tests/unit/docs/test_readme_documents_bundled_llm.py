# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""README ↔ bundled-LLM feature lockstep (feat_bundled_local_llm, AC-7).

The README must document the one-flag opt-in (`RELYLOOP_LLM=ollama make up`)
in the same PR that ships the helper + Compose service — a documented-but-
nonexistent command is exactly the clean-room failure mode this project guards
against. This test keeps the README and the implementation honest: if the
`RELYLOOP_LLM` selector is renamed/removed, or the three options drift out of
the README, this fails.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_README = _REPO_ROOT / "README.md"
_HELPER = _REPO_ROOT / "scripts" / "lib" / "relyloop_llm.sh"


@pytest.fixture(scope="module")
def readme() -> str:
    return _README.read_text()


def test_readme_documents_the_optin_command(readme: str) -> None:
    assert "RELYLOOP_LLM=ollama" in readme, (
        "README must document the bundled-LLM opt-in command "
        "`RELYLOOP_LLM=ollama make up` (feat_bundled_local_llm FR-6)"
    )


def test_readme_documents_all_three_options(readme: str) -> None:
    # Options A (no LLM), B (bundled), C (BYO endpoint) must all be present.
    for marker in ("Option A", "Option B", "Option C"):
        assert marker in readme, f"README LLM section is missing {marker!r}"


def test_readme_states_the_cpu_only_macos_caveat(readme: str) -> None:
    assert "CPU-only" in readme, (
        "README must state the Docker-on-macOS CPU-only caveat so operators "
        "aren't surprised by bundled-LLM speed"
    )


def test_readme_names_the_default_model(readme: str) -> None:
    assert "qwen3.5:4b" in readme, "README must name the bundled default model"


def test_readme_documents_native_and_docker_values() -> None:
    # Native-first re-scope: README must document both the native `ollama` value
    # and the `ollama-docker` zero-install fallback.
    readme = _README.read_text()
    assert "RELYLOOP_LLM=ollama" in readme
    assert "ollama-docker" in readme, "README must document the RELYLOOP_LLM=ollama-docker fallback"


def test_optin_selector_values_match_helper_allowlist() -> None:
    # The README's selector values must be the ones the helper actually accepts —
    # guards against doc/code drift on the allowlist.
    helper = _HELPER.read_text()
    assert "Allowed: ollama, ollama-docker." in helper, (
        "relyloop_llm.sh allowlist changed — update the README LLM options"
    )
