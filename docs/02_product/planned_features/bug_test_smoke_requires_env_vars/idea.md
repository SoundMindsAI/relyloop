# bug_test_smoke_requires_env_vars

**Date:** 2026-05-12
**Status:** Idea — captured during `feat_github_webhook` `/impl-execute`
**Origin:** Surfaced repeatedly while running `make test-unit` /
`pytest backend/tests/unit/` on the developer laptop during
`feat_github_webhook` implementation. Confirmed pre-existing on `main`
via `git stash` + `pytest backend/tests/unit/test_smoke.py::test_app_import`.

## Problem

`backend/tests/unit/test_smoke.py::test_app_import` fails when run
without `DATABASE_URL_FILE` and `POSTGRES_PASSWORD_FILE` env vars in
the test environment:

```
pydantic_core._pydantic_core.ValidationError: 2 validation errors for Settings
database_url_file
  Field required [type=missing, input_value={}, input_type=dict]
postgres_password_file
  Field required [type=missing, input_value={}, input_type=dict]
```

The other unit-test files that need Settings (e.g. `test_workers.py`,
`test_settings_pr_poll.py`, `test_git_pr_helpers.py`) all carry their
own `monkeypatch.setenv(...)` fixture pointing the two required-secret
files at `/dev/null` or a `tmp_path` file. `test_smoke.py` doesn't —
it just `from backend.app.main import app` cold, which triggers
`get_settings()` at module load via `_cors_origins`.

## Why deferred

* Out of scope for `feat_github_webhook` — this isn't a feature
  regression, it's a pre-existing fragility.
* The failure doesn't block CI because CI runs the suite with the
  required env vars populated (the GHA workflow sets them up before
  `pytest`).
* Local developer experience is the only victim. The fix is one
  fixture.

## Proposed fix

Add an autouse fixture to `backend/tests/unit/test_smoke.py` (or a
session-scoped fixture in `backend/tests/unit/conftest.py`) that sets
`DATABASE_URL_FILE` + `POSTGRES_PASSWORD_FILE` to a `tmp_path` file and
clears `get_settings.cache_clear()`. Mirror the pattern in
`backend/tests/unit/test_workers.py:_settings_env`.

## Scope signals

- backend/tests/unit/test_smoke.py: one new fixture
- No production-code changes
- 5-minute fix; ideally bundled with the next infra-sweep PR.
