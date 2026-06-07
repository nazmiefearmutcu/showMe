# i18n catalogs

This directory contains the localization catalogs and helper modules for the application.

All 12 supported locales are fully populated with 100% key parity:
`en`, `tr`, `de`, `fr`, `es`, `it`, `ja`, `zh`, `ko`, `ar`, `pt`, `ru`

## 🔒 Crucial Rules & Architecture

1. **Strict Key Parity**: Every catalog (`<locale>.json`) must contain exactly the same set of keys as the English source of truth (`en.json`).
2. **Zero English Fallback**: At runtime, `t()` does **NOT** fall back to English if a key is missing in the active locale. A missing key will immediately return the caller-supplied default/fallback or the key name itself to prevent language mixing.
3. **Arabic Direction**: Arabic (`ar`) automatically configures `<html dir="rtl">` for Right-to-Left layout.

## 🛠️ Adding or Updating Keys

When you add, edit, or delete a translation key:

1. Update the key in **all 12 JSON files** (`en.json`, `tr.json`, `de.json`, `fr.json`, `es.json`, `it.json`, `ja.json`, `zh.json`, `ko.json`, `ar.json`, `pt.json`, `ru.json`).
2. Do **not** leave any key missing in any catalog, as it will print the raw key name to the user instead of falling back to English.
3. Verify your changes by running the unit tests:
   ```bash
   npx vitest run src/i18n/
   ```
   This suite automatically asserts 100% key parity and correct fallback behavior across all registered locales.

## Key naming

`<scope>.<sub-scope>.<purpose>` — e.g. `preferences.appearance.theme`, `shell.palette.placeholder`. Keep keys stable.
