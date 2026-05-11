# Feature Specification — feat_github_pr_worker

**Date:** 2026-05-09 (review-and-patched 2026-05-12 after merges of `feat_study_lifecycle` Phase 2 / `feat_llm_judgments` / `feat_digest_proposal`)
**Status:** Approved (Opus + GPT-5.5 cross-model review; ready for `/pipeline`)
**Owners:** TBD
**Related docs:**
- [docs/02_product/mvp1-user-stories.md](../../mvp1-user-stories.md) — covers US-18, US-19
- [docs/01_architecture/apply-path.md](../../../01_architecture/apply-path.md) — Git PR workflow architecture
- [docs/01_architecture/data-model.md](../../../01_architecture/data-model.md) — `proposals`, `config_repos`, `clusters` (consumed)
- Depends on: [`infra_foundation`](../../../00_overview/implemented_features/2026_05_09_infra_foundation/feature_spec.md), [`infra_adapter_elastic`](../../../00_overview/implemented_features/2026_05_10_infra_adapter_elastic/feature_spec.md), [`feat_study_lifecycle`](../../../00_overview/implemented_features/2026_05_10_feat_study_lifecycle/feature_spec.md), [`feat_digest_proposal`](../../../00_overview/implemented_features/2026_05_11_feat_digest_proposal/feature_spec.md)
- Consumed by: [`feat_github_webhook`](../feat_github_webhook/feature_spec.md), [`feat_proposals_ui`](../feat_proposals_ui/feature_spec.md)

> **Source:** authored directly on 2026-05-09 (no `idea.md`); review-and-patched 2026-05-12 against the post-merge codebase. The 2026-05-12 pass applied 5 High + 13 Medium findings from a combined Opus + GPT-5.5 review. Decision log §19 documents the 3 product calls (PNG transport, auth model, base-URL setting).

---

## 1) Purpose

- **Problem:** A proposal sits as `status='pending'` after a study completes (the orchestrator inserted it in the same transaction as `complete_study`, and `feat_digest_proposal`'s worker populated `config_diff` + `metric_delta`). Without a worker that turns it into a real GitHub PR, the apply path is theoretical. The relevance engineer wants to click "Open PR" and see the diff land in the config repo within 60s.
- **Outcome:** `POST /api/v1/proposals/{id}/open_pr` enqueues a Git worker job that clones the configured repo, edits `*.params.json`, commits with a structured message, pushes a branch, opens a GitHub PR, attaches a parameter-importance chart by committing the PNG to the branch and referencing it from a PR comment, and updates the proposal with `pr_url` (GitHub `html_url`) + `pr_state='open'` + `status='pr_opened'`.
- **Non-goal:** No webhook receiver (that's `feat_github_webhook`). No GitHub App auth (MVP3 — see §19 decision log for why GitHub Checks attachments are deferred). No GitLab/Bitbucket (MVP3 — multi-provider abstraction). No template editing — only `*.params.json`. No PR-merge automation (humans merge in GitHub).

## 2) Current state audit

Post-merge state (2026-05-12; all dependencies shipped):

- `proposals`, `config_repos`, `clusters`, `digests` tables all exist with full MVP1 shapes. Verified columns:
  - `clusters.config_repo_id` (`String(36)`, nullable) and `clusters.config_path` (`String`, nullable) at [`backend/app/db/models/cluster.py`](../../../../backend/app/db/models/cluster.py).
  - `config_repos.{name, provider, repo_url, default_branch, pr_base_branch, auth_ref, webhook_secret_ref, webhook_registration_error}` at [`backend/app/db/models/config_repo.py`](../../../../backend/app/db/models/config_repo.py); `provider` has `CHECK (provider IN ('github'))`.
  - `proposals.{pr_url, pr_state, pr_merged_at, pr_open_error, rejected_reason}` at [`backend/app/db/models/proposal.py`](../../../../backend/app/db/models/proposal.py); `pr_state` accepts NULL (pre-PR-open) or one of `{open, closed, merged}` per the CHECK constraint.
  - `digests.{parameter_importance, suggested_followups}` at [`backend/app/db/models/digest.py`](../../../../backend/app/db/models/digest.py); `suggested_followups` is `TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[]` per cycle-1 F1 of the digest review.
- The `pr` Arq queue exists as a placeholder per `infra_foundation`; this feature adds the `open_pr` job.
- **`backend/app/api/v1/proposals.py` ALREADY EXISTS** (5 endpoints shipped by `feat_digest_proposal`: digest fetch + 4 proposal CRUD + reject). This feature ADDS the `POST /open_pr` endpoint to that existing router; it does NOT create a new router file.
- The advisory-lock idiom is established by `backend/workers/orchestrator.py:_try_replenish_xact_lock` and `backend/workers/digest.py:_acquire_digest_lock`: `pg_try_advisory_xact_lock` keyed on `blake2b(...)` with a disjoint string prefix per worker concern. This feature follows the same pattern with prefix `"config-repo:"`.
- No `gh` CLI in the worker container — this feature uses `httpx` for the GitHub REST API and shells out to `git` (which IS in the worker image per [`tech-stack.md`](../../../01_architecture/tech-stack.md)).

## 3) Scope

### In scope

- **Endpoint** `POST /api/v1/proposals/{id}/open_pr` (added to existing `backend/app/api/v1/proposals.py`):
  - Validates proposal is `pending` (404/409 otherwise) AND that `cluster.config_repo_id` is not NULL (422 `CLUSTER_HAS_NO_CONFIG_REPO`).
  - Validates the per-repo auth secret file (`./secrets/{config_repos.auth_ref}`) is non-empty (503 `GITHUB_NOT_CONFIGURED`).
  - Enqueues `open_pr(proposal_id)` Arq job with deterministic `_job_id=f"open_pr:{proposal_id}"` (Arq dedup; no duplicate paid run on a double POST).
  - Returns 202 with `{proposal_id, status: 'pending'}` (status flips to `pr_opened` only after the worker completes).
- **Worker job** `open_pr(proposal_id)` in `backend/workers/git_pr.py` per [`apply-path.md` §"PR creation flow"](../../../01_architecture/apply-path.md):
  - Pre-flight idempotency guard: re-read proposal status; bail if non-`pending` (operator-reject race; mirrors `feat_digest_proposal` cycle-3 F4 pattern).
  - Per-`config_repo_id` `pg_try_advisory_xact_lock` keyed on `blake2b("config-repo:{config_repo_id}", digest_size=8)` for serialization (xact-scoped; releases on commit/rollback). Lock prefix is disjoint from orchestrator's replenish lock and digest worker's lock.
  - Clone-or-pull the `config_repos.repo_url` to `./data/repo-clones/{config_repo_id}/` (UUID-keyed, NOT `config_repo.name`, to avoid filesystem-unsafe characters).
  - Branch creation, params-JSON edit (extract `.to` value at each path, deep-merge into the JSON), structured commit, push.
  - GitHub REST API PR creation.
  - Generate parameter-importance PNG via matplotlib; commit to `.relyloop/digest-charts/{study_id}.png` on the same branch; reference via Markdown raw-URL in the PR comment. Graceful text-only fallback if PNG generation or commit fails (the PR still opens, comment includes a Markdown table instead of the image).
  - Conditional UPDATE on `proposals` row: `WHERE id=:id AND status='pending'` (cycle-3 F4 pattern). On the rare race where the operator rejected mid-flight, log `pr_open_proposal_no_longer_pending` and skip the UPDATE; the rejection sticks.
- **Validation:** every key in `proposal.config_diff` (shape: `{path: {from: <old>, to: <new>}}`) must exist in the template's `declared_params`. Worker extracts `.to` at each path and writes that value into the JSON; if `.from` is supplied, the worker compares it to the current value in the params file and logs (does not block on) drift. Mismatched key → fails with `PARAM_NOT_IN_TEMPLATE`.
- **Error-mode handling:** if the GitHub API fails or the `*.params.json` doesn't exist in the repo, the proposal stays `pending` with `pr_open_error` populated for the UI to surface. (Column pre-created by `feat_study_lifecycle`; this feature only writes.)
- **Config-repo CRUD endpoints** (CREATE-only in MVP1; LIST + DETAIL):
  - `POST /api/v1/config-repos` — register a repo
  - `GET /api/v1/config-repos` (paginated)
  - `GET /api/v1/config-repos/{id}`
- **Settings addition:** `relyloop_base_url: str | None = Field(default=None, …)` on `backend/app/core/settings.py`. Used to construct the PR-body study link `f"{base_url}/studies/{study_id}"`. When `None`, the link is omitted from the PR body. Documented in `.env.example`.

### Out of scope

- Webhook receiver — `feat_github_webhook`.
- Polling reconciler — `feat_github_webhook` owns the polling loop.
- GitHub App auth + GitHub Checks attachments — MVP3 (see §19 decision log for the enterprise-compatibility reasoning).
- GitLab / Bitbucket — MVP3.
- Slack notifications on PR open — MVP2.
- PR-merge automation — never; humans merge.
- Template editing — never; only `*.params.json`.

### API convention check

Per [`api-conventions.md`](../../../01_architecture/api-conventions.md). All endpoints under `/api/v1/`. Cursor pagination on list endpoints. Webhook endpoint at `/webhooks/github` is owned by `feat_github_webhook`.

### Phase boundaries

Single-phase. The MVP1 deliverable: "click Open PR on a digest's proposal → within 60s see a real GitHub PR with the params diff, structured commit message, parameter-importance chart attached as a comment via committed PNG."

## 4) Product principles and constraints

- **The tool only edits `*.params.json` (and `.relyloop/digest-charts/*.png`).** Never templates. Never anything else in the repo. If the diff requires a NEW param the template doesn't expose, fail with `PARAM_NOT_IN_TEMPLATE`.
- **Per-repo serialization via Postgres advisory lock.** Concurrent proposals targeting the same repo serialize cleanly (xact-scoped); concurrent proposals to different repos run in parallel.
- **Per-proposal serialization via deterministic Arq `_job_id`.** A second POST to `/open_pr` while the first job is queued/running is dedup'd by Arq (no duplicate paid run); when the first job finishes successfully, subsequent POSTs see `status='pr_opened'` and return 409 `INVALID_STATE_TRANSITION`.
- **Branch names are unique by construction.** `relyloop/study-{study_id}` for study-backed proposals (one digest per study per `digests.study_id` UNIQUE; orchestrator inserts at most one pending proposal per study); `relyloop/proposal-{proposal_id}` for manual proposals (`POST /api/v1/proposals` from `feat_digest_proposal`'s FR-4 with `study_id=NULL`). If the branch already exists upstream (re-run after partial failure), fail with `BRANCH_EXISTS` rather than force-push.
- **PR creation is async + idempotent at the proposal level.** Re-issuing `POST /open_pr` on a proposal already in `pr_opened` returns 409 `INVALID_STATE_TRANSITION`. There's no "retry" endpoint — re-issuing on a `pending` proposal that previously failed (visible via `pr_open_error`) IS the retry path.
- **No force-push, no `--no-verify`.** Per global git-safety rules.

### Anti-patterns

- **Do not** edit the template YAML. Editing only `*.params.json` is the contract.
- **Do not** force-push. Failures result in `pr_open_error` populated; humans investigate.
- **Do not** create a PR without first validating that every key in `config_diff` is in the template's `declared_params`.
- **Do not** include the cluster's full schema or doc content in the PR body. Only metric deltas, top-10 trials, and the proposal-specific config diff.
- **Do not** assume `gh` CLI is installed. Use httpx async for the GitHub REST API; shell out to `git` (which IS in the image) for clone/branch/commit/push.
- **Do not** persist the tokenized git remote URL. After clone, immediately reset the remote URL to the tokenless `https://github.com/{owner}/{repo}` form so `.git/config` doesn't carry the secret on disk.

## 5) Assumptions and dependencies

- **Dependency: `infra_foundation`** — Merged via PR #4 (2026-05-09). Arq, Postgres, Pydantic Settings shipped. Note: `GITHUB_TOKEN_FILE` env var was introduced as a placeholder before this feature existed; this feature **retires** it in favor of per-repo `auth_ref` (see [`chore_infra_foundation_github_token_file_retirement`](../chore_infra_foundation_github_token_file_retirement/idea.md) for the cleanup ticket).
- **Dependency: `infra_adapter_elastic`** — Merged via PR #16 (2026-05-10). `clusters.config_repo_id` and `clusters.config_path` exist; `config_repos` table exists with full MVP1 shape including `auth_ref`.
- **Dependency: `feat_study_lifecycle`** — Merged via PRs #18 + #25 (2026-05-10/11). `proposals` table created with full MVP1 shape including `pr_url`, `pr_state`, `pr_merged_at`, `pr_open_error`, `rejected_reason`. This feature ADDS NO COLUMNS — it writes to existing ones only.
- **Dependency: `feat_digest_proposal`** — Merged via PR #41 (2026-05-11). The orchestrator pre-creates pending `proposals` rows in the same transaction as `complete_study`; `feat_digest_proposal`'s worker populates `config_diff` + `metric_delta`. This feature opens PRs against those rows. The `digests.parameter_importance` + `suggested_followups` columns are populated by the digest worker.
- **`git` binary** in the worker container image (standard in `python:3.12-slim`).
- **`matplotlib`** for the parameter-importance PNG (added to `pyproject.toml`).
- **Network egress to `github.com`** from the worker container.
- **Per-repo PAT secret files** mounted at `./secrets/{config_repos.auth_ref}` (operator-managed; pattern matches `infra_foundation` Rule #2 mounted-secrets convention).

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (clicks "Open PR" via UI / asks the chat agent to do it).
- **Secondary actor:** the GitHub reviewer (whoever the config repo's branch protection routes to — per umbrella §18, NOT a RelyLoop role).

### Authorization

N/A — single-tenant install, no auth surface. The per-repo GitHub PAT IS the authorization to GitHub; that's a capability of the install, scoped per `config_repos.auth_ref`.

### Audit events

N/A — `audit_log` lands at MVP2. When MVP2 ships, this feature's `proposal.pr_opened` and `proposal.pr_open_failed` will emit audit events.

## 7) Functional requirements

### FR-1: open_pr endpoint
- `POST /api/v1/proposals/{id}/open_pr` is added to the existing `backend/app/api/v1/proposals.py` router.
- Preflight order:
  1. Load proposal; 404 `PROPOSAL_NOT_FOUND` if missing.
  2. If `proposal.status != 'pending'` → 409 `INVALID_STATE_TRANSITION` (terminal states: `pr_opened` / `pr_merged` / `rejected`).
  3. Load `cluster = repo.get_cluster(proposal.cluster_id)`; if `cluster.config_repo_id IS NULL` → 422 `CLUSTER_HAS_NO_CONFIG_REPO`.
  4. Load `config_repo = repo.get_config_repo(cluster.config_repo_id)`; resolve the per-repo PAT by reading `./secrets/{config_repo.auth_ref}`. If the file is missing or empty → 503 `GITHUB_NOT_CONFIGURED`.
- Enqueues `open_pr(proposal_id)` on the `pr` Arq queue with `_job_id=f"open_pr:{proposal_id}"` for dedup.
- Returns HTTP 202 with `{proposal_id, status: 'pending', message: 'PR creation queued'}`.

### FR-2: open_pr worker
- The worker **MUST** be implemented at `backend/workers/git_pr.py`.
- The worker **MUST** acquire a Postgres advisory lock via `pg_try_advisory_xact_lock` keyed on `int.from_bytes(blake2b(f"config-repo:{config_repo_id}".encode(), digest_size=8).digest(), 'big', signed=True)` before touching the local clone. Lock is xact-scoped (releases on commit/rollback); releases automatically. If lock not acquired, log `pr_open_lock_contention` and return — another worker is in flight against the same config repo.
- The worker **MUST** re-read the proposal status inside the lock; if it's no longer `pending` (operator-reject race), log `pr_open_proposal_no_longer_pending` and return.
- The worker **MUST** resolve the GitHub token by reading `./secrets/{config_repo.auth_ref}`. The token **MUST NOT** be written to any log line, error message, PR body, commit message, subprocess argv, git stderr/stdout, or the `proposals` row.
- The worker **MUST** clone-or-pull the `config_repos.repo_url` to `./data/repo-clones/{config_repo_id}/` (UUID-keyed) using `https://x-access-token:<token>@github.com/<owner>/<repo>` URL scheme. **Immediately after clone**, the worker **MUST** reset the local remote URL to the tokenless `https://github.com/<owner>/<repo>` so `.git/config` does not persist the token on disk; subsequent fetches/pushes use the token via `-c http.extraheader="AUTHORIZATION: Bearer ${TOKEN}"` flag instead.
- The worker **MUST** create branch `relyloop/study-{study_id}` (or `relyloop/proposal-{proposal_id}` if `study_id` is null) off `config_repos.pr_base_branch`. If the branch already exists upstream, fail with `BRANCH_EXISTS`.
- The worker **MUST** resolve the template name as `query_templates.name` for `proposal.template_id`. The params file path is `<clusters.config_path>/<template_name>.params.json` (relative to the clone root). If the file doesn't exist → fail with `PARAMS_FILE_NOT_FOUND`.
- The worker **MUST** apply `proposal.config_diff` to the params JSON: at each dotted-path key, extract the `.to` value and deep-merge into the JSON. If `.from` is supplied, compare against the current value at that path and log (do not block on) any drift. If a `config_diff` key is not in the template's `declared_params`, fail with `PARAM_NOT_IN_TEMPLATE`.
- The worker **MUST** commit with the structured message format from [`apply-path.md` §"PR creation flow"](../../../01_architecture/apply-path.md). Commit author is `relyloop-bot@<install-domain>` (configured in the install runbook). Use `git commit -F <tempfile>` (not `-m` with shell-quoted args) to avoid argv injection.
- The worker **MUST** push the branch and open a PR via GitHub REST `POST /repos/{owner}/{repo}/pulls` with body containing:
  - Link back to RelyLoop study UI: `f"{settings.relyloop_base_url}/studies/{study_id}"` if `relyloop_base_url` is set, else omitted.
  - Top-10 trials table (Markdown).
  - Baseline-vs-achieved metrics table (Markdown).
  - Suggested follow-ups from `digests.suggested_followups` (Markdown bullet list).
- The worker **MUST** generate a parameter-importance bar chart (PNG, 800×600 monochrome, matplotlib) from `digests.parameter_importance`. The PNG is committed to the branch at `.relyloop/digest-charts/{study_id}.png` (separate commit, before the push), then referenced from a PR comment via `![Parameter importance](https://github.com/{owner}/{repo}/raw/{branch}/.relyloop/digest-charts/{study_id}.png)`. **Graceful degradation:** if PNG generation, commit, or comment-post fails, the worker logs `pr_open_chart_failed` at WARN, falls back to a Markdown table of the top-5 important params in the comment body, and continues. The PR open is not blocked by chart issues.
- The worker **MUST** update `proposals.pr_url` (storing GitHub's `html_url` field, not the API URL or tokenized clone URL) + `pr_state='open'` + `status='pr_opened'` atomically via a conditional UPDATE: `WHERE id=:proposal_id AND status='pending'`. If zero rows match (operator rejected mid-flight), log `pr_open_proposal_no_longer_pending` and skip the UPDATE; the rejection persists.
- On any failure, the worker **MUST** populate `proposals.pr_open_error` with the failure detail (token-redacted) and leave `status='pending'` (re-runnable).
- Notes: covers US-18, US-19.

### FR-3: Config-repo CRUD
- `POST /api/v1/config-repos` accepts `{name, repo_url, default_branch?, pr_base_branch?, auth_ref, webhook_secret_ref?}`. The `provider` column is **server-derived** from `repo_url` (regex match against `https://github.com/<owner>/<repo>(\.git)?` → `provider='github'`); not part of the payload.
  - Validates `repo_url` is a GitHub URL; rejects others with `UNSUPPORTED_PROVIDER` (GitLab + Bitbucket join MVP3).
  - Validates `auth_ref` points to an existing mounted secret file at `./secrets/{auth_ref}` (existence check at API level — non-empty contents are checked at PR-open time via `GITHUB_NOT_CONFIGURED`). If the secret file doesn't exist → 400 `AUTH_REF_NOT_FOUND`.
  - On success: returns 201 with the full `ConfigRepoDetail` row.
- `GET /api/v1/config-repos`: cursor-paginated list (cursor shape: `(created_at, id)` per `api-conventions.md`); 200 with `{data, next_cursor, has_more}` + `X-Total-Count` header.
- `GET /api/v1/config-repos/{id}` returns 200 with `ConfigRepoDetail`; 404 `CONFIG_REPO_NOT_FOUND` if missing.

### FR-4: pr_open_error population
- The `proposals.pr_open_error TEXT NULLABLE` column is pre-created by `feat_study_lifecycle`; this feature only writes to it.
- On a failed PR-open attempt, the worker **MUST** populate this column with a human-readable, **token-redacted** error message (e.g., `"GitHub API returned 422: PR already exists for branch relyloop/study-<sid>"`).
- On a successful retry that opens the PR, the column **MUST** be cleared to NULL.

### FR-5: GitHub PAT auth (per-repo)
- The worker **MUST** read the GitHub token from `./secrets/{config_repos.auth_ref}` for each PR-open invocation (per-repo auth model — see §19 decision log).
- The token **MUST** be passed via `Authorization: Bearer <pat>` header on REST calls.
- The token **MUST** be passed to `git clone` via the `https://x-access-token:<pat>@github.com/...` URL scheme; **immediately after clone**, the worker resets the local `.git/config` remote URL to the tokenless form (per FR-2). Subsequent fetches/pushes use `-c http.extraheader="AUTHORIZATION: Bearer ${TOKEN}"` so the token never lands in `.git/config`.
- The token **MUST NOT** appear in any log line, error message, PR body, commit message, subprocess argv (use `-F <tempfile>` for commit; pass token via env var or extraheader, never as a positional arg), git stderr/stdout (capture + redact before logging), or the `proposals` row. Use a redaction filter on structlog for any field matching the GitHub token regex (`gh[ps]_[A-Za-z0-9_]{36,}`).
- **Retirement note:** the global `GITHUB_TOKEN_FILE` env var introduced by `infra_foundation` is **deprecated** by this feature in favor of per-repo `auth_ref`. The deprecation cleanup is tracked at [`chore_infra_foundation_github_token_file_retirement`](../chore_infra_foundation_github_token_file_retirement/idea.md).

## 8) API and data contract baseline

### 8.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/proposals/{id}/open_pr` | Enqueue PR creation | `PROPOSAL_NOT_FOUND` (404), `INVALID_STATE_TRANSITION` (409), `CLUSTER_HAS_NO_CONFIG_REPO` (422), `GITHUB_NOT_CONFIGURED` (503), `QUEUE_UNAVAILABLE` (503; plan-cycle-2 F5) |
| `POST` | `/api/v1/config-repos` | Register a config repo | `VALIDATION_ERROR` (422), `UNSUPPORTED_PROVIDER` (400), `CONFIG_REPO_NAME_TAKEN` (409), `AUTH_REF_NOT_FOUND` (400) |
| `GET` | `/api/v1/config-repos` | Cursor-paginated list (`X-Total-Count`) | `VALIDATION_ERROR` (422; bad cursor) |
| `GET` | `/api/v1/config-repos/{id}` | Detail | `CONFIG_REPO_NOT_FOUND` (404) |

### 8.2 Pydantic schemas (request/response shapes)

Pydantic v2 `BaseModel` subclasses defined in `backend/app/api/v1/schemas.py` (existing module; this feature appends).

```python
# Open PR
class OpenPrResponse(BaseModel):
    proposal_id: str
    status: Literal["pending"]   # always 'pending' at enqueue time
    message: str

# Config repo
class CreateConfigRepoRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
    repo_url: str = Field(min_length=1, max_length=512)
    default_branch: str = Field(default="main", min_length=1, max_length=128)
    pr_base_branch: str = Field(default="main", min_length=1, max_length=128)
    auth_ref: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    webhook_secret_ref: str | None = Field(default=None, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")

class ConfigRepoDetail(BaseModel):
    id: str
    name: str
    provider: Literal["github"]   # MVP1 enum; extends MVP3
    repo_url: str
    default_branch: str
    pr_base_branch: str
    auth_ref: str
    webhook_secret_ref: str | None
    webhook_registration_error: str | None
    created_at: datetime

class ConfigReposListResponse(BaseModel):
    data: list[ConfigRepoDetail]
    next_cursor: str | None
    has_more: bool
```

Standard error envelope for ALL endpoints (matches `api-conventions.md` shared envelope used by every other v1 router):

```python
{"detail": {"error_code": "<MACHINE_READABLE>", "message": "<human>", "retryable": <bool>}}
```

### 8.4 Enumerated value contracts

Per CLAUDE.md "Enumerated Value Contract Discipline" — every wire value cites its backend source.

| Field | Accepted values | Backend source of truth |
|---|---|---|
| `config_repos.provider` | `github` | `backend/app/db/models/config_repo.py` `CHECK (provider IN ('github'))` (MVP3 adds `gitlab`, `bitbucket`) |
| `proposals.pr_state` | `open`, `closed`, `merged`, `null` | `backend/app/db/models/proposal.py` `CHECK (pr_state IS NULL OR pr_state IN ('open', 'closed', 'merged'))` — explicitly nullable pre-PR-open |
| `proposals.status` | `pending`, `pr_opened`, `pr_merged`, `rejected` | `backend/app/db/models/proposal.py` `CHECK proposals_status_check` |

### 8.5 Error code catalog

| Code | HTTP Status | Meaning | Retryable |
|---|---|---|---|
| `GITHUB_NOT_CONFIGURED` | 503 | Per-repo PAT secret file at `./secrets/{auth_ref}` is missing or empty | true |
| `QUEUE_UNAVAILABLE` | 503 | Arq enqueue failed (Redis unreachable, pool not built). Operator retries after `make up` confirms queue health. (Plan-cycle-2 F5: this feature has no boot-scan fallback so silent enqueue failure must surface as a loud 503 rather than always-202.) | true |
| `PROPOSAL_NOT_FOUND` | 404 | Proposal ID not found | false |
| `INVALID_STATE_TRANSITION` | 409 | `open_pr` on a `pr_opened` / `pr_merged` / `rejected` proposal | false |
| `CLUSTER_HAS_NO_CONFIG_REPO` | 422 | Cluster's `config_repo_id` is NULL — operator must register a config_repo first via `POST /api/v1/config-repos` and update the cluster | false |
| `CONFIG_REPO_NOT_FOUND` | 404 | Config repo ID not found | false |
| `CONFIG_REPO_NAME_TAKEN` | 409 | Name conflict (UNIQUE on `config_repos.name`) | false |
| `UNSUPPORTED_PROVIDER` | 400 | `repo_url` not GitHub (GitLab + Bitbucket arrive MVP3) | false |
| `AUTH_REF_NOT_FOUND` | 400 | `auth_ref` points to a missing mounted secret file at `./secrets/{auth_ref}` | true |
| `VALIDATION_ERROR` | 422 | Pydantic body validation failure or bad cursor | false |

**Worker-side terminal reasons** (logged at WARN; surfaced via `proposals.pr_open_error`, not endpoint-visible because the worker is async):

| Code | Meaning |
|---|---|
| `PARAM_NOT_IN_TEMPLATE` | `config_diff` key not in `declared_params` |
| `PARAMS_FILE_NOT_FOUND` | `*.params.json` missing in the repo at the expected path |
| `BRANCH_EXISTS` | Branch already exists upstream |
| `GITHUB_API_FAILED` | GitHub REST returned non-2xx after retries |
| `CLONE_FAILED` | git clone failed (network, disk, permissions) |

The operator-facing surfacing for worker-side terminals happens via `GET /api/v1/proposals/{id}` — the existing detail endpoint returns `pr_open_error` populated until the operator retries successfully.

## 9) Data model and state transitions

This feature creates NO new tables and ADDS NO new columns. All schema is pre-created by `feat_study_lifecycle` (proposals) and `infra_adapter_elastic` (config_repos). It DOES add one Settings field (`relyloop_base_url`).

### State transitions

`proposals.status`:
- `pending → pr_opened` (on successful PR open).
- `pending → pending` (on failed PR open, with `pr_open_error` populated; operator retries via re-issuing `POST /open_pr`).
- `pr_opened → pr_merged` is owned by `feat_github_webhook`.

`proposals.pr_state`:
- `null → open` (on successful PR open).
- `open → closed | merged` is owned by `feat_github_webhook`.

## 10) Security, privacy, and compliance

- **Threats:**
  1. GitHub token leak in PR bodies, commit messages, logs, subprocess argv, git stderr/stdout, `.git/config`, or `proposals.pr_open_error`. **Mitigation:** structlog redaction filter for any string matching the GitHub token regex (`gh[ps]_[A-Za-z0-9_]{36,}`); PR body templates never reference the token; commit author is the bot account, not the operator; subprocess args use `-F <tempfile>` for commit and `-c http.extraheader="AUTHORIZATION: Bearer ${TOKEN}"` (env-substituted, not argv-substituted) for fetch/push; `.git/config` remote URL is reset to the tokenless form immediately after clone; `pr_open_error` writes pass through the same redaction filter.
  2. Path traversal via crafted `clusters.config_path` (e.g., `../../etc/passwd`). **Mitigation:** validate `config_path` is a relative path containing only `[A-Za-z0-9_/.-]` at cluster registration time.
  3. Repo-content injection via `proposal.config_diff`. **Mitigation:** the worker writes ONLY `*.params.json` (and `.relyloop/digest-charts/*.png`); the diff is JSON-merged (no string interpolation into shell commands); `git commit` uses the `-F` flag with a temp file, not `-m` with shell-quoted args.
  4. Repo cloning under attacker control. **Mitigation:** `repo_url` is GitHub-only and validated at registration; clones happen via HTTPS with token-in-URL auth; SSH not supported in MVP1.
  5. PNG-comment image rendering hostile content. **Mitigation:** matplotlib-generated PNG only; no operator-supplied image bytes; the chart is regenerated each run from `digests.parameter_importance` (operator-controlled JSONB), not from external sources.
- **Secrets handling:** per-repo PAT secret files at `./secrets/{auth_ref}` only. No bare env vars (per CLAUDE.md Rule #2).
- **Auditability:** N/A — `audit_log` is MVP2.

## 11) UX flows and edge cases

This feature has no UI; "Open PR" button lives in `feat_proposals_ui`.

### Edge/error flows

- **Cluster's `config_repo_id` is NULL** (cluster registered without a repo). `POST /open_pr` returns 422 `CLUSTER_HAS_NO_CONFIG_REPO`.
- **PR already exists for the branch.** `BRANCH_EXISTS` populated; `pr_open_error` reflects the GitHub 422 message; status stays `pending`. Engineer can investigate via the GitHub UI and either close the existing PR or modify the proposal.
- **GitHub API rate-limit during PR open.** httpx retries 3× with backoff; final failure populates `pr_open_error: "GitHub rate limit exceeded; retry in <duration>"`.
- **Disk full during clone.** Clone fails; `pr_open_error: "git clone failed: <stderr>"` (token-redacted).
- **Operator rejects mid-flight.** Worker enqueues, starts clone/edit/push/PR-open, then operator rejects via `POST /api/v1/proposals/{id}/reject` (status `pending → rejected`). Worker's final conditional UPDATE `WHERE status='pending'` matches zero rows; logs `pr_open_proposal_no_longer_pending`; PR is open on GitHub but the proposal is `rejected`. Operator sees both states in the UI; closes the GitHub PR manually.
- **PNG generation fails (matplotlib error).** Worker logs `pr_open_chart_failed`, falls back to a Markdown top-5 important params table in the comment, continues.
- **Concurrent POST /open_pr on the same proposal.** First POST enqueues `_job_id="open_pr:{proposal_id}"`. Second POST: Arq dedup means the second enqueue is a no-op (no duplicate worker run); the API returns 202 with the same payload. After the first job finishes successfully, subsequent POSTs see `status='pr_opened'` and return 409 `INVALID_STATE_TRANSITION`.

## 12) Given/When/Then acceptance criteria

### AC-1: Open PR end-to-end (happy path)

- Given a `pending` proposal with `study_id`, `cluster_id` linked to a `config_repos` row pointing at the test repo `SoundMindsAI/relyloop-test-configs`, `config_diff = {"field_boosts.title": {"from": 2.0, "to": 4.5}}`, the digest's `parameter_importance` populated, the per-repo PAT mounted at `./secrets/{auth_ref}`, `relyloop_base_url` set in Settings.
- When the operator POSTs to `/api/v1/proposals/{id}/open_pr`.
- Then within 60s: a GitHub PR appears against the test repo on branch `relyloop/study-{study_id}`. The diff touches: (a) the `*.params.json` file with `field_boosts.title` updated from `2.0` to `4.5` (the `.to` value extracted), and (b) `.relyloop/digest-charts/{study_id}.png` (the parameter-importance chart). The commit message follows the structured format. The PR body includes the metric delta + top-10 trials + suggested follow-ups + link back to `{relyloop_base_url}/studies/{study_id}`. A PR comment references the chart via Markdown raw-URL. The proposal row has `status='pr_opened'`, `pr_url` populated with GitHub's `html_url`, `pr_state='open'`, `pr_open_error=NULL`. **Test layers:** integration tests via cassette-replayed GitHub API (no network required in CI); release-gate end-to-end test against the live `SoundMindsAI/relyloop-test-configs` repo runs nightly + on tagged releases (separate workflow, requires the test PAT secret).

### AC-2: Reject if per-repo PAT missing

- Given `./secrets/{config_repo.auth_ref}` is empty or missing.
- When `POST /open_pr` is called.
- Then HTTP 503 with `error_code: GITHUB_NOT_CONFIGURED`. No job enqueued; no proposal mutation.

### AC-3: PARAM_NOT_IN_TEMPLATE failure

- Given a proposal with `config_diff = {"nonexistent_param": {"from": 1, "to": 2}}` (param not in the template's `declared_params`).
- When the worker runs.
- Then no PR is created; `proposals.pr_open_error = "config_diff key 'nonexistent_param' is not in template's declared_params"`; `status='pending'`. Re-running `open_pr` after fixing the proposal (or template) succeeds.

### AC-4: BRANCH_EXISTS failure

- Given a proposal where the branch `relyloop/study-{study_id}` already exists upstream (e.g., a prior failed run).
- When `open_pr` runs.
- Then no force-push; `pr_open_error = "Branch relyloop/study-{study_id} already exists upstream"`; `status='pending'`.

### AC-5: Per-repo serialization

- Given two `pending` proposals targeting the same `config_repo_id`.
- When both `POST /open_pr` are called within 1s.
- Then the worker processes them sequentially (xact-scoped advisory lock keyed on `blake2b("config-repo:{config_repo_id}")`); both PRs eventually open with no race conditions on the local clone or the `*.params.json` file. The second PR's branch is `relyloop/study-{study2}` (different) and its diff applies on top of `pr_base_branch`, NOT on top of the first PR's branch.

### AC-6: Re-issue on already-opened proposal

- Given a proposal with `status='pr_opened'`.
- When `POST /open_pr` is called again.
- Then HTTP 409 with `error_code: INVALID_STATE_TRANSITION`. No worker job enqueued.

### AC-7: GitHub token never leaks (extended coverage)

- Given a successful PR open + a failed PR open (covering both code paths).
- When the operator inspects: PR body, commit message, PR title, the `proposals` row (especially `pr_url` and `pr_open_error`), all worker log lines for the job, captured subprocess stdout/stderr from `git clone`/`fetch`/`commit`/`push`, and the local `.git/config` after clone.
- Then no log/message/field/argv/file contains the GitHub token (no string matching `gh[ps]_[A-Za-z0-9_]{36,}`). Specifically, `.git/config` after clone contains `url = https://github.com/<owner>/<repo>` (tokenless), not `url = https://x-access-token:gh...@github.com/...`.

### AC-8: Config-repo registration validates GitHub-only

- Given a `POST /api/v1/config-repos` with `repo_url = "https://gitlab.com/foo/bar"`.
- When the request lands.
- Then HTTP 400 with `error_code: UNSUPPORTED_PROVIDER` and message naming MVP3 as the activation point.

### AC-9: AUTH_REF_NOT_FOUND validation at register time

- Given a `POST /api/v1/config-repos` with `auth_ref = "no-such-secret"` and no file at `./secrets/no-such-secret`.
- When the request lands.
- Then HTTP 400 with `error_code: AUTH_REF_NOT_FOUND`. No row inserted.

### AC-10: Operator-reject race (mid-flight rejection)

- Given a `pending` proposal whose worker job is in flight (clone done, params edited, push pending).
- When the operator calls `POST /api/v1/proposals/{id}/reject` between the worker's status re-read and its final UPDATE.
- Then the conditional UPDATE `WHERE status='pending'` matches zero rows; the worker logs `pr_open_proposal_no_longer_pending` at INFO; the proposal stays `rejected` with `rejected_reason` populated; the GitHub PR is open on the remote (operator must close it manually); `pr_url` is NOT written to the proposal row.

### AC-11: Chart fallback on PNG failure

- Given a `pending` proposal whose `digests.parameter_importance` triggers a matplotlib error (e.g., empty importance map after the worker's defensive `{}` fallback).
- When the worker runs.
- Then the PR opens normally; the PR comment contains a Markdown table of the top-5 most important params (or "Parameter importance unavailable" if the map is genuinely empty); the worker logs `pr_open_chart_failed` at WARN; `status='pr_opened'`.

### AC-12: Idempotent dedup on double POST

- Given a `pending` proposal.
- When `POST /open_pr` is called twice within 100ms.
- Then both calls return 202 with the same response body. Arq's deterministic `_job_id="open_pr:{proposal_id}"` dedup means the worker runs exactly once; CI integration test asserts exactly one PR is opened on the test repo.

## 13) Non-functional requirements

- **Performance:** PR-open completes in <60s p99 (clone <10s for ≤10MB repos, file edit + commit <2s, GitHub PR API <3s, comment with PNG <5s). Subsequent re-clones (incremental pull) <5s.
- **Reliability:** Per-repo lock prevents corrupted-clone races. Per-proposal Arq dedup prevents double-paid runs. Failed runs leave the proposal `pending` with a clear (token-redacted) `pr_open_error`.
- **Operability:** Every PR-open invocation logs `proposal_id`, `study_id`, `config_repo_id`, `branch_name`, `duration_ms`, `pr_url` (on success) at INFO. Failures log at WARN with the error reason. Worker-side `event_type` markers: `pr_open_lock_contention`, `pr_open_proposal_no_longer_pending`, `pr_open_chart_failed`, `pr_open_complete`, `pr_open_failed`.
- **Settings:** new `relyloop_base_url: str | None = Field(default=None, description="Base URL of the operator's RelyLoop install for PR-body links. None → links omitted.")` on `backend/app/core/settings.py`. Documented in `.env.example`.

## 14) Test strategy requirements

- **Unit tests** (`backend/tests/unit/workers/`):
  - `test_params_merge.py` — `config_diff` `{from, to}` extraction + deep-merge against representative `*.params.json` files; rejects keys not in `declared_params`.
  - `test_commit_message.py` — structured commit message format with various inputs (study, manual proposal, etc.).
  - `test_token_redaction.py` — structlog redaction filter strips GitHub tokens from log records, exception messages, and structured-log `extra={}` dicts.
  - `test_pr_body_render.py` — PR body construction with + without `relyloop_base_url`; asserts link presence/absence.
- **Integration tests** (`backend/tests/integration/`):
  - `test_pr_open_happy_path.py` — full flow against a cassette-replayed GitHub API; asserts AC-1 minus the actual GitHub side effects.
  - `test_pr_open_param_not_in_template.py` — AC-3.
  - `test_pr_open_branch_exists.py` — AC-4.
  - `test_pr_open_serialization.py` — AC-5 (two parallel jobs, advisory lock works).
  - `test_pr_open_rejected_after_opened.py` — AC-6.
  - `test_pr_open_no_config_repo.py` — `CLUSTER_HAS_NO_CONFIG_REPO` (FR-1 preflight).
  - `test_pr_open_auth_ref_missing.py` — `AUTH_REF_NOT_FOUND` (FR-3) + `GITHUB_NOT_CONFIGURED` (FR-1 preflight).
  - `test_pr_open_reject_race.py` — AC-10 (operator-reject mid-flight; conditional UPDATE).
  - `test_pr_open_chart_fallback.py` — AC-11 (PNG generation fails → text-only fallback).
  - `test_pr_open_dedup.py` — AC-12 (double POST → exactly one worker run via Arq `_job_id`).
  - `test_config_repo_crud.py` — AC-8 + AC-9 (provider derivation, GitLab rejection, missing auth_ref).
- **Contract tests** (`backend/tests/contract/`):
  - `test_github_pr_worker_api_contract.py` — OpenAPI parity for the 4 endpoints + static error-code grep over §8.5 catalog (router-side codes) + worker-source grep for the 5 worker-side terminal reasons.
  - `test_token_never_leaks.py` — assertion sweep over PR body / commit message / proposal row / worker logs / subprocess stdout+stderr / `.git/config` after clone (AC-7).
- **Release-gate tests** (separate GitHub Actions workflow, runs nightly + on tagged releases; not in PR CI):
  - `test_pr_open_live_repo.py` — AC-1 verified against the live `SoundMindsAI/relyloop-test-configs` repo using the dedicated test PAT (mounted as a CI secret). Cleanup task closes the test PR + deletes the branch after assertion.
- **E2E tests:** N/A (UI in `feat_proposals_ui`).

## 15) Documentation update requirements

- `docs/01_architecture/apply-path.md` already documents the workflow; update if implementation diverges.
- `docs/03_runbooks/`: add `pr-open-debugging.md` — investigate `pr_open_error`, manually clean up an orphan branch, rotate per-repo PATs, force-regenerate a chart PNG.
- `docs/04_security/`: add `github-token-handling.md` — token storage (per-repo `auth_ref`), rotation procedures, scope requirements (`contents:write`, `pull_requests:write`, optionally `workflow:write`), the `.git/config` reset rationale.
- `docs/02_product/mvp1-user-stories.md`: mark US-18 / US-19 as "(Implemented — `feat_github_pr_worker`)".
- `.env.example`: document new `RELYLOOP_BASE_URL` setting.

## 16) Rollout and migration readiness

- **Feature flags:** None.
- **Migration/backfill:** None — this feature creates no tables and adds no columns. The `relyloop_base_url` Settings field defaults to `None`; no migration needed.
- **Operational readiness gates:** PR-open against `SoundMindsAI/relyloop-test-configs` completes in <60s; runbook for `pr_open_error` debugging exists; per-repo `auth_ref` documented in install runbook.
- **Release gate:** `feat_github_webhook` author confirms the polling-reconciler interface (proposals with `status='pr_opened'` and `pr_state='open'` >15 min old) is queryable.

## 17) Traceability matrix

| FR ID | AC IDs | Stories (TBD) | Test files | Docs |
|---|---|---|---|---|
| FR-1 (open_pr endpoint) | AC-1, AC-2, AC-6, AC-12 | TBD | `tests/integration/test_pr_open_happy_path.py`, `test_pr_open_rejected_after_opened.py`, `test_pr_open_no_config_repo.py`, `test_pr_open_auth_ref_missing.py`, `test_pr_open_dedup.py` | runbook |
| FR-2 (open_pr worker) | AC-1, AC-3, AC-4, AC-5, AC-10, AC-11 | TBD | `tests/integration/test_pr_open_*.py` (most files) | runbook |
| FR-3 (config-repo CRUD) | AC-8, AC-9 | TBD | `tests/integration/test_config_repo_crud.py` | runbook |
| FR-4 (pr_open_error col) | AC-3, AC-4 | TBD | `tests/integration/test_pr_open_param_not_in_template.py`, `test_pr_open_branch_exists.py` | — |
| FR-5 (per-repo PAT auth + redaction) | AC-2, AC-7, AC-9 | TBD | `tests/unit/workers/test_token_redaction.py`, `tests/contract/test_token_never_leaks.py` | security doc |

## 18) Definition of feature done

- [ ] AC-1 through AC-12 pass.
- [ ] All test layers green; ≥80% coverage on `backend/workers/git_pr.py`, `backend/app/api/v1/proposals.py` (open_pr endpoint), `backend/app/api/v1/config_repos.py`.
- [ ] PR-open against `SoundMindsAI/relyloop-test-configs` completes in <60s (recorded benchmark in the release-gate workflow).
- [ ] `docs/03_runbooks/pr-open-debugging.md` and `docs/04_security/github-token-handling.md` merged.
- [ ] `chore_infra_foundation_github_token_file_retirement` idea file exists (the cleanup ticket for the deprecated env var).
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None — all resolved (see Decision log).

### Decision log

- 2026-05-09 — Token-via-URL for `git clone` (`https://x-access-token:<pat>@github.com/...`) — per [`apply-path.md` §"GitHub auth"](../../../01_architecture/apply-path.md). Alternative (SSH key) is rejected for MVP1 (more setup for the operator).
- 2026-05-09 — No force-push, no `--no-verify` — per global git-safety rules.
- 2026-05-09 — `proposals.pr_open_error` column owned by `feat_study_lifecycle` (full MVP1 schema there) — this feature only writes; no migration here.
- 2026-05-09 — Parameter-importance PNG: **800×600 horizontal bar chart, monochrome** (matplotlib default + shadcn-friendly grayscale; no dependency on the `feat_studies_ui` Recharts color palette).
- 2026-05-09 — `CLUSTER_HAS_NO_CONFIG_REPO` error code added to §8.5 (referenced in §11 edge flows).
- 2026-05-09 — Test config repo: **public `SoundMindsAI/relyloop-test-configs`** with a dedicated test PAT scoped only to it. Same repo serves `chore_tutorial_polish` for the tutorial's apply-PR step.
- **2026-05-12 — PNG transport: commit to branch over GitHub Checks attachments** (Opus + GPT-5.5 spec review; product call). Checks attachments require GitHub App auth (PAT cannot create check runs); GitHub Apps are explicitly deferred to MVP3. Even if Apps were available, GitHub Enterprise Server <3.0 lacks the Checks API and many enterprise org policies block third-party Apps. Commit-to-branch works on every GitHub deployment (.com / GHES / GHE Cloud) with the existing `contents:write` PAT scope. PNG lands at `.relyloop/digest-charts/{study_id}.png` so operators who want to gitignore tool artifacts can. Graceful text-only fallback ensures the PR always opens. Post-MVP3 path: opt-in `config_repos.use_checks_api` flag once App auth lands.
- **2026-05-12 — Per-repo `auth_ref` over global `GITHUB_TOKEN_FILE`** (Opus + GPT-5.5 spec review; product call). Three reasons: (1) **secret rotation blast radius** — enterprises rotate PATs on quarterly compliance cadences; per-repo means rotating one PAT doesn't impact unrelated config repos; (2) **least-privilege per repo** — different repos may need different scopes (some need `workflow:write`, some don't); (3) **the `auth_ref` column is already NOT NULL** per `infra_adapter_elastic`'s schema. The `infra_foundation`-introduced `GITHUB_TOKEN_FILE` env var is **deprecated** by this feature; cleanup tracked at [`chore_infra_foundation_github_token_file_retirement`](../chore_infra_foundation_github_token_file_retirement/idea.md).
- **2026-05-12 — `RELYLOOP_BASE_URL` Settings field added to this feature** (Opus + GPT-5.5 spec review; product call). FR-2 PR body wants a study-detail link but no such setting existed. Adding `relyloop_base_url: str | None = Field(default=None, …)` to `backend/app/core/settings.py` as part of this feature's scope. When `None`, the link is omitted from the PR body (graceful degradation for installs that haven't configured it yet).
- **2026-05-12 — Operator-reject race handled via conditional UPDATE** (`WHERE id=:id AND status='pending'`) mirroring `feat_digest_proposal` cycle-3 F4. Worker logs `pr_open_proposal_no_longer_pending` if zero rows match; the GitHub PR is open on the remote but `pr_url` is not written to the now-rejected proposal row. Operator closes the orphan PR manually.
- **2026-05-12 — Per-proposal Arq dedup via deterministic `_job_id="open_pr:{proposal_id}"`.** Mirrors the `feat_llm_judgments` cycle-4 C4-F1 pattern. Combined with the per-`config_repo_id` advisory lock (which serializes ACROSS proposals in the same repo), this gives both per-proposal and per-repo concurrency guarantees.
- **2026-05-12 — `.git/config` remote URL reset post-clone** to the tokenless form. Subsequent fetches/pushes use `-c http.extraheader="AUTHORIZATION: Bearer ${TOKEN}"` so the PAT never lands on disk in the local clone. AC-7 verifies this explicitly.
- **2026-05-12 — Clone path uses `{config_repo_id}` (UUID), not `{config_repo.name}`,** to avoid filesystem-unsafe characters in operator-supplied repo names.
- **2026-05-12 — `provider` server-derived from `repo_url`,** not part of the create payload. The CHECK constraint already restricts to `'github'` for MVP1; adding `provider` to the API would be redundant validation surface.
- **2026-05-12 — `QUEUE_UNAVAILABLE` (503) added** during plan-gen cycle-2 review (plan F5). Unlike the digest worker, this feature has no boot-scan fallback for missed enqueues — a silent best-effort enqueue would leave the proposal `pending` indefinitely with no `pr_open_error` to surface the failure. Better to fail loud at the API: 503 retryable=true; operator retries after confirming queue health.
- **2026-05-12 — Commit author identity via Settings** (plan F3): `Settings.relyloop_git_author_name` (default `"relyloop-bot"`) + `Settings.relyloop_git_author_email` (default placeholder; operator overrides per FR-2 "commit author is `relyloop-bot@<install-domain>`"). Worker passes via `GIT_AUTHOR_*` / `GIT_COMMITTER_*` env vars to the commit subprocess so commits carry the bot identity, not the worker host's global git config.
