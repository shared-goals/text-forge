# text-forge Makefile
#
# Development tools for text-forge contributors.
#
# Content repos should use their own Makefile + text-forge CLI commands.
# See whattodo/Makefile for example.

TEXT_FORGE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

# Tooling
UV := uv --project $(TEXT_FORGE_DIR)
UV_RUN := $(UV) run
PYTHON := $(UV_RUN) python

.PHONY: help install format lint check-i18n test clean info

help:
	@echo "text-forge - Development Tools"
	@echo ""
	@echo "Targets:"
	@echo "  make install       Sync Python dependencies (uv sync)"
	@echo "  make format        Format Python code with ruff"
	@echo "  make lint          Run lint checks via ruff"
	@echo "  make check-i18n    Check translation files for consistency"
	@echo "  make test          Run validation tests (uses whattodo as fixture)"
	@echo "  make clean         Remove build artifacts from whattodo"
	@echo "  make info          Show project paths"
	@echo ""
	@echo "For building content projects, see README.md and whattodo/Makefile"

install:
	@echo "==> Syncing dependencies via uv sync..."
	@$(UV) sync
	@echo "✓ Dependencies installed"

format:
	@echo "==> Formatting Python code with ruff..."
	@$(UV_RUN) ruff check --select I --fix $(TEXT_FORGE_DIR)
	@$(UV_RUN) ruff format $(TEXT_FORGE_DIR)
	@echo "✓ Code formatted"

lint:
	@echo "==> Running lint checks..."
	@$(UV_RUN) ruff check $(TEXT_FORGE_DIR)
	@echo "✓ Lint checks complete"

check-i18n:
	@echo "==> Checking i18n translation files..."
	@TRANSLATIONS_FILE="$(TEXT_FORGE_DIR)/mkdocs/overrides/assets/js/translations.json"; \
	$(PYTHON) .github/skills/check-i18n/scripts/check_i18n.py "$$TRANSLATIONS_FILE" \
		--html-glob "mkdocs/overrides/**/*.html" \
		--js-glob "mkdocs/overrides/**/*.js" \
		--key-pattern "editor_\w+"
	@echo "✓ i18n check complete"

test:
	@echo "==> Running unit tests with minimal fixtures..."
	@$(PYTHON) -m pytest tests/test_pipeline.py -v
	@echo "✓ Tests passed"

clean:
	@echo "==> Cleaning test build artifacts..."
	@rm -rf tests/fixtures/build
	@find $(TEXT_FORGE_DIR) -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find $(TEXT_FORGE_DIR) -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	@echo "✓ Cleaned"

info:
	@echo "text-forge paths:"
	@echo "  TEXT_FORGE_DIR: $(TEXT_FORGE_DIR)"
	@echo "  Tests:          tests/"
	@echo "  Fixtures:       tests/fixtures/"
