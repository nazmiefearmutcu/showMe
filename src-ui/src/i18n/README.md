# i18n catalogs

Round 13 ships **English (`en.json`)** and **Turkish (`tr.json`)** as
authoritative catalogs. The other 10 locales targeted in Rapor 1 §17.4
(`de fr es it ja zh ko ar pt ru`) fall back to English at runtime via
`t()`.

To add a locale:

1. Drop a `<locale>.json` file mirroring the shape of `en.json`.
2. Import + register it in `i18n/index.ts → CATALOGS`.
3. Confirm `setLocale("xx")` flips `<html lang="xx" dir="…">`.

Translator workflow lives in `docs/round_notes/<round>.md` once we hire
contractors (Round 24+).

## Key naming

`<scope>.<sub-scope>.<purpose>` — e.g. `preferences.appearance.theme`,
`shell.palette.placeholder`. Keep keys stable; missing keys fall back to
English, then to `<key>` itself, so mis-typing is loud.
