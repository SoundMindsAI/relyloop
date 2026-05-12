# Feature Specification — feat_github_webhook

**Date:** 2026-05-09 (patched 2026-05-12 — see Decision log)
**Status:** Approved
**Owners:** TBD
**Related docs:**
- [docs/02_product/mvp1-user-stories.md](../../mvp1-user-stories.md) — covers US-20, US-21
- [docs/01_architecture/apply-path.md](../../../01_architecture/apply-path.md) — Git PR workflow architecture (webhook receiver section)
- [docs/01_architecture/api-conventions.md](../../../01_architecture/api-conventions.md) — webhook conventions
- Depends on: [`infra_foundation`](../../../00_overview/implemented_features/2026_05_09_infra_foundation/feature_spec.md), [`infra_adapter_elastic`](../../../00_overview/implemented_features/2026_05_10_infra_adapter_elastic/feature_spec.md) (owner of `config_repos.webhook_secret_ref` + `config_repos.webhook_registration_error`), [`feat_github_pr_worker`](../../../00_overview/implemented_features/2026_05_12_feat_github_pr_worker/feature_spec.md)
- Consumed by: [`feat_proposals_ui`](../feat_proposals_ui/feature_spec.md)

---

## 1) Purpose

- **Problem:** After a PR is opened against a config repo, the engineer wants to see `pr_state` flip to `merged` in the RelyLoop UI within seconds of merging on GitHub — without manually clicking refresh, polling GitHub, or running CLI commands. Webhooks deliver the state change in real time; a polling reconciler catches missed deliveries.
- **Outcome:** GitHub posts to `POST /webhooks/github` with HMAC-SHA256 signature; the receiver verifies the signature, looks up the proposal by `pr_url`, updates `pr_state` and `pr_merged_at`. A 15-minute polling tick reconciles any proposals whose `pr_state` hasn't been updated in a window.
- **Non-goal:** No GitLab / Bitbucket webhooks (MVP3). No `pull_request_review` event handling (MVP2 — Slack notifications). No deployment-state webhooks (MVP3+). No webhook-driven re-runs (humans drive re-runs via the UI).

## 2) Current state audit

After `feat_github_pr_worker` ships:
- `proposals` rows transition to `pr_opened` with `pr_url` populated and `pr_state='open'`.
- No webhook endpoint exists yet.
- No polling reconciler exists yet.

## 3) Scope

### In scope

- Webhook endpoint `POST /webhooks/github`:
  - Verifies `X-Hub-Signature-256` HMAC-SHA256 against the `webhook_secret_ref` mounted secret. Secret is resolved by parsing the payload's `repository.full_name` (`owner/repo`), looking up the matching `config_repos` row (by canonicalised `repo_url`), and reading the secret content from `./secrets/{webhook_secret_ref}`. Lookup-by-`repository.full_name` is the only correct path — `ping` events have no `pull_request` object, so PR-URL lookup would not work for the first event GitHub sends.
  - Handles event types: `ping` (returns 200 immediately — GitHub's webhook-test) and `pull_request` (actions `closed` + `reopened`; all other actions log + 200 no-op).
  - Returns **403** on signature mismatch (`INVALID_SIGNATURE`), 200 on every accepted event regardless of outcome (applied / noop / unknown_pr / ping — GitHub retries any non-2xx, including 4xx, so we always return 200 once signature passes).
  - Unknown event types: log at INFO + return 200 (forward-compatible with new GitHub events; we never want GitHub retrying these).
  - Updates `proposals.pr_state` and `pr_merged_at`; transitions `proposals.status: pr_opened → pr_merged` if the PR was merged.
- Polling reconciler `reconcile_pr_state` Arq cron job triggered every `RELYLOOP_PR_POLL_MINUTES` minutes (default 15) via `WorkerSettings.cron_jobs`:
  - Queries `proposals WHERE status = 'pr_opened' AND pr_state = 'open' AND pr_url IS NOT NULL AND created_at > now() - interval '90 days'`.
  - For each, calls GitHub REST `GET /repos/{owner}/{repo}/pulls/{number}` (authenticated with the per-repo `config_repos.auth_ref` PAT — the same credential `feat_github_pr_worker` uses for `open_pr`).
  - Updates `pr_state` and `pr_merged_at` if changed.
  - Skips proposals where the GitHub API returns 404 (PR was deleted) — logs at WARN, leaves the proposal as-is.
- Idempotency: replay of the same webhook event MUST be a no-op (the state transition is already-applied; no duplicate audit entries). GitHub's `X-GitHub-Delivery` header is **captured to structlog application logs** (`event="webhook_received"` log line with `delivery_id` field) but is NOT used as a dedup key in MVP1 — no new tables. Idempotency is achieved by virtue of state-machine semantics (conditional `UPDATE … WHERE status='pr_opened'`).

### Out of scope

- GitLab / Bitbucket webhooks — MVP3.
- `pull_request_review` event handling (Slack notifications on review-requested) — MVP2.
- `deployment_status` events — MVP3+.
- Webhook-driven re-runs — never; humans drive.
- Webhook signature rotation — MVP4 (auth lands).

### API convention check

Per [`api-conventions.md`](../../../01_architecture/api-conventions.md):
- Webhook endpoint at `/webhooks/github` (NOT under `/api/v1/`); per the URL-structure convention.
- Response is plain JSON `{"status": "ok"}` on success or the standard error envelope on failure.

### Phase boundaries

Single-phase. The MVP1 deliverable: "merge a PR on GitHub → within 30 seconds the RelyLoop UI shows `pr_state = merged`. Even if the webhook delivery fails, within 15 minutes the polling reconciler catches it."

## 4) Product principles and constraints

- **Webhook signature is mandatory.** No unsigned acceptance, even in MVP1 dev. GitHub provides the signature; the operator configures the secret per-repo when registering the config_repo.
- **Webhook + polling = belt and suspenders.** Webhooks are real-time but unreliable (network blips, server restarts). Polling catches the gaps with a 15-min upper bound.
- **Webhook is idempotent.** Any single delivery, replayed any number of times, leaves the same state. GitHub retries up to 3× on non-200 responses; we always return 200 once we've successfully verified the signature, even if the event is a no-op.
- **Polling is bounded.** The reconciler queries only `pr_opened + open` proposals (terminal states are skipped). Polling cost is O(open_PRs) per 15-min tick; for typical installs this is <100 calls per 24 hours.

### Anti-patterns

- **Do not** trust `X-GitHub-Event` header alone to identify event type — also inspect the body for `action` field. (GitHub sometimes sends multiple events with the same header for compound state changes.)
- **Do not** synchronously call GitHub from inside the webhook handler. The handler updates Postgres and returns; if additional work is needed (e.g., audit-event emission at MVP2), it's enqueued.
- **Do not** authenticate the webhook with the GitHub PAT — use the per-repo `webhook_secret_ref`. Different secret, different concern.
- **Do not** retry webhook handler failures. If signature verification fails, return 403; if Postgres write fails, return 500 (GitHub retries). No internal retry loop.

## 5) Assumptions and dependencies

- **Dependency: `feat_github_pr_worker`** — `proposals.pr_url`, `pr_state`, `pr_merged_at`, `status` columns populated.
- **Dependency: `infra_foundation`** — `config_repos.webhook_secret_ref` column exists; mounted secrets pattern.
- **Network ingress** to the API container on port 8000 from GitHub IP ranges. The user's deployment is responsible for this (typically via a reverse proxy at MVP3+; for MVP1 local-laptop, ngrok or a similar tunnel for testing).
- **`webhook_secret_ref` mounted secret** populated when the operator registers a config_repo with a webhook (`config_repos.webhook_secret_ref` is nullable; if NULL, this feature does not register the webhook on GitHub — the polling reconciler still works).

## 6) Actors and roles

- **Primary actor:** GitHub itself (POSTs the webhook).
- **Secondary actor:** the polling tick (system actor).

### Authorization

The webhook endpoint authenticates via HMAC-SHA256 signature, NOT via SSO/API keys. This is the only auth surface in MVP1.

The polling reconciler is internal; no auth.

### Audit events

N/A — `audit_log` lands at MVP2. When MVP2 ships, `proposal.pr_merged` and `proposal.pr_closed_unmerged` will emit audit events.

## 7) Functional requirements

### FR-1: Webhook endpoint
- `POST /webhooks/github` accepts JSON body and headers `X-Hub-Signature-256`, `X-GitHub-Event`, `X-GitHub-Delivery`.
- The endpoint **MUST** look up the relevant `config_repos` row by parsing the body's `repository.full_name` (always present on every GitHub event including `ping`) and matching against `config_repos.repo_url`. URL normalization rule: extract `{owner}/{repo}` from both sides via the same regex (`backend/app/domain/git/validation.py:validate_repo_url`), strip trailing `.git`, and compare. If no `config_repos` row matches, **MUST** return **403 `INVALID_SIGNATURE`** (treat as untrusted — same response as a forged signature, so attackers can't enumerate registered repos).
- The endpoint **MUST** verify the HMAC-SHA256 signature using the `webhook_secret_ref`-mounted secret content. If verification fails, **MUST** return **403** with `INVALID_SIGNATURE` (semantically correct — request is identified but not authorized; matches GitHub's own receiver convention).
- The endpoint **MUST** return 200 for `X-GitHub-Event: ping` with body `{status: "ok", action: "ping"}` (signature is still verified — see secret-lookup path above).
- For `X-GitHub-Event: pull_request`:
  - Look up the proposal by `pr_url` constructed from `pull_request.html_url`.
  - If proposal not found, return 200 with `{status: "ok", action: "unknown_pr"}` (GitHub fired a webhook for a PR not created by us — fine).
  - If `action="closed" AND pull_request.merged=true`: call `mark_proposal_pr_merged(db, proposal_id, pr_merged_at)` (conditional UPDATE: `WHERE status='pr_opened' AND pr_state='open'`). Return 200 with `{status: "ok", action: "applied"}`.
  - If `action="closed" AND pull_request.merged=false`: call `mark_proposal_pr_closed(db, proposal_id)`. Status stays `pr_opened` so the operator can re-`open_pr` if desired (see §11 downstream-invariant note). Return 200 with `{status: "ok", action: "applied"}`.
  - If `action="reopened"`: call `mark_proposal_pr_reopened(db, proposal_id)` → `pr_state='open'`. Status stays `pr_opened`. Return 200 with `{status: "ok", action: "applied"}`.
  - Any other `pull_request` action (`opened`, `edited`, `synchronize`, `review_requested`, etc.): log at INFO + return 200 with `{status: "ok", action: "noop"}`.
- For unknown `X-GitHub-Event`: log at INFO + return 200 with `{status: "ok", action: "noop"}` (forward-compatible with new GitHub events). **Never** return 4xx/5xx for unknown events — GitHub would retry up to 3× unnecessarily.
- New repo-layer functions required (added by this feature to `backend/app/db/repo/proposal.py`):
  - `mark_proposal_pr_merged(db, proposal_id, pr_merged_at)` — conditional UPDATE; transitions to `status='pr_merged'`. Returns the row or `None` if the row wasn't in the expected pre-state.
  - `mark_proposal_pr_closed(db, proposal_id)` — conditional UPDATE; keeps `status='pr_opened'` per §11 note.
  - `mark_proposal_pr_reopened(db, proposal_id)` — conditional UPDATE; sets `pr_state='open'`.
  - `lookup_proposal_by_pr_url(db, pr_url)` — single-row SELECT keyed on the existing `pr_url` column. **Requires a new B-tree index** `proposals_pr_url_idx` on `proposals(pr_url) WHERE pr_url IS NOT NULL` — sequential scan would be fine at MVP1 scale (<1000 proposals) but the index is the canonical pattern and costs nothing to add in the migration that this feature ships (FR-4 below).
- Notes: covers US-20.

### FR-2: Polling reconciler
- The system **MUST** define `reconcile_pr_state` as an Arq cron job registered via `WorkerSettings.cron_jobs = [arq_cron(reconcile_pr_state, minute={0, 15, 30, 45})]` in `backend/workers/all.py` (the every-15-min cadence; `minute=` set drives the schedule, not `hour=`). The poll-cadence override is sourced from `Settings.relyloop_pr_poll_minutes` (env var `RELYLOOP_PR_POLL_MINUTES`, default `15`); the cron-job tuple is constructed at module-load time from that value.
- The job **MUST** query `proposals WHERE status='pr_opened' AND pr_state='open' AND pr_url IS NOT NULL AND created_at > now() - interval '90 days'` (90-day cap to avoid unbounded growth) via a new repo function `list_pr_opened_proposals_for_reconcile(db)` in `backend/app/db/repo/proposal.py`.
- For each, the job **MUST** parse `{owner}/{repo}/{number}` from `pr_url`, resolve the per-repo PAT from `config_repos.auth_ref` (mounted at `./secrets/{auth_ref}` — same credential path `feat_github_pr_worker` uses for `open_pr`), and call GitHub REST `GET /repos/{owner}/{repo}/pulls/{number}` with `Authorization: token <PAT>`:
  - On 200 with `merged=true`: call `mark_proposal_pr_merged(db, proposal_id, pr_merged_at)`.
  - On 200 with `state='closed'` and `merged=false`: call `mark_proposal_pr_closed(db, proposal_id)`.
  - On 200 with `state='open'`: no-op.
  - On 404 (PR deleted): log at WARN, no mutation (humans investigate — see runbook).
  - On 5xx / network failure: log at WARN, retry on next tick (no in-job retry loop).
  - On 401/403 (PAT lost permission): log at WARN; the proposal stays unreconciled. Operator action documented in runbook.
- The job **MUST** complete in <60s for ≤100 open proposals (5–10 GitHub API calls per second is well within rate-limit).
- Notes: covers US-21.

### FR-3: Webhook auto-registration on config_repo creation
- When `POST /api/v1/config-repos` (per `feat_github_pr_worker` FR-3) is called with a non-null `webhook_secret_ref`, this feature **MUST** auto-register the webhook on GitHub.
- **Transaction model** (post-commit fire-and-forget — mirrors `feat_github_pr_worker`'s `open_pr` enqueue pattern): the API handler commits the `config_repos` row first (status 201 preserved; existing `ConfigRepoDetail` response shape unchanged), then enqueues a new Arq job `register_webhook` against the just-created row. Webhook creation NEVER blocks or rolls back the row.
- **Idempotency**: the `register_webhook` worker **MUST** call `GET /repos/{owner}/{repo}/hooks?per_page=100` first, parse the response for any hook whose `config.url == "<RELYLOOP_BASE_URL>/webhooks/github"`, and skip creation if found (use the existing hook's secret). Without this, retried config-repo POSTs or worker re-enqueues create duplicate hooks.
- New hook payload (when no existing hook matches):
  - `POST /repos/{owner}/{repo}/hooks` with `{"config": {"url": "<RELYLOOP_BASE_URL>/webhooks/github", "content_type": "json", "secret": "<contents of ./secrets/{webhook_secret_ref}>"}, "events": ["pull_request"], "active": true}`.
- **Failure handling** (NOT blocking the API response): if the GitHub API call fails (4xx — PAT lacks `admin:repo_hook` scope; 5xx — GitHub down; network — timeout), the worker **MUST** call a new repo function `set_webhook_registration_error(db, config_repo_id, error)` populating `config_repos.webhook_registration_error` with a short human-readable string (e.g., `"GitHub returned 404 — PAT lacks 'admin:repo_hook' scope"`). UI surfaces this column.
- **Skip path**: if `webhook_secret_ref` is NULL on the new `config_repos` row, the API handler does NOT enqueue the worker — config_repos lives in polling-only mode silently.
- The `config_repos.webhook_registration_error` column was pre-created by `infra_adapter_elastic` (migration `0002_clusters_config_repos.py`, verified on main). This feature writes to it via the new repo function above; no schema change.

### FR-4: Migration + Settings additions
- **Migration** (single new file, next sequential ID after the current head `0005_digests`): adds a partial B-tree index `proposals_pr_url_idx` on `proposals(pr_url) WHERE pr_url IS NOT NULL` to support `lookup_proposal_by_pr_url`. Round-trips via `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` per CLAUDE.md Rule #5.
- **Settings field** added to `backend/app/core/settings.py`:
  - `relyloop_pr_poll_minutes: int = Field(default=15, ge=1, le=1440, description="Cron cadence for the reconcile_pr_state worker. MVP1 default 15; operators can raise for low-PR-volume installs to reduce GitHub API spend.")`
- **`.env.example`** updated with the new env var + a sentence-long comment.

## 8) API and data contract baseline

### 8.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/webhooks/github` | Receive GitHub PR state-change webhook | `INVALID_SIGNATURE` |

No new `/api/v1/` endpoints. This feature extends `POST /api/v1/config-repos` (per `feat_github_pr_worker` FR-3) to enqueue the `register_webhook` worker post-commit; the route's response shape and status code are unchanged.

### 8.4 Enumerated value contracts

| Field | Accepted values | Backend source of truth |
|---|---|---|
| `proposals.pr_state` | `open`, `closed`, `merged` | `backend/app/db/models/proposal.py:42-43` CHECK constraint + `backend/app/api/v1/schemas.py:666` `ProposalPrStateWire` |
| `proposals.status` | `pending`, `pr_opened`, `pr_merged`, `rejected` | `backend/app/db/models/proposal.py:39` CHECK constraint + `backend/app/api/v1/schemas.py:659` `ProposalStatusWire` |
| `X-GitHub-Event` header (handled) | `ping`, `pull_request` (others log + 200) | `backend/app/api/webhooks/github.py` (`HANDLED_EVENT_TYPES` frozenset — added by this feature) |
| Webhook response `action` field | `applied`, `noop`, `unknown_pr`, `ping` | `backend/app/api/webhooks/github.py` (`WEBHOOK_ACTION_VALUES` frozenset — added by this feature) |

### 8.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| `INVALID_SIGNATURE` | 403 | `X-Hub-Signature-256` HMAC verification failed, OR `repository.full_name` did not match any registered `config_repos.repo_url` (we treat the latter as "untrusted" to avoid enumeration). |

**All webhook responses use the project-standard `_err()` envelope** (per `backend/app/api/v1/clusters.py:73` + every other router). The previous draft proposed a webhook-specific envelope; that was rejected during spec review for consistency — GitHub doesn't parse webhook response bodies, so deviation has no upside but breaks contract-test patterns.

Success body schema:
```json
{ "status": "ok", "action": "applied" | "noop" | "unknown_pr" | "ping" }
```

Failure body schema:
```json
{ "detail": { "error_code": "INVALID_SIGNATURE", "message": "...", "retryable": false } }
```

## 9) Data model and state transitions

This feature adds NO new tables and NO new columns. The `config_repos.webhook_registration_error` column is pre-created by `infra_adapter_elastic` per [`data-model.md`](../../../01_architecture/data-model.md). The only schema change is a partial B-tree index on `proposals(pr_url)` for `lookup_proposal_by_pr_url` performance (per FR-4 above).

### State transitions

- `proposals.status`: `pr_opened → pr_merged` (on merge webhook OR polling-reconciler discovery).
- `proposals.pr_state`: `open → merged` (terminal); `open → closed` (terminal-for-this-PR but the proposal stays at `status='pr_opened'` so the operator can re-`open_pr`); `closed → open` on `action='reopened'`.

### Downstream-invariant audit

Two non-trivial invariants this feature introduces. **Audit existing/future readers BEFORE implementation**:

1. **`pr_state='closed' AND status='pr_opened'` is legitimate** (a PR was opened, then closed without merge; the operator can re-`open_pr`). Any consumer (UI badge logic, proposals list filters, query builders) that assumes `status='pr_opened' ⟹ pr_state='open'` will misrender or under-filter. `feat_proposals_ui` (not yet built) MUST treat this combination as a real state — surfaced as a distinct badge ("PR closed, re-open available").
2. **`pr_state='closed'` then back to `open` via `reopened`** is allowed by the state machine. Any consumer that treated `closed` as terminal needs to refresh on webhook delivery (TanStack Query invalidation; the existing `feat_studies_ui` digest panel already does this via `["proposals"]` cache invalidation per `feat_digest_proposal`).

## 10) Security, privacy, and compliance

- **Threats:**
  1. Forged webhooks from attackers updating `pr_state='merged'` to bypass review. **Mitigation:** HMAC-SHA256 signature verification. Without the per-repo secret, attackers can't forge.
  2. Replay attacks (intercepted webhook replayed later). **Mitigation:** state-machine idempotency means a replay is a no-op. (No `X-GitHub-Delivery` dedup needed.)
  3. Webhook secret leak. **Mitigation:** secret is mounted-file only (per [`deployment.md`](../../../01_architecture/deployment.md)); never logged; CI runs structlog redaction sweep.
  4. Polling reconciler exhausting GitHub API rate budget. **Mitigation:** O(open_PRs) per 15-min tick; rate-limit headers logged at INFO; if 429 returned, the job logs at WARN and skips remaining proposals.
- **Auditability:** N/A — `audit_log` is MVP2.

## 11) UX flows and edge cases

This feature has no UI; `feat_proposals_ui` displays `pr_state` and surfaces `webhook_registration_error`.

### Edge/error flows

- **Webhook secret mismatch** (operator rotated secret on GitHub but didn't update RelyLoop's mounted secret). All future webhooks return 403; polling reconciler still works (uses GitHub PAT, not webhook secret). `feat_proposals_ui` should surface this via "no recent webhooks delivered" warning. Out of scope for MVP1.
- **Webhook registered with stale URL** (operator changed `RELYLOOP_BASE_URL` after registering). Webhooks fail delivery on GitHub side; polling reconciler still works. Operator must re-register manually (or delete + recreate the config_repo).
- **PR deleted on GitHub.** Polling returns 404; proposal stays `pr_opened`; runbook documents the recovery (manually transition to `rejected` via direct DB write).
- **Polling tick takes >60s with many open PRs.** The next tick may overlap (Arq's cron doesn't gate on prior completion). Worst case: same PR gets two `GET /pulls/{number}` calls; both updates idempotent. Monitoring alerts at MVP2 if duration exceeds 5 minutes.

## 12) Given/When/Then acceptance criteria

### AC-1: Webhook delivers merge event

- Given a `pr_opened` proposal with `pr_url` matching a real test PR; webhook secret correctly mounted.
- When the test PR is merged on GitHub (real or simulated via `curl` POST to `/webhooks/github` with a valid HMAC-signed body containing `action=closed, merged=true`).
- Then within 5s the proposal row has `pr_state='merged'`, `pr_merged_at` populated, `status='pr_merged'`.

### AC-2: Bad signature rejected

- Given any webhook POST with an incorrect `X-Hub-Signature-256` header (OR a body whose `repository.full_name` matches no registered `config_repos` row).
- When the request lands.
- Then the response is HTTP **403** with the standard `_err()` envelope `{"detail": {"error_code": "INVALID_SIGNATURE", "message": "...", "retryable": false}}`. No proposal mutation.

### AC-3: Polling catches missed webhook

- Given a proposal with `pr_url`, `pr_state='open'`, `status='pr_opened'`. The PR was merged on GitHub but no webhook was delivered (e.g., delivery failed, mocked via no webhook fired).
- When the 15-min polling tick fires.
- Then within 60s of the tick, the proposal row reflects `pr_state='merged'` (polled from GitHub API).

### AC-4: Ping event

- Given a `POST /webhooks/github` with `X-GitHub-Event: ping` header (GitHub's connectivity test) and a valid signature against a registered repo.
- When the request lands.
- Then the response is HTTP 200 with `{status: "ok", action: "ping"}`. No mutation.

### AC-5: Unknown PR no-op

- Given a webhook for a PR whose `pull_request.html_url` doesn't match any RelyLoop proposal's `pr_url` (but `repository.full_name` matches a registered config_repo so signature verification passes).
- When the request lands.
- Then the response is HTTP 200 with `{status: "ok", action: "unknown_pr"}`. No mutation.

### AC-6: Webhook auto-registration on config-repo creation

- Given a `POST /api/v1/config-repos` with `webhook_secret_ref` populated.
- When the request lands.
- Then the `config_repos` row is created (201, existing response shape preserved) and the `register_webhook` Arq job is enqueued post-commit. The job inspects existing GitHub hooks first (`GET /hooks?per_page=100`), creates a new one only if no hook with our URL exists, and on success leaves `webhook_registration_error` NULL.

### AC-7: Webhook auto-registration failure surfaces

- Given a `POST /api/v1/config-repos` where the GitHub PAT lacks webhook-creation permissions.
- When the `register_webhook` worker runs and GitHub returns 404 / 422 from the hook-creation call.
- Then the `config_repos` row remains created (the API response is unaffected); the worker UPDATEs `webhook_registration_error = "GitHub returned 404 — PAT lacks 'admin:repo_hook' scope"`. `feat_proposals_ui` (when shipped) surfaces this column to the operator.

### AC-8: Polling cost stays reasonable

- Given 50 `pr_opened` proposals.
- When the polling tick runs.
- Then the tick completes in <30s; <60 GitHub API calls (50 + a few retries / pagination); rate-limit headers logged.

## 13) Non-functional requirements

- **Performance:** Webhook handler responds in <500ms p99 (signature verify + Postgres UPDATE). Polling tick completes in <60s for ≤100 open PRs.
- **Reliability:** Per AC-3, missed webhooks are reconciled within 15 minutes.
- **Operability:** Every webhook delivery logs `delivery_id`, `event`, `action`, `proposal_id` (if matched), `result` at INFO. Failed signatures log at WARN with `delivery_id` for GitHub-side investigation.

## 14) Test strategy requirements

- **Unit tests** (`backend/tests/unit/api/webhooks/` — new subdirectory matching the new `backend/app/api/webhooks/` source layout; the existing unit test tree (`adapters/`, `core/`, `domain/`, `llm/`, `services/`) sets the per-feature subdir precedent):
  - `test_signature.py` — HMAC-SHA256 verification with valid / invalid / missing-header signatures + empty-body edge case.
  - `test_event_dispatch.py` — event-type routing for `ping`, `pull_request` (every action listed in FR-1), unknown events.
  - `test_repo_url_normalization.py` — owner/repo extraction from `config_repos.repo_url` + `repository.full_name` parity (trailing `.git`, https vs ssh, enterprise hosts).
- **Integration tests** (`backend/tests/integration/`):
  - `test_webhook_pr_merged.py` — AC-1 (POST a synthetic signed webhook to the running API; assert proposal mutation).
  - `test_webhook_invalid_signature.py` — AC-2 (covers both signature-mismatch AND repository-not-registered → both surface as 403 `INVALID_SIGNATURE`).
  - `test_webhook_unknown_pr.py` — AC-5.
  - `test_webhook_ping.py` — AC-4.
  - `test_polling_reconciler.py` — AC-3 + AC-8 (cassette-replayed GitHub API via `pytest-recording`).
  - `test_register_webhook_worker.py` — AC-6, AC-7 (cassette-replayed `GET /hooks` + `POST /hooks`; both happy path and dedup-skip path).
  - `test_config_repos_extension.py` — verifies that the existing `POST /api/v1/config-repos` route's response shape + status code are unchanged after this feature wires the post-commit Arq enqueue (LOW #16 — covers GPT-5.5's "contract preservation" finding).
- **Contract tests** (`backend/tests/contract/`):
  - `test_webhook_api_contract.py` — webhook success bodies match the `{status, action}` schema; failure body matches the standard `_err()` envelope; 403 returned on signature failures.

## 15) Documentation update requirements

- `docs/01_architecture/apply-path.md` already documents the webhook + polling architecture; update if implementation diverges.
- `docs/03_runbooks/`: add `webhook-debugging.md` — investigate failed deliveries, manually re-fire a webhook, rotate secrets.
- `docs/02_product/mvp1-user-stories.md`: mark US-20 / US-21 as "implemented".

## 16) Rollout and migration readiness

- **Feature flags:** None.
- **Migration/backfill:** None — this feature creates no tables and adds no columns.
- **Operational readiness gates:** Synthetic webhook flips a proposal in <5s; polling catches a deliberately-missed webhook in <15 min.

## 17) Traceability matrix

| FR ID | AC IDs | Stories (TBD) | Test files | Docs |
|---|---|---|---|---|
| FR-1 (webhook endpoint) | AC-1, AC-2, AC-4, AC-5 | TBD | `tests/unit/api/webhooks/test_*.py`, `tests/integration/test_webhook_pr_merged.py`, `test_webhook_invalid_signature.py`, `test_webhook_unknown_pr.py`, `test_webhook_ping.py`, `tests/contract/test_webhook_api_contract.py` | runbook |
| FR-2 (polling reconciler) | AC-3, AC-8 | TBD | `tests/integration/test_polling_reconciler.py` | runbook |
| FR-3 (auto-registration via `register_webhook` worker) | AC-6, AC-7 | TBD | `tests/integration/test_register_webhook_worker.py`, `test_config_repos_extension.py` | runbook |
| FR-4 (migration + Settings) | (covered by `make test-unit` test-migration round-trip + Settings unit tests) | TBD | `tests/integration/test_pr_url_index_migration.py`, `tests/unit/core/test_settings_pr_poll.py` | — |

## 18) Definition of feature done

- [ ] AC-1 through AC-8 pass.
- [ ] All test layers green; ≥80% coverage on `backend/app/api/webhooks/github.py` + `backend/workers/pr_reconcile.py` + `backend/workers/register_webhook.py`.
- [ ] Migration round-trips cleanly (`alembic upgrade head && alembic downgrade -1 && alembic upgrade head`).
- [ ] Synthetic webhook flips a proposal in <5s.
- [ ] `docs/03_runbooks/webhook-debugging.md` merged.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None — all resolved (see Decision log).

### Decision log

- 2026-05-09 — Webhook + polling = belt and suspenders — per umbrella spec §16 lines 1140+.
- 2026-05-09 — HMAC-SHA256 signature mandatory; no unsigned-acceptance escape — security-baseline principle.
- 2026-05-09 — `RELYLOOP_BASE_URL`: **`webhook_secret_ref` NULL means polling-only (the default for laptop installs); operators with real public URLs supply both** the secret AND a non-localhost `RELYLOOP_BASE_URL`. Documented in `docs/03_runbooks/webhook-debugging.md`.
- 2026-05-09 — Polling cadence: **`RELYLOOP_PR_POLL_MINUTES` env var with 15-min default**.
- 2026-05-09 — `X-GitHub-Delivery` dedup: **SKIP for MVP1** — state-machine idempotency is enough. Add per-delivery dedup at MVP2 if real duplicate-replay issues appear.
- 2026-05-09 — `config_repos.webhook_registration_error` column owned by `infra_adapter_elastic` (full schema there) — this feature only writes; no migration here. (Verified: migration `0002_clusters_config_repos.py` already creates the column on main.)
- 2026-05-12 (spec review patches) — **Error envelope: standard `_err()` shape, not webhook-specific.** Evaluated a webhook-specific `{status:"error", error_code, message}` envelope and rejected it: GitHub doesn't parse webhook response bodies, so there's no upside to deviating, and the standard envelope keeps contract-test patterns + `_err()` callers consistent across the API.
- 2026-05-12 (spec review patches) — **HTTP 403 (not 401) for `INVALID_SIGNATURE`.** Semantically correct (the request IS identified — it has a signature — but the signature doesn't authorize it). Matches GitHub's own receiver convention.
- 2026-05-12 (spec review patches) — **FR-3 transaction model: post-commit fire-and-forget via Arq.** Mirrors the `feat_github_pr_worker` `open_pr` enqueue pattern. The API handler commits the row and dispatches `register_webhook`; the worker handles the GitHub-side call (idempotent via `GET /hooks` pre-check) and writes `webhook_registration_error` on failure. Keeps the API endpoint fast and transactionally clean.
- 2026-05-12 (spec review patches) — **Secret resolution via `repository.full_name`, not `pull_request.html_url`.** `ping` events have no `pull_request` object, so PR-URL lookup would fail on GitHub's very first webhook delivery to a new endpoint. `repository.full_name` is present on every event.
- 2026-05-12 (spec review patches) — **Polling reconciler PAT: per-repo `config_repos.auth_ref`** (same path `feat_github_pr_worker` uses for `open_pr`). Avoids a separate global PAT.
- 2026-05-12 (spec review patches) — **New repo functions explicitly enumerated in FR-1 + FR-2**: `mark_proposal_pr_merged`, `mark_proposal_pr_closed`, `mark_proposal_pr_reopened`, `lookup_proposal_by_pr_url`, `list_pr_opened_proposals_for_reconcile`, `set_webhook_registration_error`. The previous draft described SQL-level updates without naming the repo surface — the implementation plan would have had to invent names.
- 2026-05-12 (spec review patches) — **New migration introduced** (FR-4) for the partial index on `proposals(pr_url) WHERE pr_url IS NOT NULL`. Spec previously claimed "no schema change"; that was accurate for columns but missed the index.
