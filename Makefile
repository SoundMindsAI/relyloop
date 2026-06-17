# RelyLoop Makefile
# All targets per docs/02_product/planned_features/infra_foundation/feature_spec.md AC-8.
# `make` (no target) prints this help block.

.DEFAULT_GOAL := help
.PHONY: help fmt lint typecheck test test-unit test-integration test-contract test-worktree \
        backend-fmt backend-lint backend-typecheck \
        ui-fmt ui-lint ui-typecheck ui-test ui-build ui-dev \
        pre-commit pre-commit-install \
        up down restart logs reset migrate migrate-create seed-clusters seed-es seed-solr \
        dev dashboard license-inventory

help:  ## Show this help message
	@echo ""
	@echo "RelyLoop — available targets:"
	@echo ""
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Conventional flow: make up → curl localhost:8000/healthz"
	@echo "(make migrate is now run automatically by the migrate init container at boot;"
	@echo " invoke manually only to apply a freshly-authored revision without bouncing.)"
	@echo ""

# ---------- Backend code quality (per infra_make_targets_split_backend_only) ----------
#
# `backend-*` sub-targets mirror the existing `ui-*` siblings below.
# Backend-only contributors (humans or agents on backend/*.py changes)
# can run these without tripping the UI tooling's Node ≥20.18 engine
# guard. The bundled `fmt`/`lint`/`typecheck` targets compose
# `backend-*` + `ui-*` so CI behavior is unchanged.

backend-fmt:  ## Format Python (ruff format) — backend only, skips UI
	uv run ruff format .

backend-lint:  ## Lint Python (ruff check) — backend only, skips UI
	uv run ruff check .

backend-typecheck:  ## Type-check Python (mypy --strict) — backend only, skips UI
	uv run mypy backend/

# ---------- Code quality (composed: backend + UI) ----------

fmt: backend-fmt ui-fmt  ## Format Python (ruff format) and frontend (prettier)

lint: backend-lint ui-lint  ## Lint Python (ruff check) and frontend (eslint)

typecheck: backend-typecheck ui-typecheck  ## Type-check Python (mypy --strict) and frontend (tsc --noEmit)

# ---------- Tests ----------

test: test-unit test-integration test-contract ui-test  ## Run all backend + UI test layers

test-unit:  ## Run backend unit tests (smoke test required; exit-5 NOT tolerated)
	uv run pytest backend/tests/unit/

test-integration:  ## Run backend integration tests from host (Postgres tests skip — see runbook for alternatives)
	@uv run pytest -m integration backend/tests/integration/ ; rc=$$?; \
	  [ $$rc -eq 0 ] || [ $$rc -eq 5 ] || exit $$rc   # exit 5 = no tests yet; OK pre-Story-2.2

test-contract:  ## Run backend contract tests (response shape + error codes)
	@uv run pytest backend/tests/contract/ ; rc=$$?; \
	  [ $$rc -eq 0 ] || [ $$rc -eq 5 ] || exit $$rc   # exit 5 = no tests yet; OK pre-Story-3.2

test-worktree:  ## Run tests in a one-shot container that mounts the sibling worktree (use CMD="..." to override). Phase 2 of infra_agent_sibling_worktree_isolation.
	@bash scripts/run-tests-in-worktree.sh $(if $(CMD),--cmd "$(CMD)")

# ---------- Pre-commit (Story 1.4) ----------

pre-commit:  ## Run all pre-commit hooks against the entire repo
	uv run pre-commit run --all-files

pre-commit-install:  ## Install pre-commit hooks (commit-msg + pre-commit stages)
	uv run pre-commit install --hook-type commit-msg --hook-type pre-commit
	@echo "Pre-commit hooks installed. Hooks run automatically on git commit."

# ---------- Frontend (UI) ----------

ui-fmt:  ## Format frontend (prettier)
	pnpm --dir ui format

ui-lint:  ## Lint frontend (next lint / eslint)
	pnpm --dir ui lint

ui-typecheck:  ## Type-check frontend (tsc --noEmit, --strict, noUncheckedIndexedAccess)
	pnpm --dir ui typecheck

ui-test:  ## Run frontend tests (vitest run)
	pnpm --dir ui test

ui-build:  ## Production build of the frontend (next build)
	pnpm --dir ui build

# `ui-dev` runs the Next.js dev server. Resolves Node via nvm when present —
# the repo's `.nvmrc` pins Node 22 (Next 16 + Vitest 4 require >=20.18). If
# nvm isn't installed we fall back to whatever `node` is on PATH; the dev
# server will then surface its own version error if too old.
NVM_GUARD = if [ -s "$$HOME/.nvm/nvm.sh" ]; then \
	  . "$$HOME/.nvm/nvm.sh"; \
	  nvm use --silent >/dev/null 2>&1 || nvm use --silent default; \
	fi

ui-dev:  ## Start the Next.js dev server (http://localhost:3000) — uses .nvmrc
	@$(NVM_GUARD); pnpm --dir ui dev

# ---------- Stack lifecycle (Story 4.4 fills install.sh) ----------

up:  ## Generate secrets if missing, then docker compose up -d (set RELYLOOP_ENGINES=es,os,solr — any subset — to opt into a smaller engine set; default = all three)
	bash scripts/install.sh

corp-ca-extract:  ## Probe the live TLS chain and save the corp root CA to ./secrets/corp_ca.crt (for installs behind a corp HTTPS proxy with TLS interception)
	bash scripts/corp-ca-extract.sh

down:  ## docker compose down (removes containers + network; preserves data volumes)
	docker compose down

restart:  ## docker compose restart api + worker (fast bounce when something wedges)
	docker compose restart api worker

logs:  ## Tail API + worker logs (docker compose logs -f api worker)
	docker compose logs -f api worker

reset:  ## DESTRUCTIVE: docker compose down -v && rm -rf ./data (use FORCE=1 to skip prompt)
	@if [ "$(FORCE)" != "1" ]; then \
		printf "About to delete all containers, volumes, and ./data/. Type 'yes' to confirm: "; \
		read confirm; \
		[ "$$confirm" = "yes" ] || { echo "Aborted."; exit 1; }; \
	fi
	docker compose down -v
	rm -rf ./data

dev:  ## One-shot: ensure backend stack is up, then run the UI dev server in foreground
	@if ! docker compose ps --status running --services 2>/dev/null | grep -q '^api$$'; then \
	  echo "Backend not running — starting via 'make up'…"; \
	  $(MAKE) up; \
	else \
	  echo "Backend already running on http://localhost:8000"; \
	fi
	@echo "Starting UI dev server on http://localhost:3000 (Ctrl-C to stop)…"
	@$(MAKE) ui-dev

# ---------- Migrations (Story 2.2 wires alembic) ----------

migrate:  ## alembic upgrade head + initialize Optuna RDB schema (runs inside api container)
	@docker compose ps --status running --services 2>/dev/null | grep -q '^api$$' || { \
	  echo "ERROR: api container is not running. Run 'make up' first."; exit 1; \
	}
	docker compose exec -T api alembic upgrade head
	docker compose exec -T api python -m backend.app.db.optuna_schema

seed-clusters:  ## Register local-es + local-opensearch clusters (idempotent — safe to re-run)
	@docker compose ps --status running --services 2>/dev/null | grep -q '^api$$' || { \
	  echo "ERROR: api container is not running. Run 'make up' first."; exit 1; \
	}
	docker compose exec -T api python -m backend.app.scripts.seed_clusters

seed-es:  ## Seed local-es 'products' index from samples/products.json (idempotent — DELETE+recreate)
	@docker compose ps --status running --services 2>/dev/null | grep -q '^api$$' || { \
	  echo "ERROR: api container is not running. Run 'make up' first."; exit 1; \
	}
	docker compose exec -T api python -m backend.app.scripts.seed_es

seed-solr:  ## Seed local-solr 'products' collection + ubi_queries + ubi_events (idempotent — overwrites by uniqueKey)
	@docker compose ps --status running --services 2>/dev/null | grep -q '^api$$' || { \
	  echo "ERROR: api container is not running. Run 'make up' first."; exit 1; \
	}
	docker compose exec -T api python -m backend.app.scripts.seed_solr_products \
	  --solr-host solr --solr-port 8983

seed-demo:  ## DESTRUCTIVE: TRUNCATE demo state + reseed 4 meaningful scenarios (FORCE=1 to skip prompt)
	@docker compose ps --status running --services 2>/dev/null | grep -q '^api$$' || { \
	  echo "ERROR: api container is not running. Run 'make up' first."; exit 1; \
	}
	@if [ "$(FORCE)" = "1" ]; then \
	  docker compose exec -T api python /app/scripts/seed_meaningful_demos.py --force; \
	else \
	  docker compose exec -T api python /app/scripts/seed_meaningful_demos.py; \
	fi

migrate-create:  ## Create new migration: make migrate-create name=<slug> (runs inside api container; pins sequential rev-id)
	@if [ -z "$(name)" ]; then \
		echo "ERROR: name=<slug> required (e.g., make migrate-create name=add_studies_table)"; \
		exit 1; \
	fi
	@docker compose ps --status running --services 2>/dev/null | grep -q '^api$$' || { \
	  echo "ERROR: api container is not running. Run 'make up' first."; exit 1; \
	}
	@NEXT_REV=$$(printf '%04d' $$(( $$(ls migrations/versions/[0-9]*.py 2>/dev/null | wc -l | tr -d ' ') + 1 ))); \
	  echo "Generating migration with --rev-id $${NEXT_REV} (sequential numeric per CLAUDE.md Rule #5)"; \
	  docker compose exec -T api alembic revision --autogenerate --rev-id "$${NEXT_REV}" -m "$(name)"
	@echo ""
	@echo "Run 'make fmt' to apply ruff formatting to the new revision file."

# ---------- Release Dashboards ----------

dashboard:  ## Regenerate docs/00_overview/<release>_dashboard.{html,md} from feature folders
	@python3 scripts/build_mvp1_dashboard.py

license-inventory: ## Regenerate the dependency license inventory (docs/04_security/license-inventory.md)
	uv run python scripts/gen_license_inventory.py
