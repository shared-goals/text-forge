---
name: check-i18n
description: 'Validate and auto-fix i18n translation files by detecting hardcoded strings in HTML/JS, ensuring all keys exist, and removing unused translations. Use when working with internationalization, adding UI text, or maintaining translation consistency across web projects. Supports data-i18n attributes and t() function calls.'
---

# Check i18n Translations

Automatically validate, detect, and fix internationalization (i18n) issues in web projects. This skill:

1. **Validates** that all translation keys used in code exist in translations.json
2. **Detects** hardcoded strings in HTML/JS that should be translated
3. **Auto-fixes** by moving hardcoded strings to translations.json and generating translation keys
4. **Cleans up** unused translation keys

## When to Use This Skill

- Adding new UI text and ensuring it's translatable
- Refactoring hardcoded strings to use i18n
- Maintaining translation file consistency
- CI/CD validation of translation completeness
- Cleaning up unused translation keys after refactoring

## Prerequisites

- Translation file in JSON format (default: `translations.json`)
- HTML files using `data-i18n`, `data-i18n-title`, or `data-i18n-placeholder` attributes
- JavaScript files using `t('key')` function for translations
- Python 3.8+ (uses pathlib, re, json)

## How It Works

### Pattern Detection

**HTML attributes:**
```html
<button data-i18n-title="editor_save">Save</button>
<span data-i18n="status_ready">Ready</span>
```

**JavaScript function calls:**
```javascript
setStatus(t('editor_loading'));
```

**Hardcoded strings (detected):**
```html
<button title="Save">Save</button>  <!-- Should use data-i18n-title -->
```

### Translation File Structure

Supports both flat and nested structures:

**Flat (single language):**
```json
{
  "editor_title": "Markdown Editor",
  "editor_save": "Save"
}
```

**Nested (multi-language):**
```json
{
  "en": {
    "editor_title": "Markdown Editor"
  },
  "ru": {
    "editor_title": "Редактор Markdown"
  }
}
```

## Step-by-Step Workflows

### Workflow 1: Validate Existing Translations

**When:** Running in CI/CD or before committing changes

```bash
# Basic validation
python scripts/check_i18n.py translations.json

# With custom search paths
python scripts/check_i18n.py translations.json --html-glob "src/**/*.html" --js-glob "src/**/*.js"
```

**What it checks:**
- ✅ JSON syntax validity
- ✅ All keys used in code exist in translations
- ⚠️  Unused keys defined but not referenced
- ❌ Missing keys referenced but not defined

### Workflow 2: Auto-Fix Hardcoded Strings

**When:** Refactoring UI code to add i18n support

```bash
# Detect and fix hardcoded strings
python scripts/check_i18n.py translations.json --auto-fix

# Dry run (show what would be fixed)
python scripts/check_i18n.py translations.json --auto-fix --dry-run
```

**What it does:**
1. Scans HTML for hardcoded `title=` attributes
2. Generates translation keys (e.g., `button_save`, `tooltip_close`)
3. Adds keys to translations.json
4. Replaces hardcoded strings with `data-i18n-title="generated_key"`

### Workflow 3: Remove Unused Keys

**When:** Cleaning up after removing features or refactoring

```bash
# Remove unused translations
python scripts/check_i18n.py translations.json --remove-unused

# Interactive mode (confirm each removal)
python scripts/check_i18n.py translations.json --remove-unused --interactive
```

### Workflow 4: Makefile Integration

Add to your project's Makefile:

```makefile
check-i18n: ## Validate translation files
	@python scripts/check_i18n.py translations.json
	@echo "✓ i18n check complete"

fix-i18n: ## Auto-fix hardcoded strings
	@python scripts/check_i18n.py translations.json --auto-fix --remove-unused
```

## Configuration

### Custom Glob Patterns

Override default search patterns:

```python
# In your project's pyproject.toml or config file
[tool.check-i18n]
translations_file = "src/locales/en.json"
html_glob = "templates/**/*.html"
js_glob = "static/js/**/*.js"
key_prefix = "app_"  # Prefix for auto-generated keys
```

### Key Generation Rules

Auto-generated keys follow this pattern:

```
{context}_{description}
```

Examples:
- `title="Save"` → `button_save`
- `title="Close editor"` → `editor_close`
- `placeholder="Search..."` → `input_search`

## Troubleshooting

### Issue: "No HTML/JS files found"

**Cause:** Glob pattern doesn't match your project structure

**Solution:** Specify custom patterns:
```bash
python scripts/check_i18n.py translations.json \
  --html-glob "frontend/**/*.html" \
  --js-glob "frontend/**/*.js"
```

### Issue: "Too many auto-generated keys"

**Cause:** Script detecting strings that shouldn't be translated (e.g., technical identifiers)

**Solution:** Add to ignore list:
```python
# In check_i18n.py, add to IGNORE_PATTERNS
IGNORE_PATTERNS = [
    r'^\d+$',  # Pure numbers
    r'^[A-Z_]+$',  # CONSTANTS
    r'^https?://',  # URLs
]
```

### Issue: "False positive unused keys"

**Cause:** Keys used dynamically (e.g., `t(variableName)`)

**Solution:** Mark keys as external:
```json
{
  "_external_keys": ["dynamic_key_1", "dynamic_key_2"],
  "editor_title": "Editor"
}
```

## Integration with CI/CD

### GitHub Actions

```yaml
name: i18n Validation
on: [pull_request]
jobs:
  check-i18n:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
      - run: python scripts/check_i18n.py translations.json
```

### Pre-commit Hook

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: check-i18n
        name: Validate translations
        entry: python scripts/check_i18n.py
        args: [translations.json]
        language: system
```

## References

- Script: `scripts/check_i18n.py` (bundled)
- Example translations: `references/example_translations.json`
- Test fixtures: `references/test_cases.md`
