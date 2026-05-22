# Review a proposal

> 2-minute walkthrough — the human-judgment gate before anything reaches production.

A "proposal" is RelyLoop's handoff from offline optimization to Git-deployed
config. It says: *"these parameter values beat the baseline by X% — should
this become a Pull Request against the config repo?"* Every completed study
emits a proposal; engineers can also hand-craft proposals via the API.

## Steps

1. **Open the Proposals page.** Click "Proposals" in the top nav.

2. **Filter the queue.** Three filter axes:
   - **Status** — pending / pr_opened / merged / rejected
   - **Source** — study_triggered / chat_triggered / all
   - **Cluster** — narrow to one cluster

3. **Click a proposal row** to open its detail page. The page surfaces:
   - **Header** — status badge, source, cluster, template
   - **Config diff** — every parameter key being changed, with FROM and TO
     values
   - **Metric delta** — baseline ndcg@10 (or whatever metric the study used)
     vs. achieved, with percent improvement
   - **Suggested followups** — recommended next studies (from the digest)

4. **Decide.** Two paths:
   - **Open PR** — enqueues the `open_pr` worker, which creates a feature
     branch in the config repo, commits the new `*.params.json`, opens a
     GitHub PR, and posts the parameter-importance chart as a PR comment.
   - **Reject** — closes the proposal without opening a PR. Provide a brief
     reason so future you (or your teammate) can see why.

## What happens after Open PR

The proposal status transitions `pending → pr_opened`. RelyLoop tracks the
PR state via:
- **Webhook** (primary) — GitHub posts `pull_request.{closed,merged}` to
  `/webhooks/github`; RelyLoop atomically updates the proposal.
- **Reconciliation cron** (fallback) — every ~5 minutes, polls open PRs
  via the GitHub REST API and reconciles state.

When the approver merges the PR on GitHub, the proposal lands at
`status=merged`. RelyLoop never sits on the live search-serving path —
your CI/CD reads the merged config and deploys it.

## Reference

- API list: `GET /api/v1/proposals?status=&source=&cluster_id=`
- API open PR: `POST /api/v1/proposals/{id}/open_pr` (returns 202; worker
  handles the GitHub side)
- API reject: `POST /api/v1/proposals/{id}/reject` with `{reason}`
- Runbook: [`docs/03_runbooks/pr-open-debugging.md`](../03_runbooks/pr-open-debugging.md)

> See the [glossary](/guide/glossary) for definitions of every term used in this walkthrough.
