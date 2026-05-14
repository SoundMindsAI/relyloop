# Browse proposals

> 2-minute walkthrough — manage the review queue.

A team running many studies needs a workflow surface where every winning
config is queued for review. The `/proposals` page is that surface — a
filterable list with URL-backed filter state and webhook-driven PR-status
updates.

## Three filter axes

| Filter | URL param | Values |
|---|---|---|
| Status | `?status=` | `all` (no param) / `pending` / `pr_opened` / `pr_merged` / `rejected` |
| Source | state-only | `all` / `study_triggered` / `chat_triggered` / `manual` |
| Cluster | state-only | dropdown of registered clusters |

Status is URL-backed (back/forward buttons work, shareable links).
Source and cluster live in component state — they're more like personal
preferences than navigation moments.

## Auto-refetch when PRs are open

The list polls `GET /api/v1/proposals` every 30 seconds if any visible row
has `status=pr_opened` and `pr_state=open`. This catches webhook-driven
state transitions (PR merged on GitHub) without manual reload.

When all visible rows are terminal, polling stops to save bandwidth.

## What's next

Click any row to drill into the proposal detail page. From there, you can:

- Review the config diff side-by-side
- Read the metric delta + suggested followups
- Click **Open PR** to enqueue the GitHub PR worker
- Click **Reject** with a reason

See [Guide 02 (Review a proposal)](#) for the detail-page walkthrough.

## Reference

- API list: `GET /api/v1/proposals?status=&source=&cluster_id=&cursor=&limit=`
- API detail: `GET /api/v1/proposals/{id}`
- 30-second pulse: implemented via TanStack Query's `refetchInterval` —
  see [`ui/src/lib/api/proposals.ts`](../../ui/src/lib/api/proposals.ts)
