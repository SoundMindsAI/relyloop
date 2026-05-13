# chore_starlette_422_deprecation — Idea

**Date:** 2026-05-09
**Status:** Idea — captured during `infra_foundation` Story 5.1 test backfill
**Origin:** PR for `infra_foundation`. Test runs surface a stable
`DeprecationWarning` on `starlette.status.HTTP_422_UNPROCESSABLE_ENTITY`.

## Problem

Starlette has renamed `HTTP_422_UNPROCESSABLE_ENTITY` to
`HTTP_422_UNPROCESSABLE_CONTENT`. Three call sites still use the old name:

- [`backend/app/api/errors.py:62`](../../../backend/app/api/errors.py#L62)
  — error-code mapping table key
- [`backend/app/api/errors.py:117`](../../../backend/app/api/errors.py#L117)
  — `RequestValidationError` handler `status_code` argument
- [`backend/tests/unit/test_error_envelope.py:110`](../../../backend/tests/unit/test_error_envelope.py#L110)
  — assertion on the response status code

Each pytest run prints 3 `DeprecationWarning` lines (one for the import-time
attribute access; two for runtime emission inside the handler). Tests still
pass — the constant value (`422`) is unchanged.

## Why deferred

Out of scope for `infra_foundation`. The change is mechanical (one-line
search-and-replace) but Starlette's deprecation timeline matters: if the
renamed attribute lands in a Starlette release that drops the old name, this
becomes a hard break. Until then, the warnings are noise.

## Proposed work

1. Replace all three call sites with `HTTP_422_UNPROCESSABLE_CONTENT`.
2. Verify `starlette>=` minimum that ships the renamed attribute (audit
   `pyproject.toml` constraint; bump if needed).
3. Re-run `make test-unit` and confirm zero `DeprecationWarning` lines.

## Scope signals

- Backend: `backend/app/api/errors.py` (2 sites)
- Tests: `backend/tests/unit/test_error_envelope.py` (1 site)
- Migration: none
- Config: possibly `pyproject.toml` (`starlette` minimum)
- CI: none

## Depends on

Nothing — independent cleanup.
