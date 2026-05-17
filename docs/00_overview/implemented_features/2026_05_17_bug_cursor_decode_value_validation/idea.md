# `decode_cursor` doesn't validate payload shape — tampered cursor surfaces as 500

**Date:** 2026-05-16
**Status:** Idea — defense-in-depth concern surfaced by GPT-5.5 final review on PR #126 (feat_data_table_primitive).
**Origin:** PR #126 final cross-model review — Medium finding on `backend/app/db/repo/_sort.py`. Deferred from inline fix because the cursor surface is shared across 6 endpoints and the right fix benefits from a dedicated review pass.
**Depends on:** PR #126 merged.

## Problem

`backend/app/db/repo/_sort.py:decode_cursor()` performs a `json.loads(base64.urlsafe_b64decode(raw))` round-trip and then takes `decoded[0]` + `str(decoded[1])` without validating the payload shape or value type. A tampered or hand-crafted cursor can put a list, dict, or wrong-type primitive into the value half, which then flows into a SQL comparison clause and surfaces as a 500 rather than the intended 422.

Specifically:

```python
def decode_cursor(raw: str, *, value_is_datetime: bool) -> tuple[Any, str]:
    decoded = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
    raw_value = decoded[0]       # No check that it's a primitive matching the sort type
    row_id = str(decoded[1])      # No check that decoded has 2 elements
    if value_is_datetime and raw_value is not None:
        value: Any = datetime.fromisoformat(raw_value)  # raises ValueError → 422 if not str
    else:
        value = raw_value          # bypasses any type check; can be list/dict/number
    return value, row_id
```

For sort columns whose values are integers (e.g., `version`), strings (e.g., `name`), or floats (e.g., `best_metric`), an attacker (or buggy client) supplying a cursor with `[{"x": 1}, "abc"]` would pass through `decode_cursor` cleanly and then fail with a SQL TypeError when the comparison clause is built.

## Proposed capabilities

### Validate payload shape and value type at decode time

- Assert `decoded` is a 2-element list before indexing.
- Assert `decoded[0]` is `None | str | int | float` (the four shapes the sort surface uses).
- Cross-check the decoded value's type against the active sort column's expected type — e.g., string for `name`, int for `version`, float for `primary_metric`, datetime-string for `created_at`/`ended_at`/`completed_at`.
- Raise `ValueError` on any mismatch so the router catches it and returns 422 `INVALID_CURSOR`.

### Optional: carry the sort col name in the cursor payload

For belt-and-suspenders correctness, encode the cursor as `[col_name, value, row_id]` (3-tuple) so the decode step can verify the cursor matches the active sort. Today a cursor minted under `?sort=name:asc` could be replayed against `?sort=version:desc` and silently page through whatever happens.

This adds 1 element to every cursor; backward-incompatible with already-issued cursors but they're opaque base64 — clients never construct them — and short-lived (page-level navigation, not durable state).

### Add an `INVALID_CURSOR` error code

`api-conventions.md` currently does not enumerate `INVALID_CURSOR`. Adding it to the error envelope makes the failure mode explicit and clients can handle "your cursor is stale, reload" cleanly.

## Scope signals

- **Backend:** small (1 helper function + per-resource router wiring). ~50-100 LOC.
- **Frontend:** none — clients already treat cursors as opaque and shouldn't construct them.
- **Migration:** none.
- **Config:** none.
- **Audit events:** none.

## Why deferred

GPT-5.5 surfaced this in the PR #126 final review (Medium severity). The fix touches the cursor encoding contract shared by 6 endpoints + the per-list judgments endpoint; the right shape needs a small spec-side decision (2-tuple vs 3-tuple payload, INVALID_CURSOR error code addition). Doing it as part of PR #126 would expand scope significantly. Capturing here so the next infra-sweep agent or operator can pick it up.

## Relationship to other work

- **Parent:** `feat_data_table_primitive` (PR #126).
- **Related:** `chore_data_table_primitive_followups` (item 6 — URL-state Zod validation in the frontend) is the symmetric defense-in-depth concern at the frontend boundary.
