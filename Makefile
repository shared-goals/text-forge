# text-forge Makefile
#
# This Makefile is intended to be called from a content repository via:
#   make -C text-forge CONTENT_ROOT=$PWD <target>
#
# The content repo should provide:
# - mkdocs.yml
# - docs tree (e.g. text/ru)
#
# Default layout matches bongiozzo/whattodo.

TEXT_FORGE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
CONTENT_ROOT ?= $(abspath $(TEXT_FORGE_DIR)/..)

# Tooling runs from THIS project (text-forge)
UV := uv --project $(TEXT_FORGE_DIR)
UV_RUN := $(UV) run
PYTHON := $(UV_RUN) python
MKDOCS := $(UV_RUN) mkdocs
PANDOC := pandoc

# By default, disable git-committers to avoid token/rate-limit warnings
# (MkDocs `--strict` treats warnings as errors).
# Opt-in by running e.g.:
#   MKDOCS_GIT_COMMITTERS_ENABLED=true make site
MKDOCS_GIT_COMMITTERS_ENABLED ?= false

# Content repo layout (override in caller if needed)
MKDOCS_CONFIG ?= $(CONTENT_ROOT)/mkdocs.yml
DOCS_DIR ?= $(CONTENT_ROOT)/text/ru
PUBLIC_DIR ?= $(CONTENT_ROOT)/public
SITE_DIR ?= $(PUBLIC_DIR)/ru
BUILD_DIR ?= $(CONTENT_ROOT)/build

# Pipeline sources (in text-forge)
SCRIPTS_DIR := $(TEXT_FORGE_DIR)/scripts
EPUB_DIR := $(TEXT_FORGE_DIR)/epub

COMBINE_SCRIPT := $(SCRIPTS_DIR)/mkdocs-combine.py
LUA_FILTER := $(SCRIPTS_DIR)/pymdown-pandoc.lua
BOOK_META := $(EPUB_DIR)/book_meta.yml
CSS_FILE := $(EPUB_DIR)/epub.css

# Optional MkDocs extra.css (copied into docs_dir only if missing)
EXTRA_CSS_SRC := $(TEXT_FORGE_DIR)/mkdocs/assets/css/extra.css
EXTRA_CSS_DST := $(DOCS_DIR)/assets/css/extra.css

# Content assets
COVER_IMAGE ?= $(DOCS_DIR)/img/cover.jpg

# Outputs
COMBINED_MD := $(BUILD_DIR)/text_combined.txt
PANDOC_MD := $(BUILD_DIR)/pandoc.md
EPUB_OUT := $(BUILD_DIR)/text_book.epub
BOOK_META_PROCESSED := $(BUILD_DIR)/book_meta_processed.yml

.PHONY: all epub site serve test clean help info install ensure_extra_css format lint check-i18n

help:
	@echo "text-forge pipeline (called from content repo)"
	@echo ""
	@echo "Usage:"
	@echo "  make -C text-forge CONTENT_ROOT=$$PWD <target>"
	@echo ""
	@echo "Targets:"
	@echo "  make install       Sync Python deps (uv sync)"
	@echo "  make serve         Run MkDocs dev server (fast, no EPUB)"
	@echo "  make epub          Build EPUB only"
	@echo "  make site          Build MkDocs site + copy artifacts"
	@echo "  make all           Build EPUB + MkDocs site (default)"
	@echo "  make test          Run validation tests"
	@echo "  make format        Format Python code with ruff"
	@echo "  make lint          Run lint checks via ruff"
	@echo "  make check-i18n    Check translation files for consistency"
	@echo "  make clean         Remove build artifacts in content repo"
	@echo "  make info          Print resolved paths"

install:
	@echo "==> Syncing dependencies via uv sync (project: $(TEXT_FORGE_DIR))..."
	@$(UV) sync

# Fast preview — the content repo can disable git-committers via env var.

ensure_extra_css:
	@mkdir -p $(DOCS_DIR)/assets/css
	@if [ ! -f "$(EXTRA_CSS_DST)" ] && [ -f "$(EXTRA_CSS_SRC)" ]; then \
		cp "$(EXTRA_CSS_SRC)" "$(EXTRA_CSS_DST)"; \
		echo "✓ extra.css staged to $(EXTRA_CSS_DST)"; \
	fi

serve: ensure_extra_css
	cd $(CONTENT_ROOT) && MKDOCS_GIT_COMMITTERS_ENABLED=$(MKDOCS_GIT_COMMITTERS_ENABLED) $(MKDOCS) serve --config-file=$(MKDOCS_CONFIG)

epub: $(EPUB_OUT)

$(COMBINED_MD): $(MKDOCS_CONFIG) $(COMBINE_SCRIPT)
	@echo "==> Stage 1: Combining markdown files from mkdocs.yml..."
	@mkdir -p $(BUILD_DIR)
	@$(PYTHON) $(COMBINE_SCRIPT) $(MKDOCS_CONFIG) > $@
	@echo "✓ Combined markdown: $@"

$(PANDOC_MD): $(COMBINED_MD) $(LUA_FILTER)
	@echo "==> Stage 2: Converting PyMdown syntax to Pandoc markdown..."
	$(PANDOC) -f markdown+smart $(COMBINED_MD) \
		--lua-filter=$(LUA_FILTER) \
		--wrap=preserve \
		-t markdown \
		-o $@
	@echo "✓ Pandoc markdown: $@"

$(BOOK_META_PROCESSED): $(BOOK_META)
	@echo "==> Processing book metadata..."
	@mkdir -p $(BUILD_DIR)
	@GIT_TAG=$$(git -C $(CONTENT_ROOT) describe --tags --abbrev=0 2>/dev/null || echo "v0.1.0"); \
	GIT_DATE=$$(git -C $(CONTENT_ROOT) log -1 --format=%cs 2>/dev/null || true); \
	if [ -z "$$GIT_DATE" ]; then GIT_DATE=$$(date -u +%Y-%m-%d); fi; \
	GIT_DATE_DISPLAY=$$(echo "$$GIT_DATE" | $(PYTHON) -c "import sys, datetime; d = datetime.datetime.strptime(sys.stdin.read().strip(), '%Y-%m-%d'); print(d.strftime('%d %B %Y').replace('January', 'января').replace('February', 'февраля').replace('March', 'марта').replace('April', 'апреля').replace('May', 'мая').replace('June', 'июня').replace('July', 'июля').replace('August', 'августа').replace('September', 'сентября').replace('October', 'октября').replace('November', 'ноября').replace('December', 'декабря'))"); \
	EDITION="$$GIT_TAG, $$GIT_DATE_DISPLAY"; \
	$(PYTHON) $(SCRIPTS_DIR)/process-epub-meta.py \
		--mkdocs-config "$(MKDOCS_CONFIG)" \
		--template "$(BOOK_META)" \
		--out "$@" \
		--edition "$$EDITION" \
		--date "$$GIT_DATE"
	@echo "✓ Metadata processed: $@"

$(EPUB_OUT): $(PANDOC_MD) $(BOOK_META_PROCESSED) $(CSS_FILE)
	@echo "==> Stage 3: Generating EPUB..."
	@mkdir -p $(BUILD_DIR)
	@if [ -f "$(COVER_IMAGE)" ]; then \
		COVER_OPT="--epub-cover-image=$(COVER_IMAGE)"; \
	else \
		COVER_OPT=""; \
		echo "WARNING: cover image not found: $(COVER_IMAGE)"; \
	fi; \
	$(PANDOC) -f markdown+smart $(PANDOC_MD) \
		-o $@ \
		--standalone \
		--toc \
		--toc-depth=2 \
		--metadata-file=$(BOOK_META_PROCESSED) \
		--resource-path=$(DOCS_DIR) \
		--css=$(CSS_FILE) \
		$$COVER_OPT \
		-t epub3
	@echo "✓ EPUB generated: $@"

site: epub ensure_extra_css
	@echo "==> Copying artifacts for MkDocs..."
	@mkdir -p $(DOCS_DIR)/assets
	cp $(EPUB_OUT) $(DOCS_DIR)/assets/
	cp $(COMBINED_MD) $(DOCS_DIR)/assets/
	@echo "✓ Artifacts copied to $(DOCS_DIR)/assets"
	@echo "==> Building MkDocs site..."
	cd $(CONTENT_ROOT) && MKDOCS_GIT_COMMITTERS_ENABLED=$(MKDOCS_GIT_COMMITTERS_ENABLED) $(MKDOCS) build --config-file=$(MKDOCS_CONFIG) --site-dir=$(SITE_DIR) --strict
	@echo "✓ MkDocs site built: $(SITE_DIR)"
	@echo "==> Creating redirect from / to /ru/..."
	@mkdir -p $(PUBLIC_DIR)
	@echo '<!DOCTYPE html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=/ru/"><link rel="canonical" href="/ru/"><title>Redirecting to /ru/...</title></head><body><p>Redirecting to <a href="/ru/">/ru/</a>...</p><script>window.location.href="/ru/";</script></body></html>' > $(PUBLIC_DIR)/index.html
	@echo "✓ Redirect created: $(PUBLIC_DIR)/index.html"

all: epub site

format: ## Format Python code with ruff
	@echo "==> Formatting Python code with ruff..."
	@$(UV_RUN) ruff check --select I --fix $(TEXT_FORGE_DIR)
	@$(UV_RUN) ruff format $(TEXT_FORGE_DIR)
	@echo "✓ Code formatted"

lint: ## Run lint checks via ruff
	@echo "==> Running lint checks..."
	@$(UV_RUN) ruff check $(TEXT_FORGE_DIR)
	@echo "✓ Lint checks complete"

check-i18n: ## Check translation files for consistency
	@echo "==> Checking i18n translation files..."
	@TRANSLATIONS_FILE="$(TEXT_FORGE_DIR)/mkdocs/overrides/assets/js/translations.json"; \
	echo "Checking $$TRANSLATIONS_FILE..."; \
	$(PYTHON) $(SCRIPTS_DIR)/check_i18n.py "$$TRANSLATIONS_FILE"
	@echo "✓ i18n check complete"

test: $(EPUB_OUT)
	@echo "==> Unzipping EPUB for tests..."
	@rm -rf $(BUILD_DIR)/epub
	@unzip -q $(EPUB_OUT) -d $(BUILD_DIR)/epub
	@echo "==> Running tests..."
	@COMBINED_MD=$(CONTENT_ROOT)/$(patsubst $(CONTENT_ROOT)/%,%,$(COMBINED_MD)) \
	 PANDOC_MD=$(CONTENT_ROOT)/$(patsubst $(CONTENT_ROOT)/%,%,$(PANDOC_MD)) \
	 EPUB_DIR=$(BUILD_DIR)/epub \
	 $(PYTHON) -m pytest $(SCRIPTS_DIR)/tests.py -v
	@echo "✓ Tests passed"

clean:
	@echo "==> Cleaning build artifacts (content repo)..."
	rm -rf $(BUILD_DIR) $(SITE_DIR)
	rm -rf $(CONTENT_ROOT)/.pytest_cache $(CONTENT_ROOT)/.cache $(CONTENT_ROOT)/**/__pycache__
	rm -f $(PUBLIC_DIR)/index.html
	@echo "✓ Cleaned"

info:
	@echo "Resolved paths:"
	@echo "  TEXT_FORGE_DIR: $(TEXT_FORGE_DIR)"
	@echo "  CONTENT_ROOT:  $(CONTENT_ROOT)"
	@echo "  MKDOCS_CONFIG: $(MKDOCS_CONFIG)"
	@echo "  DOCS_DIR:      $(DOCS_DIR)"
	@echo "  BUILD_DIR:     $(BUILD_DIR)"
	@echo "  SITE_DIR:      $(SITE_DIR)"
	@echo "  SCRIPTS_DIR:   $(SCRIPTS_DIR)"
	@echo "  EPUB_DIR:      $(EPUB_DIR)"
