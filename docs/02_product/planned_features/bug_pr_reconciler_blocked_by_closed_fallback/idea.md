# PR reconciler can't recover a proposal closed by the webhook's `merged_at=null` fallback

**Date:** 2026-05-22
**Status:** Idea — surfaced during the 2026-05-22 GPT-5.5 cycle-2 cross-model review of `feat_config_repo_baseline_tracking`. Pre-existing bug in the shipped reconciler path, not introduced by that feature.
**Priority:** P2 — rare-but-real failure mode; affects only the GitHub eventual-consistency window where `merged=true` is sent with `merged_at=null`. The proposal lands in a permanent `pr_opened+closed` state until an operator manually intervenes.
**Origin:** GPT-5.5 cross-model review cycle 2 of [`feat_config_repo_baseline_tracking/feature_spec.md`](../../../00_overview/implemented_features/2026_05_23_feat_config_repo_baseline_tracking/feature_spec.md) flagged that FR-3a's reconciler-path pointer update could not fire for proposals closed by the webhook's `merged_at=null` fallback. Investigation confirmed a pre-existing reconciler bug independent of that feature. **The limitation is already documented in [`docs/03_runbooks/webhook-debugging.md` §8 "Known limitation — fallback-closed proposals are not recovered"](../../../03_runbooks/webhook-debugging.md) (lines 208–217) and ear-marked by an inline comment block at [`backend/workers/pr_reconcile.py:183-189`](../../../../backend/workers/pr_reconcile.py#L183-L189) referencing this idea by name** — the operator-visible trail exists; only the recovery code is missing.
**Depends on:** none. Standalone fix.

## Problem

The GitHub webhook receiver at [`backend/app/api/webhooks/github.py:181-209`](../../../../backend/app/api/webhooks/github.py#L181-L209) handles the eventual-consistency case where GitHub delivers `pull_request.closed` with `merged=true` but `merged_at=null`:

```python
if decision.mutation == "merged":
    if decision.pr_merged_at is None:
        # GPT-5.5 final-review F3 — GitHub eventual-consistency
        await repo.mark_proposal_pr_closed(db, proposal_id)
    else:
        await repo.mark_proposal_pr_merged(db, proposal_id, pr_merged_at=...)
```

The fallback calls `mark_proposal_pr_closed` at [`backend/app/db/repo/proposal.py:383-409`](../../../../backend/app/db/repo/proposal.py#L383-L409), which transitions the proposal to `(status='pr_opened', pr_state='closed')`:

```python
.where(
    Proposal.id == proposal_id,
    Proposal.status == "pr_opened",
    Proposal.pr_state == "open",
)
.values(pr_state="closed")
```

The polling reconciler at [`backend/workers/pr_reconcile.py:171-175`](../../../../backend/workers/pr_reconcile.py#L171-L175) is supposed to catch up later when GitHub starts returning `merged_at`:

```python
if merged and merged_at is not None:
    async with factory() as db:
        updated = await repo.mark_proposal_pr_merged(
            db, proposal.id, pr_merged_at=merged_at
        )
        await db.commit()
```

**Two compounding guards block recovery — both must move for any fix to land:**

1. **Candidate query filter (the primary blocker).** The reconciler's candidate set comes from [`list_pr_opened_proposals_for_reconcile`](../../../../backend/app/db/repo/proposal.py#L455-L475) (`proposal.py:455-475`), whose WHERE clause requires `pr_state='open'`. Fallback-closed proposals (`pr_state='closed'`) are never returned, so the reconciler **never sees them at all** — the code path quoted above isn't even reached.

2. **`mark_proposal_pr_merged` WHERE clause.** Even if a fallback-closed proposal were forced into the candidate set, [`mark_proposal_pr_merged` at `proposal.py:347-380`](../../../../backend/app/db/repo/proposal.py#L347-L380) is also conditional on `pr_state='open'`:

```python
.where(
    Proposal.id == proposal_id,
    Proposal.status == "pr_opened",
    Proposal.pr_state == "open",
)
```

So even the recovery sequence the prior version of this idea proposed (call `mark_proposal_pr_reopened` then re-run `mark_proposal_pr_merged`) would never be reached today — the reconciler short-circuits one level upstream. **The proposal is stuck in `(pr_opened, closed)` forever until an operator manually intervenes** via the `force-reconcile` runbook step ([§5](../../../03_runbooks/webhook-debugging.md)) or direct SQL.

This is rare in practice — GitHub usually delivers `merged_at` on `pull_request.closed merged=true` — but it's a real failure mode the existing code does not recover from.

## Why this matters

1. **Operator confusion.** A merged PR that's stuck in `pr_opened+closed` looks like an abandoned PR in the UI, not a successfully merged one. The operator sees "closed without merge" when the truth is "merged but RelyLoop got confused."
2. **Pointer-tracking miss.** Per `feat_config_repo_baseline_tracking` FR-3a, the reconciler is supposed to update `config_repos.last_merged_proposal_id` when it catches up on a missed merge. The current bug means that update never fires for proposals that hit the eventual-consistency fallback.
3. **Audit gap (MVP2+).** When `audit_log` lands, the audit event for the merge won't be emitted from the reconciler path either — same root cause.

## Proposed fix (sketch — to be specified properly via `/pipeline`)

Because the candidate query is the upstream blocker, the fix has to address **both layers** — visibility, then transition. Two design forks, both viable; pick during `/spec-gen`.

**Option A — Widen the candidate set, fix in `mark_proposal_pr_merged`:**

1. Loosen `list_pr_opened_proposals_for_reconcile` to also return `(pr_opened, closed)` rows where `pr_merged_at IS NULL` AND `pr_url IS NOT NULL` AND `created_at > now() - 90 days`. (Skip rows already in a `pr_merged` terminal — those are done.)
2. Add a separate recovery branch in `pr_reconcile.py:171` for the `pr_state='closed'` case that calls `mark_proposal_pr_reopened` then `mark_proposal_pr_merged` in the same transaction. Keep the existing branch for the normal `pr_state='open'` case unchanged.
3. Emit a structured `pr_reconcile_recovered_eventual_consistency` INFO log on success so operators can grep for the recovery rate.

**Option B — New repo function with a different WHERE:**

1. Add `mark_proposal_pr_merged_from_closed(db, proposal_id, *, pr_merged_at)` mirroring `mark_proposal_pr_merged` but with `WHERE status='pr_opened' AND pr_state='closed'`. Atomic single-UPDATE transition `(pr_opened, closed) → (pr_merged, merged)`.
2. Widen the candidate query as in Option A (still required — same visibility blocker).
3. Reconciler branches: `pr_state='open'` → existing path; `pr_state='closed'` → new repo function. No round-trip.

**Recommended default:** Option B — single-UPDATE matches the existing state-machine helper style (`mark_proposal_pr_closed`, `mark_proposal_pr_reopened`, `mark_proposal_pr_merged` all use one conditional UPDATE; mixing `reopen` + `merge` calls would be the only two-UPDATE transition in the file).

**Both options must also handle:**

- **Pointer-tracking parity.** The reconciler's existing FR-3a pointer-update branch at [`pr_reconcile.py:177-195`](../../../../backend/workers/pr_reconcile.py#L177-L195) only fires when `mark_proposal_pr_merged` returns a non-None row. The recovery path needs the same `update_config_repo_last_merged_pointer` call so fallback-closed proposals contribute to the `config_repos.last_merged_proposal_id` denormalization. (This is the whole reason `feat_config_repo_baseline_tracking`'s cycle-2 review surfaced the bug.)
- **Idempotency.** Repeated GitHub deliveries on the same `(proposal_id, pr_merged_at)` must remain a no-op once the recovery succeeds — current invariant (zero matched rows on the second UPDATE) carries over to Option B trivially; Option A's two-UPDATE sequence needs explicit zero-rows-on-replay assertions.
- **Stale-comment cleanup.** The acknowledgment comment block at [`backend/workers/pr_reconcile.py:183-189`](../../../../backend/workers/pr_reconcile.py#L183-L189) and the runbook §8 "Known limitation" paragraph both need to flip from "captured as bug X" to "shipped via PR #N" at finalization. Both are operator-visible.

Scope sketch (rough):

- Backend: ~120 LOC (Option B: one new repo function + widened candidate query + reconciler branch + log event + idempotency assertions).
- Integration test: replay the eventual-consistency sequence end-to-end. New file or extension of [`backend/tests/integration/test_polling_reconciler.py`](../../../../backend/tests/integration/test_polling_reconciler.py).
- Pointer-tracking test: extend [`backend/tests/integration/test_pr_reconcile_config_repo_pointer.py`](../../../../backend/tests/integration/test_pr_reconcile_config_repo_pointer.py) for the recovery path.
- Contract: unchanged.
- Frontend: unchanged.

## Why deferred (this is captured as a separate bug, not folded into `feat_config_repo_baseline_tracking`)

- **Different subsystem.** This is a `pr_reconcile.py` state-machine bug; the baseline-tracking feature is a `config_repos` denormalization feature. Mixing them would blow up the review surface of the baseline-tracking PR.
- **Pre-existing.** The bug existed before baseline-tracking was specced; the baseline-tracking feature merely surfaces the gap by relying on the reconciler's success path.
- **Acceptable degradation in the baseline-tracking feature.** Per its §"Known pre-existing limitation," the pointer simply isn't maintained for proposals that hit this fallback — pointer correctness for the vast majority of real-world merges is preserved.
- **Real product-design surface.** Should the reconciler implicitly reopen-then-merge a closed PR? Or should the recovery be visible in the structured log so the operator notices that GitHub had a bad day? Probably the latter, but the design decision wants spec-shaped scrutiny.

Capture as `/pipeline` candidate when the operator wants the eventual-consistency path bulletproofed — likely paired with `feat_github_webhook` hardening work post-MVP1.

## Open questions for /spec-gen

1. **Option A vs Option B for the recovery transition.** Recommended default: **Option B** (new repo function `mark_proposal_pr_merged_from_closed`). Rationale above — single-UPDATE matches the existing helper style. Lock during /spec-gen.
2. **Candidate-query expansion scope.** Should the widened `list_pr_opened_proposals_for_reconcile` also surface `(pr_opened, closed)` proposals whose `pr_url IS NULL` (no PR ever opened — true `closed` state)? Recommended default: **no** — `pr_url IS NOT NULL` stays as a filter so the reconciler isn't polling GitHub for proposals that don't have a PR yet.
3. **90-day window — does it apply to fallback-closed proposals too?** Recommended default: **yes, identical 90-day window**. A proposal stuck in `(pr_opened, closed)` for >90 days has aged out for the same reason normal `(pr_opened, open)` ones do — operator triage required.
4. **Should the fix backfill historical fallback-closed proposals?** Today's bug leaves an unknown number of historical proposals stuck. Recommended default: **no backfill migration** — the reconciler picks them up on its next run within the 90-day window automatically once the candidate query widens. Anything older than 90 days requires operator triage anyway. A backfill SQL recipe could go in the runbook.
5. **Confidence that the bug is real, not theoretical.** No bug report yet; surfaced via cross-model review. Recommended for /spec-gen: a quick log-grep recipe in the spec's "Verification" section (`grep mark_proposal_pr_closed` in production logs over the past 30 days) so the operator can measure incidence before sizing the fix.
