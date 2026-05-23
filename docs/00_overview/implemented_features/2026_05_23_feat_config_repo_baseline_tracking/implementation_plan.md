# Implementation Plan — Config Repo Baseline Tracking

**Date:** 2026-05-22
**Status:** Complete (PR #202, merged 2026-05-23)
**Primary spec:** [feature_spec.md](feature_spec.md)
**Policy source(s):** [CLAUDE.md](../../../../CLAUDE.md) absolute rules; [docs/01_architecture/api-conventions.md](../../../01_architecture/api-conventions.md); [docs/01_architecture/data-model.md](../../../01_architecture/data-model.md)

---

## 0) Planning principles

- Spec traceability first: every story/task maps to FR IDs in [feature_spec.md](feature_spec.md) §7.
- Sequential gates: Epic 1 (schema + DB writes) MUST finish before Epic 2 (API reads) starts — the reads depend on the writes being correct.
- Fail-loud tests: every test asserts explicit status / shape / error code / pointer state.
- Single PR: ~280 LOC backend, ~80 LOC frontend, 10 stories, single phase.

## 1) Scope traceability (FR → epics/stories)

| FR ID | Epic / Story | Notes |
|---|---|---|
| FR-1 (migration + ORM column + backfill) | Epic 1 / Story 1.1 | Alembic `0016_config_repos_last_merged_proposal_id`; ORM field on `ConfigRepo`; backfill SQL in `upgrade()`. |
| FR-2 (`update_config_repo_last_merged_pointer` repo helper) | Epic 1 / Story 1.2 | Row-locked `SELECT … FOR UPDATE`; strict-monotonic-timestamp guard. |
| FR-3 (webhook handler integration) | Epic 1 / Story 1.3 | Patch `webhooks/github.py:181-194` after the `mark_proposal_pr_merged` success. |
| FR-3a (PR reconciler integration) | Epic 1 / Story 1.4 | Patch `workers/pr_reconcile.py:170-180` symmetrically. |
| FR-4 (`ConfigRepoDetail.last_merged_proposal` field) | Epic 2 / Story 2.1 | New repo helper `get_config_repo_with_last_merged_proposal`; serializer extension. |
| FR-5 (`ProposalSummary.is_currently_live` field) | Epic 2 / Story 2.2 | Pointer-only derivation; new repo helper `find_currently_live_proposal_ids`. |
| FR-6 (`?is_last_merged=true\|false` filter) | Epic 2 / Story 2.3 | EXISTS / NOT EXISTS predicate; works alongside all existing filters. |
| FR-7 (`<CurrentlyLiveBadge>` on rows + detail) | Epic 3 / Story 3.1 | New shared component; tooltip-bearing pill. |
| FR-8 (glossary entries + InfoTooltip wiring) | Epic 3 / Story 3.2 | `proposal.currently_live` + `proposal.currently_live_filter`. |
| FR-9 (proposals page filter chip + empty state) | Epic 3 / Story 3.3 | Two-state chip; URL-state via `useDataTableUrlState`. |

No deferred phases — the spec ships in a single phase per [feature_spec.md §3 "Phase boundaries"](feature_spec.md). No `phaseN_idea.md` tracking artifact needed.

## 2) Delivery structure

Epic → Story → Tasks → DoD. Two backend epics (schema/writes, then API reads) followed by a frontend epic. Single phase.

### Conventions (RelyLoop-specific)

- All repo functions take `db: AsyncSession` as the first arg; use `await db.flush()` and let the caller commit.
- Services are async; the webhook receiver and reconciler are the callers in this feature (no new service module).
- Domain layer is pure — no DB access. This feature has no new domain logic (the pointer-update is repo-layer SQL, not domain).
- Models use `Mapped[]` typed columns with `String(36)` for UUIDv7 keys.
- Routers return typed Pydantic response models; errors use `HTTPException` with the standard `{detail:{error_code,message,retryable}}` envelope.
- Migrations use the existing `0NNN_<slug>` numbering and ship `downgrade()` per Absolute Rule #5.
- All `__init__.py` exports updated via `__all__` (repo, models — none for this feature since the model is modified, not new).
- Frontend: shadcn primitives + Tailwind 4; TanStack Query for server state; `useDataTableUrlState` for filter URL persistence.
- Glossary discipline: every tooltip routes through `<InfoTooltip glossaryKey="...">` (NOT inline strings) per `feat_contextual_help` precedent.

### AI Agent Execution Protocol

0. **Load context**: read [architecture.md](../../../../architecture.md), [state.md](../../../../state.md), [CLAUDE.md](../../../../CLAUDE.md). Note the current Alembic head is `0015_trials_per_query_metrics`; this feature's migration is `0016`.
1. **Read story scope**: outcome + endpoints + interfaces + DoD before writing code.
2. **Implement backend first**: model → migration → repo helpers → webhook patch → reconciler patch.
3. **Run backend tests** between each backend story (`make test-unit`, `make test-integration -k <name>`, `make test-contract -k <name>`).
4. **Implement API extensions** (Epic 2) once Epic 1 is green.
5. **Regenerate the frontend OpenAPI types** (`cd ui && pnpm types:gen`) before starting Epic 3 so `ConfigRepoDetail.last_merged_proposal` and `ProposalSummary.is_currently_live` flow through `ui/src/lib/types.ts`.
6. **Implement frontend** (Epic 3) — component → glossary keys → filter chip wiring.
7. **Run E2E** for the proposals-list badge end-to-end (real-backend Playwright).
8. **Verify migration round-trip** before opening the PR: `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`.
9. **Update docs**: `data-model.md` §"config_repos" gains the new column row; `webhook-debugging.md` gains the "Last-merged pointer" subsection.
10. **After the final story**: update `state.md` (new feature in the most-recent-changes section + Alembic head bump) and `architecture.md` (if no new architectural pattern emerges, skip).

Story completion is invalid if any step above is skipped.

---

## Epic 1 — Schema + DB writes (FR-1, FR-2, FR-3, FR-3a)

**Epic gate (hard stop before Epic 2):**
- [ ] `0016_config_repos_last_merged_proposal_id` migration round-trips cleanly.
- [ ] AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-15 pass.
- [ ] `update_config_repo_last_merged_pointer` repo helper integration tests green.
- [ ] Webhook receiver + reconciler both update the pointer in their respective paths.

### Story 1.1 — Alembic 0016 + ORM column + backfill (FR-1)

**Outcome:** `config_repos` table gains a `last_merged_proposal_id` column, FK to `proposals(id)` with `ON DELETE SET NULL`, partial index, and a backfill UPDATE that seeds the column from existing merged proposals.

**New files**

| File | Purpose |
|---|---|
| `migrations/versions/0016_config_repos_last_merged_proposal_id.py` | Alembic revision `0016` (Revises: `0015`). `upgrade()` adds the column + index + backfill; `downgrade()` drops the index then the column. Round-trip clean per Absolute Rule #5. |
| `backend/tests/integration/test_migration_0016.py` | AC-1 (round-trip introspection) + AC-2 (backfill correctness). |

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/models/config_repo.py` | Add `last_merged_proposal_id: Mapped[str \| None] = mapped_column(String(36), ForeignKey("proposals.id", ondelete="SET NULL"), nullable=True)` with docstring. NO `relationship()` declaration (rev-lookup is via JOIN, not eager-load — keeps the model file from importing `Proposal`). |

**Endpoints**

N/A (schema-only story).

**Key interfaces**

```python
# migrations/versions/0016_config_repos_last_merged_proposal_id.py

revision: str = "0016"
down_revision: str | None = "0015"

def upgrade() -> None:
    op.add_column(
        "config_repos",
        sa.Column(
            "last_merged_proposal_id",
            sa.String(length=36),
            sa.ForeignKey("proposals.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "config_repos_last_merged_proposal_id_idx",
        "config_repos",
        ["last_merged_proposal_id"],
        postgresql_where=sa.text("last_merged_proposal_id IS NOT NULL"),
    )
    # Backfill — single SQL UPDATE seeds the column from existing merged
    # proposals (FR-1, AC-2). pr_merged_at IS NOT NULL is defense-in-depth
    # per GPT-5.5 cycle-1 F3.
    op.execute("""
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
    """)

def downgrade() -> None:
    op.drop_index("config_repos_last_merged_proposal_id_idx", table_name="config_repos")
    op.drop_column("config_repos", "last_merged_proposal_id")
```

**Pydantic schemas**

N/A.

**Tasks**

1. Generate the revision file at `migrations/versions/0016_config_repos_last_merged_proposal_id.py` matching the structure of `0014_clusters_target_filter.py` (the closest prior precedent for a single-column add). Use `revision: str = "0016"` and `down_revision: str | None = "0015"`.
2. Implement `upgrade()` as the spec-locked SQL above.
3. Implement `downgrade()` to drop the index first then the column.
4. Add the ORM field to `backend/app/db/models/config_repo.py`.
5. Write `test_migration_0016.py`:
   - **AC-1** (round-trip from existing head): start at the prior head `0015_trials_per_query_metrics`. Run `alembic upgrade head` (advances to `0016`). Validate the column type via `pg_attribute` introspection, FK target + ON DELETE rule via `pg_constraint`, and partial index via `pg_indexes WHERE indexdef LIKE '%WHERE last_merged_proposal_id IS NOT NULL%'`. Then run `alembic downgrade -1` (back to `0015`); assert the column + index are gone. Then `alembic upgrade head` again; re-assert all three.
   - **AC-2**: at revision `0015` (BEFORE the migration runs), seed 2 `config_repos` (A, B), 3 `clusters` (cA1, cA2 wired to A; cB1 wired to B), 4 `proposals` (PA1 merged 2026-05-10; PA2 merged 2026-05-20; PB1 merged 2026-05-15; PA3 pending). **Important:** the test must seed with raw SQL via `Connection.execute(text(...))` or the pre-migration table reflection — NOT via the updated `ConfigRepo` ORM model (which already declares `last_merged_proposal_id` and would try to INSERT/SELECT a column that doesn't exist at 0015). Then run `alembic upgrade head` (advances to 0016, runs the backfill). Assert `config_repos.A.last_merged_proposal_id == PA2.id` and `config_repos.B.last_merged_proposal_id == PB1.id`.
6. Manually verify round-trip: `.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head` produces no errors.

**Definition of Done (DoD)**

- [ ] `test_migration_0016.py` AC-1 + AC-2 pass.
- [ ] Round-trip verified locally (`alembic upgrade head && alembic downgrade -1 && alembic upgrade head`).
- [ ] `state.md` Alembic head line will be updated in the Finalization step at the end of the plan (see §4.0 + the last item in §9 Execution tracker).
- [ ] No new error codes added (correct — this feature introduces none).

### Story 1.2 — Repo helpers: pointer update, batch derivation, detail join (FR-2, plus the read-side helpers consumed by 2.1 + 2.2)

**Outcome:** Three new repo functions in `backend/app/db/repo/config_repo.py` exposing the pointer write, the per-page batch derivation for `is_currently_live`, and the detail-page LEFT JOIN.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `backend/app/db/repo/config_repo.py` | Add three new async functions: `update_config_repo_last_merged_pointer`, `find_currently_live_proposal_ids`, `get_config_repo_with_last_merged_proposal`. |
| `backend/app/db/repo/__init__.py` | Add the three new functions to `__all__`. |
| `backend/tests/integration/test_config_repo_pointer_update_repo.py` (NEW) | Real-Postgres integration tests for the row lock + monotonic guard (AC-3..AC-5 logic isolation), plus the batch helper and the detail JOIN. |

Adding the new test file:

| File | Purpose |
|---|---|
| `backend/tests/integration/test_config_repo_pointer_update_repo.py` | Real-Postgres AsyncSession fixture; covers `update_config_repo_last_merged_pointer` (3 monotonic-guard branches + row-lock concurrency), `find_currently_live_proposal_ids` (positive + negative + cross-repo), `get_config_repo_with_last_merged_proposal` (NULL pointer + populated pointer + 404 case returning None). |

**Endpoints**

N/A (repo-layer story).

**Key interfaces**

```python
# backend/app/db/repo/config_repo.py

async def update_config_repo_last_merged_pointer(
    db: AsyncSession,
    *,
    config_repo_id: str,
    proposal_id: str,
    pr_merged_at: datetime,
) -> bool:
    """Conditionally update config_repos.last_merged_proposal_id.

    1. SELECT … FOR UPDATE on config_repos.id (serializes concurrent merges).
    2. If current pointer is NULL, write new pointer; return True.
    3. Else fetch tracked proposal's pr_merged_at; if pr_merged_at > current,
       write new pointer; return True.
    4. Else no-op; return False.

    Caller commits. Emits INFO `config_repo_last_merged_pointer_updated` on
    write, DEBUG `config_repo_last_merged_pointer_skipped_older` on no-op.
    """

async def find_currently_live_proposal_ids(
    db: AsyncSession,
    proposal_ids: Sequence[str],
) -> set[str]:
    """Return the subset of proposal_ids that appear as some config_repo's
    last_merged_proposal_id. Used by the proposals list/detail serializer to
    set `is_currently_live` on each row.

    SQL: SELECT cr.last_merged_proposal_id FROM config_repos cr
         WHERE cr.last_merged_proposal_id = ANY(:proposal_ids).
    """

async def get_config_repo_with_last_merged_proposal(
    db: AsyncSession,
    config_repo_id: str,
) -> tuple[ConfigRepo, Proposal | None, Cluster | None, QueryTemplate | None] | None:
    """Detail-endpoint helper. Returns None when the config_repo does not exist
    (router preserves the existing 404 CONFIG_REPO_NOT_FOUND envelope).
    Returns (config_repo, None, None, None) when the pointer is NULL.
    Returns the full embed tuple when the pointer is set.
    """
```

**Pydantic schemas**

N/A (repo layer).

**Tasks**

1. Implement `update_config_repo_last_merged_pointer` in `backend/app/db/repo/config_repo.py`. Use `select(ConfigRepo).where(...).with_for_update()` to acquire the row lock (mirrors the `backend/app/services/study_state.py:139` precedent). Compare timestamps in Python after fetching the tracked proposal's `pr_merged_at` via a second SELECT inside the same transaction. Emit structured logs via `structlog.get_logger(__name__)`.
2. Implement `find_currently_live_proposal_ids` using `select(ConfigRepo.last_merged_proposal_id).where(ConfigRepo.last_merged_proposal_id.in_(proposal_ids))`. Return a `set[str]`.
3. Implement `get_config_repo_with_last_merged_proposal`. When the pointer is set, LEFT JOIN to fetch the proposal, then the cluster and template (mirrors `_assemble_proposal_summary_batch` pattern; single round-trip preferred — use a single `select(ConfigRepo, Proposal, Cluster, QueryTemplate).outerjoin(...)` if it composes cleanly, otherwise fall back to two sequential fetches).
4. Export the three functions via `backend/app/db/repo/__init__.py` `__all__`.
5. Write `test_config_repo_pointer_update_repo.py`:
   - **`update_config_repo_last_merged_pointer`** — 3 monotonic-guard branches (NULL → write True; newer → write True; older → skip False); 1 same-timestamp no-op (False); 1 concurrent-merge serialization test via `asyncio.gather` of two transactions touching the same config_repo (asserts deterministic outcome: newer wins, no deadlock).
   - **`find_currently_live_proposal_ids`** — positive (set contains the live pid); negative (set excludes non-live pid); cross-repo (set includes live pids from multiple repos).
   - **`get_config_repo_with_last_merged_proposal`** — missing config_repo returns `None`; NULL pointer returns `(repo, None, None, None)`; populated pointer returns the full embed tuple with all 4 elements non-None.

**Definition of Done (DoD)**

- [ ] All 9+ test cases pass (`make test-integration -k test_config_repo_pointer_update_repo`).
- [ ] `update_config_repo_last_merged_pointer` emits the documented INFO + DEBUG log events with all required fields (verified via the existing `_log_helpers.py` `RecordingLogger` fixture).
- [ ] No regression on existing `config_repo` repo tests (`make test-integration -k test_config_repo`).

### Story 1.3 — Webhook handler integration (FR-3)

**Outcome:** After `mark_proposal_pr_merged` succeeds inside the GitHub webhook receiver, the receiver resolves the cluster's `config_repo_id` and calls `update_config_repo_last_merged_pointer` in the same transaction.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_webhook_config_repo_pointer.py` | Integration tests covering AC-3 (first merge sets pointer), AC-4 (out-of-order skip), AC-5 (duplicate webhook is no-op), AC-6 (NULL cluster.config_repo_id is skipped), AC-7 (concurrent merges serialize), AC-15 (test-only proposal hard-delete reverts FK). |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/webhooks/github.py` | Add ~12 LOC inside the `if decision.mutation == "merged":` branch, immediately after `mark_proposal_pr_merged` returns a non-None row. Resolve cluster, conditionally call `update_config_repo_last_merged_pointer`. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `POST` | `/webhooks/github` | (GitHub webhook payload — unchanged) | `200` `{ "status": "ok", "action": <wire_action> }` | `INVALID_SIGNATURE` (403, retryable=false) — unchanged. No new codes. |

**Key interfaces**

```python
# backend/app/api/webhooks/github.py — inside the merged branch (lines 181-194), after mark_proposal_pr_merged returns proposal_row (non-None):

if updated_proposal is not None:
    proposal_id = updated_proposal.id
    # NEW: maintain config_repos.last_merged_proposal_id pointer (FR-3).
    cluster = await repo.get_cluster(db, updated_proposal.cluster_id)
    if cluster is not None and cluster.config_repo_id is not None:
        await repo.update_config_repo_last_merged_pointer(
            db,
            config_repo_id=cluster.config_repo_id,
            proposal_id=proposal_id,
            pr_merged_at=decision.pr_merged_at,
        )
    else:
        logger.debug(
            "config_repo_last_merged_pointer_skipped_no_repo",
            proposal_id=proposal_id,
            cluster_id=updated_proposal.cluster_id,
        )
# Existing `await db.commit()` at line 197 unchanged — commits both writes atomically.
```

Note: the existing code structure at `github.py:181-194` will need a tiny refactor — `mark_proposal_pr_merged` currently doesn't bind the returned row to a name. Bind it as `updated_proposal = await repo.mark_proposal_pr_merged(...)` and key the new pointer-update logic on `updated_proposal is not None`.

**Pydantic schemas**

N/A (webhook receiver returns a plain `dict[str, str]`; existing shape).

**Tasks**

1. Refactor the webhook handler so `mark_proposal_pr_merged` returns the updated row (currently the return value is unused at line 190). Bind to `updated_proposal`.
2. Add the new pointer-update logic per the key-interfaces snippet above. Skip silently with DEBUG log when `cluster` is None (referential integrity should make this unreachable) OR `cluster.config_repo_id IS NULL`.
3. Verify the `mark_proposal_pr_closed` branch (line 188) is NOT touched — that branch handles the GitHub `merged_at=null` eventual-consistency fallback; per spec FR-3 + the cycle-2 decision-log entry, the pointer is NOT updated there.
4. Verify the duplicate-delivery path: when `mark_proposal_pr_merged` returns `None` (already-merged proposal), the pointer-update logic is skipped entirely (handled by the `if updated_proposal is not None:` gate).
5. Write `test_webhook_config_repo_pointer.py`:
   - **AC-3** (`test_webhook_first_merge_sets_pointer`): seed config_repo X, cluster wired to X, proposal P (`pr_opened+open`). Fire valid HMAC-signed webhook with `merged=true, merged_at=<ts>`. Assert all four AC-3 state-transition pieces: `config_repos.X.last_merged_proposal_id == P.id`, `proposals.P.status == 'pr_merged'`, `proposals.P.pr_state == 'merged'`, AND `proposals.P.pr_merged_at == <ts>` (exact equality on the webhook timestamp). Use the existing `_log_helpers.py` `RecordingLogger` fixture to assert one INFO `config_repo_last_merged_pointer_updated` event.
   - **AC-4** (`test_webhook_out_of_order_does_not_regress`): seed config_repo X already pointing at P2 (pr_merged_at=t2). Seed P1 wired to X, `pr_opened+open`, fire webhook for P1 with `merged_at=t1 < t2`. Assert pointer remains P2 AND `proposals.P1.status == 'pr_merged'`. Assert one DEBUG `config_repo_last_merged_pointer_skipped_older` event.
   - **AC-5** (`test_webhook_duplicate_delivery_is_noop`): seed P merged via webhook (pointer set). Monkeypatch `repo.update_config_repo_last_merged_pointer` with a `unittest.mock.AsyncMock` spy. Fire identical webhook again. Assert pointer unchanged AND `update_config_repo_last_merged_pointer.call_count == 0` (the duplicate-delivery path does NOT invoke the pointer helper because `mark_proposal_pr_merged` returned `None`). Spy-based assertion is more reliable than log absence (which can flake on log-level configuration changes).
   - **AC-6** (`test_webhook_null_cluster_config_repo_id_skipped`): seed P whose cluster has `config_repo_id IS NULL`. Fire webhook. Assert proposal transitions to `pr_merged` AND no INFO log AND one DEBUG `config_repo_last_merged_pointer_skipped_no_repo` event.
   - **AC-7** (`test_webhook_concurrent_merges_serialize`): seed two proposals P_A (intended merged_at=t1), P_B (intended merged_at=t2 where t2 > t1) wired to the same config_repo X. Fire two parallel webhooks via `asyncio.gather` against separate AsyncSessions. Assert deterministic outcome: pointer = P_B; both proposals merged; no deadlocks (test runs 20 iterations).
   - **AC-15** (`test_proposal_hard_delete_reverts_pointer`): seed P merged + pointer set. Drive the delete via the test-only HTTP endpoint per spec AC-15: `await async_client.delete(f"/api/v1/_test/proposals/{P.id}")`; assert HTTP 200/204 (the endpoint's documented success shape). Then assert `config_repos.X.last_merged_proposal_id IS NULL` (ON DELETE SET NULL took effect via the FK). This exercises both the test-endpoint contract AND the FK cascade in one assertion path.

**Definition of Done (DoD)**

- [ ] All 6 integration test cases pass.
- [ ] Webhook receiver code follows the standard error envelope (no new codes; existing `INVALID_SIGNATURE` unchanged).
- [ ] `make test-integration -k test_webhook` passes (full webhook suite — no regression on existing 19KB of webhook tests).
- [ ] Smoke check: manual `curl` of `/webhooks/github` with a valid HMAC body still returns 200.

### Story 1.4 — PR reconciler integration (FR-3a)

**Outcome:** The `pr_reconcile.py` worker, after `mark_proposal_pr_merged` succeeds for a proposal it catches up on, calls `update_config_repo_last_merged_pointer` symmetrically with the webhook handler.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_pr_reconcile_config_repo_pointer.py` | FR-3a happy path + negative documentation test for the known reconciler limitation. |

**Modified files**

| File | Change |
|---|---|
| `backend/workers/pr_reconcile.py` | Add ~10 LOC inside the `if merged and merged_at is not None:` branch (line 171), after `mark_proposal_pr_merged` returns a non-None row. Resolve cluster, conditionally call `update_config_repo_last_merged_pointer`. |

**Endpoints**

N/A (worker job, no HTTP surface).

**Key interfaces**

```python
# backend/workers/pr_reconcile.py — inside the merged branch (lines 171-180), after updated := mark_proposal_pr_merged returns non-None:

if merged and merged_at is not None:
    async with factory() as db:
        updated = await repo.mark_proposal_pr_merged(
            db, proposal.id, pr_merged_at=merged_at
        )
        if updated is not None:
            # NEW: maintain config_repos.last_merged_proposal_id pointer (FR-3a).
            cluster = await repo.get_cluster(db, proposal.cluster_id)
            if cluster is not None and cluster.config_repo_id is not None:
                await repo.update_config_repo_last_merged_pointer(
                    db,
                    config_repo_id=cluster.config_repo_id,
                    proposal_id=proposal.id,
                    pr_merged_at=merged_at,
                )
            else:
                logger.debug(
                    "config_repo_last_merged_pointer_skipped_no_repo",
                    proposal_id=proposal.id,
                    cluster_id=proposal.cluster_id,
                )
        await db.commit()
    if updated is not None:
        summary["reconciled"] += 1
    else:
        summary["unchanged"] += 1
```

**Pydantic schemas**

N/A.

**Tasks**

1. Patch `backend/workers/pr_reconcile.py:170-180` per the snippet above. Preserve the existing `summary["reconciled"]` / `summary["unchanged"]` counter logic.
2. Write `test_pr_reconcile_config_repo_pointer.py`:
   - **FR-3a happy path** (`test_reconciler_observes_missed_merge_updates_pointer`): seed config_repo X, cluster wired to X, proposal P (`pr_opened+open`, simulating a webhook that never arrived). Mock `httpx.AsyncClient.get` to return `{merged: true, merged_at: <ts>, state: "closed"}` for P's PR URL. Run one `tick()` of `reconcile_pr_state`. Assert `config_repos.X.last_merged_proposal_id == P.id` AND `proposals.P.status == 'pr_merged'`. Assert one INFO `config_repo_last_merged_pointer_updated` event.
   - **Negative documentation test** (`test_reconciler_does_not_recover_fallback_closed_proposal`): seed config_repo X, cluster wired, proposal P in `(pr_opened, closed)` state (simulating the webhook fallback closed it). Mock `httpx.AsyncClient.get` to return `{merged: true, merged_at: <ts>}`. Run `tick()`. Assert pointer remains UNSET (NULL) — `mark_proposal_pr_merged` returned None because `pr_state='closed'`. Include a docstring linking to [`bug_pr_reconciler_blocked_by_closed_fallback`](../bug_pr_reconciler_blocked_by_closed_fallback/idea.md) so future readers understand this is a documented limitation, not a regression.

**Definition of Done (DoD)**

- [ ] Both integration tests pass.
- [ ] Existing `backend/tests/integration/test_pr_reconcile*.py` suite (if any) regression-clean.
- [ ] Linked bug idea file [`bug_pr_reconciler_blocked_by_closed_fallback/idea.md`](../bug_pr_reconciler_blocked_by_closed_fallback/idea.md) referenced in the negative-test docstring.

---

## Epic 2 — API extensions (FR-4, FR-5, FR-6)

**Epic gate (hard stop before Epic 3):**
- [ ] AC-8, AC-9, AC-10, AC-11, AC-12, AC-14 pass.
- [ ] OpenAPI schema regeneration produces no breaking changes (only additive fields).
- [ ] `cd ui && pnpm types:gen` produces a new `ui/src/lib/types.ts` with the two new optional fields.

### Story 2.1 — `ConfigRepoDetail.last_merged_proposal` field + `ProposalSummary.is_currently_live` schema (FR-4 + FR-5 schema half)

**Outcome:** `GET /api/v1/config-repos/{id}` response embeds the pointed-to `ProposalSummary` when the pointer is set. List response also includes the field (always `null` on list rows — by design, no JOIN performed on list). To make the embed valid, the `ProposalSummary.is_currently_live` field is **also added in this story** (the bare schema field, default `False`). Story 2.2 then implements the per-row derivation in `_assemble_proposal_summary_batch`. Splitting the schema add from the derivation lets 2.1 land independently without forcing 2.2 to ship first.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_config_repo_detail_last_merged.py` | AC-8 (detail endpoint embeds the proposal summary; embed-side `is_currently_live=true` even on cluster rotation). |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/schemas.py` | Add `last_merged_proposal: ProposalSummary \| None = None` to `ConfigRepoDetail` (line 1081). **Also add `is_currently_live: bool = False` to `ProposalSummary` (line 986) AND `ProposalDetail` (line 1000)** — bare schema field only; Story 2.2 implements per-row derivation. |
| `backend/app/api/v1/config_repos.py` | Replace `_to_detail()` callers in the detail endpoint with a path that uses `get_config_repo_with_last_merged_proposal`. Assemble the embedded `ProposalSummary` with `is_currently_live=True` directly (NOT via the generic batch helper — see FR-4 + cycle-2 F12). List endpoint keeps `_to_detail()` as-is; the new field defaults to `None`. |
| `backend/tests/contract/test_github_pr_worker_api_contract.py` | Add an OpenAPI schema assertion that `ConfigRepoDetail.last_merged_proposal` is present as `ProposalSummary \| null`. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/config-repos/{config_repo_id}` | — | `200` — `ConfigRepoDetail` shape with `last_merged_proposal: ProposalSummary \| null`. Embedded summary's `is_currently_live` is `true` when populated. | `CONFIG_REPO_NOT_FOUND` (404) — unchanged. |
| `GET` | `/api/v1/config-repos` | — | `200` — paginated list. Every row's `last_merged_proposal` is `null` (additive field; population deferred to detail endpoint). | None changed. |

**Key interfaces**

```python
# backend/app/api/v1/schemas.py (line ~1081)

class ConfigRepoDetail(BaseModel):
    # ... existing fields unchanged ...
    last_merged_proposal: ProposalSummary | None = None
    """The proposal currently tracked as the live config for this repo
    (config_repos.last_merged_proposal_id). NULL when no merge has occurred
    yet. Always present in detail responses; always NULL in list responses
    (the list endpoint does not perform the JOIN — by design)."""
```

```python
# backend/app/api/v1/config_repos.py — extend the detail endpoint

@router.get("/config-repos/{config_repo_id}", response_model=ConfigRepoDetail, tags=["config-repos"])
async def get_config_repo_endpoint(
    config_repo_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConfigRepoDetail:
    result = await repo.get_config_repo_with_last_merged_proposal(db, config_repo_id)
    if result is None:
        raise _err(404, "CONFIG_REPO_NOT_FOUND", f"config_repo {config_repo_id} not found", False)
    config_repo, proposal, cluster, template = result
    detail = _to_detail(config_repo)
    if proposal is not None and cluster is not None and template is not None:
        detail.last_merged_proposal = ProposalSummary(
            id=proposal.id,
            study_id=proposal.study_id,
            cluster=_ClusterEmbed(
                id=cluster.id, name=cluster.name,
                engine_type=cluster.engine_type, environment=cluster.environment,
            ),
            template=_TemplateEmbed(
                id=template.id, name=template.name,
                version=template.version, engine_type=template.engine_type,
            ),
            status=proposal.status,
            pr_state=proposal.pr_state,
            pr_url=proposal.pr_url,
            metric_delta=proposal.metric_delta,
            is_currently_live=True,  # Embed-side context: this IS the pointer target.
            created_at=proposal.created_at,
        )
    return detail
```

**Pydantic schemas**

See above — `ConfigRepoDetail` gains one field.

**Tasks**

1. Add `last_merged_proposal: ProposalSummary | None = None` to `ConfigRepoDetail` in `schemas.py`. Pydantic v2's default-`None` makes this a forward-compatible additive field.
2. Update the detail endpoint at `config_repos.py:259-277` to use the new repo helper. List endpoint at `config_repos.py:226-251` is unchanged — `_to_detail()` produces `last_merged_proposal=None` by default.
3. Update `_to_detail()` if needed — current version at lines 93–106 doesn't reference the new field, so it naturally produces `None` from the Pydantic default. NO CHANGE required.
4. Write `test_config_repo_detail_last_merged.py`:
   - **AC-8** (`test_detail_endpoint_embeds_last_merged_proposal`): seed config_repo X with a merged proposal P (pointer set). `GET /api/v1/config-repos/X.id`. Assert response shape: `last_merged_proposal.id == P.id`, `status == 'pr_merged'`, `is_currently_live == True`.
   - **AC-8 null case** (`test_detail_endpoint_null_pointer`): seed config_repo Y with no merged proposals. `GET /api/v1/config-repos/Y.id`. Assert `last_merged_proposal is None`.
   - **AC-8 rotation case** (`test_detail_endpoint_embed_is_currently_live_even_after_cluster_rotation`): seed config_repo X pointing at P. Then SET `clusters.config_repo_id = NULL` for P's cluster (simulating rotation). `GET /api/v1/config-repos/X.id`. Assert `last_merged_proposal.is_currently_live == True` (embed-side derivation uses pointer context, not generic JOIN).
5. Add the contract test assertion in `test_github_pr_worker_api_contract.py`: after the existing OpenAPI schema introspection at lines 124, 148, add an assertion that `ConfigRepoDetail.properties.last_merged_proposal` has `oneOf: [{$ref: "#/components/schemas/ProposalSummary"}, {type: "null"}]` (or the Pydantic v2 equivalent).

**Definition of Done (DoD)**

- [ ] 3 integration test cases pass.
- [ ] Contract test asserts the OpenAPI schema includes the new field.
- [ ] `cd ui && pnpm types:gen` (manual command in the implementer's workflow) regenerates `ui/src/lib/types.ts` with `last_merged_proposal` on `ConfigRepoDetail`.
- [ ] No regression on existing config-repos contract tests (lines 124, 148 still assert the rest of the shape).

### Story 2.2 — `ProposalSummary.is_currently_live` derivation (FR-5)

**Outcome:** Every proposal serialized via `/api/v1/proposals` list or detail endpoints carries an `is_currently_live: bool` derived from the pointer-only EXISTS check. The schema fields are already in place (Story 2.1 added them); this story implements the per-row derivation.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/proposals.py` | Extend `_assemble_proposal_summary_batch()` to call `repo.find_currently_live_proposal_ids` once per page and set `is_currently_live=True` on matching rows. Extend `_assemble_proposal_detail()` similarly (single proposal id → set). |
| `backend/tests/contract/test_digest_proposal_api_contract.py` | Add OpenAPI schema assertions that `ProposalSummary.is_currently_live` and `ProposalDetail.is_currently_live` are present as `bool` (default false). |

**Endpoints**

(Unchanged endpoint surfaces; serializer outputs gain one field each.)

**Key interfaces**

```python
# backend/app/api/v1/schemas.py

class ProposalSummary(BaseModel):
    # ... existing fields unchanged ...
    is_currently_live: bool = False
    """True when this proposal is some config_repo's last_merged_proposal_id
    (FR-5). Pointer-only derivation — symmetric with ?is_last_merged=true."""

class ProposalDetail(BaseModel):
    # ... existing fields unchanged ...
    is_currently_live: bool = False
```

```python
# backend/app/api/v1/proposals.py

async def _assemble_proposal_summary_batch(
    db: AsyncSession, proposals: list[Proposal]
) -> list[ProposalSummary]:
    # ... existing cluster/template batch-fetch unchanged ...

    # NEW: pointer-only derivation of is_currently_live (FR-5).
    proposal_ids = [p.id for p in proposals]
    live_ids = await repo.find_currently_live_proposal_ids(db, proposal_ids)

    out: list[ProposalSummary] = []
    for p in proposals:
        # ... existing assembly ...
        out.append(
            ProposalSummary(
                # ... existing fields ...
                is_currently_live=p.id in live_ids,
                # ... created_at ...
            )
        )
    return out


async def _assemble_proposal_detail(db: AsyncSession, proposal: Proposal) -> ProposalDetail:
    # ... existing cluster/template/study/digest fetches unchanged ...

    # NEW: single-id lookup for is_currently_live (FR-5).
    live_ids = await repo.find_currently_live_proposal_ids(db, [proposal.id])
    is_live = proposal.id in live_ids

    return ProposalDetail(
        # ... existing fields ...
        is_currently_live=is_live,
        # ...
    )
```

**Pydantic schemas**

See above — both `ProposalSummary` and `ProposalDetail` gain `is_currently_live: bool = False`.

**Tasks**

1. (Schema fields landed in Story 2.1; this story implements the runtime derivation.)
2. Update `_assemble_proposal_summary_batch()` to call `repo.find_currently_live_proposal_ids` once per page (batched — one extra query per request, no N+1).
3. Update `_assemble_proposal_detail()` to call the same helper with a single-element list.
4. Write integration tests for AC-9 + AC-14 in `test_proposals_is_last_merged_filter.py` (story 2.3 owns that file; share):
   - **AC-9** (`test_summary_is_currently_live_per_row`): seed 1 live + 4 non-live proposals; `GET /api/v1/proposals?cluster_id=<cid>` returns exactly one row with `is_currently_live=true`.
   - **AC-14** (`test_detail_is_currently_live`): `GET /api/v1/proposals/<live_pid>` returns `is_currently_live=true`; `GET /api/v1/proposals/<other_pid>` returns `is_currently_live=false`.
5. Add the contract assertions to `test_digest_proposal_api_contract.py`.

**Definition of Done (DoD)**

- [ ] AC-9 + AC-14 pass.
- [ ] Contract test asserts the new field is in OpenAPI for both schemas.
- [ ] `_assemble_proposal_summary_batch` adds at most one extra query per page (verify by `EXPLAIN ANALYZE` or by counting queries in a fixture).

### Story 2.3 — `?is_last_merged=true|false` filter (FR-6)

**Outcome:** The `GET /api/v1/proposals` endpoint accepts a new optional `?is_last_merged` query param. `true` filters to live-pointer proposals via `EXISTS`; `false` to the complement via `NOT EXISTS`. Composes with all existing filters. `X-Total-Count` reflects the filtered count.

**New files**

| File | Purpose |
|---|---|
| `backend/tests/integration/test_proposals_is_last_merged_filter.py` | AC-9, AC-10, AC-11; also hosts AC-14 from Story 2.2. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/api/v1/proposals.py` | Add `is_last_merged: Annotated[bool \| None, Query()] = None` query param to `list_proposals_endpoint`. Forward to `repo.list_proposals_paginated` + `repo.count_proposals`. |
| `backend/app/db/repo/proposal.py` | Extend `list_proposals_paginated()` + `count_proposals()` signatures with `is_last_merged: bool \| None = None` kwarg. Add the EXISTS / NOT EXISTS predicate to the `WHERE` chain. |
| `backend/tests/contract/test_digest_proposal_api_contract.py` | Add AC-12 contract assertion: `?is_last_merged=maybe` → 422 standard envelope. |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/api/v1/proposals?is_last_merged=true` | — | `200` paginated list filtered to live proposals (0..N rows; at most one per config_repo). `X-Total-Count` reflects the filtered count. | `VALIDATION_ERROR` (422) — for non-bool values via the global handler. |
| `GET` | `/api/v1/proposals?is_last_merged=false` | — | `200` complement: all proposals not pointed at by any config_repo. NULL-safe via NOT EXISTS. | Same. |

**Key interfaces**

```python
# backend/app/db/repo/proposal.py — extend list_proposals_paginated and count_proposals

async def list_proposals_paginated(
    db: AsyncSession,
    *,
    # ... existing kwargs ...
    is_last_merged: bool | None = None,
) -> Sequence[Proposal]:
    """... existing docstring ...

    `is_last_merged` filter (FR-6) — when set, narrows to proposals that
    ARE (True) or ARE NOT (False) tracked as some config_repo's
    last_merged_proposal_id. Pointer-only EXISTS predicate (NULL-safe).
    """
    # ... existing select setup ...
    if is_last_merged is True:
        stmt = stmt.where(
            select(ConfigRepo.id)
            .where(ConfigRepo.last_merged_proposal_id == Proposal.id)
            .exists()
        )
    elif is_last_merged is False:
        stmt = stmt.where(
            ~select(ConfigRepo.id)
            .where(ConfigRepo.last_merged_proposal_id == Proposal.id)
            .exists()
        )
    # ... rest of the function ...
```

```python
# backend/app/api/v1/proposals.py

async def list_proposals_endpoint(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Annotated[ProposalStatusWire | None, Query(alias="status")] = None,
    cluster_id: Annotated[str | None, Query()] = None,
    source: Annotated[ProposalSourceWire | None, Query()] = None,
    template_id: Annotated[UUID | None, Query()] = None,
    study_id: Annotated[UUID | None, Query()] = None,
    is_last_merged: Annotated[bool | None, Query()] = None,  # NEW (FR-6)
    cursor: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_LIMIT)] = DEFAULT_PAGE_LIMIT,
    sort: Annotated[ProposalSortKey | None, Query()] = None,
) -> ProposalsListResponse:
    # ... existing filter forwarding ...
    rows = list(await repo.list_proposals_paginated(
        db, ...,
        is_last_merged=is_last_merged,  # NEW
        ...,
    ))
    # ... unchanged count + cursor logic ...
    total = await repo.count_proposals(
        db, ...,
        is_last_merged=is_last_merged,  # NEW
        ...,
    )
```

**Pydantic schemas**

N/A (param parsed by FastAPI `bool` validator; no schema change beyond the query annotation).

**Tasks**

1. Extend `list_proposals_paginated` + `count_proposals` in `backend/app/db/repo/proposal.py` with the `is_last_merged: bool | None = None` kwarg and the EXISTS / NOT EXISTS predicate. Import `ConfigRepo` from `backend.app.db.models`.
2. Extend `list_proposals_endpoint` in `backend/app/api/v1/proposals.py` to accept the new query param and forward it to both repo calls.
3. Write `test_proposals_is_last_merged_filter.py`:
   - **AC-10** (`test_is_last_merged_true_returns_live_only`): seed 3 config_repos with pointers + 2 non-live proposals. `?is_last_merged=true` returns exactly 3 rows, all `is_currently_live=true`. `X-Total-Count` header = 3.
   - **AC-11** (`test_is_last_merged_false_returns_complement_null_safe`): same seed; `?is_last_merged=false` returns exactly 2 rows + any proposals whose cluster.config_repo_id IS NULL (NULL-safe via NOT EXISTS).
   - **AC-9** (`test_summary_is_currently_live_per_row`) — see Story 2.2 tasks; this test belongs to this file.
   - **AC-14** (`test_detail_is_currently_live`) — see Story 2.2 tasks; this test belongs to this file.
   - **Compose-with-existing-filters** (`test_is_last_merged_composes_with_status_filter`): `?is_last_merged=true&status=pr_merged` returns the same set as `?is_last_merged=true` alone (live proposals are by definition `pr_merged`).
4. Add **AC-12** to `test_digest_proposal_api_contract.py`: `GET /api/v1/proposals?is_last_merged=maybe` → 422 with `{detail:{error_code: "VALIDATION_ERROR", ...}}` envelope from the global handler.

**Definition of Done (DoD)**

- [ ] AC-9, AC-10, AC-11, AC-12, AC-14 pass.
- [ ] No regression on the existing 4 integration tests in `test_proposals_*_filter.py`.
- [ ] OpenAPI schema reflects the new optional query param (FastAPI auto-generated).

---

## Epic 3 — Frontend (FR-7, FR-8, FR-9)

**Epic gate (final ship gate):**
- [ ] AC-13 passes (real-backend Playwright).
- [ ] Glossary discipline tests still pass (`ui/src/__tests__/glossary/`).
- [ ] No vitest regressions.
- [ ] Manual visual check: badge looks consistent with existing `<StatusBadge>` pill style.

### Story 3.1 — `<CurrentlyLiveBadge>` component (FR-7)

**Outcome:** A small, glossary-keyed badge component renders inline in proposals list rows AND on the proposal detail page when the row is `is_currently_live === true`.

**New files**

| File | Purpose |
|---|---|
| `ui/src/components/proposals/currently-live-badge.tsx` | The badge component. ~30 LOC. Wraps an `<InfoTooltip>` for the explanation. |
| `ui/src/__tests__/components/proposals/currently-live-badge.test.tsx` | vitest cases (label + ARIA + tooltip wiring + nothing-when-false). |

**Modified files**

| File | Change |
|---|---|
| `ui/src/components/proposals/proposals-table.column-config.tsx` | Render `<CurrentlyLiveBadge isCurrentlyLive={row.original.is_currently_live} />` inside the `status` column cell, AFTER the existing `<StatusBadge>`. |
| `ui/src/app/proposals/[id]/page.tsx` | Render `<CurrentlyLiveBadge isCurrentlyLive={proposal.is_currently_live} />` adjacent to `<ProposalHeader>` (or inside it if cleaner — implementer's choice; the existing header file is `ui/src/components/proposals/proposal-header.tsx`). |

**Endpoints**

N/A (frontend-only story).

**Key interfaces**

```tsx
// ui/src/components/proposals/currently-live-badge.tsx

'use client';

import { InfoTooltip } from '@/components/common/info-tooltip';

interface CurrentlyLiveBadgeProps {
  // Optional because OpenAPI-generated types may emit `is_currently_live?: boolean`
  // for fields with backend defaults — accept undefined and null defensively.
  isCurrentlyLive?: boolean | null;
}

/**
 * Wraps the entire pill in `<InfoTooltip asChild>` so the whole badge surface
 * (not just a small icon) acts as the tooltip trigger. Hover or keyboard-focus
 * the pill text → tooltip appears. Matches AC-13's "hover the badge" assertion.
 */
export function CurrentlyLiveBadge({ isCurrentlyLive }: CurrentlyLiveBadgeProps) {
  if (isCurrentlyLive !== true) return null;
  return (
    <InfoTooltip glossaryKey="proposal.currently_live" asChild>
      <span
        tabIndex={0}
        className="ml-2 inline-flex items-center gap-1 rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800 focus:outline-none focus:ring-2 focus:ring-green-400"
        data-testid="currently-live-badge"
        aria-label="Currently live — this proposal is the most recently merged for its config repo"
      >
        Currently live
      </span>
    </InfoTooltip>
  );
}
```

**Pydantic schemas**

N/A.

**Tasks**

1. Create `ui/src/components/proposals/currently-live-badge.tsx` with the implementation above.
2. Update `ui/src/components/proposals/proposals-table.column-config.tsx` — in the `status` column's `cell` renderer (line 144), wrap the existing `<StatusBadge>` in a fragment with the new `<CurrentlyLiveBadge>` rendered after it. Match the existing inline `<StatusBadge>` precedent.
3. Update `ui/src/app/proposals/[id]/page.tsx` to render the badge. Recommended placement: inside the `<div className="flex items-center justify-between">` at line 145 (next to the `<h1>Proposal detail</h1>` heading) so it's visible at the top of the page. Pass `proposal.is_currently_live` from the detail query.
4. Write `currently-live-badge.test.tsx`:
   - **Renders badge when `isCurrentlyLive=true`**: assert `data-testid="currently-live-badge"` is in the DOM with text "Currently live" + `aria-label`.
   - **Renders null when `isCurrentlyLive=false`**: assert no element with `data-testid="currently-live-badge"`.
   - **Tooltip wiring**: assert `<InfoTooltip>` is rendered with `glossaryKey="proposal.currently_live"` (snapshot/structural check).
5. Add 2 vitest cases for the proposals-table integration: row with `is_currently_live=true` renders the badge; row without doesn't.

**Definition of Done (DoD)**

- [ ] vitest cases pass.
- [ ] Visual check (manual or via `cd ui && pnpm dev`): badge renders consistently with existing pill style.
- [ ] No regression on existing `proposals-table.test.tsx` cases.

### Story 3.2 — Glossary entries + lint pass (FR-8)

**Outcome:** Two new glossary entries (`proposal.currently_live`, `proposal.currently_live_filter`) added to `ui/src/lib/glossary.ts` with short + long form. Existing glossary discipline tests stay green.

**New files**

None.

**Modified files**

| File | Change |
|---|---|
| `ui/src/lib/glossary.ts` | Add two new entries. Source-of-truth comment added per glossary discipline. |

**Endpoints**

N/A.

**Key interfaces**

```typescript
// ui/src/lib/glossary.ts — additions in the `proposal.*` section (around line 421)

'proposal.currently_live': {
  short: 'This proposal is the most recently merged PR for its config repo — assumed live in production.',
  long: `RelyLoop tracks the last-merged proposal per config repo as a pointer. Once a PR merges and the GitHub webhook fires, the proposal becomes the "currently live" record. Production deploy is operator-owned, so this badge means "merged most recently" not "verified live in your cluster."`,
  // Source-of-truth: backend/app/db/models/config_repo.py ConfigRepo.last_merged_proposal_id
},
'proposal.currently_live_filter': {
  short: 'Show only proposals tracked as the live config in their repo.',
  // Source-of-truth: backend/app/api/v1/proposals.py ?is_last_merged=true filter
},
```

**Pydantic schemas**

N/A.

**Tasks**

1. Add the two entries to `ui/src/lib/glossary.ts` per the snippet above.
2. Verify the glossary discipline tests pass (`pnpm test ui/src/__tests__/glossary/`). The tests parse `glossary.ts`, enumerate all `glossaryKey` references across the codebase, and assert (no orphan keys, no missing keys).
3. Confirm both keys conform to the `ShortGlossaryKey` TypeScript type — Story 3.1 + Story 3.3 will use `glossaryKey="proposal.currently_live"` and `glossaryKey="proposal.currently_live_filter"` respectively; if `ShortGlossaryKey` is a Literal-of-string-keys, the addition is mechanical.

**Definition of Done (DoD)**

- [ ] Glossary discipline tests pass.
- [ ] TypeScript `pnpm typecheck` passes (the new keys are recognized by the `ShortGlossaryKey` type).
- [ ] Stories 3.1 and 3.3 successfully reference both keys without lint warnings.

### Story 3.3 — Proposals page filter chip + URL state + empty state + E2E (FR-9)

**Outcome:** The proposals page gains a "Currently live only" two-state filter chip wired to `?is_last_merged=true` via the existing `useDataTableUrlState` hook. Empty-state copy adapts when the filter is active. Real-backend Playwright test covers AC-13.

**New files**

| File | Purpose |
|---|---|
| `ui/src/__tests__/components/proposals/filter-chip-currently-live.test.tsx` | vitest cases for the chip's two-state behavior + URL-state integration + glossary tooltip. |
| `ui/tests/e2e/proposals-currently-live.spec.ts` | Real-backend Playwright test covering AC-13 (seed proposal → fire webhook → assert badge appears in list). |

**Modified files**

| File | Change |
|---|---|
| `ui/src/app/proposals/page.tsx` | Add the filter chip; read `?is_last_merged=true` from URL state; pass `is_last_merged` to `useProposals`; swap empty-state copy when the filter is active. |
| `ui/src/lib/api/proposals.ts` | Extend the `useProposals` hook's `ProposalsFilter` interface with `is_last_merged?: boolean`; forward to the GET request's query string. |

**Endpoints**

(Consumes `GET /api/v1/proposals?is_last_merged=true` — defined by Story 2.3.)

**Key interfaces**

```tsx
// ui/src/app/proposals/page.tsx — additions to ProposalsPageInner

const isLastMergedActive = urlState.filters['is_last_merged'] === 'true';

const query = useProposals(
  {
    status,
    cluster_id: urlState.filters['cluster_id'] ?? undefined,
    template_id: urlState.filters['template_id'] ?? undefined,
    source,
    is_last_merged: isLastMergedActive ? true : undefined,  // NEW
    sort: urlState.sort ?? undefined,
    cursor: urlState.cursor ?? undefined,
    limit: urlState.pageSize,
  },
  { /* ...existing refetch policy ... */ },
);

// New chip UI inside the page header (location: implementer's choice — between the <h1> and the <Card>):
//
// Important: <InfoTooltip> in standalone mode renders its own <button>. Nesting a button
// inside the chip button is invalid HTML (per WAI-ARIA "interactive content can't contain
// interactive content"). We render the chip and the info-tooltip as SIBLINGS inside a
// wrapper span so the chip's onClick toggles the filter and the info trigger handles its
// own focus/keyboard for the tooltip.
<span className="inline-flex items-center gap-1">
  <button
    type="button"
    onClick={() => urlState.setFilter('is_last_merged', isLastMergedActive ? null : 'true')}
    aria-pressed={isLastMergedActive}
    className={
      isLastMergedActive
        ? 'inline-flex items-center gap-1 rounded-full bg-green-100 px-3 py-1 text-sm font-medium text-green-800'
        : 'inline-flex items-center gap-1 rounded-full bg-gray-100 px-3 py-1 text-sm font-medium text-gray-700 hover:bg-gray-200'
    }
    data-testid="proposals-currently-live-filter-chip"
  >
    Currently live only
  </button>
  <InfoTooltip glossaryKey="proposal.currently_live_filter" />
</span>
```

```typescript
// ui/src/lib/api/proposals.ts — extend ProposalsFilter

export interface ProposalsFilter {
  // ... existing fields ...
  is_last_merged?: boolean;
}

// In useProposals, append to the query params:
params: {
  status,
  cluster_id,
  template_id,
  source,
  is_last_merged,  // NEW — `undefined` is dropped by the fetch helper
  sort,
  cursor,
  limit,
},
```

**Pydantic schemas**

N/A (frontend hook + UI only).

**Tasks**

1. Extend `ProposalsFilter` in `ui/src/lib/api/proposals.ts` with `is_last_merged?: boolean`. Verify the hook forwards it as a query string param (existing pattern at line ~30; the apiClient drops `undefined`).
2. Update `ui/src/app/proposals/page.tsx`:
   - Read `urlState.filters['is_last_merged']` (string).
   - Compute `isLastMergedActive = filter === 'true'`.
   - Add the filter chip JSX between the `<h1>` and the `<Card>` (or wherever the existing filter chips would live — verify by reading the page; if there's no existing chip row, render it standalone above the table).
   - Update the empty-state copy: when `isLastMergedActive && data?.data.length === 0`, the `<DataTable>` should show "No currently-live proposals — no config repo has a merged proposal tracked yet." (Implementer: this likely requires passing a conditional `emptyStateNoMatch` prop to `<ProposalsTable>` or using the existing `emptyStateNoMatch` slot in `proposals-table.tsx`.)
3. Write `filter-chip-currently-live.test.tsx`:
   - **Click toggles URL state**: render the page with `urlState.filters = {}`; click the chip; assert `urlState.setFilter` was called with `('is_last_merged', 'true')`.
   - **Re-click clears**: render with `urlState.filters = { is_last_merged: 'true' }`; click; assert `setFilter('is_last_merged', null)`.
   - **aria-pressed reflects state**: active → `aria-pressed="true"`; inactive → `aria-pressed="false"`.
   - **Tooltip wiring + content on hover**: assert `<InfoTooltip glossaryKey="proposal.currently_live_filter">` is rendered inside the chip. Use `userEvent.hover(infoTrigger)` and assert the glossary short-text appears in the rendered DOM (proves the Radix tooltip opens, not just that the prop was passed).
   - **Tooltip on keyboard focus**: use `userEvent.tab()` until the InfoTooltip trigger is focused; assert the tooltip text appears (per FR-8 — focus must trigger it equally to hover).
   - **Keyboard activation**: assert the chip is focusable (`tab` reaches it) and activates on `Enter` (use `userEvent.keyboard('{Enter}')`).
   - **Empty-state copy when filter active and no rows**: render the page with `is_last_merged=true` URL state AND a mocked empty `useProposals` response. Assert the visible empty-state copy is exactly: "No currently-live proposals — no config repo has a merged proposal tracked yet." (per FR-9).
4. Write `proposals-currently-live.spec.ts` (real-backend Playwright):
   - **Setup via API helpers** (`request` only — existing pattern in `ui/tests/e2e/helpers/seed.ts`): seed a config_repo + cluster + query_set + judgment_list + template + study → completed study → pending proposal P with `pr_state='open', status='pr_opened'`.
   - **Fire the merge via a real HMAC-signed webhook** to `POST /webhooks/github`. AC-13 explicitly requires the webhook side effect to be exercised — bypassing via direct DB writes invalidates the test. If no helper exists in `ui/tests/e2e/helpers/seed.ts`, add a small `fireMergedPrWebhook(proposalPrUrl, mergedAt)` helper that:
     - Reads `WEBHOOK_HMAC_SECRET` from the test env (or uses the test-fixture default).
     - Constructs a minimal `pull_request.closed` payload with `merged=true, merged_at=<ts>, pull_request.html_url=<P.pr_url>, repository.full_name=<owner>/<repo>`.
     - Computes the SHA-256 HMAC and POSTs to `${PLAYWRIGHT_API_BASE_URL}/webhooks/github` with `X-Hub-Signature-256` + `X-GitHub-Event: pull_request`.
     - Polls `GET /api/v1/proposals/{P.id}` until `status === 'pr_merged'` (max 5s).
   - **Browser-driven assertions** (`page.*` only): `await page.goto('/proposals')`; `await expect(page.getByTestId('currently-live-badge')).toBeVisible()`; **hover the badge with `page.hover('[data-testid="currently-live-badge"]')` and assert the tooltip text from glossary key `proposal.currently_live` is visible** (per FR-8 — tooltip must appear on hover); click the "Currently live only" chip; `await expect(page).toHaveURL(/is_last_merged=true/)`; assert the visible row count is 1; click chip again; URL drops `is_last_merged`.

**Definition of Done (DoD)**

- [ ] vitest cases pass.
- [ ] Playwright real-backend spec passes.
- [ ] `cd ui && pnpm typecheck && pnpm lint && pnpm build` all green.
- [ ] No regression on the existing proposals-page tests.

---

## UI Guidance

### Reference: current component structure

**`ui/src/app/proposals/page.tsx`** (76 LOC):
- Section: `ProposalsPageInner` (lines 11–67) — table host.
- State: `urlState` (lines 12), `query` (lines 27–45).
- Insertion point for new filter chip: after line 49 (`<h1>Proposals</h1>`), before line 52 (`<Card>`).

**`ui/src/components/proposals/proposals-table.column-config.tsx`** (187 LOC):
- 7 columns defined as `DataTableColumnDef<ProposalSummary>[]` at line 67.
- The `status` column at line 134 is the natural badge anchor — `cell` renderer at line 144 currently shows `<StatusBadge kind="proposal" value={row.original.status} />` only.
- Insertion point: wrap the existing `<StatusBadge>` in a fragment with the new `<CurrentlyLiveBadge>` rendered after it.

**`ui/src/app/proposals/[id]/page.tsx`** (208 LOC):
- `<div className="flex items-center justify-between">` at line 145 holds the page heading.
- `<ProposalHeader>` at line 148 renders the proposal status pill row.
- Insertion point: either inside the line-145 flex container (next to `<h1>`) OR inside `<ProposalHeader>` itself (if implementer prefers semantic grouping with the existing status pill).

### Analogous markup patterns

**Pattern 1 — `<StatusBadge>` inline pill (used for status / pr_state columns):**

```tsx
{/* From proposals-table.column-config.tsx:144 */}
<StatusBadge kind="proposal" value={row.original.status} />
```

`<StatusBadge>` lives at `ui/src/components/common/status-badge.tsx`. It renders a Tailwind pill with semantic color (`bg-yellow-100 text-yellow-800` for pending, `bg-blue-100 text-blue-800` for pr_opened, `bg-green-100 text-green-800` for pr_merged, etc.). The new `<CurrentlyLiveBadge>` matches the `pr_merged` green palette intentionally — it's a closely related concept.

**Pattern 2 — `<InfoTooltip>` glossary affordance (used everywhere; see `suggested-followups-panel.tsx:19`):**

```tsx
{/* From suggested-followups-panel.tsx:19 */}
<InfoTooltip glossaryKey="proposal.suggested_followups" />
```

The component standalone-mode renders a 24×24 button with a 14×14 `<Info />` lucide icon, accessible on hover + focus. Tooltip body comes from the glossary entry's `short` field.

**Pattern 3 — Filter chip with `aria-pressed` (used in shadcn-influenced chip rows in the codebase):**

The `<DataTable>` filter chip pattern is established. The new chip lives outside the table (in the page header) because `is_last_merged` is a global filter, not a column filter. The button JSX in the key-interfaces block above mirrors the inline-Tailwind pattern used by the homepage `<DemoBadge>` at `ui/src/components/home/demo-badge.tsx`.

### Layout and structure

- Filter chip: standalone, rendered in a flex row above the table card. Aligns left.
- Badge in table row: inline with the existing status pill, comma-/margin-separated, no wrap.
- Badge on detail page: inline with the page `<h1>`, right-aligned.
- Responsive: badge text is short ("Currently live") so it fits all viewports; chip wraps to a second row on narrow viewports.

### Visual consistency

| New element | CSS source / pattern |
|---|---|
| `<CurrentlyLiveBadge>` | Tailwind `bg-green-100 text-green-800` pill — matches `<StatusBadge kind="proposal" value="pr_merged">` palette. |
| Filter chip (active) | `bg-green-100 text-green-800` to mirror the badge it filters for. |
| Filter chip (inactive) | `bg-gray-100 text-gray-700 hover:bg-gray-200` — neutral default. |
| `<InfoTooltip>` icon | Inherited from the existing primitive — 14×14 lucide `<Info />` in a 24×24 hit area. |

### Component composition

- `<CurrentlyLiveBadge>` is an extracted, prop-driven component (single boolean prop). Reused in two locations (table row + detail page) so extraction is justified.
- Filter chip is inline JSX inside `proposals/page.tsx` — single use site, no extraction.

### Interaction behavior

| User action | Frontend behavior | API call |
|---|---|---|
| Click "Currently live only" chip | Set `urlState.filters['is_last_merged'] = 'true'`; refetch | `GET /api/v1/proposals?is_last_merged=true&...other-filters` |
| Click chip again | Set `urlState.filters['is_last_merged'] = null`; refetch | `GET /api/v1/proposals?...other-filters` |
| Hover badge | Show tooltip with short form | None |
| Focus badge via Tab | Show tooltip with short form (a11y) | None |
| Click info icon inside tooltip | Show long form (popover) | None |

### Handler function patterns

```tsx
// Chip click handler (inline in proposals/page.tsx)
onClick={() => urlState.setFilter('is_last_merged', isLastMergedActive ? null : 'true')}

// Hook-level filter forwarding (ui/src/lib/api/proposals.ts)
return useQuery<ProposalsPage, ApiError>({
  queryKey: ['proposals', filter],
  queryFn: async () => {
    const { data, headers } = await apiClient.get<ProposalsListResponse>(
      '/api/v1/proposals',
      { params: filter },  // is_last_merged: true|undefined flows through naturally
    );
    return { ...data, totalCount: Number(headers.get('X-Total-Count') ?? 0) };
  },
});
```

### Information architecture placement

- Badge: inside the proposals table's status column → discoverable while scanning the table.
- Badge on detail page: inside the page-header flex container → visible at first glance.
- Filter chip: above the table on `/proposals` → discoverable as a global filter toggle.
- No nav-level change. No new route.

### Tooltips and contextual help

| Element | Tooltip text | Trigger | Placement | Glossary key | Source-of-truth comment target |
|---|---|---|---|---|---|
| `<CurrentlyLiveBadge>` | "This proposal is the most recently merged PR for its config repo — assumed live in production." | hover + focus + info-icon click | top | `proposal.currently_live` | `// Source-of-truth: backend/app/db/models/config_repo.py ConfigRepo.last_merged_proposal_id` |
| "Currently live only" filter chip | "Show only proposals tracked as the live config in their repo." | hover + focus | top | `proposal.currently_live_filter` | `// Source-of-truth: backend/app/api/v1/proposals.py ?is_last_merged=true filter` |

Both tooltips route through `<InfoTooltip glossaryKey="...">` — never inline strings.

### Legacy behavior parity

**No legacy behavior parity table — no user-facing component >100 LOC is being deleted or migrated in this plan.** All UI changes are additive: a new badge component, a new filter chip, two new glossary entries, and two existing component edits (proposals table column cell + proposal detail page heading) that ADD content without removing anything.

### Client-side persistence

The filter chip's active state persists via URL query string (`?is_last_merged=true`), not localStorage/sessionStorage. This matches every other proposals-page filter (already established by `useDataTableUrlState`). Reload-safe; shareable; clears on URL navigation.

---

## 3) Testing workstream

### 3.1 Unit tests

- Location: `backend/tests/unit/`
- Scope: none — the spec [feature_spec.md §14](feature_spec.md) explicitly notes this feature has no pure-Python logic that can be tested without a database. Repo helper correctness depends on Postgres row-level locking, FK semantics, async SQLAlchemy flush behavior, and timestamp comparisons.
- Tasks: **N/A** — confirmed by spec.
- DoD: N/A.

### 3.2 Integration tests

- Location: `backend/tests/integration/`
- Scope: DB-backed; covers FR-1 (migration), FR-2 (repo helper), FR-3 (webhook), FR-3a (reconciler), FR-4 (detail endpoint), FR-5 (summary derivation), FR-6 (filter).
- Tasks:
  - [ ] `test_migration_0016.py` — AC-1 (round-trip), AC-2 (backfill) — Story 1.1.
  - [ ] `test_config_repo_pointer_update_repo.py` — repo helper + concurrency + batch derivation + detail JOIN — Story 1.2.
  - [ ] `test_webhook_config_repo_pointer.py` — AC-3, AC-4, AC-5, AC-6, AC-7, AC-15 — Story 1.3.
  - [ ] `test_pr_reconcile_config_repo_pointer.py` — FR-3a happy path + negative documentation test — Story 1.4.
  - [ ] `test_config_repo_detail_last_merged.py` — AC-8 + null case + rotation case — Story 2.1.
  - [ ] `test_proposals_is_last_merged_filter.py` — AC-9, AC-10, AC-11, AC-14 + compose-with-status — Stories 2.2 + 2.3 share.
- DoD:
  - [ ] All 6 new integration test files pass.
  - [ ] No regression on existing `test_proposals_*.py` and `test_webhook_*.py` suites.

### 3.3 Contract tests

- Location: `backend/tests/contract/`
- Scope: response shape + status code + error envelope.
- Tasks:
  - [ ] Extend `test_github_pr_worker_api_contract.py` — assert `ConfigRepoDetail.last_merged_proposal` field in OpenAPI — Story 2.1.
  - [ ] Extend `test_digest_proposal_api_contract.py` — assert `ProposalSummary.is_currently_live` + `ProposalDetail.is_currently_live` in OpenAPI; AC-12 (invalid filter → 422 wrapped envelope) — Stories 2.2 + 2.3.
- DoD:
  - [ ] No new endpoints introduced; existing contract tests still cover the changed routes.
  - [ ] AC-12 passes via the global `validation_exception_handler` at `backend/app/api/errors.py:103-118`.

### 3.4 E2E tests

- Location: `ui/tests/e2e/`
- Scope: real-backend Playwright; one new spec for AC-13.
- Tasks:
  - [ ] `proposals-currently-live.spec.ts` — seed via API helpers → fire merge → assert badge in DOM → assert filter chip narrows view — Story 3.3.
- DoD:
  - [ ] Real-backend pass (no `page.route()` mocking).
  - [ ] Uses `page.*` for assertions; `request` for setup only.

### 3.5 Existing test impact audit

| Test file | Pattern | Count | Action |
|---|---|---|---|
| `backend/tests/integration/test_webhook_github.py` | webhook receiver coverage | grep `mark_proposal_pr_merged` invocations | **No change needed.** Existing tests don't assert pointer state (column didn't exist); new tests in Story 1.3 add the assertions in a separate file. Coexist cleanly. |
| `backend/tests/integration/test_proposals_*.py` | filter coverage | 4 files | **No change needed.** New filter is additive; existing filters' behavior unchanged. |
| `backend/tests/contract/test_github_pr_worker_api_contract.py` | `ConfigRepoDetail` shape | lines 124, 148 | Extend with one new assertion for `last_merged_proposal` — Story 2.1. |
| `backend/tests/contract/test_digest_proposal_api_contract.py` | `ProposalDetail` shape | line 120 | Extend with new assertions for `is_currently_live` + AC-12 — Stories 2.2 + 2.3. |
| `ui/src/__tests__/proposals/proposals-table.test.tsx` (if exists) | column rendering | TBD | No change needed if it doesn't mock `is_currently_live`; verify during Story 3.1 — the field defaults to `false` so existing test fixtures won't crash. |
| `ui/tests/e2e/proposals.spec.ts` (if exists) | proposals list E2E | TBD | No change needed if it doesn't seed a merged proposal; verify during Story 3.3. |

### 3.5 Migration verification

- [ ] Alembic `0016` includes `downgrade()`.
- [ ] `alembic upgrade head` succeeds.
- [ ] Round-trip verified: `alembic downgrade -1 && alembic upgrade head`.
- [ ] No DB revision guard regression (MVP1 doesn't enforce at startup; MVP2+ will).

### 3.6 CI gates

- [ ] `make test-unit` (no new unit tests; should pass unchanged).
- [ ] `make test-integration` (full suite — new tests should pass cleanly alongside existing).
- [ ] `make test-contract`.
- [ ] `cd ui && pnpm test` (vitest).
- [ ] `cd ui && pnpm test:e2e` (Playwright real-backend).
- [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm build`.

---

## 4) Documentation update workstream

### 4.0 Core context files

**`state.md`** updates after final story:
- [ ] Add `feat_config_repo_baseline_tracking` to the most-recent-changes section.
- [ ] Update Alembic head: `0015_trials_per_query_metrics` → `0016_config_repos_last_merged_proposal_id`.
- [ ] Note the new bug idea `bug_pr_reconciler_blocked_by_closed_fallback` was captured.

**`architecture.md`** updates: none required (no new architectural pattern; this is a single-column denormalization that doesn't change the system topology).

**`CLAUDE.md`** updates: none required (no new conventions; no new env vars).

### 4.1 Architecture docs (`docs/01_architecture`)
- [ ] `data-model.md` §"config_repos" (line 90) — add the `last_merged_proposal_id` row to the column table with type, FK target, and the "maintained by webhook handler" note. Story 2.1 owns this doc edit.

### 4.2 Product docs (`docs/02_product`)
- [ ] None — the spec + idea + this plan are the product-doc footprint. `mvp1-user-stories.md` is not extended (this feature is MVP1.5 substrate, not in the user-stories list).

### 4.3 Runbooks (`docs/03_runbooks`)
- [ ] `webhook-debugging.md` — add a §"Last-merged pointer" subsection describing the two new structured-log event names (`config_repo_last_merged_pointer_updated`, `config_repo_last_merged_pointer_skipped_*`) and a `psql` query for operators to inspect a config_repo's current pointer:
  ```sql
  SELECT cr.name, cr.last_merged_proposal_id, p.pr_merged_at, p.pr_url
  FROM config_repos cr
  LEFT JOIN proposals p ON p.id = cr.last_merged_proposal_id
  WHERE cr.name = '<repo_name>';
  ```
  Story 1.3 owns this doc edit.

### 4.4 Security docs (`docs/04_security`)
- [ ] None — no new secrets, no new threat surface.

### 4.5 Quality docs (`docs/05_quality`)
- [ ] None — test-layer convention unchanged; the absence of unit tests for this feature is documented in the spec §14.

**Documentation DoD**
- [ ] `state.md` updated with feature completion + Alembic head.
- [ ] `data-model.md` reflects the new column.
- [ ] `webhook-debugging.md` documents the new log events.

---

## 5) Lean refactor workstream

### 5.1 Refactor goals

This feature is overwhelmingly additive — no significant refactor scope. The only "refactor" is a tiny binding refactor in `webhooks/github.py` (Story 1.3): bind `mark_proposal_pr_merged` return value to a name so the downstream pointer-update logic can key on it. ~3 LOC.

### 5.2 Planned refactor tasks
- [ ] **Story 1.3**: bind `mark_proposal_pr_merged` return value (currently unused at line 190). Pre-existing — the return value was always non-None when reached; the call just didn't capture it. Now load-bearing.
- [ ] No frontend refactor.

### 5.3 Refactor guardrails
- [ ] Existing webhook-receiver behavior preserved by the existing 19KB `test_webhook_github.py` suite — must remain green throughout.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| `feat_github_webhook` shipped | Story 1.3 | Implemented (PR #56, 2026-05-12) | The merge-event path doesn't exist; this feature has nothing to extend. |
| `feat_github_pr_worker` shipped | Story 1.1 (FK target exists; proposals table has `pr_state`/`pr_merged_at`) | Implemented (PR #45, 2026-05-12) | The proposals table wouldn't have the columns the backfill reads from. |
| `feat_digest_proposal` shipped | Story 2.2 / 2.3 (proposals list endpoint + `_assemble_proposal_summary_batch`) | Implemented (PR #41, 2026-05-11) | No proposals list to extend. |
| `chore_e2e_test_rows_isolation` shipped | Story 1.3 AC-15 test (uses `DELETE /api/v1/_test/proposals/{id}`) | Implemented (PR #186, 2026-05-21) | AC-15 test would need to fall back to direct-DB delete. |
| `feat_contextual_help` shipped | Stories 3.1 + 3.2 (uses `<InfoTooltip>` + glossary discipline tests) | Implemented (PR #122, 2026-05-15) | The InfoTooltip primitive + glossary infrastructure wouldn't exist. |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Concurrent-merge race produces deadlock | L | M | `SELECT … FOR UPDATE` on the single `config_repos` row serializes deterministically; AC-7 test runs 20 iterations to catch flakes. |
| Backfill SQL pessimizes large `proposals` tables on `make migrate` | L | L | MVP1 row counts are small (<1000 proposals typical for an alpha). Backfill is a single SQL UPDATE with a covering join via existing PK indexes. Verified safe by inspection. |
| OpenAPI type regen produces frontend type churn | M | L | Runs once per spec change; output is a deterministic file. Implementer runs `pnpm types:gen` after Epic 2, before Epic 3. |
| Real-backend Playwright test depends on webhook seed helper that may not exist | M | M | Inspect `ui/tests/e2e/helpers/seed.ts` during Story 3.3. If no merge-webhook seed exists, **add `fireMergedPrWebhook(proposalPrUrl, mergedAt)` as a new helper** that constructs a valid HMAC-signed `POST /webhooks/github` payload (per Story 3.3 task 4). **Direct DB mutation / test-only endpoints are NOT acceptable fallbacks** — AC-13 requires the real webhook side effect be exercised end-to-end. |

### Failure mode catalog

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Webhook DB disconnect mid-transaction | Network blip between proposal UPDATE and `db.commit()` | Both writes roll back. GitHub retries; the receiver re-applies idempotently. | Automatic on next webhook delivery. |
| Reconciler-only merge (webhook missed entirely) | GitHub outage during merge | Reconciler tick observes `merged=true, merged_at=<ts>`; calls `mark_proposal_pr_merged` (succeeds — proposal still `pr_opened+open`); pointer-update fires. | Automatic at next reconciler tick. |
| Reconciler can't recover fallback-closed proposal | Webhook fired with `merged=true, merged_at=null` → fallback closed → reconciler tick observes `merged=true, merged_at=<ts>` | `mark_proposal_pr_merged` returns None (`pr_state='closed'`). Pointer-update is NOT called. Proposal stays in `(pr_opened, closed)` forever. | **Manual operator intervention required.** Captured as pre-existing bug [`bug_pr_reconciler_blocked_by_closed_fallback`](../bug_pr_reconciler_blocked_by_closed_fallback/idea.md). Out of scope for this feature. |
| Cluster's `config_repo_id IS NULL` at merge time | Operator unwired the repo before the PR merged | Pointer-update silently skipped with DEBUG log; proposal still transitions to `pr_merged`. | No automatic recovery; operator can re-wire the cluster and the next merge will set the pointer. |
| Pointer-target proposal hard-deleted via test endpoint | `chore_e2e_test_rows_isolation` cleanup or operator misuse | FK `ON DELETE SET NULL` reverts pointer; `ConfigRepoDetail.last_merged_proposal` becomes `null`; rows that depended on this pointer flip `is_currently_live` to `false`. | Automatic at next merge. |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Story 1.1** (migration + ORM column + backfill) — strict prerequisite for everything else.
2. **Story 1.2** (repo helpers) — required by 1.3 + 1.4 + 2.1 + 2.2 + 2.3.
3. **Story 1.3** (webhook handler integration) — can run in parallel with 1.4.
4. **Story 1.4** (reconciler integration) — can run in parallel with 1.3.
5. **Epic 1 gate** — verify all backend writes work end-to-end.
6. **Story 2.1** (ConfigRepoDetail field + ProposalSummary/Detail `is_currently_live` schema field) — depends on Story 1.2's `get_config_repo_with_last_merged_proposal`. Adds the bare schema field for `is_currently_live` so the embedded `ProposalSummary` can carry `is_currently_live=True` without forcing Story 2.2 to ship first.
7. **Story 2.2** (per-row `is_currently_live` derivation) — depends on Story 2.1's schema addition + Story 1.2's `find_currently_live_proposal_ids`. **Must land before Story 2.3** because Story 2.3's AC-10/AC-11 tests assert `is_currently_live=true` on filtered rows.
8. **Story 2.3** (filter) — depends on Story 2.2's serializer derivation. Strict sequential after 2.2.
9. **Epic 2 gate** — regen frontend types via `pnpm types:gen`.
10. **Story 3.2** (glossary entries) — prerequisite for 3.1 + 3.3.
11. **Story 3.1** (badge component) — can run in parallel with 3.3 after 3.2.
12. **Story 3.3** (filter chip + E2E).
13. **Final story** — finalize state.md, data-model.md, webhook-debugging.md.

### Parallelization opportunities

- Stories 1.3 + 1.4 are independent (different files, different test files) — can land in parallel.
- Epic 2 Stories 2.1 → 2.2 → 2.3 are **strictly sequential** within Epic 2 (each depends on the prior; the original "parallel within Epic 2" claim was wrong — caught by GPT-5.5 cycle-1 review).
- Stories 3.1 + 3.3 both consume glossary keys from 3.2 — 3.2 ships first, then 3.1 + 3.3 in either order.

---

## 8) Rollout and cutover plan

- **Rollout stages:** single-tenant MVP1 alpha — no staged rollout, no feature flag. Ships with the merged PR.
- **Migration/cutover steps:** `make migrate` after PR merge (or automatic on next `make up`). Backfill runs as part of `0016`'s `upgrade()`.
- **Reconciliation/repair strategy:** none required — pointer is maintained forward-only by the webhook + reconciler; backfill seeds the historical state.

---

## 9) Execution tracker (copy/paste section)

### Current sprint
- [ ] Story 1.1 — Alembic 0016 + ORM column + backfill
- [ ] Story 1.2 — Repo helpers (3 functions)
- [ ] Story 1.3 — Webhook handler integration
- [ ] Story 1.4 — PR reconciler integration
- [ ] Story 2.1 — `ConfigRepoDetail.last_merged_proposal` field
- [ ] Story 2.2 — `ProposalSummary.is_currently_live` field
- [ ] Story 2.3 — `?is_last_merged` filter
- [ ] Story 3.1 — `<CurrentlyLiveBadge>` component
- [ ] Story 3.2 — Glossary entries
- [ ] Story 3.3 — Filter chip + URL state + E2E
- [ ] Finalization — state.md update, data-model.md update, webhook-debugging.md update

### Blocked items
None.

### Done this sprint
(populated as stories complete)

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete:

- [ ] Files created/modified match story scope tables.
- [ ] Endpoint contracts implemented exactly as documented (no new endpoints in this feature — modifications only).
- [ ] Key interfaces match the signatures in the story.
- [ ] Required tests pass:
    - [ ] `make test-unit` (no new unit tests; existing suite green)
    - [ ] `make test-integration -k <story-specific>` (then full suite at epic gates)
    - [ ] `make test-contract -k <story-specific>` (where applicable)
    - [ ] `cd ui && pnpm test` (where applicable)
    - [ ] `cd ui && pnpm test:e2e` (Story 3.3 only)
- [ ] Migration round-trip evidence (Story 1.1 only).
- [ ] Related docs updated in same PR when contract changed (Story 2.1 + 1.3 own doc edits).

---

## 11) Plan consistency review (performed before user handoff)

1. **Spec ↔ plan endpoint count**: spec §8.1 lists 4 endpoint rows (none new, all modifications). Plan covers all 4 across Stories 1.3, 2.1, 2.2, 2.3. ✓
2. **Spec ↔ plan FR coverage**: spec FRs 1, 2, 3, 3a, 4, 5, 6, 7, 8, 9 → plan Stories 1.1, 1.2, 1.3, 1.4, 2.1, 2.2, 2.3, 3.1, 3.2, 3.3. ✓
3. **Spec ↔ plan AC coverage**: spec ACs 1–15 → plan stories cover all 15 (AC-1, AC-2 in 1.1; AC-3, AC-4, AC-5, AC-6, AC-7, AC-15 in 1.3; AC-8 in 2.1; AC-9, AC-10, AC-11, AC-12, AC-14 in 2.2/2.3; AC-13 in 3.3). ✓
4. **Story internal consistency**: endpoint tables match Pydantic schemas; new files not duplicated; modified files verified to exist. ✓
5. **Test file count**: 6 new integration files + 2 vitest files + 1 Playwright spec + extensions to 2 existing contract test files. Each owned by a specific story; no orphans. ✓
6. **Gate arithmetic**: Epic 1 gate lists 8 ACs (AC-1, AC-2, AC-3, AC-4, AC-5, AC-6, AC-7, AC-15); plan Stories 1.1+1.3 cover all 8. Epic 2 gate lists 6 ACs (AC-8, AC-9, AC-10, AC-11, AC-12, AC-14); plan Stories 2.1+2.2+2.3 cover all 6. ✓
7. **Open questions resolved**: spec §19 has 0 open questions remaining. ✓
8. **Frontend UI Guidance completeness**: all 11 required subsections present (Reference, Analogous patterns, Layout, Visual consistency, Component composition, Interaction behavior, Handler patterns, IA placement, Tooltips, Legacy parity declared N/A with reason, Persistence). ✓
9. **Enumerated value contract audit**: this feature introduces no new enumerated wire values. `is_currently_live` is plain `bool`. `?is_last_merged` is Pydantic-native `bool`. Glossary keys (`proposal.currently_live`, `proposal.currently_live_filter`) are frontend-only identifiers. ✓
10. **Audit-event coverage**: N/A — MVP1 has no `audit_log` table per spec §6.

---

## 12) Definition of plan done

- [x] Every FR maps to stories/tasks/tests/docs updates.
- [x] Every story includes New files, Modified files, Endpoints (or N/A), Key interfaces, Tasks, and DoD.
- [x] Test layers (unit/integration/contract/e2e) are explicitly scoped — unit explicitly N/A with cited reason.
- [x] Documentation updates across docs/01-05 are planned and owned by specific stories.
- [x] Lean refactor scope is explicit (one tiny binding refactor; documented).
- [x] Phase/epic gates are measurable.
- [x] Story-by-Story Verification Gate is included.
- [x] Plan consistency review (§11) has been performed with no unresolved findings.
