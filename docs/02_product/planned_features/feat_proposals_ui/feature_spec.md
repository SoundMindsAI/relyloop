# Feature Specification — feat_proposals_ui

**Date:** 2026-05-09
**Status:** Draft
**Owners:** TBD
**Related docs:**
- [docs/02_product/mvp1-user-stories.md](../../mvp1-user-stories.md) — covers US-28, US-29
- [docs/01_architecture/ui-architecture.md](../../../01_architecture/ui-architecture.md) — Next.js + shadcn + TanStack Query patterns
- [docs/01_architecture/api-conventions.md](../../../01_architecture/api-conventions.md) — API contracts the UI consumes
- Depends on: [`feat_studies_ui`](../feat_studies_ui/feature_spec.md), [`feat_digest_proposal`](../feat_digest_proposal/feature_spec.md), [`feat_github_pr_worker`](../feat_github_pr_worker/feature_spec.md), [`feat_github_webhook`](../feat_github_webhook/feature_spec.md)

---

## 1) Purpose

- **Problem:** Engineers need a place to review proposals (auto-created from study digests OR hand-crafted via chat) before sending them out as PRs, plus visibility into PR state after the fact (open/merged/closed). Without this UI, proposals are invisible blobs in Postgres.
- **Outcome:** Two routes — `/proposals` (filterable list) and `/proposals/{id}` (config diff + metric delta + "Open PR" button + post-open PR-state mirror) — plug into the existing `feat_studies_ui` Next.js app. The "Open PR" button is the single click that turns a proposal into a real GitHub PR.
- **Non-goal:** No proposal creation form (chat agent + digest auto-creation are the two creation paths). No PR state changes from the UI (state changes come from GitHub via webhook + polling). No bulk operations (one proposal at a time in MVP1; bulk reject deferred to MVP2).

## 2) Current state audit

After dependencies ship:
- The Next.js shell + nav (per `feat_studies_ui`) include a `/proposals` link.
- Backend APIs `GET /api/v1/proposals`, `GET /api/v1/proposals/{id}`, `POST /api/v1/proposals/{id}/reject`, `POST /api/v1/proposals/{id}/open_pr` exist.
- TanStack Query hook patterns + `<StatusBadge>` + `<MetricDelta>` exist in `feat_studies_ui`'s shared components.
- No proposals UI yet — this feature creates two routes.

## 3) Scope

### In scope

- **`/proposals` route** (list):
  - Cursor-paginated table: study link (or "manual" if no study_id) / cluster / template / status badge (`pending` / `pr_opened` / `pr_merged` / `rejected`) / pr_state badge (when applicable) / metric_delta (compact "ndcg: +24.5%" with color) / created_at
  - Filter chips: status (all / pending / pr_opened / pr_merged / rejected), cluster (dropdown), proposal-source (study / manual / all)
  - Empty state: "No proposals yet — they appear automatically when studies complete."
- **`/proposals/{id}` route** (detail):
  - Header: status badge, study link (if any), cluster name, template name, created_at, `pr_open_error` if present (red `<Alert>`)
  - Config diff panel: side-by-side `key`, `from`, `to` table; for each row, color-code direction (green up-arrow for increase, etc.)
  - Metric delta panel: per-metric `<MetricDelta>` cards (baseline → achieved + delta_pct)
  - PR panel:
    - When `status='pending'`: "Open PR" button → POST `/api/v1/proposals/{id}/open_pr`; on success, polls every 3s until `status='pr_opened'` then shows the PR link
    - When `status='pr_opened'`: PR link (external), pr_state badge (`open` / `closed` / `merged`); auto-poll proposal every 30s to catch state changes (the webhook is fast; polling is fallback)
    - When `status='pr_merged'`: PR link, pr_merged_at timestamp
    - When `status='rejected'`: rejected_reason text + "Re-pending this proposal" button is NOT supported (per umbrella state machine — terminal state)
  - Reject button (only when `status='pending'`): opens confirm dialog with reason textarea; on confirm POST `/reject`
  - Suggested follow-ups (when associated digest has them): bulleted list with "Create study from this hypothesis" action that links to the create-study modal in `/studies` with the hypothesis pre-filled in the search-space JSON textarea (best-effort; the agent may also offer this via chat)
- **TanStack Query hooks** in `ui/lib/api/proposals.ts`:
  - `useProposals(filter)` (with cursor pagination)
  - `useProposal(id, options)` (refetchInterval optional for polling pr_opened)
  - `useOpenPR()`, `useRejectProposal()` mutations
- **Polling on `/proposals/{id}`** when `proposal.status === 'pr_opened'` AND `proposal.pr_state === 'open'`: refetch every 30s. Stops when `pr_state` becomes `merged` or `closed`.

### Out of scope

- Proposal creation form — created via chat agent (`create_proposal_*` tools) or auto-created from study digests.
- Bulk reject — MVP2.
- PR-state changes from the UI — read-only mirror of GitHub state.
- Slack notification preferences — MVP2.
- "Reject and re-create" flow — MVP2.
- E2E tests — MVP3+ or `chore_tutorial_polish`.

### API convention check

Per [`api-conventions.md`](../../../01_architecture/api-conventions.md). Consumes existing endpoints; no new APIs.

### Phase boundaries

Single-phase. The MVP1 deliverable: "from a completed study's digest, the operator clicks 'Open PR', sees the PR appear in GitHub within 60s, sees the PR-merged state in the UI within 30s of merging on GitHub."

## 4) Product principles and constraints

- **PR state is read-only from the UI.** The UI mirrors what GitHub says (via webhook + polling reconciler). No "force-merge" or "force-close" buttons.
- **One Open PR action per proposal.** Once `status='pr_opened'`, the button is disabled. To retry on `pr_open_error`, the operator goes through chat or via the API directly (recoverable from `pending` state by re-issuing).
- **Polling is bounded.** `pr_opened + open` proposals poll at 30s; terminal states don't poll.
- **No bulk operations.** Each proposal is reviewed and acted on individually. MVP2 may add "Reject all proposals from study X" if needed.

### Anti-patterns

- **Do not** fetch the underlying study via a separate query when the proposal detail loads — `GET /api/v1/proposals/{id}` returns inline `study_summary` and inline `digest` per [`feat_digest_proposal` FR-4](../feat_digest_proposal/feature_spec.md).
- **Do not** display the PR diff inline. Link out to GitHub. Reproducing GitHub's diff renderer is out of scope.
- **Do not** block the UI on the "Open PR" call. POST returns 202 immediately; UI shows a spinner; polls for status flip.

## 5) Assumptions and dependencies

- **Dependency: `feat_studies_ui`** — shell + nav + shared components (`<StatusBadge>`, `<MetricDelta>`, `<CursorPaginator>`).
- **Dependency: `feat_digest_proposal`** — proposals exist; `digests.suggested_followups` populated.
- **Dependency: `feat_github_pr_worker`** — `POST /api/v1/proposals/{id}/open_pr` works; `pr_url`, `pr_state`, `pr_open_error` columns populated.
- **Dependency: `feat_github_webhook`** — `pr_state` updates within 30s of merge (or within 15min via polling reconciler).

## 6) Actors and roles

- **Primary actor:** Relevance Engineer (reviews proposal, decides to open or reject).

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` is MVP2.

## 7) Functional requirements

### FR-1: `/proposals` list
- The page **MUST** show a cursor-paginated table per §3 in-scope.
- Filter chips **MUST** trigger refetch with `?status=...&cluster_id=...`.
- The page **MUST** auto-refetch every 30s if any visible proposal has `status='pr_opened' AND pr_state='open'` (catches webhook-driven updates without manual reload).

### FR-2: `/proposals/{id}` detail
- The page **MUST** render header + config diff + metric delta + PR panel + suggested followups (when present) per §3.
- The page **MUST** poll the proposal at 30s while `status='pr_opened' AND pr_state='open'`.
- The page **MUST** show `pr_open_error` in a red `<Alert>` when present and proposal is `pending`.

### FR-3: Open PR action
- The "Open PR" button **MUST** POST to `/api/v1/proposals/{id}/open_pr`.
- On 202 response, the UI **MUST**: disable the button, show a spinner, poll the proposal at 3s until `status='pr_opened'` OR `pr_open_error` populated, then re-enable and show the result.
- On `OPENAI_NOT_CONFIGURED` / `GITHUB_NOT_CONFIGURED` 503 responses, the UI **MUST** surface the toast with the actionable message (per FR-10 of `feat_studies_ui`).

### FR-4: Reject action
- The "Reject" button (only when `status='pending'`) **MUST** open a confirm dialog with a reason textarea (optional but recommended).
- On confirm, the UI **MUST** POST `/api/v1/proposals/{id}/reject` with the reason; on success, refresh the proposal and the list query.
- On 409 `INVALID_STATE_TRANSITION`, the UI **MUST** show a toast and refresh the proposal (state may have changed since page load).

### FR-5: Suggested follow-ups
- When the proposal has an associated digest with non-empty `suggested_followups`, the page **MUST** render them as a bulleted list under the proposal detail.
- Each follow-up **MUST** have a "Create study from this hypothesis" action that opens the create-study modal in `/studies` with `?hypothesis=<encoded>` query param (the modal's search-space step pre-fills based on the hypothesis text — best-effort; the agent may also offer this via chat).

### FR-6: TanStack Query hooks
- `ui/lib/api/proposals.ts` **MUST** export `useProposals(filter)`, `useProposal(id, opts)`, `useOpenPR()`, `useRejectProposal()`.
- `useProposal(id)` **MUST** accept `refetchInterval?: number` for polling.

## 8) API and data contract baseline

This feature has no backend endpoints; consumes existing APIs.

### 7.4 Enumerated value contracts

| UI surface | Backend source of truth |
|---|---|
| Proposals status filter chips | `backend/db/models/proposal.py` (`ProposalStatus` `Literal[...]`) |
| `pr_state` badge color map | `backend/db/models/proposal.py` (`PRState` `Literal[...]`) |
| Cluster filter dropdown | `backend/db/models/cluster.py` (consumed via `GET /api/v1/clusters`) |

The UI **MUST** add source-of-truth comments per `feat_studies_ui` AC-6.

## 9) Data model and state transitions

This feature has no schema. UI-side state in TanStack Query cache + local React state.

## 10) Security, privacy, and compliance

- **Threats:**
  1. XSS via `rejected_reason` text. **Mitigation:** React default escaping.
  2. CSRF on the open-PR / reject mutations. **Mitigation:** SameSite=Lax cookies in MVP4 when sessions arrive; until then, the API is on localhost only (per `infra_foundation`) and not externally reachable.

## 11) UX flows and edge cases

### Primary flows

1. **Open-PR flow:** Study completes → Studies detail → Digest panel "Open PR" button → routes to `/proposals/{id}` with the action triggered → spinner for 30-60s → PR link appears → operator clicks through to GitHub.
2. **Review-then-decide flow:** `/proposals` list → click a `pending` row → review config diff + metric delta + suggested followups → either click "Open PR" or "Reject" with reason.
3. **Post-open monitoring flow:** `/proposals` list filtered to `pr_opened` → see PR states updating from webhook → click into a `pr_merged` proposal to confirm metric delta in the merge.

### Edge/error flows

- **Open PR fails (`pr_open_error`).** UI shows red `<Alert>` with the error; "Open PR" button re-enabled (re-issue is the recovery path).
- **Webhook delivers merge before user opens the page.** UI loads with `status='pr_merged'` already; no spinner shown; PR link + merged-at timestamp displayed.
- **Webhook fails to deliver, polling reconciler updates.** UI's 30s poll picks up the change within 30s after the reconciler runs (15-min reconciler tick + 30s UI poll = up to 15.5 min lag; acceptable).
- **Open PR while GitHub token missing.** API returns 503 `GITHUB_NOT_CONFIGURED`; UI surfaces toast pointing at the runbook.

## 12) Given/When/Then acceptance criteria

### AC-1: Open PR end-to-end via UI

- Given a `pending` proposal from a completed study with valid GitHub token + config repo registered.
- When the operator opens `/proposals/{id}` and clicks "Open PR".
- Then within 60s the PR panel shows: PR link (clickable), `pr_state='open'` badge, `pr_url` populated. The proposal `status` is now `pr_opened`. The button is disabled.

### AC-2: Reject flow

- Given a `pending` proposal.
- When the operator clicks Reject, types "metric delta too small to justify churn", confirms.
- Then the proposal updates to `status='rejected'` with `rejected_reason` populated; the UI refreshes both list and detail. Re-clicking Reject is impossible (button gone).

### AC-3: Webhook-driven merge updates UI

- Given a proposal `pr_opened` with the page open.
- When the PR is merged on GitHub (webhook delivered within seconds).
- Then within 30s the UI's polling refetch shows `status='pr_merged'`, `pr_merged_at` timestamp; PR link still present.

### AC-4: pr_open_error surfaces

- Given a proposal where `feat_github_pr_worker` populated `pr_open_error = "Branch already exists"`.
- When the operator opens `/proposals/{id}`.
- Then a red `<Alert>` shows the error message; "Open PR" button is enabled (re-issue path).

### AC-5: Suggested follow-ups link to create-study

- Given a proposal whose digest has 3 `suggested_followups`.
- When the operator opens `/proposals/{id}`.
- Then 3 bulleted items appear under "Suggested follow-ups"; clicking the action button on one navigates to `/studies?hypothesis=<encoded>` and opens the create-study modal.

### AC-6: Filter and pagination

- Given 75 proposals across various statuses.
- When the operator opens `/proposals?status=pr_opened`.
- Then only `pr_opened` proposals are listed; cursor pagination works; selecting "all" status chip refetches without filter.

### AC-7: Source-of-truth comments verified

- Per `feat_studies_ui` AC-6 — the CI gate verifies `// Values must match backend/db/models/proposal.py ProposalStatus` is present above any proposal-status-related option array.

## 13) Non-functional requirements

- **Performance:** Detail page renders in <1.5s on first load. 30s polling is negligible CPU.
- **Reliability:** Webhook-missed merges show within ~15 min (polling reconciler) + 30s (UI poll).
- **Operability:** Same `X-Request-ID` injection as `feat_studies_ui` — no extra plumbing.

## 14) Test strategy requirements

- **Unit tests** (`ui/tests/unit/`):
  - `app/proposals/page.spec.tsx` — filter chips trigger refetch
  - `app/proposals/[id]/page.spec.tsx` — pending vs pr_opened vs pr_merged vs rejected render correctly
  - `app/proposals/[id]/open-pr-button.spec.tsx` — disabled-spinner-resolved state machine
  - `lib/api/proposals.spec.ts` — TanStack Query hook contracts
- **E2E tests:** N/A.

## 15) Documentation update requirements

- `docs/01_architecture/ui-architecture.md` already documents the patterns; update if proposal-specific patterns diverge.
- `docs/02_product/mvp1-user-stories.md`: mark US-28 / US-29 as "implemented".

## 16) Rollout and migration readiness

- **Feature flags:** None.
- **Migration/backfill:** N/A.
- **Operational readiness gates:** AC-1 succeeds against a real test repo end-to-end.

## 17) Traceability matrix

| FR ID | AC IDs | Stories (TBD) | Test files | Docs |
|---|---|---|---|---|
| FR-1 (list) | AC-6 | TBD | `ui/tests/unit/app/proposals/page.spec.tsx` | — |
| FR-2 (detail) | AC-3, AC-4 | TBD | `ui/tests/unit/app/proposals/[id]/page.spec.tsx` | — |
| FR-3 (open PR) | AC-1, AC-4 | TBD | `ui/tests/unit/app/proposals/[id]/open-pr-button.spec.tsx` | — |
| FR-4 (reject) | AC-2 | TBD | `ui/tests/unit/app/proposals/[id]/reject-dialog.spec.tsx` | — |
| FR-5 (followups) | AC-5 | TBD | `ui/tests/unit/app/proposals/[id]/followups.spec.tsx` | — |
| FR-6 (hooks) | All | TBD | `ui/tests/unit/lib/api/proposals.spec.ts` | — |

## 18) Definition of feature done

- [ ] AC-1 through AC-7 pass.
- [ ] Tutorial flow includes a successful Open PR via this UI.
- [ ] No open questions remain in §19.

## 19) Open questions and decision log

### Open questions

None — all resolved (see Decision log).

### Decision log

- 2026-05-09 — PR state is read-only from the UI (mirrors GitHub via webhook + polling) — per [`apply-path.md`](../../../01_architecture/apply-path.md).
- 2026-05-09 — One Open PR action per proposal; retry-on-error is via re-issuing through the API or chat, not a "Retry" button — keeps the state machine simple.
- 2026-05-09 — No bulk operations in MVP1 — defer to MVP2 if real demand emerges.
- 2026-05-09 — `GET /api/v1/proposals/{id}` returns inline `study_summary` and inline `digest` — locked in `feat_digest_proposal` FR-4 with full response shape. UI does NOT fan out additional queries.
- 2026-05-09 — Hypothesis pre-fill on follow-up "Create study": **best-effort string interpolation into the search-space JSON textarea in MVP1**. Structured parsing via `propose_search_space` arrives at MVP2 (per `feat_chat_agent` decision-log).
