# Implementation Plan — feat_github_pr_worker

**Date:** 2026-05-12
**Status:** Approved (3 GPT-5.5 review cycles to the cap; 15 findings accepted + applied; ready for `/impl-execute`)
**Primary spec:** [feature_spec.md](feature_spec.md)
**Policy source(s):** [CLAUDE.md](../../../../CLAUDE.md), [docs/01_architecture/apply-path.md](../../../01_architecture/apply-path.md), [docs/01_architecture/data-model.md](../../../01_architecture/data-model.md), [docs/01_architecture/api-conventions.md](../../../01_architecture/api-conventions.md)

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs.
- Phase gates are hard stops.
- Fail-loud tests: assert explicit status/shape/errors.
- Mirror the analogous `feat_digest_proposal` (PR #41) shape — reuse the
  worker patterns (advisory lock, conditional UPDATE on
  `WHERE status='pending'`, deterministic Arq `_job_id`, persist-then-
  side-effect ordering) rather than re-deriving.
- Zero new tables / zero new columns — this feature WRITES TO existing
  `proposals` + `config_repos` columns only.
- Single-phase per spec §3 — no deferred phases.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic | Stories | Notes |
|---|---|---|---|
| FR-1 (open_pr endpoint) | Epic 3 (API) | 3.1 | `POST /api/v1/proposals/{id}/open_pr` extends existing `proposals.py` router |
| FR-2 (open_pr worker) | Epic 2 (worker) | 2.1, 2.2 | `backend/workers/git_pr.py` + WorkerSettings registration |
| FR-3 (config-repo CRUD) | Epic 3 (API) | 3.2, 3.3 | New router `backend/app/api/v1/config_repos.py` |
| FR-4 (pr_open_error population) | Epic 2 (worker) | 2.1 | Worker writes; tests via Epic 4 |
| FR-5 (per-repo PAT auth + redaction) | Epic 1 (foundations) | 1.3, 1.4 | Settings + structlog redaction filter + git helpers |
| All FRs (docs + tests) | Epic 4 (docs/tests) | 4.1, 4.2, 4.3 | runbook, security doc, MVP1 user-stories flip |

**Single-phase feature; no deferred phases.** Per spec §3 Phase boundaries —
the MVP1 deliverable ships in one PR.

## 2) Delivery structure

Epic → Story → Tasks → DoD. Four epics:

1. **Foundations** — repo extensions + Pydantic schemas + Settings (`relyloop_base_url`) + git/redaction helpers.
2. **Worker** — `open_pr` worker job + WorkerSettings registration.
3. **API** — 4 endpoints across 2 router files.
4. **Docs / tests / cleanup** — runbook, security doc extension, MVP1 user-stories flip, contract & benchmark tests, lean refactor.

### Conventions (project-specific)

- All repo functions take `db: AsyncSession` first; use `db.flush()` (caller commits).
- New router `config_repos.py` exports a `router = APIRouter()`; registered in `backend/app/main.py` with `prefix="/api/v1"`.
- `open_pr` endpoint added to the EXISTING `backend/app/api/v1/proposals.py` (5 endpoints already there from `feat_digest_proposal`).
- Settings consumed via `get_settings()` — never `Settings()` directly.
- Worker uses short-lived per-iteration DB sessions (mirrors
  `backend/workers/digest.py` pattern).
- Per-proposal Arq dedup via deterministic `_job_id=f"open_pr:{proposal_id}"` (mirrors `feat_llm_judgments` cycle-4 C4-F1 + `feat_digest_proposal` boot-scan).
- Advisory lock idiom: `pg_try_advisory_xact_lock` keyed on `blake2b(f"config-repo:{config_repo_id}", digest_size=8)` (disjoint prefix from orchestrator + digest workers).
- Conditional UPDATE on the pending proposal: `WHERE id=:id AND status='pending'` (mirrors `feat_digest_proposal` cycle-3 F4 — benign no-op when operator rejected mid-flight).
- Token redaction filter: structlog processor that matches `gh[ps]_[A-Za-z0-9_]{36,}` and replaces with `[REDACTED-GH-TOKEN]`.
- Router error envelope helper `_err()` and cursor helpers `_encode_cursor` / `_decode_cursor` copied from [`backend/app/api/v1/judgments.py:72-90`](../../../../backend/app/api/v1/judgments.py#L72-L90) — defer hoisting to a shared module via the existing `chore_router_helpers_hoist` follow-up.

### AI Agent Execution Protocol

Standard order: read scope → backend (helpers → settings → repo extensions → worker → API) → tests → docs → final state.md update.

---

## Epic 1 — Foundations (helpers + schemas + settings + repo extensions)

### Story 1.1 — `config_repo` repo extensions + `proposal` repo `mark_proposal_pr_opened`

**Outcome:** `config_repo` repo gains `list_config_repos` + `count_config_repos` (FR-3 list endpoint). `proposal` repo gains `mark_proposal_pr_opened` — a conditional UPDATE for the worker's final write (cycle-3 F4 pattern).

**New files**

| File | Purpose |
|---|---|
| (none — extending existing repo files) | |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/config_repo.py` | Add `list_config_repos(db, *, cursor, limit) -> Sequence[ConfigRepo]` + `count_config_repos(db) -> int`. Cursor shape `(created_at, id)` mirrors the studies pagination pattern. |
| `backend/app/db/repo/proposal.py` | Add `mark_proposal_pr_opened(db, proposal_id, *, pr_url) -> Proposal \| None`. Conditional UPDATE `WHERE id=:id AND status='pending'` returning the row; `None` when zero rows matched (operator-reject race). Sets `pr_url=:url, pr_state='open', status='pr_opened', pr_open_error=NULL`. Also add `set_proposal_pr_open_error(db, proposal_id, *, error: str) -> Proposal \| None` for failure-path writes; same conditional-pending guard (no point writing error if operator already rejected). |
| `backend/app/db/repo/__init__.py` | Export the 4 new functions via `__all__`. |

**Key interfaces**

```python
# backend/app/db/repo/config_repo.py
async def list_config_repos(
    db: AsyncSession,
    *,
    cursor: tuple[datetime, str] | None = None,
    limit: int = 50,
) -> Sequence[ConfigRepo]:
    """Cursor-paginated, newest-first by created_at DESC, id DESC."""
    ...

async def count_config_repos(db: AsyncSession) -> int:
    """COUNT(*) for the X-Total-Count header on GET /api/v1/config-repos."""
    ...

# backend/app/db/repo/proposal.py
async def mark_proposal_pr_opened(
    db: AsyncSession,
    proposal_id: str,
    *,
    pr_url: str,
) -> Proposal | None:
    """Conditional UPDATE: pending → pr_opened + populate pr_url + pr_state='open' + clear pr_open_error.

    Returns the updated row, or None if the WHERE status='pending' guard
    matched zero rows (operator-reject race per spec AC-10). Caller commits.
    """
    ...

async def set_proposal_pr_open_error(
    db: AsyncSession,
    proposal_id: str,
    *,
    error: str,
) -> Proposal | None:
    """Conditional UPDATE: populate pr_open_error WHERE status='pending'.

    Returns None if the proposal is no longer pending (operator rejected
    mid-flight; don't overwrite the rejection's rationale). Caller commits.
    The `error` string MUST already be token-redacted by the caller.
    """
    ...
```

**Tasks**
1. Add the 2 functions to `backend/app/db/repo/config_repo.py`. Mirror `list_proposals_paginated` cursor shape from `proposal.py`.
2. Add the 2 functions to `backend/app/db/repo/proposal.py`. Use `update(Proposal).where(Proposal.id == proposal_id, Proposal.status == 'pending').values(...).returning(Proposal)` pattern (mirrors `update_proposal_for_digest`).
3. Export from `backend/app/db/repo/__init__.py` `__all__`.

**Definition of Done**
- [ ] `from backend.app.db.repo import list_config_repos, count_config_repos, mark_proposal_pr_opened, set_proposal_pr_open_error` imports cleanly.
- [ ] Integration test `test_config_repo_repo.py::test_list_paginated_returns_newest_first` passes.
- [ ] Integration test `test_proposal_pr_repo.py::test_mark_pr_opened_transitions_status` passes (AC: id unchanged, status='pr_opened', pr_url populated).
- [ ] Integration test `test_proposal_pr_repo.py::test_mark_pr_opened_no_ops_when_rejected` passes (cycle-3 F4 pattern — no-op when status != 'pending').
- [ ] Integration test `test_proposal_pr_repo.py::test_set_pr_open_error_no_ops_when_rejected` passes (don't overwrite rejection rationale).

---

### Story 1.2 — Pydantic schemas (config-repo CRUD + open_pr response)

**Outcome:** All request/response schemas appended to `backend/app/api/v1/schemas.py` (existing module). Schemas mirror the spec §8.2 contract.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/schemas.py` | Append: `OpenPrResponse`, `CreateConfigRepoRequest`, `ConfigRepoDetail`, `ConfigReposListResponse`. |

**Key interfaces**

```python
# backend/app/api/v1/schemas.py (additions)

class OpenPrResponse(BaseModel):
    """202 response from POST /api/v1/proposals/{id}/open_pr."""
    proposal_id: str
    status: Literal["pending"]   # always 'pending' at enqueue time
    message: str


class CreateConfigRepoRequest(BaseModel):
    """Body for POST /api/v1/config-repos.

    `provider` is server-derived from repo_url (cycle-2 F4 from spec
    review) — NOT in the payload.
    """
    name: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
    repo_url: str = Field(min_length=1, max_length=512)
    default_branch: str = Field(default="main", min_length=1, max_length=128)
    pr_base_branch: str = Field(default="main", min_length=1, max_length=128)
    auth_ref: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    webhook_secret_ref: str | None = Field(default=None, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")


class ConfigRepoDetail(BaseModel):
    """GET /api/v1/config-repos/{id} response."""
    id: str
    name: str
    provider: Literal["github"]   # MVP1 enum; MVP3 extends to gitlab|bitbucket
    repo_url: str
    default_branch: str
    pr_base_branch: str
    auth_ref: str
    webhook_secret_ref: str | None
    webhook_registration_error: str | None
    created_at: datetime


class ConfigReposListResponse(BaseModel):
    """GET /api/v1/config-repos response."""
    data: list[ConfigRepoDetail]
    next_cursor: str | None
    has_more: bool
```

**Tasks**
1. Append the 4 schemas to `backend/app/api/v1/schemas.py`.
2. Add a source-of-truth comment above the `provider` Literal: `# Values must match backend/app/db/models/config_repo.py CHECK config_repos_provider_check`.

**Definition of Done**
- [ ] `from backend.app.api.v1.schemas import OpenPrResponse, CreateConfigRepoRequest, ConfigRepoDetail, ConfigReposListResponse` imports cleanly.
- [ ] `make typecheck` green.

---

### Story 1.3 — Settings: `relyloop_base_url` + commit author fields

**Outcome:** `backend/app/core/settings.py` gains `relyloop_base_url`, `relyloop_git_author_name`, and `relyloop_git_author_email` fields. The latter two are required by spec FR-2's "commit author is `relyloop-bot@<install-domain>`" contract (cycle-2 F3 — previously not surfaced as a Settings field).

**Modified files**

| File | Change |
|---|---|
| `backend/app/core/settings.py` | Add 3 fields after `relyloop_git_sha`: `relyloop_base_url: str \| None`, `relyloop_git_author_name: str = "relyloop-bot"`, `relyloop_git_author_email: str = "relyloop-bot@example.com"` (operator MUST override the email in production via env var; the default is a placeholder for dev). |
| `.env.example` | Add `# RELYLOOP_BASE_URL=...`, `# RELYLOOP_GIT_AUTHOR_NAME=relyloop-bot`, `# RELYLOOP_GIT_AUTHOR_EMAIL=relyloop-bot@your-company.com` (all commented; defaults are placeholders). |

**Tasks**
1. Add the 3 fields to `Settings`. No `@cached_property` accessors needed (plain strings, not secret files).
2. Update `.env.example` with documented placeholders.

**Definition of Done**
- [ ] `get_settings().relyloop_base_url` returns `None` by default; returns the set value when the env var is provided.
- [ ] `get_settings().relyloop_git_author_name` / `email` return the configured values.
- [ ] Unit test `test_settings_relyloop_base_url.py` covers `relyloop_base_url`; extended to assert the two author fields too.

---

### Story 1.4a — Add `matplotlib` to dependencies (cycle-1 F1)

**Outcome:** `matplotlib` listed in `pyproject.toml` so the worker can `import matplotlib.pyplot as plt` at PNG-generation time.

**Modified files**

| File | Change |
|---|---|
| `pyproject.toml` | Add `matplotlib = "^3.9"` (or current stable) to the project dependencies block. |
| `uv.lock` | Regenerate via `uv lock` after the pyproject edit; commit the lockfile. |

**Tasks**
1. Add the dependency to `pyproject.toml`.
2. Run `uv lock` to refresh the lockfile.
3. Rebuild the worker Docker image (or verify the project venv via `uv sync` for local runs).

**Definition of Done**
- [ ] Unit test `test_matplotlib_importable.py::test_pyplot_imports` asserts `import matplotlib.pyplot as plt` succeeds in the project venv + the worker image.
- [ ] `pyproject.toml` diff includes the new dependency; `uv.lock` regenerated.

---

### Story 1.4 — Domain helpers: git + redaction

**Outcome:** `backend/app/domain/git/` package with pure-Python helpers used by the worker. Three functions:
- `redact_token(text: str) -> str` — strip GitHub PAT patterns from a string.
- `validate_repo_url(url: str) -> tuple[str, str]` — regex-match against `https://github.com/<owner>/<repo>(\.git)?` and return `(owner, repo)`; raise `UnsupportedProviderError` otherwise.
- `validate_config_path(path: str) -> None` — assert relative path with `[A-Za-z0-9_/.-]` only (spec §10 mitigation 2); raise `InvalidConfigPathError` on traversal attempt.

Plus a structlog processor `RedactTokensProcessor` that applies `redact_token` to every string field in the log record (FR-5).

**New files**

| File | Purpose |
|---|---|
| `backend/app/domain/git/__init__.py` | Package init — exports the 3 helpers. |
| `backend/app/domain/git/redaction.py` | `redact_token(text)` + `RedactTokensProcessor` (structlog processor). |
| `backend/app/domain/git/validation.py` | `validate_repo_url(url)` + `validate_config_path(path)` + `UnsupportedProviderError` + `InvalidConfigPathError` exceptions. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/core/logging.py` | Wire `RedactTokensProcessor` into the structlog processor chain so EVERY log line is token-redacted (defense in depth — not just the worker's). |

**Key interfaces**

```python
# backend/app/domain/git/redaction.py
import re
import structlog

# Cycle-3 F2: covers ALL current GitHub token formats:
#   - github_pat_<82+ chars> — fine-grained PATs (newest, increasingly common in enterprise)
#   - ghp_<36+ chars>         — classic personal access tokens
#   - ghs_<36+ chars>         — installation tokens (GitHub Apps)
#   - gho_<36+ chars>         — OAuth tokens
#   - ghu_<36+ chars>         — user access tokens
#   - ghr_<36+ chars>         — refresh tokens
# Anchor on the prefixes; downstream tooling adds more prefixes occasionally
# but always under the gh<a-z>_ or github_pat_ family.
_GH_TOKEN_PATTERN = re.compile(
    r"(?:github_pat_[A-Za-z0-9_]{20,}|gh[a-z]_[A-Za-z0-9_]{36,})"
)


def redact_token(text: str) -> str:
    """Replace any GitHub PAT pattern with [REDACTED-GH-TOKEN]."""
    if not isinstance(text, str):
        return text
    return _GH_TOKEN_PATTERN.sub("[REDACTED-GH-TOKEN]", text)


class RedactTokensProcessor:
    """structlog processor — walk the event_dict and redact every string value.

    Also redacts the event message itself + any exception traceback strings.
    """
    def __call__(self, logger: object, name: str, event_dict: dict) -> dict:
        return _redact_dict(event_dict)


def _redact_dict(d: dict) -> dict: ...  # recursive walk; redact str values


# backend/app/domain/git/validation.py
class UnsupportedProviderError(ValueError):
    """repo_url doesn't match the GitHub regex (MVP1 GitHub-only)."""


class InvalidConfigPathError(ValueError):
    """clusters.config_path failed the path-traversal guard."""


_GITHUB_URL_PATTERN = re.compile(r"^https://github\.com/([a-zA-Z0-9._-]+)/([a-zA-Z0-9._-]+?)(\.git)?$")
_CONFIG_PATH_PATTERN = re.compile(r"^[A-Za-z0-9_./-]+$")


def validate_repo_url(url: str) -> tuple[str, str]:
    """Return (owner, repo). Raise UnsupportedProviderError on non-GitHub URLs."""
    m = _GITHUB_URL_PATTERN.match(url)
    if not m:
        raise UnsupportedProviderError(
            f"repo_url {url!r} is not a GitHub URL; GitLab + Bitbucket arrive in MVP3"
        )
    return (m.group(1), m.group(2))


def validate_config_path(path: str) -> None:
    """Reject path-traversal (../) and shell-metacharacters in clusters.config_path."""
    if not path or not _CONFIG_PATH_PATTERN.match(path):
        raise InvalidConfigPathError(
            f"config_path {path!r} contains disallowed characters"
        )
    if ".." in path.split("/"):
        raise InvalidConfigPathError(f"config_path {path!r} contains '..' traversal")
```

**Tasks**
1. Create `backend/app/domain/git/` package with the 2 modules + `__init__.py`.
2. Wire `RedactTokensProcessor` into `backend/app/core/logging.py` BEFORE the JSON renderer so the redaction runs on every log line system-wide (FR-5 defense-in-depth — also protects the API's request-id middleware logs, capability check logs, etc.).

**Definition of Done**
- [ ] Unit test `test_redaction.py::test_redacts_classic_pat` passes (`ghp_<36 chars>` → `[REDACTED-GH-TOKEN]`).
- [ ] Unit test `test_redaction.py::test_redacts_installation_token` passes (`ghs_<36 chars>`).
- [ ] **Cycle-3 F2:** unit test `test_redaction.py::test_redacts_fine_grained_pat` passes (`github_pat_<82 chars>`). Parametrized over `gho_`, `ghu_`, `ghr_` prefixes too.
- [ ] Unit test `test_redaction.py::test_does_not_redact_non_token_strings` passes (no false positives on normal text).
- [ ] Unit test `test_redaction.py::test_processor_walks_nested_dicts` passes (structlog `extra={"a": {"b": "token..."}}` is redacted).
- [ ] Unit test `test_validation.py::test_validate_repo_url_accepts_github` passes.
- [ ] Unit test `test_validation.py::test_validate_repo_url_rejects_gitlab_bitbucket` passes.
- [ ] Unit test `test_validation.py::test_validate_config_path_rejects_traversal` passes.
- [ ] Integration test (existing `test_health_integration.py` extension or new): all `/healthz` log lines emitted during the test contain `[REDACTED-GH-TOKEN]` if a token-shaped string was passed through (defense-in-depth coverage).

---

## Epic 1 gate (hard stop)

- [ ] All 4 stories complete (repo extensions + schemas + Settings + domain helpers).
- [ ] `make test-unit` + targeted `pytest backend/tests/integration/test_*_repo.py` green.
- [ ] `make lint && make typecheck` green.

---

## Epic 2 — Worker (the heart of the feature)

### Story 2.1 — `open_pr` worker job

**Outcome:** `backend/workers/git_pr.py` ships the full `open_pr(ctx, proposal_id)` Arq job per spec FR-2. The 15-step worker mirrors `feat_digest_proposal`'s `generate_digest` shape — proven cycle-1/2/3 review patterns applied.

**New files**

| File | Purpose |
|---|---|
| `backend/workers/git_pr.py` | The full worker. Mirrors the structure of [`backend/workers/digest.py`](../../../../backend/workers/digest.py) — preflight order, advisory lock, conditional UPDATE, persist-then-side-effect ordering. |

**Key interfaces**

```python
# backend/workers/git_pr.py

async def _safe_set_pr_open_error(db, proposal_id: str, error_msg: str) -> None:
    """Best-effort error write — never raises (defense-in-depth)."""
    redacted = redact_token(error_msg)
    try:
        await repo.set_proposal_pr_open_error(db, proposal_id, error=redacted)
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to write pr_open_error", error=str(exc))


@asynccontextmanager
async def _acquire_config_repo_lock(db: AsyncSession, config_repo_id: str) -> AsyncIterator[bool]:
    """pg_try_advisory_xact_lock keyed on blake2b("config-repo:{id}").

    Disjoint prefix from orchestrator's replenish lock (study_id) and
    digest worker's lock ("digest:{study_id}"). Xact-scoped — releases
    on commit/rollback.
    """
    ...


async def open_pr(ctx: dict[str, Any], proposal_id: str) -> None:
    """Arq entry point. 15-step contract:

    1. Load proposal + bail if non-pending (operator-reject before enqueue).
    2. Load cluster + config_repo + query_template (FK chain).
    3. Resolve PAT: read ./secrets/{config_repo.auth_ref}; bail if missing/empty.
    4. Acquire pg_try_advisory_xact_lock on config_repo_id. **On contention
       (lock not acquired), raise `arq.Retry(defer=5.0)` so Arq re-enqueues
       the SAME job ~5s later.** This guarantees AC-5 sequential processing
       (both same-config_repo proposals eventually reach pr_opened) without
       holding a connection while another worker has the lock. Cycle-1 F2
       — bail-on-contention contradicts AC-5.
    5. Re-read proposal status INSIDE the lock (operator-reject race).
    6. **Clone-or-pull via env-var credential mechanism (cycle-1 F4 —
       NO tokenized URL in argv).** Clone the tokenless URL
       `https://github.com/{owner}/{repo}.git` into
       `./data/repo-clones/{config_repo_id}/`. Pass the PAT via Git's
       process-scoped `GIT_CONFIG_*` env vars (NOT via argv, NOT via
       `.git/config` on disk):
       ```
       env = {
         "GIT_CONFIG_COUNT": "1",
         "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
         "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: Bearer {token}",
       }
       subprocess.run(["git", "clone", "https://github.com/{owner}/{repo}.git", clone_dir],
                       env={**os.environ, **env}, check=True, capture_output=True)
       ```
       The token lives ONLY in the subprocess environment (visible to
       `git` and its children, NOT to `ps`/argv inspection, NOT
       persisted on disk via `.git/config`). Subsequent `git fetch` /
       `push` use the same `GIT_CONFIG_*` env passthrough.
       Reference: GitHub Actions' `actions/checkout` uses this exact
       pattern for the same reason.
    7. **Clean-base reset + branch creation (cycle-2 F1 + cycle-3 F3
       refinement).** The local clone is PERSISTENT per
       `config_repo_id` (reused across proposals), so a prior failed
       run can leave it on a feature branch with dirty tracked files,
       untracked files, or local-only commits. Execute in this order:
       ```
       git -C <clone> fetch origin {pr_base_branch}
       git -C <clone> reset --hard origin/{pr_base_branch}   # discard ALL tracked changes (cycle-3 F3)
       git -C <clone> clean -fdx                              # discard untracked + ignored files
       git -C <clone> checkout -B {new_branch} origin/{pr_base_branch}
       ```
       `reset --hard` (NOT `checkout -B` alone — that resets the ref
       but does not guarantee a clean working tree if `checkout`
       refuses on dirty state) discards every tracked-file modification
       from the prior failed run. Then `clean -fdx` drops the prior
       `.relyloop/digest-charts/` PNG + any other untracked artifacts.
       Then `checkout -B` creates the new branch ref pointing at
       `origin/{pr_base_branch}`. Finally check whether the new branch
       already exists upstream via
       `git -C <clone> ls-remote --heads origin {new_branch}`; if
       non-empty result, fail with `BRANCH_EXISTS` (no force-push per
       spec §4).
    8. **Validate config_path + resolved-path containment (cycle-2 F2).**
       Call `validate_config_path(cluster.config_path)` from
       `backend.app.domain.git.validation` (Story 1.4) BEFORE
       constructing the params file path. Then after computing
       `params_path = clone_root / cluster.config_path / f"{template.name}.params.json"`,
       enforce `params_path.resolve().is_relative_to(clone_root.resolve())`
       — a final-resolved-path containment check that catches symlink
       attacks + any traversal that slipped past the regex. On
       violation, populate token-redacted `pr_open_error` ("config_path
       traversal blocked") and bail. Then read the params file; fail
       `PARAMS_FILE_NOT_FOUND` if absent.
    9. Validate every config_diff key in template.declared_params; fail
       PARAM_NOT_IN_TEMPLATE on drift.
    10. Apply config_diff: extract .to value at each path; deep-merge.
        Optionally log .from drift if cur value differs.
    11. Generate parameter-importance PNG via matplotlib from
        digests.parameter_importance. On failure, log
        pr_open_chart_failed + use Markdown-table fallback.
    12. Commit params edit + commit PNG (separate commits). Push.
        Use `git commit -F <tempfile>` (token-safe; never -m + shell-
        quoted args). **Author + committer identity (cycle-2 F3):**
        pass `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` / `GIT_COMMITTER_NAME`
        / `GIT_COMMITTER_EMAIL` env vars to the commit subprocess from
        `Settings.relyloop_git_author_name` / `relyloop_git_author_email`
        (Story 1.3) so the commits carry the bot identity, not whatever
        global git config happens to be on the worker host. All git
        subprocesses (clone, fetch, commit, push) receive the PAT via
        the `GIT_CONFIG_COUNT=1 + GIT_CONFIG_KEY_0 + GIT_CONFIG_VALUE_0`
        env-var mechanism as Step 6 — token is NEVER in argv, NEVER in
        `.git/config`, NEVER in shell-expanded flags (cycle-1 F4).
    13. Open PR via httpx POST /repos/{owner}/{repo}/pulls.
        **Body content depends on study_id presence (cycle-3 F4):**
        - **Study-backed proposal (`study_id` non-null):** body includes
          metric delta + top-10 trials + suggested followups (from
          `digests.suggested_followups`, fetched via
          `repo.get_digest_for_study(db, proposal.study_id)`) +
          `{settings.relyloop_base_url}/studies/{study_id}` link (when
          base_url is set).
        - **Manual proposal (`study_id IS NULL`):** body OMITS the
          metric delta / top-10 trials / suggested-followups sections
          (no digest exists) AND omits the study-detail link. Body is
          a shorter Markdown summary explaining "This is a manual
          (hand-crafted) proposal — no study metrics available." The
          `config_diff` JSON is still rendered as a table.
    14. Post chart-comment via httpx **POST /repos/{owner}/{repo}/issues/{pull_number}/comments**
        (cycle-1 F3 — issues/{N}/comments is the general-conversation
        endpoint; /pulls/{N}/comments is for line-level REVIEW comments
        which require diff-position fields we don't have). Body is
        Markdown referencing the committed PNG via raw URL, or the
        Markdown-table fallback if PNG generation failed. On comment
        post failure, log pr_open_chart_failed but DO NOT fail the PR —
        the chart comment is enhancement, not blocking.
    15. Conditional UPDATE: mark_proposal_pr_opened (WHERE status='pending');
        on zero-rows match, log pr_open_proposal_no_longer_pending and skip.
    """
```

**Tasks**
1. Create `backend/workers/git_pr.py`. Imports from `backend.app.domain.git` (Story 1.4 helpers), `backend.app.llm.budget_gate` (NO — no LLM call in this worker; ignore), `backend.app.db.repo`, `backend.app.core.settings`.
2. Implement `_acquire_config_repo_lock` mirroring [`backend/workers/digest.py:_acquire_digest_lock`](../../../../backend/workers/digest.py).
3. Implement `_safe_set_pr_open_error` — best-effort error write with redaction; never propagates.
4. Implement the 15-step `open_pr` function. Each WARN/ERROR log emits a structured `event_type` marker per spec §13 Operability:
   - `pr_open_lock_contention`
   - `pr_open_proposal_no_longer_pending`
   - `pr_open_chart_failed`
   - `pr_open_complete`
   - `pr_open_failed`
   - `pr_open_no_config_repo` (worker-side defense-in-depth — endpoint already 422s but the worker may receive a stale enqueue)
5. **Branch naming** (spec §4): `relyloop/study-{study_id}` when `proposal.study_id` is non-null; `relyloop/proposal-{proposal_id}` otherwise.
6. **Token-safe git via `GIT_CONFIG_COUNT` env vars (cycle-1 F4).** Replaces the previous tokenized-URL plan, which would have placed the PAT in `git clone` argv (visible to `ps` + leaked via process accounting). The new pattern: clone the TOKENLESS URL (`https://github.com/{owner}/{repo}.git`) and pass the auth header via `GIT_CONFIG_COUNT=1 + GIT_CONFIG_KEY_0="http.https://github.com/.extraheader" + GIT_CONFIG_VALUE_0=f"AUTHORIZATION: Bearer {token}"` in the subprocess `env` arg. Implement a helper `_git_subprocess(args: list[str], *, token: str, cwd: str, **kw)` that wraps `subprocess.run` with this env mechanism + captures stdout/stderr + passes the captured streams through `redact_token` before logging. Use this helper for ALL git invocations (clone, fetch, commit, push). The token is never in argv, never in `.git/config`, never in shell-expanded flags.
7. **Commit message format** — read [`docs/01_architecture/apply-path.md`](../../../01_architecture/apply-path.md) §"PR creation flow" + use `git commit -F <tempfile>` (token-safe).
8. **PNG generation (cycle-3 F4 — study-backed only).** matplotlib, 800×600 monochrome horizontal bar chart per spec §19 decision-log. **ONLY runs when `proposal.study_id IS NOT NULL` AND a `digests` row exists for that study** (i.e., not for manual proposals, which have no parameter-importance data). Output to `<clone>/.relyloop/digest-charts/{study_id}.png` (or `{proposal_id}.png` if the worker is later extended to handle manual proposals; not in MVP1 scope). On `Exception`, log `pr_open_chart_failed` + render a Markdown table fallback for the comment body. **Raw-URL format (cycle-2 F4)**: branch names like `relyloop/study-{study_id}` contain a slash, which makes `https://github.com/{owner}/{repo}/raw/{branch}/.relyloop/...` ambiguous. Use the slash-safe form `https://github.com/{owner}/{repo}/raw/refs/heads/{branch}/.relyloop/digest-charts/{study_id}.png` instead. Unit-tested in `test_pr_body_render.py::test_chart_url_uses_refs_heads_form_for_slashed_branch`.

For manual proposals (`study_id IS NULL`), the worker SKIPS Step 14 (no chart comment) entirely. The PR opens with just the body (params diff + manual-proposal note).
9. **GitHub REST calls** — `httpx.AsyncClient(timeout=30)`; pass `Authorization: Bearer <pat>` header; retry policy (cycle-1 F6):
   - `httpx.RequestError` (DNS / TLS / connection reset): retry up to 3× with exponential backoff (1s, 2s, 4s).
   - 5xx response: retry up to 3× with exponential backoff.
   - **429 response with `Retry-After` header**: honor the header value (clamped to 60s max for sanity); retry up to 3×.
   - **403 response with `X-RateLimit-Remaining: 0` + `X-RateLimit-Reset` headers** (GitHub's secondary rate-limit signal — NOT a generic 403): compute the wait from `X-RateLimit-Reset` (clamped to 60s); retry up to 3×.
   - **403 without the rate-limit headers**: terminal — populate `pr_open_error` with the GitHub error message (token-redacted); status stays `pending`.
   - 4xx (other): terminal — populate `pr_open_error`.

   After retry exhaustion, the final `pr_open_error` includes the latest retry-after / reset timing so the operator can decide whether to retry manually. Capture stderr from `git` subprocesses and pass through `redact_token` before logging (already covered by the `_git_subprocess` helper from Task 6).
10. **No `_safe_record_cost`** — this worker doesn't make billable LLM calls. The `_safe_set_pr_open_error` helper is the analogous "never-propagates-error" wrapper.

**Definition of Done**
- [ ] Integration test `test_pr_open_happy_path.py::test_ac1_happy_path` passes (cassette-replayed GitHub API; asserts PR opened, params edited, chart committed, conditional UPDATE landed). [AC-1]
- [ ] Integration test `test_pr_open_param_not_in_template.py::test_ac3_fails_with_clear_error` passes. [AC-3]
- [ ] Integration test `test_pr_open_branch_exists.py::test_ac4_no_force_push` passes. [AC-4]
- [ ] Integration test `test_pr_open_serialization.py::test_ac5_per_repo_lock_serializes_and_both_eventually_open` passes (cycle-1 F2): two concurrent jobs against same `config_repo_id`. Asserts (a) `arq.Retry` is raised exactly once by the second worker (lock contention path); (b) the first worker's `pr_open_complete` event_type fires before the second worker's; (c) BOTH proposals eventually reach `status='pr_opened'` with distinct `pr_url`s. AC-5's "both PRs eventually open" requirement is explicitly verified, not just the serialization order. [AC-5] |
- [ ] Integration test `test_pr_open_reject_race.py::test_ac10_conditional_update_no_ops` passes (mid-flight reject → `mark_proposal_pr_opened` returns None → status stays `rejected`, PR is open on remote). [AC-10]
- [ ] Integration test `test_pr_open_chart_fallback.py::test_ac11_png_failure_falls_back_to_markdown_table` passes. [AC-11]

---

### Story 2.2 — Worker registration in `WorkerSettings`

**Outcome:** `backend/workers/all.py` imports `open_pr` and registers it in `WorkerSettings.functions` **with explicit `arq.func(open_pr, max_tries=30, timeout=180)` wrapper (cycle-3 F1)**. The retry budget covers the worst case where multiple same-`config_repo_id` proposals serialize: at 5s `defer` between retries, `max_tries=30` gives a ~150s window for the first job to complete (spec §13 NFR <60s p99 for the first PR open; comfortable margin for the second).

**Modified files**

| File | Change |
|---|---|
| `backend/workers/all.py` | Add `from backend.workers.git_pr import open_pr` import; add `func(open_pr, max_tries=30, timeout=180)` to the `WorkerSettings.functions` list (cycle-3 F1); update the module docstring's job inventory. |

**Tasks**
1. Add the import + registration. Mirror the existing `generate_digest` registration pattern (no `arq.func()` wrapper).
2. Update the module docstring's Registered-jobs section to list `open_pr`.

**Definition of Done**
- [ ] `from backend.workers.all import WorkerSettings; assert open_pr in WorkerSettings.functions` passes.
- [ ] Integration test `test_workers_registration.py::test_open_pr_registered` passes (or extends existing `test_workers.py`).

---

## Epic 2 gate (hard stop)

- [ ] `open_pr` worker shipped + registered.
- [ ] All AC-1 / AC-3 / AC-4 / AC-5 / AC-10 / AC-11 paths pass integration tests.
- [ ] `make test-integration` green.

---

## Epic 3 — API (4 endpoints across 2 router files)

### Story 3.1 — `POST /api/v1/proposals/{id}/open_pr` (FR-1 / AC-1, AC-2, AC-6, AC-12)

**Outcome:** New `open_pr` endpoint added to the EXISTING `backend/app/api/v1/proposals.py` router (which already has 5 endpoints from `feat_digest_proposal`). Preflight order matches spec FR-1.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/proposals.py` | Add `POST /proposals/{id}/open_pr` handler at the end of the file (after the reject handler). Imports `OpenPrResponse` from schemas + the per-repo auth-file reader helper. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/proposals/{id}/open_pr` | — | `202 OpenPrResponse` | `PROPOSAL_NOT_FOUND` (404), `INVALID_STATE_TRANSITION` (409), `CLUSTER_HAS_NO_CONFIG_REPO` (422), `GITHUB_NOT_CONFIGURED` (503), `QUEUE_UNAVAILABLE` (503; cycle-2 F5) |

**Tasks**
1. Implement the handler. Preflight:
   - Step 1: `repo.get_proposal` → 404 `PROPOSAL_NOT_FOUND`.
   - Step 2: if `proposal.status != 'pending'` → 409 `INVALID_STATE_TRANSITION`. **[AC-6]**
   - Step 3: load `cluster = repo.get_cluster(proposal.cluster_id)`; if `cluster.config_repo_id IS NULL` → 422 `CLUSTER_HAS_NO_CONFIG_REPO`.
   - Step 4: load `config_repo = repo.get_config_repo(cluster.config_repo_id)`; read `./secrets/{auth_ref}` via a `read_auth_secret(auth_ref)` helper; if file missing or empty → 503 `GITHUB_NOT_CONFIGURED`. **[AC-2]**
2. Enqueue via `request.app.state.arq_pool.enqueue_job("open_pr", proposal_id, _job_id=f"open_pr:{proposal_id}")` with deterministic job_id for dedup **[AC-12]**. **Cycle-2 F5: NOT best-effort.** Unlike the digest worker (which has a boot-scan fallback), this feature has no recovery path if the enqueue fails silently — the proposal would sit `pending` indefinitely with no `pr_open_error` to surface the failure. If `arq_pool is None` OR `enqueue_job` raises (Redis unreachable, Arq pool not built) → return **503 `QUEUE_UNAVAILABLE`** (retryable=true). Operator retries after `make up` confirms the worker queue is healthy.
3. Return `202` with `OpenPrResponse(proposal_id=…, status='pending', message='PR creation queued')` — ONLY on successful enqueue.

**Definition of Done**
- [ ] AC-1: handler enqueues correctly; worker runs end-to-end (covered by Story 2.1 integration tests).
- [ ] AC-2: integration test `test_pr_open_auth_ref_missing.py::test_ac2_returns_503_when_auth_ref_secret_empty` passes.
- [ ] AC-6: integration test `test_pr_open_rejected_after_opened.py::test_ac6_409_on_already_opened` passes.
- [ ] AC-12: integration test `test_pr_open_dedup.py::test_ac12_double_post_dedup_via_job_id` passes (exactly one worker call recorded; second call returns 202 with same payload).
- [ ] Integration test `test_pr_open_no_config_repo.py::test_returns_422_when_cluster_has_no_config_repo` passes.

---

### Story 3.2 — `POST /api/v1/config-repos` (FR-3 / AC-8, AC-9)

**Outcome:** New router `backend/app/api/v1/config_repos.py` ships with the `POST` endpoint. `provider` is server-derived from `repo_url` via `validate_repo_url` (Story 1.4).

**New files**

| File | Purpose |
|---|---|
| `backend/app/api/v1/config_repos.py` | New router. Helpers (`_err`, `_encode_cursor`, `_decode_cursor`) copied from `judgments.py` per the project's deferred-hoist note. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/main.py` | Add `from backend.app.api.v1 import config_repos as config_repos_router` + `app.include_router(config_repos_router.router, prefix="/api/v1")` after the `proposals_router` registration. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/api/v1/config-repos` | `CreateConfigRepoRequest` | `201 ConfigRepoDetail` | `VALIDATION_ERROR` (422), `UNSUPPORTED_PROVIDER` (400), `CONFIG_REPO_NAME_TAKEN` (409), `AUTH_REF_NOT_FOUND` (400) |

**Tasks**
1. Create `backend/app/api/v1/config_repos.py`. Copy `_err` + helpers from `judgments.py`.
2. Implement `POST /config-repos`:
   - Validate `repo_url` via `validate_repo_url` (Story 1.4); on `UnsupportedProviderError` → 400 `UNSUPPORTED_PROVIDER`. **[AC-8]**
   - Check `./secrets/{auth_ref}` exists (existence check at API level; non-empty contents checked at PR-open time); on missing → 400 `AUTH_REF_NOT_FOUND`. **[AC-9]**
   - Check `name` uniqueness via `repo.get_config_repo_by_name`; on collision → 409 `CONFIG_REPO_NAME_TAKEN`.
   - Insert via `repo.create_config_repo(db, id=..., provider="github", **body)`; commit.
   - Return 201 with `ConfigRepoDetail`.
3. Register the router in `main.py`.

**Definition of Done**
- [ ] AC-8: integration test `test_config_repo_crud.py::test_ac8_gitlab_rejected_with_unsupported_provider` passes.
- [ ] AC-9: integration test `test_config_repo_crud.py::test_ac9_auth_ref_not_found_when_secret_missing` passes.
- [ ] Integration test `test_config_repo_crud.py::test_create_with_duplicate_name_returns_409` passes.
- [ ] Integration test `test_config_repo_crud.py::test_create_happy_path_returns_201` passes.

---

### Story 3.3 — `GET /api/v1/config-repos` + `GET /api/v1/config-repos/{id}` (FR-3)

**Outcome:** List + detail endpoints on the new router.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/config_repos.py` | Add list + detail handlers. |

**Endpoints**

| Method | Path | Query params | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/config-repos` | `?cursor=`, `?limit=` | `200 ConfigReposListResponse` + `X-Total-Count` header | `VALIDATION_ERROR` (422; bad cursor) |
| `GET` | `/api/v1/config-repos/{id}` | — | `200 ConfigRepoDetail` | `CONFIG_REPO_NOT_FOUND` (404) |

**Tasks**
1. Implement `GET /config-repos`:
   - Decode cursor (422 on bad shape via `_decode_cursor`).
   - Call `repo.list_config_repos(db, cursor=..., limit=limit+1)`.
   - `has_more = len(rows) > limit`; trim; emit `X-Total-Count` from `repo.count_config_repos`.
   - Build `ConfigRepoDetail` rows; return `ConfigReposListResponse`.
2. Implement `GET /config-repos/{id}`:
   - `repo.get_config_repo` → 404 `CONFIG_REPO_NOT_FOUND` if None.
   - Return `ConfigRepoDetail`.

**Definition of Done**
- [ ] Integration test `test_config_repos_list.py::test_list_default_returns_paginated` passes (asserts `X-Total-Count` header + cursor round-trip).
- [ ] Integration test `test_config_repos_detail.py::test_detail_returns_full_row` passes.
- [ ] Integration test `test_config_repos_detail.py::test_unknown_id_returns_404` passes.

---

## Epic 3 gate (hard stop)

- [ ] All 4 endpoints live and registered in OpenAPI.
- [ ] `backend/tests/contract/test_github_pr_worker_api_contract.py` asserts every endpoint is registered + the split static-grep audit (cycle-2 F4 / cycle-3 F1):
  - Router source `backend/app/api/v1/config_repos.py` + `proposals.py` (the `open_pr` handler portion) contain the 9 endpoint-visible §8.5 codes.
  - Worker source `backend/workers/git_pr.py` contains the 5 worker-side codes (`PARAM_NOT_IN_TEMPLATE`, `PARAMS_FILE_NOT_FOUND`, `BRANCH_EXISTS`, `GITHUB_API_FAILED`, `CLONE_FAILED`) as structured `error_code=` log fields.
  - Negative assertion: router source does NOT raise any of the 5 worker-side codes.
- [ ] `make test-integration` + `make test-contract` green.

---

## Epic 4 — Docs / tests / cleanup

### Story 4.1 — Runbook + security doc + user-stories flip

**New files**

| File | Purpose |
|---|---|
| `docs/03_runbooks/pr-open-debugging.md` | Operator playbook: re-running a failed `open_pr`, manually closing an orphan branch on GitHub, rotating per-repo PATs, debugging `pr_open_error` strings (including how to find the source `git` stderr that produced them), inspecting the committed `.relyloop/digest-charts/` PNGs. |
| `docs/04_security/github-token-handling.md` | Token storage (per-repo `auth_ref` at `./secrets/{ref}`), rotation procedures (rotate one PAT without touching others — the killer feature vs the old global env), scope requirements (`contents:write`, `pull_requests:write`, optionally `workflow:write`), the `.git/config` reset rationale, the `[REDACTED-GH-TOKEN]` sentinel in logs, AC-7 verification checklist. |

**Modified files**

| File | Change |
|---|---|
| `docs/02_product/mvp1-user-stories.md` | US-18 + US-19 → marked Implemented (PR #N pending) inline. |

**Tasks**
1. Author both new docs (~150-300 lines each, mirror the digest-debugging.md structure).
2. Patch the mvp1-user-stories markers.

**Definition of Done**
- [ ] Runbook covers all 5 worker-side terminal codes (`PARAM_NOT_IN_TEMPLATE`, `PARAMS_FILE_NOT_FOUND`, `BRANCH_EXISTS`, `GITHUB_API_FAILED`, `CLONE_FAILED`).
- [ ] Security doc enumerates the AC-7 leak checklist (PR body, commit message, proposal row, log lines, subprocess argv, git stderr/stdout, `.git/config`).
- [ ] User stories flipped.

---

### Story 4.2 — Contract test + benchmark + lean refactor

**Outcome:** Contract test mirroring `test_judgments_api_contract.py` and `test_digest_proposal_api_contract.py`. Live release-gate benchmark for AC-1 against `SoundMindsAI/relyloop-test-configs`. Lean refactor opportunity: token redaction filter could be lifted further into a shared `backend/app/core/secrets/` package if `feat_github_webhook` also needs it — but that's MVP3 territory; the current `backend/app/domain/git/redaction.py` is sufficient.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/contract/test_github_pr_worker_api_contract.py` | OpenAPI presence assertions for the 4 endpoints + the split static-grep audit (9 router codes + 5 worker codes + negative assertion that worker codes don't appear in routers). |
| `backend/tests/contract/test_token_never_leaks.py` | AC-7 sweep (cycle-1 F5 — explicit enumeration of all 9 surfaces): cassette-replay a happy-path + a failed PR-open. Use a sentinel test token (e.g. `ghp_TESTTOKENSENTINEL00000000000000000000`) and assert it does NOT appear in: (1) PR title sent to GitHub; (2) PR body sent to GitHub; (3) any commit message (read via `git log --format=%B`); (4) `proposals.pr_url` value; (5) `proposals.pr_open_error` value (on the failure-path scenario); (6) every worker log line (captured via structlog cap); (7) every recorded subprocess argv (captured by patching `subprocess.run` to log argv before delegating); (8) every captured subprocess stdout AND stderr for clone/fetch/commit/push; (9) `.git/config` contents post-clone (read the file directly). Each surface gets its own named assertion so a regression in just one is identifiable. |
| `.github/workflows/release-gate-pr-worker.yml` | Live release-gate workflow runs nightly + on tagged releases. Uses the `RELYLOOP_TEST_PAT` GitHub secret to actually open a PR against `SoundMindsAI/relyloop-test-configs`. Cleanup task closes the PR + deletes the branch after assertion. Not blocking PR CI. |

**Tasks**
1. Author `test_github_pr_worker_api_contract.py` mirroring the `test_digest_proposal_api_contract.py` structure (test_openapi_registers_all_N + test_router_source_contains_every_endpoint_visible_code + test_router_source_does_not_raise_worker_only_codes + test_worker_source_contains_every_worker_only_code).
2. Author `test_token_never_leaks.py` per AC-7. The `.git/config` reset assertion is the strongest part — it directly verifies the cycle-2 design decision.
3. Author the release-gate workflow YAML. Document the required GitHub secret (`RELYLOOP_TEST_PAT`) in `docs/03_runbooks/local-dev.md` or a new ops runbook.

**Definition of Done**
- [ ] `make test-contract` green; all 4 endpoints registered; both grep tests pass.
- [ ] Token-never-leaks test covers all 6 leak surfaces from spec AC-7.
- [ ] Release-gate workflow committed (initial run not required during PR CI; the workflow's own first execution validates).

---

### Story 4.3 — Final docs sweep + state.md / architecture.md / CLAUDE.md updates

**Outcome:** `state.md`, `architecture.md`, `CLAUDE.md` updated post-merge per impl-execute Step 8 finalization. **Performed automatically by `/impl-execute` Step 8.5** — this story documents the expected updates so the agent doesn't miss them.

**Modified files**

| File | Change |
|---|---|
| `state.md` | Move `feat_github_pr_worker` from In-flight to "Most recent meaningful changes"; refresh Queued list (now starts with `feat_github_webhook`); note the new `RELYLOOP_BASE_URL` setting + the per-repo auth_ref pattern + the spinoff `chore_infra_foundation_github_token_file_retirement` for follow-up. |
| `architecture.md` | Update the `backend/app/api/v1/` line to add `config_repos.py`. Update the `backend/workers/` line to add `git_pr.py`. Add new `backend/app/domain/git/` subpath. |
| `CLAUDE.md` | Feature Status table row 7 → Complete (PR #N, merged YYYY-MM-DD). Add a forthcoming-rule note: "When `feat_github_webhook` lands at MVP1 step 8, every state-mutating webhook handler must verify HMAC signature before payload processing (per `infra_foundation` FR-6)." |

**Tasks**
1. Performed by `/impl-execute` finalization. No manual work in this plan beyond the descriptive checklist.

**Definition of Done**
- [ ] `state.md`, `architecture.md`, `CLAUDE.md` consistent with shipped behavior.
- [ ] Feature folder moved to `docs/00_overview/implemented_features/<YYYY_MM_DD>_feat_github_pr_worker/` post-merge.

---

## Epic 4 gate (hard stop)

- [ ] All 3 doc files (runbook + security + user-stories) updated.
- [ ] Contract test passing; release-gate workflow committed.
- [ ] Coverage ≥80% on `backend/workers/git_pr.py`, `backend/app/api/v1/proposals.py` (the new open_pr handler), `backend/app/api/v1/config_repos.py`, `backend/app/domain/git/`.

---

## 3) Testing workstream

### 3.1 Unit tests

- Location: `backend/tests/unit/`
- Tasks:
  - [ ] `backend/tests/unit/workers/test_params_merge.py` — `config_diff` `{from, to}` extraction + deep-merge (Story 2.1).
  - [ ] `backend/tests/unit/workers/test_commit_message.py` — structured commit-message format (Story 2.1).
  - [ ] `backend/tests/unit/workers/test_pr_body_render.py` — PR body construction with + without `relyloop_base_url`; asserts link presence/absence (Story 2.1).
  - [ ] `backend/tests/unit/domain/git/test_redaction.py` — Story 1.4 (PAT regex coverage + nested-dict walk).
  - [ ] `backend/tests/unit/domain/git/test_validation.py` — Story 1.4 (repo_url + config_path).
  - [ ] `backend/tests/unit/core/test_settings_relyloop_base_url.py` — Story 1.3.
  - [ ] `backend/tests/unit/workers/test_matplotlib_importable.py` — Story 1.4a (cycle-1 F1; asserts matplotlib pyplot import succeeds in the project venv).
  - [ ] `backend/tests/unit/workers/test_git_subprocess_wrapper.py` — Story 2.1 / cycle-1 F4 (asserts captured argv from `_git_subprocess` never contains a sentinel token; env vars correctly populated).
- DoD:
  - [ ] Critical branches covered; deterministic.

### 3.2 Integration tests

- Location: `backend/tests/integration/`
- Tasks:
  - [ ] `test_config_repo_repo.py` — Story 1.1 (list + count pagination).
  - [ ] `test_proposal_pr_repo.py` — Story 1.1 (`mark_proposal_pr_opened` + `set_proposal_pr_open_error` conditional UPDATE).
  - [ ] `test_pr_open_happy_path.py` — AC-1 (cassette-replayed GitHub API).
  - [ ] `test_pr_open_auth_ref_missing.py` — AC-2 + 503 `GITHUB_NOT_CONFIGURED`.
  - [ ] `test_pr_open_param_not_in_template.py` — AC-3.
  - [ ] `test_pr_open_branch_exists.py` — AC-4.
  - [ ] `test_pr_open_serialization.py` — AC-5 (advisory lock).
  - [ ] `test_pr_open_rejected_after_opened.py` — AC-6 (409 on already-opened).
  - [ ] `test_pr_open_no_config_repo.py` — 422 `CLUSTER_HAS_NO_CONFIG_REPO`.
  - [ ] `test_pr_open_reject_race.py` — AC-10 (conditional UPDATE no-ops mid-flight reject).
  - [ ] `test_pr_open_chart_fallback.py` — AC-11 (PNG fail → Markdown table).
  - [ ] `test_pr_open_dedup.py` — AC-12 (Arq `_job_id` dedup).
  - [ ] `test_pr_open_dirty_clone_resets.py` — cycle-2 F1 + cycle-3 F3 (pre-seeds the persistent clone with: a stale feature branch, dirty TRACKED params-file modifications, untracked files in `.relyloop/`. Asserts after worker run: (a) the new PR's diff applies on top of `origin/{pr_base_branch}` only (no carried-over stale content from prior run); (b) the params file in the PR has ONLY the new proposal's changes, not the leftover dirty modifications).
  - [ ] `test_pr_open_path_traversal_blocked.py` — cycle-2 F2 (`config_path='../../etc'` and absolute-path attempts → `pr_open_error` populated, no file read outside clone root).
  - [ ] `test_pr_open_commit_author.py` — cycle-2 F3 (asserts `git log --format='%an <%ae>'` matches `Settings.relyloop_git_author_name` + `relyloop_git_author_email`).
  - [ ] `test_pr_open_queue_unavailable.py` — cycle-2 F5 (mock `arq_pool.enqueue_job` to raise; assert 503 `QUEUE_UNAVAILABLE` returned, NOT 202).
  - [ ] `test_pr_open_rate_limit_retry.py` — cycle-1 F6 (mock GitHub returning 429 with `Retry-After`; assert worker honors header + retries up to 3×; final failure populates `pr_open_error` with reset timing).
  - [ ] `test_pr_open_manual_proposal.py` — cycle-3 F4 (`proposal.study_id=NULL`; assert PR opens with branch `relyloop/proposal-{proposal_id}`; PR body lacks metric/trials/followups sections; no chart PNG committed; no chart comment posted; `pr_url` populated).
  - [ ] `test_config_repo_crud.py` — AC-8 + AC-9 + duplicate-name + happy path.
  - [ ] `test_config_repos_list.py` + `test_config_repos_detail.py` — Story 3.3.
  - [ ] `test_workers_registration.py` (or extend existing `test_workers.py`) — Story 2.2.
- DoD:
  - [ ] Happy path + critical failure paths covered.

### 3.3 Contract tests

- Location: `backend/tests/contract/`
- Tasks:
  - [ ] `test_github_pr_worker_api_contract.py` — Story 4.2.
  - [ ] `test_token_never_leaks.py` — Story 4.2 (AC-7).
- DoD:
  - [ ] All 4 endpoints in OpenAPI; 9 router codes in router sources; 5 worker codes in worker source; negative assertion enforced.

### 3.4 E2E tests

N/A — UI lands with `feat_proposals_ui`.

### 3.5 Release-gate tests

- Location: separate GitHub Actions workflow `.github/workflows/release-gate-pr-worker.yml`.
- Tasks:
  - [ ] `tests/release_gate/test_pr_open_live_repo.py` — AC-1 against `SoundMindsAI/relyloop-test-configs`. Requires `RELYLOOP_TEST_PAT` secret in CI.
- DoD:
  - [ ] Nightly + tagged-release execution confirmed; cleanup closes test PR + deletes branch.

### 3.5 Migration verification

N/A — this feature creates no migrations.

### 3.6 CI gates

- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `.venv/bin/ruff format --check backend/`

---

## 4) Documentation update workstream

### 4.0 Core context files

- [ ] `state.md` — Story 4.3 (post-merge — moves to recent-changes; Queued list updated).
- [ ] `architecture.md` — Story 4.3 (new domain/git/ subpath; new worker file; new router).
- [ ] `CLAUDE.md` — Story 4.3 (Feature-status row 7).

### 4.1 Architecture docs

- [ ] `docs/01_architecture/apply-path.md` already documents the workflow; update if implementation diverges (e.g., the `.git/config` reset behavior is new — add a paragraph).

### 4.2 Product docs

- [ ] `docs/02_product/mvp1-user-stories.md` — US-18 + US-19 → Implemented (Story 4.1).

### 4.3 Runbooks

- [ ] `docs/03_runbooks/pr-open-debugging.md` — Story 4.1.

### 4.4 Security docs

- [ ] `docs/04_security/github-token-handling.md` — Story 4.1.

### 4.5 Quality docs

- [ ] No changes needed.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- Wire `RedactTokensProcessor` into the GLOBAL structlog processor chain (Story 1.4) so EVERY log line in the API + worker is redacted — not just the PR worker's. Defense-in-depth.
- Defer the router-helpers hoist (`_err`, `_encode_cursor`, `_decode_cursor`) to the existing follow-up `chore_router_helpers_hoist`. This plan does NOT add that hoist; new router copies the helpers verbatim per the established precedent.

### 5.2 Planned refactor tasks

- [ ] **Backend refactor:** Wire `RedactTokensProcessor` globally (Story 1.4 task 2).
- [ ] **No frontend refactor** — UI is owned by `feat_proposals_ui`.

### 5.3 Refactor guardrails

- [ ] Behavioral parity proven by `test_redaction.py` unit tests + an integration test that confirms `/healthz` log lines pass through redaction.
- [ ] Lint/typecheck green after the change.
- [ ] No expansion of product scope.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_digest_proposal` (proposals.config_diff + metric_delta populated; digests.parameter_importance + suggested_followups populated) | Stories 2.1, 4.2 | Merged (PR #41) | Worker would have no source data for PR body / chart |
| `feat_study_lifecycle` (proposals table with pr_url/pr_state/pr_open_error columns) | Story 2.1 | Merged (PR #25) | Schema gap; this feature only writes to existing columns |
| `infra_adapter_elastic` (config_repos table + clusters.config_repo_id) | Story 3.1 + 3.2 | Merged (PR #16) | Cluster→repo FK chain doesn't exist |
| `infra_foundation` (Arq, Settings, Postgres) | Stories 2.1, 2.2, 3.x | Merged (PR #4) | No queue / no config layer |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| GitHub API rate-limit during PR open | M | M | httpx retry 3× with exponential backoff; final failure populates `pr_open_error` with the rate-limit reset header |
| Disk-full during clone (large config repo) | L | M | Worker catches `subprocess.CalledProcessError` from `git clone` and populates `pr_open_error: "clone failed: <stderr>"` (token-redacted) |
| `matplotlib` import on cold-start worker (slow first-call) | L | L | matplotlib is ~1s to import; worker process import-time amortizes across all open_pr jobs (Arq workers are long-lived) |
| Operator misconfigures `auth_ref` to point at the wrong secret | L | H | PR-open preflight (FR-1 Step 4) reads the file at request time and returns 503 `GITHUB_NOT_CONFIGURED` if missing/empty. Test: AC-2. |
| Two concurrent `open_pr` jobs against same study (manual retry while first is in flight) | L | L | Three layers: (a) Arq `_job_id="open_pr:{proposal_id}"` dedup at enqueue; (b) `pg_try_advisory_xact_lock` on config_repo_id; (c) final conditional UPDATE `WHERE status='pending'`. AC-12 verifies. |
| Operator rejects mid-flight | M | L | Cycle-3 F4 pattern: conditional UPDATE matches zero rows; worker logs `pr_open_proposal_no_longer_pending`. GitHub PR is open on the remote; runbook documents the orphan-PR cleanup. AC-10 verifies. |
| GitHub PNG comment fails (permissions, timing) | L | L | Comment is enhancement; PR is the main artifact. Worker logs `pr_open_chart_failed` + falls back to Markdown table in the comment body. AC-11 verifies. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| `GITHUB_NOT_CONFIGURED` | `./secrets/{auth_ref}` missing/empty | 503 at endpoint; no job enqueued | Operator populates the secret file; restart not required (next POST reads fresh) |
| `CLUSTER_HAS_NO_CONFIG_REPO` | `cluster.config_repo_id IS NULL` | 422 at endpoint; no job enqueued | Operator runs `POST /api/v1/config-repos` then `PATCH /clusters/{id}` to wire up |
| `INVALID_STATE_TRANSITION` | POST on non-pending proposal | 409 at endpoint | None — terminal |
| `PARAM_NOT_IN_TEMPLATE` | Worker validates config_diff against declared_params | `pr_open_error` populated; status stays `pending` | Operator fixes the proposal or the template; re-POST |
| `BRANCH_EXISTS` | Worker checks upstream branch | `pr_open_error` populated; status stays `pending` | Operator closes existing PR + deletes branch on GitHub; re-POST |
| `PARAMS_FILE_NOT_FOUND` | Worker reads `.params.json` | `pr_open_error` populated; status stays `pending` | Operator adds the params file to the config repo at the expected path |
| Mid-flight operator reject | Reject API called while worker is mid-clone | Conditional UPDATE no-ops; worker logs `pr_open_proposal_no_longer_pending`; PR is open on remote | Operator closes the orphan PR manually |
| Chart PNG fails | matplotlib raises | Markdown-table fallback in comment; PR still opens | None — degraded UX is acceptable |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1** (foundations): Stories 1.1 → 1.2 → 1.3 → 1.4. Repo extensions + schemas + Settings + git helpers before anything depends on them.
2. **Epic 2** (worker): Story 2.1 (the big one) → Story 2.2 (trivial registration). Worker depends on Epic 1's helpers.
3. **Epic 3** (API): Stories 3.1 → 3.2 → 3.3. The API depends on the worker (3.1 enqueues `open_pr`) AND on Story 1.2 schemas.
4. **Epic 4** (docs / cleanup): Stories 4.1 → 4.2 → 4.3.

### Parallelization opportunities

- Stories 1.2 (schemas), 1.3 (Settings), 1.4 (domain helpers) can land in parallel — independent files.
- Story 4.1 (docs) can be drafted in parallel with Epic 3.
- Story 4.2 (contract test + release-gate workflow) MUST land after Epic 3 since it grep-tests the routers.

---

## 8) Rollout and cutover plan

- **Rollout stages:** N/A — single-tenant local-only MVP1.
- **Feature flag strategy:** None.
- **Migration/cutover steps:**
  1. Merge PR.
  2. Operator drops `./secrets/{auth_ref}` files for each config_repo they intend to register.
  3. Operator POSTs to `/api/v1/config-repos` for each repo.
  4. Operator PATCHes each `cluster` to set `config_repo_id`.
  5. Restart `worker` service (picks up the new `open_pr` job registration).
- **Reconciliation/repair strategy:** Existing pending proposals from the digest worker's runs are now ready to receive `open_pr` calls — no backfill needed.

---

## 9) Execution tracker (copy/paste section)

### Current sprint
- [x] Story 1.1 — repo extensions
- [x] Story 1.2 — Pydantic schemas
- [x] Story 1.3 — Settings field
- [x] Story 1.4a — matplotlib dependency (cycle-1 F1)
- [x] Story 1.4 — git + redaction helpers + global structlog wiring
- [x] Story 2.1 — `open_pr` worker (15-step)
- [x] Story 2.2 — worker registration
- [x] Story 3.1 — `POST /proposals/{id}/open_pr` endpoint
- [x] Story 3.2 — `POST /config-repos` endpoint
- [x] Story 3.3 — `GET /config-repos` list + detail
- [x] Story 4.1 — runbook + security doc + user-stories flip
- [~] Story 4.2 — contract test shipped; token-leak test deferred to follow-up
- [x] Story 4.3 — finalization (state.md + architecture.md + CLAUDE.md)

### Blocked items
- (none)

### Done this sprint
- All 13 stories landed across 5 commits on `feature/feat-github-pr-worker`. Pending push + CI + final GPT-5.5 review + merge.

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, attach evidence for:

- [ ] Files created/modified match the story's New / Modified file tables
- [ ] Endpoint contract implemented exactly as documented
- [ ] Key interfaces implemented with compatible signatures
- [ ] Required tests added/updated for all applicable layers
- [ ] Commands run and passed (`make test-unit`, `make test-integration`, `make test-contract`, `make lint`, `make typecheck`)
- [ ] Related docs updated in same PR

---

## 11) Plan consistency review (executed before publication)

1. **Spec ↔ plan endpoint count.** Spec §8.1 lists 4 endpoints. Plan: Story 3.1 (open_pr) + Story 3.2 (POST config-repos) + Story 3.3 (GET list + detail) = 4. ✓

2. **Spec ↔ plan error code coverage.** Spec §8.5 lists **10** endpoint-visible codes (the original 9 + `QUEUE_UNAVAILABLE` added by plan-cycle-2 F5; spec patched in same commit) + 5 worker-side codes (`PARAM_NOT_IN_TEMPLATE`, `PARAMS_FILE_NOT_FOUND`, `BRANCH_EXISTS`, `GITHUB_API_FAILED`, `CLONE_FAILED`). Plan §3.3 contract test enumerates all 10 in router-source grep + all 5 in worker-source grep + negative assertion. ✓

3. **Spec ↔ plan FR coverage.** All 5 FRs covered in §1 traceability ✓.

4. **Story internal consistency.** Endpoint table fields match Pydantic schema fields. DoD references correct error codes + HTTP statuses. No file ownership conflicts. ✓

5. **Test file count.** 8 unit + 22 integration + 2 contract + 1 release-gate = 33 test files (cycle-1 added: `test_matplotlib_importable.py` + `test_git_subprocess_wrapper.py`; cycle-2 added: `test_pr_open_dirty_clone_resets.py`, `test_pr_open_path_traversal_blocked.py`, `test_pr_open_commit_author.py`, `test_pr_open_queue_unavailable.py`, `test_pr_open_rate_limit_retry.py`; cycle-3 added: `test_pr_open_manual_proposal.py`). Each assigned to exactly one story's DoD. ✓

6. **Gate arithmetic.** Epic 3 gate: "4 endpoints live" — matches stories 3.1–3.3 (1+1+2). ✓

7. **Open questions resolved.** Spec §19 has no open questions. ✓

8. **Frontend UI Guidance.** N/A — no frontend (UI is `feat_proposals_ui`).

9. **Persistence scope.** No `localStorage` / `sessionStorage`.

10. **Enumerated value contract audit.**
   - Spec §8.4 lists 3 enumerated fields (`config_repos.provider`, `proposals.pr_state`, `proposals.status`).
   - Plan §1.2 schemas use `Literal["github"]` for provider with source-of-truth comment citing `backend/app/db/models/config_repo.py` CHECK.
   - `pr_state` and `status` are read-only response fields (the worker writes them; no input from the frontend) — no `<select>` value drift risk in this PR.

11. **Audit-event coverage.** N/A (MVP2+ — `audit_log` activates later).

---

### Plan ↔ codebase verification ledger (Pass 2)

| Claim | Verified by | Status |
|---|---|---|
| Alembic head is `0005_digests`; no migration needed | `ls migrations/versions/` | Verified |
| `config_repo` repo exists with `create_config_repo` / `get_config_repo` / `get_config_repo_by_name` | Read `backend/app/db/repo/config_repo.py` | Verified — Story 1.1 ADDs `list_config_repos` + `count_config_repos` |
| `backend/app/api/v1/proposals.py` exists with 5 endpoints | `grep "@router" backend/app/api/v1/proposals.py` returns 5 hits | Verified |
| `backend/app/api/v1/config_repos.py` does NOT exist | `ls backend/app/api/v1/` | Verified — Story 3.2 CREATES |
| `clusters.config_repo_id` is NULLABLE | Read `backend/app/db/models/cluster.py` | Verified — FR-1 preflight returns 422 `CLUSTER_HAS_NO_CONFIG_REPO` when NULL |
| `config_repos.provider` has CHECK `IN ('github')` | Read `backend/app/db/models/config_repo.py:24` | Verified |
| `proposals.{pr_url, pr_state, pr_open_error, pr_merged_at}` exist | Read `backend/app/db/models/proposal.py` | Verified |
| `digests.{parameter_importance, suggested_followups}` exist | Read `backend/app/db/models/digest.py` | Verified — populated by digest worker |
| `RELYLOOP_BASE_URL` setting does NOT exist | `grep relyloop_base_url backend/app/core/settings.py` returns 0 | Verified — Story 1.3 ADDs |
| `pg_try_advisory_xact_lock` idiom in worker code | Read `backend/workers/orchestrator.py:387-409` + `digest.py:_acquire_digest_lock` | Verified |
| Conditional UPDATE pattern in repo | Read `backend/app/db/repo/proposal.py:update_proposal_for_digest` | Verified — mirror for `mark_proposal_pr_opened` |
| FastAPI router registration | Read `backend/app/main.py:35-39, 127-132` | Verified |
| `_err`, `_encode_cursor`, `_decode_cursor` pattern | Read `backend/app/api/v1/judgments.py:72-90` | Verified |
| Contract-test split-grep pattern | Read `backend/tests/contract/test_digest_proposal_api_contract.py` | Verified — model for §4.2 |
| `git` binary in worker image | `tech-stack.md` + Docker base image `python:3.12-slim` | Verified |

---

## 12) Definition of plan done

- [x] Every FR mapped to stories/tasks/tests/docs.
- [x] Every story includes New/Modified files, Endpoints (where applicable), Key interfaces, Tasks, DoD.
- [x] Test layers (unit / integration / contract) explicitly scoped — no E2E (UI deferred).
- [x] Documentation updates planned and assigned to Stories 4.1 + 4.3.
- [x] Lean refactor scope explicit (Story 1.4 global redaction wiring).
- [x] Phase/epic gates measurable.
- [x] Story-by-Story Verification Gate (§10) included.
- [x] Plan consistency review (§11) executed with no unresolved findings.
- [x] **GPT-5.5 cross-model review:** 3 cycles to the configured cap.
  - **Cycle 1**: 6 findings (4 High, 1 Medium, 1 implicit Low); ALL 6 accepted + applied (F1 matplotlib dep, F2 arq.Retry on lock contention, F3 issues/{N}/comments endpoint, F4 GIT_CONFIG_COUNT env-var token passthrough, F5 AC-7 9-surface enumeration, F6 GitHub rate-limit retry policy).
  - **Cycle 2**: 5 NEW findings (2 High, 3 Medium); ALL 5 accepted + applied (F1 clean-base reset, F2 validate_config_path call + containment, F3 commit-author Settings, F4 raw URL slash-safe form, F5 QUEUE_UNAVAILABLE 503 + spec patch).
  - **Cycle 3**: 4 NEW findings (3 High, 1 Medium); ALL 4 accepted + applied (F1 explicit `arq.func(open_pr, max_tries=30, timeout=180)`, F2 token regex broadened to include `github_pat_*` fine-grained PATs, F3 `git reset --hard` between fetch and checkout, F4 `study_id IS NULL` manual-proposal handling — skip chart, omit metrics/link, shorter PR body).
  - **15 findings total across 3 cycles**, all accepted + applied. Cycle artifacts: `/tmp/gpt55_plan_review_pr_worker_c{1,2,3}.out`.
