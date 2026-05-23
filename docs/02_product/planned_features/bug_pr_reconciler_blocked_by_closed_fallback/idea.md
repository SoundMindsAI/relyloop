# PR reconciler can't recover a proposal closed by the webhook's `merged_at=null` fallback

**Date:** 2026-05-22
**Status:** Idea — surfaced during the 2026-05-22 GPT-5.5 cycle-2 cross-model review of `feat_config_repo_baseline_tracking`. Pre-existing bug in the shipped reconciler path, not introduced by that feature.
**Priority:** P2 — rare-but-real failure mode; affects only the GitHub eventual-consistency window where `merged=true` is sent with `merged_at=null`. The proposal lands in a permanent `pr_opened+closed` state until an operator manually intervenes.
**Origin:** GPT-5.5 cross-model review cycle 2 of [`feat_config_repo_baseline_tracking/feature_spec.md`](../feat_config_repo_baseline_tracking/feature_spec.md) flagged that FR-3a's reconciler-path pointer update could not fire for proposals closed by the webhook's `merged_at=null` fallback. Investigation confirmed a pre-existing reconciler bug independent of that feature.
**Depends on:** none. Standalone fix.

## Problem

The GitHub webhook receiver at [`backend/app/api/webhooks/github.py:181-194`](../../../../backend/app/api/webhooks/github.py) handles the eventual-consistency case where GitHub delivers `pull_request.closed` with `merged=true` but `merged_at=null`:

```python
if decision.mutation == "merged":
    if decision.pr_merged_at is None:
        # GPT-5.5 final-review F3 — GitHub eventual-consistency
        await repo.mark_proposal_pr_closed(db, proposal_id)
    else:
        await repo.mark_proposal_pr_merged(db, proposal_id, pr_merged_at=...)
```

The fallback calls `mark_proposal_pr_closed`, which transitions the proposal to `(status='pr_opened', pr_state='closed')` per the conditional UPDATE at [`backend/app/db/repo/proposal.py:358-384`](../../../../backend/app/db/repo/proposal.py):

```python
.where(
    Proposal.status == "pr_opened",
    Proposal.pr_state == "open",
)
.values(pr_state="closed")
```

The polling reconciler at [`backend/workers/pr_reconcile.py:170-180`](../../../../backend/workers/pr_reconcile.py) is supposed to catch up later when GitHub starts returning `merged_at`:

```python
if merged and merged_at is not None:
    async with factory() as db:
        updated = await repo.mark_proposal_pr_merged(
            db, proposal.id, pr_merged_at=merged_at
        )
        await db.commit()
```

But `mark_proposal_pr_merged` at [`backend/app/db/repo/proposal.py:322-355`](../../../../backend/app/db/repo/proposal.py) is conditional on `pr_state='open'`:

```python
.where(
    Proposal.id == proposal_id,
    Proposal.status == "pr_opened",
    Proposal.pr_state == "open",
)
```

So after the fallback closes the proposal (`pr_state='closed'`), the reconciler's `mark_proposal_pr_merged` matches zero rows and returns `None`. The proposal is **stuck in `(pr_opened, closed)` forever** until an operator manually rejects it or fires `mark_proposal_pr_reopened` then re-runs the reconciler.

This is rare in practice — GitHub usually delivers `merged_at` on `pull_request.closed merged=true` — but it's a real failure mode the existing code does not recover from.

## Why this matters

1. **Operator confusion.** A merged PR that's stuck in `pr_opened+closed` looks like an abandoned PR in the UI, not a successfully merged one. The operator sees "closed without merge" when the truth is "merged but RelyLoop got confused."
2. **Pointer-tracking miss.** Per `feat_config_repo_baseline_tracking` FR-3a, the reconciler is supposed to update `config_repos.last_merged_proposal_id` when it catches up on a missed merge. The current bug means that update never fires for proposals that hit the eventual-consistency fallback.
3. **Audit gap (MVP2+).** When `audit_log` lands, the audit event for the merge won't be emitted from the reconciler path either — same root cause.

## Proposed fix (sketch — to be specified properly via `/pipeline`)

The reconciler at `pr_reconcile.py:170-176` should attempt a recovery sequence when `mark_proposal_pr_merged` returns `None` and the proposal is in `(pr_opened, closed)`:

1. Call `mark_proposal_pr_reopened(db, proposal.id)` to move `pr_state: closed → open`.
2. Re-run `mark_proposal_pr_merged(db, proposal.id, pr_merged_at=merged_at)`.
3. Both succeed → emit a new structured log event `pr_reconcile_recovered_eventual_consistency` so the operator can see the recovery happened.

Alternative: add a new repo function `mark_proposal_pr_merged_from_closed` that explicitly handles the `(pr_opened, closed) → (pr_merged, merged)` transition, mirroring the existing `mark_proposal_pr_merged` but with a different WHERE clause. Cleaner state-machine semantics; fewer round-trips.

Scope sketch (rough):
- Backend: ~80 LOC (one new repo function OR a two-step recovery sequence + tests).
- Integration test: replay the eventual-consistency sequence end-to-end.
- Contract: unchanged.
- Frontend: unchanged.

## Why deferred (this is captured as a separate bug, not folded into `feat_config_repo_baseline_tracking`)

- **Different subsystem.** This is a `pr_reconcile.py` state-machine bug; the baseline-tracking feature is a `config_repos` denormalization feature. Mixing them would blow up the review surface of the baseline-tracking PR.
- **Pre-existing.** The bug existed before baseline-tracking was specced; the baseline-tracking feature merely surfaces the gap by relying on the reconciler's success path.
- **Acceptable degradation in the baseline-tracking feature.** Per its §"Known pre-existing limitation," the pointer simply isn't maintained for proposals that hit this fallback — pointer correctness for the vast majority of real-world merges is preserved.
- **Real product-design surface.** Should the reconciler implicitly reopen-then-merge a closed PR? Or should the recovery be visible in the structured log so the operator notices that GitHub had a bad day? Probably the latter, but the design decision wants spec-shaped scrutiny.

Capture as `/pipeline` candidate when the operator wants the eventual-consistency path bulletproofed — likely paired with `feat_github_webhook` hardening work post-MVP1.
