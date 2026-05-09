# Feature Specification — feat_github_webhook

**Date:** 2026-05-09
**Status:** Draft
**Owners:** TBD
**Related docs:**
- [docs/02_product/mvp1-user-stories.md](../../mvp1-user-stories.md) — covers US-20, US-21
- [docs/01_architecture/apply-path.md](../../../01_architecture/apply-path.md) — Git PR workflow architecture (webhook receiver section)
- [docs/01_architecture/api-conventions.md](../../../01_architecture/api-conventions.md) — webhook conventions
- Depends on: [`infra_foundation`](../infra_foundation/feature_spec.md), [`feat_github_pr_worker`](../feat_github_pr_worker/feature_spec.md)
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
  - Verifies `X-Hub-Signature-256` HMAC-SHA256 against the `webhook_secret_ref` mounted secret resolved per-repo (looked up via `pr_url` → `config_repos` → `webhook_secret_ref`)
  - Handles event types: `pull_request` (action `closed` or `merged`), `ping` (responds with 200 immediately for GitHub's webhook-test ping)
  - Returns 401 on bad signature, 200 on accepted event (always — GitHub retries on non-200), 404 only for unknown event types (logged at WARN)
  - Updates `proposals.pr_state` and `pr_merged_at`; transitions `proposals.status: pr_opened → pr_merged` if the PR was merged
- Polling reconciler `reconcile_pr_state` Arq job triggered every 15 minutes via `arq.cron`:
  - Queries `proposals WHERE status = 'pr_opened' AND pr_state = 'open' AND pr_url IS NOT NULL`
  - For each, calls GitHub REST `GET /repos/{owner}/{repo}/pulls/{number}` to fetch current state
  - Updates `pr_state` and `pr_merged_at` if changed
  - Skips proposals where the GitHub API returns 404 (PR was deleted) — logs at WARN, leaves the proposal as-is
- Idempotency: replay of the same webhook event MUST be a no-op (the state transition is already-applied; no duplicate audit entries). GitHub's `X-GitHub-Delivery` header is captured to a per-proposal log but isn't used as a dedup key in MVP1 (idempotency is achieved by virtue of the state-machine semantics).

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
- **Do not** retry webhook handler failures. If signature verification fails, return 401; if Postgres write fails, return 500 (GitHub retries). No internal retry loop.

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
- `POST /webhooks/github` accepts JSON body, headers including `X-Hub-Signature-256`, `X-GitHub-Event`, `X-GitHub-Delivery`.
- The endpoint **MUST** look up the relevant `config_repos` row by parsing the body's `repository.full_name` (`owner/repo`) and matching against `repo_url`.
- The endpoint **MUST** verify the HMAC-SHA256 signature using the `webhook_secret_ref`-mounted secret. If verification fails, return HTTP 401 with `INVALID_SIGNATURE`.
- The endpoint **MUST** return 200 immediately for `X-GitHub-Event: ping` (GitHub's webhook-test).
- For `X-GitHub-Event: pull_request` with `action ∈ {closed, opened, reopened, edited, ...}`:
  - Look up the proposal by `pr_url` (constructed from `pull_request.html_url`)
  - If proposal not found, return 200 with `{status: 'unknown_pr', message: 'No proposal matches this PR'}` (GitHub fired a webhook for a PR not created by us — fine)
  - If `action='closed' AND merged=true`: update `pr_state='merged'`, `pr_merged_at = pull_request.merged_at`, `status='pr_merged'`
  - If `action='closed' AND merged=false`: update `pr_state='closed'`. Status stays `pr_opened` (the proposal was rejected upstream; the user can re-`open_pr` if desired).
  - If `action='reopened'`: update `pr_state='open'`. Status stays `pr_opened`.
  - Other actions: log + return 200 (no-op).
- For unknown `X-GitHub-Event`: log at INFO + return 200 (forward-compatible with new GitHub events).
- Notes: covers US-20.

### FR-2: Polling reconciler
- The system **MUST** define `reconcile_pr_state` as a cron Arq job running every 15 minutes via `arq.cron(reconcile_pr_state, hour={...})` (or equivalent every-15-min pattern).
- The job **MUST** query `proposals WHERE status='pr_opened' AND pr_state='open' AND pr_url IS NOT NULL AND created_at > now() - interval '90 days'` (90-day cap to avoid unbounded growth).
- For each, the job **MUST** call GitHub REST `GET /repos/{owner}/{repo}/pulls/{number}` (parsed from `pr_url`) and:
  - On 200 with `merged=true`: update `pr_state='merged'`, `pr_merged_at`, `status='pr_merged'`
  - On 200 with `state='closed'` and `merged=false`: update `pr_state='closed'`
  - On 200 with `state='open'`: no-op
  - On 404 (PR deleted): log at WARN, no mutation (humans investigate)
  - On 5xx / network failure: log at WARN, retry on next tick (no in-job retry loop)
- The job **MUST** complete in <60s for ≤100 open proposals (5–10 GitHub API calls per second is well within rate-limit).
- Notes: covers US-21.

### FR-3: Webhook auto-registration on config_repo creation
- When `POST /api/v1/config-repos` (per `feat_github_pr_worker` FR-3) is called with a non-null `webhook_secret_ref`, this feature **MUST** auto-register the webhook on GitHub via REST `POST /repos/{owner}/{repo}/hooks` with config:
  - `url`: `<RELYLOOP_BASE_URL>/webhooks/github`
  - `content_type`: `json`
  - `secret`: the secret content from `webhook_secret_ref`-mounted file
  - `events`: `["pull_request"]`
- If GitHub API fails (404 — repo not accessible to the PAT, 422 — webhook URL unreachable from GitHub), return 200 from `POST /api/v1/config-repos` (the config_repo IS registered) but populate `config_repos.webhook_registration_error` (column pre-created by `infra_adapter_elastic`; see next bullet). UI surfaces this.
- If `webhook_secret_ref` is NULL, skip webhook registration silently (polling-only mode).
- The `config_repos.webhook_registration_error` column is pre-created by `infra_adapter_elastic` per [`data-model.md` §"MVP1 table inventory + migration ownership"](../../../01_architecture/data-model.md); this feature only writes to it.

## 8) API and data contract baseline

### 7.1 Endpoint surface

| Method | Path | Purpose | Key error codes |
|---|---|---|---|
| `POST` | `/webhooks/github` | Receive GitHub PR state-change webhook | `INVALID_SIGNATURE` |

No `/api/v1/` endpoints — this feature only consumes (auto-registers webhooks via `POST /api/v1/config-repos` extension) and provides the webhook receiver.

### 7.4 Enumerated value contracts

| Field | Accepted values | Backend source of truth |
|---|---|---|
| `proposals.pr_state` | `open`, `closed`, `merged` | `backend/db/models/proposal.py` (per `feat_digest_proposal`) |
| `X-GitHub-Event` header (handled) | `ping`, `pull_request` (others log + 200) | `backend/api/webhooks/github.py` (`HANDLED_EVENT_TYPES` frozenset) |

### 7.5 Error code catalog

| Code | HTTP Status | Meaning |
|---|---|---|
| `INVALID_SIGNATURE` | 401 | `X-Hub-Signature-256` HMAC verification failed |

Webhook responses use a different envelope shape from the standard API:
```json
// Success
{ "status": "ok", "action": "<applied|noop|unknown_pr>" }

// Failure
{ "status": "error", "error_code": "INVALID_SIGNATURE", "message": "..." }
```

This matches GitHub's expectations for webhook responses (they don't require RFC 7807; they care about the HTTP status and don't parse the body).

## 9) Data model and state transitions

This feature adds NO new tables and ADDS NO new columns. The `config_repos.webhook_registration_error` column is pre-created by `infra_adapter_elastic` per [`data-model.md`](../../../01_architecture/data-model.md).

### State transitions

`proposals.status`: `pr_opened → pr_merged` (on merge webhook OR polling-reconciler discovery).
`proposals.pr_state`: `open → closed | merged` (terminal); `open → open` (no-op events).

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

- **Webhook secret mismatch** (operator rotated secret on GitHub but didn't update RelyLoop's mounted secret). All future webhooks return 401; polling reconciler still works (uses GitHub PAT, not webhook secret). `feat_proposals_ui` should surface this via "no recent webhooks delivered" warning. Out of scope for MVP1.
- **Webhook registered with stale URL** (operator changed `RELYLOOP_BASE_URL` after registering). Webhooks fail delivery on GitHub side; polling reconciler still works. Operator must re-register manually (or delete + recreate the config_repo).
- **PR deleted on GitHub.** Polling returns 404; proposal stays `pr_opened`; runbook documents the recovery (manually transition to `rejected` via direct DB write).
- **Polling tick takes >60s with many open PRs.** The next tick may overlap (Arq's cron doesn't gate on prior completion). Worst case: same PR gets two `GET /pulls/{number}` calls; both updates idempotent. Monitoring alerts at MVP2 if duration exceeds 5 minutes.

## 12) Given/When/Then acceptance criteria

### AC-1: Webhook delivers merge event

- Given a `pr_opened` proposal with `pr_url` matching a real test PR; webhook secret correctly mounted.
- When the test PR is merged on GitHub (real or simulated via `curl` POST to `/webhooks/github` with a valid HMAC-signed body containing `action=closed, merged=true`).
- Then within 5s the proposal row has `pr_state='merged'`, `pr_merged_at` populated, `status='pr_merged'`.

### AC-2: Bad signature rejected

- Given any webhook POST with an incorrect `X-Hub-Signature-256` header.
- When the request lands.
- Then the response is HTTP 401 with `error_code: INVALID_SIGNATURE`. No proposal mutation.

### AC-3: Polling catches missed webhook

- Given a proposal with `pr_url`, `pr_state='open'`, `status='pr_opened'`. The PR was merged on GitHub but no webhook was delivered (e.g., delivery failed, mocked via no webhook fired).
- When the 15-min polling tick fires.
- Then within 60s of the tick, the proposal row reflects `pr_state='merged'` (polled from GitHub API).

### AC-4: Ping event

- Given a `POST /webhooks/github` with `X-GitHub-Event: ping` header (GitHub's connectivity test).
- When the request lands.
- Then the response is HTTP 200 with `{status: 'ok', action: 'noop'}`. No mutation.

### AC-5: Unknown PR no-op

- Given a webhook for a PR whose URL doesn't match any RelyLoop proposal.
- When the request lands (signature valid).
- Then the response is HTTP 200 with `{status: 'ok', action: 'unknown_pr'}`. No mutation.

### AC-6: Webhook auto-registration on config-repo creation

- Given a `POST /api/v1/config-repos` with `webhook_secret_ref` populated.
- When the request lands.
- Then within the response's lifetime, GitHub `POST /repos/{owner}/{repo}/hooks` was called with the correct config; `webhook_registration_error` is NULL on success.

### AC-7: Webhook auto-registration failure surfaces

- Given a `POST /api/v1/config-repos` where the GitHub PAT lacks webhook-creation permissions.
- When GitHub returns 404 from the hook-creation call.
- Then the config_repos row is still created; `webhook_registration_error = "GitHub returned 404 — PAT lacks 'admin:repo_hook' scope"`.

### AC-8: Polling cost stays reasonable

- Given 50 `pr_opened` proposals.
- When the polling tick runs.
- Then the tick completes in <30s; <60 GitHub API calls (50 + a few retries / pagination); rate-limit headers logged.

## 13) Non-functional requirements

- **Performance:** Webhook handler responds in <500ms p99 (signature verify + Postgres UPDATE). Polling tick completes in <60s for ≤100 open PRs.
- **Reliability:** Per AC-3, missed webhooks are reconciled within 15 minutes.
- **Operability:** Every webhook delivery logs `delivery_id`, `event`, `action`, `proposal_id` (if matched), `result` at INFO. Failed signatures log at WARN with `delivery_id` for GitHub-side investigation.

## 14) Test strategy requirements

- **Unit tests** (`backend/tests/unit/`):
  - `api/webhooks/test_signature.py` — HMAC-SHA256 verification with valid/invalid signatures + edge cases (empty body, missing header).
  - `api/webhooks/test_event_dispatch.py` — event-type routing for `ping`, `pull_request` (various actions), unknown events.
- **Integration tests** (`backend/tests/integration/`):
  - `test_webhook_pr_merged.py` — AC-1 (POST a synthetic webhook to the running API; assert proposal mutation).
  - `test_webhook_invalid_signature.py` — AC-2.
  - `test_webhook_unknown_pr.py` — AC-5.
  - `test_polling_reconciler.py` — AC-3 (cassette-replayed GitHub API).
  - `test_webhook_auto_registration.py` — AC-6, AC-7.
- **Contract tests:**
  - `test_webhook_response_shapes.py` — webhook responses match the documented body shape.

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
| FR-1 (webhook endpoint) | AC-1, AC-2, AC-4, AC-5 | TBD | `tests/integration/test_webhook_*.py` | runbook |
| FR-2 (polling reconciler) | AC-3, AC-8 | TBD | `tests/integration/test_polling_reconciler.py` | runbook |
| FR-3 (auto-registration) | AC-6, AC-7 | TBD | `tests/integration/test_webhook_auto_registration.py` | runbook |

## 18) Definition of feature done

- [ ] AC-1 through AC-8 pass.
- [ ] All test layers green; ≥80% coverage on `backend/api/webhooks/github.py`, `backend/worker/pr_reconcile.py`.
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
- 2026-05-09 — `config_repos.webhook_registration_error` column owned by `infra_adapter_elastic` (full schema there) — this feature only writes; no migration here.
