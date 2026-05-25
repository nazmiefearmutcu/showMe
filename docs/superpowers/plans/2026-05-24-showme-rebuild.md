# showMe Full Rebuild Implementation Plan

> **For agentic workers:** This is the master plan. Execution is wave-based. Phase 0 (Foundation + Audit) is mandatory before any Wave. Each Wave can dispatch parallel agents per family.

**Goal:** Replace fallback-first, template-driven showMe with a contract-first, manifest-driven, institutional-grade multi-asset workstation where every function is real, truthful, and deeply usable.

**Architecture:**
- **Single source of truth:** `FunctionManifest` (Python pydantic + TS types) drives backend handlers, frontend controls, tests, docs.
- **Provider adapter layer** with honest data-mode enum (`live_official | live_exchange | delayed_reference | modeled | cached_snapshot | provider_unavailable | not_configured`).
- **Local analytical core:** DuckDB + Polars for cache, snapshots, transcript index, research artifacts, fast transforms.
- **Chart grammar:** Lightweight Charts for time-series/candles/panes/overlays; bespoke renderers for heatmaps/surfaces/frontiers/curves.
- **Banned in production paths:** `FunctionStub`, `TemplateRenderer`, `design-export` panes. Quarantined to dev-only.
- **Semantic tests** prove each function does its named job, not just returns 200.

**Tech Stack:**
- Backend: FastAPI sidecar, pydantic v2, DuckDB, Polars, PyPortfolioOpt, Riskfolio-Lib, QuantLib, VectorBT, httpx
- Frontend: React + TS + Vite, Tauri shell, Lightweight Charts v5, Zustand
- Data: SEC EDGAR, FRED, TreasuryDirect, OpenFIGI, Binance WS, GDELT, yfinance, RSS
- ML: FinBERT (sentiment), CardiffNLP Twitter RoBERTa (social), Whisper large-v3 (transcripts)

---

## Phase 0 — Foundation (mandatory before any Wave)

### Task 1: Full function inventory + gap matrix (Audit)

**Files:**
- Create: `docs/rebuild/INVENTORY.md` — every function code with current vs intended state
- Create: `docs/rebuild/GAP_MATRIX.md` — per-code: production-fakery dependencies, missing controls, wrong chart grammar, hidden inputs, fake "ok" states
- Create: `docs/rebuild/PROVIDER_MATRIX.md` — per-code: declared provider chain, current implementation gap

**Method:** Dispatch one Explore agent per major family in parallel. Each reads handler + pane + tests and reports current state vs spec.

### Task 2: FunctionManifest contract (Backend)

**Files:**
- Create: `backend/showme/manifest/__init__.py`
- Create: `backend/showme/manifest/spec.py` — pydantic v2 models for `FunctionManifest`, `InputSpec`, `OutputContract`, `ChartGrammar`, `TableSchema`, `CardSchema`, `ProviderChain`, `DataMode`
- Create: `backend/showme/manifest/registry.py` — registers manifest per function code
- Create: `backend/showme/server_routes/manifest.py` — `GET /api/manifest` (all), `GET /api/manifest/{code}` (one)
- Modify: `backend/showme/server.py` to mount the manifest router

### Task 3: FunctionManifest contract (Frontend)

**Files:**
- Create: `ui/src/manifest/types.ts` — mirror of backend types, derived from `/api/manifest` schema
- Create: `ui/src/manifest/registry.ts` — caches manifest, exposes `useManifest(code)` hook
- Create: `ui/src/manifest/derive-controls.tsx` — function that takes `InputSpec[]` and returns rendered React controls
- Create: `ui/src/manifest/derive-renderers.tsx` — function that picks chart/table/card renderers by manifest grammar

### Task 4: Provider adapter layer

**Files:**
- Create: `backend/showme/providers/__init__.py`
- Create: `backend/showme/providers/base.py` — `ProviderAdapter` ABC: `capabilities()`, `auth_state()`, `quota_state()`, `last_latency_ms()`, `mode()` returning `DataMode`
- Create: `backend/showme/providers/sec_edgar.py` — EDGAR submissions/XBRL/CIK lookup (no API key)
- Create: `backend/showme/providers/fred.py` — FRED series/releases/observations/vintages (API key from env)
- Create: `backend/showme/providers/treasury_direct.py` — TreasuryDirect auctions
- Create: `backend/showme/providers/openfigi.py` — identifier mapping
- Create: `backend/showme/providers/binance.py` — WS streams + REST
- Create: `backend/showme/providers/gdelt.py` — DOC 2.0 search
- Create: `backend/showme/providers/yfinance_adapter.py` — equity/fundamentals fallback with delayed_reference mode
- Create: `backend/showme/providers/registry.py` — name→adapter map, fallback chain helper

### Task 5: Local analytical core

**Files:**
- Create: `backend/showme/analytical/__init__.py`
- Create: `backend/showme/analytical/duck.py` — single DuckDB connection (Application Support path), schema bootstrap
- Create: `backend/showme/analytical/frames.py` — Polars helpers: time-series resample, join_asof, rank, feature pipelines
- Create: `backend/showme/analytical/cache.py` — provider cache: write Parquet via Polars, read via DuckDB SQL, TTL aware

### Task 6: Ban-list + semantic tests scaffold

**Files:**
- Create: `tests/test_production_fakery_banned.py` — fails if any non-dev module imports `FunctionStub`, `TemplateRenderer`, or `design-export`
- Create: `tests/test_semantic_acceptance.py` — harness that loads manifest entries, calls `/api/fn/{code}`, asserts data-mode honesty (no `status=ok` with blank core fields), control-parity (every declared control resolvable), formula presence where declared
- Create: `tests/test_chart_grammar.py` — fails if a manifest-declared grammar `time_series_candles` returns row-index plot

### Task 7: Manifest-driven shell controls (Frontend)

**Files:**
- Create: `ui/src/shell/ManifestPane.tsx` — pane wrapper that derives everything from manifest entry
- Create: `ui/src/manifest/controls/SymbolPicker.tsx` — canonical identifier search with OpenFIGI-backed resolution, recent history
- Create: `ui/src/manifest/controls/BenchmarkPicker.tsx`
- Create: `ui/src/manifest/controls/DateRangePicker.tsx`
- Create: `ui/src/manifest/controls/HorizonControl.tsx`
- Create: `ui/src/manifest/controls/ScenarioControl.tsx`
- Create: `ui/src/manifest/controls/ProviderModeControl.tsx`
- Create: `ui/src/manifest/drawers/MethodologyDrawer.tsx`
- Create: `ui/src/manifest/drawers/FormulasDrawer.tsx`
- Create: `ui/src/manifest/drawers/SourcesDrawer.tsx`
- Create: `ui/src/manifest/drawers/FieldDictionaryDrawer.tsx`
- Create: `ui/src/manifest/header/PaneHeader.tsx` — code + title + mode pill + as-of + quick actions

---

## Phase 1 — Wave 1: Core domain rebuilds

Each function in Wave 1 follows the same pattern:
1. Write manifest entry first
2. Build backend handler that fills the manifest's `output_contract` truthfully (no synthetic fallbacks; degrade explicitly)
3. Build bespoke pane using `ManifestPane` derived controls + bespoke renderer for the domain
4. Write semantic test that proves the pane does its named job
5. Delete old FunctionStub/template path for this code

### Wave 1 — Market data core: GP, HP, DES, FA, WATCH, TOP, CN, QUOTE
### Wave 1 — Portfolio & risk: PORT, ACCT, CORR, PORT_OPT, BLAK
### Wave 1 — Macro & rates: ECO, ECST, WIRP, BTMM
### Wave 1 — Derivatives: GEX, IVOL, OMON, OVDV, HVT

---

## Phase 2+ — Remaining waves

Documented in `docs/rebuild/WAVES.md`. Each wave covers one family per the spec inventory.

---

## Acceptance

The rebuild is complete only when:
- Every current function code has a consciously rebuilt destination
- No production path imports `FunctionStub`/`TemplateRenderer`/`design-export`
- Every function has real visible controls for its key workflow
- Backend + frontend driven by one `FunctionManifest`
- All charts use correct domain grammar (no row-index plots)
- All provider modes labeled explicitly
- State-changing routes safely gated (paper-mode default, arming required)
- Semantic tests green
- Resulting app feels like a serious multi-asset operator's workstation
