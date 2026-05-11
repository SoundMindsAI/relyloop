"""Unit tests for pure / cheap-to-mock helpers in backend.workers.git_pr.

Complements ``test_pr_body_render.py`` (PR body composition) by exercising:

* ``_apply_config_diff`` — diff application + drift detection + JSON guard.
* ``_validate_params_path`` — regex-pass + resolved-path containment check.
* ``_read_pat`` — mounted-secrets bundle read + containment check.
* ``_repo_clone_root`` / ``_secrets_dir`` — env-override branches.
* ``_redact_subprocess_error`` — argv-free CalledProcessError rendering.
* ``_parse_retry_after`` / ``_is_secondary_rate_limit`` /
  ``_parse_rate_limit_reset`` — httpx response header parsers.
* ``_git_env`` / ``_commit_env`` — token-safe subprocess env construction
  (asserts the token NEVER lands in any field name; only in the
  Authorization header value).
* ``_render_chart_png`` — matplotlib Agg smoke + file write.
* ``_git_subprocess`` / ``_ensure_clone`` / ``_prepare_branch`` /
  ``_branch_exists_on_remote`` / ``_git_commit_file`` — driver shape
  verification with ``subprocess.run`` monkeypatched (asserts the
  argv NEVER contains the PAT and the GIT_CONFIG_* env is correct).
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from backend.app.domain.git import InvalidConfigPathError as _InvalidConfigPathError
from backend.workers import git_pr


@pytest.fixture
def _settings_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Provide the required-secret env so ``get_settings()`` is constructible.

    Helpers that read ``Settings.relyloop_git_author_*`` (via ``_commit_env``)
    need the boot-blocking secrets pointed at *something*; ``/dev/null`` is
    fine because the @cached_property accessors aren't invoked in these tests.
    """
    db_url_file = tmp_path / "db_url"
    db_url_file.write_text("postgresql+asyncpg://x:y@localhost/test")
    pw_file = tmp_path / "pw"
    pw_file.write_text("test")
    monkeypatch.setenv("DATABASE_URL_FILE", str(db_url_file))
    monkeypatch.setenv("POSTGRES_PASSWORD_FILE", str(pw_file))
    from backend.app.core.settings import get_settings

    get_settings.cache_clear()


_TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0KlMnOpQrStUvWxYz"


# ---------------------------------------------------------------------------
# Settings + env override branches
# ---------------------------------------------------------------------------


def test_repo_clone_root_default() -> None:
    """Default returns the resolved absolute form of ``./data/repo-clones``.

    GPT-5.5 final-review F1: returning an absolute path lets callers do
    ``file_path.relative_to(clone_dir)`` without worrying about cwd.
    """
    os.environ.pop("RELYLOOP_REPO_CLONE_ROOT", None)
    assert git_pr._repo_clone_root() == Path("./data/repo-clones").resolve()
    assert git_pr._repo_clone_root().is_absolute()


def test_repo_clone_root_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RELYLOOP_REPO_CLONE_ROOT", str(tmp_path))
    assert git_pr._repo_clone_root() == tmp_path.resolve()
    assert git_pr._repo_clone_root().is_absolute()


def test_secrets_dir_default() -> None:
    os.environ.pop("RELYLOOP_SECRETS_DIR", None)
    assert git_pr._secrets_dir() == Path("./secrets")


def test_secrets_dir_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(tmp_path))
    assert git_pr._secrets_dir() == tmp_path


# ---------------------------------------------------------------------------
# _read_pat: file IO + containment
# ---------------------------------------------------------------------------


def test_read_pat_returns_content(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(tmp_path))
    (tmp_path / "acme-pat").write_text(_TOKEN + "\n")
    assert git_pr._read_pat("acme-pat") == _TOKEN


def test_read_pat_empty_returns_none(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(tmp_path))
    (tmp_path / "acme-pat").write_text("")
    assert git_pr._read_pat("acme-pat") is None


def test_read_pat_missing_file_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(tmp_path))
    assert git_pr._read_pat("does-not-exist") is None


def test_read_pat_empty_auth_ref_returns_none() -> None:
    assert git_pr._read_pat("") is None


def test_read_pat_refuses_path_escape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Containment check rejects ``../etc/passwd``-style auth_refs."""
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(tmp_path))
    # Put a file outside the secrets root.
    outside = tmp_path.parent / "outside-secret"
    outside.write_text("should not be readable")
    relative = os.path.relpath(outside, tmp_path)
    assert git_pr._read_pat(relative) is None


def test_read_pat_rejects_directory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """GPT-5.5 F4 — a directory at ``./secrets/{auth_ref}`` returns None instead of crashing."""
    monkeypatch.setenv("RELYLOOP_SECRETS_DIR", str(tmp_path))
    (tmp_path / "is-a-directory").mkdir()
    assert git_pr._read_pat("is-a-directory") is None


# ---------------------------------------------------------------------------
# _apply_config_diff: pure
# ---------------------------------------------------------------------------


def test_apply_config_diff_writes_to_value(tmp_path: Path) -> None:
    params = tmp_path / "tmpl.params.json"
    params.write_text(json.dumps({"k1": 1.0, "b": 0.5}))
    declared = {"k1": "float", "b": "float"}
    diff = {"k1": {"from": 1.0, "to": 1.4}}
    git_pr._apply_config_diff(params, diff, declared)
    after = json.loads(params.read_text())
    assert after == {"k1": 1.4, "b": 0.5}


def test_apply_config_diff_drift_raises(tmp_path: Path) -> None:
    params = tmp_path / "tmpl.params.json"
    params.write_text("{}")
    declared = {"k1": "float"}  # 'b' has drifted off
    diff = {"b": {"from": 0.5, "to": 0.4}}
    with pytest.raises(git_pr._ParamNotInTemplateError):
        git_pr._apply_config_diff(params, diff, declared)


def test_apply_config_diff_missing_file_raises(tmp_path: Path) -> None:
    params = tmp_path / "missing.params.json"
    with pytest.raises(git_pr._ParamsFileNotFoundError):
        git_pr._apply_config_diff(params, {}, {})


def test_apply_config_diff_non_object_raises(tmp_path: Path) -> None:
    params = tmp_path / "tmpl.params.json"
    params.write_text("[1, 2, 3]")
    with pytest.raises(git_pr._ParamsFileNotFoundError):
        git_pr._apply_config_diff(params, {}, {})


def test_apply_config_diff_missing_to_raises(tmp_path: Path) -> None:
    params = tmp_path / "tmpl.params.json"
    params.write_text("{}")
    declared = {"k1": "float"}
    diff = {"k1": {"from": 1.0}}  # no 'to'
    with pytest.raises(git_pr._ParamNotInTemplateError):
        git_pr._apply_config_diff(params, diff, declared)


def test_apply_config_diff_directory_at_path_raises_terminal(tmp_path: Path) -> None:
    """GPT-5.5 C2-F3 — a directory at the params path becomes a terminal worker error."""
    params = tmp_path / "is-a-directory.params.json"
    params.mkdir()
    with pytest.raises(git_pr._ParamsFileNotFoundError):
        git_pr._apply_config_diff(params, {}, {})


def test_apply_config_diff_malformed_json_raises_terminal(tmp_path: Path) -> None:
    """GPT-5.5 C2-F3 — corrupt JSON becomes a terminal worker error, not bubbling."""
    params = tmp_path / "broken.params.json"
    params.write_text("{not: json")
    with pytest.raises(git_pr._ParamsFileNotFoundError):
        git_pr._apply_config_diff(params, {}, {})


# ---------------------------------------------------------------------------
# _validate_params_path: regex + containment
# ---------------------------------------------------------------------------


def test_validate_params_path_accepts_clean(tmp_path: Path) -> None:
    out = git_pr._validate_params_path(tmp_path, "configs", "tmpl")
    assert out == (tmp_path / "configs" / "tmpl.params.json").resolve()


def test_validate_params_path_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(_InvalidConfigPathError):
        git_pr._validate_params_path(tmp_path, "../escape", "tmpl")


def test_validate_params_path_rejects_symlink_escape(tmp_path: Path) -> None:
    """A symlink pointing outside the clone root must be rejected."""
    outside = tmp_path.parent / "outside-dir"
    outside.mkdir(exist_ok=True)
    clone = tmp_path / "clone"
    clone.mkdir()
    sym = clone / "escape"
    sym.symlink_to(outside)
    with pytest.raises(_InvalidConfigPathError):
        git_pr._validate_params_path(clone, "escape", "tmpl")


# ---------------------------------------------------------------------------
# _redact_subprocess_error
# ---------------------------------------------------------------------------


def test_redact_subprocess_error_strips_token_from_stderr() -> None:
    exc = subprocess.CalledProcessError(
        128,
        ["git", "push"],
        stderr=f"fatal: Authentication failed for 'https://x:{_TOKEN}@github.com/o/r'",
    )
    out = git_pr._redact_subprocess_error(exc)
    assert "git exited 128" in out
    assert _TOKEN not in out
    assert "[REDACTED-GH-TOKEN]" in out


def test_redact_subprocess_error_falls_back_to_stdout() -> None:
    exc = subprocess.CalledProcessError(1, ["git"], output=f"warning: {_TOKEN}", stderr="")
    out = git_pr._redact_subprocess_error(exc)
    assert _TOKEN not in out


def test_redact_subprocess_error_with_no_streams() -> None:
    exc = subprocess.CalledProcessError(1, ["git"])
    out = git_pr._redact_subprocess_error(exc)
    assert "git exited 1" in out


# ---------------------------------------------------------------------------
# httpx header parsers
# ---------------------------------------------------------------------------


def test_parse_retry_after_numeric() -> None:
    response = httpx.Response(429, headers={"retry-after": "15"})
    assert git_pr._parse_retry_after(response) == 15.0


def test_parse_retry_after_invalid_falls_back() -> None:
    response = httpx.Response(429, headers={"retry-after": "tomorrow"})
    assert git_pr._parse_retry_after(response) == 1.0


def test_parse_retry_after_missing_falls_back() -> None:
    response = httpx.Response(429)
    assert git_pr._parse_retry_after(response) == 1.0


def test_is_secondary_rate_limit_true() -> None:
    response = httpx.Response(
        403,
        headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1700000000"},
    )
    assert git_pr._is_secondary_rate_limit(response) is True


def test_is_secondary_rate_limit_false_when_remaining_nonzero() -> None:
    response = httpx.Response(
        403, headers={"x-ratelimit-remaining": "10", "x-ratelimit-reset": "1700000000"}
    )
    assert git_pr._is_secondary_rate_limit(response) is False


def test_is_secondary_rate_limit_false_when_missing_reset() -> None:
    response = httpx.Response(403, headers={"x-ratelimit-remaining": "0"})
    assert git_pr._is_secondary_rate_limit(response) is False


def test_body_mentions_rate_limit_matches_secondary() -> None:
    response = httpx.Response(
        403,
        text='{"message": "You have exceeded a secondary rate limit"}',
    )
    assert git_pr._body_mentions_rate_limit(response) is True


def test_body_mentions_rate_limit_matches_abuse() -> None:
    response = httpx.Response(403, text='{"message": "abuse detection triggered"}')
    assert git_pr._body_mentions_rate_limit(response) is True


def test_body_mentions_rate_limit_no_match() -> None:
    response = httpx.Response(403, text='{"message": "Not Found"}')
    assert git_pr._body_mentions_rate_limit(response) is False


def test_parse_rate_limit_reset_future() -> None:
    future = time.time() + 30
    response = httpx.Response(403, headers={"x-ratelimit-reset": str(int(future))})
    wait = git_pr._parse_rate_limit_reset(response)
    assert 28 <= wait <= 32  # rounding tolerance


def test_parse_rate_limit_reset_invalid_falls_back() -> None:
    response = httpx.Response(403, headers={"x-ratelimit-reset": "noop"})
    assert git_pr._parse_rate_limit_reset(response) == 1.0


# ---------------------------------------------------------------------------
# _git_env + _commit_env: token-safe env construction
# ---------------------------------------------------------------------------


def test_git_env_token_only_in_value_field() -> None:
    env = git_pr._git_env(_TOKEN)
    assert env["GIT_CONFIG_COUNT"] == "1"
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    assert env["GIT_CONFIG_VALUE_0"] == f"AUTHORIZATION: Bearer {_TOKEN}"
    # The token must NEVER appear in any KEY field — it lives only in the
    # VALUE field (the Authorization header).
    for key, value in env.items():
        if key != "GIT_CONFIG_VALUE_0":
            assert _TOKEN not in value, f"token leaked to env field {key!r}"


def test_commit_env_includes_bot_identity(
    _settings_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RELYLOOP_GIT_AUTHOR_NAME", "test-bot")
    monkeypatch.setenv("RELYLOOP_GIT_AUTHOR_EMAIL", "test-bot@example.com")
    from backend.app.core.settings import get_settings

    get_settings.cache_clear()

    env = git_pr._commit_env(_TOKEN)
    assert env["GIT_AUTHOR_NAME"] == "test-bot"
    assert env["GIT_AUTHOR_EMAIL"] == "test-bot@example.com"
    assert env["GIT_COMMITTER_NAME"] == "test-bot"
    assert env["GIT_COMMITTER_EMAIL"] == "test-bot@example.com"
    # Token still only in the Authorization header value.
    for key, value in env.items():
        if key != "GIT_CONFIG_VALUE_0":
            assert _TOKEN not in value


# ---------------------------------------------------------------------------
# _render_chart_png: matplotlib Agg smoke
# ---------------------------------------------------------------------------


def test_render_chart_png_writes_file(tmp_path: Path) -> None:
    out = tmp_path / "out" / "chart.png"
    git_pr._render_chart_png({"k1": 0.5, "b": 0.3, "slop": 0.2}, out)
    assert out.exists()
    assert out.stat().st_size > 0


def test_render_chart_png_empty_dict(tmp_path: Path) -> None:
    out = tmp_path / "chart.png"
    git_pr._render_chart_png({}, out)
    assert out.exists()


# ---------------------------------------------------------------------------
# _git_subprocess + driver shape (mock subprocess.run)
# ---------------------------------------------------------------------------


class _FakeRun:
    """Records every subprocess.run call for argv + env inspection."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.stdout_to_return = ""
        self.return_code = 0

    def __call__(self, args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        env = kwargs.get("env") or {}
        self.calls.append({"argv": list(args), "env": dict(env), "cwd": kwargs.get("cwd")})
        result: subprocess.CompletedProcess[str] = subprocess.CompletedProcess(
            args=args, returncode=self.return_code, stdout=self.stdout_to_return, stderr=""
        )
        if self.return_code != 0 and kwargs.get("check"):
            raise subprocess.CalledProcessError(
                self.return_code, args, output=self.stdout_to_return, stderr=""
            )
        return result


def test_git_subprocess_argv_never_contains_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakeRun()
    monkeypatch.setattr("backend.workers.git_pr.subprocess.run", fake)
    git_pr._git_subprocess(["git", "fetch", "origin"], token=_TOKEN)
    assert fake.calls
    for call in fake.calls:
        for arg in call["argv"]:
            assert _TOKEN not in arg, "token leaked into git argv"
        # Verify env carries the auth header.
        assert call["env"]["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
        assert _TOKEN in call["env"]["GIT_CONFIG_VALUE_0"]


def test_ensure_clone_skips_when_dotgit_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeRun()
    monkeypatch.setattr("backend.workers.git_pr.subprocess.run", fake)
    (tmp_path / ".git").mkdir(parents=True)
    git_pr._ensure_clone(tmp_path, "https://github.com/o/r.git", _TOKEN)
    # No clone subprocess should fire.
    assert all("clone" not in call["argv"] for call in fake.calls)


def test_ensure_clone_invokes_git_clone(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = _FakeRun()
    monkeypatch.setattr("backend.workers.git_pr.subprocess.run", fake)
    clone_dir = tmp_path / "fresh"
    git_pr._ensure_clone(clone_dir, "https://github.com/o/r.git", _TOKEN)
    assert any("clone" in call["argv"] for call in fake.calls)


def test_prepare_branch_runs_fetch_reset_clean_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeRun()
    monkeypatch.setattr("backend.workers.git_pr.subprocess.run", fake)
    git_pr._prepare_branch(tmp_path, pr_base_branch="main", new_branch="relyloop/x", token=_TOKEN)
    seen_ops = [call["argv"][1] for call in fake.calls if len(call["argv"]) > 1]
    assert seen_ops == ["fetch", "reset", "clean", "checkout"]
    # The reset is "--hard origin/main" — verify the destructive flag.
    reset_call = next(c for c in fake.calls if c["argv"][1] == "reset")
    assert "--hard" in reset_call["argv"]


def test_branch_exists_on_remote_parses_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeRun()
    fake.stdout_to_return = "abc123\trefs/heads/relyloop/x"
    monkeypatch.setattr("backend.workers.git_pr.subprocess.run", fake)
    assert git_pr._branch_exists_on_remote(tmp_path, "relyloop/x", _TOKEN) is True

    fake.stdout_to_return = ""
    assert git_pr._branch_exists_on_remote(tmp_path, "relyloop/x", _TOKEN) is False


def test_git_commit_file_uses_file_message_and_relpath(
    _settings_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = _FakeRun()
    monkeypatch.setattr("backend.workers.git_pr.subprocess.run", fake)
    (tmp_path / ".git").mkdir(parents=True)
    file_path = tmp_path / "configs" / "tmpl.params.json"
    file_path.parent.mkdir(parents=True)
    file_path.write_text("{}")
    git_pr._git_commit_file(tmp_path, file_path, "test message", _TOKEN)
    add_call = next(c for c in fake.calls if c["argv"][1] == "add")
    assert add_call["argv"] == ["git", "add", "--", "configs/tmpl.params.json"]
    commit_call = next(c for c in fake.calls if c["argv"][1] == "commit")
    assert commit_call["argv"][2] == "-F"  # NEVER -m (cycle-1 F4)
    # Commit identity env was forwarded.
    assert commit_call["env"]["GIT_AUTHOR_NAME"]
    assert commit_call["env"]["GIT_COMMITTER_NAME"]


# ---------------------------------------------------------------------------
# _github_post: retry policy (httpx mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_github_post_returns_2xx_on_first_try() -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(201, json={"html_url": "https://x", "number": 1})
    )
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await git_pr._github_post(
            client, "https://api.github.com/r/o/r/pulls", json_body={}, token=_TOKEN
        )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_github_post_retries_on_5xx_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Make backoff a no-op so the test runs quickly.
    monkeypatch.setattr("backend.workers.git_pr.asyncio.sleep", _no_sleep)

    call_count = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] < 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await git_pr._github_post(
            client, "https://api.github.com/x", json_body={}, token=_TOKEN
        )
    assert resp.status_code == 200
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_github_post_terminal_on_4xx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("backend.workers.git_pr.asyncio.sleep", _no_sleep)
    transport = httpx.MockTransport(lambda req: httpx.Response(404, text="not found"))
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await git_pr._github_post(
            client, "https://api.github.com/x", json_body={}, token=_TOKEN
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_github_post_retries_on_403_with_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GPT-5.5 F3 — 403 with Retry-After header is retryable."""
    monkeypatch.setattr("backend.workers.git_pr.asyncio.sleep", _no_sleep)
    call_count = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] < 2:
            return httpx.Response(403, headers={"retry-after": "1"})
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await git_pr._github_post(
            client, "https://api.github.com/x", json_body={}, token=_TOKEN
        )
    assert resp.status_code == 200
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_github_post_retries_on_403_with_rate_limit_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GPT-5.5 F3 — 403 with rate-limit body but no headers is also retryable."""
    monkeypatch.setattr("backend.workers.git_pr.asyncio.sleep", _no_sleep)
    call_count = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] < 2:
            return httpx.Response(
                403, text='{"message": "You have exceeded a secondary rate limit"}'
            )
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        resp = await git_pr._github_post(
            client, "https://api.github.com/x", json_body={}, token=_TOKEN
        )
    assert resp.status_code == 200
    assert call_count["n"] == 2


async def _no_sleep(_seconds: float) -> None:
    return None
