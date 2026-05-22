# Indicator depot (Sub-system F) Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** Catalog framework + 15 hand-curated indicators + route + INDX pane.

**Architecture:** Spec at `docs/superpowers/specs/2026-05-22-indicator-depot-design.md`. Mirrors A's catalog pattern but for indicators (metadata only — no computation).

**Tech Stack:** Python 3.11+, FastAPI; React + TS + zustand.

---

## Tasks

### Task F1: Catalog YAML + loader + tests

**Files:**
- Create: `backend/showme/indicators/__init__.py` (empty)
- Create: `backend/showme/indicators/catalog/__init__.py` (empty)
- Create: `backend/showme/indicators/catalog/loader.py`
- Create: `backend/showme/indicators/catalog/indicators.yml`
- Create: `backend/tests/test_indicator_catalog.py`

Refer to the spec for the YAML schema. The 15 entries land hand-curated in `indicators.yml`. Loader mirrors `brokers/catalog/loader.py`:

- `IndicatorParam(name, type, default, min, max, effect)` frozen dataclass with `to_dict()`.
- `IndicatorEntry(id, display_name, family, short_description, long_description, formula, parameters: tuple[IndicatorParam, ...], confidence, confidence_rationale, suggested_strategy: dict, references: tuple[str, ...])` frozen with `to_dict()` + `matches_query(q) -> bool`.
- `IndicatorCatalog(entries: tuple[IndicatorEntry, ...])` with `by_id`, `search`, `filter(family=)`, `to_payload`.
- `class IndicatorCatalogError(RuntimeError)`.
- `load_indicator_catalog(path) -> IndicatorCatalog`.

Tests: parse all 15 entries; by_id; search; filter by family; missing required field raises; confidence range validated 1-10.

### Task F2: /api/indicators/* route

**Files:**
- Create: `backend/showme/server_routes/indicators.py`
- Modify: `backend/showme/server_routes/__init__.py`
- Create: `backend/tests/test_indicators_route.py`

Routes:
- `GET /api/indicators/catalog` → list of entry dicts
- `GET /api/indicators/{id}` → single entry dict or 404

Boot-time singleton: load catalog once via `_INDICATOR_CATALOG = load_indicator_catalog(_default_path())` in the route module.

### Task F3: UI indicator-store

**Files:**
- Create: `ui/src/lib/indicator-store.ts`
- Create: `ui/src/lib/indicator-store.test.ts`

zustand: `entries`, `loading`, `error`, `selectedId`. Actions: `loadCatalog()`, `setSelected(id)`, `byId(id)`, `search(q)`. Use `sidecarFetch`.

### Task F4: INDX pane + registry wiring

**Files:**
- Create: `ui/src/functions/INDX.tsx`
- Create: `ui/src/functions/INDX.test.tsx`
- Modify: `ui/src/functions/registry.tsx` (add lazy + PANES entry + NATIVE_FUNCTION_ENTRIES + bump invariant 148→149)
- Modify: `ui/src/functions/registry.test.tsx` (bump expected count)
- Modify: `ui/src/shell/Sidebar.tsx` (add to existing Tools or new Strategy group)

Left grid: cards w/ display_name + family chip + confidence chip. Color: `confidence >= 9` accent-ok, `>= 7` light variant, `>= 5` warn, `>= 3` orange, else err. Right: detail view (description, parameters table, formula, rationale, suggested strategy block).

### Task F5: Native rebuild + close-out

Full test pass; sidecar+tauri build (verify `indicators.yml` bundled — same package-data pattern A used); deploy; live curl `/api/indicators/catalog` shows 15 entries; screenshot; memory note `showme_subsystem_f.md`; `backend/SUBSYSTEM_F.md`.
