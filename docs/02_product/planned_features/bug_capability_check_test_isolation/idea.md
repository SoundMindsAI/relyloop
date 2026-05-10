# bug — `test_capability_check` flakes when integration tests run first

**Date:** 2026-05-09
**Status:** Idea (deferred from `infra_adapter_elastic` Story 5.1)
**Origin:** Surfaced during Story 5.1 coverage audit while running
`pytest backend/tests/ --cov=backend` (unit + integration + contract together).
Two cases failed:

* `test_capability_check.py::TestModelsEndpointFailure::test_models_failure_marks_downstream_untested`
* `test_capability_check.py::TestNetworkErrors::test_models_timeout_reported_as_fail`

Both pass when run in isolation:

```bash
uv run pytest backend/tests/unit/test_capability_check.py
# ✓ all green

uv run pytest backend/tests/                       # full suite
# ✗ the 2 cases above fail
```

## Why deferred

* Out of scope for `infra_adapter_elastic` (the failures are in
  `infra_foundation` capability-check code, not adapter code).
* Coverage gate still passes (90.85% > 80% required).
* The canonical Make targets run unit / integration / contract suites
  separately, so CI doesn't trip over the issue. The discovery only
  surfaced when Story 5.1's coverage audit ran them together via a single
  pytest invocation.

## Likely cause

State leakage between async tests:

* `test_capability_check` uses `pytest-mock` to patch `openai.AsyncClient`
  for each case.
* The integration tests create real httpx + asyncpg event-loop activity
  earlier in the run.
* When the unit-test loop is recreated, a residual cached client / settings
  reference appears to leak through, so `AsyncMock.side_effect = TimeoutError`
  doesn't propagate as expected.

The autouse `_clear_settings_caches` fixture in `backend/tests/conftest.py`
already clears `get_settings.cache_clear()`, `get_engine.cache_clear()`,
and `get_session_factory.cache_clear()` — so the leak isn't there. The
likely missing piece is clearing `openai`-side module-level globals or the
event-loop policy between tests.

## Proposed fix

Investigate and patch one or more of:

1. Add an autouse fixture in `tests/unit/conftest.py` that resets the
   `openai`-module's lazily-cached clients between cases.
2. Audit the `httpx_mock` / `respx` fixtures used by `test_capability_check`
   to confirm they tear down at function scope.
3. Switch the failing assertions to `pytest-asyncio`'s strict isolation
   mode (`@pytest.mark.asyncio(loop_scope="function")` explicit).

## Reproducer

```bash
docker run --rm --network relyloop_default \
  -v "$(pwd):/app" -w /app \
  -e DATABASE_URL_FILE=/app/secrets/database_url \
  -e POSTGRES_PASSWORD_FILE=/app/secrets/postgres_password \
  ghcr.io/astral-sh/uv:python3.12-bookworm \
  bash -c 'uv sync --quiet && uv run pytest backend/tests/'
# Failures: see test names above
```

## Scope signals

* Backend: yes (test-isolation infra).
* Frontend: no.
* Migration: no.
* Config: maybe (pytest-asyncio loop scope).

## Why this isn't a blocker today

The Make target convention (`make test-unit`, `make test-integration`,
`make test-contract`) runs the suites separately, and CI follows the same
convention. Coverage is well above the 80% gate when measured the
canonical way. The fix is on the post-MVP1 housekeeping list.
