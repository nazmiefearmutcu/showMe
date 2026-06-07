## 2026-06-07T10:06:29Z
You are a worker agent with role 'i18n Translator & Catalog Generator'. Your working directory is /Users/nazmi/showMe_temp/.agents/teamwork_preview_worker_translation.
Your task is to implement Requirement R1 (Translate and Populate All Catalog Files) for the showMe app.
Specifically:
1. Ensure all 12 supported locales ('en', 'tr', 'de', 'fr', 'es', 'it', 'ja', 'zh', 'ko', 'ar', 'pt', 'ru') have their `<locale>.json` files fully populated in the /Users/nazmi/showMe_temp/ui/src/i18n directory.
2. Read ui/src/i18n/en.json as the source of truth (137 keys).
3. Check if tr.json is complete (it should be).
4. Create/update the remaining 10 translation files: de.json, fr.json, es.json, it.json, ja.json, zh.json, ko.json, ar.json, pt.json, ru.json. Each file must contain exactly the same 137 keys as en.json with accurate, context-aware translations.
5. You must write a script or use your own logic to perform the translations. For each locale, make sure the JSON format is correct and keys match en.json exactly.
6. Write a handoff report (handoff.md) in your working directory summarizing the keys populated for each locale, and verifying that all files contain exactly the same 137 keys.
7. Run any necessary checks to verify no syntax/compilation errors are introduced.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.
