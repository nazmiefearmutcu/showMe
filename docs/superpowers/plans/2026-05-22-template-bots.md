# Template bot library (Sub-system G) Implementation Plan

> REQUIRED SUB-SKILL: superpowers:subagent-driven-development.

**Goal:** 12 curated template strategies, route to list/get/instantiate, TMPL pane to browse and instantiate.

**Architecture:** Spec at `docs/superpowers/specs/2026-05-22-template-bots-design.md`. Mirrors F's catalog pattern.

---

## Tasks

### Task G1: Catalog YAML + loader + 12 templates + tests

**Files:**
- `backend/showme/templates/__init__.py` (empty)
- `backend/showme/templates/catalog/__init__.py` (empty)
- `backend/showme/templates/loader.py`
- `backend/showme/templates/catalog/templates.yml` (12 entries)
- `backend/tests/test_template_catalog.py`

Loader mirrors `brokers/catalog/loader.py`:
- `TemplateEntry(id, name, description, uses_indicators, recommended_timeframe, recommended_symbols, applicability, natural_language_explanation, math, spec_template)` frozen dataclass with `to_dict()`.
- `TemplateCatalog(entries)` with `by_id`, `search`, `filter(family=)`, `to_payload`.
- `TemplateCatalogError(RuntimeError)`.
- `load_template_catalog(path) -> TemplateCatalog`.
- `_REQUIRED_KEYS = {"id", "name", "uses_indicators", "spec_template"}`.

The 12 entries follow the schema from the spec. Each entry's `spec_template` is a complete StrategySpec subset (no id/timestamps).

Tests: parse all 12 entries; by_id; search by name; filter by indicator; missing required field raises; spec_template can roundtrip through StrategySpec validation.

### Task G2: /api/templates/* routes + tests

**Files:**
- `backend/showme/server_routes/templates.py`
- Modify `backend/showme/server_routes/__init__.py` (insert `templates` between `strategies` and `veryfinder`)
- `backend/tests/test_templates_route.py`

Routes:
- `GET /api/templates` → list dict[entries]
- `GET /api/templates/{id}` → single entry or 404
- `POST /api/templates/{id}/instantiate` body `{name?: str, symbol?: str}` — creates StrategySpec from `spec_template` (overriding name/asset_filter.symbols), saves via StrategyStore, returns full saved spec

Tests: list, get-one, get-404, instantiate creates saved strategy with overriden name.

### Task G3: UI template-store + TMPL pane + registry

**Files:**
- `ui/src/lib/template-store.ts`
- `ui/src/lib/template-store.test.ts`
- `ui/src/functions/TMPL.tsx`
- `ui/src/functions/TMPL.test.tsx`
- Modify registry.tsx + registry.test.tsx (151→152 + NATIVE_ONLY += "TMPL")
- Modify Sidebar.tsx (TMPL added to TOOL_ITEMS after BOT)

template-store: `entries`, `selectedId`, `loadCatalog()`, `setSelected(id)`, `instantiate(id, name, symbol) -> Promise<StrategySpec>`.

TMPL pane:
- Left grid: cards with name + indicator chips + family.
- Right detail: NL explanation + collapsible math block + applicability + recommended timeframes/symbols + "Bu template'i kullan" button.
- Click "Use" → modal asking for strategy name + (optional) symbol override → POST /instantiate → success toast + (optionally) navigate to STRA.

### Task G4: Native rebuild + close-out

Verify PyInstaller bundles `templates.yml`; build sidecar+tauri; deploy; live curl `GET /api/templates` returns 12, `POST /instantiate` creates and persists; screenshot; memory `showme_subsystem_g.md`; `backend/SUBSYSTEM_G.md`.
