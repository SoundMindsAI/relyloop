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
- CI provides Postgres + Redis + ES + OpenSearch via service containers in
  `.github/workflows/pr.yml`. Locally, run `make up` first.
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
