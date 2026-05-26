"""Dockerfile runtime-stage regression tests.

Pins the ordering of build steps inside the `FROM base AS runtime` stage
so future Dockerfile edits can't silently reintroduce
`bug_dockerfile_venv_root_owned_after_user_switch`: the `RUN uv sync` on
line 107 installs the project package itself into `/app/.venv` as root
(because `USER relyloop` doesn't fire until line 109), leaving 11
package-metadata files root-owned. Any one-shot container then running
`uv run` / `uv sync` as the `relyloop` user (e.g. `make test-worktree`)
fails with EACCES.

The fix is a single `RUN chown -R relyloop:relyloop /app/.venv` between
the runtime-stage `uv sync` and the `USER relyloop` switch. This file
asserts those three lines appear in that strict order.
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


class TestRuntimeStageVenvOwnership:
    """bug_dockerfile_venv_root_owned_after_user_switch — the venv chown
    after `uv sync` is the load-bearing line that keeps `/app/.venv`
    fully relyloop-owned through the runtime stage."""

    def test_runtime_stage_marker_present(self, dockerfile_lines: list[str]) -> None:
        # Defensive: every assertion below scans from the runtime-stage marker
        # onward. If someone renames or removes the stage, every other
        # assertion would still pass against the deps stage and miss the bug.
        _find_line_index(dockerfile_lines, "FROM base AS runtime")

    def test_chown_appears_between_uv_sync_and_user_switch(
        self, dockerfile_lines: list[str]
    ) -> None:
        runtime_start = _find_line_index(dockerfile_lines, "FROM base AS runtime")

        # The deps stage on line ~70 has `uv sync --frozen --no-dev
        # --no-install-project`; the runtime stage has the same WITHOUT
        # `--no-install-project` (it's the one that installs the project
        # package itself, which is what writes root-owned dist-info files).
        # Scanning from the runtime-stage marker disambiguates.
        uv_sync_idx = _find_line_index(
            dockerfile_lines, "uv sync --frozen --no-dev", after=runtime_start
        )
        # Sanity check: the deps-stage sync (line ~70) has --no-install-project;
        # the runtime-stage sync does not. If the matched line carries that flag,
        # the runtime sync was deleted and we're matching the deps sync instead.
        assert "--no-install-project" not in dockerfile_lines[uv_sync_idx], (
            f"Dockerfile line {uv_sync_idx + 1} appears to be the deps-stage "
            "`uv sync` (it has --no-install-project). The runtime stage's "
            "project-installing `uv sync` must come AFTER the FROM-runtime marker "
            "and must NOT carry --no-install-project."
        )

        chown_idx = _find_line_index(
            dockerfile_lines,
            "chown -R relyloop:relyloop /app/.venv",
            after=uv_sync_idx,
        )
        user_switch_idx = _find_line_index(dockerfile_lines, "USER relyloop", after=chown_idx)

        # Strict ordering: uv sync → chown → USER. If chown is missing the
        # _find_line_index call above raises with a clear message; if chown
        # is somewhere before uv sync or after USER, the after= arguments
        # above would have failed to locate it.
        assert uv_sync_idx < chown_idx < user_switch_idx, (
            f"Expected runtime-stage ordering: `RUN uv sync` (line "
            f"{uv_sync_idx + 1}) < `RUN chown -R relyloop:relyloop /app/.venv` "
            f"(line {chown_idx + 1}) < `USER relyloop` (line "
            f"{user_switch_idx + 1}). The chown line is load-bearing — without "
            "it the project-package install leaves 11 root-owned files in "
            "/app/.venv that block any subsequent `uv run` from the relyloop "
            "user (bug_dockerfile_venv_root_owned_after_user_switch)."
        )

    def test_no_user_switch_before_runtime_uv_sync(self, dockerfile_lines: list[str]) -> None:
        # The alternative fix (move USER relyloop above the runtime-stage
        # uv sync) is intentionally NOT what shipped — see bug_fix.md
        # Decision #1. This test pins that decision: any future "let me
        # try moving USER up" change has to grapple with the chown line
        # becoming redundant, which makes the change reviewable.
        runtime_start = _find_line_index(dockerfile_lines, "FROM base AS runtime")
        uv_sync_idx = _find_line_index(
            dockerfile_lines, "uv sync --frozen --no-dev", after=runtime_start
        )
        runtime_block_before_sync = dockerfile_lines[runtime_start:uv_sync_idx]
        assert not any("USER relyloop" in line for line in runtime_block_before_sync), (
            "USER relyloop now appears BEFORE the runtime-stage `uv sync`. "
            "bug_fix.md Decision #1 explicitly picked the chown-after-uv-sync "
            "approach over the USER-above-uv-sync approach. If you want to "
            "switch approaches, drop the chown line in the same commit and "
            "update bug_fix.md."
        )
