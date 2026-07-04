# ======================================================
# Configuration
# ======================================================
# Convention:
# - Use `docker compose ...` for full stack workflows (compose-first).
# - Keep `make` targets as local developer helpers.

# Commands / tooling
COMPOSE ?= docker compose
UV ?= $(or $(shell command -v uv 2>/dev/null),$(HOME)/.local/bin/uv)
BUN ?= $(or $(shell command -v bun 2>/dev/null),bun)
PREK ?= prek
PYTHON ?= python3
PRE_COMMIT_HOME ?= /tmp/pre-commit-cache
UV_CACHE_DIR ?= /tmp/uv-cache

# Terminal colors
GREEN := \033[0;32m
YELLOW := \033[0;33m
RED := \033[0;31m
CYAN := \033[0;36m
NC := \033[0m

# Project paths
BACKEND_DIR ?= backend

# Local virtualenv resolution
define RESOLVE_VENV_BIN
venv_bin=""; \
if [ -x "$(CURDIR)/.venv/bin/python" ]; then \
	venv_bin="$(CURDIR)/.venv/bin"; \
elif [ -x "$(CURDIR)/$(BACKEND_DIR)/.venv/bin/python" ]; then \
	venv_bin="$(CURDIR)/$(BACKEND_DIR)/.venv/bin"; \
else \
	printf "%b\n" "$(RED)❌ No project virtualenv found. Run make init first.$(NC)"; \
	exit 1; \
fi
endef

define ENSURE_FRONTEND_RUNTIME
node_version="$$( $(BUN) -e 'console.log(process.versions.node)' 2>/dev/null )"; \
if [ -z "$$node_version" ]; then \
	printf "%b\n" "$(RED)❌ Unable to resolve the Node.js compatibility version exposed by Bun.$(NC)"; \
	printf "%b\n" "$(YELLOW)Run make doctor for details.$(NC)"; \
	exit 1; \
fi; \
$(PYTHON) -c 'exec("""import re\nimport sys\nRED = \"\\033[0;31m\"\nYELLOW = \"\\033[0;33m\"\nNC = \"\\033[0m\"\nversion = sys.argv[1].strip()\nnormalized = version.removeprefix(\"v\")\nmatch = re.match(r\"^(\\d+)\\.(\\d+)\\.(\\d+)\", normalized)\nif match is None:\n    print(f\"{RED}❌ Unable to parse frontend runtime version: {version}{NC}\")\n    raise SystemExit(1)\nparsed = tuple(int(part) for part in match.groups())\nsupported = parsed >= (24, 0, 0)\nif not supported:\n    print(f\"{RED}❌ Bun exposes Node {version}, but frontend requires Node >=24.0.0.{NC}\")\n    print(f\"{YELLOW}Upgrade Bun or switch to Node 24.0.0+, then rerun the frontend command.{NC}\")\n    raise SystemExit(1)\n""")' "$$node_version"
endef

# PostgreSQL helpers
POSTGRES_USER ?= postgres
POSTGRES_DB ?= app

# ======================================================
# Meta
# ======================================================

.PHONY: help help-advanced \
		db-up db-down db-logs db-restart db-shell db-reset \
		init ensure-uv doctor check check-back check-front release-techlab \
		backend-start frontend-runtime-check frontend-install frontend-start frontend-build frontend-lint frontend-format frontend-test \
		format lint mypy precommit-install precommit-run \
		migrate-create migrate-upgrade migrate-downgrade migrate-current \
		pytest pytest-cov \
		compose-watch compose-up compose-down compose-logs compose-ps

help: ## Show this help message
	@printf "%b\n" "$(CYAN)Usage: make [target]$(NC)"
	@echo ""

	@printf "%b\n" "$(CYAN)Onboarding:$(NC)"
	@grep -E '^[a-zA-Z0-9_-]+:.*## \[DEV\]' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*## \\[DEV\\] "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'
	@echo ""

	@printf "%b\n" "$(CYAN)Local Backend:$(NC)"
	@grep -E '^[a-zA-Z0-9_-]+:.*## \[LOCAL\]' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*## \\[LOCAL\\] "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'
	@echo ""

	@printf "%b\n" "$(CYAN)Frontend:$(NC)"
	@grep -E '^[a-zA-Z0-9_-]+:.*## \[FRONTEND\]' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*## \\[FRONTEND\\] "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'
	@echo ""

	@printf "%b\n" "$(CYAN)Quality:$(NC)"
	@grep -E '^[a-zA-Z0-9_-]+:.*## \[QUALITY\]' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*## \\[QUALITY\\] "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'
	@echo ""

	@printf "%b\n" "$(CYAN)Database:$(NC)"
	@grep -E '^[a-zA-Z0-9_-]+:.*## \[DB\]' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*## \\[DB\\] "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'
	@echo ""

	@printf "%b\n" "$(CYAN)Migrations:$(NC)"
	@grep -E '^[a-zA-Z0-9_-]+:.*## \[MIGRATION\]' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*## \\[MIGRATION\\] "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'
	@echo ""

	@printf "%b\n" "$(CYAN)Compose:$(NC)"
	@grep -E '^[a-zA-Z0-9_-]+:.*## \[COMPOSE\]' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*## \\[COMPOSE\\] "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@printf "%b\n" "$(YELLOW)Tip: run 'make help-advanced' to list advanced/internal commands.$(NC)"
	@echo ""

help-advanced: ## Show advanced and internal commands
	@printf "%b\n" "$(CYAN)Usage: make [target]$(NC)"
	@echo ""
	@printf "%b\n" "$(CYAN)Advanced Commands:$(NC)"
	@grep -E '^[a-zA-Z0-9_-]+:.*## \[ADV\]' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*## \\[ADV\\] "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@printf "%b\n" "$(CYAN)Internal Commands:$(NC)"
	@grep -E '^[a-zA-Z0-9_-]+:.*## \[INTERNAL\]' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*## \\[INTERNAL\\] "}; {printf "  \033[36m%-25s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ======================================================
# Tooling versions (info)
# ======================================================

PYTHON_VERSION  := $(shell python --version 2>/dev/null)
UV_VERSION      := $(shell $(UV) --version 2>/dev/null)
DOCKER_VERSION  := $(shell docker --version 2>/dev/null)
COMPOSE_VERSION := $(shell docker compose version 2>/dev/null)


doctor: ## [DEV] Show local backend/frontend tooling status
	@printf "%b\n" "$(CYAN)Running local tooling doctor...$(NC)"
	@UV='$(UV)' BUN='$(BUN)' PYTHON='$(PYTHON)' BACKEND_DIR='$(BACKEND_DIR)' bash scripts/dev-doctor.sh
	@printf "%b\n" "$(GREEN)✓ Doctor completed$(NC)"


check: ## [DEV] Run canonical backend + frontend validation checks
	@printf "%b\n" "$(CYAN)Running full template checks (backend + frontend)...$(NC)"
	@UV='$(UV)' BUN='$(BUN)' PYTHON='$(PYTHON)' BACKEND_DIR='$(BACKEND_DIR)' MAKE_BIN='$(MAKE)' bash scripts/dev-check.sh all
	@printf "%b\n" "$(GREEN)✓ Full checks completed$(NC)"


check-back: ## [DEV] Run canonical backend validation checks
	@printf "%b\n" "$(CYAN)Running backend checks...$(NC)"
	@UV='$(UV)' BUN='$(BUN)' PYTHON='$(PYTHON)' BACKEND_DIR='$(BACKEND_DIR)' MAKE_BIN='$(MAKE)' bash scripts/dev-check.sh back
	@printf "%b\n" "$(GREEN)✓ Backend checks completed$(NC)"


check-front: ## [DEV] Run canonical frontend validation checks
	@printf "%b\n" "$(CYAN)Running frontend checks...$(NC)"
	@UV='$(UV)' BUN='$(BUN)' PYTHON='$(PYTHON)' BACKEND_DIR='$(BACKEND_DIR)' MAKE_BIN='$(MAKE)' bash scripts/dev-check.sh front
	@printf "%b\n" "$(GREEN)✓ Frontend checks completed$(NC)"


init: ## [DEV] Initialize backend/frontend tooling and hooks
	@printf "%b\n" "$(CYAN)Starting project initialization...$(NC)"
	@UV='$(UV)' BUN='$(BUN)' PYTHON='$(PYTHON)' PREK='$(PREK)' PRE_COMMIT_HOME='$(PRE_COMMIT_HOME)' UV_CACHE_DIR='$(UV_CACHE_DIR)' BACKEND_DIR='$(BACKEND_DIR)' bash scripts/dev-init.sh
	@printf "%b\n" "$(GREEN)✓ Initialization completed$(NC)"


ensure-uv: ## [INTERNAL] Ensure uv is installed locally
	@if ! command -v $(UV) >/dev/null 2>&1; then \
		printf "%b\n" "$(YELLOW)⚠ uv is not installed.$(NC)"; \
		if [ ! -t 0 ]; then \
			printf "%b\n" "$(RED)❌ Cannot prompt to install uv in a non-interactive shell.$(NC)"; \
			printf "%b\n" "$(YELLOW)Install it manually: https://docs.astral.sh/uv/getting-started/installation/$(NC)"; \
			exit 1; \
		fi; \
		printf "Install uv now using the official installer? [y/N] "; \
		read -r answer; \
		case "$$answer" in \
			[yY]|[yY][eE][sS]) \
				if command -v curl >/dev/null 2>&1; then \
					curl -LsSf https://astral.sh/uv/install.sh | sh; \
				elif command -v wget >/dev/null 2>&1; then \
					wget -qO- https://astral.sh/uv/install.sh | sh; \
				else \
					printf "%b\n" "$(RED)❌ Neither curl nor wget is available to install uv automatically.$(NC)"; \
					exit 1; \
				fi; \
				if ! command -v $(UV) >/dev/null 2>&1; then \
					printf "%b\n" "$(RED)❌ uv installation completed but uv is still not available in PATH.$(NC)"; \
					printf "%b\n" "$(YELLOW)Reopen your shell or install it manually: https://docs.astral.sh/uv/getting-started/installation/$(NC)"; \
					exit 1; \
				fi ;; \
			*) \
				printf "%b\n" "$(RED)❌ uv installation skipped.$(NC)"; \
				printf "%b\n" "$(YELLOW)Install it manually: https://docs.astral.sh/uv/getting-started/installation/$(NC)"; \
				exit 1 ;; \
		esac; \
	else \
		printf "%b\n" "$(GREEN)✓ uv is already available$(NC)"; \
	fi


release-techlab: ## [DEV] Prepare a Techlab release locally (usage: make release-techlab version=0.2.0)
	@if [ -z "$(version)" ]; then \
		printf "%b\n" "$(RED)❌ Please provide a version: make release-techlab version=0.2.0$(NC)"; \
		exit 1; \
	fi
	@printf "%b\n" "$(CYAN)Preparing Techlab release $(version)...$(NC)"
	$(PYTHON) scripts/release_techlab.py --version "$(version)"
	@printf "%b\n" "$(GREEN)✓ Release preparation completed$(NC)"


# ======================================================
# Local backend
# ======================================================

backend-start: ## [LOCAL] Start backend in local dev mode
	@printf "%b\n" "$(CYAN)Starting backend (FastAPI dev server)...$(NC)"
	@$(RESOLVE_VENV_BIN); \
	cd $(BACKEND_DIR) && PATH="$$venv_bin:$$PATH" fastapi dev app/main.py --host 0.0.0.0 --port 8000

frontend-install: ## [ADV] Install frontend workspace dependencies with Bun
	@printf "%b\n" "$(CYAN)Installing frontend dependencies with Bun...$(NC)"
	$(BUN) install --cwd frontend --frozen-lockfile
	@printf "%b\n" "$(GREEN)✓ Frontend dependencies installed$(NC)"

frontend-runtime-check: ## [INTERNAL] Validate the Bun/Node runtime expected by Vite
	@printf "%b\n" "$(CYAN)Checking frontend runtime compatibility...$(NC)"
	@$(ENSURE_FRONTEND_RUNTIME)
	@printf "%b\n" "$(GREEN)✓ Frontend runtime is compatible$(NC)"

frontend-start: ## [FRONTEND] Start the frontend dev server
	@printf "%b\n" "$(CYAN)Starting frontend dev server...$(NC)"
	@$(ENSURE_FRONTEND_RUNTIME)
	$(BUN) run --cwd frontend dev


frontend-build: ## [FRONTEND] Build the frontend workspace
	@printf "%b\n" "$(CYAN)Building frontend workspace...$(NC)"
	@$(ENSURE_FRONTEND_RUNTIME)
	$(BUN) run --cwd frontend build
	@printf "%b\n" "$(GREEN)✓ Frontend build completed$(NC)"

frontend-lint: ## [QUALITY] Run non-mutating frontend lint checks
	@printf "%b\n" "$(CYAN)Running frontend lint checks...$(NC)"
	$(BUN) run --cwd frontend lint
	@printf "%b\n" "$(GREEN)✓ Frontend lint checks completed$(NC)"

frontend-format: ## [QUALITY] Apply frontend formatting and safe fixes
	@printf "%b\n" "$(CYAN)Applying frontend formatting...$(NC)"
	$(BUN) run --cwd frontend format
	@printf "%b\n" "$(GREEN)✓ Frontend formatting completed$(NC)"


# ======================================================
# Quality
# ======================================================

format: ## [QUALITY] Format backend code (ruff)
	@printf "%b\n" "$(CYAN)Formatting backend code...$(NC)"
	@$(RESOLVE_VENV_BIN); \
	cd $(BACKEND_DIR) && PATH="$$venv_bin:$$PATH" bash scripts/format.sh
	@printf "%b\n" "$(GREEN)✓ Backend formatting completed$(NC)"

lint: ## [QUALITY] Run backend lint checks (ruff)
	@printf "%b\n" "$(CYAN)Running backend lint checks...$(NC)"
	@$(RESOLVE_VENV_BIN); \
	cd $(BACKEND_DIR) && PATH="$$venv_bin:$$PATH" bash scripts/lint.sh
	@printf "%b\n" "$(GREEN)✓ Backend lint checks completed$(NC)"

mypy: ## [QUALITY] Run backend static type checks
	@printf "%b\n" "$(CYAN)Running backend type checks (mypy)...$(NC)"
	@$(RESOLVE_VENV_BIN); \
	cd $(BACKEND_DIR) && PATH="$$venv_bin:$$PATH" bash scripts/mypy.sh
	@printf "%b\n" "$(GREEN)✓ Backend type checks completed$(NC)"

precommit-install: ensure-uv ## [ADV] Install pre-commit hooks
	@printf "%b\n" "$(CYAN)Synchronizing backend dependencies for pre-commit...$(NC)"
	cd $(BACKEND_DIR) && UV_CACHE_DIR=$(UV_CACHE_DIR) UV_LINK_MODE=copy $(UV) sync --all-groups --frozen --no-progress --no-install-project
	@printf "%b\n" "$(CYAN)Installing pre-commit hooks...$(NC)"
	@$(RESOLVE_VENV_BIN); \
	cd $(BACKEND_DIR) && PRE_COMMIT_HOME=$(PRE_COMMIT_HOME) XDG_CACHE_HOME=/tmp/xdg-cache PATH="$$venv_bin:$$PATH" $(PREK) install -f --hook-type pre-commit
	@printf "%b\n" "$(GREEN)✓ Pre-commit hooks installed$(NC)"

precommit-run: ## [ADV] Run all pre-commit hooks
	@printf "%b\n" "$(CYAN)Running pre-commit hooks...$(NC)"
	@$(RESOLVE_VENV_BIN); \
	cd $(BACKEND_DIR) && PRE_COMMIT_HOME=$(PRE_COMMIT_HOME) XDG_CACHE_HOME=/tmp/xdg-cache PATH="$$venv_bin:$$PATH" $(PREK) run --all-files
	@printf "%b\n" "$(GREEN)✓ Pre-commit run completed$(NC)"

# ======================================================
# Database (PostgreSQL)
# ======================================================

db-up: ## [DB] Start PostgreSQL database
	@printf "%b\n" "$(CYAN)Starting PostgreSQL service...$(NC)"
	$(COMPOSE) up -d db
	@printf "%b\n" "$(YELLOW)⏳ Waiting for PostgreSQL to be ready...$(NC)"
	@until $(COMPOSE) exec -T db pg_isready -U $(POSTGRES_USER) -d $(POSTGRES_DB) > /dev/null 2>&1; do \
		sleep 2; \
	done
	@printf "%b\n" "$(GREEN)✅ PostgreSQL is ready!$(NC)"

db-down: ## [ADV] Stop PostgreSQL service only
	@printf "%b\n" "$(CYAN)Stopping PostgreSQL service...$(NC)"
	$(COMPOSE) stop db
	@printf "%b\n" "$(GREEN)🛑 PostgreSQL service stopped$(NC)"

db-logs: ## [ADV] Show PostgreSQL logs
	@printf "%b\n" "$(CYAN)Streaming PostgreSQL logs...$(NC)"
	$(COMPOSE) logs -f db

db-restart: ## [ADV] Restart PostgreSQL database
	@printf "%b\n" "$(CYAN)Restarting PostgreSQL service...$(NC)"
	$(COMPOSE) restart db
	@printf "%b\n" "$(GREEN)🔄 Database restarted$(NC)"

db-shell: ## [ADV] Open psql shell inside PostgreSQL container
	@printf "%b\n" "$(CYAN)Opening PostgreSQL shell...$(NC)"
	$(COMPOSE) exec db psql -U $(POSTGRES_USER) -d $(POSTGRES_DB)

db-reset: ## [ADV] ⚠️ Reset public schema of PostgreSQL database
	@printf "%b\n" "$(RED)⚠ This will DELETE all data from $(POSTGRES_DB)$(NC)"
	$(COMPOSE) up -d db
	@printf "%b\n" "$(YELLOW)⏳ Waiting for PostgreSQL to be ready...$(NC)"
	@until $(COMPOSE) exec -T db pg_isready -U $(POSTGRES_USER) -d $(POSTGRES_DB) > /dev/null 2>&1; do \
		sleep 2; \
	done
	$(COMPOSE) exec -T db psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -v ON_ERROR_STOP=1 -c "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;"
	@printf "%b\n" "$(GREEN)✅ Database schema reset complete$(NC)"

# ======================================================
# Alembic migrations
# ======================================================

migrate-create: ## [MIGRATION] Create a new migration (usage: make migrate-create msg="your message")
	@if [ -z "$(msg)" ]; then \
		printf "%b\n" "$(RED)❌ Please provide a message: make migrate-create msg=\"your message\"$(NC)"; \
		exit 1; \
	fi
	@printf "%b\n" "$(CYAN)Creating migration: $(msg)$(NC)"
	@$(RESOLVE_VENV_BIN); \
	cd $(BACKEND_DIR) && PATH="$$venv_bin:$$PATH" alembic revision --autogenerate -m "$(msg)"
	@printf "%b\n" "$(GREEN)✓ Migration created$(NC)"

migrate-upgrade: ## [MIGRATION] Apply all pending migrations
	@printf "%b\n" "$(CYAN)Applying pending migrations...$(NC)"
	@$(RESOLVE_VENV_BIN); \
	cd $(BACKEND_DIR) && PATH="$$venv_bin:$$PATH" alembic upgrade head
	@printf "%b\n" "$(GREEN)✓ Migrations applied$(NC)"

migrate-downgrade: ## [ADV] Rollback one migration (usage: make migrate-downgrade rev=-1)
	@printf "%b\n" "$(CYAN)Rolling back migration...$(NC)"
	@rev_to_use=$${rev:--1}; \
	$(RESOLVE_VENV_BIN); \
	cd $(BACKEND_DIR) && PATH="$$venv_bin:$$PATH" alembic downgrade "$$rev_to_use"
	@printf "%b\n" "$(GREEN)✓ Migration rollback completed$(NC)"

migrate-current: ## [ADV] Show current migration version
	@printf "%b\n" "$(CYAN)Showing current migration version...$(NC)"
	@$(RESOLVE_VENV_BIN); \
	cd $(BACKEND_DIR) && PATH="$$venv_bin:$$PATH" alembic current

# ======================================================
# Tests
# ======================================================

pytest: ## [QUALITY] Run backend tests (usage: make pytest args="...")
	@printf "%b\n" "$(CYAN)Running backend tests...$(NC)"
	@$(RESOLVE_VENV_BIN); \
	cd $(BACKEND_DIR) && PATH="$$venv_bin:$$PATH" pytest $(args)
	@printf "%b\n" "$(GREEN)✓ Backend tests completed$(NC)"

pytest-cov: ## [ADV] Run backend tests with coverage report
	@printf "%b\n" "$(CYAN)Running backend tests with coverage...$(NC)"
	@$(RESOLVE_VENV_BIN); \
	cd $(BACKEND_DIR) && PATH="$$venv_bin:$$PATH" bash scripts/test.sh
	@printf "%b\n" "$(GREEN)✓ Backend coverage tests completed$(NC)"

# ======================================================
# Docker compose
# ======================================================

compose-watch: ## [COMPOSE] Start full local stack in watch mode
	@printf "%b\n" "$(CYAN)Starting full stack in watch mode...$(NC)"
	$(COMPOSE) watch

compose-up: ## [ADV] Start full local stack in detached mode
	@printf "%b\n" "$(CYAN)Starting full local stack (detached)...$(NC)"
	$(COMPOSE) up -d
	@printf "%b\n" "$(GREEN)✓ Full local stack started$(NC)"

compose-down: ## [ADV] Stop local stack
	@printf "%b\n" "$(CYAN)Stopping local stack...$(NC)"
	$(COMPOSE) down
	@printf "%b\n" "$(GREEN)✓ Local stack stopped$(NC)"

compose-logs: ## [ADV] Show stack logs (usage: make compose-logs service=backend)
	@printf "%b\n" "$(CYAN)Streaming stack logs...$(NC)"
	$(COMPOSE) logs -f $(service)

compose-ps: ## [ADV] Show stack service status
	@printf "%b\n" "$(CYAN)Showing stack service status...$(NC)"
	$(COMPOSE) ps
