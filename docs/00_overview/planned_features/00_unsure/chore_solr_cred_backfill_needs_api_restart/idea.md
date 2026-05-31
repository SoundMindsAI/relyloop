# chore: backfilling cluster_credentials into a *running* stack needs an `api` restart

**Type:** chore (operator-doc gap)
**Priority:** P2
**Origin:** infra_adapter_solr rework, Phase 4 (cluster registration + capability probe), 2026-05-30. Surfaced while validating the live Solr adapter end-to-end against the running Compose stack.

## Problem

`scripts/install.sh` step 5a backfills a `local-solr:` entry into a
**pre-existing** `./secrets/cluster_credentials.yaml`. That write is correct
and idempotent. But the `api` (and `worker`) process reads the YAML through
`Settings.cluster_credentials_yaml`, which is a `@cached_property` on an
`@lru_cache`'d `get_settings()` (`backend/app/core/settings.py`). The file
content is therefore memoized **at process start**.

Consequence: if the stack is already running when the backfill happens (or
when an operator hand-edits the creds file), the api keeps serving the *old*
YAML. A freshly-registered `local-solr` cluster then reports
`health: unreachable — credentials_ref 'local-solr' not found` until the api
process is restarted, even though the mounted file (a live Docker bind mount)
already contains the entry. `docker compose restart api` forces a re-read and
resolves it.

In the **normal** `make up` operator flow this is not hit: install.sh writes
the creds file *before* `docker compose up -d` starts the containers, so the
api boots with the entry already present. The gap only bites the incremental
path — editing creds against an already-running stack (exactly what happened
during this rework, and what an operator adding a new production cluster's
credentials mid-session would hit).

## Why deferred (not fixed inline)

This is a documentation gap, not a code bug — the caching is intentional
(avoids per-request file IO). The fix is a one-line note in the Solr
cluster-registration runbook (`docs/03_runbooks/solr-cluster-registration.md`):
after editing `cluster_credentials.yaml` on a running stack, run
`docker compose restart api worker` so the new credentials are picked up. The
same caching applies to ES/OpenSearch creds, so the note should be generalized,
not Solr-specific.

## Suggested fix

Add a "Credential changes need a restart" callout to
`docs/03_runbooks/solr-cluster-registration.md` (generalized to all engines),
and optionally next to install.sh step 5a.
