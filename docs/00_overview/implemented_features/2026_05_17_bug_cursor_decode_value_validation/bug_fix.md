# Bug fix — bug_cursor_decode_value_validation

**Source idea:** [idea.md](./idea.md)
**Branch:** `claude/review-docs-prioritize-qgUla`
**Type:** bug fix — medium (this skill's scope)
**Date:** 2026-05-17

## Problem

[`backend.app.db.repo._sort.decode_cursor`](../../../../backend/app/db/repo/_sort.py#L148-L193) does no payload-shape or value-type validation. A tampered cursor whose value-half is a non-primitive (dict, list, bool, etc.) passes through `decoded[0]` and `str(decoded[1])` cleanly when `value_is_datetime=False`, flows into [`keyset_predicate`](../../../../backend/app/db/repo/_sort.py#L81-L127), and surfaces as **500 INTERNAL_ERROR** when SQLAlchemy / Postgres rejects the type-mismatched comparison — instead of the intended **422 VALIDATION_ERROR** that all 9 cursor-consuming routers translate `except Exception` into. Origin: GPT-5.5 final review on PR #126 (Medium severity, deferred from inline fix).

## Reproduction

`backend/tests/unit/db/test_parse_sort.py` is the proof:

```bash
.venv/bin/python -m pytest backend/tests/unit/db/test_parse_sort.py -v -k "rejects"
```

On `main` the 6 new test cases fail — `decode_cursor` returns successfully with a dict / list / bool / wrong-length / non-list payload instead of raising `ValueError`. After the fix the same cases pass.

A standalone repro of the silent-pass-through:

```python
import base64, json
from backend.app.db.repo._sort import decode_cursor

tampered = base64.urlsafe_b64encode(json.dumps([{"x": 1}, "abc"]).encode()).decode()
result = decode_cursor(tampered, value_is_datetime=False)
# Main: result == ({"x": 1}, "abc") — dict flows into SQL → 500.
# Fixed: ValueError("cursor value-half must be null|str|int|float, got dict")
```

## Root cause

- **Owning layer:** repo helper.
- **Origin:** [`backend/app/db/repo/_sort.py:148-193`](../../../../backend/app/db/repo/_sort.py#L148-L193) — no shape/type validation on `decoded`.
- **Propagation:** non-primitive `raw_value` enters [`keyset_predicate` at `_sort.py:81-127`](../../../../backend/app/db/repo/_sort.py#L81-L127) and reaches SQLAlchemy / Postgres as a type-mismatched comparison.
- **Caller landscape:** 9 routers (`studies`, `judgments` ×2, `clusters`, `query_templates`, `query_sets`, `conversations`, `config_repos`, `proposals`) wrap `_sort_decode_cursor` in `try/except Exception → 422 VALIDATION_ERROR`. The except never fires because decode succeeds.

## Fix design (locked decisions)

1. **Generic 4-type allowlist (`None | str | int | float`, bool rejected).** Covers every legitimate sort value (datetime → ISO string; name/status → str; version/rating → int; metrics → float; nullable → None). Cites: CLAUDE.md "Don't add abstractions beyond what the task requires."
2. **Normalize all decode failures to `ValueError`.** Today partial-payload errors raise `IndexError` / `KeyError`; routers catch the parent `Exception` so user-visible behavior is fine, but the contract should be one exception type for clarity and test grep-ability. Routers stay on `except Exception` — already a superset.
3. **Keep the 2-tuple `[value, row_id]` cursor shape.** Carrying `col_name` (idea's 3-tuple option) is backward-incompatible with issued cursors and addresses a non-crash concern (cross-sort replay). Defer to MVP2 cursor redesign if it surfaces as a real problem.
4. **Reuse `VALIDATION_ERROR` (422) instead of adding `INVALID_CURSOR`.** All 9 routers already translate cursor failures to `VALIDATION_ERROR`. New code adds noise without changing client behavior. Cites: 9-router precedent.
5. **Scope:** only `decode_cursor` changes. No router edits, no `api-conventions.md` change, no migration, no frontend.

## Regression test plan

| Layer | Path | What it asserts |
|---|---|---|
| unit | `backend/tests/unit/db/test_parse_sort.py` | 6 new cases: dict / list / bool value-half (with `value_is_datetime=False`), wrong-length payload (0 / 1 element), non-list top-level. Each must raise `ValueError`. |
| unit | `backend/tests/unit/db/test_parse_sort.py` | 1 new case: `value_is_datetime=True` with int value-half raises `ValueError` (today raises `TypeError` from `datetime.fromisoformat`, which is `Exception`-caught but not contract-explicit). |

Tests run pre-fix on `main` — all 7 fail. Post-fix — all pass. The existing 5 round-trip happy-path tests remain green.

## Rollout

None — code-only change. Cursor wire format unchanged (still 2-tuple base64-JSON); pre-fix and post-fix cursors decode identically for legitimate payloads. No client invalidation. No migration.

## Tangential observations

None. The 9 routers' inline `try/except Exception` blocks are slightly redundant once `decode_cursor` raises only `ValueError`, but unifying them would expand scope; left as-is.
