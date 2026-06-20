# chore_studies_chain_recent_contract_db_skip_gate — add skip gate to the 3 LifespanManager contract tests

**Date:** 2026-06-19
**Status:** Idea — tangential discovery during `chore_agent_confirmation_per_tool_binding` (Phase 5 step 7 sweep)
**Priority:** P2
**Origin:** During the bug-fix flow's `pytest backend/tests/contract/` run, 3 tests failed with a Pydantic `ValidationError` ("`database_url_file` Field required", "`postgres_password_file` Field required") because they construct the FastAPI app via `from backend.app.main import app` + `LifespanManager(app)`, which boots `Settings(...)` at import time. The 366 other contract tests pass cleanly. Confirmed pre-existing on `main` (stashed the bug-fix branch + reran — same failure).
**Depends on:** None.

## Problem

Three tests in [`backend/tests/contract/test_studies_chain_recent_contract.py`](../../../../backend/tests/contract/test_studies_chain_recent_contract.py) fail outside the Docker stack:

- `test_x_total_count_header_emitted`
- `test_malformed_since_returns_422_validation_error`
- `test_limit_out_of_range_returns_422_validation_error`

Failure mode (verified 2026-06-19 against `main`):

```
pydantic_core._pydantic_core.ValidationError: 2 validation errors for Settings
database_url_file
  Field required [type=missing, input_value={}, input_type=dict]
postgres_password_file
  Field required [type=missing, input_value={}, input_type=dict]
```

The other contract tests in the same file (those NOT importing `app`) pass — they assert pure-Pydantic schema shapes without booting the FastAPI app. The webhook contract suite ([`test_webhook_api_contract.py`](../../../../backend/tests/contract/test_webhook_api_contract.py)) already handles this with `_skip_if_no_pg = pytest.mark.skipif(not postgres_reachable(), reason="Postgres not reachable — webhook router resolves get_db dependency at boot")`. The three `studies_chain_recent` tests just never got the same gate.

## Why this matters

- `make test-contract` from a fresh shell (no `DATABASE_URL_FILE` / `POSTGRES_PASSWORD_FILE` mounted) reports red on these three. CI is unaffected because GHA mounts the secrets, but the local-dev signal is muddied — contributors hit "3 failed" and have to triage to discover it's environmental.
- The same pattern likely affects other `LifespanManager`-based contract tests that haven't been gate-audited. A broader sweep could be filed as a sibling chore.

## Proposed capabilities

### Add `_skip_if_no_pg`-style decorator to the 3 affected tests

- Import the existing `postgres_reachable()` helper (already exported by [`backend/tests/contract/test_webhook_api_contract.py`](../../../../backend/tests/contract/test_webhook_api_contract.py) — or factor to a shared `backend/tests/contract/_skip.py` if the import shape is awkward).
- Add `@pytest.mark.skipif(not postgres_reachable(), reason="Postgres not reachable — studies_chain_recent contract test boots app via LifespanManager")` to the 3 functions.
- Estimated patch: ~10 LOC (1 import + 3 decorators) + 1 small helper extraction (~20 LOC).

## Scope signals

- **Backend:** [`backend/tests/contract/test_studies_chain_recent_contract.py`](../../../../backend/tests/contract/test_studies_chain_recent_contract.py); optional shared helper in `backend/tests/contract/_skip.py`.
- **Frontend:** none.
- **Migration:** none.
- **Config:** none.
- **Audit events:** N/A — `audit_log` activates at MVP3 per CLAUDE.md; this is test-infra only.

## Why filed rather than fixed inline

The fix is small (<30 LOC total) but the subsystem is **wholly unrelated to the agent-confirmation work** that surfaced it (test infra vs. orchestrator security). Bundling it would muddy the bug-fix PR's review boundary (per CLAUDE.md "A bug-fix PR with 4 unrelated changes is the same shape as an unreviewed PR"). A dedicated chore — possibly extended to other `LifespanManager` contract tests that may have the same gap — is cleaner.

## Relationship to other work

Surfaced during `chore_agent_confirmation_per_tool_binding` Phase 5 (tangential sweep). No coordination needed with siblings.
