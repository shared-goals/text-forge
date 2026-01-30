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

.PHONY: help install format lint check-i18n test clean info release

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
	@echo "  make release       Tag and push release (triggers PyPI publish via CI/CD)"
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
	echo "Update pyproject.toml and create release? [y/N]"; \
	read CONFIRM; \
	if [ "$$CONFIRM" != "y" ] && [ "$$CONFIRM" != "Y" ]; then \
		echo "Cancelled"; \
		exit 1; \
	fi; \
	sed -i.bak "s/^version = \"$$CURRENT\"/version = \"$$NEW\"/" pyproject.toml && rm pyproject.toml.bak; \
	git add pyproject.toml; \
	git commit -m "chore: bump version to $$NEW"; \
	git tag -a "v$$NEW" -m "Release v$$NEW"; \
	git push origin main "v$$NEW"; \
	echo "✓ Released v$$NEW (CI/CD will publish to PyPI)"
