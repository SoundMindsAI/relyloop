# Implementation Plan — infra_foundation

**Date:** 2026-05-09
**Status:** Draft
**Primary spec:** [`feature_spec.md`](feature_spec.md)
**Policy sources:**
- [`docs/01_architecture/tech-stack.md`](../../../01_architecture/tech-stack.md) — language/framework/tooling choices
- [`docs/01_architecture/deployment.md`](../../../01_architecture/deployment.md) — Compose layout + secrets
- [`docs/01_architecture/api-conventions.md`](../../../01_architecture/api-conventions.md) — endpoint conventions + error envelope
- [`docs/01_architecture/system-overview.md`](../../../01_architecture/system-overview.md) — service inventory
- [`docs/01_architecture/llm-orchestration.md`](../../../01_architecture/llm-orchestration.md) — capability check at startup
- [`docs/01_architecture/mvp1-overview.md`](../../../01_architecture/mvp1-overview.md) — MVP1 reading guide

**Cross-model review status:** **Skipped** — no `.env` at repo root, `OPENAI_API_KEY` not available; ran Opus-only Pass 1 + Pass 2 internal review (see §13 Review log).

---

## 0) Planning principles

- **Spec traceability first.** Every story maps to one or more FR IDs (§17 spec traceability). Every FR is owned by exactly one story (no ownership ambiguity).
- **Greenfield = no codebase verification.** This is the bootstrap feature; there is no existing code to grep against. "Verify path against codebase" steps degrade to "verify path against the architecture docs and the spec."
- **Boot order matters.** Compose health-check sequencing (Postgres → API/worker) is load-bearing. Story 4.2's `depends_on` blocks are the source of truth.
- **Every Make target the spec promises must work** (`fmt`, `lint`, `typecheck`, `test`, `up`, `down`, `migrate`, `migrate-create`). AC-8 verifies discoverability via `make` (no target).
- **Single-phase ship.** Spec §3 Phase boundaries: "everything in scope ships in one PR." No `phase2_idea.md`.

---

## 1) Scope traceability (FR → epics/stories)

| FR | Description | Owning epic / story | ACs covered | Test files |
|---|---|---|---|---|
| **FR-1** | One-command boot of 6-container stack, all healthy in 60s | Epic 4 / Stories 4.1, 4.2, 4.4 | AC-1, AC-2 | `backend/tests/integration/test_health_integration.py` |
| **FR-2** | `GET /healthz` reports subsystem status (200/503) | Epic 3 / Stories 3.1, 3.2 | AC-3, AC-4 | `backend/tests/unit/test_health.py`, `backend/tests/contract/test_health_contract.py` |
| **FR-3** | Secrets via mounted files; `*_FILE` env vars only | Epic 2 / Story 2.1 (Pydantic Settings); Epic 4 / Story 4.4 (`.env.example` + install script) | AC-1, AC-4 | `backend/tests/unit/test_settings.py` |
| **FR-4** | CI workflow runs lint/typecheck/test with 80% coverage gate | Epic 5 / Story 5.1 | AC-5, AC-6 | (workflow itself) |
| **FR-5** | Alembic migration scaffold + `make migrate` (with Optuna RDB stub) | Epic 2 / Story 2.2 | AC-7 | `backend/tests/integration/test_migrations.py` |
| **FR-6** | Conventional Commits enforced via pre-commit | Epic 1 / Story 1.4 | (no AC; hook) | (hook itself) |
| **FR-7** | OpenAI-compatible capability check at startup, cached in Redis | Epic 3 / Story 3.3 | (covered by AC-4 + AC-3 indirectly) | `backend/tests/unit/test_capability_check.py` |

**Deferred phases:** None — single-phase ship per spec §3.

**FR coverage check:** 7 FRs in spec, 7 FRs assigned, 0 orphan. ✓

---

## 2) Delivery structure

### Conventions (RelyLoop, MVP1)

These conventions apply to every story. They are derived from [`tech-stack.md`](../../../01_architecture/tech-stack.md) and [`api-conventions.md`](../../../01_architecture/api-conventions.md):

**Backend (Python):**
- Python 3.12+, `mypy --strict`, no `Any` without explicit annotation
- ruff (`check` + `format`), rule set: defaults + `B` (bugbear), `S` (security/bandit), `UP` (pyupgrade), `D` (docstrings)
- 100-char line limit
- snake_case for variables/functions/modules; PascalCase for classes; SCREAMING_SNAKE for constants
- Public functions/classes/modules have Google-style docstrings
- All Pydantic models have field descriptions (used in OpenAPI auto-generation)
- Settings via `pydantic-settings`; `*_FILE` env vars for secrets — **bare env vars (e.g., `OPENAI_API_KEY=sk-...`) are NOT supported**
- Logs: structured JSON via `structlog` to stdout
- HTTP endpoints: business endpoints prefixed `/api/v1/<resource>`; operator endpoints unversioned (e.g., `/healthz`)
- Error envelope: `{ "detail": { "error_code": "...", "message": "...", "retryable": <bool> } }`

**Frontend (TypeScript):**
- TypeScript with `--strict` and `noUncheckedIndexedAccess`
- Next.js 14 App Router, server components by default
- 100-char line limit (prettier default)
- camelCase for variables/functions; PascalCase for components/types
- ESLint Next.js + security + react-hooks plugins

**Database:**
- SQLAlchemy 2.0 async via `asyncpg`
- Alembic with `--autogenerate`
- UUIDv7 primary keys (when business tables land in later features); `TIMESTAMPTZ` UTC; `deleted_at` soft-delete on user-facing tables
- snake_case table and column names
- **MVP1 has no business tables** — only the `alembic_version` row

**Secrets:**
- Mounted as files at `/run/secrets/<name>` inside containers
- Pydantic Settings reads via `*_FILE`-suffixed env vars (e.g., `OPENAI_API_KEY_FILE=/run/secrets/openai_key` → settings reads file content)
- Required secrets: `postgres_password`, `database_url` (must be non-empty content)
- Optional secrets: `openai_key`, `github_token`, `cluster_credentials.yaml` (empty content is treated as "not configured" with a startup WARN; mount file must exist for Compose to start)

**Tests:**
- Backend: `backend/tests/{unit,integration,contract}/`
- Frontend: `ui/tests/` (vitest)
- Coverage gate: 80% on backend Python (MVP1 — rises to 90% at GA v1)
- E2E tests use real Playwright `page` interactions (not `page.route()` mocking) — N/A for this feature, no UI flows

**Make targets** (per spec §3 + AC-8):
`fmt`, `lint`, `typecheck`, `test`, `up`, `down`, `logs`, `reset`, `migrate`, `migrate-create`, plus a default `help` target listing all targets with one-line descriptions

### AI Agent Execution Protocol (applies to every story)

0. **Load context first**: Read [`feature_spec.md`](feature_spec.md), [`tech-stack.md`](../../../01_architecture/tech-stack.md), [`deployment.md`](../../../01_architecture/deployment.md), and [`api-conventions.md`](../../../01_architecture/api-conventions.md). The repo has no `state.md` / `architecture.md` / `CLAUDE.md` at root yet; those are partial outputs of this very feature.
1. **Read scope**: verify story Outcome + New files + Modified files + DoD.
2. **Implement backend first**: settings → models (none in MVP1) → migration → router → schemas → main.py wiring.
3. **Run backend tests**: `make test-unit` minimum; `make test-integration` for Docker-dependent stories.
4. **Implement frontend** (Story 1.3 only — placeholder `/` page).
5. **E2E**: N/A (no UI flows in this feature).
6. **Update docs**: Story 5.2 owns the consolidated doc updates; per-story doc updates only if they touch documented behavior.
7. **Verify migration round-trip** (Story 2.2): `alembic upgrade head` → `alembic downgrade -1` → `alembic upgrade head` returns to head cleanly.
8. **Attach evidence** in the per-story PR comment (or commit body): commands run, pass/fail, files changed.
9. **After the final story**, create `state.md`, `architecture.md`, and `CLAUDE.md` at repo root (Story 5.2 owns this — they don't exist yet).

Story completion is invalid if any step is skipped without explicit justification.

---

## Epic 1 — Project scaffolding & toolchain

**Outcome:** A clean monorepo with Python and frontend toolchains wired up, every `make` target stubbed, and pre-commit hooks running locally. No application code yet.

**Epic gate:** `make fmt && make lint && make typecheck` exits 0 on a fresh clone after `uv sync` + `pnpm install`.

### Story 1.1 — Monorepo layout & root configs

**Outcome:** Repo has the canonical top-level directory layout per [`tech-stack.md` §"Code organization"](../../../01_architecture/tech-stack.md), with empty placeholders ready for subsequent stories. Root `Makefile` lists every promised target.

**New files**

| File | Purpose |
|---|---|
| `Makefile` | All targets per spec §3 + AC-8: `help` (default), `fmt`, `lint`, `typecheck`, `test`, `test-unit`, `test-integration`, `test-contract`, `up`, `down`, `logs`, `reset`, `migrate`, `migrate-create`. `help` parses `## comment` lines and prints them. |
| `.editorconfig` | Cross-editor consistency: UTF-8, LF, trim trailing WS, 4-space indent for Python, 2-space for TS/JSON/YAML. |
| `.gitignore` | `.env`, `./secrets/`, `./data/`, `__pycache__/`, `*.pyc`, `.venv/`, `node_modules/`, `.next/`, `dist/`, `coverage/`, `htmlcov/`, `.coverage`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.DS_Store` |
| `.gitattributes` | `* text=auto eol=lf`; binary patterns for images and archives |
| `backend/.keep` | Empty placeholder — replaced by Story 1.2 |
| `ui/.keep` | Empty placeholder — replaced by Story 1.3 |
| `worker/.keep` | Empty placeholder — Arq config lands in Story 4.3 |
| `migrations/.keep` | Empty placeholder — Alembic init lands in Story 2.2 |
| `prompts/.keep` | Empty placeholder — populated by `feat_llm_judgments`, `feat_digest_proposal`, `feat_chat_agent` |
| `templates/.keep` | Empty placeholder — populated by `infra_adapter_elastic` |
| `samples/.keep` | Empty placeholder — populated by `chore_tutorial_polish` |
| `scripts/install.sh` | Stub — full implementation in Story 4.4 (generates required+optional secrets, then invokes `docker compose up -d`) |
| `secrets/.gitkeep` | Empty marker — `./secrets/` directory must exist for Compose to mount; gitignore excludes contents |

**Modified files**

| File | Change |
|---|---|
| `README.md` | Add a "Quickstart" stub pointing at `make up` (full quickstart in Story 5.2). Update "What's in this repo today" to mention infra is being scaffolded. |

**Tasks**
1. Create the top-level directory layout with `.keep` placeholders so subsequent stories have a known landing site.
2. Write the `Makefile` with all targets per AC-8. Each target prints a one-line description under `make help`.
3. Stub `scripts/install.sh` to `echo "TODO: secrets generation"` + `docker compose up -d` (exit 0). Story 4.4 fills in the body.
4. Write `.gitignore`, `.editorconfig`, `.gitattributes`.
5. Update `README.md` "What's in this repo" line and add a Quickstart placeholder.
6. Verify on a fresh clone: `git clone … && make help` lists every target with descriptions.

**Definition of Done (DoD)**
- [ ] `make help` (or bare `make`) prints every target listed above with one-line descriptions (AC-8 partial — AC-8 fully met after Story 4.4 wires the targets).
- [ ] `git status` after clone-and-make-help is clean (no untracked files generated).
- [ ] `.gitignore` excludes `.env`, `./secrets/*` (except `.gitkeep`), `./data/`.

### Story 1.2 — Python project (`uv`, ruff, mypy, pytest)

**Outcome:** `backend/` is a Python project managed by `uv` with ruff + mypy --strict + pytest configured. `make fmt`, `make lint`, `make typecheck`, `make test-unit` all exit 0 on the empty project.

**New files**

| File | Purpose |
|---|---|
| `pyproject.toml` (repo root) | Single-package layout: `[project]` (name=`relyloop`, version=`0.1.0`, requires-python=`>=3.12`, dependencies). `[tool.uv]`, `[tool.ruff]`, `[tool.ruff.lint]` (rule selection), `[tool.ruff.format]`, `[tool.mypy]` (strict), `[tool.pytest.ini_options]`, `[tool.coverage.run]`, `[tool.coverage.report]` (`fail_under = 80`). `[tool.hatch.build.targets.wheel]` includes `backend/`. |
| `uv.lock` | Generated by `uv sync`; checked in. |
| `backend/__init__.py` | Empty marker. |
| `backend/app/__init__.py` | Empty marker. |
| `backend/app/main.py` | Stub `app = FastAPI()` with no routers — Story 3.1 expands. |
| `backend/tests/__init__.py` | Empty marker. |
| `backend/tests/unit/__init__.py` | Empty marker. |
| `backend/tests/integration/__init__.py` | Empty marker. |
| `backend/tests/contract/__init__.py` | Empty marker. |
| `backend/tests/conftest.py` | Pytest fixtures stub (empty for now; Story 3.2+ will add `httpx.AsyncClient` fixture). |
| `backend/tests/unit/test_smoke.py` | Single test: `def test_python_works(): assert 1 + 1 == 2` — proves toolchain is wired. |

**Modified files**

| File | Change |
|---|---|
| `Makefile` | Wire `fmt` → `uv run ruff format .`; `lint` → `uv run ruff check .`; `typecheck` → `uv run mypy backend/`; `test-unit` → `uv run pytest backend/tests/unit/`; `test-integration` → `uv run pytest backend/tests/integration/ -m integration`; `test-contract` → `uv run pytest backend/tests/contract/`; `test` → `make test-unit && make test-integration && make test-contract`. |

**Key dependencies (added to `pyproject.toml`)**

```toml
[project]
dependencies = [
  "fastapi >= 0.115",
  "uvicorn[standard] >= 0.32",
  "pydantic >= 2.9",
  "pydantic-settings >= 2.6",
  "sqlalchemy[asyncio] >= 2.0.36",
  "asyncpg >= 0.30",
  "alembic >= 1.14",
  "redis >= 5.2",
  "httpx >= 0.28",
  "openai >= 1.55",
  "structlog >= 24.4",
  "arq >= 0.26",
]

[dependency-groups]
dev = [
  "ruff >= 0.8",
  "mypy >= 1.13",
  "pytest >= 8.3",
  "pytest-asyncio >= 0.24",
  "pytest-cov >= 6.0",
  "pytest-mock >= 3.14",
  "pytest-recording >= 0.13",
]
```

**Key configuration (`pyproject.toml` highlights)**

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "W", "B", "S", "UP", "D"]
ignore = ["D100", "D104"]  # missing module / package docstrings

[tool.ruff.lint.per-file-ignores]
"backend/tests/**" = ["S101", "D"]  # asserts and docstrings ok in tests

[tool.mypy]
strict = true
python_version = "3.12"
plugins = ["pydantic.mypy"]
files = ["backend"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
  "integration: requires Docker / external services",
]

[tool.coverage.run]
source = ["backend"]
omit = ["backend/tests/*"]

[tool.coverage.report]
fail_under = 80
show_missing = true
```

**Tasks**
1. Run `uv init --package relyloop --bare` (or write `pyproject.toml` from scratch per the snippet above).
2. Run `uv add fastapi uvicorn[standard] pydantic pydantic-settings 'sqlalchemy[asyncio]' asyncpg alembic redis httpx openai structlog arq` to install runtime deps and produce `uv.lock`.
3. Run `uv add --dev ruff mypy pytest pytest-asyncio pytest-cov pytest-mock pytest-recording`.
4. Write the ruff/mypy/pytest/coverage config blocks shown above into `pyproject.toml`.
5. Stub `backend/app/main.py` with `from fastapi import FastAPI; app = FastAPI(title="RelyLoop", version="0.1.0")`.
6. Write `backend/tests/unit/test_smoke.py` with the trivial assertion.
7. Wire `Makefile` targets to `uv run …` commands.
8. Verify: `make fmt && make lint && make typecheck && make test-unit` all exit 0.

**Definition of Done (DoD)**
- [ ] `uv sync` completes from a fresh clone.
- [ ] `make fmt` formats with ruff (no diff on a clean tree).
- [ ] `make lint` exits 0 (ruff check passes).
- [ ] `make typecheck` exits 0 (mypy --strict on `backend/`).
- [ ] `make test-unit` exits 0 (smoke test passes).
- [ ] `pyproject.toml` declares Python `>=3.12` and pins ruff/mypy/pytest in dev deps.

### Story 1.3 — Frontend project (Next.js 14, pnpm, TS strict)

**Outcome:** `ui/` is a Next.js 14 App Router project managed by pnpm. The placeholder `/` page renders "RelyLoop is running. See [docs/](../../docs/) for getting started." Lint, typecheck, build, and vitest all exit 0.

**Note on directory naming:** Spec §14 references `web/tests/e2e/`, but [`tech-stack.md` §"Code organization"](../../../01_architecture/tech-stack.md), [`deployment.md`](../../../01_architecture/deployment.md), and [`system-overview.md`](../../../01_architecture/system-overview.md) all use `ui/`. **Using `ui/` as canonical** — this feature has no E2E tests, so the §14 typo is functionally moot; later UI features should write E2E tests to `ui/tests/e2e/`.

**New files**

| File | Purpose |
|---|---|
| `ui/package.json` | name=`relyloop-ui`, private=true, scripts (`dev`, `build`, `start`, `lint`, `typecheck`, `test`), Next.js + React + TypeScript + Tailwind + shadcn-base deps |
| `ui/pnpm-lock.yaml` | Generated by `pnpm install`; checked in |
| `ui/tsconfig.json` | `--strict`, `noUncheckedIndexedAccess`, App Router config |
| `ui/next.config.mjs` | App Router defaults; no experimental features |
| `ui/.eslintrc.json` | Extends `next/core-web-vitals`, plus security plugin |
| `ui/.prettierrc.json` | 100-char line, single-quote, trailing-comma=`all` |
| `ui/postcss.config.mjs` | Tailwind + autoprefixer |
| `ui/tailwind.config.ts` | Default content globs for App Router |
| `ui/src/app/layout.tsx` | Root layout with `<html>`/`<body>`; loads global Tailwind CSS |
| `ui/src/app/page.tsx` | Placeholder home page: heading "RelyLoop is running" + link to docs |
| `ui/src/app/globals.css` | Tailwind directives (`@tailwind base; @tailwind components; @tailwind utilities`) |
| `ui/src/__tests__/page.test.tsx` | vitest smoke test: renders `<Page />`, asserts heading text present |
| `ui/vitest.config.ts` | jsdom env, includes `src/**/*.test.{ts,tsx}` |
| `ui/.gitignore` | `node_modules/`, `.next/`, `dist/`, `out/` |

**Modified files**

| File | Change |
|---|---|
| `Makefile` | Add UI target wiring: `fmt` runs `cd ui && pnpm format`; `lint` runs `cd ui && pnpm lint` after backend lint; `typecheck` runs `cd ui && pnpm typecheck`; new target `ui-build` → `cd ui && pnpm build`; `test` includes `cd ui && pnpm test` after backend tests. |
| `.gitignore` (root) | Already covers `node_modules/`, `.next/` from Story 1.1; verify. |

**UI element inventory** (placeholder page only)

| Element | Type | Source | Notes |
|---|---|---|---|
| Heading "RelyLoop is running" | `<h1>` | static | Single visible element |
| Link "See docs/ for getting started." | `<a href="/docs">` (or relative) | static | Points at the docs portal once it's wired; for MVP1 link to `https://github.com/SoundMindsAI/relyloop/tree/main/docs` |

No state, no props, no interactions. **No legacy behavior parity table** — no user-facing component being deleted or replaced.

**Tasks**
1. Run `pnpm create next-app@latest ui --typescript --tailwind --eslint --app --src-dir --no-import-alias` (then prune the boilerplate page).
2. Replace `ui/src/app/page.tsx` with the placeholder.
3. Add `vitest` + `@testing-library/react` + `@testing-library/jest-dom` + `jsdom` as devDeps.
4. Write `ui/src/__tests__/page.test.tsx` rendering `<Page />` and asserting `getByRole('heading')` text.
5. Wire `pnpm test` → `vitest run`; `pnpm typecheck` → `tsc --noEmit`.
6. Wire Makefile targets per the modified-files table.
7. Verify: `cd ui && pnpm install && pnpm lint && pnpm typecheck && pnpm test && pnpm build` all exit 0.

**Definition of Done (DoD)**
- [ ] `cd ui && pnpm install` succeeds from a fresh clone.
- [ ] `cd ui && pnpm dev` serves `/` showing "RelyLoop is running" + docs link.
- [ ] `cd ui && pnpm lint` exits 0 (ESLint Next.js + security).
- [ ] `cd ui && pnpm typecheck` exits 0 (`tsc --noEmit --strict --noUncheckedIndexedAccess`).
- [ ] `cd ui && pnpm test` exits 0 (vitest smoke).
- [ ] `cd ui && pnpm build` exits 0 (Next.js production build).

### Story 1.4 — Pre-commit hooks (ruff, mypy, eslint, prettier, gitleaks, Conventional Commits)

**Outcome:** `pre-commit install` wires up commit-stage and commit-msg hooks. Every commit is formatted, linted, type-checked, secret-scanned, and CC-validated. **Owns FR-6.**

**New files**

| File | Purpose |
|---|---|
| `.pre-commit-config.yaml` | Hook stages: `pre-commit` (ruff format + check, mypy, eslint, prettier, gitleaks); `commit-msg` (Conventional Commits regex). |
| `scripts/check-conventional-commit.sh` | Regex check for the commit message file passed by `commit-msg` stage. Per spec FR-6: `^(feat|fix|chore|docs|infra|refactor|test|style|perf|build|ci)(\([a-z0-9-]+\))?(!)?:` — print a clear error message on mismatch listing accepted prefixes. |
| `CONTRIBUTING.md` (modified — exists already) | Add "Commit message format" section pointing at the regex; add "Pre-commit hooks" section with `pre-commit install` instruction. |

**Modified files**

| File | Change |
|---|---|
| `pyproject.toml` | Add `pre-commit` to dev deps. |
| `Makefile` | Add `pre-commit` target → `uv run pre-commit run --all-files`. |
| `CONTRIBUTING.md` | Add commit-format + pre-commit setup sections. |

**Hook configuration sketch (`.pre-commit-config.yaml`):**

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
    hooks:
      - id: ruff-format
      - id: ruff
        args: [--fix]

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.13.0
    hooks:
      - id: mypy
        additional_dependencies: [pydantic, sqlalchemy, fastapi, structlog]
        args: [--strict, --config-file=pyproject.toml]
        files: ^backend/

  - repo: https://github.com/pre-commit/mirrors-prettier
    rev: v4.0.0-alpha.8
    hooks:
      - id: prettier
        types_or: [javascript, jsx, ts, tsx, json, yaml, markdown, css]
        exclude: ^(uv\.lock|pnpm-lock\.yaml)$

  - repo: https://github.com/pre-commit/mirrors-eslint
    rev: v9.15.0
    hooks:
      - id: eslint
        files: ^ui/src/.*\.(js|jsx|ts|tsx)$
        additional_dependencies:
          - eslint@9
          - eslint-config-next
          - typescript

  - repo: https://github.com/zricethezav/gitleaks
    rev: v8.21.0
    hooks:
      - id: gitleaks

  - repo: local
    hooks:
      - id: conventional-commit
        name: Conventional Commits format check
        entry: bash scripts/check-conventional-commit.sh
        language: system
        stages: [commit-msg]
```

**Tasks**
1. `uv add --dev pre-commit`.
2. Write `.pre-commit-config.yaml` per the sketch.
3. Write `scripts/check-conventional-commit.sh` with the regex from spec FR-6 and a clear error message listing accepted prefixes (`feat`, `fix`, `chore`, `docs`, `infra`, `refactor`, `test`, `style`, `perf`, `build`, `ci`).
4. Make the script executable: `chmod +x scripts/check-conventional-commit.sh`.
5. Update `CONTRIBUTING.md` with "Commit message format" and "Pre-commit hooks" sections.
6. Add `make pre-commit` target.
7. Verify: `pre-commit install --install-hooks --hook-type commit-msg --hook-type pre-commit`; attempt a commit with a non-CC message → rejected; attempt with a valid CC message → accepted.

**Definition of Done (DoD)**
- [ ] `uv run pre-commit install --hook-type commit-msg --hook-type pre-commit` succeeds.
- [ ] `git commit -m "broken: not a CC type"` is rejected by the `commit-msg` hook with an error listing accepted prefixes.
- [ ] `git commit -m "feat(infra): wire pre-commit"` is accepted.
- [ ] `make pre-commit` runs all hooks against the entire repo and exits 0.
- [ ] gitleaks blocks a commit that contains a fake `AKIA...` AWS key (manual verify; documented in `CONTRIBUTING.md`).
- [ ] `CONTRIBUTING.md` documents the regex + how to install hooks.

---

## Epic 2 — Persistence & migrations

**Outcome:** SQLAlchemy 2.0 async engine is wired, `make migrate` runs Alembic + initializes Optuna's RDB schema, and the baseline migration creates the `alembic_version` table only.

**Epic gate:** `make migrate` against a fresh Postgres applies the baseline migration and the `alembic_version` table exists with the head revision. Round-trip (`alembic downgrade -1 && alembic upgrade head`) returns to head cleanly.

### Story 2.1 — SQLAlchemy 2.0 async engine + Pydantic Settings

**Outcome:** `backend/app/core/settings.py` loads configuration from env + `*_FILE` mounted secrets. `backend/app/db/session.py` exposes an async engine + session factory. **Owns FR-3 application layer** (the `*_FILE` secrets handling).

**New files**

| File | Purpose |
|---|---|
| `backend/app/core/__init__.py` | Empty marker. |
| `backend/app/core/settings.py` | `Settings(BaseSettings)` class: reads `DATABASE_URL_FILE`, `POSTGRES_PASSWORD_FILE`, `REDIS_URL`, `OPENAI_BASE_URL`, `OPENAI_API_KEY_FILE`, `OPENAI_MODEL`, `OPENAI_MODEL_CHAT`, `GITHUB_TOKEN_FILE`, `CLUSTER_CREDENTIALS_FILE`, `OPENAI_DAILY_BUDGET_USD`, `RELYLOOP_GIT_SHA`, `ES_HEAP_SIZE`. Custom field validators read `*_FILE` paths and return file content (or `None` for empty/missing optional secrets; raises for empty/missing required secrets at API startup). |
| `backend/app/db/__init__.py` | Empty marker. |
| `backend/app/db/session.py` | `engine = create_async_engine(settings.database_url, …)`, `async_session_factory = async_sessionmaker(engine, expire_on_commit=False)`, `async def get_db() -> AsyncIterator[AsyncSession]` dependency. |
| `backend/app/db/base.py` | `class Base(DeclarativeBase): pass` — empty registry; subclasses arrive with future feature migrations. |
| `backend/tests/unit/test_settings.py` | Tests `*_FILE` resolution: required-secret missing → raises; optional-secret missing → `None`; optional-secret empty → `None`; valid file → content stripped of trailing newline. Uses `tmp_path` + `monkeypatch.setenv`. |

**Key interfaces**

```python
# backend/app/core/settings.py
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, env_prefix="", extra="ignore")

    # Required (startup fails if missing/empty)
    database_url_file: Path = Field(description="Path to file containing Postgres URL")
    postgres_password_file: Path = Field(description="Path to file containing Postgres password")

    # Optional (empty/missing → not configured, startup warning)
    openai_api_key_file: Path | None = None
    github_token_file: Path | None = None
    cluster_credentials_file: Path | None = None

    # Plain values
    redis_url: str = "redis://redis:6379/0"
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-2024-08-06"
    openai_model_chat: str = "gpt-4o-mini-2024-07-18"
    openai_daily_budget_usd: float = 10.0
    relyloop_git_sha: str = "dev"
    es_heap_size: str = "512m"

    @cached_property
    def database_url(self) -> str:
        """Read DATABASE_URL from the mounted secret file."""
        content = self.database_url_file.read_text().strip()
        if not content:
            raise SettingsError("DATABASE_URL_FILE points at empty file")
        return content

    @cached_property
    def openai_api_key(self) -> str | None:
        """Read OpenAI key from mounted file. Returns None if missing or empty."""
        if self.openai_api_key_file is None or not self.openai_api_key_file.exists():
            return None
        content = self.openai_api_key_file.read_text().strip()
        return content or None

    # ...same pattern for github_token, cluster_credentials_yaml...

@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


# backend/app/db/session.py
engine = create_async_engine(get_settings().database_url, echo=False, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
```

**Modified files**

| File | Change |
|---|---|
| `backend/app/main.py` | Import `get_settings()` for startup validation (Story 3.1 expands this further). |

**Tasks**
1. Write `backend/app/core/settings.py` per the interface above. Use `pydantic-settings` v2 patterns.
2. Write `backend/app/db/session.py` and `backend/app/db/base.py`.
3. Write `backend/tests/unit/test_settings.py` covering: required-missing, optional-missing, optional-empty, valid-content, content-with-trailing-newline.
4. Verify: `make test-unit` includes `test_settings.py` and passes; `make typecheck` clean.

**Definition of Done (DoD)**
- [ ] `Settings` class loads required secrets via `*_FILE` paths; raises clearly on missing/empty required secrets.
- [ ] Optional secrets return `None` for missing/empty; do not raise.
- [ ] Bare env vars (e.g., `DATABASE_URL=postgres://...`) are NOT supported — only `*_FILE` variants. Documented in the docstring of each secret field.
- [ ] `test_settings.py` covers required, optional, empty, and valid-content cases. `make test-unit` exits 0.
- [ ] `mypy --strict backend/` exits 0 (Pydantic plugin used).

### Story 2.2 — Alembic init + baseline migration + `make migrate` + Optuna RDB stub

**Outcome:** Alembic is initialized at `migrations/`, the baseline migration creates the `alembic_version` table only, `make migrate` runs `alembic upgrade head` AND a stub helper that initializes Optuna's RDB schema (no-op MVP1 — becomes load-bearing when `infra_optuna_eval` ships). **Owns FR-5.**

**New files**

| File | Purpose |
|---|---|
| `alembic.ini` (repo root) | `script_location = migrations`, `sqlalchemy.url` left blank (overridden by `env.py`), `file_template` for revision filenames |
| `migrations/env.py` | Alembic env: imports `Base` from `backend.app.db.base`, reads `DATABASE_URL` from `Settings`, supports both online and offline modes with async engine wrapper |
| `migrations/script.py.mako` | Default Alembic revision template (modified to include `from typing import Sequence`) |
| `migrations/versions/<rev>_baseline.py` | Empty `upgrade()` and `downgrade()` (Alembic creates `alembic_version` table automatically when `upgrade head` runs against a fresh DB; the baseline migration is the marker that "we're at the start") |
| `backend/app/db/optuna_schema.py` | `def init_optuna_schema(database_url: str) -> None:` — stub that creates the `optuna` schema (`CREATE SCHEMA IF NOT EXISTS optuna`) but does NOT create Optuna's tables (those land when `infra_optuna_eval` adds Optuna as a dependency and calls `optuna.create_study(storage=...)` for the first time). Logs at INFO. |
| `backend/tests/integration/test_migrations.py` | Marked `@pytest.mark.integration`. Spins up Postgres via Compose (or testcontainers), runs `alembic upgrade head`, asserts `alembic_version` row exists with the head revision. Then runs `alembic downgrade -1 && alembic upgrade head`; asserts head is restored. |

**Modified files**

| File | Change |
|---|---|
| `Makefile` | `migrate` → `uv run alembic upgrade head && uv run python -m backend.app.db.optuna_schema`. `migrate-create` → `uv run alembic revision --autogenerate -m "$(name)"` (validates `$(name)` is set). |
| `pyproject.toml` | Already has `alembic` from Story 1.2 deps. |

**Key interfaces**

```python
# backend/app/db/optuna_schema.py
def init_optuna_schema(database_url: str) -> None:
    """Create the `optuna` schema in Postgres (no-op if exists).

    Optuna's RDBStorage creates its own tables on first use; this function only
    ensures the schema namespace exists so Optuna's CREATE TABLE statements
    target `optuna.*` instead of `public.*`. Become load-bearing when
    infra_optuna_eval ships its run_trial worker.
    """

# Run as a script (per the Makefile target)
if __name__ == "__main__":
    from backend.app.core.settings import get_settings
    init_optuna_schema(get_settings().database_url)
```

**Tasks**
1. Run `uv run alembic init migrations` to scaffold `migrations/env.py` + `script.py.mako`.
2. Edit `migrations/env.py`: import `from backend.app.db.base import Base`, set `target_metadata = Base.metadata`, and configure async engine via `engine_from_config` adapted for `asyncpg` (or use Alembic's documented async pattern with `asyncio.run`).
3. Edit `alembic.ini`: set `script_location = migrations`, leave `sqlalchemy.url` empty (env.py provides it from settings), pin `file_template = %%(rev)s_%%(slug)s` (no date prefix; revision IDs are 12-char hex).
4. Run `uv run alembic revision -m "baseline" --rev-id 0001` to create the first migration. Edit it: `def upgrade(): pass; def downgrade(): pass` — `alembic_version` is created automatically by Alembic when `upgrade head` runs.
5. Write `backend/app/db/optuna_schema.py` per the interface. Use `text()` SQL through SQLAlchemy.
6. Wire the Makefile targets.
7. Write `backend/tests/integration/test_migrations.py` — marked `@pytest.mark.integration`; uses `testcontainers` (add as dev dep) or expects a running Postgres at `DATABASE_URL`. Asserts: `alembic upgrade head` succeeds; `SELECT version_num FROM alembic_version` returns the head revision; round-trip works.
8. Verify locally: `make up` (after Story 4.4 lands) → `make migrate` → query `alembic_version` table → see the head revision.

**Definition of Done (DoD)**
- [ ] `alembic.ini` + `migrations/env.py` + `migrations/script.py.mako` + one `versions/<rev>_baseline.py` exist.
- [ ] `make migrate` exits 0 against a fresh Postgres; `alembic_version` table exists with the head revision.
- [ ] `make migrate-create name=<slug>` creates a new revision file in `migrations/versions/`.
- [ ] `init_optuna_schema()` creates the `optuna` namespace if missing; idempotent.
- [ ] `backend/tests/integration/test_migrations.py` passes when Postgres is available; marked `@pytest.mark.integration` so unit-only test runs skip it.
- [ ] `alembic downgrade -1 && alembic upgrade head` round-trip succeeds.
- [ ] AC-7 met: from a fresh DB, `make migrate` creates `alembic_version` and shows the head revision.

---

## Epic 3 — API skeleton & health endpoint

**Outcome:** FastAPI app boots on port 8000, exposes `GET /healthz` reporting subsystem status (200 healthy, 503 degraded), runs an OpenAI-compatible capability check at startup, and emits structured logs.

**Epic gate:** `curl localhost:8000/healthz` against a fully-healthy stack returns HTTP 200 with `status: "ok"` and all 5 subsystems healthy. Stopping any required subsystem returns 503 with that subsystem reported `down` / `unreachable`.

### Story 3.1 — FastAPI app skeleton + structlog + X-Request-ID middleware + error envelope

**Outcome:** FastAPI app starts cleanly, logs JSON to stdout with `request_id` context per request, and uses the structured error envelope for all non-auth errors. Adopts client-supplied `X-Request-ID` header on input; mints UUIDv7 otherwise. (Per [`api-conventions.md` §"Trace / request correlation"](../../../01_architecture/api-conventions.md).)

**New files**

| File | Purpose |
|---|---|
| `backend/app/api/__init__.py` | Empty marker. |
| `backend/app/api/errors.py` | `ErrorEnvelope(BaseModel)` (with `error_code`, `message`, `retryable`); `ErrorResponse(BaseModel)` wrapping `detail: ErrorEnvelope`; FastAPI exception handlers that translate `HTTPException`, `RequestValidationError`, and `Exception` into the envelope. Handles standard codes per [`api-conventions.md` §"Standard error codes"](../../../01_architecture/api-conventions.md): `VALIDATION_ERROR` (422), `INTERNAL_ERROR` (500), `SERVICE_UNAVAILABLE` (503). |
| `backend/app/core/logging.py` | `configure_logging()` — sets up structlog with JSON renderer, ISO timestamps, `request_id` / `service` / `lvl` / `msg` / `ts` fields. |
| `backend/app/api/middleware.py` | `RequestIDMiddleware` — reads `X-Request-ID` header or mints `uuid7()`, binds to structlog context, echoes back in response header. |
| `backend/tests/unit/test_error_envelope.py` | Tests envelope shape for `HTTPException`, `RequestValidationError`, generic `Exception`. |
| `backend/tests/unit/test_request_id_middleware.py` | Tests: client-supplied X-Request-ID is adopted; missing header mints a new UUID; both paths echo back in response. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/main.py` | Wire `configure_logging()` at module-load; install `RequestIDMiddleware`; install exception handlers from `errors.py`; set `title`, `version` (from `settings.relyloop_git_sha`), `description`. |
| `pyproject.toml` | Add `uuid-utils` (for UUIDv7) to deps if not already pulled in by another package. |

**Endpoints**

No new endpoints in this story (Story 3.2 adds `/healthz`).

**Key interfaces**

```python
# backend/app/api/errors.py
class ErrorEnvelope(BaseModel):
    error_code: str = Field(description="Machine-readable error code; never renamed once shipped")
    message: str = Field(description="Human-readable explanation; can change freely")
    retryable: bool = Field(description="True if the same request may succeed if retried")

class ErrorResponse(BaseModel):
    detail: ErrorEnvelope

async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse: ...
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse: ...
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse: ...

# backend/app/api/middleware.py
class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response: ...

# backend/app/core/logging.py
def configure_logging() -> None: ...
```

**Tasks**
1. Write `backend/app/core/logging.py` configuring structlog (JSON renderer + ISO timestamps + context vars for `request_id`).
2. Write `backend/app/api/errors.py` with the envelope models and three exception handlers (HTTPException, RequestValidationError, Exception).
3. Write `backend/app/api/middleware.py` with `RequestIDMiddleware`. Use `uuid_utils.uuid7()`.
4. Update `backend/app/main.py`:
   ```python
   from .core.logging import configure_logging
   from .core.settings import get_settings
   from .api.middleware import RequestIDMiddleware
   from .api.errors import http_exception_handler, validation_exception_handler, generic_exception_handler

   configure_logging()
   settings = get_settings()
   app = FastAPI(title="RelyLoop", version=settings.relyloop_git_sha, description="Relevance tuning loop API")
   app.add_middleware(RequestIDMiddleware)
   app.add_exception_handler(HTTPException, http_exception_handler)
   app.add_exception_handler(RequestValidationError, validation_exception_handler)
   app.add_exception_handler(Exception, generic_exception_handler)
   ```
5. Write `backend/tests/unit/test_error_envelope.py` and `backend/tests/unit/test_request_id_middleware.py` using `httpx.AsyncClient(app=app, base_url="http://test")` against a temporary route that raises each exception type.
6. Verify: `make test-unit` passes; `make typecheck` clean.

**Definition of Done (DoD)**
- [ ] `uvicorn backend.app.main:app` starts cleanly with structured JSON logs to stdout.
- [ ] Logs include `request_id`, `service`, `lvl`, `msg`, `ts` fields.
- [ ] An unhandled exception returns HTTP 500 with envelope `{"detail": {"error_code": "INTERNAL_ERROR", "message": "...", "retryable": false}}`. Internal traceback is logged but NOT returned in the response body.
- [ ] A request body that fails Pydantic validation returns HTTP 422 with envelope `error_code: "VALIDATION_ERROR"`.
- [ ] Client-supplied `X-Request-ID` is echoed back in the response; missing header mints a UUIDv7.
- [ ] `test_error_envelope.py` and `test_request_id_middleware.py` cover all paths; `make test-unit` exits 0.

### Story 3.2 — `/healthz` endpoint with parallel subsystem probes

**Outcome:** `GET /healthz` returns the JSON shape from spec §7.3 with HTTP 200 (healthy) or 503 (any required subsystem down/unreachable). Probes run in parallel with 200ms-per-subsystem timeouts; total response under 500ms p99. **Owns FR-2 (except OpenAI capability reporting, which is Story 3.3).**

**Note on spec inconsistency:** FR-2 lists `subsystems.openai` enum as `configured | missing_key | incapable`, but spec §7.4 enum table lists only `configured | missing_key`. **Implementing all three states per FR-2.** Will flag this in §13 Review log; suggest spec §7.4 should add `incapable`.

**New files**

| File | Purpose |
|---|---|
| `backend/app/api/health.py` | The `/healthz` router. Defines `SubsystemStatus` enum, `HealthResponse` Pydantic model, parallel probe orchestration, status mapping (any required subsystem `down`/`unreachable` → overall `degraded` → HTTP 503). |
| `backend/app/api/probes.py` | Async probe functions: `probe_db()`, `probe_redis()`, `probe_openai_key()` (file presence/non-empty only — capability check is Story 3.3), `probe_elasticsearch()`, `probe_opensearch()`. Each function takes the relevant client/setting and returns `SubsystemStatus`. Each wrapped in `asyncio.wait_for(probe(), timeout=0.2)` by the caller. |
| `backend/tests/unit/test_health.py` | Tests `health.py` handler with mocked probes: all-ok → 200; one-failure → 503; openai-missing → 200 (not degraded); slow-probe (>200ms) → that subsystem reported as `down` / `unreachable`. Targets 100% coverage of `backend/app/api/health.py` per spec §14. |
| `backend/tests/unit/test_probes.py` | Tests each probe function in isolation with mocked clients (`asyncpg.connect`, `aioredis.Redis.ping`, `httpx.AsyncClient.get`). |
| `backend/tests/contract/test_health_contract.py` | Asserts response JSON shape matches the OpenAPI schema generated from the Pydantic model. Tests both 200 success and 503 degraded shapes per spec §7.3. Tests `error_code: "SERVICE_UNAVAILABLE"` is returned when any required subsystem is unreachable (per spec §7.5 + api-conventions.md). |

**Modified files**

| File | Change |
|---|---|
| `backend/app/main.py` | Register the health router: `app.include_router(health.router)` (no prefix — `/healthz` is unversioned per api-conventions §"Operator endpoints"). |

**Endpoints**

| Method | Path | Request body | Success response | Error codes |
|---|---|---|---|---|
| `GET` | `/healthz` | — | `200 HealthResponse` (all subsystems healthy) | `503 SERVICE_UNAVAILABLE` (any required subsystem down/unreachable) |

**Pydantic schemas**

```python
# backend/app/api/health.py
class SubsystemStatus(str, Enum):
    OK = "ok"
    DOWN = "down"
    REACHABLE = "reachable"
    UNREACHABLE = "unreachable"
    CONFIGURED = "configured"
    MISSING_KEY = "missing_key"
    INCAPABLE = "incapable"  # FR-2; not in spec §7.4 enum table — see §13 Review log

class OpenAICapabilities(BaseModel):
    chat: Literal["ok", "fail", "untested"] = Field(description="Chat completion probe result")
    function_calling: Literal["ok", "fail", "untested"] = Field(description="Function-calling probe result")
    structured_output: Literal["ok", "fail", "untested"] = Field(description="JSON-schema response_format probe result")

class Subsystems(BaseModel):
    db: Literal["ok", "down"]
    redis: Literal["ok", "down"]
    openai: Literal["configured", "missing_key", "incapable"]
    elasticsearch: Literal["reachable", "unreachable"]
    opensearch: Literal["reachable", "unreachable"]

class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    subsystems: Subsystems
    openai_endpoint: str = Field(description="Configured OPENAI_BASE_URL")
    openai_capabilities: OpenAICapabilities
    version: str = Field(description="Application version (RELYLOOP_GIT_SHA)")
    uptime_seconds: int
```

**Status mapping** (which subsystems trigger HTTP 503):

| Subsystem | Healthy values | Triggers 503 |
|---|---|---|
| `db` | `ok` | `down` |
| `redis` | `ok` | `down` |
| `openai` | `configured`, `missing_key`, `incapable` | None — OpenAI is optional pre-judgments-feature; `missing_key` and `incapable` are non-blocking per spec FR-2 |
| `elasticsearch` | `reachable` | `unreachable` |
| `opensearch` | `reachable` | `unreachable` |

If any "Triggers 503" condition fires, overall `status = "degraded"` and HTTP status = 503 with envelope `error_code: "SERVICE_UNAVAILABLE"`. The body shape stays the same (per spec §7.2: "Body is always JSON with the same shape").

**Key interfaces**

```python
# backend/app/api/probes.py
async def probe_db(engine: AsyncEngine) -> Literal["ok", "down"]:
    """Run `SELECT 1` against the engine. Returns 'ok' or 'down'."""

async def probe_redis(client: Redis) -> Literal["ok", "down"]: ...
async def probe_openai_key(api_key: str | None) -> Literal["configured", "missing_key", "incapable"]:
    """File-content check only. 'configured' if present + non-empty + capability cache says ok.
       'missing_key' if absent/empty. 'incapable' if present but cached capabilities show degradation
       (cache populated by Story 3.3 startup check)."""
async def probe_elasticsearch(client: AsyncClient, base_url: str) -> Literal["reachable", "unreachable"]: ...
async def probe_opensearch(client: AsyncClient, base_url: str) -> Literal["reachable", "unreachable"]: ...

# backend/app/api/health.py
@router.get("/healthz", response_model=HealthResponse, responses={
    503: {"model": ErrorResponse, "description": "One or more required subsystems is down"}
})
async def healthz(...) -> Response: ...
```

**Tasks**
1. Write `backend/app/api/probes.py` with 5 probe functions + 200ms `asyncio.wait_for` wrappers. Catch `TimeoutError` and exception classes per probe → return the "down"/"unreachable" value.
2. Write `backend/app/api/health.py`:
   - Use `asyncio.gather(*probes, return_exceptions=True)` to run all 5 in parallel.
   - Map results to the `Subsystems` model.
   - Determine overall status from the table above.
   - For 503: return `JSONResponse(status_code=503, content=HealthResponse(...).model_dump())` — same body shape, different status code, and the envelope is the response itself (not nested under `detail`) per spec §7.3 (the body shape doesn't switch to `error_code` envelope; this is an operator endpoint, not a business endpoint). **Exception:** for tests/contracts, the 503 body still includes the same `HealthResponse` shape; `error_code` is only emitted if the route raises (which it doesn't — it returns the explicit status).
3. Write the unit tests (`test_health.py`, `test_probes.py`) — mock the engine/client objects.
4. Write the contract test (`test_health_contract.py`) — uses real FastAPI app via `httpx.AsyncClient`, mocks the probe functions, asserts JSON Schema compliance via `app.openapi()`.
5. Wire the router into `main.py`.
6. Verify: `make test-unit && make test-contract` exit 0; coverage on `backend/app/api/health.py` is 100% per spec §14.

**Definition of Done (DoD)**
- [ ] `GET /healthz` returns 200 with the spec §7.3 shape when all subsystems are reachable.
- [ ] `GET /healthz` returns 503 with `status: "degraded"` when any required subsystem is down/unreachable.
- [ ] OpenAI `missing_key` / `incapable` does NOT trigger 503 (per spec FR-2).
- [ ] Probes run in parallel via `asyncio.gather`; total endpoint p99 < 500ms (per spec FR-2).
- [ ] Per-probe timeout = 200ms; a hung probe is reported as `down`/`unreachable`, not blocking the response.
- [ ] AC-3 met: `docker compose stop redis && curl /healthz` → 503 with `subsystems.redis: "down"`, other subsystems still reflect actual state.
- [ ] AC-4 met: missing OpenAI key → 200, `status: "ok"`, `subsystems.openai: "missing_key"`.
- [ ] Coverage on `backend/app/api/health.py` = 100% per spec §14.
- [ ] Contract test asserts response JSON shape matches OpenAPI schema; covers both 200 and 503 paths.

### Story 3.3 — OpenAI capability check at startup + Redis cache + `/healthz` integration

**Outcome:** API container performs a 4-step capability self-test against `OPENAI_BASE_URL` at startup (only when `OPENAI_API_KEY_FILE` is non-empty). Results cached in Redis under `openai:capabilities:{sha256(base_url)}` with 24h TTL. `/healthz` reports the cached capabilities. **Owns FR-7.**

Per [`llm-orchestration.md` §"Capability check at startup"](../../../01_architecture/llm-orchestration.md).

**New files**

| File | Purpose |
|---|---|
| `backend/app/llm/__init__.py` | Empty marker. (`backend/llm/` per tech-stack.md §"Code organization" — using `backend/app/llm/` to keep all app code under `backend/app/`; matches FastAPI convention.) |
| `backend/app/llm/capability_check.py` | `async def check_capabilities(base_url, api_key, redis_client) -> CapabilityResult` — runs the 4 probes (models endpoint reachable, chat completion, function calling with trivial `echo(text)` tool, structured output via `json_schema` response_format), returns structured result, stores in Redis with 24h TTL. Logs at WARN on partial failure; never crashes. |
| `backend/app/llm/capability_models.py` | `CapabilityResult(BaseModel)` matching the cache shape per llm-orchestration.md (`base_url`, `model`, `models_endpoint`, `chat_completion`, `function_calling`, `structured_output`, `tested_at`). |
| `backend/tests/unit/test_capability_check.py` | Tests with mocked `httpx.AsyncClient`: all-ok, models-endpoint-fail, chat-fail, fc-fail, structured-output-fail, no-api-key-skips-test, network-timeout. Verifies WARN log; verifies Redis `set` is called with 24h TTL. |

**Modified files**

| File | Change |
|---|---|
| `backend/app/main.py` | Add a startup hook (`@app.on_event("startup")` or lifespan context) that runs `check_capabilities()` if `settings.openai_api_key` is non-empty. Logs structured WARN on any probe failure. Caches the result. |
| `backend/app/api/probes.py` | Update `probe_openai_key()` to read the cached capabilities from Redis: `configured` if all four probes are `ok`; `incapable` if key is set but any probe failed; `missing_key` if api_key is None/empty. |

**Key interfaces**

```python
# backend/app/llm/capability_check.py
async def check_capabilities(
    base_url: str,
    api_key: str,
    model: str,
    redis_client: Redis,
) -> CapabilityResult:
    """Run the 4-step capability self-test and cache the result.

    Steps:
      1. GET {base_url}/models         → models_endpoint: ok | fail
      2. POST /chat/completions (1tok) → chat_completion: ok | fail
      3. POST /chat/completions + tool → function_calling: ok | fail
      4. POST /chat/completions + JSON-schema response_format → structured_output: ok | fail

    Cache key: openai:capabilities:{sha256(base_url)}
    Cache TTL: 86400 seconds (24h)

    On failure, logs at WARN with the failing step name; never raises.
    """

# backend/app/llm/capability_models.py
class CapabilityResult(BaseModel):
    base_url: str
    model: str
    models_endpoint: Literal["ok", "fail"]
    chat_completion: Literal["ok", "fail", "untested"]
    function_calling: Literal["ok", "fail", "untested"]
    structured_output: Literal["ok", "fail", "untested"]
    tested_at: datetime
```

**Tasks**
1. Write `backend/app/llm/capability_models.py` with `CapabilityResult`.
2. Write `backend/app/llm/capability_check.py` with 4 sequential probe steps. Use `httpx.AsyncClient` with a 5s per-call timeout. Use a trivial `echo(text)` tool definition for FC step (per llm-orchestration.md §"Capability check at startup"). For structured output, use a 1-field Pydantic schema (`{"value": int}`).
3. Update `backend/app/api/probes.py::probe_openai_key()` to read the cached `CapabilityResult` from Redis. Mapping:
   - api_key is None/empty → `missing_key`
   - cache hit + all 4 fields `ok` → `configured`
   - cache hit + any field `fail` → `incapable`
   - cache miss (Redis down or check hasn't run yet) → `configured` if api_key present (don't block startup); WARN log
4. Update `backend/app/main.py` lifespan/startup: run `check_capabilities()` non-blockingly if api_key is set. Use `asyncio.create_task()` so a slow OpenAI endpoint doesn't delay startup. Log WARN on failure.
5. Write `test_capability_check.py` mocking `httpx.AsyncClient`. Use `pytest-recording` cassettes for one happy-path and one degraded-path test against `https://api.openai.com/v1` if a real key is provided in CI; gate behind `OPENAI_API_KEY_FILE` presence so CI without a key still passes.
6. Verify: `make test-unit` exits 0; `make typecheck` clean. Manual verify: `docker compose up -d` with valid `./secrets/openai_key` → API logs show "OpenAI capability check: chat=ok, function_calling=ok, structured_output=ok" within ~10s of startup.

**Definition of Done (DoD)**
- [ ] `check_capabilities()` runs all 4 probe steps with proper timeouts; never raises.
- [ ] Result cached in Redis under `openai:capabilities:{sha256(base_url)}` with 24h TTL.
- [ ] Startup lifespan runs the check non-blockingly when `OPENAI_API_KEY_FILE` is non-empty; skips entirely when missing/empty.
- [ ] `/healthz` reports `subsystems.openai: configured` when all 4 probes are `ok`; `incapable` when any failed; `missing_key` when no key.
- [ ] `subsystems.openai: incapable` does NOT trigger HTTP 503 — overall `status: "ok"` (per spec FR-2 + FR-7: "MUST NOT crash the API on failure").
- [ ] WARN-level structured log emitted on any probe failure with the failing step name and the response error.
- [ ] `test_capability_check.py` covers all 4 probe outcomes + no-key skip + network timeout; `make test-unit` exits 0.

---

## Epic 4 — Compose stack & operator workflow

**Outcome:** `docker compose up -d` brings up the 6-container stack from a fresh checkout; `make up` does the same after auto-generating required+optional secret files.

**Epic gate:** AC-1 met — `git clone && cd relyloop && make up` results in `curl localhost:8000/healthz` returning HTTP 200 within 90s (allowing image pulls).

### Story 4.1 — Dockerfile (`relyloop/api`)

**Outcome:** Single Dockerfile builds the API image (also used by `worker` per deployment.md). `python:3.12-slim` base; multi-stage with `uv` for fast dependency install; `RELYLOOP_GIT_SHA` ARG injected for version reporting per spec decision log.

**New files**

| File | Purpose |
|---|---|
| `Dockerfile` (repo root) | Multi-stage: `FROM python:3.12-slim AS base` → install `uv` via the official installer → copy `pyproject.toml` + `uv.lock` → `uv sync --frozen --no-dev` → copy `backend/` + `migrations/` + `alembic.ini` → final stage with non-root user. Sets `ENV PYTHONUNBUFFERED=1`, `ENV PYTHONPATH=/app`, `ENV RELYLOOP_GIT_SHA=${RELYLOOP_GIT_SHA:-dev}`. Default command: `uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`. |
| `.dockerignore` (repo root) | `node_modules/`, `.next/`, `ui/`, `data/`, `secrets/`, `.git/`, `.venv/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `coverage/`, `htmlcov/`, `*.pyc` |

**Decision rationale (per spec decision log):**
- Base image: `python:3.12-slim` — Alpine's musl libc has surprised real Python projects; distroless adds CI complexity.
- Lockfile workflow: `uv sync --frozen --no-dev` — uv handles lockfile + venv + install in one tool.
- Version reporting: `RELYLOOP_GIT_SHA` Docker ARG → ENV → `Settings.relyloop_git_sha` → `/healthz.version` field.

**Tasks**
1. Write `Dockerfile` per the structure above.
2. Write `.dockerignore` excluding all non-build artifacts.
3. Verify locally: `docker buildx build --build-arg RELYLOOP_GIT_SHA=$(git rev-parse --short HEAD) -t relyloop/api:dev .` succeeds.
4. Verify: image size is reasonable (~300MB — Python slim + deps).
5. Verify: container starts with `docker run --rm relyloop/api:dev python -c "import backend.app.main"` succeeds.

**Definition of Done (DoD)**
- [ ] `docker buildx build -t relyloop/api:dev .` succeeds in <2 min on a warm Docker cache.
- [ ] Image runs as non-root user (uid != 0).
- [ ] `RELYLOOP_GIT_SHA` build ARG is honored and surfaced in `/healthz.version`.
- [ ] `.dockerignore` excludes `ui/`, `data/`, `secrets/`, `.git/` (verified via `docker buildx build --progress=plain` showing context size).

### Story 4.2 — `docker-compose.yml` (6 services + healthchecks + secrets)

**Outcome:** `docker compose up -d` brings up Postgres, Redis, API, worker, Elasticsearch, OpenSearch — all bound to `127.0.0.1` per [`deployment.md` §"Network exposure"](../../../01_architecture/deployment.md). Healthchecks gate the API → Postgres dependency. **Owns FR-1 Compose layer.**

**New files**

| File | Purpose |
|---|---|
| `docker-compose.yml` (repo root) | 6 services per [`deployment.md` §"MVP1 deployment shape"](../../../01_architecture/deployment.md). Verbatim adoption of the YAML in that doc, with `${RELYLOOP_GIT_SHA:-dev}` substitution and explicit `healthcheck` + `depends_on: condition: service_healthy` for `api` → `postgres` and `worker` → `postgres`. |

**Service inventory** (matches deployment.md exactly):

| Service | Image | Port (host:container) | Healthcheck |
|---|---|---|---|
| `postgres` | `postgres:16` | (no host bind; api connects via Docker network) | `pg_isready -U relyloop -d relyloop`, 5s/10 retries |
| `redis` | `redis:7` | (no host bind) | `redis-cli ping`, 5s/10 retries |
| `api` | `relyloop/api:${RELYLOOP_GIT_SHA:-dev}` | `127.0.0.1:8000:8000` | `curl -fs http://localhost:8000/healthz` (added — not in deployment.md sample but required for `worker` not to start before API) |
| `worker` | Same as `api` | (no host bind) | (no healthcheck; worker is consumer-only) |
| `elasticsearch` | `elasticsearch:9.0.0` | `127.0.0.1:9200:9200` | `curl -fs http://localhost:9200/_cluster/health`, 10s/6 retries |
| `opensearch` | `opensearchproject/opensearch:2.18.0` | `127.0.0.1:9201:9200` | (omitted in deployment.md; add `curl -fs http://localhost:9200` against the OpenSearch cluster) |

**Secrets declared** (matches deployment.md):
- `postgres_password` → `./secrets/postgres_password` (required, generated by install script)
- `database_url` → `./secrets/database_url` (required, generated)
- `openai_key` → `./secrets/openai_key` (optional empty file)
- `cluster_credentials` → `./secrets/cluster_credentials.yaml` (optional empty YAML doc)
- `github_token` → `./secrets/github_token` (optional empty file)

**Volumes**: `./data/postgres`, `./data/redis`, `./data/repo-clones` (per [`deployment.md` §"Volumes"](../../../01_architecture/deployment.md)).

**Tasks**
1. Copy the YAML from [`deployment.md` §"MVP1 deployment shape"](../../../01_architecture/deployment.md) to `docker-compose.yml`. Substitute `relyloop/api:latest` → `relyloop/api:${RELYLOOP_GIT_SHA:-dev}`.
2. Add the API healthcheck (not in deployment.md sample but required for `worker` not to start before API): `test: ["CMD-SHELL", "curl -fs http://localhost:8000/healthz || exit 1"]`, 10s/12 retries.
3. Add `worker.depends_on.api: condition: service_healthy`.
4. Add OpenSearch healthcheck: `test: ["CMD", "curl", "-fs", "http://localhost:9200"]`, 10s/6 retries.
5. Verify: `docker compose config --quiet` exits 0 (YAML valid).
6. Verify after Story 4.4 lands: `make up` brings the stack up; `docker compose ps` shows all 6 services healthy within 60s on warm-image boot.

**Definition of Done (DoD)**
- [ ] `docker-compose.yml` declares 6 services exactly matching deployment.md.
- [ ] All host port binds use `127.0.0.1:` (no `0.0.0.0:`).
- [ ] `api` and `worker` `depends_on: postgres: { condition: service_healthy }`.
- [ ] `worker` `depends_on: api: { condition: service_healthy }` (so worker doesn't try to enqueue against an unstarted API).
- [ ] Healthchecks defined for every service whose dependents `condition: service_healthy` against it.
- [ ] `docker compose config --quiet` exits 0.

### Story 4.3 — Worker process skeleton (Arq WorkerSettings stub)

**Outcome:** `worker` container starts and listens on Redis but consumes no jobs (no jobs defined yet — `feat_study_lifecycle` adds `run_trial`, `feat_digest_proposal` adds `generate_digest`, `feat_github_pr_worker` adds `open_pr`). Skeleton enables the Compose `worker` service to start successfully.

**New files**

| File | Purpose |
|---|---|
| `backend/workers/__init__.py` | Empty marker. |
| `backend/workers/all.py` | `WorkerSettings` class for Arq. `functions = []` (empty for MVP1). `redis_settings` from `Settings.redis_url`. |
| `backend/tests/unit/test_workers.py` | Smoke test: import `WorkerSettings`, assert `functions == []`, assert `redis_settings.host` parses from URL. |

**Modified files**

| File | Change |
|---|---|
| (none — `docker-compose.yml`'s worker service already runs `arq backend.workers.all.WorkerSettings`) | |

**Tasks**
1. Write `backend/workers/all.py` with the empty `WorkerSettings`.
2. Write the smoke test.
3. Verify: `docker compose up -d worker` (after Story 4.2 + Story 4.4) — `docker compose logs worker` shows Arq startup banner without crashing.

**Definition of Done (DoD)**
- [ ] `backend/workers/all.py:WorkerSettings` is importable; `functions = []`.
- [ ] Worker container in Compose starts cleanly and connects to Redis.
- [ ] Smoke test passes.

### Story 4.4 — `.env.example` + secrets layout + install script + Make `up`/`down`/`logs`/`reset`

**Outcome:** Operator runs `make up` from a fresh clone, the install script auto-generates required secrets (postgres_password, database_url) and creates empty placeholder files for optional ones (openai_key, github_token, cluster_credentials.yaml), then `docker compose up -d` brings the stack up. **Owns FR-1 operator workflow + FR-3 install script.**

**New files**

| File | Purpose |
|---|---|
| `.env.example` | Documents every env var per deployment.md + spec FR-3 + FR-7. Shipped values are paths/defaults, not secrets. See content below. |

**Modified files**

| File | Change |
|---|---|
| `scripts/install.sh` | Implementation per spec FR-3: detect missing required secrets and generate them; create empty optional secret files; verify Compose config; invoke `docker compose up -d`. Handles re-runs idempotently. |
| `Makefile` | Wire targets: `up` → `bash scripts/install.sh`; `down` → `docker compose stop`; `logs` → `docker compose logs -f api worker`; `reset` → `docker compose down -v && rm -rf ./data` (with `-y` confirmation prompt unless `FORCE=1`). |
| `README.md` | Quickstart section per spec §15 — points at `make up` (full quickstart updated in Story 5.2). |

**`.env.example` content (sketch — full file in the implementation):**

```bash
# RelyLoop MVP1 — environment configuration
# Copy this file to `.env` and edit values. Secrets live in ./secrets/, generated by `make up`.

# --- Postgres -----------------------------------------------------------
POSTGRES_PASSWORD_FILE=./secrets/postgres_password    # required; auto-generated
DATABASE_URL_FILE=./secrets/database_url              # required; templated from password

# --- Redis -------------------------------------------------------------
REDIS_URL=redis://redis:6379/0

# --- OpenAI / OpenAI-compatible endpoint -------------------------------
OPENAI_BASE_URL=https://api.openai.com/v1             # for local LLM, e.g. http://host.docker.internal:11434/v1 (Ollama)
OPENAI_API_KEY_FILE=./secrets/openai_key              # optional; empty file = "not configured"
OPENAI_MODEL=gpt-4o-2024-08-06                        # for judgments + digest
OPENAI_MODEL_CHAT=gpt-4o-mini-2024-07-18              # for chat agent (cost-sensitive)
OPENAI_DAILY_BUDGET_USD=10.0                          # rolling 24h spend cap; 0 disables

# --- GitHub (optional, only used by feat_github_pr_worker once it ships) -
GITHUB_TOKEN_FILE=./secrets/github_token              # optional; empty file = "not configured"

# --- Cluster credentials (optional, populated when adding non-local clusters) -
CLUSTER_CREDENTIALS_FILE=./secrets/cluster_credentials.yaml

# --- Elasticsearch / OpenSearch knobs (local Compose) ------------------
ES_HEAP_SIZE=512m

# --- Build-time only --------------------------------------------------
# RELYLOOP_GIT_SHA is injected at `docker buildx build` via --build-arg
```

**`scripts/install.sh` behavior:**

```bash
#!/usr/bin/env bash
set -euo pipefail

# 1. Ensure ./secrets/ exists
mkdir -p ./secrets

# 2. Generate postgres_password if missing
if [[ ! -s ./secrets/postgres_password ]]; then
  echo "Generating ./secrets/postgres_password (32 random bytes, base64)..."
  openssl rand -base64 32 | tr -d '\n' > ./secrets/postgres_password
fi

# 3. Generate database_url if missing (template from password)
if [[ ! -s ./secrets/database_url ]]; then
  PASSWORD="$(cat ./secrets/postgres_password)"
  printf 'postgresql://relyloop:%s@postgres/relyloop' "$PASSWORD" > ./secrets/database_url
fi

# 4. Create empty placeholder files for optional secrets (Compose mounts them)
[[ -e ./secrets/openai_key ]] || touch ./secrets/openai_key
[[ -e ./secrets/github_token ]] || touch ./secrets/github_token
if [[ ! -e ./secrets/cluster_credentials.yaml ]]; then
  printf '{}\n' > ./secrets/cluster_credentials.yaml
fi

# 5. Verify Compose config
docker compose config --quiet

# 6. Bring the stack up
docker compose up -d
```

**Tasks**
1. Write `.env.example` per the sketch above; document every var.
2. Write `scripts/install.sh` per the behavior; make executable.
3. Wire Makefile targets per the modified-files entry.
4. Update root `README.md` with a brief Quickstart pointing at `make up` (full quickstart in Story 5.2).
5. **Manual operator handoff (impl-execute MUST pause here)** — see §7.5. After `.env.example` is committed, before invoking `make up` for AC-1 verification, prompt the operator: *"`.env.example` is in place. If you want to override Compose defaults (e.g., point `OPENAI_BASE_URL` at a local Ollama, change `ES_HEAP_SIZE`), now is the moment to `cp .env.example .env` and edit. Reply `continue` when ready, or `use defaults` to proceed without copying."* Do NOT auto-create `.env` — it's a developer-environment file that must be a deliberate operator action.
6. Verify AC-1: from a fresh clone, `make up` brings up the stack; within 90s `curl http://localhost:8000/healthz` returns 200.
7. Verify AC-2: `docker compose stop && docker compose up -d` (warm cache) — within 60s `/healthz` returns 200.
8. Verify AC-4: with empty `./secrets/openai_key`, `/healthz` returns 200, `subsystems.openai: "missing_key"`.
9. Verify "fresh clone without `make up`" path: `git clone … && cd … && docker compose up` — fails with a clear "missing secrets file" error from Compose pointing at `./secrets/postgres_password` (per spec FR-3).

**Definition of Done (DoD)**
- [ ] AC-1 passes: fresh clone → `make up` → `/healthz` 200 within 90s.
- [ ] AC-2 passes: warm cache → `docker compose up -d` → `/healthz` 200 within 60s.
- [ ] AC-4 passes: empty `openai_key` file → `/healthz` 200 with `subsystems.openai: "missing_key"`.
- [ ] AC-8 passes: `make` (no target) lists every target with one-line descriptions.
- [ ] `make reset` removes data volumes and `./data/` (with confirmation prompt unless `FORCE=1`).
- [ ] `bare docker compose up` from a fresh clone (without `make up` first) fails with a clear "missing secrets file" error mentioning `./secrets/postgres_password`.
- [ ] Install script is idempotent: running `make up` twice produces the same secret files (doesn't regenerate or overwrite).
- [ ] `.env.example` documents every env var the stack reads.
- [ ] **Manual operator handoff documented and respected (per §7.5):** impl-execute pauses after committing `.env.example`, prompts the operator to optionally `cp .env.example .env` + edit, waits for explicit `continue` / `use defaults` reply before invoking `make up`. The agent does NOT auto-create `.env`.

---

## Epic 5 — CI & quality gates

**Outcome:** Every PR is gated by a GitHub Actions workflow that runs lint + typecheck + test + coverage on backend, lint + typecheck + test + build on frontend, and Docker buildx for both `relyloop/api` and `relyloop/ui` images.

**Epic gate:** A test PR with an intentional lint error fails CI and cannot merge. AC-5 + AC-6 met.

### Story 5.1 — GitHub Actions `pr.yml` (backend + frontend + Docker build) + 80% coverage gate

**Outcome:** `.github/workflows/pr.yml` runs on every PR, with parallel jobs per the matrix below. **Owns FR-4.**

**New files**

| File | Purpose |
|---|---|
| `.github/workflows/pr.yml` | Workflow per the structure below. |
| `.github/dependabot.yml` | Weekly dependency updates for `pip` (uv `pyproject.toml`), `npm` (`ui/package.json`), `github-actions`, `docker`. (Decision: small overhead now prevents lock-in; spec doesn't require but it's hygiene.) |

**Workflow structure (`pr.yml`):**

```yaml
name: pr

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: relyloop
          POSTGRES_PASSWORD: testpassword
          POSTGRES_DB: relyloop
        ports: ["5432:5432"]
        options: --health-cmd pg_isready --health-interval 5s --health-timeout 5s --health-retries 10
      redis:
        image: redis:7
        ports: ["6379:6379"]
        options: --health-cmd "redis-cli ping" --health-interval 5s --health-retries 10
      elasticsearch:
        image: elasticsearch:9.0.0
        env:
          discovery.type: single-node
          xpack.security.enabled: "false"
          ES_JAVA_OPTS: "-Xms512m -Xmx512m"
        ports: ["9200:9200"]
      opensearch:
        image: opensearchproject/opensearch:2.18.0
        env:
          discovery.type: single-node
          DISABLE_SECURITY_PLUGIN: "true"
          OPENSEARCH_JAVA_OPTS: "-Xms512m -Xmx512m"
        ports: ["9201:9200"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          enable-cache: true
      - run: uv sync --frozen
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy backend/
      - run: uv run pytest backend/tests/ --cov=backend --cov-report=xml --cov-report=term-missing
        env:
          DATABASE_URL_FILE: ${{ runner.temp }}/db_url
          POSTGRES_PASSWORD_FILE: ${{ runner.temp }}/db_pw
          # CI helper: write the file the test expects (instead of mounting a Docker secret)
      - uses: actions/upload-artifact@v4
        with:
          name: coverage-xml
          path: coverage.xml

  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with: { version: 9 }
      - uses: actions/setup-node@v4
        with: { node-version: 20, cache: "pnpm", cache-dependency-path: "ui/pnpm-lock.yaml" }
      - run: cd ui && pnpm install --frozen-lockfile
      - run: cd ui && pnpm lint
      - run: cd ui && pnpm typecheck
      - run: cd ui && pnpm test
      - run: cd ui && pnpm build

  docker:
    runs-on: ubuntu-latest
    needs: [backend, frontend]
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - run: docker buildx build --build-arg RELYLOOP_GIT_SHA=${{ github.sha }} -t relyloop/api:${{ github.sha }} .
      # (UI containerization is a chore_tutorial_polish item per deployment.md — skipping the docker buildx for ui in MVP1)
```

**Modified files**

| File | Change |
|---|---|
| (none — workflow is self-contained) | |

**Tasks**
1. Write `.github/workflows/pr.yml` per the structure above. Tune service-container env to match Compose values (passwords differ — use `testpassword` for CI's ephemeral Postgres).
2. Write a small CI helper at the start of the backend pytest job that writes the `DATABASE_URL_FILE` content (`postgresql://relyloop:testpassword@localhost:5432/relyloop`) and `POSTGRES_PASSWORD_FILE` content (`testpassword`) to `${{ runner.temp }}/`. This adapts the file-based secrets pattern to GHA service containers.
3. Wire the 80% coverage gate via `[tool.coverage.report].fail_under = 80` (already in `pyproject.toml` from Story 1.2). pytest-cov reads this and fails the run.
4. Add `.github/dependabot.yml` (small but standard).
5. Verify: open a test PR with a deliberate lint error → backend job fails. Open a PR with deliberately uncovered code → coverage job fails (per AC-6 — when project total drops below 80%).
6. Verify AC-5: PR opens, lint job fails, PR cannot merge (assuming branch protection requires `pr / backend` check).

**Definition of Done (DoD)**
- [ ] `.github/workflows/pr.yml` exists; runs on `pull_request` and `push: [main]`.
- [ ] Backend job runs lint + format-check + typecheck + test (with Postgres + Redis + ES + OpenSearch service containers); 80% coverage gate enforced via `pytest --cov` reading `[tool.coverage.report].fail_under` from `pyproject.toml`.
- [ ] Frontend job runs lint + typecheck + test + build.
- [ ] Docker job runs `buildx build` for `relyloop/api` (UI containerization deferred per deployment.md note).
- [ ] AC-5 verified: a PR with a deliberate lint error fails CI (the lint job at minimum).
- [ ] AC-6 verified: a PR that drops coverage below 80% fails CI.
- [ ] Branch protection on `main` requires this workflow (operator step — documented in Story 5.2's runbook, not enforced by code).

### Story 5.2 — Documentation updates + create root `state.md` / `architecture.md` / `CLAUDE.md`

**Outcome:** Per spec §15 + plan §4.0, all required doc updates land in the same PR. Creates the missing root context files (`state.md`, `architecture.md`, `CLAUDE.md`) that all subsequent feature plans reference.

**New files**

| File | Purpose |
|---|---|
| `state.md` (repo root) | Active branch (`main`), recent changes (this PR landed), current focus (`infra_adapter_elastic` is next per dependency order), known debt (none yet), Alembic head (the baseline revision). |
| `architecture.md` (repo root) | One-screen pointer to `docs/01_architecture/` topical docs + `docs/01_architecture/mvp1-overview.md`. Filename exists at root because the impl-plan-gen / impl-execute skills read it; it stays a navigation pointer rather than duplicating the topical docs. |
| `CLAUDE.md` (repo root) | Codebase conventions, absolute rules (mounted secrets only; no bare env-var fallback; pre-commit must pass), data model summary (no business tables in MVP1), feature-status section listing the 12 MVP1 features with status (#1 infra_foundation = SHIPPED, #2 infra_adapter_elastic = NEXT, etc.). |
| `docs/03_runbooks/local-dev.md` | Per spec §15: how to boot, restart, debug, and reset the local stack. Includes the AC-1 happy path; `make logs` debugging tips; `make reset` for nuking state; common port-collision and OOM remediations from spec §11. |
| `docs/05_quality/testing.md` | Per spec §15: test-layer convention (unit/integration/contract/e2e), the 80% coverage gate, how to run each layer. Mirrors the rules from the plan template's §3 testing workstream. |
| `docs/03_runbooks/README.md` | Index for the runbooks directory; lists `local-dev.md` and notes more arrive with later features. |
| `docs/05_quality/README.md` | Index for the quality directory; lists `testing.md` and notes more arrive with later features. |

**Modified files**

| File | Change |
|---|---|
| `README.md` (repo root) | Update "What's in this repo today" to reflect post-bootstrap state; expand the Quickstart to the full clone → make up → curl /healthz flow per AC-1. Link to `docs/03_runbooks/local-dev.md` for deeper setup. |
| `docs/01_architecture/system-overview.md` | Audit against the actual implementation; update only if drift (per spec §15). |
| `docs/01_architecture/deployment.md` | Audit against the actual `docker-compose.yml`; update only if drift. |

**Tasks**
1. Write `state.md` per the structure used by sibling projects (active branch, current focus, recent changes, known debt, Alembic head). Initial content: branch=main, focus=infra_adapter_elastic, recent changes=[infra_foundation shipped (PR #N)], known debt=none, alembic head=`<rev>_baseline`.
2. Write `architecture.md` as a one-screen navigation pointer to `docs/01_architecture/`.
3. Write `CLAUDE.md` summarizing conventions + the 12-feature MVP1 status list + the absolute rules (mounted secrets only, no bare env vars, pre-commit must pass, never commit to main).
4. Write `docs/03_runbooks/local-dev.md` walking through clone → `cp .env.example .env` (optional) → `make up` → `/healthz` → debugging tips → `make reset`. Include the §7.5 manual-handoff checklist as an "operator setup checklist" subsection.
5. Write `docs/05_quality/testing.md` documenting the four test layers + 80% coverage gate.
6. Write the two README index files.
7. Update root `README.md` with the full Quickstart per AC-1.
8. Audit `docs/01_architecture/system-overview.md` and `deployment.md` against the actual implementation; update only if drift.
9. **Manual operator handoff #3 (per §7.5)** — after CI is green on the feature PR and before merging: prompt the operator to update branch protection on `main` to require the new `pr / *` checks. Wait for `protection updated` reply before declaring the feature done.
10. Verify: a new contributor can follow `docs/03_runbooks/local-dev.md` end-to-end and boot the stack (manual / maintainer review).

**Definition of Done (DoD)**
- [ ] `state.md`, `architecture.md`, `CLAUDE.md` exist at repo root.
- [ ] `docs/03_runbooks/local-dev.md` and `docs/05_quality/testing.md` exist with the content specified by spec §15.
- [ ] Root `README.md` has a working Quickstart matching AC-1.
- [ ] System-overview and deployment docs match the actual `docker-compose.yml` (no drift).

---

## UI Guidance

**N/A for full UI Guidance section** — this feature creates only a single placeholder page (`ui/src/app/page.tsx`, Story 1.3) with a `<h1>` and one `<a>`. No layout decisions, no shared state, no analogous patterns, no insertion points (it's the first page).

**Information architecture placement:** `/` is the root page; sidebar/nav/tabs do not exist yet. Subsequent UI features (`feat_studies_ui`, `feat_proposals_ui`, `feat_chat_agent`) replace this placeholder with the real shell.

**No legacy behavior parity table** — no user-facing component being deleted or replaced (this is the first frontend code in the repo).

---

## 3) Testing workstream

### 3.1 Unit tests

- **Location:** `backend/tests/unit/`
- **Tasks:**
  - [ ] `backend/tests/unit/test_smoke.py` (Story 1.2) — toolchain smoke
  - [ ] `backend/tests/unit/test_settings.py` (Story 2.1) — `*_FILE` resolution: required-missing, optional-missing, optional-empty, valid-content, trailing-newline
  - [ ] `backend/tests/unit/test_error_envelope.py` (Story 3.1) — HTTPException, RequestValidationError, generic Exception → envelope shape
  - [ ] `backend/tests/unit/test_request_id_middleware.py` (Story 3.1) — client-supplied X-Request-ID adopted; missing header mints UUIDv7; both echoed in response
  - [ ] `backend/tests/unit/test_health.py` (Story 3.2) — handler with mocked probes: all-ok → 200; one-failure → 503; openai-missing → 200; slow-probe → reported as down/unreachable. Targets 100% coverage of `backend/app/api/health.py` per spec §14.
  - [ ] `backend/tests/unit/test_probes.py` (Story 3.2) — each probe in isolation with mocked clients
  - [ ] `backend/tests/unit/test_capability_check.py` (Story 3.3) — 4 probe outcomes + no-key skip + network timeout; verifies WARN log; verifies Redis `set` with 24h TTL
  - [ ] `backend/tests/unit/test_workers.py` (Story 4.3) — WorkerSettings smoke
- **DoD:**
  - [ ] All listed unit tests pass via `make test-unit`.
  - [ ] Coverage on `backend/app/api/health.py` and `backend/app/core/settings.py` ≥ 100% per spec §14 / DoD.
  - [ ] Project total coverage ≥ 80% per FR-4.

### 3.2 Integration tests

- **Location:** `backend/tests/integration/`
- **Tasks:**
  - [ ] `backend/tests/integration/test_health_integration.py` (Story 4.4) — boot the full Compose stack (`docker compose up -d`), `curl /healthz`, assert 200 and JSON shape. Marked `@pytest.mark.integration`.
  - [ ] `backend/tests/integration/test_migrations.py` (Story 2.2) — `alembic upgrade head` against fresh Postgres; assert `alembic_version` row; round-trip `downgrade -1 && upgrade head`. Marked `@pytest.mark.integration`.
- **DoD:**
  - [ ] Both pass via `make test-integration` when Postgres + the rest of the stack is up.
  - [ ] Both are marked `@pytest.mark.integration` so unit-only test runs skip them.

### 3.3 Contract tests

- **Location:** `backend/tests/contract/`
- **Tasks:**
  - [ ] `backend/tests/contract/test_health_contract.py` (Story 3.2) — assert `/healthz` response matches the OpenAPI schema generated by FastAPI. Cover 200 (all healthy) and 503 (degraded) paths. Asserts `error_code: "SERVICE_UNAVAILABLE"` is reported per spec §7.5 + api-conventions §"Standard error codes" when triggered.
- **DoD:**
  - [ ] No accepted endpoint without contract coverage. **Endpoint count = 1 (`/healthz`); contract test count = 1.** ✓
  - [ ] Error code coverage: spec §7.5 lists `SERVICE_UNAVAILABLE`; the contract test asserts it.

### 3.4 E2E tests

- **N/A — this feature has no UI flows.** The placeholder page is exercised only by Story 1.3's vitest smoke test (`ui/src/__tests__/page.test.tsx`). E2E infrastructure (Playwright) lands with `feat_studies_ui` per spec §14.

### 3.5 Existing test impact audit

**N/A — greenfield.** No existing tests, no URL renames, no deprecation paths.

### 3.6 Migration verification

- [ ] Alembic baseline migration includes `downgrade()` (empty pass — `alembic_version` is auto-managed).
- [ ] `alembic upgrade head` succeeds against a fresh Postgres.
- [ ] Round-trip verified by `test_migrations.py`: `alembic downgrade -1 && alembic upgrade head`.
- [ ] DB revision guard at API startup is **not** in MVP1 scope (would crash the stack if migrations are pending — out of scope; reconsider at MVP2).

### 3.7 CI gates (per FR-4)

- [ ] `make lint` (ruff check + format-check; eslint)
- [ ] `make typecheck` (mypy --strict; tsc --noEmit)
- [ ] `make test-unit`
- [ ] `make test-integration`
- [ ] `make test-contract`
- [ ] `cd ui && pnpm test` (vitest)
- [ ] `cd ui && pnpm build` (Next.js build)
- [ ] `docker buildx build` for `relyloop/api`
- [ ] Coverage gate: pytest fails if project total < 80% (configured via `pyproject.toml [tool.coverage.report].fail_under`)

---

## 4) Documentation update workstream

### 4.0 Core context files (Story 5.2 owns all three)

These files don't exist yet — this feature creates them:

- **`state.md`** — branch, current focus, recent changes (this PR), known debt (none), Alembic head (the baseline revision)
- **`architecture.md`** — one-screen navigation pointer to `docs/01_architecture/` (which holds the topical docs)
- **`CLAUDE.md`** — codebase conventions, absolute rules, MVP1 feature-status list

### 4.1 Architecture docs (`docs/01_architecture/`) — Story 5.2 audits + updates only on drift

- [ ] Audit `system-overview.md` — update only if implementation diverges from the doc
- [ ] Audit `deployment.md` — update only if `docker-compose.yml` diverges
- [ ] No new architecture docs in scope (per spec §15)

### 4.2 Product docs (`docs/02_product/`)

- No updates in scope.

### 4.3 Runbooks (`docs/03_runbooks/`) — NEW per spec §15

- [ ] Create `docs/03_runbooks/README.md` — index
- [ ] Create `docs/03_runbooks/local-dev.md` — boot, restart, debug, reset (per spec §15)

### 4.4 Security docs (`docs/04_security/`)

- No updates in scope. (`audit_log` and threat-model arrive at MVP2.)

### 4.5 Quality docs (`docs/05_quality/`) — NEW per spec §15

- [ ] Create `docs/05_quality/README.md` — index
- [ ] Create `docs/05_quality/testing.md` — test-layer convention + 80% coverage gate

### 4.6 Root `README.md`

- [ ] Update "What's in this repo today" to reflect post-bootstrap state
- [ ] Expand Quickstart to the full AC-1 flow (`git clone … && make up && curl localhost:8000/healthz`)

**Documentation DoD**

- [ ] `state.md`, `architecture.md`, `CLAUDE.md` are consistent with shipped behavior.
- [ ] `docs/03_runbooks/local-dev.md` walks an operator from clean state to AC-1 success.
- [ ] `docs/05_quality/testing.md` documents the four test layers + coverage gate consistent with `pyproject.toml`.
- [ ] Root `README.md` Quickstart works on a clean machine (manual maintainer verify).

---

## 5) Lean refactor workstream

**N/A — greenfield.** No existing code to refactor; nothing to deduplicate; no dead branches to remove. This workstream activates from the next feature (`infra_adapter_elastic`) onward.

---

## 6) Dependencies, risks, and mitigations

### Dependencies

| Dependency | Needed by | Status | Risk if missing |
|---|---|---|---|
| Docker 24+ with Compose v2 | FR-1 / Story 4.4 | Operator prerequisite | Compose `services.depends_on: condition: service_healthy` requires Compose v2; older Docker fails AC-1 |
| Python 3.12+ on developer machine | Story 1.2 | Operator prerequisite | `uv` install fails; `pyproject.toml` `requires-python = ">=3.12"` rejects |
| Node 20+ on developer machine | Story 1.3 | Operator prerequisite | `pnpm install` may succeed but `pnpm build` fails on Next.js 14 minimum |
| 16 GB RAM on developer machine | AC-1 | Spec §11 documented | ES + OpenSearch each consume ~1 GB heap (`-Xms512m -Xmx512m`); on <8 GB free, ES OOMs and `/healthz` reports `elasticsearch: unreachable` |
| GitHub Actions runner availability | FR-4 / Story 5.1 | GitHub-managed | None — managed service |
| OpenAI API key (optional) | FR-7 capability check + downstream features | Optional | `subsystems.openai: missing_key`; `feat_llm_judgments` and downstream features gate themselves until configured |

### Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| ES container OOMs on <8 GB free RAM | Medium | High (AC-1 fails) | `ES_HEAP_SIZE` knob in `.env.example` (default 512m); README documents 16 GB recommendation; `/healthz` reports `elasticsearch: unreachable` so operator sees the cause |
| Pre-commit Conventional Commits hook rejects squash-merge messages | Low | Medium (DX friction) | Regex permits the standard CC types; GitHub squash-merge title is set by the author following CC convention; CI does NOT enforce CC on merge commits — only on developer-machine commits via the `commit-msg` hook |
| GitHub Actions service-container Postgres exposes credentials in env vars (CI-only) | Low | Low (CI only, ephemeral) | CI uses a deliberately-distinct `testpassword`; the file-mount pattern is reproduced via a temp-file helper at the start of the pytest job; the production `*_FILE` pattern is enforced in code (`Settings` class) |
| OpenAI capability check on first `make up` adds noticeable startup latency | Medium | Low (one-time per 24h per base_url) | Check is non-blocking (`asyncio.create_task`); cached for 24h; subsequent boots within the window are no-op |
| `docker buildx build` in CI without push hides registry-config drift | Low | Low (MVP1 doesn't push) | Spec §3 explicitly defers GHCR publish to `chore_tutorial_polish`; documented in §13 Review log |

### Failure modes (per spec §11)

| Failure mode | Trigger | Expected system behavior | Recovery |
|---|---|---|---|
| Postgres slow to boot | Cold-cache `make up`; pg_isready takes >30s | Compose `depends_on` retries the API healthcheck; eventually API connects or the deploy fails clearly in `docker compose logs api` | Operator restarts: `make down && make up` |
| Port collision (5432, 6379, 9200, 9201, 3000, 8000 in use) | Operator already runs Postgres etc. on host | Compose fails with "port already allocated" error | README documents how to override via `.env` (currently only Postgres+Redis ports aren't bound to host; ES, OpenSearch, API are bound — `127.0.0.1:9200`, `9201`, `8000`. Document the override pattern.) |
| Insufficient memory (<8 GB free) | ES OOMs at startup | `/healthz` reports `elasticsearch: unreachable`; HTTP 503 with envelope `error_code: "SERVICE_UNAVAILABLE"` | Operator tunes `ES_HEAP_SIZE` in `.env`; restarts |
| OpenAI capability check fails (network down at startup) | Local LLM endpoint not running, or `OPENAI_BASE_URL` wrong | Capability check logs WARN with the failing step; cached as partial; `subsystems.openai: incapable` in `/healthz` (does NOT trigger 503) | Operator fixes endpoint; capability check re-runs after 24h cache expiry, or operator can manually invalidate via `redis-cli DEL openai:capabilities:*` |
| Worker container crash-loop | Arq fails to connect to Redis | Compose restart policy (`unless-stopped` — TBD) restarts; if Redis healthcheck fails, worker `depends_on` blocks restart until Redis is healthy | Operator: `make logs` → see Arq error; usually a `REDIS_URL` typo |

---

## 7) Sequencing and parallelization

### Suggested sequence

1. **Epic 1 (scaffolding)** — Story 1.1 → 1.2 → 1.3 → 1.4. All four stories can be reviewed independently but build on 1.1's directory layout.
2. **Epic 2 (persistence)** — Story 2.1 → 2.2. 2.2 depends on 2.1's `Settings` class for the database URL.
3. **Epic 3 (API skeleton)** — Story 3.1 → 3.2 → 3.3. 3.2 depends on 3.1's main.py + middleware; 3.3 depends on 3.2's probe machinery.
4. **Epic 4 (Compose)** — Story 4.1 (Dockerfile) → 4.2 (Compose) → 4.3 (worker stub) → 4.4 (install script + Make targets). 4.4 is the integration point that makes AC-1 testable.
5. **Epic 5 (CI + docs)** — Story 5.1 (workflow) → 5.2 (docs). 5.1 needs Epic 1–4 in place to be meaningful; 5.2 audits the final state.

### Parallelization opportunities

- **Story 1.2 (Python)** and **Story 1.3 (Frontend)** are independent toolchains and can be implemented in parallel by two engineers.
- **Story 4.3 (worker stub)** is independent of Story 4.1/4.2 and can land any time after Story 1.2 (Python project exists).
- **Story 2.2 (Alembic)** can land before Story 3.x — Alembic init only needs the Python project (Story 1.2) and the Settings class (Story 2.1).
- **Story 5.1 (CI workflow)** can be drafted in parallel with later epics, but verifying it requires the rest of the stack to be in place (so its DoD blocks until last).

### Critical path

`1.1 → 1.2 → 2.1 → 2.2 → 3.1 → 3.2 → 3.3 → 4.1 → 4.2 → 4.4 → 5.1 → 5.2`

(Story 1.3, 1.4, 4.3 can happen off the critical path.)

---

## 7.5) Manual operator handoffs (impl-execute pause points)

This section enumerates every point where `impl-execute` MUST stop, prompt the operator, and wait for an explicit reply before continuing. These are operator-environment actions that the agent cannot complete on the operator's behalf — auto-performing them would either assume content the operator hasn't approved (`.env` config) or require credentials/permissions the agent does not have (GitHub branch protection).

| # | Story | Pause point | Operator action | Exact prompt |
|---|---|---|---|---|
| 1 | **4.4** | After `.env.example` is committed; before invoking `make up` for AC-1 verification | Optionally `cp .env.example .env` and edit overrides (e.g., `OPENAI_BASE_URL` for local Ollama, `ES_HEAP_SIZE`, default models). The stack works without `.env` because Compose has `${VAR:-default}` fallbacks; copying is only needed for overrides. | *"`.env.example` is in place. If you want to override Compose defaults (e.g., point `OPENAI_BASE_URL` at a local Ollama, change `ES_HEAP_SIZE`), now is the moment to `cp .env.example .env` and edit. Reply `continue` when ready, or `use defaults` to proceed without copying."* |
| 2 | **4.4** | After AC-4 verification (which intentionally tests the missing-key path); only if the operator wants to exercise OpenAI-dependent capability checks (Story 3.3) before merging | `echo "<your-openai-key>" > ./secrets/openai_key` (or set up local LLM per `deployment.md` operator workflow) | *"AC-4 verified the missing-key path. If you want me to also verify the OpenAI capability check (Story 3.3) end-to-end, populate `./secrets/openai_key` now and reply `key set`. Otherwise reply `skip` — the unit/contract tests already cover the capability-check logic with mocked HTTP."* |
| 3 | **5.2** | After CI workflow lands and is verified green on the feature PR; before declaring the feature "done" | Update GitHub branch protection on `main` to require the `pr / backend`, `pr / frontend`, and `pr / docker` checks. Requires repo admin access. | *"CI workflow is green. The final operator-only step is to update branch protection on `main` to require the new `pr / *` checks. Open `https://github.com/SoundMindsAI/relyloop/settings/branches`, edit the `main` rule, and add the three required checks. Reply `protection updated` when done — that's the last gate before this feature is marked complete."* |

**Rules for impl-execute:**

1. Treat each pause point as a **hard stop**. Do not proceed to the next task until the operator's reply is received.
2. **Do NOT auto-create `.env`.** It's gitignored on purpose; the operator owns its content. (Bare env vars for secrets are explicitly forbidden by spec FR-3 anti-patterns — `.env` is for non-secret Compose overrides only; real secrets go in `./secrets/<name>` files.)
3. **Do NOT auto-populate `./secrets/openai_key` or `./secrets/github_token`.** The install script creates them as empty files for Compose mount-time correctness; populating them with real credentials is the operator's deliberate action when downstream features need them.
4. **Do NOT call the GitHub branch-protection API.** Even with sufficient PAT scopes, this is a repo-policy decision the human must make (which checks become required, who's exempt, etc.).

If an operator skips a pause point ("use defaults", "skip"), record the skip in the per-story execution evidence so it's visible in the PR description.

---

## 8) Rollout and cutover plan

- **Feature flags:** None. Spec §16: "This feature is not gated."
- **Migration/backfill:** First migration in repo history. No backfill (no prior data). The `alembic_version` table is auto-created by Alembic on first `upgrade head`.
- **Operational readiness gates:**
  - `docs/03_runbooks/local-dev.md` exists and a maintainer can boot from clean clone using only that doc.
  - GitHub repo branch protection on `main` updated to require the `pr / backend`, `pr / frontend`, and `pr / docker` checks (manual operator step — documented in `local-dev.md`).
- **Release gate:** First commit on `main` after this feature ships is the v0.0.1 placeholder tag (per spec §16). Root `README.md` flips status from "pre-MVP1" to "MVP1 in progress."
- **Rollback:** N/A. Pre-existence repo had no infra; rollback is `git revert` of the merge commit, which leaves the spec/architecture docs in place but removes all code.

---

## 9) Execution tracker

### Current sprint (this PR)

- [x] Story 1.1 — Monorepo layout & root configs
- [x] Story 1.2 — Python project (`uv`, ruff, mypy, pytest)
- [x] Story 1.3 — Frontend project (Next.js 14, pnpm, TS strict)
- [x] Story 1.4 — Pre-commit hooks (ruff, mypy, eslint, prettier, gitleaks, Conventional Commits) **[FR-6]**
- [x] **Epic 1 phase gate** — GPT-5.5 review cycle 1: pass-with-notes (11 findings, 8 accepted, 3 rejected with cited counter-evidence). Gate passed.
- [ ] Story 2.1 — SQLAlchemy 2.0 async engine + Pydantic Settings **[FR-3 app layer]**
- [ ] Story 2.2 — Alembic init + baseline migration + `make migrate` **[FR-5]**
- [ ] Story 3.1 — FastAPI app skeleton + structlog + X-Request-ID middleware + error envelope
- [ ] Story 3.2 — `/healthz` endpoint with parallel subsystem probes **[FR-2]**
- [ ] Story 3.3 — OpenAI capability check at startup + Redis cache **[FR-7]**
- [ ] Story 4.1 — Dockerfile (`relyloop/api`)
- [ ] Story 4.2 — `docker-compose.yml` (6 services + healthchecks + secrets)
- [ ] Story 4.3 — Worker process skeleton (Arq WorkerSettings stub)
- [ ] Story 4.4 — `.env.example` + secrets layout + install script + Make targets **[FR-1, FR-3 install layer]**
- [ ] Story 5.1 — GitHub Actions `pr.yml` (backend + frontend + Docker build) **[FR-4]**
- [ ] Story 5.2 — Documentation updates + create root `state.md` / `architecture.md` / `CLAUDE.md`

### Blocked items

None.

### Done this sprint

(Filled in as stories complete.)

---

## 10) Story-by-Story Verification Gate (Agent Checklist)

Before marking any story complete, the executing engineer or agent must attach evidence for:

- [ ] Files created/modified match story scope (`New files` / `Modified files` tables).
- [ ] Endpoint contract implemented exactly as documented (Story 3.2 only — 1 endpoint).
- [ ] Key interfaces implemented with compatible signatures (Stories 2.1, 3.1, 3.3).
- [ ] Required tests added/updated for the relevant test layers.
- [ ] Commands executed and passed:
    - [ ] `make lint`
    - [ ] `make typecheck`
    - [ ] `make test-unit`
    - [ ] `make test-integration` (after Epic 4 lands; or marker-skip explanation)
    - [ ] `make test-contract` (after Story 3.2 lands)
    - [ ] `cd ui && pnpm lint && pnpm typecheck && pnpm test && pnpm build` (Story 1.3 + after)
- [ ] Migration round-trip evidence (Story 2.2 only).
- [ ] Related docs updated in same PR if behavior/contract changed (Story 5.2 owns the bulk).

---

## 11) Plan consistency review (performed)

### Spec ↔ plan endpoint count

- Spec §7.1 lists 1 endpoint (`GET /healthz`).
- Plan covers 1 endpoint (Story 3.2).
- ✓ Match.

### Spec ↔ plan error code coverage

- Spec §7.5 lists 1 feature-specific code: `SERVICE_UNAVAILABLE` (503).
- Plan's contract test (Story 3.2's `test_health_contract.py`) asserts it.
- Plan's error envelope baseline (Story 3.1's `test_error_envelope.py`) covers the standard codes from api-conventions.md (`VALIDATION_ERROR` 422, `INTERNAL_ERROR` 500, plus `SERVICE_UNAVAILABLE` 503).
- ✓ Coverage complete.

### Spec ↔ plan FR coverage

| FR | Spec section | Plan owner | Status |
|---|---|---|---|
| FR-1 | Spec §7 FR-1 | Stories 4.1, 4.2, 4.4 | ✓ |
| FR-2 | Spec §7 FR-2 | Stories 3.1, 3.2 | ✓ |
| FR-3 | Spec §7 FR-3 | Stories 2.1, 4.4 | ✓ |
| FR-4 | Spec §7 FR-4 | Story 5.1 | ✓ |
| FR-5 | Spec §7 FR-5 | Story 2.2 | ✓ |
| FR-6 | Spec §7 FR-6 | Story 1.4 | ✓ |
| FR-7 | Spec §7 FR-7 | Story 3.3 | ✓ |

7/7. ✓ No orphan stories (every story maps to ≥1 FR).

### Story internal consistency

- Endpoint table (Story 3.2) field names match Pydantic schema (`HealthResponse`, `Subsystems`, `OpenAICapabilities`).
- DoD assertions reference correct error codes (`SERVICE_UNAVAILABLE`) and HTTP statuses (200/503).
- New files: scanned across all 14 stories — no file claimed by two stories.
- Modified files: minimal cross-story modification (`Makefile` modified by Stories 1.1, 1.2, 1.3, 1.4, 2.2, 4.4 — each adds or wires distinct targets; documented intent in each story's modified-files table). `backend/app/main.py` modified by Stories 1.2, 2.1, 3.1, 3.3 (each adds distinct wiring per epic order).

### Test file count and assignment

- Unit: 8 test files (`test_smoke`, `test_settings`, `test_error_envelope`, `test_request_id_middleware`, `test_health`, `test_probes`, `test_capability_check`, `test_workers`).
- Integration: 2 test files (`test_health_integration`, `test_migrations`).
- Contract: 1 test file (`test_health_contract`).
- E2E: 0 (none in this feature; vitest smoke for placeholder page is in `ui/src/__tests__/`).
- Every test file is assigned to exactly one story's DoD. ✓ No orphans.

### Gate arithmetic

- Epic 1 gate: "`make fmt && make lint && make typecheck` exits 0 on a fresh clone after `uv sync` + `pnpm install`." ✓ Achievable after Stories 1.1–1.4.
- Epic 2 gate: "`make migrate` against a fresh Postgres applies the baseline." ✓ Achievable after Story 2.2.
- Epic 3 gate: "`curl localhost:8000/healthz` against a fully-healthy stack returns 200." ✓ Achievable after Story 3.3 (and the rest of the stack from Epic 4).
- Epic 4 gate: AC-1 (`git clone && cd relyloop && make up` → `/healthz` 200 within 90s). ✓ Achievable after Story 4.4 (which is the integration point).
- Epic 5 gate: Test PR with deliberate lint error fails CI. ✓ Achievable after Story 5.1.

### Open questions resolved

Spec §19 lists no open questions ("None — all resolved"). ✓ Plan inherits clean.

### Plan ↔ codebase verification

**N/A — greenfield.** No existing code to verify against. Plan claims are verified against the architecture docs (which are the canonical source for this feature, since the codebase doesn't yet exist).

### Infrastructure path verification

- **Migration directory: `migrations/`** at repo root, per [`tech-stack.md` §"Code organization"](../../../01_architecture/tech-stack.md). `alembic.ini` lives at repo root with `script_location = migrations`. ✓
- **Alembic head:** `0001_baseline` (the very first migration; revision-id pinned via `--rev-id 0001` per Story 2.2 task list).
- **Router registration: `backend/app/main.py:app.include_router(health.router)`** with no prefix (operator endpoint). ✓ Matches spec §3 API convention check (`/healthz` is unversioned).

### Frontend data plumbing verification

**N/A** — placeholder page only, no props, no fetched data.

### Persistence scope consistency

**N/A** — this feature uses no `localStorage` / `sessionStorage`.

### Enumerated value contract audit

Spec §7.4 enumerates wire values for `subsystems.{db,redis,openai,elasticsearch,opensearch}` and `status`. Plan Story 3.2's `Subsystems` Pydantic model uses `Literal[...]` types matching each enum exactly:

| Field | Spec §7.4 values | Plan model values | Match |
|---|---|---|---|
| `subsystems.db` | `ok`, `down` | `Literal["ok", "down"]` | ✓ |
| `subsystems.redis` | `ok`, `down` | `Literal["ok", "down"]` | ✓ |
| `subsystems.openai` | `configured`, `missing_key` | `Literal["configured", "missing_key", "incapable"]` | **Mismatch** — plan adds `incapable` per FR-2; spec §7.4 omits it. **Plan implements FR-2 (more specific); §13 Review log flags the spec inconsistency for spec-gen patch.** |
| `subsystems.elasticsearch` | `reachable`, `unreachable` | `Literal["reachable", "unreachable"]` | ✓ |
| `subsystems.opensearch` | `reachable`, `unreachable` | `Literal["reachable", "unreachable"]` | ✓ |
| `status` | `ok`, `degraded` | `Literal["ok", "degraded"]` | ✓ |

Source-of-truth comment in `backend/app/api/health.py`:

```python
# Wire values must match docs/02_product/planned_features/infra_foundation/feature_spec.md §7.4
# (with `incapable` added per FR-2 — see implementation_plan.md §13 Review log)
```

### Audit-event coverage audit

**N/A — MVP1 has no `audit_log` subsystem.** Activates at MVP2 per [`tech-stack.md` §"Canonical release matrix"](../../../01_architecture/tech-stack.md). Spec §6 confirms: "Audit-event instrumentation matrix: N/A — RelyLoop has no audit-events subsystem yet."

### Admin control / RBAC audit

**N/A — single-tenant, no auth in MVP1.** Per spec §6 + tech-stack matrix. Activates at MVP4.

---

## 12) Definition of plan done

This implementation plan is execution-ready when:

- [x] Every FR (FR-1..FR-7) is mapped to stories/tasks/tests/docs updates (§1, §11).
- [x] Every story includes New files, Modified files, Endpoints (where API-facing), Key interfaces (where applicable), Tasks, and DoD.
- [x] Test layers (unit/integration/contract) are explicitly scoped (§3.1–§3.3); E2E correctly marked N/A.
- [x] Documentation updates across docs/01–05 are planned and owned (§4).
- [x] Lean refactor scope correctly marked N/A for greenfield (§5).
- [x] Phase/epic gates are measurable.
- [x] Story-by-Story Verification Gate is included (§10).
- [x] Plan consistency review (§11) has been performed; one Medium finding (`incapable` enum mismatch) is documented in §13 Review log; no unresolved Highs.
- [ ] **Cross-model GPT-5.5 review skipped** — `OPENAI_API_KEY` not available at repo root. Opus-only Pass 1 + Pass 2 ran; user should consider running `/impl-plan-gen … review` once a key is configured.
- [ ] User approves the plan (orchestrator approval gate).

---

## 13) Review log

**Mode:** Generate
**Source spec:** [`feature_spec.md`](feature_spec.md) (392 lines)
**Reviewer:** Opus (Pass 1 plan-internal + Pass 2 codebase accuracy)
**Cross-model (GPT-5.5):** **Skipped** — no `OPENAI_API_KEY` in any `.env` at repo root; per skill workflow Step 6 fallback rule, alerted user and proceeded.

### Findings raised during plan generation

| # | Severity | Source | Finding | Resolution |
|---|---|---|---|---|
| 1 | Medium | Pass 1 (plan-spec consistency) | Spec FR-2 lists `subsystems.openai` enum as `configured | missing_key | incapable` (3 values), but spec §7.4 enum table lists only `configured | missing_key` (2 values). | Plan implements FR-2 (3 values) — FR is more specific than the §7.4 table summary. **Recommendation:** patch spec §7.4 to add `incapable` row. Surface as a spec-gen Review & Patch finding when next reviewing the spec. |
| 2 | Low | Pass 1 (cross-doc consistency) | Spec §14 references `web/tests/e2e/`; tech-stack.md §"Code organization", deployment.md, and system-overview.md all use `ui/`. | Plan uses `ui/` (canonical). No E2E tests in this feature so functionally moot. **Recommendation:** patch spec §14 to use `ui/`. |
| 3 | Low | Pass 1 (cross-doc consistency) | Spec §3 in-scope monorepo layout lists "tests/" at top level; spec §14 specifies `backend/tests/{unit,integration,contract}/`; tech-stack.md says "mirror the source tree under `tests/`." | Plan uses `backend/tests/{unit,integration,contract}/` per spec §14 (most specific). For frontend, uses `ui/src/__tests__/` (vitest convention). **Recommendation:** patch tech-stack.md `tests/` mention to clarify per-layer convention. |
| 4 | Low | Pass 2 (codebase verification) | `state.md`, `architecture.md`, `CLAUDE.md` referenced by impl-plan-gen and impl-execute skills don't exist at repo root. | Story 5.2 creates them as part of this feature. Documented in plan §4.0. |
| 5 | Low | Pass 1 (deployment.md compliance) | deployment.md sample YAML omits an `api` healthcheck; plan adds one (so `worker.depends_on.api: condition: service_healthy` works). | Plan documents the addition in Story 4.2 task list. **Recommendation:** patch deployment.md sample to include the API healthcheck for correctness. |
| 6 | Low | Pass 2 | OpenSearch healthcheck not in deployment.md sample; plan adds one (probes `http://localhost:9200` inside the OpenSearch container). | Plan documents in Story 4.2. **Recommendation:** patch deployment.md to include. |
| 7 | Medium | User feedback (post-draft) | Initial draft did not enumerate the operator-environment handoff points (`.env` copy, `./secrets/openai_key` population, GitHub branch protection update). Without explicit pause points, impl-execute could either auto-create files it shouldn't (`.env`) or skip operator-only steps entirely (branch protection). | Added §7.5 "Manual operator handoffs" enumerating all three pause points with exact prompts, hard-stop rules, and explicit prohibitions on auto-creating `.env` / auto-populating secret files / auto-calling the GitHub branch-protection API. Story 4.4 task 5 and Story 5.2 task 9 reference §7.5. Story 4.4 DoD added a parity check. |

### Verification ledger (material claims)

| Claim | Verified by | Status |
|---|---|---|
| Migration directory is `migrations/` at repo root | tech-stack.md §"Code organization" | Verified |
| First Alembic revision id is `0001_baseline` (pinned) | Story 2.2 task list | Verified — pinned via `alembic revision --rev-id 0001` |
| `/healthz` is unversioned (not under `/api/v1/`) | api-conventions.md §"URL structure" | Verified |
| Error envelope shape `{detail: {error_code, message, retryable}}` | api-conventions.md §"Error envelope" | Verified |
| 6-container Compose stack: postgres, redis, api, worker, elasticsearch, opensearch | deployment.md §"MVP1 deployment shape" | Verified |
| `python:3.12-slim` Docker base | spec §19 decision log | Verified |
| `uv` lockfile workflow | spec §19 decision log | Verified |
| gitleaks for pre-commit secret scanning | spec §19 decision log | Verified |
| `RELYLOOP_GIT_SHA` Docker ARG → `/healthz.version` | spec §19 decision log | Verified |
| `subsystems.openai` enum has 3 values per FR-2 | spec FR-2 vs §7.4 mismatch | Conflict resolved — plan implements FR-2 |
| `ui/` is canonical frontend dir name | tech-stack.md, deployment.md, system-overview.md | Verified |
| 80% backend coverage gate | spec FR-4, tech-stack.md | Verified |
| Conventional Commits regex from spec FR-6 | spec FR-6 verbatim | Verified |
| Capability check 4 steps + 24h Redis cache | llm-orchestration.md §"Capability check at startup" + spec FR-7 | Verified |
| Single-phase ship; no `phase2_idea.md` needed | spec §3 Phase boundaries | Verified |

### Spec-plan alignment status

- All 7 FRs covered by ≥1 story.
- All 8 ACs (AC-1..AC-8) covered by story DoDs.
- 1 endpoint, 1 contract test — match.
- 1 feature-specific error code (`SERVICE_UNAVAILABLE`) covered.
- 0 orphaned stories.
- 1 Medium finding (#1) requires spec patch (informational; plan unblocked because plan implements the more-specific FR).

### Open questions for the user

None. Plan is ready for execution review.

### Proposed downstream patches

When `/spec-gen … review` next runs against `infra_foundation/feature_spec.md`, suggest:
- §7.4: add `incapable` row for `subsystems.openai`
- §14: rename `web/tests/e2e/` → `ui/tests/e2e/`
- §3 in-scope monorepo: clarify per-layer test location convention or drop the top-level `tests/` mention

When `/impl-plan-gen … review` runs against `deployment.md`:
- Sample `docker-compose.yml`: add `api` healthcheck and `opensearch` healthcheck for completeness
