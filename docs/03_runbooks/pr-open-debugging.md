# Runbook: debugging the `open_pr` worker

Operator playbook for the `feat_github_pr_worker` worker
(`backend/workers/git_pr.py`): inspecting failed PR-open jobs, rotating
per-repo PATs, recovering from stale branches, and resetting persistent
clone state when a prior run left a config-repo's local clone in a bad
state.

## Quick reference

| Symptom | First check |
|---|---|
| `POST /api/v1/proposals/{id}/open_pr` returns 503 `GITHUB_NOT_CONFIGURED` | `./secrets/{config_repo.auth_ref}` is missing or empty. Populate the file, no service restart needed — the worker reads it per job. |
| `POST /api/v1/proposals/{id}/open_pr` returns 503 `QUEUE_UNAVAILABLE` | The Arq pool isn't initialized (Redis unreachable at API startup). `docker compose restart api worker` after confirming `redis` is healthy. |
| `POST /api/v1/proposals/{id}/open_pr` returns 422 `CLUSTER_HAS_NO_CONFIG_REPO` | The cluster has no `config_repo_id` wired in. Register one via `POST /api/v1/config-repos` and update the cluster row (or the chat agent's `register_config_repo` tool). |
| `POST /api/v1/proposals/{id}/open_pr` returns 409 `INVALID_STATE_TRANSITION` | The proposal isn't `pending` (already `pr_opened`, `pr_merged`, or `rejected`). Inspect `proposals.status` for the current state. |
| `proposals.pr_open_error` contains `CLONE_FAILED` | The initial `git clone` of the config repo failed. Common causes: wrong `repo_url`, PAT lacks `contents:read` scope, network firewall blocking github.com. Re-run after fixing the upstream cause. |
| `proposals.pr_open_error` contains `BRANCH_EXISTS` | The deterministic branch name (`relyloop/study-{id}` or `relyloop/proposal-{id}`) already exists on the remote. Close + delete the orphan branch manually (see "Closing an orphan branch" below). |
| `proposals.pr_open_error` contains `PARAM_NOT_IN_TEMPLATE` | The proposal's `config_diff` references a param no longer declared on the template. Either re-add the param to the template, or reject the proposal and run a fresh study against the updated template. |
| `proposals.pr_open_error` contains `PARAMS_FILE_NOT_FOUND` | The expected `{template.name}.params.json` file is missing under `cluster.config_path` in the config repo. Either create the file (empty `{}` is fine), or fix `cluster.config_path`. |
| `proposals.pr_open_error` contains `GITHUB_API_FAILED` | GitHub returned a non-success on the PR-open POST. The full GitHub error message is appended (token-redacted). Common causes: PAT lacks `pull_requests:write`, branch protection blocks the head ref, owner/repo doesn't match. |
| `make logs worker` shows `pr_open_lock_contention` | Two workers raced for the same `config_repo_id`. Both eventually open per AC-5 — the lock contention loser raises `arq.Retry(defer=5.0)` and re-enters the queue. Benign unless seen >5 times per minute (then `max_tries=30` may be insufficient for the operator's PR-open p99). |
| `make logs worker` shows `pr_open_proposal_no_longer_pending` | The operator rejected the proposal mid-flight. The PR may still exist on the remote — close it manually (see below). |

## End-to-end flow walkthrough

```text
operator POST /api/v1/proposals/{id}/open_pr
  ↓ preflight: proposal-pending → cluster.config_repo_id → PAT readable → arq enqueue
  ↓ 202 Accepted with deterministic _job_id=open_pr:{proposal_id}
worker.open_pr:
  ↓ Step 1: load proposal, bail if not pending
  ↓ Step 2: load cluster + config_repo + template (FK chain)
  ↓ Step 3: read PAT from ./secrets/{auth_ref}, bail if missing
  ↓ Step 4: pg_try_advisory_xact_lock(blake2b("config-repo:{id}"))
              on contention → arq.Retry(defer=5.0) (NOT a bail)
  ↓ Step 5: re-read proposal under lock (operator-reject race)
  ↓ Step 6: clone-or-pull via GIT_CONFIG_* env-var auth (token NEVER in argv)
  ↓ Step 7: fetch / reset --hard origin/{base} / clean -fdx / checkout -B {branch}
              ls-remote --heads origin {branch} → BRANCH_EXISTS if non-empty
  ↓ Step 8: validate_config_path + resolved-path containment check
  ↓ Step 9: validate config_diff keys against template.declared_params
  ↓ Step 10: apply diff to {template.name}.params.json
  ↓ Step 11: render PNG chart (study-backed only; matplotlib Agg)
              on failure → log pr_open_chart_failed + Markdown-table fallback
  ↓ Step 12: commit params (then chart if generated) with bot identity, push
  ↓ Step 13: POST /repos/{owner}/{repo}/pulls (httpx, retry on 5xx + 429 + 403-rate-limit)
              body branches on study_id (manual proposals omit metrics + study link)
  ↓ Step 14: POST /repos/{owner}/{repo}/issues/{N}/comments with chart embed
              (study-backed only; failure is non-fatal → pr_open_chart_failed)
  ↓ Step 15: conditional UPDATE proposals SET status='pr_opened' WHERE status='pending'
              zero-row match → log pr_open_proposal_no_longer_pending
```

## Re-running a failed PR-open

`proposals.pr_open_error` is cleared automatically on the next successful
run, so the simplest recovery flow is:

1. **Fix the upstream cause** based on the error code (see Quick reference above).
2. **Re-trigger the worker** via the API:
   ```bash
   curl -X POST http://localhost:8000/api/v1/proposals/<id>/open_pr
   ```
   The deterministic `_job_id=open_pr:<id>` dedups against any still-
   in-flight job, but otherwise re-enqueues cleanly.

## Closing an orphan branch on GitHub

If a `BRANCH_EXISTS` error means a prior run pushed the branch but then
crashed before the PR-open succeeded, close + delete the orphan manually:

```bash
# Replace with your config repo's owner/repo + the affected branch name.
gh api -X DELETE repos/{owner}/{repo}/git/refs/heads/relyloop/study-<study-id>
```

Then re-trigger the proposal's PR-open per the previous section.

## Rotating a per-repo PAT

The per-repo `auth_ref` pattern (one PAT per config repo) means a single
compromised PAT can be rotated WITHOUT touching the other config repos —
the killer-feature vs the old `feat_llm_judgments`-era global env-var
token. To rotate:

1. Generate a new PAT on GitHub with `contents:write` + `pull_requests:
   write` (and optionally `workflow:write` if the config repo has CI on
   the proposal branch).
2. Overwrite the secret file in-place:
   ```bash
   echo "<new-pat>" > ./secrets/<auth_ref>
   ```
3. No service restart needed — the worker reads the file on every job.
4. Revoke the old PAT on GitHub.

If the operator wants to rotate the file path itself (different
`auth_ref` key), update the config_repo row + create the new file:

```sql
UPDATE config_repos SET auth_ref = '<new_auth_ref>' WHERE id = '<config_repo_id>';
```

```bash
mv ./secrets/<old_auth_ref> ./secrets/<new_auth_ref>
```

## Inspecting the persistent clone

The worker keeps one persistent clone per config repo at
`./data/repo-clones/{config_repo.id}/` so each PR-open avoids the
~5–30s cost of a fresh clone. Step 7 of the worker contract (reset
--hard + clean -fdx + checkout -B) discards all prior-run state, but
if you suspect the clone has drifted into an unrecoverable state, you
can blow it away — the next run re-clones from scratch:

```bash
docker compose exec worker rm -rf /app/data/repo-clones/<config_repo_id>
```

(The path is on a Docker named volume mounted at `/app/data/` in the
worker container; `make reset FORCE=1` wipes the entire `./data/`
directory if you want to re-clone every config repo.)

## Verifying the PNG was committed

The worker commits the parameter-importance chart to a hidden directory
inside the proposal branch:

```bash
gh api repos/{owner}/{repo}/contents/.relyloop/digest-charts/{study_id}.png \
  --jq '.size' \
  -F ref=relyloop/study-{study_id}
```

The PR's chart-comment uses the slash-safe raw URL form
`https://github.com/{owner}/{repo}/raw/refs/heads/{branch}/.relyloop/
digest-charts/{study_id}.png` (cycle-2 F4). If the comment's image is
broken, verify the file exists at that exact path on the branch.

## Manual proposal-only paths

When `proposal.study_id IS NULL` (hand-crafted via the chat agent's
`open_pr` tool call), the worker:

* Uses the branch name `relyloop/proposal-{proposal_id}` (vs
  `relyloop/study-{study_id}` for study-backed).
* Skips PNG render + chart-comment entirely (no `digest` row exists).
* Emits a shorter PR body with just the config-diff table + an
  explanatory note ("This is a manual (hand-crafted) proposal — no
  study metrics available.").

## Worker-side terminal codes

These five codes never escape the worker into a 4xx/5xx HTTP response —
they're recorded as text in `proposals.pr_open_error` (token-redacted)
and surface in `make logs worker` as structured `event_type=pr_open_
failed error_code=<CODE>` log lines:

| Code | Source step | Recovery |
|---|---|---|
| `CLONE_FAILED` | Step 6 | Fix `repo_url` or PAT scopes; re-run. |
| `BRANCH_EXISTS` | Step 7 | Close orphan branch on GitHub; re-run. |
| `PARAM_NOT_IN_TEMPLATE` | Step 9 | Re-add the param to the template or reject. |
| `PARAMS_FILE_NOT_FOUND` | Step 9 | Create the `{template_name}.params.json` file (empty `{}` is fine) or fix `cluster.config_path`. |
| `GITHUB_API_FAILED` | Step 13 | Read the captured GitHub error in `pr_open_error` — usually a PAT scope or branch-protection issue. |
