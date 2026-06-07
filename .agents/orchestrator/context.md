# Context - Language Catalogs Translation, Integration, and Verification

## Objective
The task is to translate and integrate 12 language catalogs for the `showMe` desktop app, specifically: `en`, `tr`, `de`, `fr`, `es`, `it`, `ja`, `zh`, `ko`, `ar`, `pt`, `ru`.
Currently, the English (`en`) catalog is considered the source of truth, containing exactly 138 keys.
We need to:
1. Translate all keys for the other 11 catalogs.
2. Register them in `ui/src/i18n/index.ts`.
3. Modify the `t()` function in `ui/src/i18n/index.ts` so it does not fallback to English.
4. Verify all tests pass, and write validation tests asserting completeness and zero English fallback.

## Current Knowledge
- Original user request is stored in /Users/nazmi/showMe_temp/.agents/ORIGINAL_REQUEST.md.
- The workspace path is /Users/nazmi/showMe_temp.
- The command allowlist is: `git`, `python3`, `pip`, `pytest`, `make`, `npm`, `node`, `cargo`, `go`, `ruff`, `mypy`, `tsc`, `jq`.
- Integrity mode is `development`.
- Target files/directories: `ui/src/i18n`.
