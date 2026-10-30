# text-forge Makefile
#
# Development tools for text-forge contributors.
#
# Content repos should use their own Makefile + text-forge CLI commands.
# See whattodo/Makefile for example.

SHELL := /bin/bash

TEXT_FORGE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

# Tooling
UV := uv --project $(TEXT_FORGE_DIR)
UV_RUN := $(UV) run
PYTHON := $(UV_RUN) python

.PHONY: help install format check-i18n test clean info release

help:
	@echo "text-forge - Development Tools"
	@echo ""
	@echo "Targets:"
	@echo "  make install       Sync Python dependencies (uv sync)"
	@echo "  make format        Run Ruff check --fix and Ruff format"
	@echo "  make check-i18n    Check translation files for consistency"
	@echo "  make test          Run i18n check and validation tests (uses whattodo as fixture)"
	@echo "  make clean         Remove build artifacts from whattodo"
	@echo "  make info          Show project paths"
	@echo "  make release       Tag and push release (triggers PyPI publish via CI/CD)"
	@echo ""
	@echo "For building content projects, see README.md and whattodo/Makefile"

install:
	@echo "==> Syncing dependencies via uv sync..."
	@$(UV) sync
	@echo "✓ Dependencies installed"

format:
	@echo "==> Running Ruff fix and format..."
	@$(UV_RUN) ruff check --fix $(TEXT_FORGE_DIR)
	@$(UV_RUN) ruff format $(TEXT_FORGE_DIR)
	@echo "✓ Code formatted"

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
	@$(MAKE) check-i18n
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

release:
	@echo "==> Creating release..."
	@CURRENT=$$(grep '^version = ' pyproject.toml | cut -d'"' -f2); \
	if [ -z "$$CURRENT" ]; then \
		echo "Error: Could not extract version from pyproject.toml"; \
		exit 1; \
	fi; \
	echo "Current version: $$CURRENT"; \
	echo "Bump type? [patch/minor/major] (default: patch)"; \
	read BUMP; \
	BUMP=$${BUMP:-patch}; \
	IFS='.' read -r MAJOR MINOR PATCH <<< "$$CURRENT"; \
	case "$$BUMP" in \
		patch) NEW="$$MAJOR.$$MINOR.$$((PATCH + 1))" ;; \
		minor) NEW="$$MAJOR.$$((MINOR + 1)).0" ;; \
		major) NEW="$$((MAJOR + 1)).0.0" ;; \
		*) echo "Error: Invalid bump type. Use patch, minor, or major"; exit 1 ;; \
	esac; \
	echo "New version: $$NEW"; \
	sed -i.bak "s/^version = \"$$CURRENT\"/version = \"$$NEW\"/" pyproject.toml && rm pyproject.toml.bak; \
	$(UV) lock; \
	echo "Commit message (default: chore: bump version to v$$NEW). Press Ctrl+C to cancel."; \
	read -r COMMIT_MESSAGE; \
	COMMIT_MESSAGE=$${COMMIT_MESSAGE:-chore: bump version to v$$NEW}; \
	git add -A; \
	git commit -m "$$COMMIT_MESSAGE"; \
	git tag -a "v$$NEW" -m "Release v$$NEW"; \
	git push origin main "v$$NEW"; \
	echo "✓ Released v$$NEW (CI/CD will publish to PyPI)"; \
	echo "→ Watch workflow: https://github.com/shared-goals/text-forge/actions"
