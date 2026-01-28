#!/usr/bin/env python3
"""Check i18n translation files for consistency."""

import json
import sys
from pathlib import Path


def check_translations(filepath: str) -> bool:
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
        return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: check_i18n.py <translations_file>")
        sys.exit(1)
    
    success = check_translations(sys.argv[1])
    sys.exit(0 if success else 1)
