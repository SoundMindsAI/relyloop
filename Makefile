# RelyLoop Makefile
# All targets per docs/02_product/planned_features/infra_foundation/feature_spec.md AC-8.
# `make` (no target) prints this help block.

.DEFAULT_GOAL := help
.PHONY: help fmt lint typecheck test test-unit test-integration test-contract \
        ui-lint ui-typecheck ui-test ui-build \
        pre-commit pre-commit-install \
        up down logs reset migrate migrate-create seed-clusters

help:  ## Show this help message
	@echo ""
	@echo "RelyLoop — available targets:"
	@echo ""
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Conventional flow: make up → make migrate → curl localhost:8000/healthz"
	@echo ""

# ---------- Code quality ----------

fmt:  ## Format Python (ruff format) and frontend (prettier)
	uv run ruff format .
	pnpm --dir ui format

lint: ui-lint  ## Lint Python (ruff check) and frontend (eslint)
	uv run ruff check .

typecheck: ui-typecheck  ## Type-check Python (mypy --strict) and frontend (tsc --noEmit)
	uv run mypy backend/

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

# ---------- Pre-commit (Story 1.4) ----------

pre-commit:  ## Run all pre-commit hooks against the entire repo
	uv run pre-commit run --all-files

pre-commit-install:  ## Install pre-commit hooks (commit-msg + pre-commit stages)
	uv run pre-commit install --hook-type commit-msg --hook-type pre-commit
	@echo "Pre-commit hooks installed. Hooks run automatically on git commit."

# ---------- Frontend (UI) ----------

ui-lint:  ## Lint frontend (next lint / eslint)
	pnpm --dir ui lint

ui-typecheck:  ## Type-check frontend (tsc --noEmit, --strict, noUncheckedIndexedAccess)
	pnpm --dir ui typecheck

ui-test:  ## Run frontend tests (vitest run)
	pnpm --dir ui test

ui-build:  ## Production build of the frontend (next build)
	pnpm --dir ui build

# ---------- Stack lifecycle (Story 4.4 fills install.sh) ----------

up:  ## Generate secrets if missing, then docker compose up -d (auto-bootstrap)
	bash scripts/install.sh

down:  ## docker compose stop (preserves data volumes)
	docker compose stop

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
