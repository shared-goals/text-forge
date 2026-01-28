#!/usr/bin/env python3
"""Check i18n translation files for consistency."""

import json
import re
import sys
from pathlib import Path


def find_translation_keys_in_files(base_path: Path) -> set:
    """Find all data-i18n* attribute values used in HTML and JS files."""
    keys = set()
    
    # Check HTML files
    html_files = list(base_path.glob('mkdocs/overrides/**/*.html'))
    for html_file in html_files:
        content = html_file.read_text(encoding='utf-8')
        # Match data-i18n="key", data-i18n-title="key", data-i18n-placeholder="key"
        matches = re.findall(r'data-i18n(?:-\w+)?="([^"]+)"', content)
        keys.update(matches)
    
    # Check JS files for t('key') calls
    js_files = list(base_path.glob('mkdocs/overrides/**/*.js'))
    for js_file in js_files:
        content = js_file.read_text(encoding='utf-8')
        # Match t('editor_*') or t("editor_*") - only keys starting with editor_
        matches = re.findall(r"t\(['\"]+(editor_[^'\"]+)['\"]+\)", content)
        keys.update(matches)
    
    return keys


def check_translations(filepath: str, base_path: Path = None) -> bool:
    """Check translation file for consistency across languages."""
    path = Path(filepath)
    
    if not path.exists():
        print(f"⚠️  No translations file found at {filepath}")
        return True
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ Invalid JSON: {e}")
        return False
    except Exception as e:
        print(f"❌ Error reading file: {e}")
        return False
    
    if not isinstance(data, dict):
        print("❌ Root must be an object")
        return False
    
    # Check if this is a multi-language structure (lang -> translations)
    # or a single-language flat structure (key -> value)
    first_value = next(iter(data.values()), None)
    
    if isinstance(first_value, dict):
        # Multi-language structure: {"en": {...}, "ru": {...}}
        keys_per_lang = {}
        for lang, translations in data.items():
            if not isinstance(translations, dict):
                print(f"❌ {lang}: must be an object")
                return False
            keys_per_lang[lang] = set(translations.keys())
        
        if not keys_per_lang:
            print("⚠️  No languages found")
            return True
        
        reference_lang = list(keys_per_lang.keys())[0]
        reference_keys = keys_per_lang[reference_lang]
        
        all_ok = True
        for lang, keys in keys_per_lang.items():
            if lang == reference_lang:
                continue
            
            missing = reference_keys - keys
            extra = keys - reference_keys
            
            if missing:
                print(f"❌ {lang}: missing keys: {sorted(missing)}")
                all_ok = False
            
            if extra:
                print(f"⚠️  {lang}: extra keys: {sorted(extra)}")
        
        if all_ok:
            print(f"✅ All {len(keys_per_lang)} languages have consistent keys")
        
        return all_ok
    else:
        # Single-language flat structure: {"key": "value"}
        print(f"✅ Translation file is valid with {len(data)} keys")
        
        # Check if all keys used in templates/JS exist in translations
        if base_path:
            used_keys = find_translation_keys_in_files(base_path)
            defined_keys = set(data.keys())
            
            missing = used_keys - defined_keys
            unused = defined_keys - used_keys
            
            if missing:
                print(f"❌ Missing translations for keys used in code: {sorted(missing)}")
                return False
            
            if unused:
                print(f"⚠️  Unused translation keys (defined but not used): {sorted(unused)}")
        
        return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: check_i18n.py <translations_file>")
        sys.exit(1)
    
    filepath = sys.argv[1]
    # Get absolute project root
    script_dir = Path(__file__).parent.resolve()
    base_path = script_dir.parent  # Go up from scripts/ to project root
    
    success = check_translations(filepath, base_path)
    sys.exit(0 if success else 1)
