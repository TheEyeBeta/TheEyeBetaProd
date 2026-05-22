# theeyebeta — Makefile
# Default goal: print the help menu.
.DEFAULT_GOAL := help

# ── ANSI colours ──────────────────────────────────────────────────────────────
BOLD  := \033[1m
RESET := \033[0m
GREEN := \033[32m
CYAN  := \033[36m
RED   := \033[31m
GREY  := \033[90m

# ── Tool aliases (override on CLI: make lint UV="python -m uv") ───────────────
UV             := uv
DC             := docker compose
PYTEST         := $(UV) run pytest
RUFF           := $(UV) run ruff
BLACK          := $(UV) run black
MYPY           := $(UV) run mypy
SQLFLUFF       := $(UV) run sqlfluff
ALEMBIC        := $(UV) run alembic

# ── C++ build preset (override: make build-cpp PRESET=linux-debug) ───────────
PRESET         := linux-release
BUILD_DIR      := build/$(PRESET)

# ── Help ──────────────────────────────────────────────────────────────────────
# Parses ##@ section headings and ## target descriptions from this file.
.PHONY: help
help:  ## Show this help
	@awk ' \
	  BEGIN { FS = ":.*##"; printf "\n$(BOLD)theeyebeta$(RESET)\n\n" } \
	  /^[a-zA-Z0-9_%\-]+:.*##/ { \
	    gsub(/logs-%/, "logs-<svc>"); \
	    printf "  $(CYAN)%-20s$(RESET) %s\n", $$1, $$2 \
	  } \
	  /^##@/ { printf "\n$(BOLD)%s$(RESET)\n", substr($$0, 5) } \
	' $(MAKEFILE_LIST)
	@echo ""

# ─────────────────────────────────────────────────────────────────────────────
##@ Infrastructure
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: up
up: ## Start all services and wait until every healthcheck is green
	@printf "$(GREEN)$(BOLD)▶ docker compose up$(RESET)\n"
	$(DC) up -d --wait
	@printf "$(GREEN)$(BOLD)✔ All services healthy$(RESET)\n"
	@$(MAKE) --no-print-directory ps

.PHONY: down
down: ## Stop containers (volumes are preserved)
	@printf "$(GREY)▶ docker compose down$(RESET)\n"
	$(DC) down

.PHONY: nuke
nuke: ## [DEV ONLY] Stop and DELETE all volumes — requires CONFIRM=yes
ifndef CONFIRM
	@printf "$(RED)$(BOLD)✖ Refusing: nuke destroys all data.$(RESET)\n"
	@printf "$(RED)  Run:  make nuke CONFIRM=yes$(RESET)\n"
	@exit 1
endif
ifneq ($(CONFIRM),yes)
	@printf "$(RED)$(BOLD)✖ CONFIRM must equal 'yes', got '$(CONFIRM)'$(RESET)\n"
	@exit 1
endif
	@printf "$(RED)$(BOLD)☠  Nuking all volumes...$(RESET)\n"
	$(DC) down -v --remove-orphans
	@printf "$(RED)$(BOLD)☠  Done — all data destroyed$(RESET)\n"

.PHONY: ps
ps: ## Show service status
	$(DC) ps

.PHONY: deploy
deploy: ## Pull latest images, bring services up, verify healthchecks
	@printf "$(GREEN)$(BOLD)▶ Pulling images$(RESET)\n"
	$(DC) pull
	@printf "$(GREEN)$(BOLD)▶ Deploying$(RESET)\n"
	$(DC) up -d --wait
	@printf "$(GREEN)$(BOLD)✔ Deploy complete$(RESET)\n"
	@$(MAKE) --no-print-directory status

.PHONY: status
status: ## Alias for: tb status
	tb status

logs-%: ## Tail logs for a service, e.g. make logs-postgres
	$(DC) logs -f $*

# ─────────────────────────────────────────────────────────────────────────────
##@ Code quality
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: lint
lint: lint-python lint-cpp lint-sql ## Run all linters (ruff + mypy + clang-format + sqlfluff)

.PHONY: lint-python
lint-python: ## ruff check + ruff format --check + mypy --strict
	@printf "$(BOLD)▶ ruff check$(RESET)\n"
	$(RUFF) check .
	@printf "$(BOLD)▶ ruff format --check$(RESET)\n"
	$(RUFF) format --check .
	@printf "$(BOLD)▶ mypy$(RESET)\n"
	@MYPY_PATHS=$$(for d in libs services tb; do [ -d "$$d" ] && printf "$$d "; done); \
	if [ -n "$$MYPY_PATHS" ]; then \
		$(MYPY) $$MYPY_PATHS; \
	else \
		printf "$(GREY)  No Python source dirs found — skipping mypy$(RESET)\n"; \
	fi

.PHONY: lint-cpp
lint-cpp: ## clang-format --dry-run on all C++ sources
	@printf "$(BOLD)▶ clang-format --dry-run$(RESET)\n"
	@CPP_FILES=$$(find cpp -type f \( -name "*.cpp" -o -name "*.hpp" -o -name "*.cc" -o -name "*.h" \) \
	    2>/dev/null | head -1); \
	if [ -n "$$CPP_FILES" ]; then \
	    find cpp -type f \( -name "*.cpp" -o -name "*.hpp" -o -name "*.cc" -o -name "*.h" \) \
	        -exec clang-format --dry-run --Werror {} +; \
	else \
	    printf "$(GREY)  No C++ files found — skipping clang-format$(RESET)\n"; \
	fi

.PHONY: lint-sql
lint-sql: ## sqlfluff lint on migrations and raw SQL
	@printf "$(BOLD)▶ sqlfluff lint$(RESET)\n"
	@SQL_FILES=$$(find db -name "*.sql" 2>/dev/null | head -1); \
	if [ -n "$$SQL_FILES" ]; then \
	    $(SQLFLUFF) lint --dialect postgres db/; \
	else \
	    printf "$(GREY)  No .sql files found — skipping sqlfluff$(RESET)\n"; \
	fi

# ─────────────────────────────────────────────────────────────────────────────
##@ Formatting
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: format
format: format-python format-cpp ## Auto-format everything (ruff + black + clang-format)

.PHONY: format-python
format-python: ## ruff format + black
	@printf "$(BOLD)▶ ruff format$(RESET)\n"
	$(RUFF) format .
	$(RUFF) check --fix .
	@printf "$(BOLD)▶ black$(RESET)\n"
	$(BLACK) .

.PHONY: format-cpp
format-cpp: ## clang-format -i on all C++ sources
	@printf "$(BOLD)▶ clang-format -i$(RESET)\n"
	@CPP_FILES=$$(find cpp -type f \( -name "*.cpp" -o -name "*.hpp" -o -name "*.cc" -o -name "*.h" \) \
	    2>/dev/null | head -1); \
	if [ -n "$$CPP_FILES" ]; then \
	    find cpp -type f \( -name "*.cpp" -o -name "*.hpp" -o -name "*.cc" -o -name "*.h" \) \
	        -exec clang-format -i {} +; \
	    printf "$(GREEN)  Done$(RESET)\n"; \
	else \
	    printf "$(GREY)  No C++ files found — skipping clang-format$(RESET)\n"; \
	fi

# ─────────────────────────────────────────────────────────────────────────────
##@ Testing
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: test
test: ## Unit tests: pytest -m "not integration and not smoke" + ctest
	@printf "$(BOLD)▶ pytest (unit)$(RESET)\n"
	$(PYTEST) -m "not integration and not smoke" --tb=short -q
	@printf "$(BOLD)▶ ctest$(RESET)\n"
	@if [ -d "$(BUILD_DIR)" ]; then \
	    ctest --test-dir $(BUILD_DIR) --output-on-failure -j$$(nproc 2>/dev/null || echo 4); \
	else \
	    printf "$(GREY)  No CMake build dir ($(BUILD_DIR)) — skipping ctest$(RESET)\n"; \
	fi

.PHONY: test-int
test-int: ## Integration tests: pytest -m integration (uses testcontainers — no make up needed)
	@printf "$(BOLD)▶ pytest (integration / testcontainers)$(RESET)\n"
	$(PYTEST) -m integration --tb=short -q

.PHONY: test-smoke
test-smoke: ## Smoke tests: full stack (requires make up)
	@printf "$(BOLD)▶ pytest (smoke — full stack)$(RESET)\n"
	$(PYTEST) -m smoke -v

# ─────────────────────────────────────────────────────────────────────────────
##@ Database
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: db-migrate
db-migrate: ## Apply Alembic migrations: alembic upgrade head
	@printf "$(BOLD)▶ alembic upgrade head$(RESET)\n"
	@bash scripts/db-migrate.sh
	@printf "$(GREEN)✔ Migrations complete$(RESET)\n"

.PHONY: db-revision
db-revision: ## Generate a new migration: make db-revision MSG="add orders table"
ifndef MSG
	@printf "$(RED)✖ MSG is required$(RESET)\n"
	@printf "  Usage: make db-revision MSG=\"add orders table\"\n"
	@exit 1
endif
	@printf "$(BOLD)▶ alembic revision --autogenerate -m \"$(MSG)\"$(RESET)\n"
	$(ALEMBIC) revision --autogenerate -m "$(MSG)"

# ─────────────────────────────────────────────────────────────────────────────
##@ C++ Build
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: build-cpp
build-cpp: ## CMake configure + build (preset: linux-release)
	@if [ ! -f cpp/CMakePresets.json ] && [ ! -f CMakePresets.json ]; then \
	    printf "$(GREY)  No CMakePresets.json found — skipping C++ build$(RESET)\n"; \
	    exit 0; \
	fi
	@printf "$(BOLD)▶ conan install$(RESET)\n"
	conan install cpp/ \
	    --output-folder=$(BUILD_DIR)/conan \
	    --build=missing \
	    --settings=build_type=Release
	@printf "$(BOLD)▶ cmake --preset $(PRESET)$(RESET)\n"
	cmake --preset $(PRESET)
	@printf "$(BOLD)▶ cmake --build --preset $(PRESET)$(RESET)\n"
	cmake --build --preset $(PRESET) --parallel $$(nproc 2>/dev/null || echo 4)
	@printf "$(GREEN)✔ C++ build complete — artefacts in $(BUILD_DIR)$(RESET)\n"

# ─────────────────────────────────────────────────────────────────────────────
##@ Setup
# ─────────────────────────────────────────────────────────────────────────────

.PHONY: decrypt-env
decrypt-env: ## Decrypt secrets → .env (ENV=dev|staging|prod)
	@bash scripts/decrypt-env.sh $(ENV)

.PHONY: install
install: ## Install Python dev dependencies via uv
	@printf "$(BOLD)▶ uv sync$(RESET)\n"
	$(UV) sync --group dev
	@printf "$(GREEN)✔ Dependencies installed$(RESET)\n"

.PHONY: install-hooks
install-hooks: ## Install pre-commit + commit-msg hooks (reads default_install_hook_types from config)
	@printf "$(BOLD)▶ pre-commit install$(RESET)\n"
	$(UV) run pre-commit install
	@printf "$(BOLD)▶ pre-commit install --hook-type commit-msg$(RESET)\n"
	$(UV) run pre-commit install --hook-type commit-msg
	@printf "$(GREEN)✔ Hooks installed — pre-commit and commit-msg stages active$(RESET)\n"

.PHONY: hooks-update
hooks-update: ## Bump all pre-commit hook revisions to latest
	@printf "$(BOLD)▶ pre-commit autoupdate$(RESET)\n"
	$(UV) run pre-commit autoupdate

.PHONY: hooks-run
hooks-run: ## Run all pre-commit hooks against every file (useful after changing config)
	@printf "$(BOLD)▶ pre-commit run --all-files$(RESET)\n"
	$(UV) run pre-commit run --all-files
