# Flaky UBI-dispatch test: naive-datetime error-code precedence (VALIDATION_ERROR vs UBI_INSUFFICIENT_DATA)

**Date:** 2026-06-04
**Status:** Idea — flaky backend test surfaced during an unrelated frontend PR
**Priority:** P2
**Origin:** Noticed during PR #453 (`feat_study_wizard_inline_judgment_generation`, frontend-only). The `backend (lint + typecheck + tests + coverage)` job **passed on the PR's first CI run, then failed on the re-run** (same branch, zero backend changes in the diff) — the signature of a non-deterministic test.
**Depends on:** None.

## Problem

`backend/tests/unit/services/test_agent_judgments_dispatch_ubi.py::test_naive_since_with_none_until_does_not_crash` (around `:324`) is flaky:

```
assert _detail(ei.value)["error_code"] == "UBI_INSUFFICIENT_DATA"
E   AssertionError: assert 'VALIDATION_ERROR' == 'UBI_INSUFFICIENT_DATA'
```

The test patches `observed=0` (via `_patch_count`) expecting `start_ubi_judgment_generation` to reach the U-D2 "insufficient data" gate and raise `UBI_INSUFFICIENT_DATA`. But on some runs a `VALIDATION_ERROR` fires **first** — i.e., a UBI-window validation rejects the request before the insufficient-data gate is reached.

The trigger is the test's use of a **naive** `datetime.now()` (line ~315, `# noqa: DTZ005`) for `since`, with `until=None` (the service defaults `until` to "now"). When `since = naive_now − 7d` and `until` resolves to a fresh `now` inside the service, the window comparison / validation outcome appears to depend on wall-clock timing (or on naive-vs-aware datetime handling), making the error-code precedence non-deterministic across runs. A sibling test (`test_naive_since_with_naive_until_does_not_crash`, ~`:304`) exercises the same path and may share the fragility.

This is **pre-existing** and unrelated to PR #453 (frontend-only, no backend files touched). Because `main` currently has no required status checks (the heavy-CI gate was removed 2026-05-31), the flake doesn't block merges — but it produces spurious red `backend` jobs and erodes trust in CI.

## Proposed capabilities

### Make the error-code precedence deterministic

- Trace the validation order in `start_ubi_judgment_generation` (`backend/app/services/...` UBI dispatch): identify which window/temporal validation can raise `VALIDATION_ERROR` before the U-D2 `UBI_INSUFFICIENT_DATA` gate, and why a naive `since` + `until=None` can flip the outcome.
- Decide the intended precedence (almost certainly: a structurally-valid window with `observed=0` should yield `UBI_INSUFFICIENT_DATA`, not `VALIDATION_ERROR`) and make it deterministic — e.g. normalize naive datetimes to UTC at the boundary so the comparison is stable, or order the insufficient-data gate ahead of the soft window check.
- Harden the test: use a **fixed/frozen** timestamp (or `timezone`-aware datetimes) instead of `datetime.now()` so the assertion can't race the wall clock; assert the precedence explicitly.

## Scope signals

- **Backend:** UBI judgment-dispatch service (`start_ubi_judgment_generation`) validation order + naive-datetime handling; the test file. Likely a small, bounded fix once the precedence is traced.
- **Frontend / Migration / Config / Audit events:** none.

## Why deferred (not fixed inline in PR #453)

Per the CLAUDE.md tangential-discoveries rubric: the fix is in a **different subsystem** (backend UBI dispatch) from PR #453's frontend wizard feature, and pinning the exact precedence/naive-datetime root cause needs investigation of the dispatch validation flow (not a sub-60-minute mechanical change verifiable from the frontend PR). Filing here so the flake isn't lost; the frontend PR's own `pr` job (frontend lint/tsc/vitest/build) is green and the backend flake is reproducible-independent.

## Relationship to other work

Related to `feat_ubi_judgments` (the dispatch path under test). Independent of `feat_study_wizard_inline_judgment_generation`.
