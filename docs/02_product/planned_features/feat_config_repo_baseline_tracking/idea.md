# Config Repo Baseline Tracking — record the last merged proposal per `config_repo` so future studies can auto-bootstrap their baseline

**Date:** 2026-05-21
**Status:** Idea — surfaced during the 2026-05-21 Karpathy-loop audit.
**Origin:** Standalone audit at `~/.claude/plans/compressed-sparking-hamming.md` — the "across studies" gap section. Verified live via grep of [`backend/app/db/models/config_repo.py`](../../../../backend/app/db/models/config_repo.py) (no `last_merged_*` field) + [`backend/app/api/webhooks/github.py:183-191`](../../../../backend/app/api/webhooks/github.py) (the merge webhook stamps `pr_merged_at` on the *proposal* but does not propagate that to the config repo).
**Depends on:** [`feat_github_webhook`](../../../00_overview/implemented_features/2026_05_12_feat_github_webhook/) (shipped 2026-05-12) — provides the merge event that this feature consumes.

## Problem

RelyLoop does not track which configuration is currently live in production. When a proposal's PR merges, the merge webhook at [`backend/app/api/webhooks/github.py:187-191`](../../../../backend/app/api/webhooks/github.py) updates `proposals.pr_state = 'merged'` and `proposals.pr_merged_at = <timestamp>`, but no field on [`config_repos`](../../../../backend/app/db/models/config_repo.py) (or [`clusters`](../../../../backend/app/db/models/cluster.py)) records that this was the **most recent merged proposal**. To answer "what's currently deployed?" the system has to scan all proposals for a given config repo, filter by `pr_state = 'merged'`, sort by `pr_merged_at DESC`, and take the first row. That query exists nowhere in the codebase today.

This omission compounds three downstream gaps:

1. **No baseline for the next study.** When an operator creates study B after study A's winner merged, there is no signal in the system that says "the live config is now study A's winner." The new study's `baseline_metric` (per [`backend/app/db/models/study.py`](../../../../backend/app/db/models/study.py)) is whatever the operator measures *manually* against the running cluster — there is no automated path. This blocks [`feat_auto_followup_studies`](../feat_auto_followup_studies/idea.md) at the protocol level: the auto-followup worker doesn't know which config the next study should beat.
2. **No "last shipped" surface on the proposals UI.** The proposals list at [`ui/src/app/proposals/page.tsx`](../../../../ui/src/app/proposals/page.tsx) shows pending/open/closed/merged status per proposal but cannot say "this PR superseded the one that shipped 5 days ago — here's what changed since then." A `config_repos.last_merged_proposal_id` denormalization gives the UI the anchor to render that view.
3. **No drift detection.** If the operator's CI/CD silently fails to deploy a merged proposal (per CLAUDE.md persona note: deploy is operator-owned, outside RelyLoop), the system has no record of "we believe X is live; operator should confirm." Knowing the last-merged proposal is the first ingredient of any "is live config in sync with our records" health check (the operator-side check itself is out of scope, but the substrate isn't).

The umbrella spec §6 hard constraint — "Approvers... cannot be bypassed... the tool delegates approval to the config repo's branch protection" — means RelyLoop never *enforces* what's deployed. But knowing what was *last merged* is internal bookkeeping, not enforcement, and there is no contradiction with the spec.

## Proposed capabilities

Single tier — small, additive, schema-only at the DB layer.

### Schema change

- **One new column** on `config_repos`: `last_merged_proposal_id VARCHAR(36) NULL REFERENCES proposals(id) ON DELETE SET NULL`. Nullable because a fresh config repo has no merged proposal yet. `ON DELETE SET NULL` because operator-deleted proposals shouldn't break the config_repo row (the proposal table doesn't currently have soft-delete; if/when it does, this changes).
- **Index** `ix_config_repos_last_merged_proposal_id` on the new FK (`btree`, default). The index is small and supports the "find the config_repo by last-merged-proposal" reverse lookup that the proposals UI uses.
- **No `last_merged_at` denormalization** — readers join to `proposals.pr_merged_at` instead. Saves a column and keeps `proposals.pr_merged_at` as the single source of truth.
- **Alembic migration** `00NN_config_repos_last_merged_proposal_id`. Strictly additive; `downgrade()` drops the FK column + index. Round-trip-clean per Absolute Rule #5.

### Webhook handler update

- **Location:** [`backend/app/api/webhooks/github.py:187-191`](../../../../backend/app/api/webhooks/github.py) — where `update_proposal_merged()` is called today.
- **New behavior:** in the same transaction as the proposal merge update, look up the proposal's `study.config_repo_id` (via the existing FK chain: `proposals → studies → cluster → config_repo`, or more directly if there's a `proposals.config_repo_id` denorm — verify in the feature spec), then `UPDATE config_repos SET last_merged_proposal_id = :proposal_id WHERE id = :config_repo_id`. Idempotent: if the new merge's `pr_merged_at` is older than the currently-tracked proposal's `pr_merged_at`, do not overwrite (an out-of-order webhook should not regress the pointer).
- **No new webhook event types** — this rides the existing `pull_request.closed` (with `merged=true`) handler path.
- **Tests:** integration test asserting the column updates when a merged-PR webhook fires; integration test asserting an older-timestamp merge does not overwrite a newer-timestamp pointer.

### Read surface

- **`ConfigRepoDetail` response model** ([`backend/app/api/v1/schemas.py`](../../../../backend/app/api/v1/schemas.py)) gains a `last_merged_proposal: ProposalSummary | None` field. The endpoint at [`backend/app/api/v1/config_repos.py`](../../../../backend/app/api/v1/config_repos.py) joins to load the proposal row.
- **Proposals list filtering** at [`backend/app/api/v1/proposals.py`](../../../../backend/app/api/v1/proposals.py) gains an optional `is_last_merged: bool` query param so the UI can highlight the live config in the list. Cursor pagination remains.
- **UI:** `ConfigRepoDetail` page (when it exists; today the cluster detail page surfaces the linked config repo) gains a "Currently live: [proposal name] — merged on [date]" badge. Minor change, ~30 LOC.

### Out of scope

- **Cluster-level baseline tracking.** Argued and rejected: `config_repos` is the right scope because one repo can serve multiple clusters (e.g., dev + staging + prod) and the operator's CI/CD applies the merged config to all of them in step. Tracking per-cluster would create three different "last merged" records for the same merge event and confuse the auto-followup story.
- **Live-cluster verification.** Querying the running cluster to confirm the merged config actually deployed is outside RelyLoop's scope per CLAUDE.md (RelyLoop never sits on the serving path).
- **Multi-repo studies.** A future study may target multiple config repos. The schema permits this naturally (each repo gets its own `last_merged_proposal_id`); the UI surface is out of scope until that user story is real.

## Scope signals

- **Backend:** ~150 LOC. Alembic migration (~30 LOC) + ORM field (~5) + webhook handler update (~30) + idempotency check (~15) + response-model field (~10) + endpoint join (~20) + tests across unit/integration/contract (~50).
- **Frontend:** ~50 LOC for the "Currently live" badge on the config repo / cluster detail surface + 1 vitest case.
- **Migration:** one strictly additive Alembic migration. Nullable column + index. Round-trip drops cleanly.
- **Config:** none.
- **Audit events:** N/A (MVP1 has no audit_log).
- **Tests:**
  - Integration: 3 cases — webhook fires + column updates; older-timestamp webhook is a no-op; cascade-delete of proposal nulls the column.
  - Contract: 1 case — `GET /config_repos/{id}` response shape includes `last_merged_proposal`.
  - Migration round-trip: 1 test.

## Why not implemented inline today

1. **Schema migration on a production table.** `config_repos` is a real shared table — any schema change ships through the Alembic discipline (Absolute Rule #5) plus a round-trip-clean verify. Not a drive-by.
2. **Cross-cuts the webhook + proposals routers.** The webhook handler is a hot path (CLAUDE.md persona note: "webhook idempotency required"). Adding logic without spec-shaped scrutiny risks subtle ordering bugs.
3. **Substrate for a larger feature.** This feature has no user-visible behavior change by itself — it's bookkeeping. The "Currently live" badge is mild; the real payoff lands when [`feat_auto_followup_studies`](../feat_auto_followup_studies/idea.md) consumes the new column. Shipping the substrate as its own small PR lets reviewers focus on the schema + idempotency, then the consumer lands cleanly on top.

## Relationship to other work

- **Required by [`feat_auto_followup_studies`](../feat_auto_followup_studies/idea.md)** — that feature's auto-chained follow-up worker needs to know "what's currently deployed?" to set the next study's baseline meaningfully. This idea ships first.
- **Adjacent to [`feat_pr_metric_confidence`](../feat_pr_metric_confidence/idea.md)** — the PR body would naturally include "previously deployed: [last_merged_proposal_name] from [date]" as part of the confidence framing. Composes cleanly once both ship.
- **Extends [`feat_github_webhook`](../../../00_overview/implemented_features/2026_05_12_feat_github_webhook/)** — the merge event becomes load-bearing for a downstream feature, raising the importance of the webhook's existing idempotency invariants.
- **Visible in [`feat_proposals_ui`](../../../00_overview/implemented_features/2026_05_12_feat_proposals_ui/)** — the proposals list gains a "live config" indicator and the proposal-detail page can show "supersedes proposal X" backwards-pointer.
