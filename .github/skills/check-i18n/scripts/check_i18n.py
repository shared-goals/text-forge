#!/usr/bin/env python3
"""
Check i18n translation files for consistency with auto-fix capabilities.

Features:
- Validate translation keys against actual usage in HTML/JS
- Detect hardcoded strings that should be translated
- Auto-fix by generating translation keys and updating files
- Remove unused translation keys
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


def find_translation_keys_in_files(
    base_path: Path,
    html_glob: str = "**/*.html",
    js_glob: str = "**/*.js",
    key_pattern: str = r"\w+",
) -> Set[str]:
    """Find all translation keys used in HTML and JS files."""
    keys = set()

    # Check HTML files for data-i18n* attributes
    html_files = list(base_path.glob(html_glob))
    for html_file in html_files:
        content = html_file.read_text(encoding="utf-8")
        # Match data-i18n="key", data-i18n-title="key", data-i18n-placeholder="key"
        matches = re.findall(r'data-i18n(?:-\w+)?="([^"]+)"', content)
        keys.update(matches)

    # Check JS files for t('key') calls
    js_files = list(base_path.glob(js_glob))
    for js_file in js_files:
        content = js_file.read_text(encoding="utf-8")
        # Match t('key') or t("key") - filter by pattern
        matches = re.findall(rf"t\(['\"]({key_pattern})['\"]\)", content)
        keys.update(matches)

    return keys


def find_hardcoded_strings(
    base_path: Path, html_glob: str = "**/*.html"
) -> List[Tuple[Path, int, str, str]]:
    """
    Find hardcoded strings that should use i18n.

    Returns list of (file_path, line_number, attribute_name, hardcoded_text)
    """
    findings = []
    html_files = list(base_path.glob(html_glob))

    for html_file in html_files:
        lines = html_file.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines, 1):
            # Find title="text" not followed by data-i18n-title
            if 'title="' in line and "data-i18n-title" not in line:
                match = re.search(r'title="([^"]+)"', line)
                if match:
                    findings.append((html_file, i, "title", match.group(1)))

            # Find placeholder="text" not followed by data-i18n-placeholder
            if 'placeholder="' in line and "data-i18n-placeholder" not in line:
                match = re.search(r'placeholder="([^"]+)"', line)
                if match:
                    findings.append((html_file, i, "placeholder", match.group(1)))

    return findings


def generate_translation_key(text: str, prefix: str = "") -> str:
    """Generate a translation key from text."""
    # Normalize: lowercase, remove special chars, replace spaces with underscores
    key = re.sub(r"[^\w\s]", "", text.lower())
    key = re.sub(r"\s+", "_", key.strip())
    key = re.sub(r"_+", "_", key)  # Collapse multiple underscores

    if prefix:
        key = f"{prefix}_{key}"

    return key[:64]  # Limit length


def auto_fix_hardcoded_strings(
    findings: List[Tuple[Path, int, str, str]],
    translations: Dict[str, str],
    prefix: str = "auto",
    dry_run: bool = False,
) -> Dict[str, str]:
    """
    Auto-fix hardcoded strings by:
    1. Generating translation keys
    2. Adding to translations dict
    3. Updating HTML files with data-i18n-* attributes

    Returns updated translations dict.
    """
    updated_translations = translations.copy()
    files_to_update = {}

    for file_path, line_num, attr_name, text in findings:
        # Generate key
        key = generate_translation_key(text, prefix)

        # Ensure unique key
        original_key = key
        counter = 1
        while key in updated_translations:
            key = f"{original_key}_{counter}"
            counter += 1

        # Add to translations
        updated_translations[key] = text
        print(f"  + {key}: {text}")

        # Track file update
        if file_path not in files_to_update:
            files_to_update[file_path] = []
        files_to_update[file_path].append((line_num, attr_name, key))

    # Update files
    if not dry_run and files_to_update:
        for file_path, updates in files_to_update.items():
            content = file_path.read_text(encoding="utf-8")
            lines = content.splitlines()

            # Sort updates by line number (reverse to preserve line numbers)
            for line_num, attr_name, key in sorted(updates, reverse=True):
                line = lines[line_num - 1]
                # Add data-i18n-* attribute after the original attribute
                attr_pattern = f'{attr_name}="[^"]*"'
                replacement = f'\\g<0> data-i18n-{attr_name}="{key}"'
                lines[line_num - 1] = re.sub(attr_pattern, replacement, line)

            file_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print(f"✓ Updated {file_path}")

    return updated_translations


def check_translations(
    filepath: str,
    base_path: Path = None,
    html_glob: str = "**/*.html",
    js_glob: str = "**/*.js",
    key_pattern: str = r"\w+",
    auto_fix: bool = False,
    remove_unused: bool = False,
    dry_run: bool = False,
    key_prefix: str = "auto",
) -> bool:
    """Check translation file for consistency with optional auto-fix."""
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

    # Detect structure type
    first_value = next(iter(data.values()), None)

    if isinstance(first_value, dict):
        # Multi-language structure
        print("⚠️  Multi-language structure detected. Auto-fix not supported.")
        return check_multilang(data)

    # Single-language flat structure
    print(f"✅ Translation file is valid with {len(data)} keys")

    if not base_path:
        return True

    # Find keys used in code
    used_keys = find_translation_keys_in_files(
        base_path, html_glob, js_glob, key_pattern
    )
    defined_keys = set(data.keys())

    # Check for missing keys
    missing = used_keys - defined_keys
    if missing:
        print(f"❌ Missing translations for keys used in code: {sorted(missing)}")
        return False

    # Check for unused keys
    unused = defined_keys - used_keys
    if unused:
        print(f"⚠️  Unused translation keys: {sorted(unused)}")

        if remove_unused:
            if not dry_run:
                for key in unused:
                    del data[key]
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                    f.write("\n")
                print(f"✓ Removed {len(unused)} unused keys")
            else:
                print(f"[DRY RUN] Would remove {len(unused)} unused keys")

    # Auto-fix hardcoded strings
    if auto_fix:
        print("\n==> Detecting hardcoded strings...")
        findings = find_hardcoded_strings(base_path, html_glob)

        if findings:
            print(f"Found {len(findings)} hardcoded strings:")
            for file_path, line_num, attr, text in findings:
                print(f'  {file_path}:{line_num} {attr}="{text}"')

            if not dry_run:
                print("\n==> Generating translation keys...")
                updated_data = auto_fix_hardcoded_strings(
                    findings, data, key_prefix, dry_run
                )

                # Write updated translations
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(updated_data, f, indent=2, ensure_ascii=False)
                    f.write("\n")
                print(f"✓ Added {len(findings)} translation keys")
            else:
                print("[DRY RUN] Would add translation keys and update files")
        else:
            print("✓ No hardcoded strings found")

    return True


def check_multilang(data: Dict) -> bool:
    """Check multi-language translation structure."""
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


def main():
    parser = argparse.ArgumentParser(description="Check i18n translation files")
    parser.add_argument("translations_file", help="Path to translations JSON file")
    parser.add_argument(
        "--base-path", help="Base path for searching files (default: script parent dir)"
    )
    parser.add_argument(
        "--html-glob", default="**/*.html", help="Glob pattern for HTML files"
    )
    parser.add_argument(
        "--js-glob", default="**/*.js", help="Glob pattern for JS files"
    )
    parser.add_argument(
        "--key-pattern", default=r"\w+", help="Regex pattern for translation keys"
    )
    parser.add_argument(
        "--auto-fix", action="store_true", help="Auto-fix hardcoded strings"
    )
    parser.add_argument(
        "--remove-unused", action="store_true", help="Remove unused translation keys"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without modifying files",
    )
    parser.add_argument(
        "--key-prefix", default="auto", help="Prefix for auto-generated keys"
    )

    args = parser.parse_args()

    # Determine base path
    if args.base_path:
        base_path = Path(args.base_path).resolve()
    else:
        # Default: assume script is in .github/skills/*/scripts/, go up to project root
        script_dir = Path(__file__).parent.resolve()
        base_path = (
            script_dir.parent.parent.parent.parent
        )  # Go up 4 levels to project root

    success = check_translations(
        args.translations_file,
        base_path,
        args.html_glob,
        args.js_glob,
        args.key_pattern,
        args.auto_fix,
        args.remove_unused,
        args.dry_run,
        args.key_prefix,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
