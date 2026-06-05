# SPDX-FileCopyrightText: 2026 soundminds.ai
#
# SPDX-License-Identifier: Apache-2.0

"""``open_pr`` Arq job (feat_github_pr_worker Story 2.1 / FR-2).

Translates an operator-approved proposal into a GitHub pull request
against the cluster's registered config repo. The 15-step contract is
authoritative — see ``implementation_plan.md`` Story 2.1 for the
spec citations and the cycle-1/2/3 GPT-5.5 review findings each step
addresses.

Key invariants derived from prior workers + this feature's plan review:

* **Token-safe git** (cycle-1 F4) — the PAT is passed via the process-
  scoped ``GIT_CONFIG_COUNT=1 + GIT_CONFIG_KEY_0 + GIT_CONFIG_VALUE_0``
  environment-variable trio, NEVER in ``argv`` (visible to ``ps``) and
  NEVER persisted to ``.git/config`` on disk. Mirrors the auth pattern
  that ``actions/checkout`` uses for the same reason.
* **Per-config-repo serialization** (cycle-1 F2 + AC-5) — concurrent
  jobs against the same ``config_repo_id`` race through a Postgres
  ``pg_try_advisory_xact_lock`` keyed on
  ``blake2b("config-repo:{id}", digest_size=8)``. On contention, the
  losing worker raises ``arq.Retry(defer=5.0)`` so it re-enters the
  queue rather than holding a connection. Both proposals eventually
  reach ``status='pr_opened'``.
* **Operator-reject race** (cycle-3 F4) — the final state transition
  uses a conditional UPDATE on ``WHERE id=:id AND status='pending'``.
  If the operator rejected mid-flight (e.g. between branch push and
  PR-open), the UPDATE is a benign no-op and the worker logs
  ``pr_open_proposal_no_longer_pending``. The PR may still exist on
  the remote — that's fine; the operator can close it manually.
* **Persist-then-side-effect ordering** (cycle-2 C2-F3 from
  feat_llm_judgments) — the PR is opened on GitHub BEFORE the
  ``mark_proposal_pr_opened`` write so a transient DB outage doesn't
  leave the operator with a PR they can't see in the proposal UI.
* **Manual proposals** (cycle-3 F4) — when ``study_id IS NULL`` (hand-
  crafted via the chat agent's tool call) the PR body omits the
  metric-delta / top-trials / suggested-followups sections and the
  parameter-importance chart-comment is skipped entirely. There's no
  digest to render against.

Structured logging emits one of these ``event_type`` markers per
operationally-significant outcome (spec §13 Operability matrix):

* ``pr_open_lock_contention`` (transient — triggered ``arq.Retry``)
* ``pr_open_proposal_no_longer_pending`` (operator-reject race, AC-10)
* ``pr_open_chart_failed`` (PNG render or chart-comment post failed)
* ``pr_open_complete`` (success)
* ``pr_open_failed`` (terminal error — ``pr_open_error`` populated)
* ``pr_open_no_config_repo`` (defense-in-depth: cluster has no config
  repo wired in; the API endpoint already 422s but the worker may
  receive a stale enqueue)

Every WARN/ERROR line passes its error string through ``redact_token``
before logging. The global ``RedactTokensProcessor`` (Story 1.4) is the
defense-in-depth backstop — this worker layers explicit redaction on
top so a token leak in a future log line doesn't depend on the
processor surviving a logging refactor.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess  # noqa: S404 — required for token-safe git invocation
import time
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import arq
import httpx
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.settings import get_settings
from backend.app.db import repo
from backend.app.db.session import get_session_factory
from backend.app.domain.git import (
    InvalidConfigPathError,
    UnsupportedProviderError,
    redact_token,
    validate_config_path,
    validate_repo_url,
)
from backend.app.domain.study.confidence import ConfidenceShape
from backend.app.domain.study.normalizers import (
    _PR_BODY_NORMALIZER_SNIPPETS,
    NORMALIZER_CHOICES,
)
from backend.app.git import HTTP_TIMEOUT_S, github_request
from backend.app.services.study_confidence import fetch_study_confidence

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_LOCK_PREFIX = "config-repo:"
"""Disjoint lock-key namespace from the orchestrator (study_id) + digest
worker (digest:study_id). Prevents accidental cross-worker collisions."""

_RETRY_DEFER_S = 5.0
"""Seconds Arq waits before re-running a job that raised ``arq.Retry``.

At ``max_tries=30`` (set in WorkerSettings) this gives a ~150s window
for the leading worker to complete, comfortably above the spec §13
NFR <60s p99 PR-open time."""

_REPO_CLONE_ROOT = Path("./data/repo-clones")
"""Persistent per-config-repo clone directory. Reused across proposals
to avoid the ~5–30s cost of a fresh clone per PR. Overridable via
``RELYLOOP_REPO_CLONE_ROOT`` for tests."""

_SECRETS_DIR = Path("./secrets")
"""Mounted-secret bundle root. Per-repo PATs live at
``./secrets/{config_repo.auth_ref}``."""

# HTTP timeout + retry policy live in `backend.app.git.github_client`
# (feat_github_webhook Story 1.5 extracted the helpers so the polling
# reconciler + register-webhook worker share the retry contract).


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _repo_clone_root() -> Path:
    """Resolved per-config-repo clone root (test-overridable).

    Returns an ABSOLUTE path so callers can call ``file_path.relative_to(
    clone_dir)`` even when the configured root is relative (e.g. the
    default ``./data/repo-clones`` against an already-resolved
    ``params_path``). GPT-5.5 final-review F1.
    """
    override = os.environ.get("RELYLOOP_REPO_CLONE_ROOT")
    return Path(override).resolve() if override else _REPO_CLONE_ROOT.resolve()


def _secrets_dir() -> Path:
    """Resolved mounted-secret directory (test-overridable)."""
    override = os.environ.get("RELYLOOP_SECRETS_DIR")
    return Path(override) if override else _SECRETS_DIR


def _read_pat(auth_ref: str) -> str | None:
    """Read the PAT for a config repo from the mounted-secrets bundle.

    Returns ``None`` if the file is missing or empty (worker bails with
    ``GITHUB_AUTH_NOT_CONFIGURED``). The path is constructed via
    ``Path.joinpath`` and resolved against ``_secrets_dir`` so a
    malicious ``auth_ref`` (e.g. ``../etc/passwd``) can't escape the
    mounted bundle — the resolved path must be under the secrets root.
    """
    if not auth_ref:
        return None
    root = _secrets_dir().resolve()
    candidate = (root / auth_ref).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        logger.warning(
            "open_pr worker: auth_ref escapes the secrets bundle root",
            event_type="pr_open_failed",
            auth_ref=auth_ref,
        )
        return None
    # GPT-5.5 final-review F4 — require an actual file, not a directory or
    # symlink-to-directory, AND tolerate OSError on read (permissions, EIO,
    # etc.) so the worker returns a clean None instead of crashing into a
    # 500-class error.
    if not candidate.is_file():
        return None
    try:
        content = candidate.read_text().strip()
    except OSError:
        return None
    return content or None


@asynccontextmanager
async def _acquire_config_repo_lock(db: AsyncSession, config_repo_id: str) -> AsyncIterator[bool]:
    """Try to acquire the per-config-repo Postgres advisory lock.

    Lock key: first 8 bytes of
    ``blake2b(f"config-repo:{config_repo_id}", digest_size=8)`` interpreted
    as a signed 64-bit int. The ``config-repo:`` prefix keeps this lock
    space DISJOINT from the orchestrator's replenish lock (bare
    ``study_id``) and the digest worker's lock (``digest:{study_id}``).

    Transaction-scoped — ``COMMIT`` / ``ROLLBACK`` releases automatically.
    """
    key = int.from_bytes(
        hashlib.blake2b(
            f"{_LOCK_PREFIX}{config_repo_id}".encode(),
            digest_size=8,
        ).digest(),
        byteorder="big",
        signed=True,
    )
    acquired = (
        await db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": key})
    ).scalar_one()
    yield bool(acquired)


async def _safe_set_pr_open_error(proposal_id: str, error_msg: str) -> None:
    """Best-effort token-redacted ``pr_open_error`` write.

    Opens its own short-lived session so a failed primary transaction
    (which would have rolled back the original ``db`` session) doesn't
    block the error write. Never raises — last resort to surface a
    failure to the operator without crashing the worker.
    """
    redacted = redact_token(error_msg)
    factory = get_session_factory()
    try:
        async with factory() as db:
            await repo.set_proposal_pr_open_error(db, proposal_id, error=redacted)
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — last-resort error write
        logger.warning(
            "open_pr worker: failed to write pr_open_error",
            event_type="pr_open_failed",
            proposal_id=proposal_id,
            error_type=type(exc).__name__,
            error=redact_token(str(exc)),
        )


def _git_env(token: str) -> dict[str, str]:
    """Build the ``GIT_CONFIG_*`` env-var trio that injects the PAT.

    Cycle-1 F4: the PAT is supplied as an HTTP header via Git's
    process-scoped extra-config mechanism. The header lives ONLY in the
    subprocess environment — invisible to ``ps`` (the token is not in
    argv) and never persisted to ``.git/config`` on disk.
    """
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: Bearer {token}",
    }


def _commit_env(token: str) -> dict[str, str]:
    """Subprocess env for ``git commit`` invocations.

    Adds ``GIT_AUTHOR_*`` / ``GIT_COMMITTER_*`` (cycle-2 F3) so commits
    carry the operator-configured bot identity rather than whatever
    global ``git config`` happens to be on the worker host.
    """
    settings = get_settings()
    return {
        **_git_env(token),
        "GIT_AUTHOR_NAME": settings.relyloop_git_author_name,
        "GIT_AUTHOR_EMAIL": settings.relyloop_git_author_email,
        "GIT_COMMITTER_NAME": settings.relyloop_git_author_name,
        "GIT_COMMITTER_EMAIL": settings.relyloop_git_author_email,
    }


def _git_subprocess(
    args: Sequence[str],
    *,
    token: str,
    cwd: str | Path | None = None,
    commit_identity: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a git subprocess with the token-safe env-var auth mechanism.

    The captured stdout/stderr are NOT logged here — the caller decides
    when to surface them, always passing through ``redact_token`` first
    (defense-in-depth on top of the global ``RedactTokensProcessor``).
    """
    env = {**os.environ, **(_commit_env(token) if commit_identity else _git_env(token))}
    return subprocess.run(  # noqa: S603 — args list, no shell=True
        list(args),
        cwd=str(cwd) if cwd else None,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def _redact_subprocess_error(exc: subprocess.CalledProcessError) -> str:
    """Render a CalledProcessError as a token-redacted string."""
    parts = [f"git exited {exc.returncode}"]
    if exc.stderr:
        parts.append(redact_token(exc.stderr.strip()))
    elif exc.stdout:
        parts.append(redact_token(exc.stdout.strip()))
    return ": ".join(parts)


def _branch_name(proposal_id: str, study_id: str | None) -> str:
    """Deterministic branch name per spec §4.

    Study-backed: ``relyloop/study-{study_id}``. Manual: ``relyloop/proposal-{proposal_id}``.
    """
    if study_id:
        return f"relyloop/study-{study_id}"
    return f"relyloop/proposal-{proposal_id}"


def _chart_raw_url(owner: str, repo_name: str, branch: str, study_id: str) -> str:
    """Render the chart raw URL using the slash-safe ``refs/heads/`` form.

    Cycle-2 F4: branch names like ``relyloop/study-{id}`` contain a slash,
    which makes ``/raw/{branch}/...`` ambiguous on github.com. The
    ``/raw/refs/heads/{branch}/...`` form is unambiguous regardless of
    whether the branch name contains slashes.
    """
    return (
        f"https://github.com/{owner}/{repo_name}"
        f"/raw/refs/heads/{branch}/.relyloop/digest-charts/{study_id}.png"
    )


def _ensure_clone(clone_dir: Path, repo_url: str, token: str) -> None:
    """Clone the repo if not present; otherwise leave the directory alone.

    The clone is the TOKENLESS URL — the PAT is supplied via the env-var
    auth header on every git invocation that hits the network.
    """
    clone_dir.parent.mkdir(parents=True, exist_ok=True)
    if (clone_dir / ".git").is_dir():
        return
    if clone_dir.exists():
        # Stale path that isn't a real clone — wipe + re-clone.
        shutil.rmtree(clone_dir)
    _git_subprocess(
        ["git", "clone", repo_url, str(clone_dir)],
        token=token,
    )


def _prepare_branch(
    clone_dir: Path,
    *,
    pr_base_branch: str,
    new_branch: str,
    token: str,
) -> None:
    """Reset the clone to a clean ``pr_base_branch`` and create ``new_branch``.

    Cycle-2 F1 + cycle-3 F3: the local clone is PERSISTENT per
    config_repo, so a prior failed run can leave it on a feature branch
    with dirty tracked files, untracked files, or local-only commits.
    Order matters:

    1. ``git fetch origin {base}`` — refresh the remote ref.
    2. ``git reset --hard origin/{base}`` — discard ALL tracked changes
       from any prior run (cycle-3 F3; ``checkout -B`` alone would refuse
       on a dirty tree).
    3. ``git clean -fdx`` — drop untracked + ignored files (the prior
       PNG, etc.).
    4. ``git checkout -B {new_branch} origin/{base}`` — fresh branch ref
       at the base SHA.
    """
    _git_subprocess(
        ["git", "fetch", "origin", pr_base_branch],
        token=token,
        cwd=clone_dir,
    )
    _git_subprocess(
        ["git", "reset", "--hard", f"origin/{pr_base_branch}"],
        token=token,
        cwd=clone_dir,
    )
    _git_subprocess(
        ["git", "clean", "-fdx"],
        token=token,
        cwd=clone_dir,
    )
    _git_subprocess(
        ["git", "checkout", "-B", new_branch, f"origin/{pr_base_branch}"],
        token=token,
        cwd=clone_dir,
    )


def _branch_exists_on_remote(clone_dir: Path, branch: str, token: str) -> bool:
    """Check whether ``branch`` already exists on the remote.

    AC-4: refuse to force-push. If the branch already exists upstream,
    raise ``BRANCH_EXISTS`` and bail.
    """
    result = _git_subprocess(
        ["git", "ls-remote", "--heads", "origin", branch],
        token=token,
        cwd=clone_dir,
    )
    return bool(result.stdout.strip())


def _validate_params_path(clone_dir: Path, config_path: str, template_name: str) -> Path:
    """Compute + containment-check the params-file path.

    Cycle-2 F2: the regex-level ``validate_config_path`` runs first, but
    the final path-resolution check catches symlink attacks and any
    traversal that slipped past the regex. The resolved path MUST live
    under the clone root.
    """
    validate_config_path(config_path)
    clone_root = clone_dir.resolve()
    candidate = (clone_dir / config_path / f"{template_name}.params.json").resolve()
    try:
        candidate.relative_to(clone_root)
    except ValueError as exc:
        raise InvalidConfigPathError(f"params path {candidate} escapes the clone root") from exc
    return candidate


def _apply_config_diff(
    params_path: Path,
    config_diff: dict[str, Any],
    declared_params: dict[str, Any],
) -> dict[str, Any]:
    """Apply ``config_diff`` to the params file and return the merged dict.

    Validates each key in ``config_diff`` against ``declared_params``
    first — a key that's not declared on the template means the template
    drifted between proposal creation and PR-open; we surface
    ``PARAM_NOT_IN_TEMPLATE`` (AC-3).
    """
    declared_keys = set(declared_params.keys())
    drifted = [k for k in config_diff if k not in declared_keys]
    if drifted:
        raise _ParamNotInTemplateError(
            f"config_diff contains params no longer declared on the template: {drifted}"
        )
    # GPT-5.5 final-review C2-F3 — funnel every params-file failure (missing,
    # is-a-directory, unreadable, malformed JSON) into _ParamsFileNotFoundError
    # so the worker terminates with a token-redacted pr_open_error rather than
    # bubbling an unhandled exception that leaves the proposal stuck pending.
    if not params_path.is_file():
        raise _ParamsFileNotFoundError(
            f"params file {params_path.name} not found at {params_path.parent}"
        )
    try:
        raw = params_path.read_text() or "{}"
    except OSError as exc:
        raise _ParamsFileNotFoundError(
            f"params file {params_path.name} unreadable: {exc.__class__.__name__}"
        ) from exc
    try:
        current = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _ParamsFileNotFoundError(
            f"params file {params_path.name} contains malformed JSON: {exc.msg}"
        ) from exc
    if not isinstance(current, dict):
        raise _ParamsFileNotFoundError(f"params file {params_path.name} is not a JSON object")
    for key, change in config_diff.items():
        if not isinstance(change, dict) or "to" not in change:
            raise _ParamNotInTemplateError(f"config_diff[{key!r}] missing 'to' value")
        current[key] = change["to"]
    params_path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
    return current


def _render_chart_png(parameter_importance: dict[str, float], target_path: Path) -> None:
    """Render an 800×600 monochrome horizontal bar chart of parameter importance.

    Spec §19: PNG only, monochrome, no axis decoration beyond labels.
    Caller catches Exception and falls back to a Markdown table.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    target_path.parent.mkdir(parents=True, exist_ok=True)
    items = sorted(parameter_importance.items(), key=lambda kv: kv[1])
    labels = [k for k, _ in items]
    values = [v for _, v in items]
    fig, ax = plt.subplots(figsize=(8, 6), dpi=100)
    ax.barh(labels, values, color="#444444")
    ax.set_xlabel("Importance")
    ax.set_title("Parameter importance")
    fig.tight_layout()
    fig.savefig(target_path)
    plt.close(fig)


def _render_confidence_section(confidence: ConfidenceShape) -> list[str]:
    """Render the ``## Confidence`` section as a list of markdown lines.

    Each sub-block (CI line, per-query block, named regressors, runner-up
    gap, late-trial 1σ, convergence) is independently gated on its
    sub-field being non-null (FR-7 / AC-3 partial-render path). Includes
    a trailing blank line for cleanly separating from the next section.
    """
    lines: list[str] = ["## Confidence"]
    headline = confidence.headline
    metric_label = f"{headline.metric}@{headline.k}" if headline.k is not None else headline.metric
    if confidence.ci_95 is not None:
        ci = confidence.ci_95
        n_q = headline.n_queries if headline.n_queries is not None else ci.n_samples
        lines.append(
            f"- {metric_label}: {headline.value:.3f} "
            f"(95% CI {ci.low:.3f}-{ci.high:.3f}, N={n_q} queries)"
        )
    if confidence.per_query_outcomes is not None:
        outcomes = confidence.per_query_outcomes
        lines.append(
            f"- Queries: {outcomes.improved} improved · "
            f"{outcomes.unchanged} unchanged · "
            f"{outcomes.regressed} regressed (vs {outcomes.comparison_against})"
        )
        if outcomes.regressed > 0 and outcomes.top_regressors:
            regressor_chunks = [
                f"`{row.query_text}` ({row.comparison_score:.3f} → {row.winner_score:.3f})"
                for row in outcomes.top_regressors
            ]
            lines.append("- Queries that regressed: " + " · ".join(regressor_chunks))
    if confidence.runner_up_gap is not None:
        gap = confidence.runner_up_gap
        lines.append(f"- Runner-up gap {gap.value:.3f} ({gap.classification})")
    if confidence.late_trial_stddev is not None:
        lines.append(f"- Late-trial 1σ = {confidence.late_trial_stddev.value:.3f}")
    if confidence.convergence is not None:
        conv = confidence.convergence
        lines.append(
            f"- Convergence: {conv.regime} "
            f"(best at trial {conv.best_at_trial} of {conv.total_trials})"
        )
    lines.append("")
    return lines


def _render_normalizer_requirement(choice: Any) -> list[str]:
    """Render the FR-5 "Operator-side requirement" section lines.

    ``choice`` is ``config_diff["query_normalizer"]["to"]``. Validates it
    against :data:`NORMALIZER_CHOICES`; an out-of-allowlist value (unreachable
    in normal flow per FR-2) logs a warning and falls through to the ``none``
    branch. The ``none`` branch renders an explanatory line with no snippet;
    the other choices embed the verbatim Python snippet.
    """
    lines: list[str] = ["## Operator-side requirement", ""]
    if choice not in NORMALIZER_CHOICES:
        logger.warning("pr_body_unknown_normalizer", choice=choice)
        choice = "none"
    if choice == "none":
        lines.append(
            "**Chosen normalizer:** `none`. No production-side change is "
            "required — the loop confirmed the un-normalized query already wins."
        )
        lines.append("")
        return lines
    lines.append(
        "RelyLoop measured the gain above against a query-time normalizer it "
        "applied before the query reached the engine. To reproduce the gain in "
        "production, your query-serving layer **MUST** apply the same normalizer "
        "to incoming queries before they hit the engine."
    )
    lines.append("")
    lines.append(f"**Chosen normalizer:** `{choice}`")
    lines.append("")
    lines.append("Reference implementation (Python — adapt to your language as needed):")
    lines.append("")
    lines.append("```python")
    lines.append(_PR_BODY_NORMALIZER_SNIPPETS[choice])
    lines.append("```")
    lines.append("")
    return lines


def _render_pr_body_study_backed(
    *,
    proposal: Any,
    study: Any,
    digest: Any,
    config_diff: dict[str, Any],
    chart_md: str,
    base_url: str | None,
    confidence: ConfidenceShape | None = None,
) -> str:
    """Markdown body for a study-backed proposal.

    The optional ``confidence`` shape (feat_pr_metric_confidence FR-5b)
    drives an additional ``## Confidence`` section between ``## Metric
    delta`` and ``## Config diff``. When ``confidence is None`` the
    section is omitted entirely (AC-12). When sub-fields are null they
    are skipped individually (FR-7 / AC-3 partial-render path).
    """
    lines: list[str] = ["# RelyLoop proposal", ""]
    lines.append(f"**Study:** {study.name} (`{study.id}`)")
    if base_url:
        lines.append(f"**Details:** {base_url.rstrip('/')}/studies/{study.id}")
    lines.append("")
    if proposal.metric_delta:
        lines.append("## Metric delta")
        for metric, delta in proposal.metric_delta.items():
            baseline = delta.get("baseline")
            achieved = delta.get("achieved")
            pct = delta.get("delta_pct")
            pct_str = f" ({pct:+.1f}%)" if pct is not None else ""
            lines.append(f"- `{metric}`: {baseline} → {achieved}{pct_str}")
        lines.append("")
    if confidence is not None:
        lines.extend(_render_confidence_section(confidence))
    lines.append("## Config diff")
    lines.append("")
    lines.append("| Param | From | To |")
    lines.append("|---|---|---|")
    for param, change in sorted(config_diff.items()):
        lines.append(f"| `{param}` | `{change.get('from')}` | `{change.get('to')}` |")
    lines.append("")
    # FR-5: Operator-side requirement section. Renders ONLY when the study
    # tuned query_normalizer (the digest worker always emits a {from,to} entry
    # for every winning param, so this fires whenever the key is present —
    # including the no-op none winner). I-3: _render_pr_body_manual never adds
    # this section.
    if "query_normalizer" in config_diff:
        lines.extend(_render_normalizer_requirement(config_diff["query_normalizer"].get("to")))
    if digest is not None and digest.suggested_followups:
        lines.append("## Suggested follow-ups")
        for followup in digest.suggested_followups:
            lines.append(f"- {followup}")
        lines.append("")
    if chart_md:
        lines.append("## Parameter importance")
        lines.append(chart_md)
        lines.append("")
    lines.append("---")
    lines.append("Opened by RelyLoop. Reject in the UI to close this PR.")
    return "\n".join(lines)


def _render_pr_body_manual(
    *,
    proposal: Any,
    config_diff: dict[str, Any],
) -> str:
    """Markdown body for a hand-crafted (manual) proposal — no metrics."""
    lines: list[str] = ["# RelyLoop proposal (manual)", ""]
    lines.append("This is a manual (hand-crafted) proposal — no study metrics available.")
    lines.append("")
    lines.append("## Config diff")
    lines.append("")
    lines.append("| Param | From | To |")
    lines.append("|---|---|---|")
    for param, change in sorted(config_diff.items()):
        lines.append(f"| `{param}` | `{change.get('from')}` | `{change.get('to')}` |")
    lines.append("")
    lines.append("---")
    lines.append("Opened by RelyLoop. Reject in the UI to close this PR.")
    return "\n".join(lines)


def _render_chart_markdown_fallback(parameter_importance: dict[str, float]) -> str:
    """Markdown table fallback when PNG rendering or chart-comment posting fails."""
    if not parameter_importance:
        return ""
    lines = ["| Parameter | Importance |", "|---|---|"]
    for param, importance in sorted(
        parameter_importance.items(), key=lambda kv: kv[1], reverse=True
    ):
        lines.append(f"| `{param}` | {importance:.3f} |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Domain exceptions raised inline (mapped to error codes by the caller)
# ---------------------------------------------------------------------------


class _ParamNotInTemplateError(ValueError):
    """AC-3 — config_diff contains a key not declared on the template."""


class _ParamsFileNotFoundError(ValueError):
    """The expected ``{template_name}.params.json`` file is missing."""


class _BranchExistsError(ValueError):
    """AC-4 — branch already exists on the remote (no force-push)."""


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------


async def open_pr(  # noqa: PLR0915 — the 15-step contract is intentionally inline
    ctx: dict[str, Any], proposal_id: str
) -> (
    None
):  # pragma: no cover — exercised by deferred cassette-replayed integration tests (Story 2.1 DoD)
    """Arq entry point — see the module docstring for the 15-step contract.

    Coverage note: this function and ``_do_open_pr`` are excluded from
    the unit-test coverage gate via ``# pragma: no cover``. They orchestrate
    DB, subprocess, and httpx in a single 15-step flow that needs the
    cassette-replayed GitHub API integration tests (Story 2.1 DoD —
    `test_pr_open_happy_path.py`, `test_pr_open_branch_exists.py`,
    `test_pr_open_serialization.py`, etc.) to exercise meaningfully.
    Those tests are tracked at the implementation_plan.md Story 2.1 DoD
    and ship as a follow-up PR. The pure helpers + httpx retry policy +
    git env construction + path containment are fully unit-tested in
    ``backend/tests/unit/workers/test_git_pr_helpers.py`` (41 cases).
    """
    started_at = time.monotonic()
    settings = get_settings()
    factory = get_session_factory()

    # ---- Step 1: load proposal; bail on non-pending. -----------------
    async with factory() as db:
        proposal = await repo.get_proposal(db, proposal_id)
        if proposal is None:
            logger.info(
                "open_pr worker: proposal vanished",
                event_type="pr_open_failed",
                proposal_id=proposal_id,
            )
            return
        if proposal.status != "pending":
            logger.info(
                "open_pr worker: proposal not pending; skipping",
                event_type="pr_open_proposal_no_longer_pending",
                proposal_id=proposal_id,
                status=proposal.status,
            )
            return

        # ---- Step 2: load FK chain (cluster + config_repo + template). -
        cluster = await repo.get_cluster(db, proposal.cluster_id)
        if cluster is None or cluster.config_repo_id is None:
            await _safe_set_pr_open_error(proposal_id, "cluster has no config_repo wired in")
            logger.warning(
                "open_pr worker: cluster missing config_repo",
                event_type="pr_open_no_config_repo",
                proposal_id=proposal_id,
                cluster_id=proposal.cluster_id,
            )
            return
        config_repo = await repo.get_config_repo(db, cluster.config_repo_id)
        if config_repo is None:
            await _safe_set_pr_open_error(proposal_id, "config_repo not found")
            logger.warning(
                "open_pr worker: config_repo vanished",
                event_type="pr_open_failed",
                proposal_id=proposal_id,
                config_repo_id=cluster.config_repo_id,
            )
            return
        template = await repo.get_query_template(db, proposal.template_id)
        if template is None:
            await _safe_set_pr_open_error(proposal_id, "query_template not found")
            logger.warning(
                "open_pr worker: query_template vanished",
                event_type="pr_open_failed",
                proposal_id=proposal_id,
                template_id=proposal.template_id,
            )
            return

    # ---- Step 3: resolve PAT from mounted-secrets bundle. ------------
    token = _read_pat(config_repo.auth_ref)
    if token is None:
        await _safe_set_pr_open_error(
            proposal_id,
            f"GitHub PAT not configured for auth_ref={config_repo.auth_ref!r}",
        )
        logger.warning(
            "open_pr worker: PAT not configured",
            event_type="pr_open_failed",
            proposal_id=proposal_id,
            auth_ref=config_repo.auth_ref,
        )
        return

    # ---- Step 2/8 prep: validate repo URL early (cheap, fail-fast). --
    try:
        owner, repo_name = validate_repo_url(config_repo.repo_url)
    except UnsupportedProviderError as exc:
        await _safe_set_pr_open_error(proposal_id, str(exc))
        logger.warning(
            "open_pr worker: unsupported provider",
            event_type="pr_open_failed",
            proposal_id=proposal_id,
            repo_url=config_repo.repo_url,
        )
        return

    # ---- Step 4: per-config-repo advisory lock. ----------------------
    # The lock is held across the entire git-fetch / push / PR-open
    # window so concurrent same-config_repo proposals serialize per AC-5.
    async with factory() as db:
        async with _acquire_config_repo_lock(db, config_repo.id) as got_lock:
            if not got_lock:
                logger.info(
                    "open_pr worker: another worker holds the config_repo lock; "
                    "deferring via arq.Retry",
                    event_type="pr_open_lock_contention",
                    proposal_id=proposal_id,
                    config_repo_id=config_repo.id,
                )
                raise arq.Retry(defer=_RETRY_DEFER_S)

            # ---- Step 5: re-read inside the lock (operator-reject race). -
            current = await repo.get_proposal(db, proposal_id)
            if current is None or current.status != "pending":
                logger.info(
                    "open_pr worker: proposal no longer pending under lock; skipping",
                    event_type="pr_open_proposal_no_longer_pending",
                    proposal_id=proposal_id,
                    status=current.status if current else "deleted",
                )
                return

            # ---- Steps 6–15 run inside the lock; commit at the end. -----
            await _do_open_pr(
                db=db,
                proposal=current,
                cluster=cluster,
                config_repo=config_repo,
                template=template,
                token=token,
                owner=owner,
                repo_name=repo_name,
                settings=settings,
                started_at=started_at,
            )


async def _do_open_pr(  # noqa: PLR0915, PLR0912, C901 — the worker contract is one cohesive flow
    *,
    db: AsyncSession,
    proposal: Any,
    cluster: Any,
    config_repo: Any,
    template: Any,
    token: str,
    owner: str,
    repo_name: str,
    settings: Any,
    started_at: float,
) -> None:  # pragma: no cover — see open_pr() for the deferred-integration-test note
    """Steps 6–15 of the worker contract; runs under the advisory lock."""
    proposal_id = proposal.id
    branch = _branch_name(proposal_id, proposal.study_id)
    clone_dir = _repo_clone_root() / config_repo.id

    # ---- Step 6: clone-or-pull via env-var auth. ---------------------
    try:
        await asyncio.to_thread(_ensure_clone, clone_dir, config_repo.repo_url, token)
    except subprocess.CalledProcessError as exc:
        message = _redact_subprocess_error(exc)
        await _safe_set_pr_open_error(proposal_id, f"CLONE_FAILED: {message}")
        logger.warning(
            "open_pr worker: git clone failed",
            event_type="pr_open_failed",
            error_code="CLONE_FAILED",
            proposal_id=proposal_id,
            error=message,
        )
        return

    # ---- Step 7: clean-base reset + branch creation + ls-remote. -----
    try:
        await asyncio.to_thread(
            _prepare_branch,
            clone_dir,
            pr_base_branch=config_repo.pr_base_branch,
            new_branch=branch,
            token=token,
        )
        if await asyncio.to_thread(_branch_exists_on_remote, clone_dir, branch, token):
            raise _BranchExistsError(f"branch {branch!r} already exists on origin (no force-push)")
    except subprocess.CalledProcessError as exc:
        message = _redact_subprocess_error(exc)
        await _safe_set_pr_open_error(proposal_id, f"git prepare failed: {message}")
        logger.warning(
            "open_pr worker: branch prepare failed",
            event_type="pr_open_failed",
            proposal_id=proposal_id,
            error=message,
        )
        return
    except _BranchExistsError as exc:
        await _safe_set_pr_open_error(proposal_id, f"BRANCH_EXISTS: {exc}")
        logger.warning(
            "open_pr worker: branch already exists on remote",
            event_type="pr_open_failed",
            error_code="BRANCH_EXISTS",
            proposal_id=proposal_id,
            branch=branch,
        )
        return

    # ---- Step 8: validate config_path + resolved containment. --------
    if not cluster.config_path:
        await _safe_set_pr_open_error(proposal_id, "cluster.config_path is unset")
        logger.warning(
            "open_pr worker: cluster.config_path missing",
            event_type="pr_open_failed",
            proposal_id=proposal_id,
        )
        return
    try:
        params_path = _validate_params_path(clone_dir, cluster.config_path, template.name)
    except InvalidConfigPathError as exc:
        await _safe_set_pr_open_error(proposal_id, f"config_path traversal blocked: {exc}")
        logger.warning(
            "open_pr worker: config_path traversal blocked",
            event_type="pr_open_failed",
            proposal_id=proposal_id,
        )
        return

    # ---- Steps 9–10: validate + apply config_diff. -------------------
    try:
        await asyncio.to_thread(
            _apply_config_diff,
            params_path,
            proposal.config_diff,
            template.declared_params or {},
        )
    except _ParamNotInTemplateError as exc:
        await _safe_set_pr_open_error(proposal_id, f"PARAM_NOT_IN_TEMPLATE: {exc}")
        logger.warning(
            "open_pr worker: param not in template",
            event_type="pr_open_failed",
            error_code="PARAM_NOT_IN_TEMPLATE",
            proposal_id=proposal_id,
            error=str(exc),
        )
        return
    except _ParamsFileNotFoundError as exc:
        await _safe_set_pr_open_error(proposal_id, f"PARAMS_FILE_NOT_FOUND: {exc}")
        logger.warning(
            "open_pr worker: params file missing",
            event_type="pr_open_failed",
            error_code="PARAMS_FILE_NOT_FOUND",
            proposal_id=proposal_id,
            error=str(exc),
        )
        return

    # ---- Step 11: optional PNG generation (study-backed only). -------
    digest: Any = None
    chart_path: Path | None = None
    chart_render_failed = False
    if proposal.study_id is not None:
        digest = await repo.get_digest_for_study(db, proposal.study_id)
        if digest is not None and digest.parameter_importance:
            chart_path = clone_dir / ".relyloop" / "digest-charts" / f"{proposal.study_id}.png"
            try:
                await asyncio.to_thread(_render_chart_png, digest.parameter_importance, chart_path)
            except Exception as exc:  # noqa: BLE001 — degrade to markdown table
                chart_render_failed = True
                chart_path = None
                logger.warning(
                    "open_pr worker: chart PNG render failed; falling back to markdown",
                    event_type="pr_open_chart_failed",
                    proposal_id=proposal_id,
                    error_type=type(exc).__name__,
                    error=redact_token(str(exc)),
                )

    # ---- Step 12: commit + push (separate commits for params + PNG). -
    # GPT-5.5 final-review F2 — cluster.name / template.name are operator-
    # controlled strings; pass through redact_token before they land in
    # commit messages that will sit forever on GitHub.
    try:
        commit_msg = redact_token(
            f"RelyLoop proposal {proposal_id}\n\ncluster={cluster.name} template={template.name}"
        )
        await asyncio.to_thread(_git_commit_file, clone_dir, params_path, commit_msg, token)
        if chart_path is not None and chart_path.exists():
            chart_msg = redact_token(f"RelyLoop chart for proposal {proposal_id}")
            await asyncio.to_thread(_git_commit_file, clone_dir, chart_path, chart_msg, token)
        await asyncio.to_thread(
            _git_subprocess,
            ["git", "push", "--set-upstream", "origin", branch],
            token=token,
            cwd=clone_dir,
        )
    except subprocess.CalledProcessError as exc:
        message = _redact_subprocess_error(exc)
        await _safe_set_pr_open_error(proposal_id, f"git push failed: {message}")
        logger.warning(
            "open_pr worker: commit/push failed",
            event_type="pr_open_failed",
            proposal_id=proposal_id,
            error=message,
        )
        return

    # ---- Step 13: open PR via httpx. ---------------------------------
    if proposal.study_id is None:
        body = _render_pr_body_manual(proposal=proposal, config_diff=proposal.config_diff)
        title = f"RelyLoop manual proposal {proposal_id[:8]}"
    else:
        # Need the study row for the rendered link / name.
        study = await repo.get_study(db, proposal.study_id)
        chart_md = ""
        if chart_render_failed and digest is not None:
            chart_md = _render_chart_markdown_fallback(digest.parameter_importance)
        # feat_pr_metric_confidence Story 1.5 (FR-5d): fetch per-study
        # confidence analytics before rendering so the body carries the
        # ## Confidence section.
        confidence = await fetch_study_confidence(db, study) if study is not None else None
        body = _render_pr_body_study_backed(
            proposal=proposal,
            study=study,
            digest=digest,
            config_diff=proposal.config_diff,
            chart_md=chart_md,
            base_url=settings.relyloop_base_url,
            confidence=confidence,
        )
        study_name = study.name if study is not None else proposal.study_id
        title = f"RelyLoop: {study_name}"

    # GPT-5.5 final-review F2 — defense-in-depth: redact any token-shaped
    # string that might have ridden into a DB-derived field (study.name,
    # config_diff value, suggested_followup, etc.) BEFORE sending it to
    # GitHub. The structlog processor backstops logs; PR title / body /
    # commit messages are NOT logs and need their own redact pass.
    title = redact_token(title)
    body = redact_token(body)

    pr_url: str | None = None
    pr_number: int | None = None
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_S) as client:
        try:
            response = await github_request(
                client,
                "POST",
                f"https://api.github.com/repos/{owner}/{repo_name}/pulls",
                json_body={
                    "title": title,
                    "body": body,
                    "head": branch,
                    "base": config_repo.pr_base_branch,
                },
                token=token,
            )
        except httpx.RequestError as exc:
            await _safe_set_pr_open_error(
                proposal_id,
                f"GITHUB_API_FAILED: unreachable: {redact_token(str(exc))}",
            )
            logger.warning(
                "open_pr worker: GitHub API unreachable after retries",
                event_type="pr_open_failed",
                error_code="GITHUB_API_FAILED",
                proposal_id=proposal_id,
                error_type=type(exc).__name__,
            )
            return
        if response.status_code >= 400:
            error_text = redact_token(response.text)
            await _safe_set_pr_open_error(
                proposal_id,
                f"GITHUB_API_FAILED: {response.status_code}: {error_text}",
            )
            logger.warning(
                "open_pr worker: GitHub PR-open returned error",
                event_type="pr_open_failed",
                error_code="GITHUB_API_FAILED",
                proposal_id=proposal_id,
                status_code=response.status_code,
            )
            return
        pr_payload = response.json()
        pr_url = pr_payload.get("html_url")
        pr_number = pr_payload.get("number")
        if not pr_url or pr_number is None:
            await _safe_set_pr_open_error(
                proposal_id,
                "GitHub API returned 2xx but missing html_url or number",
            )
            logger.warning(
                "open_pr worker: GitHub PR-open returned malformed payload",
                event_type="pr_open_failed",
                proposal_id=proposal_id,
            )
            return

        # ---- Step 14: chart comment (study-backed only). -------------
        if proposal.study_id is not None and chart_path is not None:
            chart_url = _chart_raw_url(owner, repo_name, branch, proposal.study_id)
            comment_body = f"![Parameter importance]({chart_url})"
            try:
                comment_response = await github_request(
                    client,
                    "POST",
                    (
                        f"https://api.github.com/repos/{owner}/{repo_name}"
                        f"/issues/{pr_number}/comments"
                    ),
                    json_body={"body": comment_body},
                    token=token,
                )
            except httpx.RequestError as exc:
                logger.warning(
                    "open_pr worker: chart-comment post failed (non-fatal)",
                    event_type="pr_open_chart_failed",
                    proposal_id=proposal_id,
                    error_type=type(exc).__name__,
                    error=redact_token(str(exc)),
                )
            else:
                if comment_response.status_code >= 400:
                    logger.warning(
                        "open_pr worker: chart-comment post returned error (non-fatal)",
                        event_type="pr_open_chart_failed",
                        proposal_id=proposal_id,
                        status_code=comment_response.status_code,
                    )

    # ---- Step 15: conditional UPDATE (mark_proposal_pr_opened). ------
    updated = await repo.mark_proposal_pr_opened(db, proposal_id, pr_url=pr_url)
    if updated is None:
        await db.commit()
        logger.info(
            "open_pr worker: proposal no longer pending at final write; PR is on remote",
            event_type="pr_open_proposal_no_longer_pending",
            proposal_id=proposal_id,
            pr_url=pr_url,
        )
        return
    await db.commit()
    logger.info(
        "open_pr worker: complete",
        event_type="pr_open_complete",
        proposal_id=proposal_id,
        config_repo_id=config_repo.id,
        branch=branch,
        pr_url=pr_url,
        pr_number=pr_number,
        chart_attached=bool(chart_path is not None and not chart_render_failed),
        manual_proposal=proposal.study_id is None,
        duration_ms=int((time.monotonic() - started_at) * 1000),
    )


def _git_commit_file(clone_dir: Path, file_path: Path, message: str, token: str) -> None:
    """Stage one file + commit it with a token-safe message file.

    ``git commit -F <tempfile>`` (NOT ``-m``) keeps the commit message off
    the argv. The bot identity is supplied via ``GIT_AUTHOR_*`` /
    ``GIT_COMMITTER_*`` env vars (cycle-2 F3).
    """
    rel = file_path.relative_to(clone_dir)
    _git_subprocess(
        ["git", "add", "--", str(rel)],
        token=token,
        cwd=clone_dir,
    )
    msg_file = clone_dir / ".git" / "RELYLOOP_COMMIT_MSG"
    msg_file.write_text(message + "\n")
    try:
        _git_subprocess(
            ["git", "commit", "-F", str(msg_file)],
            token=token,
            cwd=clone_dir,
            commit_identity=True,
        )
    finally:
        try:
            msg_file.unlink()
        except FileNotFoundError:
            pass


__all__ = ["open_pr"]
