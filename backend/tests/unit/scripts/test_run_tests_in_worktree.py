# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""Smoke tests for scripts/run-tests-in-worktree.sh.

Phase 2 of infra_agent_sibling_worktree_isolation (FR-10). Exercises the
script's argument parsing, dry-run command construction, and error paths
WITHOUT invoking Docker. The script's actual end-to-end behavior against a
live Compose stack is the operator-path verification gate (AC-11), run
once per PR rather than every CI cycle.

Pattern: invoke the script via subprocess.run with --dry-run, assert on the
captured stdout/stderr. The script prints `docker` followed by one argv arg
per line in canonical order in --dry-run mode (see FR-8 + AC-9).

Hermeticity: all successful dry-run tests pass `RELYLOOP_MAIN_REPO=<tmp_path>`
with a fake `secrets/database_url` file inside, so the tests do not depend
on the operator having run `make up` or `scripts/install.sh` first. The
missing-secret negative test passes a `RELYLOOP_MAIN_REPO=<tmp_path>` WITHOUT
the secret file.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Final

import pytest

# backend/tests/unit/scripts/ is 4 levels deep from repo root — same parent
# count as the sibling test_dashboard_truncation.py:14.
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[4]
_SCRIPT: Final[Path] = _REPO_ROOT / "scripts" / "run-tests-in-worktree.sh"

# Skip the whole module when running INSIDE the one-shot worktree container
# launched by scripts/run-tests-in-worktree.sh itself. The script sets
# RELYLOOP_IN_WORKTREE_CONTAINER=1 in the container env; inside that container
# `/app` is not a git worktree (the script mounts source paths individually,
# not `.git`), so the script's `git rev-parse --show-toplevel` prerequisite
# check would fail. The smoke tests are host-only by design — they exercise
# the script, not the in-container test runner. Skipping cleanly when nested
# preserves `make test-worktree` (default `pytest backend/tests/unit/ -v`)
# usability: operators see "N skipped" instead of N spurious failures.
pytestmark = pytest.mark.skipif(
    os.environ.get("RELYLOOP_IN_WORKTREE_CONTAINER") == "1",
    reason=(
        "Script smoke tests are host-only — they invoke scripts/run-tests-in-"
        "worktree.sh, which requires a git worktree at cwd. The one-shot "
        "container doesn't mount .git. Run these from the host instead."
    ),
)


def _make_fake_main(
    tmp_path: Path,
    *,
    with_secret: bool = True,
    with_cluster_credentials: bool = False,
) -> Path:
    """Build a fake main-repo directory at tmp_path/fake-main.

    With `with_secret=True` (default), creates BOTH `secrets/database_url`
    AND `secrets/postgres_password` — both are now prerequisites for the
    script (per infra_test_worktree_missing_integration_envs FR-1, the
    postgres_password file is required; the DB-secret check still applies).

    With `with_cluster_credentials=True`, also creates
    `secrets/cluster_credentials.yaml` with a non-empty placeholder so the
    optional FR-2 mount probe succeeds.

    Returns the absolute path the test should pass as `RELYLOOP_MAIN_REPO=`.
    """
    fake_main = tmp_path / "fake-main"
    (fake_main / "secrets").mkdir(parents=True)
    if with_secret:
        (fake_main / "secrets" / "database_url").write_text(
            "postgresql+asyncpg://relyloop:fake@postgres/relyloop\n"
        )
        (fake_main / "secrets" / "postgres_password").write_text("fakepw\n")
    if with_cluster_credentials:
        (fake_main / "secrets" / "cluster_credentials.yaml").write_text(
            "local-es: {username: x, password: y}\n"
        )
    return fake_main


def _run(
    *args: str,
    cwd: Path | None = None,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke the script with the given args; never invokes real `docker`.

    All tests pass --dry-run so the script's last step (`docker "${ARGV[@]}"`)
    is replaced by `printf '%s\\n' docker "${ARGV[@]}"; exit 0`. No Docker
    daemon needed. Pass `cwd=` to control the worktree-detection result; pass
    `env_overrides=` to inject RELYLOOP_* env vars.
    """
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
        check=False,
    )


class TestDryRunArgvShape:
    """FR-10 test 1: --dry-run prints the canonical docker run argv."""

    def test_dry_run_outputs_canonical_argv(self, tmp_path: Path) -> None:
        """The dry-run argv contains every flag FR-8 mandates and starts with `docker`.

        Uses a hermetic fake $MAIN_REPO so the test doesn't depend on the
        operator having run `make up`.
        """
        fake_main = _make_fake_main(tmp_path)
        # Clear RELYLOOP_GIT_SHA so the image tag is the documented default `:dev`
        # rather than whatever the operator happens to have set.
        result = _run(
            "--dry-run",
            cwd=_REPO_ROOT,
            env_overrides={
                "RELYLOOP_MAIN_REPO": str(fake_main),
                "RELYLOOP_GIT_SHA": "",
            },
        )
        assert result.returncode == 0, (
            f"--dry-run should exit 0; got {result.returncode}. stderr={result.stderr!r}"
        )
        argv_lines = result.stdout.strip().split("\n")
        # First line is the `docker` executable itself (AC-9).
        assert argv_lines[0] == "docker", (
            f"Dry-run output must start with 'docker' so operators can copy-paste; "
            f"first line was {argv_lines[0]!r}"
        )
        # Post-bug_dockerfile_venv_root_owned_after_user_switch fix: the
        # `--user root` workaround was reverted (the Dockerfile now switches
        # `USER relyloop` BEFORE the runtime-stage `uv sync` so the venv stays
        # fully relyloop-owned), and `PYTHONDONTWRITEBYTECODE=1` was dropped
        # from the `-e` flag list (already set in Dockerfile:23's base ENV).
        # Negative assertions guard against re-adding the workaround.
        assert "run" in argv_lines
        assert "--rm" in argv_lines
        assert "--user" not in argv_lines, (
            "--user flag must NOT be set; the Dockerfile USER-before-uv-sync "
            "fix removed the need for the --user root workaround. If you're "
            "re-adding it, first check whether "
            "bug_dockerfile_venv_root_owned_after_user_switch regressed."
        )
        assert "PYTHONDONTWRITEBYTECODE=1" not in argv_lines, (
            "PYTHONDONTWRITEBYTECODE=1 -e flag is redundant — already set in "
            "Dockerfile:23's base stage ENV; only had a reason to exist while "
            "--user root was in play."
        )
        assert "--network" in argv_lines
        assert "DATABASE_URL_FILE=/run/secrets/database_url" in argv_lines
        assert "POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password" in argv_lines
        # Count docker `-v` MOUNT flags only (each is paired with a `host:container[:ro]`
        # value containing a colon). Naive `line == "-v"` counts also catch the
        # pytest verbose flag at the end of the default command, so we look at
        # adjacent pairs. FR-8 + Phase 2 operator-path verification + the
        # infra_test_worktree_missing_integration_envs FR-1 addition: DB secret
        # + postgres_password + CLAUDE.md + 9 source paths = 12 mounts when no
        # cluster_credentials.yaml is present in the fake main repo.
        v_mount_count = sum(
            1 for i, line in enumerate(argv_lines[:-1]) if line == "-v" and ":" in argv_lines[i + 1]
        )
        assert v_mount_count == 12, (
            f"Expected exactly 12 -v mounts (DB secret + postgres_password + "
            f"CLAUDE.md + 9 source paths per FR-8 + infra_test_worktree_missing_"
            f"integration_envs FR-1); found {v_mount_count}. argv: {argv_lines!r}"
        )
        # The postgres_password mount must target the canonical compose path so
        # Pydantic-settings auto-binding inside the container resolves the
        # `POSTGRES_PASSWORD_FILE` env var to a readable mounted secret.
        assert any("/run/secrets/postgres_password:ro" in line for line in argv_lines), (
            f"Expected a -v mount targeting /run/secrets/postgres_password:ro "
            f"(matches docker-compose.yml lines 69, 96, 154); argv: {argv_lines!r}"
        )
        # With RELYLOOP_GIT_SHA cleared, the image tag is exactly `relyloop/api:dev`.
        assert "relyloop/api:dev" in argv_lines, (
            f"Expected image tag 'relyloop/api:dev' (FR-8 default when "
            f"RELYLOOP_GIT_SHA unset); argv: {argv_lines!r}"
        )
        # Default in-container command is `uv run pytest backend/tests/unit/ -v`.
        assert "uv" in argv_lines
        assert "pytest" in argv_lines
        assert "backend/tests/unit/" in argv_lines

    def test_required_bind_mounts_all_present(self, tmp_path: Path) -> None:
        """Every spec-mandated mount target appears in the dry-run argv."""
        fake_main = _make_fake_main(tmp_path)
        result = _run(
            "--dry-run",
            cwd=_REPO_ROOT,
            env_overrides={"RELYLOOP_MAIN_REPO": str(fake_main)},
        )
        assert result.returncode == 0
        stdout = result.stdout
        # Each of the 12 mount target paths must appear in some -v argument.
        # postgres_password was added by infra_test_worktree_missing_integration_envs
        # FR-1; the other 11 are the original FR-8 + Phase 2 mount set.
        for target in (
            "/run/secrets/database_url:ro",
            "/run/secrets/postgres_password:ro",
            "/app/CLAUDE.md:ro",
            "/app/backend",
            "/app/migrations",
            "/app/scripts",
            "/app/pyproject.toml:ro",
            "/app/uv.lock:ro",
            "/app/alembic.ini:ro",
            "/app/docker-compose.yml:ro",
            "/app/Makefile:ro",
            "/app/samples:ro",
        ):
            assert target in stdout, (
                f"Expected mount target {target!r} in --dry-run argv; stdout did not contain it."
            )


class TestErrorPaths:
    """FR-10 tests 2-3: clear-error paths for missing prerequisites."""

    def test_errors_on_missing_secret_file(self, tmp_path: Path) -> None:
        """If $MAIN_REPO/secrets/database_url is missing, the script exits
        non-zero with a clear error that references both Rule #2 and the
        scripts/install.sh regeneration command (AC-10).
        """
        # Build a fake "main repo" that does NOT have secrets/database_url.
        fake_main = _make_fake_main(tmp_path, with_secret=False)
        result = _run(
            "--dry-run",
            cwd=_REPO_ROOT,
            env_overrides={"RELYLOOP_MAIN_REPO": str(fake_main)},
        )
        assert result.returncode != 0, (
            f"Expected non-zero exit for missing secret; got {result.returncode}. "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        # Error references the missing path.
        assert "secrets/database_url" in result.stderr, (
            f"Error should name the missing path; stderr={result.stderr!r}"
        )
        # AC-10 specifically requires the error to mention Rule #2.
        assert "Rule #2" in result.stderr, (
            f"Error should reference CLAUDE.md Absolute Rule #2; stderr={result.stderr!r}"
        )
        # AC-10 also requires pointing at scripts/install.sh for regeneration.
        assert "scripts/install.sh" in result.stderr, (
            f"Error should point at scripts/install.sh for secret regeneration; "
            f"stderr={result.stderr!r}"
        )

    def test_errors_on_missing_postgres_password_file(self, tmp_path: Path) -> None:
        """If $MAIN_REPO/secrets/postgres_password is missing, the script exits 5
        with a clear error that references Rule #2 and the scripts/install.sh
        regeneration command (infra_test_worktree_missing_integration_envs
        AC-2).
        """
        # Build a fake main repo with database_url but NOT postgres_password.
        fake_main = _make_fake_main(tmp_path)
        (fake_main / "secrets" / "postgres_password").unlink()

        result = _run(
            "--dry-run",
            cwd=_REPO_ROOT,
            env_overrides={"RELYLOOP_MAIN_REPO": str(fake_main)},
        )
        assert result.returncode == 5, (
            f"Expected exit 5 for missing postgres_password; got {result.returncode}. "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        # Error references the missing path.
        assert "secrets/postgres_password" in result.stderr, (
            f"Error should name the missing path; stderr={result.stderr!r}"
        )
        # AC-2 requires the error to mention Rule #2.
        assert "Rule #2" in result.stderr, (
            f"Error should reference CLAUDE.md Absolute Rule #2; stderr={result.stderr!r}"
        )
        # AC-2 also requires pointing at scripts/install.sh for regeneration.
        assert "scripts/install.sh" in result.stderr, (
            f"Error should point at scripts/install.sh for secret regeneration; "
            f"stderr={result.stderr!r}"
        )

    def test_errors_when_not_in_worktree(self, tmp_path: Path) -> None:
        """If invoked from a path outside any git worktree, the script exits
        non-zero with a clear error naming the prerequisite.
        """
        # tmp_path is hermetic and not inside any git worktree (pytest tmp_path
        # is /tmp/pytest-... on Linux, /private/var/folders/... on macOS — neither
        # is typically inside a git repo).
        outside = tmp_path / "outside-repo"
        outside.mkdir()
        result = _run("--dry-run", cwd=outside)
        if result.returncode == 0:
            # Defensive: if the operator's /tmp happens to be inside a parent
            # git repo (unusual), skip rather than fail spuriously. CI runners
            # are hermetic, so this path is for local-dev resilience.
            pytest.skip(
                "tmp_path appears to be inside a parent git repo on this "
                "system; cannot exercise the not-in-worktree error path."
            )
        # Error names the worktree prerequisite.
        assert "git worktree" in result.stderr or "worktree" in result.stderr.lower(), (
            f"Expected stderr to name the worktree prerequisite; stderr={result.stderr!r}"
        )


class TestCmdOverride:
    """FR-10 test 4: --cmd override propagates into the argv."""

    def test_cmd_override_appears_in_argv(self, tmp_path: Path) -> None:
        """--cmd "<override>" replaces the default command but keeps `uv run`."""
        fake_main = _make_fake_main(tmp_path)
        result = _run(
            "--dry-run",
            "--cmd",
            "pytest backend/tests/integration -v",
            cwd=_REPO_ROOT,
            env_overrides={"RELYLOOP_MAIN_REPO": str(fake_main)},
        )
        assert result.returncode == 0, (
            f"Expected exit 0 for --dry-run with override; got {result.returncode}. "
            f"stderr={result.stderr!r}"
        )
        argv_lines = result.stdout.strip().split("\n")
        # The script always prepends `uv run`.
        assert "uv" in argv_lines
        # Override-specific tokens.
        assert "backend/tests/integration" in argv_lines, (
            f"Expected override target 'backend/tests/integration' in argv; argv: {argv_lines!r}"
        )
        # The DEFAULT target should NOT appear when --cmd overrides.
        assert "backend/tests/unit/" not in argv_lines, (
            f"Default target leaked into --cmd override argv: {argv_lines!r}"
        )

    def test_cmd_override_requires_value(self, tmp_path: Path) -> None:
        """--cmd without a value exits non-zero with a usage error."""
        # Even before validating prerequisites, --cmd <missing-value> should fail.
        result = _run("--cmd", cwd=_REPO_ROOT)
        assert result.returncode == 2, (
            f"Expected exit code 2 (usage error) for --cmd without value; "
            f"got {result.returncode}. stdout={result.stdout!r} "
            f"stderr={result.stderr!r}"
        )
        assert "--cmd" in result.stderr

    def test_positional_args_after_dash_dash_preserve_quoting(self, tmp_path: Path) -> None:
        """`-- pytest -k 'foo bar'` preserves the quoted arg as a single token.

        This is the recommended path (over --cmd's word-splitting) for any
        in-container command that needs quoted arguments.
        """
        fake_main = _make_fake_main(tmp_path)
        result = _run(
            "--dry-run",
            "--",
            "pytest",
            "-k",
            "foo bar",  # single arg with a space — must survive as one token
            cwd=_REPO_ROOT,
            env_overrides={"RELYLOOP_MAIN_REPO": str(fake_main)},
        )
        assert result.returncode == 0, (
            f"Expected exit 0 for -- positional args; got {result.returncode}. "
            f"stderr={result.stderr!r}"
        )
        argv_lines = result.stdout.strip().split("\n")
        # The quoted arg should appear as a single argv line.
        assert "foo bar" in argv_lines, (
            f"Quoted -k value 'foo bar' should be preserved as a single argv "
            f"token; argv: {argv_lines!r}"
        )
        # And NOT word-split (no separate 'foo' and 'bar' lines from this arg).
        # Note: "bar" might appear elsewhere; we check that "foo" doesn't appear
        # as its own line.
        assert "foo" not in argv_lines or argv_lines.count("foo") == 0, (
            f"-- positional args should NOT word-split; argv: {argv_lines!r}"
        )

    def test_cmd_and_positional_are_mutually_exclusive(self, tmp_path: Path) -> None:
        """Passing both --cmd and `--ARG` is rejected with a usage error."""
        result = _run(
            "--cmd",
            "pytest backend/tests/unit/ -v",
            "--",
            "pytest",
            "-k",
            "foo",
            cwd=_REPO_ROOT,
        )
        assert result.returncode == 2, (
            f"Expected exit 2 (usage error) when --cmd and -- are both passed; "
            f"got {result.returncode}. stderr={result.stderr!r}"
        )
        assert "--cmd" in result.stderr or "positional" in result.stderr.lower(), (
            f"Error should explain the conflict; stderr={result.stderr!r}"
        )


class TestClusterCredentialsOptionalMount:
    """infra_test_worktree_missing_integration_envs FR-2 + FR-3: optional
    CLUSTER_CREDENTIALS_FILE propagation with mount-if-present semantics
    and a --dry-run stderr hint when the probe fails.
    """

    def test_cluster_credentials_mounted_when_host_file_present(self, tmp_path: Path) -> None:
        """When secrets/cluster_credentials.yaml is readable and non-empty,
        the script adds the CLUSTER_CREDENTIALS_FILE env var + mount to argv
        (AC-3). The total mount count becomes 13 (the 12-mount baseline plus
        the new cluster_credentials entry).
        """
        fake_main = _make_fake_main(tmp_path, with_cluster_credentials=True)
        result = _run(
            "--dry-run",
            cwd=_REPO_ROOT,
            env_overrides={
                "RELYLOOP_MAIN_REPO": str(fake_main),
                "RELYLOOP_GIT_SHA": "",
            },
        )
        assert result.returncode == 0, (
            f"Expected exit 0 for present cluster_credentials; got {result.returncode}. "
            f"stderr={result.stderr!r}"
        )
        argv_lines = result.stdout.strip().split("\n")

        # The env-var token must appear in argv.
        assert "CLUSTER_CREDENTIALS_FILE=/run/secrets/cluster_credentials" in argv_lines, (
            f"Expected CLUSTER_CREDENTIALS_FILE env var in argv; argv: {argv_lines!r}"
        )

        # The mount target must match docker-compose.yml lines 102, 160.
        assert any("/run/secrets/cluster_credentials:ro" in line for line in argv_lines), (
            f"Expected a -v mount targeting /run/secrets/cluster_credentials:ro "
            f"(matches docker-compose.yml lines 102, 160); argv: {argv_lines!r}"
        )

        # Mount count is now 13 (12 baseline + 1 conditional).
        v_mount_count = sum(
            1 for i, line in enumerate(argv_lines[:-1]) if line == "-v" and ":" in argv_lines[i + 1]
        )
        assert v_mount_count == 13, (
            f"Expected exactly 13 -v mounts when cluster_credentials.yaml is "
            f"present (12 baseline + 1 cluster_credentials); found {v_mount_count}. "
            f"argv: {argv_lines!r}"
        )

        # When mount succeeds, the FR-3 skip hint MUST NOT appear.
        assert "skipped optional mount" not in result.stderr, (
            f"FR-3 stderr hint should NOT fire when the probe succeeds; stderr={result.stderr!r}"
        )

    @pytest.mark.parametrize(
        "mode",
        ["absent", "empty", "unreadable"],
    )
    def test_cluster_credentials_skipped_when_host_file_absent_or_empty(
        self, tmp_path: Path, mode: str
    ) -> None:
        """FR-2 + FR-3: parametrized across all three skip modes (absent /
        empty / unreadable). For each, the script must:
          - exit 0 (skip is a normal path, not an error)
          - omit CLUSTER_CREDENTIALS_FILE from argv (no env var, no mount)
          - keep v_mount_count at the 12-mount baseline
          - emit the FR-3 skip hint to stderr (--dry-run only)

        Covers AC-4 (absent), AC-5 (empty), and the readability-probe addition
        from spec D-0 (unreadable). The unreadable subcase skips when the test
        runner has euid 0 (root can read 0o000 files; chmod can't enforce the
        unreadable state under root) per spec D-0a.
        """
        if mode == "unreadable" and (
            os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0)
        ):
            pytest.skip(
                "unreadable subcase requires a non-Windows platform and a "
                "non-root euid — chmod 0o000 doesn't restrict reads on "
                "Windows (NTFS ACLs work differently) and root bypasses "
                "POSIX mode bits, so the probe would still succeed and the "
                "test's mount-count assertion would falsely fail"
            )

        # Build a fake main repo with database_url + postgres_password but
        # without cluster_credentials.yaml; then create the file in the
        # requested skip-mode state.
        fake_main = _make_fake_main(tmp_path)
        creds_path = fake_main / "secrets" / "cluster_credentials.yaml"
        original_mode: int | None = None

        try:
            if mode == "absent":
                # File does not exist — _make_fake_main(with_cluster_credentials=False)
                # is the default; nothing more to do.
                pass
            elif mode == "empty":
                creds_path.write_text("")
            elif mode == "unreadable":
                creds_path.write_text("local-es: {username: x, password: y}\n")
                original_mode = creds_path.stat().st_mode & 0o777
                os.chmod(creds_path, 0o000)

            result = _run(
                "--dry-run",
                cwd=_REPO_ROOT,
                env_overrides={
                    "RELYLOOP_MAIN_REPO": str(fake_main),
                    "RELYLOOP_GIT_SHA": "",
                },
            )
        finally:
            # Restore perms so pytest's tmp_path cleanup can delete the file.
            if original_mode is not None and creds_path.exists():
                os.chmod(creds_path, original_mode)

        assert result.returncode == 0, (
            f"Expected exit 0 when cluster_credentials is in skip mode {mode!r}; "
            f"got {result.returncode}. stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        argv_lines = result.stdout.strip().split("\n")

        # The env-var token must NOT appear in argv.
        assert "CLUSTER_CREDENTIALS_FILE=/run/secrets/cluster_credentials" not in argv_lines, (
            f"CLUSTER_CREDENTIALS_FILE leaked into argv despite skip mode "
            f"{mode!r}; argv: {argv_lines!r}"
        )

        # The mount target must NOT appear in argv.
        assert not any("/run/secrets/cluster_credentials:ro" in line for line in argv_lines), (
            f"cluster_credentials mount leaked into argv despite skip mode "
            f"{mode!r}; argv: {argv_lines!r}"
        )

        # Mount count stays at the 12-mount baseline.
        v_mount_count = sum(
            1 for i, line in enumerate(argv_lines[:-1]) if line == "-v" and ":" in argv_lines[i + 1]
        )
        assert v_mount_count == 12, (
            f"Expected 12 -v mounts in skip mode {mode!r} (no cluster_credentials "
            f"added); found {v_mount_count}. argv: {argv_lines!r}"
        )

        # FR-3: --dry-run mode emits the skip hint to stderr.
        assert "skipped optional mount: CLUSTER_CREDENTIALS_FILE" in result.stderr, (
            f"FR-3 stderr hint should fire in --dry-run mode for skip mode "
            f"{mode!r}; stderr={result.stderr!r}"
        )
