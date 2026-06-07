# Project: Language Catalogs Translation, Integration, and Verification

## Architecture
- Codebase structure for internationalization is under `ui/src/i18n/`.
- Locales are defined in `<locale>.json` files under `ui/src/i18n/`.
- Integration and registration is done in `ui/src/i18n/index.ts`.
- The `t()` function is used for key lookups.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Exploration | Inspect `ui/src/i18n` structure and files | None | DONE |
| 2 | Translation | Generate and translate 11 locale catalogs | 1 | IN_PROGRESS |
| 3 | Registration & Integration | Update `index.ts` to register catalogs and modify `t()` to remove fallback | 2 | PLANNED |
| 4 | Verification | Run tests and add validation tests | 3 | PLANNED |

## Interface Contracts
### ui/src/i18n/index.ts ↔ ui/src/i18n/<locale>.json
- All `<locale>.json` files must match `en.json` keys exactly (138 keys).
- The `t(key, defaultValue)` function in `index.ts` must return the translation if found, otherwise `defaultValue || key`. It must NOT fallback to English.
