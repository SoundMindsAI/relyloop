# Bug fix — pr_reconciler_blocked_by_closed_fallback

**Source idea:** [idea.md](./idea.md)
**Branch:** `bug/pr-reconciler-blocked-by-closed-fallback`
**Type:** bug fix — medium (single subsystem, ~140 LOC across worker + repo + tests + runbook)
**Date:** 2026-05-23

## Problem

GitHub's PR-closed webhook delivery occasionally arrives with `merged=true` AND `merged_at=null` (eventual-consistency edge case). The receiver's fallback at [`backend/app/api/webhooks/github.py:181-209`](../../../../backend/app/api/webhooks/github.py#L181-L209) calls `mark_proposal_pr_closed` and leaves the proposal in `(pr_opened, closed)`. The polling reconciler is supposed to catch up later — but it can't, for two compounding reasons:

1. The candidate query [`list_pr_opened_proposals_for_reconcile`](../../../../backend/app/db/repo/proposal.py#L455-L475) filtered to `pr_state='open'`, so fallback-closed rows were **never selected** as candidates.
2. Even if they had been, `mark_proposal_pr_merged` required `pr_state='open'` and would return None.

The proposal stayed stuck in `(pr_opened, closed)` forever, looked like an abandoned PR to operators, and never contributed to `config_repos.last_merged_proposal_id` (FR-3a pointer-update gap from `feat_config_repo_baseline_tracking`).

## Reproduction

```bash
# This test fails on `main` (candidates=0; recovery never runs)
# and passes on this branch:
docker run --rm --network relyloop_default \
  -v "$(pwd):/app" -v /app/.venv -w /app \
  -e DATABASE_URL_FILE=/app/secrets/database_url \
  -e POSTGRES_PASSWORD_FILE=/app/secrets/postgres_password \
  ghcr.io/astral-sh/uv:python3.13-bookworm \
  bash -c 'uv sync --quiet && uv run pytest \
    backend/tests/integration/test_pr_reconcile_config_repo_pointer.py::test_reconciler_recovers_fallback_closed_proposal \
    -v'
```

Verified: on `main` the test asserts `summary["reconciled"] >= 1` and gets `0`. After the fix, `reconciled == 1` and the proposal transitions to `(pr_merged, merged)` with the pointer correctly maintained.

## Root cause

- **Owning layer:** workers (reconciler routing) + repo (proposal state machine)
- **Primary blocker:** [`backend/app/db/repo/proposal.py:455-475`](../../../../backend/app/db/repo/proposal.py#L455-L475) — candidate query WHERE clause excluded fallback-closed rows entirely
- **Secondary blocker:** [`backend/app/db/repo/proposal.py:347-380`](../../../../backend/app/db/repo/proposal.py#L347-L380) — `mark_proposal_pr_merged` requires `pr_state='open'`, so even an Out-of-band recovery attempt would no-op against closed rows

## Fix design (locked decisions)

1. **Option B over Option A.** New repo helper `mark_proposal_pr_merged_from_closed` doing a single atomic UPDATE on `(pr_opened, closed) → (pr_merged, merged)`. Cites: matches the single-conditional-UPDATE style of every other `mark_proposal_pr_*` helper in [`backend/app/db/repo/proposal.py`](../../../../backend/app/db/repo/proposal.py); avoids the two-UPDATE `reopen+merge` round-trip; idempotent under concurrent ticks (the second worker's WHERE matches zero rows).
2. **Widen the candidate query, don't narrow it later.** Drop the `pr_state='open'` clause from `list_pr_opened_proposals_for_reconcile`; keep `pr_url IS NOT NULL` and the 90-day window. Cites: minimal change; the polling cost for genuinely-closed-unmerged proposals (case b) is bounded by the 90-day window and is the natural price of recovering case-a proposals.
3. **Branch on `proposal.pr_state` in the reconciler.** For `pr_state='open'` keep the existing `mark_proposal_pr_merged` path unchanged; for `pr_state='closed'` route to the new helper. Pointer-update branch fires from both paths. Cites: minimal touch to the existing happy-path code.
4. **Emit `pr_reconcile_recovered_eventual_consistency` INFO log on recovery.** Cites: operators need a grep handle to measure real-world incidence; matches the existing structlog-event vocabulary in [`backend/workers/pr_reconcile.py`](../../../../backend/workers/pr_reconcile.py).
5. **No backfill migration.** Cites: reconciler picks up historical fallback-closed rows within the 90-day window automatically on the next tick. Anything older than 90 days requires operator triage (the existing `force-reconcile` runbook recipe).

### Open questions

None — every fork was an engineering judgment call already locked in `idea.md`'s "Open questions for /spec-gen" section with cited rationale.

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| integration | `backend/tests/integration/test_pr_reconcile_config_repo_pointer.py::test_reconciler_recovers_fallback_closed_proposal` | Flipped from negative-documentation to positive-recovery: fallback-closed proposal + reconciler tick with non-null `merged_at` → `(pr_merged, merged)` AND `config_repos.last_merged_proposal_id == proposal_id` |
| integration | `backend/tests/integration/test_pr_reconcile_config_repo_pointer.py::test_reconciler_noops_on_genuinely_closed_unmerged` | NEW: `(pr_opened, closed)` proposal + reconciler observes `merged=false, state=closed` → proposal stays put, pointer NOT updated. Locks the widened candidate query against false-positive transitions. |

The existing happy-path test (`test_reconciler_observes_missed_merge_updates_pointer`) keeps the `pr_state='open'` branch under coverage.

## Rollout

None — code-only change.

- No schema migration. Alembic head unchanged at `0016_config_repos_last_merged_proposal_id`.
- No API contract change.
- No operator action required. Existing fallback-closed proposals (if any) will be recovered automatically on the next reconciler tick within the 90-day window.
- One log-event vocabulary addition (`pr_reconcile_recovered_eventual_consistency`) — additive, doesn't break log consumers.
- Stale comments at [`backend/workers/pr_reconcile.py:183-189`](../../../../backend/workers/pr_reconcile.py) and the runbook §8 "Known limitation" paragraph at [`docs/03_runbooks/webhook-debugging.md`](../../../03_runbooks/webhook-debugging.md) are updated to reflect the recovery path.

## Tangential observations

None.
