# Feature Specification — Config Repo Baseline Tracking

**Date:** 2026-05-22
**Status:** Draft
**Owners:** RelyLoop maintainers (soundminds.ai)
**Related docs:**
- [idea.md](idea.md)
- [`feat_auto_followup_studies/idea.md`](../feat_auto_followup_studies/idea.md) — downstream consumer
- [`feat_pr_metric_confidence/feature_spec.md`](../../../00_overview/implemented_features/2026_05_21_feat_pr_metric_confidence/feature_spec.md) §2 — surfaces the `studies.baseline_metric=NULL` finding this feature unblocks

---

## 1) Purpose

- **Problem:** RelyLoop has no first-class record of "which proposal is currently live in production." Every merged-PR webhook updates the proposal row (`status='pr_merged'`, `pr_state='merged'`, `pr_merged_at=<ts>`) but never propagates that signal to the parent `config_repos` row. Answering the question "what's the most recently merged proposal for this config repo?" requires scanning all proposals, filtering by `pr_state='merged'`, sorting by `pr_merged_at DESC`, and taking the first row — a query that exists nowhere in the codebase today.
- **Outcome:** A single denormalized FK `config_repos.last_merged_proposal_id` points at the most recently merged proposal for each config repo. The merge-event webhook handler AND the PR-state reconciler maintain the pointer with strict-monotonic-timestamp idempotency. The proposals list API exposes a per-row `is_currently_live: bool` and a `?is_last_merged=true` filter. The proposals list rows and proposal detail page render a "Currently live" badge for proposals that ARE the live pointer for their config repo. (The cluster detail page is intentionally out of scope — see §3 Out of scope.)
- **Non-goal:** Verifying that the merged config has *actually* deployed to the operator's running cluster (deploy is operator-owned per the umbrella spec §6 hard constraint — RelyLoop never sits on the live serving path). The pointer is internal bookkeeping, not enforcement.

## 2) Current state audit

### Existing implementations

| File | What it does | API | Notes |
|---|---|---|---|
| [`backend/app/db/models/config_repo.py`](../../../../backend/app/db/models/config_repo.py) | `ConfigRepo` ORM model | — | 10 columns; **no `last_merged_*` field** today. |
| [`backend/app/db/models/proposal.py`](../../../../backend/app/db/models/proposal.py) | `Proposal` ORM model | — | `cluster_id` NOT NULL; `study_id` NULLABLE (hand-crafted from `feat_chat_agent`); `pr_merged_at` populated on merge. |
| [`backend/app/db/models/cluster.py`](../../../../backend/app/db/models/cluster.py) | `Cluster` ORM model | — | `config_repo_id` NULLABLE FK to `config_repos.id` (a cluster may exist before a Git repo is wired in). |
| [`backend/app/api/webhooks/github.py`](../../../../backend/app/api/webhooks/github.py) | Webhook receiver | `POST /webhooks/github` | Lines 181–194 handle the `merged` decision: `mark_proposal_pr_merged` on success, `mark_proposal_pr_closed` for the GitHub eventual-consistency fallback. **Neither stamps anything on `config_repos`.** |
| [`backend/app/db/repo/proposal.py:322-355`](../../../../backend/app/db/repo/proposal.py) | `mark_proposal_pr_merged()` | — | **Conditional UPDATE** gated on `WHERE status='pr_opened' AND pr_state='open'`. Returns `None` for out-of-order/duplicate deliveries (already-merged proposals match zero rows). This is the natural idempotency primitive this feature builds on. |
| [`backend/app/db/repo/config_repo.py`](../../../../backend/app/db/repo/config_repo.py) | `ConfigRepo` repo layer | — | 6 functions; no helper writes to a non-existent `last_merged_*` column today. |
| [`backend/app/api/v1/config_repos.py`](../../../../backend/app/api/v1/config_repos.py) | Config-repo CRUD router | `POST/GET /api/v1/config-repos[/{id}]` | `_to_detail()` serializer at lines 93–106 maps the ORM row → `ConfigRepoDetail`. |
| [`backend/app/api/v1/proposals.py`](../../../../backend/app/api/v1/proposals.py) | Proposals CRUD router | `GET /api/v1/proposals[/{id}]` etc. | `_assemble_proposal_summary_batch()` at lines 191–234 batches cluster + template fetches per row. |
| [`backend/app/api/v1/schemas.py`](../../../../backend/app/api/v1/schemas.py) | Pydantic wire models | — | `ConfigRepoDetail` at line 1081; `ProposalSummary` at line 986. |
| [`ui/src/app/proposals/page.tsx`](../../../../ui/src/app/proposals/page.tsx) | Proposals list page | — | Uses `<ProposalsTable>` shadcn primitive + URL-state hook. |
| [`ui/src/app/clusters/[id]/page.tsx`](../../../../ui/src/app/clusters/%5Bid%5D/page.tsx) | Cluster detail page | — | Renders `<ClusterDetailSummary>` + `<ClusterActionBar>` + `<StudiesByClusterTable>`. **Does NOT currently surface the linked `config_repo_id` at all** — contrary to the idea's parenthetical hedge in §"Read surface". |
| [`ui/src/lib/api/config-repos.ts`](../../../../ui/src/lib/api/config-repos.ts) | TanStack hooks for config-repos | — | `useConfigRepos` list, `useCreateConfigRepo` mutation; no `useConfigRepo(id)` detail hook today. |

**Audit-of-the-audit (resolves an open question raised by the idea):** the idea hedges "today the cluster detail page surfaces the linked config repo." That hedge was wrong — the cluster detail page makes no mention of `config_repo_id` (grep returns zero matches). The UI surface decision moves below (§11) to land the "Currently live" badge on the **proposals list rows + proposal detail page**, where the data already exists and a single field on `ProposalSummary` produces the badge with no new fetch.

### Navigation and link impact

| Source file | Current link target | New link target |
|---|---|---|
| `ui/src/app/proposals/page.tsx` | row → `/proposals/[id]` | unchanged; row gains a "Currently live" badge column inline |
| `ui/src/app/clusters/[id]/page.tsx` | n/a | unchanged; **out of scope** — adding a config-repo summary section is deferred to a follow-up |

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/contract/test_github_pr_worker_api_contract.py` | asserts `ConfigRepoDetail` + config-repos endpoint shape | exists — already references `ConfigRepoDetail` at lines 124, 148 | Extend with `last_merged_proposal` field; default `None` for repos with no tracked pointer. |
| `backend/tests/contract/test_digest_proposal_api_contract.py` | asserts proposals + digest endpoint shapes (`ProposalDetail` at line 120) | exists | Extend with `is_currently_live: bool` assertion on `ProposalSummary` + `ProposalDetail`. |
| `backend/tests/integration/test_proposals_study_filter.py` | exercises list-side filters | exists | Add 3 cases for `?is_last_merged=true` (positive, negative, NULL pointer). |
| `backend/tests/integration/test_webhook_*.py` | webhook receiver coverage | grep `mark_proposal_pr_merged` invocations | Add 4 cases: pointer updates on first merge; out-of-order merge does not regress pointer; `cluster.config_repo_id IS NULL` does not crash; concurrent merges serialize via row lock. |
| `ui/src/__tests__/proposals/*` | proposals table component tests | inspected | Add 2 cases for the "Currently live" badge rendering. |
| `ui/tests/e2e/proposals.spec.ts` (or sibling) | Playwright E2E | inspected | 1 new real-backend case: seed proposal → fire merge webhook → assert badge appears in list. |

### Existing behaviors affected by scope change

- **Proposals list response shape:** Current `ProposalSummary` has 9 fields. New: adds `is_currently_live: bool`. Additive — frontend can ignore the field until the badge ships. Decision needed: **No** (purely additive; matches MVP1 wire-evolution precedent).
- **ConfigRepoDetail response shape:** Adds `last_merged_proposal: ProposalSummary | None`. Additive. Decision needed: **No**.
- **Merge-webhook side effects:** Today a merge webhook updates exactly one row (`proposals`). After this feature, it updates two rows (`proposals` + `config_repos`) in the same transaction. The added latency on the webhook receiver is a single UPDATE; well under the existing 200ms p99 target for `/webhooks/github`. Decision needed: **No**.

---

## 3) Scope

### In scope

- New nullable column `config_repos.last_merged_proposal_id String(36) NULL REFERENCES proposals(id) ON DELETE SET NULL` (Alembic migration `0016`).
- Backfill of existing data inside the migration's `upgrade()`: single SQL UPDATE picks the most-recently-merged proposal per config_repo via the `proposals → clusters → config_repos` join. Idempotent and self-contained.
- Index `config_repos_last_merged_proposal_id_idx` (B-tree, partial `WHERE last_merged_proposal_id IS NOT NULL`) for the reverse-lookup path.
- New repo function `update_config_repo_last_merged_pointer(db, config_repo_id, proposal_id, pr_merged_at)` that does a row-locked `SELECT … FOR UPDATE` on `config_repos.id` then conditionally updates the pointer with strict-monotonic-timestamp idempotency.
- Webhook handler patch at `backend/app/api/webhooks/github.py:181-194`: after `mark_proposal_pr_merged` returns a non-None row, resolve the proposal's `config_repo_id` via the `proposals → clusters → config_repos` chain. If non-NULL, call the new repo function in the same transaction. Skip silently when `cluster.config_repo_id IS NULL`.
- `ConfigRepoDetail` response model gains `last_merged_proposal: ProposalSummary | None` (loaded via a single JOIN in the existing `GET /api/v1/config-repos/{id}` endpoint).
- `ProposalSummary` (and `ProposalDetail`) gain `is_currently_live: bool` derived in the existing list/detail serializers via the same `proposals → clusters → config_repos` JOIN.
- `GET /api/v1/proposals` gains `?is_last_merged=true|false` query param. `true` filters to proposals that match `config_repos.last_merged_proposal_id` for their cluster's repo; `false` returns the complement; omitted = unfiltered.
- UI: a new `<CurrentlyLiveBadge>` component renders inside `<ProposalsTable>` rows when `proposal.is_currently_live === true` and on `/proposals/[id]` near the status badge.
- Tests at every layer (unit/integration/contract/E2E) — see §14.

### Out of scope

- **Cluster-level baseline tracking.** Argued and rejected per the idea: `config_repos` is the right scope because one repo can serve multiple clusters (dev / staging / prod) and the operator's CI/CD applies the merged config to all of them in step.
- **Live-cluster verification.** Querying the running cluster to confirm the merged config actually deployed is outside RelyLoop's scope per CLAUDE.md (RelyLoop never sits on the serving path).
- **Multi-repo studies.** The schema permits this naturally (each repo gets its own `last_merged_proposal_id`); the UI surface for a multi-repo proposal is out of scope until that user story is real.
- **Cluster-detail-page config-repo summary section.** The cluster detail page does not currently surface its linked config repo at all. Adding that section is a separate follow-up (capture as `chore_cluster_detail_config_repo_summary/idea.md` if/when needed); this feature does NOT add it.
- **Audit-event emission for the pointer write.** MVP1 has no `audit_log` table; audit instrumentation lands at MVP2 per [`docs/01_architecture/data-model.md` §"Reserved for later releases"](../../../01_architecture/data-model.md). When MVP2 lands, the webhook handler's `audit_log` INSERT will fold in this UPDATE alongside the proposal's existing event.

### API convention check

Per [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md):

- **Endpoint prefix:** `/api/v1/<resource>` for business endpoints; unversioned at `/webhooks/<provider>` for webhook deliveries. ✓
- **Router namespace:** existing — [`backend/app/api/webhooks/github.py`](../../../../backend/app/api/webhooks/github.py) (webhook patch), [`backend/app/api/v1/config_repos.py`](../../../../backend/app/api/v1/config_repos.py) (detail response field), [`backend/app/api/v1/proposals.py`](../../../../backend/app/api/v1/proposals.py) (filter + summary field).
- **HTTP methods:** unchanged from existing surface. No new endpoints — this feature only extends responses + the merge-event side effect.
- **Non-auth error envelope:** `{ "detail": { "error_code": "<CODE>", "message": "<human>", "retryable": <bool> } }` — unchanged.
- **Auth error shape:** N/A (MVP1).

### Phase boundaries

Single phase. No deferred Phase 2.

The work is small (~200 LOC backend + ~80 LOC frontend) and the consumer features (`feat_auto_followup_studies`, `feat_study_baseline_trial`) depend on the complete substrate. Splitting would force the downstream features to re-spec around a half-shipped pointer.

## 4) Product principles and constraints

- **Single source of truth for "currently live":** the `config_repos.last_merged_proposal_id` column is *the* answer. All read paths (API field, filter, UI badge) MUST derive from this column — never from `MAX(pr_merged_at)` scans of the proposals table.
- **Strict-monotonic-timestamp idempotency.** Out-of-order webhook delivery (possible per `feat_github_webhook`'s established invariants) MUST NOT regress the pointer. The repo helper's gating SQL is the single enforcement point.
- **Forward-only.** No retention of an old "previously-live" pointer or shadow column. When a new proposal merges and supersedes the prior live one, the prior pointer value is overwritten; the historical record lives in `proposals.pr_merged_at` rows.
- **Single-transaction atomicity.** The pointer UPDATE happens inside the webhook receiver's existing transaction. Either both the proposal state transition AND the pointer write commit, or neither does. No two-phase, no eventual reconciler for the pointer (the eventual-consistency reconciler at [`backend/workers/reconcile_pr_state.py`] is for `proposals.pr_state` only and does not touch `config_repos`).
- **No new error codes.** This feature does not surface any user-actionable failure modes — the silent-skip on `cluster.config_repo_id IS NULL` is the only edge case, and it has no failure semantics.

### Anti-patterns

- **Do not** answer "what's currently live?" by querying `proposals WHERE pr_state='merged' ORDER BY pr_merged_at DESC LIMIT 1` — that bypasses the pointer and produces drift the moment an out-of-order webhook arrives. The column IS the answer.
- **Do not** write to `config_repos.last_merged_proposal_id` from anywhere except the new repo helper. Every call site routes through `update_config_repo_last_merged_pointer` so the row-lock + timestamp guard hold by construction.
- **Do not** update the pointer in the `mark_proposal_pr_closed` fallback branch at `github.py:188`. That branch fires when GitHub's webhook says `merged=true` but `merged_at` is null (eventual-consistency window). The merge isn't confirmed; the polling reconciler will pick it up and the *real* merge event will fire `mark_proposal_pr_merged` later — at which point THIS feature's pointer update runs.
- **Do not** add a Postgres trigger to maintain the pointer. The pointer is the responsibility of the webhook handler — keeping the update in application code makes the idempotency rule auditable, testable, and observable via structured logs.
- **Do not** treat `cluster.config_repo_id IS NULL` as an error. Many clusters exist before a Git repo is wired in; a merge against such a (theoretical) proposal would skip the pointer write silently. Log the skip at DEBUG level only.

## 5) Assumptions and dependencies

- **Dependency:** [`feat_github_webhook`](../../../00_overview/implemented_features/2026_05_12_feat_github_webhook/) — shipped 2026-05-12 as PR #56. Provides the merge-event path this feature extends.
  - Status: **implemented** — verified live at `backend/app/api/webhooks/github.py:181-194`.
- **Dependency:** [`feat_github_pr_worker`](../../../00_overview/implemented_features/2026_05_12_feat_github_pr_worker/) — shipped 2026-05-12 as PR #45. Defines the `ConfigRepo` registry + the proposals table's `pr_url`/`pr_state`/`pr_merged_at` columns this feature reads.
  - Status: **implemented**.
- **Dependency:** [`feat_digest_proposal`](../../../00_overview/implemented_features/2026_05_11_feat_digest_proposal/) — shipped 2026-05-11 as PR #41. Defines the proposals list/detail endpoints this feature extends.
  - Status: **implemented**.
- **Dependency (test-only):** [`chore_e2e_test_rows_isolation`](../../../00_overview/implemented_features/2026_05_21_chore_e2e_test_rows_isolation/) — shipped 2026-05-21 as PR #186. Provides `DELETE /api/v1/_test/proposals/{id}` used by AC-15 to exercise the FK's ON DELETE SET NULL behavior. Endpoint is gated by `Settings.environment == "development"` so it is callable in CI's dev-env test runs but returns 404 in any non-dev environment.
  - Status: **implemented**.
- **Existing code path also updated:** [`backend/workers/pr_reconcile.py:170-180`](../../../../backend/workers/pr_reconcile.py) — the GitHub eventual-consistency reconciler that polls `GET /repos/{owner}/{repo}/pulls/{n}` and catches up on merges the webhook receiver missed (e.g., GitHub initially delivered `merged_at=null`). This path ALSO calls `mark_proposal_pr_merged` and commits — so this feature MUST patch it identically to the webhook path; see FR-3a.
- **Assumption:** `mark_proposal_pr_merged` returns `None` for out-of-order/duplicate webhook deliveries (verified at `proposal.py:322-355` — `WHERE status='pr_opened' AND pr_state='open'`). This is the natural deduplication gate; the pointer update runs ONLY when the function returns a non-None row.
- **Risk if missing:** the only failure mode is a webhook handler crash between the proposal UPDATE staging and the `await db.commit()`. FastAPI + SQLAlchemy's existing transaction semantics handle this — both writes share one transaction:
  - **Before-commit crash** (DB disconnect, ASGI worker SIGKILL, etc.): the transaction rolls back; neither the proposal UPDATE nor the pointer UPDATE persists. GitHub retries the delivery; `mark_proposal_pr_merged` succeeds on retry (the proposal is still `pr_opened+open`), the pointer UPDATE re-runs against the unchanged `config_repos` row, and both commit cleanly.
  - **After-commit crash** (response packet lost to the client): both writes already persisted. GitHub retries; `mark_proposal_pr_merged` matches zero rows (proposal is already `pr_merged`) and returns `None`; the pointer-update function is not called (per FR-3); no second write.

## 6) Actors and roles

- **Primary actor:** GitHub (webhook delivery) — system, not a human.
- **Secondary actor:** Relevance Engineer reading the proposals list to see which proposal is currently live.
- **Role model:** N/A — single-tenant install, no auth surface (MVP1–MVP3 per [`docs/01_architecture/tech-stack.md`](../../../01_architecture/tech-stack.md)).

### Authorization

N/A — single-tenant install, no auth surface.

### Audit events

N/A — `audit_log` lands at MVP2.

## 7) Functional requirements

### FR-1: Add `last_merged_proposal_id` column to `config_repos`

- Requirement:
  - The system **MUST** add a new nullable column `last_merged_proposal_id VARCHAR(36) NULL REFERENCES proposals(id) ON DELETE SET NULL` to the `config_repos` table via Alembic migration `0016_config_repos_last_merged_proposal_id`.
  - The system **MUST** create a partial B-tree index `config_repos_last_merged_proposal_id_idx` ON `config_repos(last_merged_proposal_id) WHERE last_merged_proposal_id IS NOT NULL` to support the reverse-lookup join used by the `ProposalSummary.is_currently_live` derivation and the `?is_last_merged=true` filter.
  - The migration **MUST** round-trip cleanly per Absolute Rule #5 (`alembic upgrade head && alembic downgrade -1 && alembic upgrade head`). `downgrade()` drops the index THEN the column (FK direction).
  - The migration **MUST** backfill existing rows via a single SQL UPDATE inside `upgrade()`:
    ```sql
    UPDATE config_repos cr
    SET last_merged_proposal_id = sub.proposal_id
    FROM (
      SELECT DISTINCT ON (c.config_repo_id)
        c.config_repo_id, p.id AS proposal_id
      FROM proposals p
      JOIN clusters c ON c.id = p.cluster_id
      WHERE p.pr_state = 'merged'
        AND p.pr_merged_at IS NOT NULL
        AND c.config_repo_id IS NOT NULL
      ORDER BY c.config_repo_id, p.pr_merged_at DESC, p.id DESC
    ) AS sub
    WHERE cr.id = sub.config_repo_id;
    ```
    Repos with no merged proposal stay NULL. `pr_merged_at IS NOT NULL` is defense-in-depth: in normal flow `mark_proposal_pr_merged` sets both fields atomically, but the filter ensures no pre-feat_github_webhook historical row with NULL timestamp slips in. The `DISTINCT ON` + `ORDER BY pr_merged_at DESC, id DESC` deterministically picks the newest-by-timestamp; the `id DESC` tie-break is a deterministic one-time seed for the (cosmically unlikely) case of two proposals merging at the same microsecond. At runtime the strict-monotonic-timestamp guard (FR-2) intentionally does NOT overwrite on equal timestamps — see the decision-log entry "Tie-break asymmetry" for the rationale.
- Notes: index naming follows the existing `<table>_<column>_idx` convention from `proposals_pr_url_idx`. ORM model gains a `Mapped[str | None]` field with no `relationship()` (the rev-lookup is via JOIN, not SQLAlchemy eager-load — keeps the model minimal and avoids importing `Proposal` into `config_repo.py`).

### FR-2: New repo function `update_config_repo_last_merged_pointer`

- Requirement:
  - The system **MUST** expose a new repo function at [`backend/app/db/repo/config_repo.py`] with signature:
    ```python
    async def update_config_repo_last_merged_pointer(
        db: AsyncSession,
        *,
        config_repo_id: str,
        proposal_id: str,
        pr_merged_at: datetime,
    ) -> bool: ...
    ```
  - The function **MUST** acquire a row-level lock on the target `config_repos` row via `SELECT … FOR UPDATE` before reading the current pointer state (mirrors the established `study_state.py:139` pattern).
  - The function **MUST** then evaluate the strict-monotonic-timestamp guard:
    - If `current.last_merged_proposal_id IS NULL` → write the new pointer; return `True`.
    - Else, fetch the currently-tracked proposal's `pr_merged_at`; if `pr_merged_at_new > pr_merged_at_current` → write the new pointer; return `True`.
    - Else → no-op; return `False`.
  - The function **MUST NOT** commit — the caller (webhook handler) owns the transaction boundary. The function uses `db.flush()` to stage the UPDATE.
  - The function **MUST** emit a structured log line at INFO level on a successful update (`config_repo_last_merged_pointer_updated` with `config_repo_id` + `previous_proposal_id` + `new_proposal_id` + `pr_merged_at`) and at DEBUG level on a no-op skip (`config_repo_last_merged_pointer_skipped_older` with reason).
- Notes: returns `bool` rather than the updated row because the caller has no read need — the receiver's existing log line uses the proposal_id and the webhook receipt doesn't surface the config_repo summary.

### FR-3: Webhook handler integration

- Requirement:
  - The system **MUST** patch [`backend/app/api/webhooks/github.py:181-194`] so that, immediately after `mark_proposal_pr_merged` returns a non-None row inside the `if decision.mutation == "merged":` + non-None `pr_merged_at` branch, the handler:
    1. Reads the merged proposal's `cluster_id` (already in scope as `proposal_row.cluster_id`).
    2. Resolves the cluster's `config_repo_id` via `await repo.get_cluster(db, proposal_row.cluster_id)`.
    3. If the resolved row has a non-NULL `config_repo_id`, calls `await repo.update_config_repo_last_merged_pointer(db, config_repo_id=cluster.config_repo_id, proposal_id=proposal_row.id, pr_merged_at=decision.pr_merged_at)`.
    4. If the cluster is None (referential integrity should make this unreachable) OR `cluster.config_repo_id IS NULL`, logs `config_repo_last_merged_pointer_skipped_no_repo` at DEBUG and continues without crashing.
  - The pointer update **MUST** happen in the SAME transaction as the proposal UPDATE — the existing `await db.commit()` at line 197 commits both writes atomically.
  - The handler **MUST NOT** call the pointer-update function in the `mark_proposal_pr_closed` fallback branch (line 188) — that branch handles GitHub's eventual-consistency `merged_at=null` case, where the merge isn't yet confirmed. The reconciler (FR-3a) will pick up the real merge later.
  - The handler **MUST NOT** call the pointer-update function when `mark_proposal_pr_merged` returns `None` (already-merged proposal, out-of-order delivery) — the row didn't transition this delivery, so the pointer write would race against the delivery that DID make the transition.
- Notes: the receiver's existing structured-log line at lines 199–206 is unchanged; the pointer update gets its own log line via FR-2.

### FR-3a: PR reconciler integration

- Requirement:
  - The system **MUST** patch [`backend/workers/pr_reconcile.py:170-180`](../../../../backend/workers/pr_reconcile.py) so that, immediately after `mark_proposal_pr_merged` returns a non-None row in the reconciler's `if merged and merged_at is not None:` branch, the worker:
    1. Resolves the cluster via `await repo.get_cluster(db, proposal.cluster_id)`.
    2. If `cluster.config_repo_id IS NOT NULL`, calls `await repo.update_config_repo_last_merged_pointer(db, config_repo_id=cluster.config_repo_id, proposal_id=proposal.id, pr_merged_at=merged_at)`.
    3. Else logs DEBUG `config_repo_last_merged_pointer_skipped_no_repo` and continues.
  - The pointer update **MUST** happen in the SAME `async with factory() as db:` block as the existing proposal UPDATE — both share `await db.commit()` at line 176.
  - The reconciler **MUST NOT** call the pointer-update function in the `elif state == "closed":` branch (line 181) — that branch handles abandoned PRs that never merged.
- Notes: FR-3a covers the case where the webhook delivery NEVER fired (e.g., GitHub outage, mounted-secret rotation between PR-open and merge) and the reconciler is the first path to observe the merge — proposal is still `pr_opened+open`, `mark_proposal_pr_merged` succeeds, pointer update runs.
- **Known pre-existing limitation (out of scope for this feature):** when the webhook DID fire with the GitHub `merged_at=null` eventual-consistency fallback (`github.py:188` → `mark_proposal_pr_closed`), the proposal lands in `pr_opened+closed`. The reconciler's `mark_proposal_pr_merged` requires `pr_state='open'` and returns `None` against this state — so FR-3a's pointer update does NOT run on that delivery. The proposal stays `pr_opened+closed` forever until an operator manually reopens or rejects it. This is a pre-existing bug in the reconciler path (independent of this feature) and is captured for separate triage as [`bug_pr_reconciler_blocked_by_closed_fallback/idea.md`](../bug_pr_reconciler_blocked_by_closed_fallback/idea.md). This feature does NOT attempt to fix that bug — the pointer simply won't be maintained for any merge that hits the eventual-consistency fallback, until the underlying reconciler bug is fixed. Acceptable for MVP1 because (a) the fallback is rare (most GitHub deliveries include `merged_at`), (b) the affected proposal's status string still tells the operator what's wrong, and (c) trying to fix the closed→merged transition path here would balloon the scope.

### FR-4: `ConfigRepoDetail` response field

- Requirement:
  - The system **MUST** add a new field to `ConfigRepoDetail` (Pydantic model at [`backend/app/api/v1/schemas.py:1081`]):
    ```python
    last_merged_proposal: ProposalSummary | None = None
    ```
  - The system **MUST** populate the field in `GET /api/v1/config-repos/{id}` via a new repo helper:
    ```python
    async def get_config_repo_with_last_merged_proposal(
        db: AsyncSession,
        config_repo_id: str,
    ) -> tuple[ConfigRepo, Proposal | None, Cluster | None, QueryTemplate | None] | None: ...
    ```
    The helper returns `None` when the config_repo does not exist (preserving the existing 404 `CONFIG_REPO_NOT_FOUND` envelope). When the row exists but `last_merged_proposal_id IS NULL`, the helper returns `(config_repo, None, None, None)`. When the pointer is set, the helper LEFT JOINs `proposals → clusters → query_templates` and returns the embedded rows so the router can assemble the `ProposalSummary` without a second roundtrip.
  - **The embedded `ProposalSummary.is_currently_live` field MUST be `True` whenever it is rendered as `ConfigRepoDetail.last_merged_proposal` — derived from the embed context (`config_repos.last_merged_proposal_id = proposal.id`), NOT from the generic `proposals → clusters → config_repos` JOIN used elsewhere.** This guarantees AC-8 even when the proposal's cluster was later unwired from the config_repo (see decision-log entry "Cluster-with-config_repo-rotated").
  - The list endpoint `GET /api/v1/config-repos` extends the response too: every row's `last_merged_proposal` defaults to `null` (no JOIN performed for list calls — populating it for every row in a 200-row page is wasteful and the proposals list already exposes the live indicator via `is_currently_live`). The serializer `_to_detail()` at `config_repos.py:93` is updated to accept an optional `last_merged_proposal: ProposalSummary | None = None` kwarg so the detail endpoint passes the populated value and the list endpoint passes `None`.
- Notes: keeps the change additive — frontend code that doesn't use the new field is unaffected. The OpenAPI schema for both endpoints will declare the field as `ProposalSummary | null`; clients that omit it on read are forward-compatible.

### FR-5: `ProposalSummary.is_currently_live` field

- Requirement:
  - The system **MUST** add a new field to `ProposalSummary` (Pydantic model at [`backend/app/api/v1/schemas.py:986`]):
    ```python
    is_currently_live: bool = False
    ```
  - The system **MUST** add the same field to `ProposalDetail` (line 1000).
  - The system **MUST** populate the field via the existing `_assemble_proposal_summary_batch()` and `_assemble_proposal_detail()` paths at [`backend/app/api/v1/proposals.py`]. **The derivation is pointer-only — symmetric with the `?is_last_merged=true` filter (FR-6):** a proposal is "currently live" iff at least one `config_repos` row has `last_merged_proposal_id = proposal.id`. The derivation does NOT JOIN through the proposal's current `cluster.config_repo_id` because that would produce asymmetric results when an operator unwires a cluster after a merge (the cluster's edge changes but the proposal IS still historically the last-merged for the repo).
  - A new repo helper `find_currently_live_proposal_ids(db, proposal_ids)` returns `set[str]` of proposal IDs that appear in `config_repos.last_merged_proposal_id` for the given set. SQL pattern:
    ```sql
    SELECT cr.last_merged_proposal_id
    FROM config_repos cr
    WHERE cr.last_merged_proposal_id = ANY(:proposal_ids)
    ```
    The serializer marks rows in the returned set as `is_currently_live=True`.
- Notes: the JOIN is bounded by the page size (max 200 per request); no risk of unbounded fan-out. This derivation is also what the `ConfigRepoDetail.last_merged_proposal` embed uses (FR-4): the pointer is the single source of truth for "live."

### FR-6: `?is_last_merged=true|false` filter on `GET /api/v1/proposals`

- Requirement:
  - The system **MUST** accept a new optional query param `?is_last_merged=true|false` on `GET /api/v1/proposals`.
  - `?is_last_merged=true` filters to proposals where an `EXISTS` subquery matches a `config_repos` row whose `last_merged_proposal_id = proposals.id`:
    ```sql
    AND EXISTS (
      SELECT 1 FROM config_repos cr
      WHERE cr.last_merged_proposal_id = proposals.id
    )
    ```
    0–N rows expected — at most one live row per config_repo.
  - `?is_last_merged=false` filters to the complement via `NOT EXISTS` against the same subquery. NULL-safe by construction: proposals whose `cluster.config_repo_id IS NULL` AND proposals whose config_repo has a NULL or different pointer are all included.
  - Omitted = unfiltered.
  - The filter MUST work alongside all existing filters (`?status=`, `?cluster_id=`, `?source=`, `?template_id=`, `?study_id=`, `?since=`, `?q=`) via the same `WHERE` chain.
  - `X-Total-Count` MUST reflect the filtered count.
  - Cursor pagination MUST remain correct when the filter is on (the cursor encoding is unchanged; the filter narrows the result set, the keyset paging still orders deterministically on `(created_at, id)` or the active `?sort=` key).
- Notes: FastAPI's default `bool` parsing accepts `true|false|1|0|yes|no|on|off|t|f|y|n` (Pydantic `BoolValidator`), so values like `yes` parse as `True` rather than failing. Truly invalid values (e.g., `maybe`, `2`) surface as the standard `VALIDATION_ERROR` envelope via the global handler at [`backend/app/api/errors.py:103-118`](../../../../backend/app/api/errors.py).

### FR-7: UI badge — "Currently live"

- Requirement:
  - The system **MUST** add a small `<CurrentlyLiveBadge>` component at [`ui/src/components/proposals/currently-live-badge.tsx`] that renders a green "Currently live" pill when shown.
  - The proposals table at [`ui/src/components/proposals/proposals-table.tsx`] (or its column config) **MUST** render the badge in the status column (or as a sibling chip in the row's primary identity column) when `row.is_currently_live === true`.
  - The proposal detail page at [`ui/src/app/proposals/[id]/page.tsx`] **MUST** render the badge adjacent to the status row when `proposal.is_currently_live === true`.
  - The badge **MUST** have a tooltip (via the existing `<InfoTooltip>` primitive) keyed to a new glossary entry `proposal.currently_live` (short + long form) per CLAUDE.md "Enumerated Value Contract Discipline" (the contextual-help drift safety net).
  - Glossary key `proposal.currently_live` added to [`ui/src/lib/glossary.ts`]:
    - **short:** "This proposal is the most recently merged PR for its config repo — assumed live in production."
    - **long:** "RelyLoop tracks the last-merged proposal per config repo as a pointer. Once a PR merges and the GitHub webhook fires, the proposal becomes the 'currently live' record. Production deploy is operator-owned, so this badge means 'merged most recently' not 'verified live in your cluster.'"
- Notes: the existing `<StatusBadge>` precedent at [`ui/src/components/proposals/`] is the visual model — pill, small text, semantic color.

### FR-8: Tooltip + glossary parity

- Requirement:
  - The new glossary entry `proposal.currently_live` **MUST** pass the existing glossary discipline tests at [`ui/src/__tests__/glossary/`] (no missing entries, no orphan tooltip references).
  - The component **MUST** route its tooltip through `<InfoTooltip glossaryKey="proposal.currently_live">` (NOT an inline hardcoded string), enforced by the `glossary-gate-skill-edits` lint guard pattern from `chore_guides_glossary_route`.
  - The `<InfoTooltip>` trigger MUST be focusable (keyboard `Tab` reaches it) and the tooltip content MUST appear on `focus` events as well as `hover` events. Mirrors the established `<InfoTooltip>` Radix-based accessibility primitives at [`ui/src/components/common/info-tooltip.tsx`].
- Notes: matches the contextual-help discipline pattern established by `feat_contextual_help` (16th MVP1 feature, PR #122).

### FR-9: Proposals page filter chip — "Currently live only"

- Requirement:
  - The proposals page at [`ui/src/app/proposals/page.tsx`] **MUST** add a new filter chip labeled **"Currently live only"** that is a **two-state toggle** between (a) absent — no `is_last_merged` URL param, all proposals shown — and (b) active — `?is_last_merged=true`. The chip does NOT expose `?is_last_merged=false` (that complement remains API-only — see FR-6 notes).
  - The chip MUST integrate with the existing `useDataTableUrlState` hook so the active state survives reloads and shows up in the URL query string as `?is_last_merged=true`.
  - The chip MUST have a glossary-keyed tooltip (`proposal.currently_live_filter`) explaining the filter scope. This is a SECOND new glossary key in addition to `proposal.currently_live` (FR-7).
  - When the filter is active and `query.data?.data` is empty, the existing table empty-state copy MUST be replaced with: "No currently-live proposals — no config repo has a merged proposal tracked yet."
  - Clearing the filter (clicking the chip a second time, or removing the URL param manually) MUST drop the URL param entirely and reset to the unfiltered view.
  - Keyboard activation MUST work: the chip is operable via `Enter` and `Space` from focus, matching the existing filter-chip pattern.
- Notes: two new glossary entries total — `proposal.currently_live` (FR-7, badge) and `proposal.currently_live_filter` (FR-9, chip). Both are added in the same Story 3.2 glossary patch.

## 8) API and data contract baseline

### 8.1 Endpoint surface

This feature does NOT add any new endpoints. It extends three existing surfaces:

| Method | Path | Purpose | Change |
|---|---|---|---|
| `POST` | `/webhooks/github` | Receive a GitHub webhook delivery | Side-effect added on the `pull_request.closed` + `merged=true` + non-null `merged_at` branch: pointer update on `config_repos`. No response-shape change. |
| `GET` | `/api/v1/config-repos/{id}` | Config-repo detail | Response gains `last_merged_proposal: ProposalSummary \| null`. |
| `GET` | `/api/v1/proposals` | Cursor-paginated proposals list | Accepts new `?is_last_merged=true\|false` query param; `ProposalSummary` rows gain `is_currently_live: bool`. |
| `GET` | `/api/v1/proposals/{id}` | Proposal detail | `ProposalDetail` response gains `is_currently_live: bool`. |

No new error codes.

### 8.2 Contract rules

- Standard rules apply per [`api-conventions.md`](../../../01_architecture/api-conventions.md):
  - Error body **MUST** include machine-readable `error_code` (existing standard envelope).
  - Status codes are deterministic per scenario.
- This feature's only validation-error case is `?is_last_merged=<not-a-bool>` → 422 `VALIDATION_ERROR` via Pydantic; no domain-specific code.

### 8.3 Response examples

**`GET /api/v1/config-repos/{id}` success (with last-merged tracked):**
```json
{
  "id": "0192ab34-5678-7000-8000-deadbeef0001",
  "name": "search-config-prod",
  "provider": "github",
  "repo_url": "https://github.com/example/search-config",
  "default_branch": "main",
  "pr_base_branch": "main",
  "auth_ref": "github_pat_prod",
  "webhook_secret_ref": "github_webhook_secret_prod",
  "webhook_registration_error": null,
  "created_at": "2026-05-15T10:00:00+00:00",
  "last_merged_proposal": {
    "id": "0192cd56-7890-7000-8000-deadbeef0002",
    "study_id": "0192ef78-9abc-7000-8000-deadbeef0003",
    "cluster": {
      "id": "0192aa00-0000-7000-8000-deadbeef0004",
      "name": "prod-es",
      "engine_type": "elasticsearch",
      "environment": "prod"
    },
    "template": {
      "id": "0192bb00-0000-7000-8000-deadbeef0005",
      "name": "default-bm25",
      "version": 3,
      "engine_type": "elasticsearch"
    },
    "status": "pr_merged",
    "pr_state": "merged",
    "pr_url": "https://github.com/example/search-config/pull/42",
    "metric_delta": { "ndcg@10": { "baseline": 0.41, "achieved": 0.47, "delta_pct": 14.6 } },
    "is_currently_live": true,
    "created_at": "2026-05-22T14:30:00+00:00"
  }
}
```

**`GET /api/v1/config-repos/{id}` success (no last-merged yet):**
```json
{
  "id": "0192ab34-5678-7000-8000-deadbeef0001",
  "name": "search-config-dev",
  "provider": "github",
  "repo_url": "https://github.com/example/search-config-dev",
  "default_branch": "main",
  "pr_base_branch": "main",
  "auth_ref": "github_pat_dev",
  "webhook_secret_ref": null,
  "webhook_registration_error": null,
  "created_at": "2026-05-22T09:00:00+00:00",
  "last_merged_proposal": null
}
```

**`GET /api/v1/proposals` success (with filter, summary rows):**
```json
{
  "data": [
    {
      "id": "0192cd56-7890-7000-8000-deadbeef0002",
      "study_id": "0192ef78-9abc-7000-8000-deadbeef0003",
      "cluster": { "id": "0192aa00-...", "name": "prod-es", "engine_type": "elasticsearch", "environment": "prod" },
      "template": { "id": "0192bb00-...", "name": "default-bm25", "version": 3, "engine_type": "elasticsearch" },
      "status": "pr_merged",
      "pr_state": "merged",
      "pr_url": "https://github.com/example/search-config/pull/42",
      "metric_delta": { "ndcg@10": { "baseline": 0.41, "achieved": 0.47, "delta_pct": 14.6 } },
      "is_currently_live": true,
      "created_at": "2026-05-22T14:30:00+00:00"
    }
  ],
  "next_cursor": null,
  "has_more": false
}
```

**Validation error (`?is_last_merged=maybe` — truly unparseable; note `yes` parses as `True` per Pydantic bool grammar):**
```json
{
  "detail": {
    "error_code": "VALIDATION_ERROR",
    "message": "Input should be a valid boolean, unable to interpret input (query.is_last_merged: maybe)",
    "retryable": false
  }
}
```
(Wrapped by the global validation handler at [`backend/app/api/errors.py:103-118`](../../../../backend/app/api/errors.py) — identical envelope to every other validation failure across the RelyLoop API.)

### 8.4 Enumerated value contracts

This feature introduces no new enumerated wire values. The new field `is_currently_live` is a plain `bool` (FastAPI/Pydantic-native; not enum-backed). The new query param `?is_last_merged` accepts the Pydantic-native bool grammar (`true|false|1|0|yes|no|on|off|t|f|y|n`).

Two new glossary keys (frontend-only — no backend wire contract):
- `proposal.currently_live` — used by the `<CurrentlyLiveBadge>` (FR-7).
- `proposal.currently_live_filter` — used by the proposals-page filter chip (FR-9).

Both keys must pass the existing glossary discipline tests at `ui/src/__tests__/glossary/` before merge.

### 8.5 Error code catalog

This feature introduces **no new error codes**. All edge cases (NULL config_repo_id, out-of-order webhooks, etc.) are silent skips with structured DEBUG/INFO logs.

## 9) Data model and state transitions

### New/changed entities

**Modified table: `config_repos`**

- Add `last_merged_proposal_id VARCHAR(36) NULL REFERENCES proposals(id) ON DELETE SET NULL` — denormalized FK pointing at the most recently merged proposal for this repo.
- Add partial index `config_repos_last_merged_proposal_id_idx` ON `config_repos(last_merged_proposal_id) WHERE last_merged_proposal_id IS NOT NULL`.

Resulting ORM:
```python
class ConfigRepo(Base):
    # ... existing columns unchanged ...

    last_merged_proposal_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("proposals.id", ondelete="SET NULL"),
        nullable=True,
    )
    """The most recently merged proposal for this repo. Maintained by the
    merge-event webhook handler in :mod:`backend.app.api.webhooks.github`.
    NULL on repos that have never had a proposal merge."""
```

### Required invariants

- **I1: pointer points only at a merged proposal.** When `last_merged_proposal_id IS NOT NULL`, the referenced proposal MUST have `pr_state='merged'`. Enforcement: the only write site (`update_config_repo_last_merged_pointer`) is called from the merge-event branch of the webhook handler, after `mark_proposal_pr_merged` succeeded — at which point the referenced row's `pr_state='merged'`. **No DB CHECK constraint** can express this (would require a subquery, not allowed in CHECK on Postgres); enforcement is at the application layer.
- **I2: monotonic timestamp.** When a new merge fires for the same config_repo, the new `pr_merged_at` MUST be strictly greater than the currently-tracked proposal's `pr_merged_at`. Enforcement: `update_config_repo_last_merged_pointer`'s guard logic.
- **I3: ON DELETE SET NULL.** If a tracked proposal is hard-deleted (only via the test-only `DELETE /api/v1/_test/proposals/{id}` endpoint shipped by `chore_e2e_test_rows_isolation`), the FK reverts to NULL. The downstream reads (`ConfigRepoDetail.last_merged_proposal`, `is_currently_live`) silently degrade to "no live pointer."
- **I4: same-transaction atomicity.** The pointer UPDATE shares the webhook receiver's transaction with the `mark_proposal_pr_merged` UPDATE. Both commit or both roll back.

### State transitions

The pointer has two states:
- `NULL` (no merged proposal tracked).
- `<proposal_id>` (one specific merged proposal is the live pointer).

Transitions:
- `NULL → <pid_A>` when the first proposal for this repo merges.
- `<pid_A> → <pid_B>` when a newer-timestamp merge for the same repo fires.
- `<pid_A> → NULL` only via `ON DELETE SET NULL` (test-only hard-delete).
- `<pid_A> → <pid_A>` (no-op) when a duplicate/out-of-order merge webhook arrives for the same or older pid — the strict-monotonic-timestamp guard rejects it.

There is no `<pid_A> → NULL` transition through normal operation. A proposal being closed-without-merge does not clear the pointer (the `mark_proposal_pr_closed` fallback explicitly does not call the pointer-update function — see Anti-patterns).

### Idempotency/replay behavior

- **Out-of-order webhook delivery.** Webhook for proposal P2 (merged at t=10) arrives BEFORE webhook for proposal P1 (merged at t=5).
  - Sequence: P2 fires → `mark_proposal_pr_merged(P2)` succeeds → pointer set to P2 (pr_merged_at=10). P1 fires → `mark_proposal_pr_merged(P1)` succeeds → pointer-update function checks `pr_merged_at(P1)=5 < pr_merged_at(current=P2)=10` → no-op skip. Final state: pointer = P2 (correct).
- **Duplicate delivery.** Same merge webhook redelivered.
  - Second invocation: `mark_proposal_pr_merged` returns `None` (proposal already `pr_state='merged'`) → pointer-update function is not called → no-op (correct).
- **Concurrent merges on the same config_repo.** PR-A and PR-B for the same repo both fire near-simultaneously.
  - The `SELECT … FOR UPDATE` on `config_repos.id` inside the pointer-update function serializes the two webhook transactions on the same row. Whichever transaction acquires the lock first writes its pointer; the second then sees the first's value and applies the strict-monotonic-timestamp guard against it. Deterministic outcome: the newer-timestamp merge wins regardless of webhook delivery order.

## 10) Security, privacy, and compliance

- **Threats:**
  - T1 — Tampering with the pointer via SQL injection. **Mitigation:** all writes go through parameterized SQLAlchemy statements; no raw string interpolation.
  - T2 — Pointer reveals which repo is most active. **Mitigation:** the proposals list already exposes `pr_merged_at` on every row; the pointer is denormalization, not new information.
  - T3 — Webhook spoofing causing forged pointer updates. **Mitigation:** the existing HMAC signature verification at `github.py:155-165` is the gate; the pointer update is downstream of `verify_webhook_signature`.
- **Controls:** Standard SQLAlchemy parameterization; existing webhook HMAC; no new secrets.
- **Secrets/key handling:** None. This feature reads/writes no secret material.
- **Auditability:** N/A — `audit_log` lands at MVP2. When it lands, the pointer update will need an audit event paired with the existing proposal-merge event.
- **Data retention/deletion/export impact:** ON DELETE SET NULL on the FK ensures hard-deleting a proposal (test-only path) correctly clears any references. No export-format changes.

## 11) UX flows and edge cases

### Information architecture

- **Navigation placement:** the "Currently live" badge appears on the proposals list rows (`/proposals`) and on the proposal detail page (`/proposals/[id]`). Both are existing pages — no new routes.
- **Labeling taxonomy:**
  - Badge label: **"Currently live"** (matches operator mental model — concise, doesn't claim deploy verification).
  - Tooltip key: `proposal.currently_live` (glossary).
  - Filter chip label (proposals page): **"Currently live only"** with description "Show only the most recently merged proposal per config repo."
- **Content hierarchy:** badge renders inline within the existing status column on the proposals list (or as an adjacent pill in the row's identity area, decided in implementation review). On the detail page, badge sits adjacent to the `<StatusBadge>` near the top of the page.
- **Progressive disclosure:** badge is visible by default for any proposal whose `is_currently_live === true`; tooltip discloses the meaning on hover.
- **Relationship to existing pages:** purely additive to existing surfaces.

### Tooltips and contextual help

| Element | Tooltip / help text | Trigger | Placement | Glossary key |
|---|---|---|---|---|
| `<CurrentlyLiveBadge>` | "This proposal is the most recently merged PR for its config repo — assumed live in production." (short form; long form via popover on info-icon click) | `hover` (badge) and `focus` (keyboard) and `click` (info icon) | `top` | `proposal.currently_live` |
| "Currently live only" filter chip | "Show only proposals tracked as the live config in their repo." | `hover` and `focus` | `top` | `proposal.currently_live_filter` |

Both entries route through the existing `<InfoTooltip>` / `<HelpPopover>` glossary-keyed primitives. Both primitives expose tooltips on keyboard focus (not hover-only) per WAI-ARIA tooltip pattern.

### Primary flows

1. **Operator views proposals list.** Navigates to `/proposals`. The most recently merged proposal for each config_repo shows the "Currently live" green pill in its row. Older merged proposals show their normal status badges only.
2. **Operator filters to live proposals.** Clicks the "Currently live only" filter chip. The list narrows to proposals where `is_currently_live === true` (one per config_repo at most). `X-Total-Count` reflects the filtered count.
3. **Operator opens a proposal detail.** Clicks a row. The detail page renders the "Currently live" badge if applicable. Tooltip on hover explains the semantics.
4. **System: merge webhook arrives.** GitHub delivers `pull_request.closed` with `merged=true`. The receiver verifies HMAC, runs `dispatch_event`, calls `mark_proposal_pr_merged` (returns non-None), then calls `update_config_repo_last_merged_pointer` which row-locks the `config_repos` row, checks the timestamp guard, and writes the pointer. Both writes commit in one transaction. Structured log line confirms the update.

### Edge/error flows

- **Out-of-order webhook delivery.** Older-timestamp merge arrives after newer-timestamp merge for the same repo. The strict-monotonic guard skips the update. DEBUG log line `config_repo_last_merged_pointer_skipped_older` captures the skip with both timestamps.
- **`cluster.config_repo_id IS NULL`.** Merge fires for a proposal whose cluster has no wired Git repo (rare in practice). The receiver logs DEBUG `config_repo_last_merged_pointer_skipped_no_repo` and commits the proposal update only.
- **Pointer-target proposal deleted via test endpoint.** `ON DELETE SET NULL` reverts the FK. `ConfigRepoDetail.last_merged_proposal` becomes `null`; rows with `is_currently_live=true` that depend on this pointer flip to `false`. Frontend renders without the badge — no error state.
- **Webhook crash mid-transaction.** SQLAlchemy/FastAPI rolls back both the proposal UPDATE and the pointer UPDATE. GitHub retries the delivery; the receiver re-applies idempotently (proposal UPDATE no-ops via its own conditional WHERE; pointer UPDATE re-runs and produces the correct end state).

## 12) Given/When/Then acceptance criteria

### AC-1: Migration adds the column and index round-trip-cleanly

- Given the database is at revision `0015_trials_per_query_metrics`.
- When the test runs `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` against a temporary DB.
- Then the column `config_repos.last_merged_proposal_id` exists at the head with type `VARCHAR(36) NULL`, the FK targets `proposals(id)` with `ON DELETE SET NULL`, the partial index `config_repos_last_merged_proposal_id_idx` exists, and the same shape is restored after the round-trip.
- Example values: assert via `pg_attribute` + `pg_constraint` + `pg_indexes` introspection queries.

### AC-2: Migration backfills existing rows correctly

- Given a database with 2 `config_repos` rows (A, B), 3 clusters (cA1, cA2 wired to A; cB1 wired to B), and 4 proposals (PA1 merged 2026-05-10; PA2 merged 2026-05-20; PB1 merged 2026-05-15; PA3 pending, no merge).
- When the migration `upgrade()` runs.
- Then `config_repos.A.last_merged_proposal_id = PA2.id` (newest by `pr_merged_at`), `config_repos.B.last_merged_proposal_id = PB1.id`. Repos with no merged proposal stay NULL.

### AC-3: Webhook handler updates the pointer on the first merge

- Given a `config_repo` X with `last_merged_proposal_id IS NULL` and a proposal P (`status='pr_opened'`, `pr_state='open'`) under a cluster wired to X.
- When the test fires a valid HMAC-signed `pull_request.closed` webhook for P with `merged=true` and `merged_at='2026-05-22T14:30:00Z'`.
- Then `config_repos.X.last_merged_proposal_id == P.id` AND `proposals.P.status='pr_merged'` AND `proposals.P.pr_merged_at='2026-05-22T14:30:00Z'`. One INFO log line `config_repo_last_merged_pointer_updated` is emitted.

### AC-4: Out-of-order webhook does not regress the pointer

- Given `config_repos.X.last_merged_proposal_id = P2` (merged 2026-05-22T14:30:00Z).
- When the test fires a valid webhook for P1 (also wired to X) with `merged=true` and `merged_at='2026-05-22T10:00:00Z'` (older timestamp).
- Then `mark_proposal_pr_merged(P1)` succeeds (P1 transitions `pr_opened → pr_merged`), BUT `config_repos.X.last_merged_proposal_id` remains `P2`. One DEBUG log line `config_repo_last_merged_pointer_skipped_older` is emitted.

### AC-5: Duplicate webhook is a no-op

- Given a proposal P merged via webhook with current pointer set.
- When the test fires the same webhook delivery again (identical payload, identical HMAC).
- Then `mark_proposal_pr_merged(P)` returns `None` (proposal already merged), the pointer-update function is NOT called, the pointer remains unchanged.

### AC-6: NULL `cluster.config_repo_id` is silently skipped

- Given a proposal P whose cluster has `config_repo_id IS NULL`.
- When the merge webhook fires.
- Then `mark_proposal_pr_merged(P)` succeeds, NO pointer write happens, NO error is raised, one DEBUG log line `config_repo_last_merged_pointer_skipped_no_repo` is emitted.

### AC-7: Concurrent merges serialize via the row lock

- Given two proposals P_A (merged_at=t1) and P_B (merged_at=t2 where t2 > t1, distinct microseconds) wired to the same `config_repo` X.
- When two webhook deliveries fire concurrently (parallel async tasks against separate sessions).
- Then the deterministic outcome holds: `config_repos.X.last_merged_proposal_id == P_B` (newer wins) AND both `proposals.P_A.status='pr_merged'` AND `proposals.P_B.status='pr_merged'`. Deadlocks are not observed (verified by running the test 20 times back-to-back in the integration suite — Postgres's row-level lock is sufficient because both transactions touch the same `config_repos` PK).

### AC-8: `ConfigRepoDetail` exposes `last_merged_proposal`

- Given `config_repos.X.last_merged_proposal_id = P`.
- When `GET /api/v1/config-repos/X` is called.
- Then the response body's `last_merged_proposal` field is a populated `ProposalSummary` JSON object with `id = P.id`, `status='pr_merged'`, and (importantly) `is_currently_live: true`. For an X with NULL pointer, the field is `null`.

### AC-9: `ProposalSummary` carries `is_currently_live`

- Given `config_repos.X.last_merged_proposal_id = P_live`, plus 4 other proposals (P_pending, P_open, P_closed, P_merged_older) wired to clusters under X.
- When `GET /api/v1/proposals?cluster_id=<X.cluster>` is called.
- Then exactly one row in `data` has `is_currently_live: true` (the `P_live` row). All other rows have `is_currently_live: false`. The field is present on every row (never omitted).

### AC-10: `?is_last_merged=true` filter

- Given the corpus from AC-9.
- When `GET /api/v1/proposals?is_last_merged=true` is called.
- Then `data` contains exactly the live proposals across all config_repos (one per repo with a non-NULL pointer). `X-Total-Count` equals `data.length` (assuming no pagination).
- Example values: with 3 config_repos each having a tracked pointer, `data.length == 3`, all rows have `is_currently_live: true`.

### AC-11: `?is_last_merged=false` filter

- Given the same corpus.
- When `GET /api/v1/proposals?is_last_merged=false` is called.
- Then `data` contains the complement: all proposals NOT pointed at by any `config_repos.last_merged_proposal_id`. Every row has `is_currently_live: false`.

### AC-12: Invalid filter value surfaces 422 (wrapped envelope)

- When `GET /api/v1/proposals?is_last_merged=maybe` is called.
- Then HTTP 422 with the standard RelyLoop envelope: `{"detail": {"error_code": "VALIDATION_ERROR", "message": "<human>", "retryable": false}}` — wrapped by the global handler at `backend/app/api/errors.py:103-118`. Pydantic's bool grammar accepts `yes|no|on|off|1|0|t|f|y|n` so those values do NOT trigger this AC; pick `maybe` or `2` as the test fixture.

### AC-13: UI badge renders when `is_currently_live=true`

- Given a Playwright real-backend test that seeds a proposal P, fires the merge webhook, and waits for the webhook receiver to commit.
- When the operator navigates to `/proposals` and the table renders.
- Then the row for P shows a `<CurrentlyLiveBadge>` (locator `[data-testid="currently-live-badge"]` or equivalent). Hovering the badge surfaces the tooltip text from glossary key `proposal.currently_live`.

### AC-14: ProposalDetail also carries the field

- Given `is_currently_live=true` for P.
- When `GET /api/v1/proposals/P` is called.
- Then the response includes `is_currently_live: true`. The UI detail page renders the badge.

### AC-15: ON DELETE SET NULL on test-only hard-delete

- Given `config_repos.X.last_merged_proposal_id = P` AND the test-only `DELETE /api/v1/_test/proposals/P` endpoint is callable in the test env.
- When the endpoint is called.
- Then `config_repos.X.last_merged_proposal_id IS NULL` (FK cascade reverted to NULL). No constraint violation; no orphan FK.

## 13) Non-functional requirements

- **Performance:**
  - The added webhook latency is one row-locked SELECT + one UPDATE — well under 10ms p99 on Postgres for an indexed primary-key lookup.
  - The `_assemble_proposal_summary_batch` JOIN extension adds one query per page (returning at most 200 rows) — no significant change to the proposals list latency.
  - `GET /api/v1/config-repos/{id}` adds one optional JOIN — same order of magnitude as the existing detail-fetch query.
- **Reliability:** No new failure modes. Transaction atomicity guarantees the pointer cannot drift from the proposal state.
- **Operability:**
  - Two new structured log events (`config_repo_last_merged_pointer_updated` at INFO, `config_repo_last_merged_pointer_skipped_*` at DEBUG). Operators can `grep` for either name to track pointer activity.
  - No new metrics, no new alerts. The existing webhook latency histogram captures the added cost.
- **Accessibility:** the `<CurrentlyLiveBadge>` component MUST include an `aria-label` matching the tooltip short form so screen readers narrate the meaning. The badge must remain readable in both light and dark themes (tested visually).

## 14) Test strategy requirements (spec-level)

### Unit tests (`backend/tests/unit/`)

This feature has **no pure-Python logic that can be tested without a database** — the repo helper's correctness depends on Postgres row-level locking, FK semantics, async SQLAlchemy flush behavior, and timestamp comparisons. All meaningful coverage of the repo helper sits in the integration layer below.

If a small pure-domain helper is extracted (e.g., a "given two timestamps + current pointer state, should we update?" comparator), it MAY live at `backend/tests/unit/domain/` — but that's an implementation-plan decision, not a spec mandate.

### Integration tests (`backend/tests/integration/`)

- `test_config_repo_pointer_update_repo.py` (real-Postgres AsyncSession fixture):
  - Strict-monotonic-timestamp guard logic (3 cases: NULL pointer → write; newer → write; older → skip).
  - Idempotent same-pointer/same-timestamp call returns `False`, no write.
  - Row-lock test (`SELECT … FOR UPDATE` properly serializes — paired async tasks observe ordered writes).
- `test_webhook_config_repo_pointer.py`:
  - AC-3 (first merge sets the pointer).
  - AC-4 (out-of-order skip).
  - AC-5 (duplicate webhook is a no-op).
  - AC-6 (NULL `cluster.config_repo_id` is skipped).
  - AC-7 (concurrent merges serialize correctly, verified by `asyncio.gather` of two fake-webhook tasks).
  - AC-15 (test-only proposal hard-delete reverts the FK).
- `test_pr_reconcile_config_repo_pointer.py`:
  - **FR-3a happy path** — reconciler picks up a merge that the webhook never delivered (proposal still `pr_opened+open` because no webhook arrived). The reconciler's `mark_proposal_pr_merged` succeeds and the pointer update fires. Mirrors AC-3 but drives the reconciler's `tick()` loop instead of the webhook receiver. Single new test.
  - **Negative documentation test** — explicitly asserts the known pre-existing limitation: when the webhook delivered `merged=true` with `merged_at=null` and the fallback called `mark_proposal_pr_closed`, the proposal lands in `(pr_opened, closed)`. A subsequent reconciler tick observing `merged=true` + non-null `merged_at` does NOT update the pointer (because `mark_proposal_pr_merged` matches zero rows under that state). The test asserts the no-op behavior AND includes a comment linking to [`bug_pr_reconciler_blocked_by_closed_fallback/idea.md`](../bug_pr_reconciler_blocked_by_closed_fallback/idea.md) so future readers understand the gap is intentional, not a regression. Fixing the gap requires changes to the reconciler state machine, which is out of scope for this feature.
- `test_proposals_is_last_merged_filter.py`:
  - AC-9 (per-row `is_currently_live`).
  - AC-10 (`?is_last_merged=true`).
  - AC-11 (`?is_last_merged=false`).
- `test_config_repo_detail_last_merged.py`:
  - AC-8 (detail endpoint embeds the proposal summary; embedded `is_currently_live` is True even when the proposal's cluster has had its `config_repo_id` rotated).
- `test_migration_0016.py`:
  - AC-1 (round-trip), AC-2 (backfill).

### Contract tests (`backend/tests/contract/`)

- `test_github_pr_worker_api_contract.py` — extend to assert `last_merged_proposal` field is in the `ConfigRepoDetail` schema with type `ProposalSummary | null`. Default `None` for new repos.
- `test_digest_proposal_api_contract.py` — extend to assert `is_currently_live` field exists on every row of `ProposalsListResponse.data` AND on `ProposalDetail`. AC-12 (invalid filter → 422 standard envelope).

### E2E tests (`ui/tests/e2e/`)

- `proposals-currently-live.spec.ts` (or extend existing `proposals.spec.ts`):
  - AC-13 (real-backend seed → webhook fire → badge appears).
  - Real-backend only — no `page.route()` mocking per CLAUDE.md "Integration Test Mocking Policy."

### UI vitest tests (`ui/src/__tests__/`)

- `proposals/currently-live-badge.test.tsx`:
  - Renders with the correct label + ARIA attributes.
  - Tooltip wiring routes through `<InfoTooltip glossaryKey="proposal.currently_live">`.
  - Renders nothing when `is_currently_live === false` (or undefined for backward compat).
- `proposals/proposals-table-row-badge.test.tsx`:
  - Row renders the badge column when the prop is set.

### Coverage gate

This feature contributes to the existing 80% backend coverage gate. New backend modules MUST meet the gate; the new UI component MUST be covered by at least one vitest case.

## 15) Documentation update requirements

- `docs/01_architecture/data-model.md` — §"config_repos" section: add the `last_merged_proposal_id` row to the column table with type, nullability, and "maintained by webhook handler" note.
- `docs/01_architecture/api-conventions.md` — no changes (no new error codes, conventions unchanged).
- `docs/02_product/mvp1-user-stories.md` — no changes (this feature is not in the MVP1 user-stories list; it's MVP1.5 substrate for downstream features).
- `docs/03_runbooks/webhook-debugging.md` — add a §"Last-merged pointer" subsection describing the two new log events and the `psql` query to inspect a config_repo's current pointer value.
- `docs/04_security/github-token-handling.md` — no changes.
- `docs/05_quality/testing.md` — no changes (test layers unchanged).

## 16) Rollout and migration readiness

- **Feature flags / staged rollout:** None — single-tenant MVP1 deploy, no need for a flag.
- **Migration / backfill expectations:** Alembic `0016_config_repos_last_merged_proposal_id` upgrade is strictly additive (new column + new index + backfill UPDATE). Downgrade drops both. Round-trip-verify required (Absolute Rule #5).
- **Operational readiness gates:**
  - Runbook update (above) merged before ship.
  - Webhook-debugging runbook references the new structured-log event names.
  - Pre-push gate (lint/typecheck/test) green.
  - Phase-gate cumulative-diff GPT-5.5 review clean.
- **Release gate:** all CI jobs green; Gemini Code Assist review adjudicated; final GPT-5.5 review pass.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 (migration) | AC-1, AC-2, AC-15 | Story 1.1 (Alembic + ORM) | `test_migration_0016.py`; `test_webhook_config_repo_pointer.py` (AC-15) | `data-model.md` |
| FR-2 (repo helper) | AC-3, AC-4, AC-5, AC-7 | Story 1.2 (repo function) | `test_config_repo_pointer_update_repo.py`; `test_webhook_config_repo_pointer.py` | — |
| FR-3 (webhook integration) | AC-3, AC-4, AC-5, AC-6, AC-7 | Story 1.3 (handler patch) | `test_webhook_config_repo_pointer.py` | `webhook-debugging.md` |
| FR-3a (reconciler integration) | AC-3, AC-7 (analog via reconciler tick) | Story 1.4 (reconciler patch) | `test_pr_reconcile_config_repo_pointer.py` | `webhook-debugging.md` |
| FR-4 (ConfigRepoDetail field) | AC-8 | Story 2.1 (response model + endpoint) | `test_config_repo_detail_last_merged.py`; `test_github_pr_worker_api_contract.py` | — |
| FR-5 (ProposalSummary field) | AC-9, AC-14 | Story 2.2 (summary + detail serializer) | `test_proposals_is_last_merged_filter.py`; `test_digest_proposal_api_contract.py` | — |
| FR-6 (?is_last_merged filter) | AC-10, AC-11, AC-12 | Story 2.3 (router param + repo predicate) | `test_proposals_is_last_merged_filter.py`; `test_digest_proposal_api_contract.py` | — |
| FR-7 (UI badge) | AC-13 | Story 3.1 (component + integration) | `currently-live-badge.test.tsx`; `proposals-currently-live.spec.ts` | — |
| FR-8 (tooltip + glossary) | AC-13 | Story 3.2 (glossary entry + lint pass) | existing glossary discipline tests | — |
| FR-9 (proposals filter chip) | AC-13 + new UX assertions | Story 3.3 (filter chip + URL state) | `proposals/filter-chip-currently-live.test.tsx`; `proposals-currently-live.spec.ts` | — |

## 18) Definition of feature done

This feature is complete when:

- [ ] All acceptance criteria (AC-1 through AC-15) pass in CI.
- [ ] Alembic `0016` round-trips cleanly with backfill verified.
- [ ] All test layers (unit/integration/contract/E2E + UI vitest) are green; 80% backend coverage gate maintained.
- [ ] Documentation update to `docs/01_architecture/data-model.md` and `docs/03_runbooks/webhook-debugging.md` is merged in the same PR.
- [ ] No open questions remain in §19.
- [ ] Cross-model review (GPT-5.5) passed on both spec and plan.
- [ ] PR CI green; Gemini Code Assist findings adjudicated; final GPT-5.5 review pass clean.

## 19) Open questions and decision log

### Open questions

None at spec finalization time. The three questions raised in the idea are all resolved below in the decision log.

### Decision log

- **2026-05-22 — Backfill yes/no** (idea Open Question #1): **YES**. Backfill via single SQL UPDATE in `upgrade()` so the pointer is consistent on day one. Alternative (leave NULL; let first new merge populate) was rejected because it would leave the read-side surface incorrect for repos with historical merges until a new PR happens to merge — that gap could persist for weeks on low-activity repos.
- **2026-05-22 — Reopen → re-merge handling** (idea Open Question #2): the strict-monotonic-timestamp guard naturally handles it. P's reopen does NOT clear the pointer (the reopen path uses `mark_proposal_pr_reopened`, which leaves `status='pr_opened'`); a subsequent merge of P or any new proposal P' for the same repo runs through the same timestamp guard.
- **2026-05-22 — Cluster-with-config_repo-rotated** (idea Open Question #3): the pointer is historical truth for the repo. The cross-model cycle-2 review surfaced an asymmetry in the original answer; revised locked behavior: under the symmetric pointer-only derivation (FR-5, FR-6, embed in FR-4), the "Currently live" badge **still renders** for the proposal even if the operator unwires the cluster's `config_repo_id` later. Rationale: the badge answers "is this the live config for the repo?" not "is this currently routed to this cluster?" — operator unwiring is an orthogonal cluster-config decision that doesn't undo the historical merge. If an operator wants to mute the badge, they can register a new proposal-merge against the repo (which supersedes the pointer) or accept the historical-truth display.
- **2026-05-22 — UI placement** (idea hedge in §"Read surface"): the cluster detail page does NOT currently surface the linked config repo, so the badge lands on the proposals list rows + proposal detail page instead. Adding a config-repo summary section to the cluster detail page is captured as a separate follow-up if/when the operator surfaces a real need.
- **2026-05-22 — Per-row `is_currently_live` boolean vs join-on-read**: spec settled on **per-row boolean** computed in the existing batch-fetch path. Reasoning: the JOIN is bounded by the page size (max 200), and having the value on the row eliminates a separate frontend fetch + complex client-side derivation. Stays additive, easy to test.
- **2026-05-22 — Concurrent-merge serialization**: spec settled on `SELECT … FOR UPDATE` on the `config_repos` row inside the pointer-update function. Mirrors the established `study_state.py:139` pattern. Postgres handles row-level lock contention without operator-visible failures.
- **2026-05-22 — No new error codes.** All edge cases are silent skips with structured logs. No frontend-visible failure modes.
- **2026-05-22 — Tie-break asymmetry between backfill and runtime guard.** Backfill picks the highest `id` on equal-timestamp ties (one-time deterministic seed via `ORDER BY pr_merged_at DESC, id DESC`). Runtime intentionally never overwrites on equal timestamps — the strict-monotonic `>` guard's no-op IS the desired behavior. Rationale: on a microsecond-precision TIMESTAMPTZ, two webhook deliveries producing identical `pr_merged_at` is cosmically unlikely; if it ever happens, the first-committer-wins outcome is correct (the second is genuinely simultaneous, not "newer"). Backfill's tie-break is a different problem space — it's reconciling historical data where the partial ordering may have been lost; we pick a deterministic seed and let runtime invariants take over from there.
- **2026-05-22 — Embedded `is_currently_live` derives from embed context, not generic JOIN** (cross-model review F12). When `ConfigRepoDetail.last_merged_proposal` embeds a `ProposalSummary`, the embedded row's `is_currently_live` is `True` by construction — it's the pointer target. The generic `proposals → clusters → config_repos` JOIN used for the list/detail derivation could return `False` if the proposal's cluster was later rotated to a different config_repo, but inside the embed context the pointer itself is the source of truth.
- **2026-05-22 — PR reconciler is the second merge-write path** (cross-model review F9). `backend/workers/pr_reconcile.py:173` also calls `mark_proposal_pr_merged` (GitHub eventual-consistency catch-up). The pointer invariant only holds if BOTH paths maintain the pointer — added as FR-3a.
- **2026-05-22 — Repo helper coverage is integration-only** (cross-model review F13). Postgres row-level locking + FK semantics + SQLAlchemy async flush cannot be meaningfully tested with mocks. The repo helper's tests sit in `backend/tests/integration/test_config_repo_pointer_update_repo.py` with a real Postgres fixture.
- **2026-05-22 — Symmetric pointer-only derivation everywhere** (cross-model cycle-2 F1). The original draft had three derivations: embed-side (pointer-only), list-row (generic JOIN), and filter (pointer-only EXISTS). The cluster-rotation edge case revealed the asymmetry — a list row would be `is_currently_live=false` for a proposal that the filter would still return. Locked: pointer-only EXISTS everywhere. A proposal IS currently live iff a `config_repos` row's `last_merged_proposal_id = proposal.id`. The proposal's current cluster wiring is orthogonal — if an operator unwires the cluster, the historical merge truth is preserved. This is operator-intuitive: the question "is this the live config for the repo?" is answered by the repo's pointer, not by the proposal's current cluster edge.
- **2026-05-22 — Reconciler/eventual-consistency edge case is pre-existing bug** (cross-model cycle-2 F2). FR-3a handles the "webhook never fired" reconciler path. It does NOT handle the "webhook fired with `merged_at=null` → fallback closed → reconciler can't recover" path, because `mark_proposal_pr_merged` requires `pr_state='open'` and the fallback set it to `closed`. This is a pre-existing limitation in `pr_reconcile.py` (independent of this feature) captured separately as `bug_pr_reconciler_blocked_by_closed_fallback`. For this feature, the pointer is correctly maintained for ~all real-world merges (the eventual-consistency case is rare); fixing the reconciler is scope creep.
- **2026-05-22 — Filter chip is two-state, not three** (cross-model cycle-2 F4). The chip toggles between absent and `?is_last_merged=true`. The `?is_last_merged=false` complement is API-only — a future "Not currently live" UI control could expose it, but the current chip's "Currently live only" label is a single-purpose include filter.
