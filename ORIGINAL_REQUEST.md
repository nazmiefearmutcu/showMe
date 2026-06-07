# Original User Request

## Initial Request — 2026-06-07T12:45:06+03:00

Update all supported language catalogs (en, tr, de, fr, es, it, ja, zh, ko, ar, pt, ru) in the showMe desktop app to match the current 138-key English catalog exactly, and ensure that selecting a language does not mix with any other languages (strictly zero English fallback).

Working directory: /Users/nazmi/showMe_temp
Integrity mode: development

## Requirements

### R1. Translate and Populate All Catalog Files
All 12 supported locales must have their `<locale>.json` files fully populated in the `ui/src/i18n` directory. Each file must contain exactly the same 138 keys as `en.json` (as of the current application state) with accurate, context-aware translations. 
*Note: The translation agent team should use LLM models (e.g. Gemini) to translate keys based on the context of the English values.*

### R2. Register and Integrate Locales
All 12 translation files must be imported and registered in `ui/src/i18n/index.ts` within the `CATALOGS` record. Selecting a language in the preferences must correctly switch the application language.

### R3. Remove Runtime Fallback to English
To ensure other languages never mix when a language is selected, modify the translation function `t()` in `ui/src/i18n/index.ts` so that it does not fall back to English when a key is missing in the active locale catalog. Instead, it should immediately fall back to the caller-supplied default or the key name itself.

### R4. Verify Integration and UI Completeness
Ensure that all UI unit tests pass and add validation tests verifying that all supported catalogs are 100% complete, free of missing keys, and that no runtime language mixing can occur.

## Acceptance Criteria

### Translation Completeness
- [ ] Every catalog file (`de.json`, `fr.json`, `es.json`, `it.json`, `ja.json`, `zh.json`, `ko.json`, `ar.json`, `pt.json`, `ru.json`, `tr.json`, `en.json`) exists in `ui/src/i18n/`.
- [ ] Every JSON file contains exactly the same set of keys as `en.json` (138 keys).
- [ ] No key contains untranslated English placeholders or untranslated values, guaranteeing that when any language is selected, it does not mix with other languages.

### Code Integration
- [ ] `ui/src/i18n/index.ts` is updated to import and register all 12 catalogs in `CATALOGS`.
- [ ] The translation function `t()` does not fall back to English if the active locale has a catalog.
- [ ] Compilation builds (`npm run build:ui`) complete successfully without any TypeScript or bundling errors.

### Testing
- [ ] All existing and new i18n tests pass successfully.
- [ ] Test cases in `ui/src/i18n/i18n.test.ts` and `ui/src/i18n/i18n-extra.test.ts` are updated to assert the new fallback behavior (i.e. not falling back to English when a catalog exists).
