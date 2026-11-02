# Radius developer entry points. `make help` lists them.
#
# Windows: GNU make is not installed by default. Either install it (e.g.
# `winget install ezwinports.make`, or use WSL/Git Bash) or use the equivalent
# PowerShell wrapper: `.\scripts\dev.ps1 help`. Same targets, same behaviour.

COMPOSE ?= docker compose
ENV_FILE ?= .env
PY ?= uv run --frozen python

.DEFAULT_GOAL := help
.PHONY: help env setup dev up down logs ps dev-local dev-local-demo test lint \
        seed-demo sandbox observability clean-volumes

help: ## List targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

env: ## Create .env from .env.example if missing (never overwrites)
	@test -f $(ENV_FILE) || (cp .env.example $(ENV_FILE) 	  && printf '
# Local dev default added by `make env` (compose passes an empty value otherwise, which the API rejects)
GITHUB_DEFAULT_ORGANIZATION_ID=00000000-0000-4000-8000-000000000001
' >> $(ENV_FILE) 	  && echo "created $(ENV_FILE) from .env.example")

setup: env ## Install Python (uv) and JS (pnpm via corepack) dependencies
	uv sync --frozen --extra dev
	corepack enable
	pnpm install --frozen-lockfile

dev: env ## ONE COMMAND: start postgres, migrations, api, worker, dashboard in Docker
	$(COMPOSE) --env-file $(ENV_FILE) up --build -d --wait --wait-timeout 300 postgres migrations api worker dashboard
	@echo ""
	@echo "Dashboard http://localhost:3000   API http://localhost:8000/docs   Health http://localhost:8000/api/v1/health"
	@echo "Logs: make logs   Stop: make down"

up: dev ## Alias for dev

down: ## Stop the stack (keeps the database volume)
	$(COMPOSE) --env-file $(ENV_FILE) --profile sandbox --profile observability down

logs: ## Follow api, worker and dashboard logs
	$(COMPOSE) logs -f api worker dashboard

ps: ## Show container status
	$(COMPOSE) ps

dev-local: env ## Run api + worker + dashboard natively with hot reload (memory storage; run make setup first)
	PATH="$$PWD/.venv/bin:$$PWD/.venv/Scripts:$$PATH" pnpm dev

dev-local-demo: env ## Like dev-local, with OPT-IN demo data (illustrative fixtures, demo login)
	RADIUS_SEED_DEMO_DATA=true PATH="$$PWD/.venv/bin:$$PWD/.venv/Scripts:$$PATH" pnpm dev

test: ## Run the Python test suite
	uv run --frozen python -m pytest

lint: ## Ruff on the Python code
	uv run --frozen python -m ruff check .

seed-demo: ## OPT-IN demo data into the SQL database (DEMO ONLY, see scripts/seed_demo.py)
	STORAGE_BACKEND=sql DATABASE_URL=postgresql+psycopg://radius:radius@localhost:$${POSTGRES_HOST_PORT:-5432}/radius $(PY) scripts/seed_demo.py --yes

sandbox: ## Build the sandbox test image (compose profile: sandbox)
	$(COMPOSE) --profile sandbox up --build sandbox-image

observability: ## Start Jaeger + Prometheus (see docs/OBSERVABILITY.md)
	$(COMPOSE) --profile observability up jaeger prometheus

clean-volumes: ## DESTRUCTIVE: stop the stack and delete the database volume
	$(COMPOSE) --profile sandbox --profile observability down -v
