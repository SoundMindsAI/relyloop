# Security: GitHub token handling in the open_pr worker

The `feat_github_pr_worker` worker
(`backend/workers/git_pr.py`) is the only RelyLoop component that
holds a long-lived GitHub credential (PAT) on disk. This doc
enumerates the storage model, rotation procedures, scope requirements,
and the AC-7 leak-prevention checklist that every code path must
respect.

## Storage model — per-repo `auth_ref` pattern

Each registered config repo has an `auth_ref` field that names a file
under `./secrets/{auth_ref}`. The worker reads the PAT at job time:

```text
./secrets/
├── postgres_password           # infra_foundation
├── database_url                # infra_foundation
├── openai_api_key              # feat_llm_judgments (optional)
├── acme-prod-search-config     # config_repo "acme-prod" — auth_ref="acme-prod-search-config"
├── acme-staging-config         # config_repo "acme-staging" — auth_ref="acme-staging-config"
└── beta-team-config            # config_repo "beta-team"   — auth_ref="beta-team-config"
```

Each file holds ONE PAT scoped to ONE config repo. This is the killer-
feature vs the older single-token model:

* **Blast-radius bounded.** A compromised `auth_ref` exposes one repo;
  rotation touches one file, not the whole install.
* **Operator-side audit clarity.** GitHub's audit log shows which PAT
  performed which commit — operators can map "PR opened by ghp_abc..."
  to "config_repo {name}" without grepping the worker source.
* **Independent rotation windows.** Sensitive prod repos can be rotated
  on a quarterly schedule while less-sensitive dev repos stay on a
  longer cadence — no all-or-nothing trade-off.

The `GITHUB_TOKEN_FILE` env var from `infra_foundation` is now
deprecated for the PR worker's needs. See
[`chore_infra_foundation_github_token_file_retirement/idea.md`](../02_product/planned_features/chore_infra_foundation_github_token_file_retirement/idea.md)
for the formal retirement path.

## Rotation procedures

### Routine rotation (planned)

1. Generate a replacement PAT on GitHub with the scopes from the next
   section.
2. Overwrite the secret file in-place:
   ```bash
   echo "<new-pat>" > ./secrets/<auth_ref>
   ```
3. **No service restart needed** — `backend/workers/git_pr.py:_read_pat`
   reads the file fresh on every job.
4. Revoke the old PAT on GitHub.

### Emergency rotation (suspected compromise)

1. **Revoke first.** Go to GitHub Settings → Developer settings → PATs
   → Delete the compromised token. Subsequent worker calls will get
   401 from GitHub; `pr_open_error` will surface `GITHUB_API_FAILED`
   with the 401 response.
2. Wipe the local file:
   ```bash
   : > ./secrets/<auth_ref>   # truncate without removing
   ```
3. Generate + write the new PAT (per "Routine rotation" steps 1–2).
4. **Audit recent commits** via `git log --since=<compromise-window>`
   on each branch the worker has pushed against the affected repo —
   force-push concerns are bounded by AC-4 (worker refuses to overwrite
   existing branches) but the operator should still verify no
   unexpected commits landed.
5. Re-trigger any pending proposals that failed during the window.

## PAT scopes required

| Scope | Why |
|---|---|
| `contents:write` | Push commits to the proposal branch (Step 12 of the worker contract). |
| `pull_requests:write` | Open PRs via `POST /repos/{owner}/{repo}/pulls` (Step 13). |
| `workflow:write` | OPTIONAL — only needed if the config repo has CI that runs on the proposal branch (worker commits don't touch `.github/workflows/` directly, but some setups gate other branches via workflow files). |

Fine-grained PATs (`github_pat_...`) are the recommended format —
the redaction regex (cycle-3 F2) covers both classic
(`ghp_`/`ghs_`/`gho_`/`ghu_`/`ghr_`) and fine-grained prefixes.

## Token-safe git invocations (cycle-1 F4)

Every git subprocess invocation in the worker uses the process-scoped
env-var auth mechanism instead of embedding the PAT in `argv` or
`.git/config`:

```python
env = {
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
    "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: Bearer {token}",
}
subprocess.run(["git", "clone", "https://github.com/{owner}/{repo}.git", clone_dir], env=env, ...)
```

This pattern mirrors GitHub Actions' `actions/checkout` for the same
reason: the token lives ONLY in the subprocess environment (visible to
`git` and its children, **not** to `ps` / `argv` inspection, **not**
persisted on disk via `.git/config`).

The `git clone` URL is the **tokenless** form
`https://github.com/{owner}/{repo}.git`. The Authorization header
arrives via the `GIT_CONFIG_*` env vars — never in the URL.

## Log-line redaction (FR-5)

Every WARN/ERROR log line passes its error string through
`redact_token` (defined in `backend.app.domain.git.redaction`). The
global `RedactTokensProcessor` (wired into `backend.app.core.logging`
at the structlog chain) is the defense-in-depth backstop — even a
future log line that forgets explicit redaction gets scrubbed before
the JSON renderer serializes it.

Redacted tokens are replaced with the literal string
`[REDACTED-GH-TOKEN]` so grep through log archives is deterministic
("did this exfiltrate?" → grep for `gh[a-z]_` or `github_pat_`; any
hit is a regression).

## AC-7 leak surfaces — full enumeration

The worker MUST guarantee the PAT never appears in any of the
following 9 surfaces. The token-leak contract test
(`backend/tests/contract/test_token_never_leaks.py` — Story 4.2; not
yet shipped in this PR) covers each.

1. **PR title** — built from `study.name` / proposal id; no PAT input.
2. **PR body** — Markdown body composition uses only safe inputs
   (proposal/study/digest fields, config_diff); no PAT input.
3. **Commit messages** — built from proposal id + cluster + template
   names; no PAT input. Passed via `git commit -F <tempfile>` (NOT
   `-m` + shell-quoted args) for additional argv safety.
4. **`pr_url`** — populated from GitHub's response `html_url` field;
   no PAT input.
5. **`pr_open_error`** — every write through `_safe_set_pr_open_error`
   applies `redact_token` to the input string before persisting.
6. **Worker log lines** — explicit `redact_token` on every error
   string + the global `RedactTokensProcessor` backstop on the entire
   event_dict.
7. **Subprocess argv** — git invocations use the tokenless URL form
   with auth supplied via env vars (cycle-1 F4); the captured argv
   for `subprocess.run` calls NEVER contains the PAT.
8. **Subprocess stdout / stderr** — captured by `subprocess.run(..,
   capture_output=True)`; the worker's `_redact_subprocess_error`
   helper applies `redact_token` to the captured streams before any
   log emission.
9. **`.git/config`** — the worker NEVER calls
   `git config http.https://github.com/.extraheader ...` (which would
   persist the token to disk). The auth header lives only in the
   subprocess environment, which is gone the moment `git` exits.

## Operator verification checklist

When deploying a new RelyLoop install (or auditing an existing one):

* [ ] Confirm each `config_repo.auth_ref` maps to a real file under
      `./secrets/` (verify via the `POST /api/v1/config-repos` 400
      `AUTH_REF_NOT_FOUND` response if not).
* [ ] Run `grep -r 'gh[a-z]_\|github_pat_' ./logs/` against archived
      logs — any hit is a regression.
* [ ] Run `git -C ./data/repo-clones/<config_repo_id> config --get-all
      http.https://github.com/.extraheader` — should return empty
      (header lives in env, not config).
* [ ] Verify `ps auxf` during an active PR-open never shows the PAT
      in any `git` argv (use the production load-test or staging).
