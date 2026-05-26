# `db_session` fixture skip-reason is misleading when env vars are missing (vs Postgres genuinely unreachable)

**Date:** 2026-05-25
**Status:** Closed 2026-05-26 — refactored `postgres_reachable()` in `backend/tests/conftest.py` into two helpers: `postgres_skip_reason() -> str | None` returns a precise per-failure-mode skip-reason string (env-var-missing / Settings-construction-failure / TCP-unreachable), while the original `postgres_reachable() -> bool` is kept as a thin wrapper for the 100+ existing `pytest.mark.skipif(not postgres_reachable(), ...)` callsites (no migration required). The `db_session` fixture now emits the precise reason instead of the misleading hardcoded `"Postgres not reachable"`. New unit test at `backend/tests/unit/test_postgres_skip_reason.py` (8/8 pass) locks the precise reason strings against future regression.
**Priority:** P2 — ergonomics; the underlying skip is correct, just the reason string lied. Workaround was: read the script's stderr or the test environment's env-var state to disambiguate.
**Depends on:** none — self-contained ~10-LOC edit to `backend/tests/conftest.py`.

## Origin

While shipping `infra_test_worktree_missing_integration_envs` (PR pending — the patch that propagates `POSTGRES_PASSWORD_FILE` + optional `CLUSTER_CREDENTIALS_FILE` to `make test-worktree`), the existing `db_session` fixture at [`backend/tests/conftest.py:104-117`](../../../../backend/tests/conftest.py#L104-L117) was identified as having a misleading skip reason. The fixture calls `postgres_reachable()` (lines 50-72) which gates on:

1. `DATABASE_URL_FILE` env var present, AND
2. `POSTGRES_PASSWORD_FILE` env var present, AND
3. TCP connect to `host:port` succeeds within 1s timeout.

When the skip fires, the reason is hardcoded to `"Postgres not reachable — see docs/03_runbooks/local-dev.md §'Local-vs-CI test layers'."` — which is correct ONLY when failure case (3) is hit. When (1) or (2) fails, the message lies: Postgres might be perfectly reachable, but the test process just doesn't have the env-var presence the helper requires.

The same misleading-reason failure mode is what triggered the parent feature: `make test-worktree` was missing `POSTGRES_PASSWORD_FILE` propagation, every integration test skipped with "Postgres not reachable," and the actual root cause (script doesn't propagate the env var) was opaque until someone read `postgres_reachable()` carefully.

Spec D-7 of `infra_test_worktree_missing_integration_envs` captured this discovery explicitly: *"Improving the skip-reason message to differentiate the two failure modes is a separate ergonomics fix. Tracked: if the operator decides the ergonomics improvement is worth a separate PR, capture as a new `chore_db_session_skip_reason_disambiguation` idea file."*

## Problem

When an integration test skips, the reason string should tell the operator which precondition failed:

- **Env var presence failure** (cases 1 + 2 above) → skip reason should say something like `"Postgres skip: DATABASE_URL_FILE or POSTGRES_PASSWORD_FILE env var not present — see docs/03_runbooks/local-dev.md §'Local-vs-CI test layers' (likely missing -e flag on the test invocation)."`
- **TCP unreachable failure** (case 3 above) → skip reason should say `"Postgres skip: TCP connect to <host:port> timed out — Postgres container may not be running (try `make up`)."`

Both are real operator-actionable hints. The current `"Postgres not reachable"` is a lowest-common-denominator string that covers both cases equally poorly.

## Proposed capabilities

1. **Refactor `postgres_reachable()`** to return a structured result instead of `bool`. Options:
   - Return `tuple[bool, str | None]` — `(True, None)` on success; `(False, "reason string")` on each failure mode.
   - Or raise a `PostgresSkipReason` enum-typed exception, caught by the fixture.
   - Simplest: return a string discriminator (`"ok"` | `"env_missing"` | `"tcp_unreachable"`) and let the caller map it to a reason.
2. **Update the `db_session` fixture** at lines 104-117 to call the structured helper and emit a precise `pytest.skip(reason=...)` for each failure mode.
3. **Add a unit test** at `backend/tests/unit/test_postgres_reachable.py` that asserts the discriminator's value for each failure mode (mocking `socket.create_connection` for the TCP cases; manipulating `monkeypatch.delenv` for the env-var cases).

## Scope signals

- **Backend:** ~10-20 LOC change in `backend/tests/conftest.py:50-117` + 1 new ~50-LOC unit test file.
- **Frontend:** none.
- **Infra:** none.
- **Migration:** none.

## Why deferred

Out of scope for `infra_test_worktree_missing_integration_envs`. The parent feature's scope was narrowly the `make test-worktree` env-var propagation; mixing in a conftest-fixture refactor would broaden the diff and review surface for no functional benefit (the propagation fix eliminates the original symptom completely; the ergonomics fix only matters for future env-var-related regressions in OTHER test surfaces).

The spec author explicitly locked this as a separate PR via D-7. The implement-over-defer rubric supports the deferral here: the work is genuinely cross-subsystem (test infra vs. script infra) and the parent PR is already touching enough surfaces (script + smoke tests + CLAUDE.md + runbook).

## Coordinates with

- **`infra_test_worktree_missing_integration_envs`** (parent feature) — the discovery surfaced during this feature's implementation. The propagation fix eliminates the *current* manifestation of the bug; this idea hardens against *future* manifestations in any test surface that uses the helper.
- **CI workflow** — the existing `.github/workflows/pr.yml` integration-test job sets both env vars correctly (no skip should fire there). A precise skip reason would help operators debugging CI failures locally without re-deriving the env-var-check semantics.

## Open questions for /spec-gen

1. **Return-shape API choice (`tuple[bool, str | None]` vs. enum vs. discriminator string).** Recommended default: discriminator string (simplest; matches existing patterns in conftest helpers; trivially unit-testable). Locked decision can ship with the spec.
2. **Should the fixture emit different skip *reasons* for env-missing vs. TCP-unreachable, or different skip *kinds* (xfail vs. skip)?** Recommended default: same kind (skip), different reasons. xfail implies "expected failure" which doesn't match the "test couldn't run" semantic.
