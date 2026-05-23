# `test_migrations.py` hardcoded head pins force a sympathy edit on every new migration

**Date:** 2026-05-23
**Status:** Idea — surfaced during `chore_reconciler_terminal_closed_no_poll` implementation
**Priority:** P3 — small-but-recurring tax; safe to defer until the next ~3 migrations land.
**Origin:** Implementation of `chore_reconciler_terminal_closed_no_poll` (PR pending). After adding migration `0017`, two assertions in `backend/tests/integration/test_migrations.py` (lines 132 and 157) failed because they pinned `row[0] == "0016"`. Updating them to `"0017"` is mechanical but easy to miss in `make test-unit`-only verification flows.

## Problem

[`backend/tests/integration/test_migrations.py`](../../../../backend/tests/integration/test_migrations.py) has two assertions:

```python
# line 130 (post-fix)
assert row[0] == "0017"

# line 155 (post-fix)
assert row[0] == "0017"
```

Every new migration bumps the head and breaks both assertions. The breakage shows up only at integration-test time (which requires a running Postgres), so a contributor running `make test-unit` after adding a migration won't see it. This is exactly the "test deferred to integration that humans don't run locally" failure mode.

The same pattern appears in `test_migration_0016.py:174,184` but that test is specifically about migration `0016`'s shape — pinning makes sense there. I fixed those during this PR by using `_alembic("downgrade", "0016")` + `_alembic("upgrade", "0016")` to pin to the specific revision rather than relying on `head`.

**Cost estimate (recurring):**
- Each new migration = 2 lines to edit in `test_migrations.py` + 2 comment lines to add (the documenting comment chain).
- 17 migrations have shipped to date; assuming ~12 more before MVP1 wraps, that's ~50 LOC of sympathy edits.

## Proposed capabilities

Replace the hardcoded head string with a dynamic lookup that reads the latest revision ID at test time. Two options:

### Option A — Read from `alembic heads`

```python
import subprocess

def _current_head() -> str:
    result = subprocess.check_output(
        ["uv", "run", "alembic", "heads"],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
    )
    # Output is "0017 (head)" — grab the first whitespace-separated token.
    return result.strip().split()[0]
```

Then assertions become `assert row[0] == _current_head()`. Drift-proof; one function shared between both tests.

### Option B — Read from the latest migration file's `revision: str = "..."`

Walk `migrations/versions/`, find the file with the highest sortable name, parse `revision: str = "XXXX"`. More work; less robust if revision IDs ever stop being lexicographically sortable.

**Recommendation:** Option A. The `alembic heads` command is the source of truth Alembic itself uses.

## Scope signals

- **Backend:** ~15 LOC (new `_current_head()` helper + 2 assertion replacements + a comment block).
- **Frontend:** none.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A (pre-MVP2).
- **Tests:** the same tests that already cover the head assertions; no new tests needed.

## Why deferred

The current 2-lines-per-migration tax is small. Worth fixing when (a) we're already touching `test_migrations.py` for another reason, or (b) a contributor hits the same surprise on their next migration and files a duplicate idea.

## Relationship to other work

None directly. The same pattern principle ("test asserts pinned constant that grows with the project") could be checked across the codebase but is not in scope here.
