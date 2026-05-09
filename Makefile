# RelyLoop Makefile
# All targets per docs/02_product/planned_features/infra_foundation/feature_spec.md AC-8.
# `make` (no target) prints this help block.

.DEFAULT_GOAL := help
.PHONY: help fmt lint typecheck test test-unit test-integration test-contract \
        up down logs reset migrate migrate-create

help:  ## Show this help message
	@echo ""
	@echo "RelyLoop — available targets:"
	@echo ""
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Conventional flow: make up → make migrate → curl localhost:8000/healthz"
	@echo ""

# ---------- Code quality (Story 1.2 wires uv) ----------

fmt:  ## Format Python (ruff format) and frontend (prettier)
	uv run ruff format .

lint:  ## Lint Python (ruff check) and frontend (eslint, wired by Story 1.3)
	uv run ruff check .

typecheck:  ## Type-check Python (mypy --strict)
	uv run mypy backend/

# ---------- Tests (Story 1.2 wires pytest; Story 1.3 wires vitest) ----------

test: test-unit test-integration test-contract  ## Run all backend test layers

test-unit:  ## Run backend unit tests (no DB / Docker required)
	uv run pytest backend/tests/unit/

test-integration:  ## Run backend integration tests (requires running stack)
	uv run pytest -m integration backend/tests/integration/

test-contract:  ## Run backend contract tests (response shape + error codes)
	uv run pytest backend/tests/contract/

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

migrate:  ## alembic upgrade head + initialize Optuna RDB schema (no-op MVP1)
	uv run alembic upgrade head
	uv run python -m backend.app.db.optuna_schema

migrate-create:  ## Create new migration: make migrate-create name=<slug>
	@if [ -z "$(name)" ]; then \
		echo "ERROR: name=<slug> required (e.g., make migrate-create name=add_studies_table)"; \
		exit 1; \
	fi
	uv run alembic revision --autogenerate -m "$(name)"
