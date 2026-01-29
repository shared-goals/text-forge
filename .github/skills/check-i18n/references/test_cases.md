# Test Cases for check-i18n

## Test Case 1: Detect Missing Keys

**Input HTML:**
```html
<button data-i18n-title="editor_save">Save</button>
```

**Input translations.json:**
```json
{
  "editor_title": "Editor"
}
```

**Expected Output:**
```
❌ Missing translations for keys used in code: ['editor_save']
```

## Test Case 2: Detect Hardcoded Strings

**Input HTML:**
```html
<button title="Save Changes">Save</button>
```

**Expected Output:**
```
Found 1 hardcoded strings:
  file.html:1 title="Save Changes"
```

**After --auto-fix:**
```html
<button title="Save Changes" data-i18n-title="auto_save_changes">Save</button>
```

```json
{
  "auto_save_changes": "Save Changes"
}
```

## Test Case 3: Remove Unused Keys

**Input translations.json:**
```json
{
  "editor_save": "Save",
  "unused_key": "Never used"
}
```

**Expected Output:**
```
⚠️  Unused translation keys: ['unused_key']
```

**After --remove-unused:**
```json
{
  "editor_save": "Save"
}
```

## Test Case 4: Multi-language Consistency

**Input:**
```json
{
  "en": {
    "editor_save": "Save",
    "editor_close": "Close"
  },
  "ru": {
    "editor_save": "Сохранить"
  }
}
```

**Expected Output:**
```
❌ ru: missing keys: ['editor_close']
```
