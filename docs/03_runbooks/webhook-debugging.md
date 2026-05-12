# Webhook debugging — operator runbook

Operational playbook for the GitHub webhook receiver (`POST /webhooks/github`),
the polling reconciler (`reconcile_pr_state` cron), and the auto-register worker
(`register_webhook` Arq job) introduced by `feat_github_webhook`.

> Companion docs: [`pr-open-debugging.md`](pr-open-debugging.md) covers the
> `open_pr` worker; this runbook covers the *post-merge* lifecycle —
> webhook delivery, state reconciliation, and webhook auto-registration.

---

## 1. Inspect the last delivery from GitHub

GitHub's "Webhooks" panel on the config repo settings page lists every
delivery with its response code, headers, and body.

1. Visit `https://github.com/<owner>/<repo>/settings/hooks` (operator
   needs `admin:repo_hook` scope).
2. Click the configured RelyLoop hook.
3. Open the **Recent Deliveries** tab. Each row shows the response
   code from `POST /webhooks/github`. A green checkmark means RelyLoop
   responded `200`; a red `X` means non-`200`.
4. Click any delivery to inspect the raw request + response. The
   request body is the GitHub payload; the response body is RelyLoop's
   error envelope (e.g. `{"detail": {"error_code": "INVALID_SIGNATURE", ...}}`).

## 2. Re-fire a webhook

In the Recent Deliveries panel, click **Redeliver** on the failed
delivery. GitHub re-issues the exact same payload (same
`X-GitHub-Delivery` header). RelyLoop's handler is idempotent — repeat
deliveries of the same state transition match zero rows on the
conditional UPDATE and return `{"action": "applied"}` with no
secondary mutation.

## 3. Verify the receive line in RelyLoop logs

For every delivery that passes signature verification, the handler
emits one structured log line:

```
make logs | rg "webhook_received"
```

Example:

```json
{
  "event": "webhook_received",
  "delivery_id": "abc-123",
  "event_type": "pull_request",
  "action": "applied",
  "proposal_id": "0190a83b-...",
  "result": "applied"
}
```

For deliveries the handler rejected with `403 INVALID_SIGNATURE`:

```
make logs | rg "webhook_invalid_signature"
```

The `reason` field disambiguates: `bad_signature` (HMAC mismatch), or
`unknown_repo` (no `config_repos` row matches the
`repository.full_name`).

## 4. Rotate the webhook secret

The webhook HMAC secret lives at `./secrets/{config_repos.webhook_secret_ref}`
(mounted via Compose secrets). Rotation procedure:

1. Generate a new secret: `openssl rand -hex 32 > ./secrets/<new-name>`.
2. Update GitHub's hook config:
   - Settings → Webhooks → click the hook → "Edit"
   - Paste the new secret into the "Secret" field
   - Save.
3. Update RelyLoop's `config_repos.webhook_secret_ref` (currently
   requires a direct DB update; the MVP1 API doesn't expose a PATCH
   endpoint):
   ```sql
   UPDATE config_repos
      SET webhook_secret_ref = '<new-name>'
    WHERE id = '<config-repo-id>';
   ```
4. Restart the API container so the new file gets re-read on the next
   request: `make restart` (or `docker compose restart api`).
5. Trigger a redelivery from GitHub's webhook panel. Confirm the log
   line shows `webhook_received` with `action="applied"` (or `ping`
   for a ping event).

## 5. Force-reconcile a specific proposal

The polling reconciler runs every `RELYLOOP_PR_POLL_MINUTES` minutes
(default 15). To run a tick on demand:

```bash
docker compose exec worker python -c "
import asyncio
from backend.workers.pr_reconcile import reconcile_pr_state
print(asyncio.run(reconcile_pr_state({})))
"
```

The summary dict logs `{candidates, reconciled, unchanged, errored,
rate_limited}` so you can see whether the tick found your proposal.
If `candidates: 0`, the proposal is either:

- Already in `pr_merged` / `rejected` (not a polling target).
- `pr_state IS NULL` (PR hasn't been opened yet — different worker).
- `created_at` is older than 90 days (FR-2 cap).
- Has no `pr_url` (operator-cancelled or never opened).

## 6. Polling reconciler not running

If the cron job seems silent:

```bash
docker compose logs worker | rg "reconcile_pr_state|pr_reconcile"
```

Expected cadence: one `pr_reconcile_tick_complete` line every
`RELYLOOP_PR_POLL_MINUTES` minutes. If you see nothing:

1. Confirm `Settings.relyloop_pr_poll_minutes` is in the whitelist
   (`{1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60, 120, 180, 240, 360, 720, 1440}`).
   The Settings validator rejects out-of-set values at boot — check
   `docker compose logs worker | rg ValidationError`.
2. Confirm Arq's cron supervisor is up:
   `docker compose logs worker | rg "scheduled cron job"` — should
   show `reconcile_pr_state` registered.
3. Confirm Redis is reachable:
   `docker compose exec worker redis-cli -h redis ping` → `PONG`.

## 7. `register_webhook` failed — operator triage

When `POST /api/v1/config-repos` succeeds (201) but the auto-register
job failed, the failure surfaces on the `config_repos` row:

```
curl http://localhost:8000/api/v1/config-repos/<id> | jq .webhook_registration_error
```

Possible messages and their fixes:

| Error message contains | Diagnosis | Fix |
|---|---|---|
| `admin:repo_hook` | PAT lacks the scope to create webhooks | Re-issue the PAT with `admin:repo_hook`, overwrite `./secrets/{auth_ref}`, re-enqueue (Story 8 below). |
| `422` validation failed | GitHub rejected the hook payload — usually because `Settings.relyloop_base_url` is unreachable from GitHub | If running on a laptop, expose via a tunnel (`ngrok http 8000` etc.) and re-set `RELYLOOP_BASE_URL` to the tunnel URL. |
| `transient` (5xx) | GitHub had a brief outage | Re-enqueue after https://www.githubstatus.com shows green. |
| `network error` | Worker host can't reach `api.github.com` | Check egress firewall + DNS. |
| `RELYLOOP_BASE_URL is not configured` | `Settings.relyloop_base_url` is `None` | Set the env var + restart the worker. |

### Manual re-enqueue

```bash
docker compose exec worker python -c "
import asyncio
from arq.connections import RedisSettings, create_pool
from backend.app.core.settings import get_settings

async def main():
    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    await pool.enqueue_job('register_webhook', '<config-repo-id>')
    await pool.close()

asyncio.run(main())
"
```

Wait ~5 seconds, then re-read the `webhook_registration_error` column.
It should be `null` on success or carry the new failure class.

---

## Quick reference

| Symptom | Logs to check | First action |
|---|---|---|
| Deliveries 403 on every event | `webhook_invalid_signature` | Rotate the webhook secret (§4) |
| State stuck at `pr_state=open` after merge | `webhook_received` for the delivery | Force-reconcile (§5) |
| Reconciler never runs | `pr_reconcile_tick_complete` | Check Settings whitelist (§6) |
| `webhook_registration_error` populated | n/a (column read) | Match per-class fix (§7) |
| GitHub can't reach the install | n/a | Tunnel + re-set `RELYLOOP_BASE_URL` |
