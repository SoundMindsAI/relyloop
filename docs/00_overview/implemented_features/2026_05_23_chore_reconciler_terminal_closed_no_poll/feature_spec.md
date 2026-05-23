# Feature Specification — Stop polling genuinely-closed-unmerged proposals (Tier A)

**Date:** 2026-05-23
**Status:** Approved
**Owners:** RelyLoop maintainer (soundminds.ai)
**Related docs:**
- [`idea.md`](idea.md)
- [`bug_pr_reconciler_blocked_by_closed_fallback` (predicate, shipped)](../../../00_overview/implemented_features/2026_05_23_bug_pr_reconciler_blocked_by_closed_fallback/)
- [`docs/01_architecture/data-model.md`](../../../01_architecture/data-model.md)
- [`docs/03_runbooks/pr-open-debugging.md`](../../../03_runbooks/pr-open-debugging.md)

---

## 1) Purpose

- **Problem.** After `bug_pr_reconciler_blocked_by_closed_fallback` widened the reconciler's candidate query (`list_pr_opened_proposals_for_reconcile` in [`backend/app/db/repo/proposal.py:493-523`](../../../../backend/app/db/repo/proposal.py#L493-L523)) to include `(pr_opened, closed)` rows so eventual-consistency recovery can fire, genuinely-closed-unmerged proposals (case b — operator closed the PR without merging) now also enter the candidate set. They get polled once per reconciler tick (default 5 min) for up to 90 days, each call returning `merged=false, state=closed` and short-circuiting at `mark_proposal_pr_closed`'s `pr_state='open'` guard as a benign no-op. Under realistic deployments this is bounded but wasteful; under adversarial workflows (1,700+ simultaneously stuck case-(b) rows) it consumes the entire GitHub authenticated-rate-limit budget.
- **Outcome.** Case (b) rows get polled at most once per 24 hours instead of once per tick — a ~288× reduction at the default 5-minute cadence (best-effort under single-worker operation; see §13 Reliability). Case (a) recovery latency for rows that have NEVER been observed as `(merged=false, state=closed)` is unaffected (still bounded by tick interval). Case (a) recovery for the narrow race where a fallback-closed row is observed as `(merged=false, state=closed)` once and then GitHub flips to `merged=true` within 24 hours is delayed by up to one 24-hour bucket — accepted trade-off per the predicate idea's cost analysis. Achieved via one nullable `proposals.last_polled_at` TIMESTAMPTZ column stamped only in the reconciler's `state=closed AND not merged` branch and a `WHERE` exclusion in the candidate query.
- **Non-goal.** No new terminal proposal status (`pr_closed_unmerged` enum or boolean) — that's Tier B in the predicate idea and waits for a UX brief on the "closed without merge" surface. No frontend changes. No new config knob (the 24-hour cadence is hard-coded; if operators need to tune it, that's a follow-up).

## 2) Current state audit

### Existing implementations

| File | What it does | API/symbol | Notes |
|---|---|---|---|
| [`backend/app/db/models/proposal.py:32-79`](../../../../backend/app/db/models/proposal.py#L32-L79) | `Proposal` ORM model | `pr_state`, `pr_merged_at`, etc. | Two CHECK constraints; no `last_polled_at` yet. |
| [`backend/app/db/repo/proposal.py:493-523`](../../../../backend/app/db/repo/proposal.py#L493-L523) | `list_pr_opened_proposals_for_reconcile` | repo helper | Returns both `(pr_opened, open)` and `(pr_opened, closed)` newer than 90 days, ordered by `created_at` asc. Widened by predicate bug-fix. |
| [`backend/app/db/repo/proposal.py:421-447`](../../../../backend/app/db/repo/proposal.py#L421-L447) | `mark_proposal_pr_closed` | repo helper | Conditional UPDATE `pr_opened+open → pr_opened+closed`; returns `None` (no-op) when `pr_state` is already `closed`. This is the no-op site we want to short-circuit before the API call. |
| [`backend/app/db/repo/proposal.py:383-419`](../../../../backend/app/db/repo/proposal.py#L383-L419) | `mark_proposal_pr_merged_from_closed` | repo helper | Recovery path for fallback-closed case (a). |
| [`backend/workers/pr_reconcile.py:77-234`](../../../../backend/workers/pr_reconcile.py#L77-L234) | `reconcile_pr_state` Arq cron worker | worker function | Iterates candidates, calls GitHub, branches on `(merged, state)`. The `elif state == "closed":` branch is at [line 221](../../../../backend/workers/pr_reconcile.py#L221) — current no-op site. |
| [`backend/workers/pr_reconcile.py:255-282`](../../../../backend/workers/pr_reconcile.py#L255-L282) | `_poll_cron_kwargs` | scheduler | Default cadence `RELYLOOP_PR_POLL_MINUTES=5`. Whitelist set documented at [lines 239-241](../../../../backend/workers/pr_reconcile.py#L239-L241). |
| [`backend/tests/integration/test_proposal_repo_webhook.py`](../../../../backend/tests/integration/test_proposal_repo_webhook.py) | Integration tests for `list_pr_opened_proposals_for_reconcile` and `mark_proposal_pr_closed` | pytest | Existing assertions on 90-day window, ordering, and `pr_state` filter. |
| [`backend/tests/integration/test_pr_reconcile_config_repo_pointer.py`](../../../../backend/tests/integration/test_pr_reconcile_config_repo_pointer.py) | Reconciler integration tests with mocked GitHub | pytest | Existing case-(b) no-op assertion at lines 277-293. |

### Navigation and link impact

No UI changes. No URL references.

### Existing test impact

| Test file | Pattern | Count | Required change |
|---|---|---|---|
| `backend/tests/integration/test_proposal_repo_webhook.py` | `list_pr_opened_proposals_for_reconcile(db)` calls (lines 208, 222, 243) | 3 | Add a fourth assertion: rows with `pr_state='closed' AND last_polled_at > now() - interval '24 hours'` MUST be excluded. Existing assertions keep passing because seeded rows leave `last_polled_at` NULL. |
| `backend/tests/integration/test_pr_reconcile_config_repo_pointer.py` | `mark_proposal_pr_closed(db, pid)` and case-(b) no-op flow (lines 277-293) | 1 | Existing test still passes (single tick, no `last_polled_at` exclusion to trip). Add a new test that asserts the stamp is set when the reconciler observes case (b) for a `(pr_opened, closed)` candidate. |
| `backend/tests/integration/test_webhook_github.py` | `mark_proposal_pr_closed` | 1 | No change — webhook path doesn't stamp `last_polled_at`. |

### Existing behaviors affected by scope change

- **Reconciler tick cardinality for case-(b) rows.** Current: every tick (5-min default) issues one GitHub GET per stuck case-(b) row. New: at most one GitHub GET per stuck case-(b) row every 24 hours. Decision needed: no — locked.
- **Case-(a) recovery latency (first observation).** Current: detected on first successful poll after GitHub reports `merged=true, merged_at=<ts>`. New: unchanged for rows that have NEVER been observed as `(closed, not-merged)` — they keep `last_polled_at = NULL` so the exclusion doesn't fire. The stamp site is intentionally narrowed to the case-(b) branch (`state=closed AND merged=false`) to keep first-observation case-(a) recovery bounded by tick interval. See FR-2.
- **Case-(a) recovery latency (post-observation race).** Acknowledged trade-off: if the fallback-closed row is observed as `(merged=false, state=closed)` once and THEN GitHub flips to `merged=true` within 24 hours, the row is excluded from candidates until the 24-hour window expires. Worst-case recovery delay: 24 hours instead of one tick (~5 min). Decision needed: no — accepted per predicate idea §"Why deferred"; GitHub's `merged_at` typically populates within seconds of the merge event, so the race window is narrow in practice. See §11 flow 3 and §13 Reliability.
- **`(pr_opened, open)` candidate cardinality.** Current: every tick polls every `(pr_opened, open)` row newer than 90 days. New: unchanged — the exclusion only applies when `pr_state='closed'`. Decision needed: no.

---

## 3) Scope

### In scope
- Add nullable `proposals.last_polled_at` (TIMESTAMPTZ) column via Alembic migration `0017`.
- Update `list_pr_opened_proposals_for_reconcile` to exclude rows where `pr_state='closed' AND last_polled_at IS NOT NULL AND last_polled_at > now() - interval '24 hours'`.
- Update the reconciler's case-(b) branch ([`pr_reconcile.py:221`](../../../../backend/workers/pr_reconcile.py#L221)) to branch on the candidate's selection-time `pr_state` (per FR-2): candidates selected as `pr_state='open'` call `mark_proposal_pr_closed` (genuine close transition, no stamp on this tick); candidates selected as `pr_state='closed'` skip the close helper and call the new `stamp_proposal_last_polled_at` helper.
- Repo helper `stamp_proposal_last_polled_at(db, proposal_id)` — single-row UPDATE keyed on `Proposal.id AND status='pr_opened' AND pr_state='closed'` (defensive guard against mid-tick webhook-reopen). Returns `None` as a benign no-op when the guard mismatches. Caller commits.
- Tests at every layer the change touches: unit (column definition / model), integration (candidate query exclusion, reconciler stamp behavior), contract N/A (no API endpoint added).
- Migration round-trip verification per CLAUDE.md Rule #5.

### Out of scope
- **Tier B — terminal `pr_closed_unmerged` status enum or `is_closed_unmerged` boolean.** Deferred per predicate idea §"Tier B". Waits for a UX brief on the "closed without merge" surface.
- **Operator-tunable cadence.** The 24-hour interval is hard-coded in the SQL. If an operator hits a budget concern that requires sub-24h cadence, that's a follow-up (new `Settings` field + validation).
- **Backfill of `last_polled_at` for existing rows.** Migration adds the column as nullable with no default; existing rows have `last_polled_at = NULL` and will poll on the next tick — exactly the behavior we want (no skipped polls just because the migration ran).
- **Audit-event emission.** N/A — `audit_log` lands at MVP2 per [`data-model.md` §"Reserved for later releases"](../../../01_architecture/data-model.md). The reconciler is a system-internal scheduler, not a tenant-visible mutation site.
- **Frontend display of the field.** `last_polled_at` is a reconciler internal; no `/proposals` UI surface needs it.

### API convention check

Per [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md):

- **Endpoint prefix:** N/A — no new endpoints.
- **Router namespace:** N/A.
- **HTTP methods for CRUD:** N/A.
- **Non-auth error envelope:** N/A.
- **Auth error shape:** N/A (no auth surface through MVP3).

### Phase boundaries

Single phase. No deferred phase tracking needed.

## 4) Product principles and constraints

- **Bounded ongoing cost.** A reconciler that polls indefinitely against a stuck row violates the implicit GitHub-API-budget contract operators have when they enable the worker. One poll per stuck row per day keeps the cost ceiling sane.
- **Backwards compatible.** Migration is additive (nullable column, no default). Operators already running RelyLoop see no behavior change until their next reconciler tick observes a case-(b) row — at which point the row starts honoring the 24-hour exclusion.
- **Round-trip clean migration** per CLAUDE.md Absolute Rule #5.

### Anti-patterns

- **Do not** add `last_polled_at` to the case-(a) recovery branch (`merged=true AND merged_at is not None`). Case (a) is a terminal transition (`pr_opened+closed → pr_merged+merged`) — the row exits the candidate set on the same tick. Stamping `last_polled_at` there is wasted UPDATE traffic.
- **Do not** stamp `last_polled_at` on every successful GitHub poll regardless of outcome. The whole point is to short-circuit *only* the case-(b) no-op pattern; stamping on case-(a) recovery would delay merged-state detection by up to 24 hours if `merged_at` arrives via webhook in between.
- **Do not** add the column to the candidate query's SELECT list "for visibility" without using it. `Proposal` is already a wide row; the ORM-level addition is unavoidable but the candidate query MUST keep the WHERE clause narrow.
- **Do not** use server-side `func.now()` in the repo helper without timezone awareness — `proposals.created_at` is TIMESTAMPTZ via `DateTime(timezone=True)` so the new column matches.
- **Do not** rename or repurpose `mark_proposal_pr_closed`'s `pr_state='open'` guard. The guard is intentional (webhook-event idempotency from `feat_github_webhook`); the stamp is *additional* behavior that does not depend on the helper returning a row.
- **Do not** introduce `RELYLOOP_PR_RECONCILE_CASE_B_CADENCE_HOURS` (or any other tunable) in this PR. Lock the cadence at 24 hours; tuning is a follow-up if operator demand emerges.

## 5) Assumptions and dependencies

- **Predicate `bug_pr_reconciler_blocked_by_closed_fallback` (PR #204, merged 2026-05-23, commit `a0ca5b9`).** SATISFIED. Without it, `list_pr_opened_proposals_for_reconcile` would not return case-(b) rows at all and this work would be premature.
- **Postgres `TIMESTAMPTZ` + `now()` semantics.** Compose Postgres 16; the existing `proposals.created_at` already uses the same type pattern. No new dependency.
- **Alembic head `0016`.** New migration is `0017_proposals_last_polled_at`. Verified via `.venv/bin/alembic heads` returning `0016 (head)` on this branch's base.

## 6) Actors and roles

- Primary actor: the `reconcile_pr_state` Arq cron worker (system actor).
- Role model: N/A — single-tenant install, no auth surface (MVP1).
- Permission boundaries: N/A — system-internal scheduler.

### Authorization

N/A — single-tenant install, no auth surface (MVP1).

### Audit events

N/A — `audit_log` lands at MVP2.

---

## 7) Functional requirements

### FR-1: Add nullable `last_polled_at` column to `proposals`

- Requirement:
  - The migration **MUST** add `last_polled_at TIMESTAMPTZ NULL` to `proposals` via Alembic revision `0017`.
  - The migration **MUST** define a `downgrade()` that drops the column.
  - The migration **MUST** be idempotency-safe (caller invokes `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`).
  - The `Proposal` ORM model **MUST** declare `last_polled_at: Mapped[datetime | None]` via `mapped_column(DateTime(timezone=True), nullable=True)` matching the `pr_merged_at` precedent on the same table.
- Notes: No default. No backfill. Existing rows have `last_polled_at = NULL` post-migration, which is the desired starting state (they get polled on next tick).

### FR-2: Stamp `last_polled_at` in the reconciler's case-(b) branch, with branch-on-selection-pr_state

- Requirement:
  - When `reconcile_pr_state` observes `merged=false AND state="closed"` against a candidate, the worker **MUST** branch on the candidate's **selection-time** `pr_state`:
    - **Candidate selected as `pr_state='open'`** (the original case-b path that existed pre-predicate-bug-fix): call `mark_proposal_pr_closed(db, proposal.id)` (the existing transition `(pr_opened, open) → (pr_opened, closed)`) — this is the genuine close transition. **DO NOT** stamp `last_polled_at` on this tick — stamping is reserved for confirmed steady-state case-(b) rows. The next tick will re-observe the row as `(pr_opened, closed)` and stamp it via the path below.
    - **Candidate selected as `pr_state='closed'`** (the post-predicate-widened path — case b in its steady state): **DO NOT** call `mark_proposal_pr_closed` (avoids the documented webhook-reopen race in §11 edge flows). **DO** call `stamp_proposal_last_polled_at(db, proposal.id)` and treat its `None` return as a benign race no-op.
  - The stamp **MUST NOT** happen in the case-(a) recovery branch (`merged=true AND merged_at is not None`).
  - The stamp **MUST NOT** happen in the still-open branch (`state="open"`).
  - The stamp helper's UPDATE **MUST** include `WHERE status='pr_opened' AND pr_state='closed'` so that a concurrent webhook-driven transition (e.g., `pull_request.reopened` arriving mid-tick) cannot cause `last_polled_at` to be written onto a row that's no longer in the `(pr_opened, closed)` shape.
- Notes:
  - New repo helper `stamp_proposal_last_polled_at(db, proposal_id) -> Proposal | None` issues a single-row UPDATE keyed on `Proposal.id AND status='pr_opened' AND pr_state='closed'`. Returns `None` when the row no longer matches — treated as a benign race no-op by the caller. Helper calls `db.flush()`; caller commits inside the same `async with factory() as db: ... await db.commit()` block at [`pr_reconcile.py:222-224`](../../../../backend/workers/pr_reconcile.py#L222-L224).
  - **Race-safety rationale (selection-time branching).** Cycle-2 GPT-5.5 review surfaced a race: if the reconciler selected a row as `(pr_opened, closed)` and a `pull_request.reopened` webhook flipped the row to `(pr_opened, open)` between selection and the worker's branch, the original "always call `mark_proposal_pr_closed` in the closed branch" approach would clobber the operator's reopen (the helper's `WHERE ... pr_state='open'` would match the just-reopened row and re-close it). Branching on the candidate's selection-time `pr_state` (`proposal.pr_state`, already loaded into the ORM object) avoids the issue: case-(b) candidates that were *originally* `closed` skip the close helper entirely; case-(b) candidates that were *originally* `open` go through the legitimate close transition (the helper's `pr_state='open'` guard ensures it's a no-op if the row has since flipped). This also subsumes the predicate bug-fix's recovery semantics — the recovery branch (case-a) already has its own selection-time pr_state branch via `recovery_path = proposal.pr_state == "closed"` at [`pr_reconcile.py:179`](../../../../backend/workers/pr_reconcile.py#L179). The case-b branch will use the same pattern.

### FR-3: Exclude recently-polled case-(b) rows from candidate query

- Requirement:
  - `list_pr_opened_proposals_for_reconcile` **MUST** exclude rows where `pr_state = 'closed' AND last_polled_at IS NOT NULL AND last_polled_at > now() - interval '24 hours'`.
  - The 90-day window cutoff on `created_at` **MUST** remain unchanged.
  - The ordering (`ORDER BY created_at ASC`) **MUST** remain unchanged.
  - Rows with `pr_state='open'` **MUST NOT** be affected by the new exclusion (their `last_polled_at` is irrelevant).
- Notes: Use `or_` / explicit `not_` SQLAlchemy construct so the predicate reads cleanly. The new clause is `~(and_(Proposal.pr_state == "closed", Proposal.last_polled_at.is_not(None), Proposal.last_polled_at > <24h cutoff>))`. Compute the cutoff as `datetime.now(UTC) - timedelta(hours=24)` in Python, matching the existing 90-day cutoff style in the same function.

### FR-4: Reconciler summary observability

- Requirement:
  - The reconciler **SHOULD** continue emitting the existing `pr_reconcile_tick_complete` log line with `unchanged` counter incremented for case-(b) ticks (unchanged behavior).
  - The reconciler **SHOULD** emit a DEBUG-level log line `pr_reconcile_stamped_last_polled_at` with `proposal_id` when the stamp is applied, to aid operators debugging the cadence reduction in `pr-open-debugging.md`.
- Notes: No new metric; no INFO/WARN log addition. DEBUG-level is appropriate — stamping is a routine internal operation.

---

## 8) API and data contract baseline

### 8.1 Endpoint surface

N/A — no API surface added.

### 8.2 Contract rules

N/A.

### 8.3 Response examples

N/A.

### 8.4 Enumerated value contracts

N/A — no new enumerated field. The existing `pr_state IN ('open', 'closed', 'merged')` CHECK constraint (`proposals_pr_state_check` in [`backend/app/db/models/proposal.py:42-44`](../../../../backend/app/db/models/proposal.py#L42-L44)) is unchanged.

### 8.5 Error code catalog

N/A.

## 9) Data model and state transitions

### New/changed entities

**Modified table: `proposals`**
- Add `last_polled_at` (`TIMESTAMPTZ NULL`) — reconciler stamp recording the last time we observed `(merged=false, state=closed)` against a `(pr_opened, closed)` row. NULL means "never observed" (default for existing rows post-migration; default for new rows pre-PR-open and during the open lifecycle).

### Required invariants

- `last_polled_at` is **only** written by the reconciler's case-(b) branch via `stamp_proposal_last_polled_at`. The webhook receiver (`feat_github_webhook`) does NOT touch this column.
- The stamp UPDATE is guarded by `WHERE status='pr_opened' AND pr_state='closed'` (FR-2), so the column is only written when the row is in the `(pr_opened, closed)` shape at write time.
- `last_polled_at` is **best-effort monotonically non-decreasing** per row under MVP1's single-worker Arq deployment. Under hypothetical multi-worker operation, concurrent reconcilers could write older `now()` values after newer ones; the bounded skew is at most one tick interval (≤5 min default) and does not affect correctness of the 24-hour exclusion. Strict-monotonic enforcement (e.g., `GREATEST(last_polled_at, :ts)`) is deferred — not required at MVP1 scale.
- `last_polled_at` is meaningful only when `pr_state = 'closed' AND status = 'pr_opened'`. Reading the field for any other row is undefined (will always be NULL in practice given the FR-2 guard, but the schema does not enforce this).

### State transitions

No proposal-status state-machine change. The `last_polled_at` column is metadata on the existing `(pr_opened, closed)` resting state.

### Idempotency/replay behavior

Re-stamping `last_polled_at` is **operation-idempotent in effect** under MVP1 single-worker operation: repeated UPDATEs from sequential ticks advance the timestamp forward by ~24-hour buckets. It is NOT strictly idempotent in the data-contract sense (the value changes on each write), but the candidate query semantics (24-hour exclusion) make repeated writes outside the 24-hour window the expected behavior. The reconciler's existing 90-day window + new 24-hour exclusion combined cap the per-row stamp rate at ~90 stamps over the row's polling lifetime.

## 10) Security, privacy, and compliance

- Threats: none new. `last_polled_at` reveals when the reconciler last observed a row — already inferable from `pr_reconcile_tick_complete` logs.
- Controls: column is reconciler-internal; no API surface exposes it; no PII content.
- Secrets/key handling: unchanged.
- Auditability: N/A — pre-MVP2.
- Data retention/deletion/export impact: column is dropped with the row on hard-delete; no separate retention policy.

## 11) UX flows and edge cases

### Information architecture

No UI change. The 24-hour cadence is invisible to operators except via the GitHub API call cardinality in `pr_reconcile_tick_complete` log lines.

### Tooltips and contextual help

N/A — no UI change.

### Primary flows

1. **Operator closes a PR without merging it (webhook-first path).** Webhook delivers `pull_request.closed`; `mark_proposal_pr_closed` transitions the row to `(pr_opened, closed)`. Reconciler picks up the row on next tick — selection-time `pr_state='closed'` — polls GitHub, observes `merged=false, state=closed`. Per FR-2 branch-on-selection rule, the reconciler **skips** `mark_proposal_pr_closed` (avoids the webhook-reopen clobber race) and calls only `stamp_proposal_last_polled_at`, which writes `last_polled_at = now()` via its guarded UPDATE. Next tick (5 min later), `list_pr_opened_proposals_for_reconcile` excludes the row because `last_polled_at > now() - interval '24 hours'`. 24 hours later, the row re-enters the candidate set for one tick, gets re-stamped, and exits again. Continues until the row ages out of the 90-day window.

   **Variant — reconciler-first close (no webhook):** Webhook missed or delayed. Reconciler picks up the row on next tick as `(pr_opened, open)`, polls GitHub, observes `merged=false, state=closed`. Per FR-2 branch-on-selection rule, selection-time `pr_state='open'` → call `mark_proposal_pr_closed` (genuine close transition, returns the updated row). Do **not** stamp on this tick. Next tick selects the row as `(pr_opened, closed)` and falls into the steady-state pattern above.
2. **Operator re-opens the closed PR.** Webhook delivers `pull_request.reopened`; `mark_proposal_pr_reopened` transitions the row to `(pr_opened, open)`. `last_polled_at` is NOT cleared by `mark_proposal_pr_reopened` (intentional — see below). From that tick onward, the row is polled every tick because the exclusion only fires when `pr_state='closed'`.

   **Reopen-then-reclose-within-24h trade-off.** If the operator later closes the PR again *within 24 hours* of the previous stamp, the row returns to `(pr_opened, closed)` while `last_polled_at` still satisfies `> now() - 24h`. The candidate query excludes the row until the original 24-hour bucket expires (worst case ~22 hours after the second close). Reconciler polling is delayed by up to ~22 hours; the row is still correctly `(pr_opened, closed)` in the DB (the webhook handled the transition), so no state drift — only delayed re-confirmation polling. This is the same bounded-delay trade-off documented for case-(a) recovery in flow 3, and is accepted under the same rationale (24h is the worst-case ceiling; typical-case delay is small). Explicitly NOT clearing `last_polled_at` on reopen avoids a webhook-driven write to the column, keeping the column's write surface narrow (reconciler-only per §9 invariants).

   **AC-9-race remains correct under this trade-off** because it asserts the reconciler does not clobber the reopen — not that it polls the reclosed row immediately.
3. **Eventual-consistency case-(a) recovery.** The fallback-closed row has `pr_state='closed'` but GitHub still hasn't reported `merged=true`. First poll observes `merged=false, state=closed` → stamp set (the row is selection-time `pr_state='closed'`, so per FR-2 we call only `stamp_proposal_last_polled_at`). Within 24 hours, GitHub flips to `merged=true, merged_at=<ts>` — but the reconciler doesn't see it because the exclusion kicks in. **This is the trade-off:** case-(a) recovery latency for the narrow race where `(merged=false, closed)` was observed once before the merge flip increases from "next tick" (~5 min) to "next 24h-bucket tick" (~24 h, worst case). Mitigation: GitHub's `merged_at` typically populates within seconds of the merge event, well before the reconciler's first observation; the bug-fix that landed the recovery branch (`mark_proposal_pr_merged_from_closed`) targeted that narrow race. If the race happens AND the merged-state materializes between the first observation and the next case-(a) tick, recovery is delayed by up to 24 h. Acceptable per the predicate idea's cost analysis.

   **Why the case-(a) recovery branch still works post-FR-2:** when GitHub reports `merged=true, merged_at=<ts>`, the reconciler enters the `if merged and merged_at is not None:` branch at [`pr_reconcile.py:171`](../../../../backend/workers/pr_reconcile.py#L171), which already branches on `recovery_path = proposal.pr_state == 'closed'` ([line 179](../../../../backend/workers/pr_reconcile.py#L179)) and calls `mark_proposal_pr_merged_from_closed`. FR-2 only modifies the `state=closed` (non-merged) branch — recovery semantics are untouched.

### Edge/error flows

- **Stamp UPDATE fails (e.g., DB blip).** The existing `try/except` around the reconciler's per-candidate loop catches the exception and increments `errored`. The next tick re-attempts. No special handling needed.
- **Migration rollback in production.** `alembic downgrade -1` drops the column; the candidate query, having been deployed with the column reference, would 500. Mitigation: standard release ordering — code and migration ship together; rollback is unusual and operator-driven.

## 12) Given/When/Then acceptance criteria

### AC-1: Migration round-trips cleanly

- Given a database at Alembic head `0016`
- When `alembic upgrade head` runs (advancing to `0017`)
- Then `proposals.last_polled_at` exists as `TIMESTAMPTZ NULL`
- And running `alembic downgrade -1` removes the column
- And running `alembic upgrade head` again restores it
- Example values:
  - Pre-upgrade head: `0016`
  - Post-upgrade head: `0017`

### AC-2: Existing rows have `last_polled_at = NULL` post-migration

- Given proposals exist in the database at revision `0016` (any combination of `status`/`pr_state`)
- When the migration to `0017` runs
- Then every existing row has `last_polled_at IS NULL`
- Example: a `(pr_opened, closed)` row inserted before the migration polls on the next tick because its `last_polled_at IS NULL`.

### AC-3a: Reconciler stamps `last_polled_at` on steady-state case-(b) observation (selected as `pr_state='closed'`)

- Given a proposal in state `(status='pr_opened', pr_state='closed', last_polled_at=NULL)` and GitHub returning `{merged: false, state: 'closed'}` for its PR
- When `reconcile_pr_state` runs one tick
- Then the row's `last_polled_at` is set to a timestamp within the last 5 seconds (relative to test wall clock)
- And `mark_proposal_pr_closed` was NOT called (FR-2 branch-on-selection rule)
- And the reconciler summary shows `unchanged += 1`

### AC-3b: Reconciler performs the genuine close transition on first observation (selected as `pr_state='open'`)

- Given a proposal in state `(status='pr_opened', pr_state='open', last_polled_at=NULL)` and GitHub returning `{merged: false, state: 'closed'}` for its PR
- When `reconcile_pr_state` runs one tick
- Then `mark_proposal_pr_closed` was called and returned the updated row
- And the row's `pr_state` is now `'closed'`
- And the row's `last_polled_at` is still NULL (the stamp is reserved for the next tick, when the row is selected in steady-state case-b shape)
- And the reconciler summary shows `reconciled += 1`

### AC-4: Reconciler does NOT stamp `last_polled_at` on case-(a) recovery

- Given a proposal in state `(status='pr_opened', pr_state='closed', last_polled_at=NULL)` and GitHub returning `{merged: true, merged_at: '<ts>', state: 'closed'}`
- When `reconcile_pr_state` runs one tick
- Then the row transitions to `(status='pr_merged', pr_state='merged', pr_merged_at=<ts>, last_polled_at=NULL)`
- And the reconciler summary shows `reconciled += 1`

### AC-5: Reconciler does NOT stamp `last_polled_at` on still-open polls

- Given a proposal in state `(status='pr_opened', pr_state='open', last_polled_at=NULL)` and GitHub returning `{merged: false, state: 'open'}`
- When `reconcile_pr_state` runs one tick
- Then the row's `last_polled_at` remains `NULL`
- And the reconciler summary shows `unchanged += 1`

### AC-6: Candidate query excludes recently-stamped case-(b) rows

- Given a proposal in state `(status='pr_opened', pr_state='closed', last_polled_at=now() - 1 hour)`
- When `list_pr_opened_proposals_for_reconcile` runs
- Then the row is NOT in the returned list
- And the reconciler tick issues zero GitHub API calls for this proposal

### AC-7: Candidate query includes stamped rows older than 24 hours

- Given a proposal in state `(status='pr_opened', pr_state='closed', last_polled_at=now() - 25 hours)`
- When `list_pr_opened_proposals_for_reconcile` runs
- Then the row IS in the returned list
- And the reconciler re-stamps `last_polled_at` to `now()` after polling GitHub.

### AC-8: Candidate query NEVER excludes `pr_state='open'` rows

- Given a proposal in state `(status='pr_opened', pr_state='open', last_polled_at=now() - 1 hour)` — pathological state (the column should be NULL for open rows, but the test seeds it deliberately to prove the exclusion is gated on `pr_state='closed'`)
- When `list_pr_opened_proposals_for_reconcile` runs
- Then the row IS in the returned list
- And the reconciler polls GitHub for it.

### AC-9-race: Webhook reopens a candidate mid-tick → reconciler does not clobber the reopen

- Given a proposal selected by the reconciler as `(status='pr_opened', pr_state='closed', last_polled_at=NULL)`
- And before the reconciler's per-candidate branch runs, a `pull_request.reopened` webhook flips the DB row to `(pr_opened, open)` (simulated by the test mutating the DB between candidate selection and branch execution)
- And GitHub's `pulls/{n}` GET still returns `{merged: false, state: 'closed'}` (slightly stale relative to the webhook)
- When `reconcile_pr_state` proceeds with its case-(b) selection-time branch
- Then `mark_proposal_pr_closed` is NOT called (FR-2 branch-on-selection rule prevents the clobber)
- And the row remains `(pr_opened, open)` after the tick
- And `last_polled_at` is NULL (the stamp helper's `WHERE pr_state='closed'` guard prevents the write)
- And the reconciler summary shows `unchanged += 1` (the stamp helper returned `None` → benign no-op)

### AC-9-reclose: Reopen-then-reclose-within-24h stays excluded until the original 24h bucket expires

- Given a proposal at `(status='pr_opened', pr_state='closed', last_polled_at=now() - 1 hour)` (recently stamped by the reconciler)
- And the operator reopens the PR via webhook → `last_polled_at` unchanged, `pr_state='open'`
- And shortly after, the operator closes it again via webhook → `pr_state='closed'`, `last_polled_at` still ~1h old
- When `list_pr_opened_proposals_for_reconcile` runs
- Then the row is NOT in the returned list (it's still within the 24h exclusion window from the original stamp)
- And no reconciler poll fires for the row until ~23 hours later when the stamp ages out

### AC-10: Two sequential ticks 30 minutes apart against a case-(b) row → exactly one GitHub call

- Given a proposal in state `(status='pr_opened', pr_state='closed', last_polled_at=NULL)` and GitHub returning `{merged: false, state: 'closed'}`
- When `reconcile_pr_state` runs at t=0, then again at t=30 minutes (test-clock) — sequentially within the same worker process (MVP1 single-worker assumption)
- Then GitHub was called exactly once (on the t=0 tick)
- And `last_polled_at` is set to ~t=0
- And summary at t=0: `unchanged += 1`; summary at t=30min: `candidates = 0` (row excluded from candidate set)
- Note: "exactly once" is asserted under sequential ticks in the same test. Concurrent reconcilers across multi-worker deployments could issue duplicate calls within the 24-hour window; this is documented in §13 Reliability and is out of scope for MVP1.

## 13) Non-functional requirements

- **Performance.** New WHERE clause adds one comparison on a nullable timestamp column. No new index — the candidate query is already bounded by the 90-day `created_at` cutoff; case-(b) rows are a fraction of that population. If a deployment ever exceeds ~10K stuck case-(b) rows, revisit with a partial index `WHERE pr_state = 'closed' AND last_polled_at IS NOT NULL`. Not in scope for this PR.
- **Reliability.** The "at most once per 24 hours" guarantee is **best-effort under MVP1's single-worker Arq deployment** (`worker` service in `docker-compose.yml`). Multi-worker deployments are not supported in MVP1 and would introduce a race: two reconcilers could select the same eligible `(pr_opened, closed, last_polled_at=NULL or stale)` candidate before either commits its stamp, causing duplicate GitHub calls within the 24-hour window. Mitigation when MVP3+ multi-worker arrives: add `SELECT ... FOR UPDATE SKIP LOCKED` to `list_pr_opened_proposals_for_reconcile` or introduce a claim table. Out of scope here. Stamp UPDATE failure (e.g., DB connection blip) is handled by the existing `errored` counter path. The stamp's defensive guard (`WHERE status='pr_opened' AND pr_state='closed'`) makes the helper safe against the narrow race where a webhook flips the row between candidate selection and stamp time.
- **Operability.** `pr-open-debugging.md` runbook gains one sentence about the 24-hour exclusion behavior. Existing log lines (`pr_reconcile_tick_complete`) are sufficient for observability.
- **Accessibility/usability.** N/A — no UI change.

## 14) Test strategy requirements

- **Unit tests** (`backend/tests/unit/`): N/A — no pure-domain logic added (the 24-hour cutoff is a SQL expression, not a domain function).
- **Integration tests** (`backend/tests/integration/`):
  - `test_proposal_repo_last_polled_at.py` (new) — DB-backed: seed `(pr_opened, closed)` rows with varying `last_polled_at` (NULL, 1h ago, 25h ago) plus a `(pr_opened, open, last_polled_at=1h ago)` pathological row; assert candidate query returns the right subset. Covers AC-2, AC-6, AC-7, AC-8. Also covers `stamp_proposal_last_polled_at` helper directly: stamp succeeds against a `(pr_opened, closed)` row; stamp returns `None` against a `(pr_opened, open)` row (the defensive guard from FR-2).
  - `test_pr_reconcile_last_polled_at.py` (new) — DB-backed reconciler integration test with mocked GitHub. Four scenarios in this file:
    1. **Case-(b) stamp:** GitHub returns `{merged: false, state: 'closed'}` against a `(pr_opened, closed, last_polled_at=NULL)` seed row → assert `last_polled_at` is non-NULL after the tick (covers AC-3).
    2. **Case-(a) recovery no-stamp:** GitHub returns `{merged: true, merged_at: <ts>, state: 'closed'}` against a `(pr_opened, closed, last_polled_at=NULL)` seed row → assert row transitions to `pr_merged` AND `last_polled_at` is still NULL (covers AC-4).
    3. **Still-open no-stamp:** GitHub returns `{merged: false, state: 'open'}` against a `(pr_opened, open, last_polled_at=NULL)` seed row → assert `last_polled_at` remains NULL (covers AC-5).
    4. **Sequential two-tick cadence:** as AC-10 — two ticks 30 min apart against a case-(b) row produce exactly one mocked GitHub call.
    5. **Webhook-reopen mid-tick race:** as AC-9-race — assert no clobber + no stamp.
  - Extend `test_proposal_repo_webhook.py` — assert existing tests still pass with the new exclusion (rows seeded without `last_polled_at` keep showing up).
- **Contract tests** (`backend/tests/contract/`): N/A — no API endpoint added.
- **E2E tests** (`ui/tests/e2e/`): N/A — no UI surface.
- **Migration round-trip**: `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` runs cleanly in CI (verified via the existing migration-round-trip step in `pr.yml`).

## 15) Documentation update requirements

- `docs/01_architecture/`: `data-model.md` — add `last_polled_at` to the `proposals` table column listing with a one-sentence note about its role.
- `docs/02_product/`: move `chore_reconciler_terminal_closed_no_poll/` to `docs/00_overview/implemented_features/2026_05_23_chore_reconciler_terminal_closed_no_poll/` post-merge (finalization PR).
- `docs/03_runbooks/`: `pr-open-debugging.md` — append a one-sentence note: "Genuinely-closed-unmerged proposals are polled once per 24 hours via the `last_polled_at` exclusion in `list_pr_opened_proposals_for_reconcile` (see `chore_reconciler_terminal_closed_no_poll`)."
- `docs/04_security/`: N/A.
- `docs/05_quality/`: N/A.

## 16) Rollout and migration readiness

- **Feature flags / staged rollout.** None — schema change is additive and the new behavior activates immediately for case-(b) rows on first observation.
- **Migration/backfill expectations.** Migration `0017` adds the column nullable with no default. No backfill — existing rows have `last_polled_at IS NULL` which is the desired "never observed" state.
- **Operational readiness gates.** Updated runbook (FR-15) and a single new entry in `state.md` referencing the merged PR.
- **Release gate.** `pr.yml` green (lint, mypy, pytest unit/integration/contract, 80% coverage, Next.js build); migration round-trip step passes; Gemini adjudication done; GPT-5.5 final review.

## 17) Traceability matrix

| FR ID | Acceptance Criteria IDs | Planned stories/tasks | Test files/suites | Docs to update |
|---|---|---|---|---|
| FR-1 | AC-1, AC-2 | Story 1: migration `0017_proposals_last_polled_at` + ORM column | `migrations/versions/0017_proposals_last_polled_at.py`; new `test_proposal_repo_last_polled_at.py` | `docs/01_architecture/data-model.md` |
| FR-2 | AC-3a, AC-3b, AC-4, AC-5, AC-9-race | Story 3: reconciler stamp + branch-on-selection-pr_state + new repo helper `stamp_proposal_last_polled_at` with defensive guard | new `test_pr_reconcile_last_polled_at.py` (scenarios 1–3, 5) | — |
| FR-3 | AC-6, AC-7, AC-8, AC-9-reclose, AC-10 | Story 2: candidate query 24-h exclusion | new `test_proposal_repo_last_polled_at.py`; scenario 4 of new `test_pr_reconcile_last_polled_at.py`; extension to `test_proposal_repo_webhook.py` | — |
| FR-4 | (covered transitively in AC-3a by log capture) | Story 3 (same story as stamp) | new `test_pr_reconcile_last_polled_at.py` | `docs/03_runbooks/pr-open-debugging.md` |

## 18) Definition of feature done

- [ ] All acceptance criteria (AC-1 through AC-10, plus AC-9-race and AC-9-reclose) pass in CI.
- [ ] Migration round-trip step in CI is green.
- [ ] Integration tests cover the candidate query, the stamp behavior, and the two-tick cadence assertion.
- [ ] `data-model.md` `proposals` table listing mentions `last_polled_at`.
- [ ] `pr-open-debugging.md` mentions the 24-hour exclusion.
- [ ] PR has passed Gemini line-level adjudication AND final GPT-5.5 cross-model review.
- [ ] PR squash-merged on `main`; folder moved to `implemented_features/` in finalization PR.
- [ ] `state.md` updated.

## 19) Open questions and decision log

### Open questions

None. All forks locked at idea-preflight (Decision log below).

### Decision log

- **2026-05-23 — Tier A only, defer Tier B.** Per task brief: ship the cheap `last_polled_at` + exclusion now; the terminal-status enum / boolean (Tier B) waits for a UX brief on the "closed without merge" surface. Bundling Tier B would also require frontend `/proposals` display work (status badge variant, label) which is unscoped here.
- **2026-05-23 — Column name `last_polled_at` (not `pr_state_observed_at`).** Shorter; mirrors `pr_merged_at` precedent on the same table; the idea itself leads with this name.
- **2026-05-23 — 24-hour cadence hard-coded (no `Settings` knob).** Avoid premature configurability; if operators report budget concerns at sub-24h scale, a follow-up `Settings.relyloop_pr_reconcile_case_b_cadence_hours` is cheap to add later. CLAUDE.md "implement-over-defer" rubric: configurability adds tests + validator + docs; revert to YAGNI.
- **2026-05-23 — Stamp only in case-(b) branch (not on every successful poll).** Case-(a) recovery latency must stay bounded by tick interval, not the 24-hour exclusion window. The narrow stamp site is the minimum change that achieves the goal.
- **2026-05-23 — No backfill, no `server_default`.** Existing rows are `NULL` post-migration → they poll on next tick → they get stamped → they enter the 24-hour exclusion. Clean state machine, no migration-time computation.
- **2026-05-23 — No partial index on `last_polled_at`.** The candidate query is already bounded by the 90-day `created_at` cutoff; adding an index for a sub-population that the WHERE clause already prunes is premature. If operations show the query plan needs help at scale, add the partial index in a follow-up.
- **2026-05-23 — DEBUG-level log on stamp (`pr_reconcile_stamped_last_polled_at`), not INFO.** Stamping is a routine internal operation; INFO logs already capture the `unchanged` counter increment via `pr_reconcile_tick_complete`. Adding INFO per-row would inflate logs in the steady-state.
- **2026-05-23 — GPT-5.5 cross-model review (cycle 1) adjudication.** Reviewer surfaced 5 findings, all Accepted:
  - **F1 (High, Pass B) Accepted.** §1/§2/§11 case-(a) latency claims were internally inconsistent. Patched: §1 Outcome and §2 "Existing behaviors affected" now distinguish first-observation case-(a) (unchanged) from post-observation race case-(a) (up-to-24h delay, accepted trade-off). Matches §11 flow 3.
  - **F2 (Medium, Pass B) Accepted.** §14 originally cited only case-(b) stamp + cadence tests but claimed AC-4/AC-5 coverage. Patched: new `test_pr_reconcile_last_polled_at.py` enumerated with four explicit scenarios mapping 1:1 to AC-3/AC-4/AC-5/AC-9. Traceability matrix updated.
  - **F3 (Medium, Pass A) Accepted.** Strict monotonicity claim was overstated for concurrent-worker scenarios. Patched: §9 invariants now say "best-effort monotonic under MVP1 single-worker"; idempotency reframed as "operation-idempotent in effect" with note that the value changes.
  - **F4 (Medium, Pass B) Accepted.** "At most once per 24 hours" not strictly guaranteeable without advisory locking. Patched: §13 Reliability explicitly says best-effort under single-worker (MVP1 default); multi-worker mitigation (`FOR UPDATE SKIP LOCKED`) noted as out-of-scope; AC-9 Given/When says "sequentially within the same worker process" with explicit MVP1 single-worker note.
  - **F5 (Low, Pass A) Accepted.** Stamp helper needed defensive guard against webhook-driven race. Patched: FR-2 now requires `WHERE status='pr_opened' AND pr_state='closed'` on the helper's UPDATE; helper returns `Proposal | None`; `None` is benign no-op. New invariant added.
- **2026-05-23 — GPT-5.5 cycle 2 adjudication.** Reviewer surfaced one new finding (Medium, Pass A), Accepted:
  - **C2-F1 (Medium, Pass A) Accepted.** The cycle-1 defensive guard on `stamp_proposal_last_polled_at` did not address a separate race: `mark_proposal_pr_closed` could still clobber a webhook-reopened row in the case-b branch. Patched: FR-2 now requires **branch-on-selection-pr_state** in the reconciler's case-b path. Candidates selected as `(pr_opened, open)` go through the genuine close transition (`mark_proposal_pr_closed`); candidates selected as `(pr_opened, closed)` skip the close helper entirely and only stamp `last_polled_at`. Mirrors the predicate bug-fix's `recovery_path = proposal.pr_state == 'closed'` pattern in the case-a branch. New AC-3a/AC-3b split and AC-9-race added. Code complexity rises by ~5 LOC for the extra branch; race-safety value substantial.
- **2026-05-23 — GPT-5.5 cycle 3 adjudication.** Reviewer surfaced one new finding (Medium, Pass A), Accepted:
  - **C3-F1 (Medium, Pass A) Accepted.** §3 (in-scope bullets) and §11 (primary flow 1) still described the old "calls `mark_proposal_pr_closed` as a no-op AND `stamp_proposal_last_polled_at`" behavior, contradicting the cycle-2 FR-2 patch. An implementer following §11 verbatim could reintroduce the webhook-reopen clobber race. Patched: §3 in-scope bullet rewritten to mention selection-time branching; §11 flow 1 split into "webhook-first" (selected as closed → stamp only) and "reconciler-first close" (selected as open → close transition, no stamp) variants. §11 flow 3 cross-references the recovery branch's existing `recovery_path = proposal.pr_state == 'closed'` pattern to demonstrate the consistency.
- **2026-05-23 — GPT-5.5 cycle 4 adjudication.** Reviewer surfaced one new finding (Medium, Pass A), Accepted:
  - **C4-F1 (Medium, Pass A) Accepted.** §11 flow 2 (reopen path) claimed "if the operator closes again later, the next case-(b) observation re-stamps it" — incorrect if the reclose lands within 24h of the previous stamp. The row remains correctly `(pr_opened, closed)` per the webhook handlers, but reconciler re-polling is delayed by up to ~22 hours. This is the same bounded-delay trade-off as case-(a) recovery and is acceptable; the flow text was wrong. Patched: §11 flow 2 rewritten to explicitly document the reopen-reclose-within-24h trade-off; explicitly stated that `mark_proposal_pr_reopened` does NOT clear `last_polled_at` (preserves "reconciler-only write surface" invariant); new AC-9-reclose added. No code change required beyond the original FR-2 design — only doc + tests.
- **2026-05-23 — GPT-5.5 cycle 5.** Re-review after cycle-4 patches: clean pass. Convergence reached. Total: 8 findings across 4 cycles, all Accepted.
