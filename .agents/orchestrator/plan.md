# Plan - Language Catalogs Translation, Integration, and Verification

## Goal
Translate, register, integrate, and verify all 12 supported locales in the showMe app, ensuring exactly 138 keys in each catalog and strictly zero English fallback.

## Milestones

### Milestone 1: Exploration
- **Objective**: Discover the structure of `ui/src/i18n` and the format/content of `en.json`.
- **Method**: Spawn `teamwork_preview_explorer` to inspect files under `ui/src/i18n` and identify all files, keys, and `t()` function structure.
- **Verification**: Explorer handoff report with exact list of files and keys.

### Milestone 2: Translation & Catalog Generation (R1)
- **Objective**: Translate all 11 missing/incomplete catalogs to match `en.json` (138 keys).
- **Method**: Spawn `teamwork_preview_worker` to read `en.json` and generate/update the other `<locale>.json` files in `ui/src/i18n/`.
- **Verification**: Verify all files exist and contain 138 keys.

### Milestone 3: Register and Integrate Locales (R2, R3)
- **Objective**: Import and register the 12 catalogs in `ui/src/i18n/index.ts` and modify the `t()` function to remove the English fallback.
- **Method**: Spawn `teamwork_preview_worker` to make these code changes.
- **Verification**: Code compiles cleanly via `npm run build:ui`.

### Milestone 4: Verification (R4)
- **Objective**: Assert correctness, catalog completeness, and zero English fallback behavior through existing and new unit tests.
- **Method**: Spawn `teamwork_preview_challenger` and `teamwork_preview_auditor` to verify functionality.
- **Verification**: Run `npm test` or the appropriate test runner, and verify 100% test pass.
