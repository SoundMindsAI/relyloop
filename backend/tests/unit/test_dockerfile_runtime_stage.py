# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Dockerfile runtime-stage regression tests.

Pins the ordering of build steps inside the `FROM base AS runtime` stage
so future Dockerfile edits can't silently reintroduce
`bug_dockerfile_venv_root_owned_after_user_switch`: if `USER relyloop`
is dropped or moved AFTER the runtime-stage `RUN uv sync --frozen
--no-dev`, the sync runs as root and writes `relyloop-0.1.0.dist-info/*`
files as `root:root` into the venv. Any one-shot container then running
`uv run` / `uv sync` as the `relyloop` user (e.g. `make test-worktree`)
fails with EACCES rewriting those files.

The fix is to place `USER relyloop` BEFORE the runtime-stage
`RUN uv sync` so the project-install runs as the unprivileged user from
the start. The alternative (chown-after-sync) was rejected during
Gemini review because `RUN chown -R /app/.venv` triggers an overlay2
layer copy-up that bloats the image by ~385MB.
"""

from __future__ import annotations

from pathlib import Path

import pytest

DOCKERFILE_PATH = Path(__file__).resolve().parents[3] / "Dockerfile"


@pytest.fixture(scope="module")
def dockerfile_lines() -> list[str]:
    return DOCKERFILE_PATH.read_text().splitlines()


def _find_line_index(lines: list[str], substring: str, *, after: int = 0) -> int:
    """Return the index of the first line containing `substring` at or after `after`.

    Raises AssertionError with a helpful message if not found.
    """
    for i in range(after, len(lines)):
        if substring in lines[i]:
            return i
    raise AssertionError(
        f"Dockerfile does not contain a line with {substring!r} at or after index {after}"
    )


def _find_directive(lines: list[str], directive: str, args: str, *, after: int = 0) -> int:
    """Return the index of the first actual Dockerfile directive matching `directive args`.

    Skips comment lines (lines whose stripped form starts with `#`) and any
    line where the directive token is embedded in prose rather than at the
    start. This is the load-bearing matcher for assertions that must NOT be
    fooled by Dockerfile comments mentioning the directive by name.

    Match shape: `<directive> <args>` after stripping leading whitespace. Trailing
    text (e.g., line-continuation backslash, trailing comment) is allowed.
    """
    needle = f"{directive} {args}"
    for i in range(after, len(lines)):
        stripped = lines[i].lstrip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith(needle):
            return i
    raise AssertionError(
        f"Dockerfile does not contain a `{needle}` directive at or after index {after} "
        "(comment lines mentioning the directive in prose are ignored)"
    )


class TestRuntimeStageVenvOwnership:
    """bug_dockerfile_venv_root_owned_after_user_switch — `USER relyloop`
    must fire BEFORE the runtime-stage `RUN uv sync --frozen --no-dev` so
    the project-install runs unprivileged and writes
    `relyloop-0.1.0.dist-info/*` files as relyloop:relyloop."""

    def test_runtime_stage_marker_present(self, dockerfile_lines: list[str]) -> None:
        # Defensive: every assertion below scans from the runtime-stage marker
        # onward. If someone renames or removes the stage, every other
        # assertion would still pass against the deps stage and miss the bug.
        _find_line_index(dockerfile_lines, "FROM base AS runtime")

    def test_user_switch_appears_before_runtime_uv_sync(self, dockerfile_lines: list[str]) -> None:
        runtime_start = _find_line_index(dockerfile_lines, "FROM base AS runtime")
        # Match actual directives only — Dockerfile comments mentioning the
        # `USER relyloop` directive in prose must not satisfy these lookups
        # (per GPT-5.5 round-2 review: substring matching was too weak).
        user_switch_idx = _find_directive(dockerfile_lines, "USER", "relyloop", after=runtime_start)
        # The runtime-stage `uv sync` is the one WITHOUT `--no-install-project`.
        # The deps-stage sync (line ~70) has that flag; the runtime-stage one
        # installs the project package itself, which is the load-bearing call.
        uv_sync_idx = _find_directive(
            dockerfile_lines, "RUN", "uv sync --frozen --no-dev", after=user_switch_idx
        )
        # Sanity check: confirm we matched the runtime-stage sync, not a future
        # rearrangement that put the deps-stage sync after the USER directive.
        assert "--no-install-project" not in dockerfile_lines[uv_sync_idx], (
            f"Dockerfile line {uv_sync_idx + 1} appears to be a deps-style "
            "`uv sync` (it has --no-install-project). The runtime-stage's "
            "project-installing `uv sync` must be the one this test pins, and "
            "it must come AFTER `USER relyloop`."
        )

        assert user_switch_idx < uv_sync_idx, (
            f"Expected runtime-stage ordering: `USER relyloop` (line "
            f"{user_switch_idx + 1}) < `RUN uv sync --frozen --no-dev` (line "
            f"{uv_sync_idx + 1}). The USER switch is load-bearing — without "
            "it the project-package install runs as root and leaves 11 "
            "root-owned files in /app/.venv that block any subsequent `uv run` "
            "from the relyloop user "
            "(bug_dockerfile_venv_root_owned_after_user_switch)."
        )

    def test_no_chown_recursive_on_venv(self, dockerfile_lines: list[str]) -> None:
        # The chown-after-sync alternative was rejected in Gemini review
        # because `RUN chown -R /app/.venv` triggers an overlay2 layer
        # copy-up that bloats the image by ~385MB. If a future edit adds
        # such a step "to be safe," it would silently re-introduce the
        # bloat without solving any problem (the USER-above-sync placement
        # already produces the correct ownership). Pin the absence.
        # Match only actual RUN instructions (stripped line starts with
        # "RUN ") — Dockerfile comments are allowed to mention the
        # pattern when explaining why we don't do it.
        offending = [
            (i, line)
            for i, line in enumerate(dockerfile_lines)
            if line.lstrip().startswith("RUN ") and "chown -R" in line and "/app/.venv" in line
        ]
        assert not offending, (
            f"Dockerfile contains `RUN chown -R … /app/.venv` at line(s) "
            f"{[idx + 1 for idx, _ in offending]}. That step triggers an "
            "overlay2 layer copy-up that bloats the image by ~385MB. The "
            "correct fix is `USER relyloop` BEFORE the runtime-stage "
            "`uv sync` (no chown needed). See "
            "bug_dockerfile_venv_root_owned_after_user_switch/bug_fix.md."
        )
