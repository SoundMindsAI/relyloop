# bug — `test_capability_check` flakes when integration tests run first

**Date:** 2026-05-09 (originally captured); re-audited 2026-05-12 — claims still grounded against current code.
**Status:** Idea — deferred from `infra_adapter_elastic` Story 5.1; still applies to `main` as of `c6a46a3`.
**Origin:** Surfaced during Story 5.1 coverage audit while running
`pytest backend/tests/ --cov=backend` (unit + integration + contract together).
Two cases failed:

* `test_capability_check.py::TestModelsEndpointFailure::test_models_failure_marks_downstream_untested`
* `test_capability_check.py::TestNetworkErrors::test_models_timeout_reported_as_fail`

Both pass when run in isolation:

```bash
uv run pytest backend/tests/unit/test_capability_check.py
# ✓ all green (XPASS — the xfail markers fire as unexpected-pass when isolated)

uv run pytest backend/tests/                       # full suite
# ✗ the 2 cases above XFAIL (the xfail markers hold; CI tolerates with strict=False)
```

**Re-audit 2026-05-12:** the xfail markers are still in place at
[`backend/tests/unit/test_capability_check.py:80–85`](../../../../backend/tests/unit/test_capability_check.py)
and [`:154–160`](../../../../backend/tests/unit/test_capability_check.py)
with reason text matching the structlog root-cause hypothesis below. CI is
green via `xfail strict=False`; the underlying flake is unfixed.

## Why deferred

* Out of scope for `infra_adapter_elastic` (the failures are in
  `infra_foundation` capability-check code, not adapter code).
* Coverage gate still passes (currently 80.68% on `main`, > 80% required).
* The xfail markers (added 2026-05-10 in PR #25) keep CI green; the bug is
  invisible to operators because production code paths are correct — only
  the test-side `capsys` capture is broken.

## Likely root cause (refined 2026-05-10; still valid 2026-05-12)

State leakage from structlog's logger cache, not openai client caching:

* [`backend/app/core/logging.py`](../../../../backend/app/core/logging.py)
  calls `structlog.configure(..., cache_logger_on_first_use=True)`.
* `structlog.stdlib.LoggerFactory()` binds `sys.stdout` at the moment the
  first logger call materializes the cached logger.
* When the integration tests run first, they instantiate a structlog
  logger early — the cached `PrintLogger` captures THAT test's
  `sys.stdout`, NOT the `capsys`-mocked stdout in the unit-test cases
  that run later.
* The autouse `_clear_settings_caches` fixture in
  [`backend/tests/conftest.py:74–95`](../../../../backend/tests/conftest.py)
  clears `get_settings`/`get_engine`/`get_session_factory` lru_caches but
  does NOT touch structlog's logger cache — that's the missing piece.

The original 2026-05-09 hypothesis (openai client / asyncpg event-loop
state) was disproven by the 2026-05-10 investigation; structlog is the
actual culprit.

## Proposed solutions (one to pick at spec time)

1. **Replace `capsys` with `caplog`** in the two failing tests. `caplog`
   captures stdlib `LogRecord`s before they reach any cached
   `PrintLogger`. Tests assert on `record.levelname == "WARNING"` +
   `record.msg`. Smallest blast radius — only the 2 test cases change.
2. **Autouse `structlog.reset_defaults()`** in `tests/unit/conftest.py`.
   Forces `configure_logging()` to run again per-test so the cached
   logger gets the current `capsys` stdout. Touches every unit test's
   structlog binding — slight perf cost, broader semantic change.
3. **Bind per-test logger via `structlog.wrap_logger(...)`** in the
   failing tests. Most invasive — requires the production code to
   inject a logger rather than calling `structlog.get_logger()`.

Default for /spec-gen to lock: **option 1** (replace capsys with caplog).
Cleanest scope; doesn't perturb other tests.

## Reproducer

```bash
docker run --rm --network relyloop_default \
  -v "$(pwd):/app" -w /app \
  -e DATABASE_URL_FILE=/app/secrets/database_url \
  -e POSTGRES_PASSWORD_FILE=/app/secrets/postgres_password \
  ghcr.io/astral-sh/uv:python3.13-bookworm \
  bash -c 'uv sync --quiet && uv run pytest backend/tests/'
# Failures: see test names above
```

(Bumped to `python3.13-bookworm` 2026-05-12 to match
`pyproject.toml [project] requires-python = ">=3.13"`.)

## Acceptance

- [ ] Both `test_models_failure_marks_downstream_untested` and
      `test_models_timeout_reported_as_fail` pass without `xfail` markers
      when run as part of the full `pytest backend/tests/` invocation.
- [ ] The xfail markers + their `reason=...` text are removed.
- [ ] No new XFAIL/XPASS cases introduced elsewhere as a side effect.
- [ ] CI's combined-suite invocation in `pr.yml` (`uv run pytest backend/tests/`)
      stays green.

## Sibling coordination

[`bug_test_smoke_requires_env_vars`](../bug_test_smoke_requires_env_vars/idea.md)
is a closely-related but distinct test-isolation issue (Settings env-var
pollution, NOT structlog caching). Different root cause, different test.
Whoever picks up this fix should ALSO check whether the same conftest
session can absorb the `bug_test_smoke_requires_env_vars` fix — both
land in the unit-test conftest, both are infra-test improvements, and
the diff is small enough that bundling probably reduces churn. If they
disagree on conftest fixture design, ship separately.

## Scope signals

* Backend: yes (test-isolation infra in `backend/tests/conftest.py` or `tests/unit/conftest.py`).
* Frontend: no.
* Migration: no.
* Config: maybe (pytest-asyncio loop scope, structlog cache flag).
* Audit-log: N/A — pre-MVP2; no state mutation.

## Open questions for /spec-gen

- **Which solution?** Default: option 1 (caplog swap). Lock at spec time.
- **Bundle with `bug_test_smoke_requires_env_vars`?** Default: split (different root causes; smaller PRs review faster). Confirm at spec time.
- **Retire the xfail markers in the same PR?** Default: yes — the markers are a band-aid; their removal IS the acceptance criterion. Verify `strict=False` doesn't get re-introduced.

## Why this isn't a blocker for v0.1.0

The xfail markers are correctly tolerating the flake on every CI run.
Coverage gate passes. Production code paths (the actual capability check
warnings) emit correctly to operator logs — only the test-side capture
is broken. The fix is on the post-MVP1 housekeeping list and can ship
any time post-`v0.1.0` tag without affecting alpha operators.

## Audit history

- **2026-05-09** — captured during `infra_adapter_elastic` Story 5.1 coverage audit. Original hypothesis: openai client / asyncpg event-loop state leakage.
- **2026-05-10 — re-surfaced by PR #25** (`feat_study_lifecycle` Phase 2). The CI workflow at [`.github/workflows/pr.yml`](../../../../.github/workflows/pr.yml) actually runs all three test layers in a single `pytest backend/tests/` invocation (the original "Why isn't this a blocker today" was based on the Make-target convention; CI does it differently). Phase 2 added ~120 new integration tests; the extra setup tripped the latent flake more reliably and the two cases failed on every PR #25 CI run. Cases marked `@pytest.mark.xfail(strict=False)` to keep CI green. **Tactical band-aid; root-cause fix still the right path.** Hypothesis refined from openai → structlog cache.
- **2026-05-12 — re-audit (`/idea-preflight`):** all claims grounded against current code. Reproducer Python version bumped 3.12 → 3.13. Acceptance criteria added. Sibling coordination note added. Open questions reframed with default-locked answers. Original "Why this isn't a blocker today" + 2026-05-10 update consolidated into a single `Audit history` section to remove contradiction.
