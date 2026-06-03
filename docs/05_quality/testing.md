# Testing strategy

> Test-layer conventions, coverage gates, and how to run each layer locally and in CI. Lands in `infra_foundation` Story 5.2.

## Test layers

| Layer | Location | DB? | When it runs | Notes |
|---|---|---|---|---|
| **Unit** | `backend/tests/unit/` | No | `make test-unit` (always) | Pure functions; mocked externals (httpx, openai, asyncpg); fast. |
| **Integration** | `backend/tests/integration/` | Yes | `make test-integration` (requires stack) | Marked `@pytest.mark.integration`; DB-backed; some require running ES/OpenSearch. |
| **Contract** | `backend/tests/contract/` | No | `make test-contract` | Assert response shapes against FastAPI's OpenAPI schema; verify error codes. |
| **E2E** | `ui/tests/e2e/` | Via running stack | (lands with `feat_studies_ui`) | Playwright; real backend (no `page.route()` mocking). |

## Coverage gate

**80% backend Python** for MVP1. Configured via `pyproject.toml`:

```toml
[tool.coverage.report]
fail_under = 80
```

`pytest --cov=backend ...` reads this and fails the run if coverage drops
below the gate. Per-file targets called out in `infra_foundation` Story 5.1:

- `backend/app/api/health.py`: 100% (operator probe — every code path tested)
- `backend/app/core/settings.py`: 100% (every secret path tested)
- Project total: ≥80%

The 90% gate activates at GA v1.

## Running tests

```bash
make test-unit           # unit only — no Docker, no DB; fast (~1s)
make test-integration    # integration — requires running stack (Postgres + Redis + ES + OpenSearch)
make test-contract       # contract — no DB; tests OpenAPI shape + error codes
make test                # all three in sequence

# Targeted
.venv/bin/pytest backend/tests/unit/test_health.py -v --tb=short
.venv/bin/pytest backend/tests/unit/test_settings.py::TestRequiredSecrets -v
.venv/bin/pytest -k "capability_check" -v
```

## Test conventions

### Unit tests

- Pure functions, mocked externals (httpx, openai, asyncpg)
- Located in `backend/tests/unit/<topic>.py`
- No DB fixtures; `monkeypatch` for env / module-level state
- Settings cache pollution: tests that change `*_FILE` env vars must call
  `get_settings.cache_clear()`

### Integration tests

- Mark each test (or the test module) with `@pytest.mark.integration`
- Run against the live Compose stack — Postgres + Redis + ES + OpenSearch
- **Mocking rule:** mock external services (OpenAI, GitHub API) via
  `monkeypatch`. Never mock internal code — DB, repos, services, domain
  logic all run for real against the test database.
- **Real-engine ES writes:** test fixtures that need to bulk-index controlled
  documents into the ES service container (currently only AC-1..AC-4b of
  `feat_study_preflight_overlap_probe` via the helpers in
  [`backend/tests/integration/fixtures/es_overlap_probe.py`](../../backend/tests/integration/fixtures/es_overlap_probe.py))
  use a dedicated test-only `httpx.AsyncClient` directly inside the fixture
  module. Bulk-indexing is intentionally NOT on the `SearchAdapter` Protocol
  per `infra_study_preflight_real_engine_integration` D-1 (the Protocol is
  engine-agnostic *query-time* search; write-side helpers don't generalize
  across `ElasticAdapter` + future `SolrAdapter`). The same pattern is used
  by [`backend/app/scripts/seed_es.py`](../../backend/app/scripts/seed_es.py)
  and [`backend/tests/integration/test_seed_es.py`](../../backend/tests/integration/test_seed_es.py).
- CI provides Postgres + Redis + ES + OpenSearch via service containers in
  `.github/workflows/pr.yml`. Locally, run `make up` first.
- **No-cluster-writes invariant (`feat_ubi_judgments`):** RelyLoop only
  *reads* the UBI indices, never writes to a cluster. The pattern for
  asserting this is in
  [`backend/tests/unit/services/test_ubi_reader_no_writes.py`](../../backend/tests/unit/services/test_ubi_reader_no_writes.py):
  boot a real `ElasticAdapter` against an `httpx.MockTransport` that
  records every `(method, path)`, run the reader end-to-end, then assert
  no recorded call used a write method (`PUT`/`DELETE`/`PATCH`) or a
  write-shaped path segment (`_bulk`/`_update`/`_doc`/`_create`). Use the
  same transport-recording shape for any future read-only adapter
  surface.
- Tests that depend on the API itself running should use the
  `_api_reachable()` helper to skip cleanly when the API isn't up — that's
  acceptable (CI doesn't boot the API in MVP1; deploy job comes at MVP3).

### Contract tests

- One contract test file per accepted endpoint
- Assert response JSON shape matches FastAPI's `app.openapi()` schema
- Verify error codes per `docs/01_architecture/api-conventions.md`
  "Standard error codes"
- No DB; mock dependencies via `app.dependency_overrides` and `monkeypatch`

### E2E tests (lands with `feat_studies_ui`)

- Playwright against the real backend at `localhost:8000`
- **No `page.route()` mocking of backend endpoints** — tests must exercise
  the real HTTP path
- Use `page` (browser interactions) for assertions; `request` only for
  test setup (creating clusters, seeding judgments, etc.)

#### Real-backend Playwright suite inventory

The specs below run against the live `make up` stack. Heavy specs
self-skip when `SKIP_HEAVY_CI=true` is set.

| Spec | Heavy lane? | Coverage |
|---|---|---|
| `dashboard-reseed.spec.ts` | No | Dashboard reset-to-demo affordance |
| `ubi-onramp-rung-0.spec.ts` | No | Rung_0 nudge + LLM default + dismissal |
| `ubi-onramp-rung-3.spec.ts` | No | Rung_3 default → CTR converter → click judgments |
| `demo-ubi.spec.ts` | Yes | 5 synthetic-UBI surfaces post-reseed (FR-7 + FR-12 of `feat_demo_ubi_study_comparison`); includes the chip-absent negative case on `news-search-staging` |

#### Synthetic-UBI integration tests

| File | Lane | Wall-clock | Coverage |
|---|---|---|---|
| `backend/tests/integration/test_demo_seeding_ubi_fast.py` | Always-on | <60s | Generator → writer → classifier round-trip; allowlist guard; mapping JSON shape |
| `backend/tests/integration/test_demo_seeding_ubi_full.py` | Heavy (`SKIP_HEAVY_CI` gated) | 13–19 min | Full `reseed_demo_state` orchestrator; AC-1 (8 lists + 8 studies); AC-10 (cleanup deletes UBI indices) |

## Adding tests for a new feature

The "test completeness rule" from CLAUDE.md: a feature is not complete until
it has tests at every layer it touches.

| New surface | Required test layer |
|---|---|
| Pure domain function | Unit (`backend/tests/unit/domain/`) |
| Service function (touches DB / external services) | Integration |
| API endpoint | Contract (response shape + error codes) |
| Webhook handler | Integration (idempotency assertion) |
| User-facing UI flow | E2E (when E2E lands) |

Every accepted endpoint needs a contract test asserting response shape +
documented error codes (per spec §7.5 and api-conventions.md).

### Frontend-specific: column-config discipline (`feat_data_table_primitive`)

`<DataTable>` consumers export a co-located column config that drives the
toolbar's enum / FK filters. The Story 2.13 lint guard at
[`ui/src/__tests__/components/common/data-table-column-discipline.test.tsx`](../../ui/src/__tests__/components/common/data-table-column-discipline.test.tsx)
scans every `*.column-config.{ts,tsx}` under `ui/src/components/**` and
fails the suite when:

- A `filter: { kind: 'enum', ... }` entry uses an inline `wireValues: [...]`
  array instead of importing the identifier from `@/lib/enums`.
- The imported identifier's declaration in `enums.ts` is missing the
  canonical `// Values must match backend/...py <Symbol>` comment.
- A `filter` entry (enum or fk-select) is missing its `sourceOfTruth: '...'`
  string or its value doesn't start with `backend/`.

The test is pure-Node (no DOM), runs in well under 100 ms, and is the only
test in the project that scans the live source tree for a static invariant.
Five regression cases pin the failure-message contract so the next contributor
sees a useful diagnostic on a real violation.

### Frontend-specific: Pydantic-discriminator parity (`feat_create_study_search_space_builder`)

Some wire-value enums live in a Pydantic discriminated union rather than in
[`ui/src/lib/enums.ts`](../../ui/src/lib/enums.ts) — the `form-select-discipline.test.tsx`
lint guard above does NOT catch drift in those cases because the values aren't
imported from `enums.ts`. The canonical example is
`ParamSpec.type` (`float` / `int` / `categorical`) which lives in
[`backend/app/domain/study/search_space.py`](../../backend/app/domain/study/search_space.py)'s
discriminated union over `FloatParam | IntParam | CategoricalParam`.

For these cases, the source-of-truth gate is a dedicated parity test that reads
the backend file at runtime, extracts the `Literal["..."]` values via regex,
and asserts the frontend's option array matches one-for-one. The canonical
first instance is
[`ui/src/__tests__/components/studies/search-space-builder/param-spec-discriminator.parity.test.tsx`](../../ui/src/__tests__/components/studies/search-space-builder/param-spec-discriminator.parity.test.tsx).

Pattern: use `fs.readFileSync(path.join(process.cwd(), '..', 'backend/...py'), 'utf-8')`
(vitest cwd is `ui/`, so `..` resolves to repo root), then
`source.matchAll(/type:\s*Literal\["([^"]+)"\]/g)`. Assert against the typed
array imported from the frontend component. Any future spec that adds a new
variant to the discriminated union must update both sides in the same PR, or
the parity test fails on next CI run.

## Benchmarks (opt-in)

Performance budgets are enforced by benchmark tests under
[`backend/tests/benchmarks/`](../../backend/tests/benchmarks/), marked with
`@pytest.mark.benchmark` so they don't run as part of the default
`make test-unit` / `make test-contract` flow. Opt in via:

```bash
uv run pytest -m benchmark backend/tests/benchmarks/
```

First-shipped benchmark: `test_scoring_perf.py` (from `infra_optuna_eval`)
asserts `backend.app.eval.scoring.score` completes in <100ms per query for
a 50-query × top_k=10 fixture (spec §FR-3 SHOULD).

## Testing the `run_trial` worker

The hot-path Arq job at [`backend/workers/trials.py`](../../backend/workers/trials.py)
is exercised at three test layers:

* **Unit** — `backend/tests/unit/workers/test_trials_unit.py`. Tests the
  `_snapshot_optuna_trial` helper and the state-specific
  `_reconstruct_from_optuna` reconciliation (COMPLETE / FAIL / PRUNED) via
  `AsyncMock` — no real Postgres or Optuna storage.
* **Integration** — six modules under `backend/tests/integration/`
  (test_run_trial.py, test_run_trial_adapter_failure.py,
  test_run_trial_idempotent_retry.py, test_run_trial_partial_failure.py,
  test_pruner_defaults.py, test_optuna_rdb.py). Each:
  * skips when Postgres isn't reachable (CI provides it as a service
    container);
  * uses `setup_study_with_cluster()` from
    `backend/tests/integration/fixtures/run_trial_setup.py` to create the
    cluster / template / query_set / study rows;
  * simulates Phase 2's orchestrator via
    `create_optuna_trial_for_study()` (which calls `study.ask()` AND
    `trial.suggest_*()` to populate params before the worker runs);
  * installs a `StubAdapter` (from `fixtures/stub_adapter.py`) via
    `monkeypatch` so AC-7's "exactly one _msearch, zero _search" assertion
    is verified by stub call recording (no real ES + no cassette).
* **Contract** — `backend/tests/contract/test_trial_row_shape.py` asserts
  the `Trial` ORM row's FR-5 invariants after a happy-path run.

For partial-failure tests (AC-8b) the worker runs in a subprocess via
`backend/tests/integration/_subprocess_helpers/run_trial_with_test_stubs.py`,
which reinstalls the qrels + adapter stubs inside the child process from
env-var-passed JSON (pytest monkeypatches do not survive into a fresh
interpreter). Fault injection is via the `INFRA_OPTUNA_EVAL_FAULT` env
var, which triggers `os._exit(1)` at one of two seams
(`after_trial_load_before_execute`, `after_tell_before_insert`).

## Generated-artifact freshness gates

Three CI gates catch the failure mode where a developer edits a source
file but forgets to regenerate the committed artifact built from it. Each
gate **regenerates** the artifact in CI and fails the PR if
`git status --porcelain` reports drift — a contributor never has to
remember to run a regen step locally before pushing; CI does it for them
and the gate's failure output prints the one-paste fix command.

Why `git status --porcelain` (and not `git diff --exit-code`): `git diff`
silently ignores untracked files. A freshly-added `DOCS` entry whose
public copy was never committed would slip through. `--porcelain` reports
the modified, untracked, AND deleted cases (the `M` / `??` / ` D`
markers) — every drift mode the gate exists to catch.

| # | Gate | Workflow | Source → Output | Regenerator | Self-test |
|---|---|---|---|---|---|
| 1 | `copy-docs-freshness` | own file (`copy-docs-freshness.yml`) — runs on every PR with no `paths-ignore` filter (FR-3 escape from `pr.yml`'s `docs/**` paths-ignore so docs-only PRs still get the check) | `docs/08_guides/*.md` → `ui/public/docs/*.md` | `node ui/scripts/copy-docs.mjs` (prunes the dest to `{README.md} ∪ {DOCS[].dest}` per FR-9, so a renamed entry never leaves a stale public copy behind) | `scripts/ci/test_verify_copy_docs_fresh.sh` exercises clean / source-drift / untracked-AC-9 cases against a disposable `mktemp` git fixture |

The fix command printed on failure:

```bash
cd ui && node scripts/copy-docs.mjs && git add public/docs
```

The freshness-gate scripts (`scripts/ci/verify_copy_docs_fresh.sh` + its
self-test) follow the canonical `scripts/ci/` shape: `set -euo pipefail`,
SPDX header, `git status --porcelain` (never bare `git diff`), and a
sibling `test_<name>.sh` that drives the guard against disposable
fixtures.

## Where to look

- [`backend/tests/conftest.py`](../../backend/tests/conftest.py) — shared
  fixtures (currently a stub; populated as features land)
- [`backend/tests/unit/test_health.py`](../../backend/tests/unit/test_health.py) —
  exemplar handler test (status mapping, parallel probes, timeout fallback)
- [`backend/tests/unit/test_capability_check.py`](../../backend/tests/unit/test_capability_check.py) —
  exemplar httpx-mocked external-service test
- [`backend/tests/contract/test_health_contract.py`](../../backend/tests/contract/test_health_contract.py) —
  exemplar contract test (OpenAPI shape + 200/503 paths)
- [`pyproject.toml`](../../pyproject.toml) `[tool.coverage.report]` — gate config
