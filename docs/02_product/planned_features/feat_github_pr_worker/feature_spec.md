# Feature Specification — feat_github_pr_worker

**Date:** 2026-05-09
**Status:** Draft
**Owners:** TBD
**Related docs:**
- [docs/02_product/mvp1-user-stories.md](../../mvp1-user-stories.md) — covers US-18, US-19
- [docs/01_architecture/apply-path.md](../../../01_architecture/apply-path.md) — Git PR workflow architecture
- [docs/01_architecture/data-model.md](../../../01_architecture/data-model.md) — `proposals`, `config_repos`, `clusters` (consumed)
- Depends on: [`infra_foundation`](../infra_foundation/feature_spec.md), [`infra_adapter_elastic`](../infra_adapter_elastic/feature_spec.md), [`feat_digest_proposal`](../feat_digest_proposal/feature_spec.md)
- Consumed by: [`feat_github_webhook`](../feat_github_webhook/feature_spec.md), [`feat_proposals_ui`](../feat_proposals_ui/feature_spec.md)

---

## 1) Purpose

- **Problem:** A proposal sits as `status='pending'` after a study completes; without a worker that turns it into a real GitHub PR, the apply path is theoretical. The relevance engineer wants to click "Open PR" and see the diff land in the config repo within 60s.
- **Outcome:** `POST /api/v1/proposals/{id}/open_pr` enqueues a Git worker job that clones the configured repo, edits `*.params.json`, commits with a structured message, pushes a branch, opens a GitHub PR, attaches a parameter-importance chart as a comment, and updates the proposal with `pr_url` + `pr_state='open'`.
- **Non-goal:** No webhook receiver (that's `feat_github_webhook`). No GitHub App auth (MVP3). No GitLab/Bitbucket (MVP3 — multi-provider abstraction). No template editing — only `*.params.json`. No PR-merge automation (humans merge in GitHub).

## 2) Current state audit

After dependencies ship:
- `proposals`, `config_repos`, `clusters` tables exist (created by `feat_digest_proposal` + `infra_adapter_elastic`).
- The `proposals.pr_url`, `pr_state`, `pr_merged_at`, `rejected_reason` columns already exist (created by `feat_digest_proposal` per its open question #2 decision); this feature populates them.
- The `pr` Arq queue exists as a placeholder (per `infra_foundation`); this feature adds the `open_pr` job.
- No `gh` CLI assumed installed in the worker container — this feature uses `httpx` for the GitHub REST API and shells out to `git` (which IS in the worker image per [`tech-stack.md`](../../../01_architecture/tech-stack.md)).

## 3) Scope

### In scope

- API endpoint `POST /api/v1/proposals/{id}/open_pr`:
  - Validates proposal is `pending` (404/409 otherwise)
  - Enqueues `open_pr(proposal_id)` Arq job
  - Returns 202 with `{proposal_id, status: 'pending'}` (status flips to `pr_opened` only after the worker completes)
- Worker job `open_pr(proposal_id)` in `backend/worker/git_pr.py` per [`apply-path.md` §"PR creation flow"](../../../01_architecture/apply-path.md):
  - Clone-or-pull the `config_repos` row's repo into `./data/repo-clones/<repo_name>/`
  - Per-`config_repo_id` Postgres advisory lock for serialization
  - Branch creation, params-JSON edit, structured commit, push
  - GitHub REST API PR creation
  - Attach parameter-importance chart as a PR comment (PNG generated from `digests.parameter_importance` via `matplotlib`)
  - Update `proposals.pr_url` + `pr_state='open'`
- Validation: every key in `proposal.config_diff` must exist in the template's `declared_params` (rejects with `PARAM_NOT_IN_TEMPLATE`).
- Error-mode handling: if the GitHub API fails or the `*.params.json` doesn't exist in the repo, the proposal stays `pending` with a `pr_open_error` field populated for the UI to surface (column added in this feature's migration).
- Config-repo CRUD endpoints (CREATE-only in MVP1; LIST + DETAIL):
  - `POST /api/v1/config-repos` — register a repo
  - `GET /api/v1/config-repos` (paginated)
  - `GET /api/v1/config-repos/{id}`

### Out of scope

- Webhook receiver — `feat_github_webhook`.
- Polling reconciler — `feat_github_webhook` owns the polling loop.
- GitHub App auth — MVP3.
- GitLab / Bitbucket — MVP3.
- Slack notifications on PR open — MVP2.
- PR-merge automation — never; humans merge.
- Template editing — never; only `*.params.json`.

### API convention check

Per [`api-conventions.md`](../../../01_architecture/api-conventions.md). All endpoints under `/api/v1/`. Cursor pagination on list endpoints. Webhook endpoint at `/webhooks/github` is owned by `feat_github_webhook`.

### Phase boundaries

Single-phase. The MVP1 deliverable: "click Open PR on a digest's proposal → within 60s see a real GitHub PR with the params diff, structured commit message, parameter-importance chart attached as a comment."

## 4) Product principles and constraints

- **The tool only edits `*.params.json`.** Never templates. Never anything else in the repo. If the diff requires a NEW param the template doesn't expose, fail with `PARAM_NOT_IN_TEMPLATE`.
- **Per-repo serialization via Postgres advisory lock.** Concurrent proposals targeting the same repo serialize cleanly; concurrent proposals to different repos run in parallel.
- **Branch names are unique by construction.** `relyloop/study-{study_id}` (or `relyloop/proposal-{proposal_id}` for manual proposals). If the branch already exists upstream (re-run after partial failure), fail with `BRANCH_EXISTS` rather than force-push (per the project's no-force-push principle from [the Git Safety Protocol](../../../../README.md)).
- **PR creation is async + idempotent at the proposal level.** Re-issuing `POST /open_pr` on a proposal already in `pr_opened` returns 409 `INVALID_STATE_TRANSITION`. There's no "retry" endpoint — re-issuing on a `pending` proposal that previously failed (visible via `pr_open_error`) IS the retry path.
- **No force-push, no `--no-verify`.** Per global git-safety rules.

### Anti-patterns

- **Do not** edit the template YAML. Editing only `*.params.json` is the contract.
- **Do not** force-push. Failures result in `pr_open_error` populated; humans investigate.
- **Do not** create a PR without first validating that every key in `config_diff` is in the template's `declared_params`.
- **Do not** include the cluster's full schema or doc content in the PR body. Only metric deltas, top-10 trials, and the proposal-specific config diff.
- **Do not** assume `gh` CLI is installed. Use httpx async for the GitHub REST API; shell out to `git` (which IS in the image) for clone/branch/commit/push.

## 5) Assumptions and dependencies

- **Dependency: `infra_foundation`** — Arq, Postgres, Pydantic Settings; `GITHUB_TOKEN_FILE` may be empty (returns `GITHUB_NOT_CONFIGURED`).
- **Dependency: `infra_adapter_elastic`** — `clusters.config_repo_id` and `clusters.config_path` populated; `config_repos` table exists.
- **Dependency: `feat_digest_proposal`** — `proposals` table created with `pr_url`, `pr_state`, `pr_merged_at`, `rejected_reason` columns. This feature ADDS one column: `pr_open_error TEXT NULLABLE` (for surfacing PR-creation failures to the UI).
- **`git` binary** in the worker container image (standard in `python:3.12-slim`).
- **`matplotlib`** for the parameter-importance PNG (added to `pyproject.toml`).
- **Network egress to `github.com`** from the worker container.

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (clicks "Open PR" via UI / asks the chat agent to do it).
- **Secondary actor:** the GitHub reviewer (whoever the config repo's branch protection routes to — per umbrella §18, NOT a RelyLoop role).

### Authorization

N/A — single-tenant install, no auth surface. The GitHub PAT IS the authorization to GitHub; that's a capability of the install.

### Audit events

N/A — `audit_log` lands at MVP2. When MVP2 ships, this feature's `proposal.pr_opened` and `proposal.pr_open_failed` will emit audit events.

## 7) Functional requirements

### FR-1: open_pr endpoint
- `POST /api/v1/proposals/{id}/open_pr` validates proposal is `pending` (otherwise 409 `INVALID_STATE_TRANSITION` for terminal states; 404 for unknown id).
- Validates `GITHUB_TOKEN_FILE` is non-empty (otherwise 503 `GITHUB_NOT_CONFIGURED`).
- Enqueues `open_pr(proposal_id)` on the `pr` Arq queue.
- Returns HTTP 202 with `{proposal_id, status: 'pending', message: 'PR creation queued'}`.

### FR-2: open_pr worker
- The worker **MUST** acquire a Postgres advisory lock on `(hashtext(config_repo_id::text))` before touching the local clone.
- The worker **MUST** clone-or-pull the `config_repos.repo_url` to `./data/repo-clones/<config_repo.name>/` using `https://x-access-token:<token>@github.com/<owner>/<repo>` URL scheme (token from `GITHUB_TOKEN_FILE`).
- The worker **MUST** create branch `relyloop/study-{study_id}` (or `relyloop/proposal-{proposal_id}` if `study_id` is null) off the cluster's `config_repos.pr_base_branch`. If the branch already exists upstream, fail with `BRANCH_EXISTS`.
- The worker **MUST** read `<clusters.config_path>/<template_name>.params.json`, deep-merge `proposal.config_diff` into it, validate the result against the template's `declared_params`, and write the file. If a `config_diff` key is not in `declared_params`, fail with `PARAM_NOT_IN_TEMPLATE`.
- The worker **MUST** commit with the structured message format from [`apply-path.md` §"PR creation flow"](../../../01_architecture/apply-path.md). Commit author is `relyloop-bot@<install-domain>` (configured in the install runbook).
- The worker **MUST** push the branch and open a PR via GitHub REST `POST /repos/{owner}/{repo}/pulls` with body containing: link back to RelyLoop study UI (constructed from `RELYLOOP_BASE_URL` setting + `study_id`), top-10 trials table (markdown), baseline-vs-achieved metrics table, suggested follow-ups from `digests.suggested_followups`.
- The worker **MUST** attach a parameter-importance bar chart as a PR COMMENT (separate API call) — PNG generated via matplotlib from `digests.parameter_importance`.
- The worker **MUST** update `proposals.pr_url` + `pr_state='open'` + `status='pr_opened'` atomically.
- On any failure, the worker **MUST** populate `proposals.pr_open_error` with the failure detail and leave `status='pending'` (re-runnable).
- Notes: covers US-18, US-19.

### FR-3: Config-repo CRUD
- `POST /api/v1/config-repos` accepts `{name, repo_url, default_branch?, pr_base_branch?, auth_ref, webhook_secret_ref?}` and returns the created config_repos row.
  - Validates `repo_url` is a GitHub URL (regex match against `https://github.com/<owner>/<repo>(\.git)?`); rejects others with `UNSUPPORTED_PROVIDER` (GitLab + Bitbucket join MVP3).
  - Validates `auth_ref` points to an existing mounted secret file (existence check at API level).
- `GET /api/v1/config-repos` paginated.
- `GET /api/v1/config-repos/{id}` returns full detail.

### FR-4: pr_open_error column
- The system **MUST** add `proposals.pr_open_error TEXT NULLABLE` in this feature's migration.
- On a failed PR-open attempt, the worker **MUST** populate this column with a human-readable error message (e.g., `"GitHub API returned 422: PR already exists for branch relyloop/study-stu_01HXYZ"`).
- On a successful retry that opens the PR, the column **MUST** be cleared to NULL.

### FR-5: GitHub PAT auth
- The worker **MUST** read the GitHub token from the file path in `GITHUB_TOKEN_FILE` env var (per `infra_foundation` FR-3 secrets pattern).
- The token **MUST** be passed via `Authorization: token <pat>` header on REST calls; via URL embedding (`https://x-access-token:<pat>@github.com/...`) on git clone.
- The token **MUST NOT** appear in any log line, error message, or PR body. (Use a redaction filter on structlog for any field matching the token regex.)

## 8) API and data contract baseline

### 7.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/api/v1/proposals/{id}/open_pr` | Enqueue PR creation | `PROPOSAL_NOT_FOUND`, `INVALID_STATE_TRANSITION`, `GITHUB_NOT_CONFIGURED` |
| `POST` | `/api/v1/config-repos` | Register a config repo | `VALIDATION_ERROR`, `UNSUPPORTED_PROVIDER`, `CONFIG_REPO_NAME_TAKEN`, `AUTH_REF_NOT_FOUND` |
| `GET` | `/api/v1/config-repos` | List | (none) |
| `GET` | `/api/v1/config-repos/{id}` | Detail | `CONFIG_REPO_NOT_FOUND` |

### 7.4 Enumerated value contracts

| Field | Accepted values | Backend source of truth |
|---|---|---|
| `config_repos.provider` | `github` | `backend/db/models/config_repo.py` (MVP3 adds `gitlab`, `bitbucket`) |
| `proposals.pr_state` | `open`, `closed`, `merged` | `backend/db/models/proposal.py` (mirrors GitHub API semantics) |
| `proposals.status` | `pending`, `pr_opened`, `pr_merged`, `rejected` | `backend/db/models/proposal.py` (per `feat_digest_proposal` enum) |

### 7.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| `GITHUB_NOT_CONFIGURED` | 503 | `GITHUB_TOKEN_FILE` is missing/empty |
| `PROPOSAL_NOT_FOUND` | 404 | Proposal ID not found |
| `INVALID_STATE_TRANSITION` | 409 | `open_pr` on a `pr_opened` / `pr_merged` / `rejected` proposal |
| `CONFIG_REPO_NOT_FOUND` | 404 | Config repo ID not found |
| `CONFIG_REPO_NAME_TAKEN` | 409 | Name conflict |
| `UNSUPPORTED_PROVIDER` | 400 | repo_url not GitHub (GitLab + Bitbucket arrive MVP3) |
| `AUTH_REF_NOT_FOUND` | 400 | `auth_ref` points to a missing mounted secret |
| `PARAM_NOT_IN_TEMPLATE` | 422 | Worker-internal: config_diff key not in `declared_params`. Surfaced via `proposals.pr_open_error`. |
| `BRANCH_EXISTS` | 409 | Worker-internal: branch already exists upstream. Surfaced via `pr_open_error`. |
| `PARAMS_FILE_NOT_FOUND` | 404 | Worker-internal: `*.params.json` missing in the repo at the expected path. Surfaced via `pr_open_error`. |

## 9) Data model and state transitions

This feature adds `proposals.pr_open_error TEXT NULLABLE`. All other table creation owned by `feat_digest_proposal` + `infra_adapter_elastic`.

### State transitions

`proposals.status`: `pending → pr_opened` (on successful PR open). `pending → pending` (on failed PR open, with `pr_open_error` populated). `pr_opened → pr_merged` is owned by `feat_github_webhook`.

## 10) Security, privacy, and compliance

- **Threats:**
  1. GitHub token leak in PR bodies, commit messages, or logs. **Mitigation:** structlog redaction filter for any string matching the GitHub token regex (`gh[ps]_[A-Za-z0-9_]{36,}`); PR body templates never reference the token; commit author is the bot account, not the operator.
  2. Path traversal via crafted `clusters.config_path` (e.g., `../../etc/passwd`). **Mitigation:** validate `config_path` is a relative path containing only `[A-Za-z0-9_/.-]` at cluster registration time.
  3. Repo-content injection via `proposal.config_diff`. **Mitigation:** the worker writes ONLY `*.params.json`; the diff is JSON-merged (no string interpolation into shell commands); `git commit` uses the `-F` flag with a temp file, not `-m` with shell-quoted args.
  4. Repo cloning under attacker control. **Mitigation:** `repo_url` is GitHub-only and validated at registration; clones happen via HTTPS with token-in-URL auth; SSH not supported in MVP1.
- **Secrets handling:** `GITHUB_TOKEN_FILE` only.
- **Auditability:** N/A — `audit_log` is MVP2.

## 11) UX flows and edge cases

This feature has no UI; "Open PR" button lives in `feat_proposals_ui`.

### Edge/error flows

- **Cluster's config_repo_id is NULL** (cluster registered without a repo). `POST /open_pr` returns 422 `CLUSTER_HAS_NO_CONFIG_REPO` (added to catalog above? — let me add).
- **PR already exists for the branch.** `BRANCH_EXISTS` populated; `pr_open_error` reflects the GitHub 422 message; status stays `pending`. Engineer can investigate via the GitHub UI and either close the existing PR or modify the proposal.
- **GitHub API rate-limit during PR open.** httpx retries 3× with backoff; final failure populates `pr_open_error: "GitHub rate limit exceeded; retry in <duration>"`.
- **Disk full during clone.** Clone fails; `pr_open_error: "git clone failed: <stderr>"`.

## 12) Given/When/Then acceptance criteria

### AC-1: Open PR end-to-end (happy path)

- Given a `pending` proposal with `study_id`, `cluster_id` linked to a `config_repos` row pointing at a real test repo, `config_diff = {field_boosts.title: {from: 2.0, to: 4.5}}`, the digest's `parameter_importance` populated, `GITHUB_TOKEN_FILE` configured.
- When the operator POSTs to `/api/v1/proposals/{id}/open_pr`.
- Then within 60s: a GitHub PR appears against the test repo on branch `relyloop/study-{study_id}`, the diff touches only the `*.params.json` file with `field_boosts.title` updated from 2.0 to 4.5, the commit message follows the structured format, the PR body includes the metric delta + top-10 trials + suggested follow-ups + link back to the study, and a comment with a parameter-importance PNG is attached. The proposal row has `status='pr_opened'`, `pr_url` populated, `pr_state='open'`, `pr_open_error=NULL`.

### AC-2: Reject if GitHub token missing

- Given `./secrets/github_token` is empty.
- When `POST /open_pr` is called.
- Then HTTP 503 with `error_code: GITHUB_NOT_CONFIGURED`. No job enqueued; no proposal mutation.

### AC-3: PARAM_NOT_IN_TEMPLATE failure

- Given a proposal with `config_diff = {nonexistent_param: {from: 1, to: 2}}` (param not in the template's `declared_params`).
- When the worker runs.
- Then no PR is created; `proposals.pr_open_error = "config_diff key 'nonexistent_param' is not in template's declared_params"`; `status='pending'`. Re-running `open_pr` after fixing the proposal (or template) succeeds.

### AC-4: BRANCH_EXISTS failure

- Given a proposal where the branch `relyloop/study-{study_id}` already exists upstream (e.g., a prior failed run).
- When `open_pr` runs.
- Then no force-push; `pr_open_error = "Branch relyloop/study-{study_id} already exists upstream"`; `status='pending'`.

### AC-5: Per-repo serialization

- Given two `pending` proposals targeting the same `config_repo_id`.
- When both `POST /open_pr` are called within 1s.
- Then the worker processes them sequentially (Postgres advisory lock); both PRs eventually open with no race conditions on the local clone or the `*.params.json` file. The second PR's branch is `relyloop/study-{study2}` (different) and its diff applies on top of `pr_base_branch`, NOT on top of the first PR's branch.

### AC-6: Re-issue on already-opened proposal

- Given a proposal with `status='pr_opened'`.
- When `POST /open_pr` is called again.
- Then HTTP 409 with `error_code: INVALID_STATE_TRANSITION`. No worker job enqueued.

### AC-7: GitHub token never leaks

- Given a successful PR open.
- When the operator inspects: PR body, commit message, the `proposals` row (especially `pr_url` and `pr_open_error`), all worker log lines for the job.
- Then no log/message/field contains the GitHub token (no string matching `gh[ps]_[A-Za-z0-9_]{36,}`).

### AC-8: Config-repo registration validates GitHub-only

- Given a `POST /api/v1/config-repos` with `repo_url = "https://gitlab.com/foo/bar"`.
- When the request lands.
- Then HTTP 400 with `error_code: UNSUPPORTED_PROVIDER` and message naming MVP3 as the activation point.

## 13) Non-functional requirements

- **Performance:** PR-open completes in <60s p99 (clone <10s for ≤10MB repos, file edit + commit <2s, GitHub PR API <3s, comment with PNG <5s). Subsequent re-clones (incremental pull) <5s.
- **Reliability:** Per-repo lock prevents corrupted-clone races. Failed runs leave the proposal `pending` with a clear `pr_open_error`.
- **Operability:** Every PR-open invocation logs `proposal_id`, `study_id`, `config_repo_id`, `branch_name`, `duration_ms`, `pr_url` (on success) at INFO. Failures log at WARN with the error reason.

## 14) Test strategy requirements

- **Unit tests** (`backend/tests/unit/`):
  - `worker/test_params_merge.py` — `config_diff` deep-merge against representative `*.params.json` files; rejects keys not in `declared_params`.
  - `worker/test_commit_message.py` — structured commit message format with various inputs (study, manual proposal, etc.).
  - `worker/test_token_redaction.py` — structlog redaction filter strips GitHub tokens.
- **Integration tests** (`backend/tests/integration/`):
  - `test_pr_open_happy_path.py` — full flow against a cassette-replayed GitHub API; asserts AC-1 minus the actual GitHub side effects.
  - `test_pr_open_param_not_in_template.py` — AC-3.
  - `test_pr_open_branch_exists.py` — AC-4.
  - `test_pr_open_serialization.py` — AC-5 (two parallel jobs, advisory lock works).
  - `test_pr_open_rejected_after_opened.py` — AC-6.
- **Contract tests**:
  - `test_github_pr_worker_api_contract.py` — endpoint shape parity.
  - `test_token_never_leaks.py` — assertion sweep over logs/PR-body/proposal row (AC-7).
- **E2E tests:** N/A (UI in `feat_proposals_ui`).

## 15) Documentation update requirements

- `docs/01_architecture/apply-path.md` already documents the workflow; update if implementation diverges.
- `docs/03_runbooks/`: add `pr-open-debugging.md` — investigate `pr_open_error`, manually clean up an orphan branch, rotate the GitHub PAT.
- `docs/04_security/`: add `github-token-handling.md` — token storage, rotation, scope requirements.
- `docs/02_product/mvp1-user-stories.md`: mark US-18 / US-19 as "implemented".

## 16) Rollout and migration readiness

- **Feature flags:** None.
- **Migration/backfill:** Adds `proposals.pr_open_error` column.
- **Operational readiness gates:** PR-open against a sample test repo completes in <60s; runbook for pr_open_error debugging exists.
- **Release gate:** `feat_github_webhook` author confirms the polling-reconciler interface (proposals with `status='pr_opened'` and `pr_state='open'` >15 min old) is queryable.

## 17) Traceability matrix

| FR ID | AC IDs | Stories (TBD) | Test files | Docs |
|---|---|---|---|---|
| FR-1 (open_pr endpoint) | AC-1, AC-2, AC-6 | TBD | `tests/integration/test_pr_open_happy_path.py`, `tests/integration/test_pr_open_rejected_after_opened.py` | runbook |
| FR-2 (open_pr worker) | AC-1, AC-3, AC-4, AC-5 | TBD | `tests/integration/test_pr_open_*.py` | runbook |
| FR-3 (config-repo CRUD) | AC-8 | TBD | `tests/integration/test_config_repo_crud.py` | runbook |
| FR-4 (pr_open_error col) | AC-3, AC-4 | TBD | `tests/integration/test_pr_open_param_not_in_template.py` | — |
| FR-5 (PAT auth + redaction) | AC-2, AC-7 | TBD | `tests/unit/worker/test_token_redaction.py`, `tests/contract/test_token_never_leaks.py` | security doc |

## 18) Definition of feature done

- [ ] AC-1 through AC-8 pass.
- [ ] All test layers green; ≥80% coverage on `backend/worker/git_pr.py`, `backend/api/proposals.py` (open_pr endpoint), `backend/api/config_repos.py`.
- [ ] PR-open against a test repo completes in <60s (recorded benchmark).
- [ ] `docs/03_runbooks/pr-open-debugging.md` and `docs/04_security/github-token-handling.md` merged.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

1. **Test config repo for CI** — CI integration tests need a real GitHub repo to push to. Recommend: create `SoundMindsAI/relyloop-test-configs` as a public test repo; CI runs use a dedicated test PAT with scope only for that repo. — Owner: Ops — Due: before plan.
2. **Parameter-importance PNG dimensions + style** — fixed 800x600 with shadcn/Tailwind-compatible colors? Or use the same color palette as the UI's Recharts component (defined later by `feat_studies_ui`)? Recommend: 800x600 PNG, simple horizontal bar chart, monochrome (no UI palette dependency). — Owner: TBD — Due: before plan.
3. **`CLUSTER_HAS_NO_CONFIG_REPO` error code** — should it be added to §7.5 (it's referenced in §11 edge flows)? Recommend yes. — Owner: TBD — Due: before plan.

### Decision log

- 2026-05-09 — `pr_open_error` column added by this feature (not by `feat_digest_proposal`) — keeps the migration ownership clean per the feature's responsibility.
- 2026-05-09 — Token-via-URL for `git clone` (`https://x-access-token:<pat>@github.com/...`) — per [`apply-path.md` §"GitHub auth"](../../../01_architecture/apply-path.md). Alternative (SSH key) is rejected for MVP1 (more setup for the operator).
- 2026-05-09 — No force-push, no `--no-verify` — per global git-safety rules.
