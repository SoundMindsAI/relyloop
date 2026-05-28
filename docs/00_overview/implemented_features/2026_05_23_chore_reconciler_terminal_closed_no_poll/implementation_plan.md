# Implementation Plan — chore_reconciler_terminal_closed_no_poll (Tier A)

**Date:** 2026-05-23
**Status:** Complete (PR #216, merged 2026-05-23, squash SHA `95d4c414`)
**Primary spec:** [feature_spec.md](feature_spec.md)
**Policy source(s):** CLAUDE.md Absolute Rules (Rule #5: migration round-trip; Rule #10: no log/expose secrets)

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs.
- Three-story epic (schema → query → worker behavior). One PR.
- Migration round-trip verified before push (CLAUDE.md Rule #5).
- Tests at every layer the change touches: integration only (no API surface, no UI, no pure-domain logic).
- Branch-on-selection-pr_state rule in FR-2 is the load-bearing race-safety mechanism — guard with both unit-ish helper tests and a webhook-reopen-race integration test.

## 1) Scope traceability (FR → epics/phases)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (column + ORM) | Epic 1 / Story 1.1 | Migration `0017_proposals_last_polled_at` + `Proposal.last_polled_at` column |
| FR-2 (stamp + branch-on-selection) | Epic 1 / Story 1.3 | Worker case-(b) branch rewrite + new `stamp_proposal_last_polled_at` helper |
| FR-3 (candidate-query exclusion) | Epic 1 / Story 1.2 | `list_pr_opened_proposals_for_reconcile` 24-h exclusion clause |
| FR-4 (DEBUG observability log) | Epic 1 / Story 1.3 | Folded into Story 1.3 (same touch site) |

No deferred phases. Tier B is out-of-scope per [feature_spec.md §3 Out of scope](feature_spec.md#out-of-scope); tracked in [idea.md](idea.md) §"Tier B".

## 2) Delivery structure

**Epic → Story → Tasks → DoD** for all three stories.

### Conventions

- All repo functions take `db: AsyncSession` as first arg; use `await db.flush()` (caller commits).
- Stamp helper returns `Proposal | None`; `None` is a benign race no-op (FR-2 guard mismatch).
- Reconciler worker's case-(b) branch reads `proposal.pr_state` (already loaded into the ORM object at candidate selection time) to decide whether to call `mark_proposal_pr_closed` or `stamp_proposal_last_polled_at`.
- Migration revision is `0017` (next sequential after `0016`). Ships `downgrade()`; round-trip verified per CLAUDE.md Rule #5.
- No new env vars, no new Settings field, no new Compose service.
- No frontend changes.
- `__init__.py` exports updated via `__all__` (proposal repo).
- All timestamps `DateTime(timezone=True)` (TIMESTAMPTZ); cutoff computed as `datetime.now(UTC) - timedelta(hours=24)` matching the existing 90-day pattern at [`proposal.py:513`](../../../../backend/app/db/repo/proposal.py#L513).

### AI Agent Execution Protocol

0. Load context: read `CLAUDE.md`, `state.md`, `architecture.md`, the spec, and this plan.
1. Story 1.1 (migration + ORM column).
2. Story 1.2 (candidate-query exclusion + repo helper for stamp).
3. Story 1.3 (worker branch rewrite + DEBUG log).
4. Run `make test-integration` after each story; full `make lint && make typecheck && make test-unit && make test-integration && make test-contract` before pre-push gate.
5. Migration round-trip: `.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head` (Story 1.1 DoD).
6. Update docs (data-model.md, pr-open-debugging.md runbook) in the same PR.
7. Pre-push gate per `impl-execute` skill.

---

## Epic 1 — Stop polling genuinely-closed-unmerged proposals (Tier A)

### Story 1.1 — Add `proposals.last_polled_at` column

**Outcome:** `proposals` table has a nullable `last_polled_at TIMESTAMPTZ` column; `Proposal` ORM model exposes it; migration round-trips cleanly.

**New files**

| File | Purpose |
|---|---|
| `migrations/versions/0017_proposals_last_polled_at.py` | Alembic revision `0017` (down_revision `0016`). `upgrade()` adds nullable `TIMESTAMPTZ` column. `downgrade()` drops it. No backfill, no default, no index. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/models/proposal.py` | Add `last_polled_at: Mapped[datetime \| None] = mapped_column(DateTime(timezone=True), nullable=True)`. Docstring entry under "Two CHECK constraints" listing existing fields. Mirrors `pr_merged_at` column convention at `proposal.py:71`. |

**Endpoints**: N/A — no API surface.

**Key interfaces**

```python
# Migration 0017_proposals_last_polled_at.py
revision: str = "0017"
down_revision: str | None = "0016"

def upgrade() -> None:
    op.add_column(
        "proposals",
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
    )

def downgrade() -> None:
    op.drop_column("proposals", "last_polled_at")
```

```python
# backend/app/db/models/proposal.py — add after pr_open_error (line 73):
last_polled_at: Mapped[datetime | None] = mapped_column(
    DateTime(timezone=True), nullable=True
)
"""Reconciler stamp recording the last time we observed (merged=false,
state=closed) against a (pr_opened, closed) row. Used by the
list_pr_opened_proposals_for_reconcile 24h exclusion. Written ONLY by
stamp_proposal_last_polled_at — see chore_reconciler_terminal_closed_no_poll."""
```

**Pydantic schemas**: N/A.

**Tasks**

1. Create `migrations/versions/0017_proposals_last_polled_at.py` modelled on the structure of `0016_config_repos_last_merged_proposal_id.py` (copy revision header, module docstring style). No backfill, no index, no FK — just `add_column` / `drop_column`.
2. Edit `backend/app/db/models/proposal.py` to add `last_polled_at` mapped column after `pr_open_error` and before `rejected_reason`. Match the `pr_merged_at` precedent at `proposal.py:71` (same type, same nullability).
3. Run `.venv/bin/alembic upgrade head` against the shared Postgres in the worktree.
4. Run `.venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head` to verify round-trip.
5. Confirm via `.venv/bin/alembic heads` that head is `0017`.

**Definition of Done**

- [ ] Migration `0017` exists and round-trips cleanly (covers AC-1).
- [ ] `Proposal` ORM model declares `last_polled_at` matching `pr_merged_at` precedent.
- [ ] Integration test asserts existing rows post-upgrade have `last_polled_at IS NULL` (covers AC-2). Test lives in `backend/tests/integration/test_proposal_repo_last_polled_at.py` (introduced in Story 1.2).
- [ ] `make typecheck` green (mypy --strict on the new mapped column).
- [ ] `make lint` green.

---

### Story 1.2 — Candidate-query 24-hour exclusion + stamp helper

**Outcome:** `list_pr_opened_proposals_for_reconcile` excludes case-(b) rows stamped within the last 24 hours. New `stamp_proposal_last_polled_at` repo helper issues a defensively-guarded UPDATE.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_proposal_repo_last_polled_at.py` | DB-backed integration tests: candidate-query exclusion semantics (NULL / 1h / 25h cases including the pathological `(pr_opened, open, last_polled_at=1h)` row); `stamp_proposal_last_polled_at` helper direct calls (covers FR-2 guard via repo unit test); AC-9-reclose simulation (reopen-then-reclose within 24h stays excluded). |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/proposal.py` | (a) Add new helper `async def stamp_proposal_last_polled_at(db: AsyncSession, proposal_id: str) -> Proposal | None` at end of file before `list_pending_proposals_for_boot_scan`. (b) Modify `list_pr_opened_proposals_for_reconcile` to add the 24-hour exclusion clause. |
| `backend/app/db/repo/__init__.py` | Export `stamp_proposal_last_polled_at` via import block (line ~82, adjacent to `mark_proposal_pr_closed`) and add it to `__all__` (line ~218, adjacent to `"mark_proposal_pr_closed"`). |

**Endpoints**: N/A.

**Key interfaces**

```python
# backend/app/db/repo/proposal.py — additions

async def stamp_proposal_last_polled_at(
    db: AsyncSession,
    proposal_id: str,
) -> Proposal | None:
    """Defensively-guarded UPDATE stamping `last_polled_at = now()`.

    chore_reconciler_terminal_closed_no_poll FR-2. Single-row UPDATE
    keyed on ``id AND status='pr_opened' AND pr_state='closed'``.
    Returns ``None`` (benign no-op) when the row is no longer in the
    ``(pr_opened, closed)`` shape (e.g., a ``pull_request.reopened``
    webhook flipped the row between candidate selection and stamp
    time). Caller commits.
    """
    stmt = (
        update(Proposal)
        .where(
            Proposal.id == proposal_id,
            Proposal.status == "pr_opened",
            Proposal.pr_state == "closed",
        )
        .values(last_polled_at=datetime.now(UTC))
        .returning(Proposal)
    )
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is not None:
        await db.flush()
    return row


# backend/app/db/repo/proposal.py — modified list_pr_opened_proposals_for_reconcile

async def list_pr_opened_proposals_for_reconcile(
    db: AsyncSession,
) -> Sequence[Proposal]:
    """Return pr_opened proposals (open OR closed pr_state) newer than 90 days,
    excluding case-(b) rows polled within the last 24 hours.

    feat_github_webhook Story 1.4 / bug_pr_reconciler_blocked_by_closed_fallback /
    chore_reconciler_terminal_closed_no_poll FR-3.
    """
    now = datetime.now(UTC)
    cutoff_90d = now - timedelta(days=90)
    cutoff_24h = now - timedelta(hours=24)
    stmt = (
        select(Proposal)
        .where(
            Proposal.status == "pr_opened",
            Proposal.pr_url.is_not(None),
            Proposal.created_at > cutoff_90d,
            # FR-3: exclude case-(b) rows stamped within the last 24h.
            # pr_state='open' rows are unaffected (their last_polled_at
            # is irrelevant). pr_state='closed' rows with NULL
            # last_polled_at are included (never observed yet).
            ~and_(
                Proposal.pr_state == "closed",
                Proposal.last_polled_at.is_not(None),
                Proposal.last_polled_at > cutoff_24h,
            ),
        )
        .order_by(Proposal.created_at.asc())
    )
    return list((await db.execute(stmt)).scalars().all())
```

**Pydantic schemas**: N/A.

**Tasks**

1. Add `from sqlalchemy import and_` if not already imported. Inspect the existing imports at the top of `backend/app/db/repo/proposal.py` (already imports `select`, `update`); add `and_` only. Do NOT import `not_` — the implementation uses `~and_(...)` (negate via Python invert operator) for readability, and an unused `not_` import would fail `make lint`.
2. Add `stamp_proposal_last_polled_at` at the bottom of `backend/app/db/repo/proposal.py` (just before `list_pending_proposals_for_boot_scan` at line 526). Match the `mark_proposal_pr_closed` helper's structure (lines 421-447): conditional UPDATE with RETURNING, `db.flush()` only when row matches, caller commits.
3. Modify `list_pr_opened_proposals_for_reconcile` to compute both cutoffs (90d, 24h) from the same `now` value, and add the `~and_(...)` clause to the WHERE. Update the docstring to reflect FR-3.
4. Edit `backend/app/db/repo/__init__.py`: add `stamp_proposal_last_polled_at` to the import group from `.proposal` and to `__all__`. Verify both list orderings match the existing alphabetical/grouping convention.
5. Create `backend/tests/integration/test_proposal_repo_last_polled_at.py`. Test cases:
   - **`test_default_insert_leaves_last_polled_at_null`** — insert a `Proposal` row via the ORM (no explicit `last_polled_at` value). Assert the column reads back as `None`. This verifies the column's default-NULL behavior at the ORM/DB layer. **Note on AC-2 coverage:** The strict "rows that existed at revision 0016 keep `last_polled_at=NULL` after the migration runs" assertion is implicitly guaranteed by Alembic's `add_column(..., nullable=True)` with no `server_default` — there is no value Postgres could choose other than NULL. Story 1.1's `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` round-trip (AC-1) exercises the same code path against the shared Postgres which already contains pre-feature `proposals` rows from sibling branches. AC-2 is therefore covered by: (a) the migration round-trip succeeding without data loss, and (b) this ORM-level default test. No bespoke "insert at revision 0016 then upgrade" test is added — that would require contortions (testing migrations against a specifically-pinned alembic state) that the project's existing test infra doesn't support.
   - **`test_list_excludes_recently_stamped_closed_rows`** — seed `(pr_opened, closed, last_polled_at=now-1h)`; assert NOT in candidate set. Covers AC-6.
   - **`test_list_includes_stamped_rows_older_than_24h`** — seed `(pr_opened, closed, last_polled_at=now-25h)`; assert IN candidate set. Covers AC-7.
   - **`test_list_includes_closed_rows_with_null_last_polled_at`** — seed `(pr_opened, closed, last_polled_at=NULL)`; assert IN candidate set (never-observed case).
   - **`test_list_includes_open_rows_regardless_of_last_polled_at`** — seed `(pr_opened, open, last_polled_at=now-1h)` (pathological); assert IN candidate set. Covers AC-8.
   - **`test_stamp_proposal_last_polled_at_updates_closed_row`** — seed `(pr_opened, closed, last_polled_at=NULL)`; call helper; assert non-NULL.
   - **`test_stamp_proposal_last_polled_at_no_op_on_open_row`** — seed `(pr_opened, open, last_polled_at=NULL)`; call helper; assert returned `None` AND `last_polled_at` still NULL (covers FR-2 defensive guard).
   - **`test_stamp_proposal_last_polled_at_no_op_on_merged_row`** — seed `(pr_merged, merged, last_polled_at=NULL)`; call helper; assert returned `None` AND `last_polled_at` still NULL.
   - **`test_reopen_reclose_within_24h_stays_excluded`** — covers AC-9-reclose. Seed `(pr_opened, closed, last_polled_at=now-1h)`; mutate to `(pr_opened, open, last_polled_at=now-1h)` (simulating webhook reopen which doesn't clear the stamp); mutate back to `(pr_opened, closed, last_polled_at=now-1h)`; assert NOT in candidate set.

**Definition of Done**

- [ ] `stamp_proposal_last_polled_at` helper exists in `backend/app/db/repo/proposal.py` with the FR-2 defensive guard (`WHERE status='pr_opened' AND pr_state='closed'`).
- [ ] Helper exported via `backend/app/db/repo/__init__.py` `__all__`.
- [ ] `list_pr_opened_proposals_for_reconcile` excludes `(pr_state='closed', last_polled_at > now-24h)` rows.
- [ ] All 9 test cases in `test_proposal_repo_last_polled_at.py` pass via `make test-integration`.
- [ ] AC-2, AC-6, AC-7, AC-8, AC-9-reclose covered by integration tests.
- [ ] `make typecheck` and `make lint` green.

---

### Story 1.3 — Reconciler worker: branch on selection-time `pr_state` + stamp on case-(b)

**Outcome:** `reconcile_pr_state` worker's `elif state == "closed":` branch now branches on the candidate's selection-time `pr_state`. Open-selected → call `mark_proposal_pr_closed` (existing close transition). Closed-selected → skip the close helper, call `stamp_proposal_last_polled_at` only. DEBUG log emitted on stamp.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_pr_reconcile_last_polled_at.py` | DB-backed reconciler integration tests with mocked GitHub. Five scenarios mapping to AC-3a, AC-3b, AC-4, AC-5, AC-9-race, AC-10. |

**Modified files**

| File | Change |
|---|---|
| `backend/workers/pr_reconcile.py` | Rewrite the `elif state == "closed":` branch (current lines 221-228) to branch on `proposal.pr_state`. Open-selected: call `mark_proposal_pr_closed`. Closed-selected: skip close helper, call `stamp_proposal_last_polled_at`. Both paths increment the `unchanged`/`reconciled` counters per existing semantics; the stamp's `None` return increments `unchanged`. Add DEBUG log line `pr_reconcile_stamped_last_polled_at` on a successful stamp (FR-4). |
| `docs/01_architecture/data-model.md` | Add `last_polled_at` to the `proposals` table column listing with a one-sentence note about its reconciler-only write role. |
| `docs/03_runbooks/pr-open-debugging.md` | Append one sentence to the relevant reconciler section: "Genuinely-closed-unmerged proposals are polled at most once per 24 hours via the `last_polled_at` exclusion in `list_pr_opened_proposals_for_reconcile` (see `chore_reconciler_terminal_closed_no_poll`)." |

**Endpoints**: N/A.

**Key interfaces**

```python
# backend/workers/pr_reconcile.py — rewritten case-b branch (replaces current lines 221-228)

elif state == "closed":
    # chore_reconciler_terminal_closed_no_poll FR-2 — branch on selection-time
    # pr_state to avoid the webhook-reopen clobber race. Mirrors the case-a
    # recovery branch's `recovery_path = proposal.pr_state == "closed"` pattern
    # at line 179.
    selected_as_closed = proposal.pr_state == "closed"
    async with factory() as db:
        if selected_as_closed:
            # Steady-state case (b): don't re-close (would clobber a
            # concurrent webhook reopen). Only stamp the row to defer
            # the next poll by 24h.
            stamped = await repo.stamp_proposal_last_polled_at(db, proposal.id)
            await db.commit()
            if stamped is not None:
                logger.debug(
                    "pr_reconcile_stamped_last_polled_at",
                    proposal_id=proposal.id,
                )
            # Stamp success or benign race no-op both count as "unchanged"
            # (no proposal state-machine transition occurred this tick).
            summary["unchanged"] += 1
        else:
            # Selected as (pr_opened, open) but GitHub now reports closed:
            # genuine close transition. Existing pre-feature behavior.
            updated = await repo.mark_proposal_pr_closed(db, proposal.id)
            await db.commit()
            if updated is not None:
                summary["reconciled"] += 1
            else:
                summary["unchanged"] += 1
```

**Pydantic schemas**: N/A.

**Tasks**

1. Read the current `backend/workers/pr_reconcile.py` lines 165-235 to confirm the context around the case-(b) branch. The case-(a) recovery branch at lines 171-220 uses the `recovery_path = proposal.pr_state == "closed"` pattern at line 179 — mirror that style.
2. Rewrite the `elif state == "closed":` branch (lines 221-228) per the key-interfaces snippet above. Keep the existing summary counter semantics: stamp success or benign no-op both increment `unchanged`; the genuine close-transition path increments `reconciled` when a row was updated.
3. Verify the `_list_candidates()` helper at line 65-68 already returns ORM objects with `pr_state` populated (it does — it returns the full `Sequence[Proposal]` from `list_pr_opened_proposals_for_reconcile`). No change needed there.
4. Create `backend/tests/integration/test_pr_reconcile_last_polled_at.py`. Mock `github_request` (already imported by the worker at `backend/workers/pr_reconcile.py:38`); use the same fixture approach as `test_pr_reconcile_config_repo_pointer.py`. Five scenarios:
   - **Scenario 1 (AC-3a):** Seed `(pr_opened, closed, last_polled_at=NULL)` + config_repo + secret. Mock GitHub returning `{"merged": False, "state": "closed", "merged_at": None}`. Call `reconcile_pr_state(ctx)`. Assert `last_polled_at` is non-NULL post-tick AND `mark_proposal_pr_closed` was NOT called (use a `monkeypatch` spy on the repo function, or assert via the proposal's `pr_state` unchanged + a fresh-DB read showing only `last_polled_at` changed).
   - **Scenario 2 (AC-3b):** Seed `(pr_opened, open, last_polled_at=NULL)`. Mock GitHub returning `{"merged": False, "state": "closed", "merged_at": None}`. Assert post-tick the row is `(pr_opened, closed)` AND `last_polled_at` is still NULL.
   - **Scenario 3 (AC-4 — case-a recovery no-stamp):** Seed `(pr_opened, closed, last_polled_at=NULL)`. Mock GitHub returning `{"merged": True, "state": "closed", "merged_at": "2026-05-23T00:00:00Z"}`. Assert post-tick: `(pr_merged, merged, pr_merged_at=<ts>, last_polled_at=NULL)`. Confirm the existing recovery branch is untouched by FR-2.
   - **Scenario 4 (AC-5 — still-open no-stamp):** Seed `(pr_opened, open, last_polled_at=NULL)`. Mock GitHub returning `{"merged": False, "state": "open"}`. Assert post-tick: `(pr_opened, open, last_polled_at=NULL)` — no transition, no stamp.
   - **Scenario 5 (AC-10 — two sequential ticks):** Seed `(pr_opened, closed, last_polled_at=NULL)`. Mock GitHub returning `{"merged": False, "state": "closed"}`. Call `reconcile_pr_state` twice with 30 minutes simulated between (use `freezegun` or compare `last_polled_at` values; the second tick excludes the row from candidates). Assert the mocked GitHub function was called exactly once.
   - **Scenario 6 (AC-9-race — webhook reopen mid-tick):** Seed `(pr_opened, closed, last_polled_at=NULL)`. Inside the mocked `github_request`, mutate the DB to `(pr_opened, open)` before returning `{"merged": False, "state": "closed"}` (simulates webhook arriving during the network round-trip). Assert post-tick: `(pr_opened, open, last_polled_at=NULL)` — the stamp helper returned `None` due to the guard; the close helper was never called (open-selected path doesn't apply because selection-time pr_state was closed... wait, this needs an additional setup step). **Revised setup for Scenario 6:** seed `(pr_opened, closed, last_polled_at=NULL)` so the candidate is selected as closed. Inside the mocked `github_request` callback, run a synchronous DB UPDATE to flip the row to `(pr_opened, open)` before returning the mocked response. Then assert post-tick: `(pr_opened, open, last_polled_at=NULL)`. The stamp helper's `WHERE pr_state='closed'` guard returns `None`; the close helper is never called because we're on the closed-selected branch.
5. Edit `docs/01_architecture/data-model.md` — find the `proposals` table column listing (grep for `proposals` table description). Add a row for `last_polled_at` with the one-sentence note.
6. Edit `docs/03_runbooks/pr-open-debugging.md` — find the reconciler section (grep for "reconcile" or "pr_reconcile_tick"). Append the one sentence about the 24-hour exclusion behavior.

**Definition of Done**

- [ ] `backend/workers/pr_reconcile.py` case-(b) branch rewritten per FR-2; no clobber of webhook-reopened rows.
- [ ] DEBUG log `pr_reconcile_stamped_last_polled_at` emitted on successful stamp (FR-4).
- [ ] All 6 scenarios in `test_pr_reconcile_last_polled_at.py` pass via `make test-integration`.
- [ ] AC-3a, AC-3b, AC-4, AC-5, AC-9-race, AC-10 covered.
- [ ] `data-model.md` lists `last_polled_at` on the `proposals` table.
- [ ] `pr-open-debugging.md` mentions the 24-hour exclusion behavior.
- [ ] `make typecheck`, `make lint`, full `make test-unit && make test-integration && make test-contract` green.

---

## 3) Testing workstream

### 3.1 Unit tests

- Location: `backend/tests/unit/`
- Scope: N/A — no pure-domain logic added. The 24-hour cutoff is a SQL expression, not a domain function.
- DoD: Story 1.1 typecheck/lint covers the ORM column shape.

### 3.2 Integration tests

- Location: `backend/tests/integration/`
- Scope: DB-backed repo helpers (`stamp_proposal_last_polled_at`, modified `list_pr_opened_proposals_for_reconcile`) and worker behavior (`reconcile_pr_state`).
- Tasks:
  - [x] Create `test_proposal_repo_last_polled_at.py` with 9 test cases (Story 1.2 tasks step 5).
  - [x] Create `test_pr_reconcile_last_polled_at.py` with 6 scenarios (Story 1.3 tasks step 4).
  - [ ] Verify `test_proposal_repo_webhook.py` existing assertions still pass with the new exclusion clause (no edit needed; the new test file covers the regression risk).
  - [ ] Verify `test_pr_reconcile_config_repo_pointer.py` still passes — it does not use `last_polled_at` and its mocked GitHub responses match the new branch semantics.
- DoD: 15 new test cases pass; existing integration tests unaffected.

### 3.3 Contract tests

- Location: `backend/tests/contract/`
- Scope: N/A — no new API endpoint, no API contract change.
- DoD: existing contract tests unaffected.

### 3.4 E2E tests

- Location: `ui/tests/e2e/`
- Scope: N/A — no UI surface; reconciler is a worker, observable only via logs.
- DoD: existing E2E tests unaffected.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/integration/test_proposal_repo_webhook.py` | `list_pr_opened_proposals_for_reconcile(db)` calls (lines 208, 222, 243) | 3 | No change. Existing seeded rows leave `last_polled_at` NULL, which the new exclusion preserves in-list. |
| `backend/tests/integration/test_proposal_repo_webhook.py` | `mark_proposal_pr_closed(db, pid)` calls | several | No change. The helper signature is unchanged. |
| `backend/tests/integration/test_pr_reconcile_config_repo_pointer.py` | `mark_proposal_pr_closed(db, pid)` at lines 230, 293 | 2 | No change. These exercise the case-(b) no-op path via a `(pr_opened, open)`→`(pr_opened, closed)` transition that does not interact with the new branch logic (the test mocks GitHub on first call, not the new selection-time branch). |
| `backend/tests/integration/test_webhook_github.py` | `mark_proposal_pr_closed` at line 253 | 1 | No change. Webhook path is unaffected. |
| Other test files | `pr_reconcile`, `list_pr_opened_proposals_for_reconcile`, `mark_proposal_pr_closed` | — | Verified by grep: no other references to these symbols. |

### 3.6 Migration verification (Story 1.1 DoD)

- [ ] Alembic migration `0017` includes `downgrade()` that drops the column.
- [ ] `.venv/bin/alembic upgrade head` succeeds (head becomes `0017`).
- [ ] Round-trip: `.venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head` succeeds with no errors.
- [ ] No DB revision guard issues (the guard is MVP2+; not applicable here).

### 3.7 CI gates

- [ ] `make lint`
- [ ] `make typecheck`
- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] Docker build (relyloop/api) — `pr.yml` step
- [ ] UI lint + typecheck + vitest + Next.js build — unchanged but must stay green

---

## 4) Documentation update workstream

### 4.0 Core context files

- [ ] `state.md` — append a "Last updated" entry and a recent-changes line citing the PR number/SHA once merged. Bump Alembic head to `0017`. (Finalization PR.)
- [ ] `architecture.md` — no update needed; this is a tactical reconciler refinement, not an architectural change.
- [ ] `CLAUDE.md` — no update needed; no new convention added.

### 4.1 Architecture docs

- [ ] `docs/01_architecture/data-model.md` — add `last_polled_at` to the `proposals` table column listing (Story 1.3).

### 4.2 Product docs

- [ ] Move `docs/00_overview/planned_features/chore_reconciler_terminal_closed_no_poll/` → `docs/00_overview/implemented_features/2026_05_23_chore_reconciler_terminal_closed_no_poll/` in the finalization PR after the implementation PR squash-merges.

### 4.3 Runbooks

- [ ] `docs/03_runbooks/pr-open-debugging.md` — append the 24-hour exclusion note (Story 1.3).

### 4.4 Security docs

- [ ] No update needed. Column is reconciler-internal; no secret/key/PII change.

### 4.5 Quality docs

- [ ] No update needed. Test strategy (integration-only) is documented in this plan and the spec.

**Documentation DoD**

- [ ] `data-model.md` and `pr-open-debugging.md` updated in the implementation PR.
- [ ] `state.md` updated in the finalization PR after squash-merge (per CLAUDE.md "After completing a task, evaluate whether documentation needs updating").

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

- None. This is a tactical fix; the existing reconciler / repo / model layering is correct and the changes are additive.

### 5.2 Planned refactor tasks

- [ ] None.

### 5.3 Refactor guardrails

- [ ] Worker case-(a) recovery branch (line 171-220) MUST remain unchanged — FR-2 only modifies the case-(b) branch.
- [ ] Existing webhook handlers (`mark_proposal_pr_closed`, `mark_proposal_pr_reopened`) MUST NOT be modified to touch `last_polled_at` (FR-2 invariant: reconciler-only write surface).
- [ ] `__init__.py` `__all__` updated; no other repo helpers added.
- [ ] No new Settings field; no new Compose service.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `bug_pr_reconciler_blocked_by_closed_fallback` (PR #204) | All stories | Implemented (merged 2026-05-23, commit `a0ca5b9`) | The candidate query wouldn't include `(pr_opened, closed)` rows and this work would be moot. |
| Alembic at head `0016` | Story 1.1 | Verified (`.venv/bin/alembic heads` returns `0016 (head)`) | Would conflict with newer migrations from other branches. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| The branch-on-selection rule misses an edge case the spec didn't enumerate | Low | Medium | Six integration test scenarios covering the documented races (webhook-reopen mid-tick, reopen-reclose within 24h, case-a recovery via fallback-closed path). |
| Multi-worker race (concurrent reconcilers) issues duplicate GitHub calls within 24h | Low (MVP1 single-worker) | Low | Documented as out-of-scope in spec §13; advisory locking is MVP3+ infra. |
| 24-hour cadence chosen incorrectly for some deployment | Low | Low | Hard-coded per spec §19 decision log. Tunable Settings field is a documented follow-up. |
| Stamp UPDATE on a row that has transitioned terminal during the tick | Vanishingly low | Low | Defensive `WHERE` guard returns `None`; row remains unchanged. |
| Docs drift on `data-model.md` | Low | Low | Story 1.3 DoD requires the doc edit. Plan-finalization PR verifies. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Webhook reopen arrives during candidate selection→stamp window | Network delay / Arq dispatch latency | Selection-time `pr_state` branch skips `mark_proposal_pr_closed`; stamp helper's `WHERE pr_state='closed'` guard returns `None`; row remains `(pr_opened, open)` | None needed — benign. |
| Reopen-then-reclose within 24h of last stamp | Operator rapidly toggles PR state | Row excluded from candidates until original stamp ages out (up to ~22h delay) | Auto: next tick after 24h bucket expiration. |
| GitHub returns `merged=true` 24h+ after first case-(b) observation | Eventual-consistency case-(a) on a slow GitHub | Recovery via `mark_proposal_pr_merged_from_closed` happens up to 24h late instead of next-tick | Auto: bounded by exclusion window. Operator can manually trigger via reconciler debug runbook. |
| Stamp UPDATE fails (e.g., DB connection blip) | Postgres unavailability | Per-candidate `try/except` in reconciler increments `errored`; next tick re-attempts | Auto: next tick. |
| Migration applied but code rollback | Manual operator action | Old code doesn't read the new column; column lies unused. No data corruption. | Re-deploy correct code OR `alembic downgrade -1`. |
| Migration rollback (`downgrade()` runs) while code references column | Operator runs downgrade without re-deploying | Candidate query 500s on the missing column reference | Re-apply migration OR re-deploy old code. |

## 7) Sequencing and parallelization

### Suggested sequence

1. Story 1.1 — Migration + ORM column.
2. Story 1.2 — Candidate-query exclusion + stamp helper + repo integration tests.
3. Story 1.3 — Worker rewrite + reconciler integration tests + doc updates.

### Parallelization opportunities

Stories 1.2 and 1.3 cannot run in parallel because 1.3 depends on the helper from 1.2. Stories 1.2 and 1.3 could technically be merged into one story; kept separate so the helper unit-tests in 1.2 surface contract bugs before the worker integration.

## 8) Rollout and cutover plan

- **Rollout stages:** single environment (MVP1 local dev / shared CI Postgres). No remote staging in MVP1 per CLAUDE.md.
- **Feature flag strategy:** None. Schema change is additive; behavior activates on first case-(b) observation.
- **Migration/cutover steps:** standard PR → CI green → squash-merge → next `make migrate` on operator stacks applies `0017`. No backfill, no downtime, no manual intervention.
- **Reconciliation/repair strategy:** None needed. Existing rows have `last_polled_at = NULL` and behave identically until their next case-(b) observation.

## 9) Execution tracker

### Current sprint

- [ ] Story 1.1 — Migration + ORM
- [ ] Story 1.2 — Candidate query + stamp helper + repo tests
- [ ] Story 1.3 — Worker branch rewrite + reconciler tests + docs

### Blocked items

- None.

### Done this sprint

- (none yet)

## 10) Story-by-Story Verification Gate

For each story, before marking complete, attach:

- [ ] `New files` / `Modified files` tables verified against actual diff.
- [ ] Key interfaces implemented with matching signatures.
- [ ] All test scenarios in DoD pass via `make test-integration`.
- [ ] Migration round-trip command output (Story 1.1).
- [ ] `make lint && make typecheck` green.
- [ ] Doc updates (Story 1.3): `data-model.md` and `pr-open-debugging.md` diffs included in the PR.

## 11) Plan consistency review

| Check | Result |
|---|---|
| Spec ↔ plan FR coverage | All 4 FRs covered (FR-1→Story 1.1, FR-2→Story 1.3, FR-3→Story 1.2, FR-4→Story 1.3). |
| Spec ↔ plan endpoint count | Spec §8.1: 0 endpoints. Plan: 0 endpoints. Match. |
| Spec ↔ plan error code coverage | Spec §8.5: 0 error codes. Plan: 0 contract tests. Match. |
| Test file count | 2 new test files (`test_proposal_repo_last_polled_at.py`, `test_pr_reconcile_last_polled_at.py`); both assigned to their owning story (1.2, 1.3). No orphans. |
| AC coverage | AC-1 (migration round-trip) → Story 1.1; AC-2 (NULL post-migration) → Story 1.2 test 1; AC-3a/3b → Story 1.3 scenarios 1-2; AC-4 → Story 1.3 scenario 3; AC-5 → Story 1.3 scenario 4; AC-6/7/8 → Story 1.2 tests 2-5; AC-9-race → Story 1.3 scenario 6; AC-9-reclose → Story 1.2 test 9; AC-10 → Story 1.3 scenario 5. All 11 ACs (1, 2, 3a, 3b, 4, 5, 6, 7, 8, 9-race, 9-reclose, 10) covered. |
| Gate arithmetic | Epic gate "all 4 FRs implemented, 15 new test cases passing" matches story-level breakdown (9 repo tests + 6 worker scenarios = 15). |
| Open questions resolved | Spec §19: none open. All forks locked. |
| Frontend UI Guidance | N/A — no frontend changes (spec §3 confirms). |
| Legacy behavior parity table | N/A — no user-facing component >100 LOC deleted/migrated. Spec confirms no UI surface. |
| Enumerated value contract audit | N/A — no new enumerated field (spec §8.4 confirms). |
| Audit-event coverage | N/A — pre-MVP2 (spec §6 confirms). |
| Infrastructure paths | Verified: `migrations/versions/` (NOT `backend/alembic/versions/`); Alembic head is `0016` (confirmed via `.venv/bin/alembic heads`); next revision is `0017`. |
| Persistence scope | N/A — no client-side storage. |

## 12) Definition of plan done

- [x] Every FR (FR-1 through FR-4) is mapped to a story.
- [x] Every story includes New files, Modified files, Key interfaces, Tasks, and DoD.
- [x] Test layers explicitly scoped (integration-only; unit/contract/E2E N/A with justification).
- [x] Documentation updates planned (`data-model.md` + `pr-open-debugging.md` in implementation PR; `state.md` in finalization PR).
- [x] Lean refactor scope explicit (none; guardrails listed).
- [x] Plan consistency review (§11) performed; no unresolved findings.
- [x] Story-by-Story Verification Gate included.
- [x] No deferred phases (Tier B explicitly out of scope; tracked in idea.md).

## 13) Cross-model review log

- **Cycle 1 (GPT-5.5)** — 2 findings, both Accepted (Low severity):
  - **P1 (Low, Pass A) Accepted.** AC-2 was claimed to be covered by a "seed pre-migration row" test that's impossible to write with the project's existing test infra. Patched: Story 1.2 test renamed to `test_default_insert_leaves_last_polled_at_null` with explicit note that AC-2's strict pre-migration coverage is provided by Alembic's `add_column(nullable=True)` semantics combined with the round-trip step in Story 1.1's DoD.
  - **P2 (Low, Pass B) Accepted.** Story 1.2 task step 1 originally said to import `not_`. Implementation uses `~and_(...)` (Python invert) so `not_` would be unused and fail lint. Patched: import only `and_`.
- **Cycle 2 (GPT-5.5)** — 1 new finding (Medium, Pass A), **Rejected with cited counter-evidence**:
  - **P2-C1 Rejected.** Reviewer claimed the rewritten `list_pr_opened_proposals_for_reconcile` dropped an existing `pr_state` filter, broadening the candidate set. Counter-evidence: read `backend/app/db/repo/proposal.py:513-523` — the **current** helper does NOT filter on `pr_state`; it filters only on `status='pr_opened' AND pr_url IS NOT NULL AND created_at > cutoff_90d`. The query returns "both `pr_state='open'` and `pr_state='closed'`" as documented behavior, not as a query-level filter. The state machine (see `mark_proposal_pr_merged` at line 347, `mark_proposal_pr_merged_from_closed` at line 383) ensures `pr_state='merged'` always co-occurs with `status='pr_merged'`, so a hypothetical `(pr_opened, merged)` row cannot exist in practice. Adding `pr_state.in_(('open', 'closed'))` would be defense-in-depth but is not part of the FR-3 contract and would change a separate behavior outside this feature's scope.
- **Cycle 3 (GPT-5.5)** — clean pass; convergence reached.
